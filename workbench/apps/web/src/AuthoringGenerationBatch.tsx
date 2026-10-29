import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { ApiResult } from "./api";
import type {
  AuthoringGenerationBatch as Batch,
  AuthoringGenerationBatchCapabilities,
  AuthoringGenerationBatchPage,
  AuthoringGenerationBatchReceipt,
  DraftView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useAssistantPolling } from "./useAssistantFeed";
import { AuthoringGenerationForm } from "./AuthoringGenerationForm";
import type { GenerationFormValue } from "./AuthoringGenerationForm";
import { AuthoringGenerationCandidate } from "./AuthoringGenerationCandidate";
import type { GenerationCandidateReview } from "./AuthoringGenerationCandidate";
import {
  currentGenerationAttempt,
  publishedGenerationAttempt,
  terminalGenerationAttempt,
  validateGenerationBatch,
  validateGenerationCapabilities,
  validateGenerationCommandDigest,
  validateGenerationPage,
  validateGenerationReceipt,
} from "./authoringGenerationProtocol";
import type {
  GenerationAttempt,
  GenerationSection,
} from "./authoringGenerationProtocol";
import {
  definitiveGenerationFailure,
  generationEtag,
  generationInteger,
  generationPath,
  generationText,
  readGenerationRecovery,
  storeGenerationRecovery,
  validGenerationCreate,
} from "./authoringGenerationRecovery";
import type {
  GenerationRecovery,
  PendingGeneration,
} from "./authoringGenerationRecovery";
import { generationAmountText } from "./authoringGenerationBudget";
import "./AuthoringGenerationBatch.css";

function checked<T>(read: () => T): { value?: T; error: unknown } {
  try {
    return { value: read(), error: null };
  } catch (error) {
    return { error };
  }
}
const batchState = {
  open: "待核对",
  applied: "已应用",
  rejected: "已关闭",
} as const;
const budgetState = {
  held: "已预留",
  sent: "已发送，待费用确认",
  unknown: "费用待核清",
  settled: "已结算",
  released: "已释放",
} as const;
function attemptLabel(
  attempt: GenerationAttempt,
  batch?: Batch,
  sectionId?: string,
) {
  if (
    attempt.publication_state === "published" &&
    batch?.state !== undefined &&
    batch.state !== "open"
  ) {
    return batch.resolution?.applied_section_ids.includes(sectionId ?? "")
      ? "已应用"
      : "未应用（已关闭）";
  }
  if (attempt.state === "succeeded") {
    if (attempt.publication_state === "pending") return "候选整理中";
    if (attempt.publication_state === "published") return "候选已就绪";
    if (attempt.publication_state === "stale") return "候选基准已变化";
    return "候选校验未通过";
  }
  return {
    queued: "等待执行",
    running: "正在编写",
    cancel_requested: "已请求取消",
    failed: "本次失败",
    cancelled: "本次已取消",
  }[attempt.state];
}
function settledBatch(batch: Batch) {
  return (
    !batch.budget.requires_reconciliation &&
    batch.sections.every((section) => {
      const attempt = currentGenerationAttempt(section);
      return (
        terminalGenerationAttempt(attempt) &&
        !(
          attempt.state === "succeeded" &&
          attempt.publication_state === "pending"
        ) &&
        !section.budget.requires_reconciliation &&
        !attempt.requires_reconciliation &&
        ["settled", "released"].includes(attempt.budget_state)
      );
    })
  );
}

type Props = {
  bidId: string;
  memberId: string;
  draft: DraftView;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onChanged: () => Promise<unknown>;
  onBusy: (busy: boolean) => void;
};
export function AuthoringGenerationBatch(props: Props) {
  return (
    <GenerationBatchPanel
      key={`${props.memberId}:${props.bidId}:${props.draft.id}`}
      {...props}
    />
  );
}

function GenerationBatchPanel({
  bidId,
  memberId,
  draft,
  disabled,
  prepare,
  onChanged,
  onBusy,
}: Props) {
  const draftId = draft.id;
  const scope = useMemo(
    () => ({ bidId, memberId, draftId }),
    [bidId, memberId, draftId],
  );
  const path = generationPath(scope);
  const interval = useAssistantPolling();
  const capabilities = useResource<AuthoringGenerationBatchCapabilities>(
    "/authoring/generation-batch-capabilities",
  );
  const capability = useMemo(
    () =>
      capabilities.data
        ? checked(() => validateGenerationCapabilities(capabilities.data))
        : { error: null },
    [capabilities.data],
  );
  const [initial] = useState(() =>
    checked(() => readGenerationRecovery(scope)),
  );
  const [record, setRecord] = useState<GenerationRecovery>(
    initial.value ?? { version: 1, scope, pending: null, lastBatchId: null },
  );
  const recordRef = useRef(record);
  const [opened, setOpened] = useState(false);
  const [batch, setBatch] = useState<Batch | null>(null);
  const batchRef = useRef(batch);
  const [result, setResult] = useState<AuthoringGenerationBatchReceipt | null>(
    null,
  );
  const resultRef = useRef(result);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [reviews, setReviews] = useState<
    Record<string, GenerationCandidateReview>
  >({});
  const [reason, setReason] = useState("");
  const [retryReasons, setRetryReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loadingBatch, setLoadingBatch] = useState(false);
  const [batchError, setBatchError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const history = useResource<AuthoringGenerationBatchPage>(
    showHistory ? path : null,
  );
  const [moreHistory, setMoreHistory] = useState<
    AuthoringGenerationBatchPage[]
  >([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const active = useRef(true);
  const working = useRef(false);
  const readTicket = useRef(0);
  const inFlight = useRef<{
    id: string;
    promise: Promise<Batch | null>;
  } | null>(null);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onBusy(busy || !!record.pending);
    return () => onBusy(false);
  }, [busy, record.pending, onBusy]);
  useEffect(() => {
    setSelected({});
    setReviews({});
    setReason("");
    setRetryReasons({});
  }, [record.lastBatchId]);

  const loadBatch = useCallback(
    (id: string): Promise<Batch | null> => {
      if (inFlight.current?.id === id) return inFlight.current.promise;
      const ticket = ++readTicket.current;
      setLoadingBatch(true);
      const promise = (async () => {
        try {
          const response = await api<Batch>(`${path}/${id}`);
          const value = validateGenerationBatch(response.data, scope, id);
          await validateGenerationCommandDigest(value.preparation, scope);
          if (value.resolution)
            await validateGenerationCommandDigest(
              value.resolution.command,
              scope,
            );
          if (
            response.etag !== value.etag ||
            (resultRef.current?.batch_id === id &&
              resultRef.current.batch_digest !== value.batch_digest)
          )
            throw new Error(
              "批次版本或摘要与已核验回执不同，请保留原请求并重新核对。",
            );
          if (active.current && readTicket.current === ticket) {
            batchRef.current = value;
            setBatch(value);
            setBatchError(null);
          }
          return value;
        } catch (failure) {
          if (active.current && readTicket.current === ticket)
            setBatchError(failure);
          return null;
        } finally {
          if (active.current && readTicket.current === ticket)
            setLoadingBatch(false);
          if (readTicket.current === ticket) inFlight.current = null;
        }
      })();
      inFlight.current = { id, promise };
      return promise;
    },
    [path, scope],
  );
  useEffect(() => {
    const id = record.lastBatchId;
    if (id) void loadBatch(id);
  }, [record.lastBatchId, loadBatch]);
  const current = batch?.batch_id === record.lastBatchId ? batch : null;
  const refreshNeeded =
    !!current &&
    (current.state === "open" ||
      current.budget.requires_reconciliation ||
      current.sections.some((section) => {
        const attempt = currentGenerationAttempt(section);
        return (
          !terminalGenerationAttempt(attempt) ||
          (attempt.state === "succeeded" &&
            attempt.publication_state === "pending")
        );
      }));
  useEffect(() => {
    const id = record.lastBatchId;
    if (!id) return;
    const refresh = () => void loadBatch(id);
    window.addEventListener("server-snapshot-change", refresh);
    const timer =
      interval && refreshNeeded ? window.setInterval(refresh, interval) : null;
    return () => {
      window.removeEventListener("server-snapshot-change", refresh);
      if (timer) window.clearInterval(timer);
    };
  }, [record.lastBatchId, refreshNeeded, interval, loadBatch]);

  const onReview = useCallback(
    (id: string, review: GenerationCandidateReview | null) => {
      setReviews((old) => {
        if (!review) {
          if (!(id in old)) return old;
          const next = { ...old };
          delete next[id];
          return next;
        }
        if (
          old[id]?.candidate === review.candidate &&
          old[id]?.ready === review.ready
        )
          return old;
        return { ...old, [id]: review };
      });
    },
    [],
  );
  const onSelect = useCallback(
    (id: string, actionId: string, value: boolean) => {
      setSelected((old) => {
        const next = { ...old };
        if (value) next[id] = actionId;
        else delete next[id];
        return next;
      });
    },
    [],
  );
  function persist(value: GenerationRecovery) {
    storeGenerationRecovery(value);
    recordRef.current = value;
    if (active.current) setRecord(value);
  }
  const checkedHistory = useMemo(
    () =>
      checked(() =>
        [history.data, ...moreHistory]
          .filter((page) => page !== undefined)
          .map((page) => validateGenerationPage(page, scope)),
      ),
    [history.data, moreHistory, scope],
  );
  const historyRows = [
    ...new Map(
      (checkedHistory.value ?? [])
        .flatMap((page) => page.items)
        .map((item) => [item.batch_id, item]),
    ).values(),
  ];
  const lastHistory = checkedHistory.value?.at(-1);
  const pending = !!record.pending;
  const stale = !!current && current.base_draft_revision !== draft.revision;
  const locked = disabled || busy || pending || !!initial.error;
  const selectedSections =
    current?.sections.filter((section) => {
      const attempt = currentGenerationAttempt(section),
        review = reviews[section.section_id];
      return (
        selected[section.section_id] === attempt.action_id &&
        review?.ready &&
        review.candidate.action_id === attempt.action_id &&
        review.candidate.job_id === attempt.job_id &&
        review.candidate.attempt === attempt.attempt &&
        review.candidate.batch_id === current.batch_id &&
        review.candidate.candidate_digest === attempt.candidate_digest &&
        review.candidate.state === "pending" &&
        Date.parse(review.candidate.expires_at) > Date.now()
      );
    }) ?? [];
  const allSelectedReady =
    Object.keys(selected).length > 0 &&
    selectedSections.length === Object.keys(selected).length;
  const canApply =
    !!current &&
    current.state === "open" &&
    !stale &&
    !batchError &&
    settledBatch(current) &&
    allSelectedReady &&
    generationText(reason.trim());

  async function exactHead(expected?: Batch) {
    const head = await prepare();
    if (!head || !active.current) return null;
    if (
      head.data.id !== draftId ||
      head.data.bid_id !== bidId ||
      !generationEtag(head.etag) ||
      !generationInteger(head.data.revision, 1) ||
      !Array.isArray(head.data.sections)
    )
      throw new Error("无法核对保存后的草稿身份和修订，未发起新批次操作。");
    if (
      expected &&
      (head.data.revision !== expected.base_draft_revision ||
        head.etag !== expected.base_draft_etag)
    )
      throw new Error(
        "保存后的草稿已偏离本批冻结基准。原候选和选择仍保留，请以当前修订建立新批次并重新核对。",
      );
    return head;
  }

  type Action =
    | { kind: "create"; value: GenerationFormValue }
    | { kind: "retry"; section: GenerationSection }
    | { kind: "apply" | "reject" | "recover" };
  async function act(action: Action) {
    if (
      working.current ||
      initial.error ||
      (action.kind !== "recover" && recordRef.current.pending) ||
      (action.kind !== "recover" && disabled)
    )
      return;
    working.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    let responseReceived = false;
    let sent = false;
    try {
      let request: PendingGeneration | null =
        action.kind === "recover" ? recordRef.current.pending : null;
      const expected =
        batchRef.current?.batch_id === recordRef.current.lastBatchId
          ? batchRef.current
          : null;
      if (!request) {
        if (action.kind === "recover") return;
        if (action.kind === "create") {
          if (
            !capability.value?.enabled ||
            capabilities.error ||
            !capability.value.price ||
            Date.parse(capability.value.price.valid_until) <= Date.now() ||
            capability.value.price.price_version_id !==
              action.value.price_version_id
          )
            return;
          const head = await exactHead();
          if (!head || !active.current) return;
          const body = {
            ...action.value,
            base_draft_revision: head.data.revision,
            sections: action.value.sections.map((section) => {
              const saved = head.data.sections.find(
                (item) => item.id === section.section_id,
              );
              if (!saved || !generationInteger(saved.revision, 1))
                throw new Error(
                  "选中的章节在保存后已不可用。原目标和份额仍保留，请核对当前目录。",
                );
              return { ...section, base_section_revision: saved.revision };
            }),
          };
          if (!validGenerationCreate(body))
            throw new Error("章节、来源或预算输入无法核验，未创建付费任务。");
          request = {
            kind: "create",
            key: crypto.randomUUID(),
            etag: head.etag!,
            baseDraftRevision: head.data.revision,
            body,
          };
        } else {
          if (!expected || expected.state !== "open" || batchError) return;
          if (action.kind === "retry") {
            const section = expected.sections.find(
              (item) => item.section_id === action.section.section_id,
            );
            if (!section) return;
            const attempt = currentGenerationAttempt(section);
            const retryReason = retryReasons[section.section_id]?.trim();
            if (
              !capability.value?.enabled ||
              capabilities.error ||
              !attempt.retry_allowed ||
              !generationText(retryReason) ||
              stale
            )
              return;
            if (!(await exactHead(expected)) || !active.current) return;
            request = {
              kind: "retry",
              batchId: expected.batch_id,
              key: crypto.randomUUID(),
              etag: expected.base_draft_etag,
              baseDraftRevision: expected.base_draft_revision,
              body: {
                batch_digest: expected.batch_digest,
                section_id: section.section_id,
                previous_attempt: attempt.attempt,
                previous_job_id: attempt.job_id,
                reason: retryReason,
              },
            };
          } else {
            if (
              !generationText(reason.trim()) ||
              (action.kind === "apply" && !canApply)
            )
              return;
            if (
              action.kind === "apply" &&
              (!(await exactHead(expected)) || !active.current)
            )
              return;
            if (
              action.kind === "apply" &&
              selectedSections.some((section) => {
                const candidate = reviews[section.section_id]?.candidate;
                return (
                  !candidate ||
                  candidate.state !== "pending" ||
                  Date.parse(candidate.expires_at) <= Date.now()
                );
              })
            )
              throw new Error(
                "候选在保存当前编辑期间已过期。原稿和选择保留，请重新读取候选状态。",
              );
            request = {
              kind: "resolve",
              batchId: expected.batch_id,
              key: crypto.randomUUID(),
              etag: expected.base_draft_etag,
              baseDraftRevision: expected.base_draft_revision,
              body: {
                decision: action.kind,
                batch_digest: expected.batch_digest,
                reason: reason.trim(),
                selections:
                  action.kind === "reject"
                    ? []
                    : selectedSections.map((section) => {
                        const attempt = currentGenerationAttempt(section);
                        return {
                          section_id: section.section_id,
                          attempt: attempt.attempt,
                          job_id: attempt.job_id,
                          action_id: attempt.action_id!,
                          candidate_digest: attempt.candidate_digest!,
                        };
                      }),
              },
            };
          }
        }
        persist({
          ...recordRef.current,
          pending: request,
          ...(request.kind === "create"
            ? {}
            : { lastBatchId: request.batchId }),
        });
      }
      if (!active.current) return;
      sent = true;
      const response = await api<AuthoringGenerationBatchReceipt>(
        request.kind === "create"
          ? path
          : `${path}/${request.batchId}/${request.kind}`,
        {
          method: "POST",
          body: request.body,
          etag: request.etag,
          key: request.key,
        },
      );
      responseReceived = true;
      const receipt = validateGenerationReceipt(
        response.data,
        scope,
        request,
        request.kind !== "create" && expected?.batch_id === request.batchId
          ? expected
          : undefined,
      );
      await validateGenerationCommandDigest(receipt.command, scope);
      if (!active.current) return;
      persist({
        ...recordRef.current,
        pending: null,
        lastBatchId: receipt.batch_id,
      });
      resultRef.current = receipt;
      setResult(receipt);
      setNotice(
        receipt.kind === "created"
          ? "批次已受理。以下任务依照明确份额执行，当前草稿尚未修改。"
          : receipt.kind === "retried"
            ? "新尝试已明确受理，费用继续累计在本章原额度内。"
            : receipt.kind === "applied"
              ? "所选章节已一次应用，本批已结束。未选章节保持原样。"
              : "批次已关闭；运行中的任务已请求取消，已有费用和待核清敞口仍保留。",
      );
      if (receipt.kind === "applied") await onChanged();
      // A metadata GET started before the write must not stand in for its fresh receipt read.
      readTicket.current++;
      inFlight.current = null;
      await loadBatch(receipt.batch_id);
      if (active.current && showHistory) {
        setMoreHistory([]);
        await history.reload();
      }
    } catch (failure) {
      if (!active.current) return;
      setError(failure);
      if (
        sent &&
        !responseReceived &&
        recordRef.current.pending &&
        definitiveGenerationFailure(failure)
      ) {
        try {
          persist({ ...recordRef.current, pending: null });
          if (
            failure instanceof ApiError &&
            failure.code.endsWith("PRICE_CHANGED")
          )
            await capabilities.reload();
          const id = recordRef.current.lastBatchId;
          if (id) await loadBatch(id);
        } catch (storageFailure) {
          setError(storageFailure);
        }
      }
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }

  function chooseBatch(id: string) {
    if (busy || pending) return;
    setError(null);
    setNotice("");
    try {
      if (initial.error) setRecord((old) => ({ ...old, lastBatchId: id }));
      else persist({ ...recordRef.current, lastBatchId: id });
      if (record.lastBatchId === id) void loadBatch(id);
    } catch (failure) {
      setError(failure);
    }
  }
  async function nextHistory() {
    if (!lastHistory?.next_cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const { data } = await api<AuthoringGenerationBatchPage>(
        `${path}?cursor=${encodeURIComponent(lastHistory.next_cursor)}`,
      );
      const page = validateGenerationPage(data, scope);
      if (page.next_cursor === lastHistory.next_cursor)
        throw new Error("历史分页游标未前进，请重新读取记录。");
      if (active.current) setMoreHistory((old) => [...old, page]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setLoadingMore(false);
    }
  }
  const resolved =
    current?.resolution ??
    (result?.batch_id === record.lastBatchId ? result : null);

  return (
    <section
      className="panel generation-panel"
      aria-label="多章节批量编写"
      aria-busy={busy}
    >
      <div className="section-heading">
        <div>
          <h2>多章节批量编写</h2>
          <p className="muted">
            按章确定目标、来源与累计预算，核对完整前后稿后，一次应用明确选择的成功章节。
          </p>
        </div>
        <Badge>明确预算 · 人工确认</Badge>
      </div>
      <ResourceState
        {...capabilities}
        hasData={!!capability.value}
        onRetry={() => void capabilities.reload()}
      />
      <ErrorNotice error={initial.error ?? capability.error ?? error} />
      {capability.value && !capability.value.enabled && (
        <p className="notice warning">
          {capability.value.unavailable_reason?.message ??
            "当前环境尚未开放多章节模型编写。已有批次与回执仍可读取。"}
        </p>
      )}
      {record.pending && (
        <div className="notice warning generation-recovery" role="status">
          <p>
            上次
            {record.pending.kind === "create"
              ? "创建批次"
              : record.pending.kind === "retry"
                ? "明确重试"
                : record.pending.body.decision === "apply"
                  ? "应用章节"
                  : "关闭批次"}
            的回执尚未核验。原请求内容、原键和原保存条件已保留，先恢复该请求再继续。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !!initial.error}
            onClick={() => void act({ kind: "recover" })}
          >
            {busy ? "正在恢复原批次请求…" : "恢复原批次请求结果"}
          </button>
          <p className="small-note">
            恢复使用原请求，不创建新的模型尝试。即使价格或当前草稿已变化，也不会悄悄替换原保存条件。
          </p>
        </div>
      )}
      {notice && (
        <p className="inline-success" role="status">
          {notice}
        </p>
      )}
      {resolved && (
        <div
          className="generation-receipt"
          role="region"
          aria-label="批次操作回执"
        >
          <strong>
            {resolved.kind === "applied"
              ? "已确认应用"
              : resolved.kind === "rejected"
                ? "已确认关闭"
                : resolved.kind === "retried"
                  ? "已确认新尝试"
                  : "已确认创建批次"}
          </strong>
          <p>
            {resolved.kind === "applied"
              ? `草稿修订 ${resolved.draft_revision}；本次应用 ${resolved.applied_section_ids.length} 章，未选 ${resolved.unselected_section_ids.length} 章保持原样。`
              : resolved.kind === "rejected"
                ? "未应用章节；取消状态和费用核清记录继续保留。"
                : `本次创建 ${resolved.created_job_ids.length} 个任务，尚未改写草稿。`}
          </p>
          <small>
            批次 {resolved.batch_id} ·{" "}
            {new Date(resolved.recorded_at).toLocaleString("zh-CN")}
          </small>
        </div>
      )}
      <div className="generation-toolbar">
        <button
          type="button"
          className="button secondary"
          aria-expanded={opened}
          onClick={() => setOpened((value) => !value)}
        >
          {opened ? "收起新批次设置" : "设置新的多章编写批次"}
        </button>
        <button
          type="button"
          className="text-button"
          aria-expanded={showHistory}
          onClick={() => setShowHistory((value) => !value)}
        >
          {showHistory ? "收起批次历史" : "读取批次历史"}
        </button>
      </div>
      {opened && capability.value && (
        <AuthoringGenerationForm
          bidId={bidId}
          draft={draft}
          capabilities={capability.value}
          disabled={locked || !!capabilities.error || !capability.value.enabled}
          initial={
            initial.value?.pending?.kind === "create"
              ? initial.value.pending.body
              : undefined
          }
          onCreate={(value) => act({ kind: "create", value })}
        />
      )}
      {showHistory && (
        <div className="generation-history" aria-label="批次历史">
          <p className="small-note">历史读取与候选预览不启动模型调用。</p>
          <ResourceState
            {...history}
            hasData={!!checkedHistory.value?.length}
            onRetry={() => {
              setMoreHistory([]);
              void history.reload();
            }}
          />
          <ErrorNotice error={checkedHistory.error} />
          {historyRows.map((item) => (
            <div className="generation-history-row" key={item.batch_id}>
              <div>
                <strong>
                  草稿修订 {item.base_draft_revision} · {item.section_count} 章
                </strong>
                <small>
                  {new Date(item.created_at).toLocaleString("zh-CN")} ·{" "}
                  {batchState[item.state]} · 已计费{" "}
                  {generationAmountText(item.budget.charged_minor)}{" "}
                  {item.budget.currency}
                </small>
              </div>
              <button
                type="button"
                className="text-button"
                disabled={busy || pending}
                onClick={() => chooseBatch(item.batch_id)}
              >
                查看批次 {item.batch_id.slice(-8)}
              </button>
            </div>
          ))}
          {history.data && !historyRows.length && !checkedHistory.error && (
            <p className="small-empty">尚无批次记录。</p>
          )}
          {lastHistory?.has_more && (
            <button
              type="button"
              className="text-button"
              disabled={loadingMore}
              onClick={() => void nextHistory()}
            >
              读取更早批次
            </button>
          )}
        </div>
      )}
      {record.lastBatchId && (
        <ResourceState
          loading={loadingBatch}
          error={batchError}
          hasData={!!current}
          onRetry={() => void loadBatch(record.lastBatchId!)}
        />
      )}
      {current && (
        <div className="generation-current" aria-label="当前批次">
          <div className="section-heading">
            <div>
              <h3>
                本批 {current.section_count} 章 · {batchState[current.state]}
              </h3>
              <p className="small-note">
                冻结草稿修订 {current.base_draft_revision} ·{" "}
                {current.price.model} ·{" "}
                {current.created_by === memberId ? "本人发起" : "项目成员发起"}
              </p>
            </div>
            <button
              type="button"
              className="text-button"
              disabled={loadingBatch}
              onClick={() => void loadBatch(current.batch_id)}
            >
              刷新批次状态
            </button>
          </div>
          <BudgetSummary budget={current.budget} label="本批费用" />
          {current.budget.requires_reconciliation && (
            <p className="notice warning">
              本批仍有费用尚未核清，不能发起新尝试或部分应用。请保留原批次，等实际调用与结算记录核对。
            </p>
          )}
          {current.budget.over_limit && (
            <p className="notice warning">
              实际费用敞口已超出本地额度。记录按真实账单保留，不能把预留估算当作供应方硬性扣费上限。
            </p>
          )}
          {stale && current.state === "open" && (
            <p className="notice warning">
              当前草稿已是修订 {draft.revision}
              ，与本批基准不同。原候选仍可核对；本批不会自动合并到新修订。
            </p>
          )}
          <p className="small-note">
            每章额度覆盖该章所有尝试。成功候选需人工勾选；失败后不会自动重试。应用所选章节会结束本批，未选章节需基于当时草稿另建批次。
          </p>
          <div className="generation-section-results">
            {current.sections.map((section) => {
              const attempt = currentGenerationAttempt(section);
              return (
                <article
                  className="generation-section-result"
                  key={section.section_id}
                  aria-label={`${section.title}的编写状态`}
                >
                  <div className="section-heading">
                    <div>
                      <h4>{section.title}</h4>
                      <p className="small-note">
                        章节修订 {section.base_section_revision} · 第{" "}
                        {attempt.attempt} 次尝试 · 输出上限 {section.max_tokens}{" "}
                        token
                      </p>
                    </div>
                    <Badge>
                      {attemptLabel(attempt, current, section.section_id)}
                    </Badge>
                  </div>
                  <p className="generation-instruction">
                    {section.instruction}
                  </p>
                  <BudgetSummary
                    budget={section.budget}
                    label={`${section.title}累计费用`}
                  />
                  <p className="small-note">
                    本次费用状态：{budgetState[attempt.budget_state]}；预计预留{" "}
                    {generationAmountText(attempt.reserved_minor)}{" "}
                    {current.price.currency}；已确认费用{" "}
                    {attempt.charged_minor === null
                      ? "尚未确认"
                      : `${generationAmountText(attempt.charged_minor)} ${current.price.currency}`}
                    。
                  </p>
                  {attempt.error_code && (
                    <p className="notice warning">
                      本次未完成原因：{attempt.error_code}
                    </p>
                  )}
                  {attempt.state === "succeeded" &&
                    attempt.publication_state === "pending" && (
                      <p className="notice neutral" role="status">
                        模型任务已完成，候选整理中。将继续刷新；整理完成前不能应用或发起新尝试。
                      </p>
                    )}
                  {attempt.requires_reconciliation && (
                    <p className="notice warning">
                      此尝试的调用或费用状态未核清。原任务保留，不发起第二次调用。
                    </p>
                  )}
                  {publishedGenerationAttempt(attempt) && (
                    <AuthoringGenerationCandidate
                      key={`${current.batch_id}:${section.section_id}:${attempt.attempt}:${attempt.action_id}`}
                      scope={scope}
                      batch={current}
                      section={section}
                      disabled={
                        locked ||
                        !!batchError ||
                        stale ||
                        current.state !== "open"
                      }
                      selected={
                        selected[section.section_id] === attempt.action_id
                      }
                      onSelect={onSelect}
                      onReview={onReview}
                    />
                  )}
                  {current.state === "open" &&
                    terminalGenerationAttempt(attempt) &&
                    !publishedGenerationAttempt(attempt) &&
                    !(
                      attempt.state === "succeeded" &&
                      attempt.publication_state === "pending"
                    ) && (
                      <div className="generation-retry">
                        {attempt.retry_blocked_reason && (
                          <p className="small-note">
                            当前不能重试：{attempt.retry_blocked_reason.message}
                          </p>
                        )}
                        {attempt.retry_allowed && (
                          <>
                            <label>
                              明确重试本章的理由
                              <input
                                aria-label={`${section.title}的重试理由`}
                                value={retryReasons[section.section_id] ?? ""}
                                maxLength={1000}
                                disabled={
                                  locked || stale || !capability.value?.enabled
                                }
                                onChange={(event) =>
                                  setRetryReasons((old) => ({
                                    ...old,
                                    [section.section_id]: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <button
                              type="button"
                              className="button secondary"
                              disabled={
                                locked ||
                                stale ||
                                !!batchError ||
                                !capability.value?.enabled ||
                                !generationText(
                                  retryReasons[section.section_id]?.trim(),
                                )
                              }
                              onClick={() =>
                                void act({ kind: "retry", section })
                              }
                            >
                              明确重试{section.title}（继续占用本章额度）
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  <details className="generation-attempts">
                    <summary>
                      全部尝试记录 · {section.attempts.length} 次
                    </summary>
                    <ol>
                      {section.attempts.map((item) => (
                        <li key={item.job_id}>
                          第 {item.attempt} 次：
                          {attemptLabel(
                            item,
                            current,
                            section.section_id,
                          )} · {budgetState[item.budget_state]} · 已计费{" "}
                          {item.charged_minor === null
                            ? "待核清"
                            : `${generationAmountText(item.charged_minor)} ${current.price.currency}`}
                          <small>
                            任务 {item.job_id}
                            {item.error_code ? ` · ${item.error_code}` : ""}
                          </small>
                        </li>
                      ))}
                    </ol>
                  </details>
                </article>
              );
            })}
          </div>
          {current.state === "open" && (
            <div className="generation-resolve">
              {!settledBatch(current) && (
                <p className="notice neutral">
                  等待本批所有章节结束、候选整理完成且费用核清后，才能一次应用成功章节。关闭批次可以请求取消运行任务，已有费用记录继续保留。
                </p>
              )}
              <p>
                已明确选择 {selectedSections.length} / {current.section_count}{" "}
                章。未选章节保持原样。
              </p>
              <label>
                本次应用或关闭理由
                <input
                  aria-label="本次应用或关闭理由"
                  value={reason}
                  maxLength={1000}
                  disabled={locked}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <div className="generation-toolbar">
                <button
                  type="button"
                  className="button primary"
                  disabled={locked || !canApply}
                  onClick={() => void act({ kind: "apply" })}
                >
                  一次应用已核对的 {selectedSections.length} 章并结束本批
                </button>
                <button
                  type="button"
                  className="button secondary"
                  disabled={
                    locked || !!batchError || !generationText(reason.trim())
                  }
                  onClick={() => void act({ kind: "reject" })}
                >
                  关闭本批并请求取消未完成任务
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function BudgetSummary({
  budget,
  label,
}: {
  budget: Batch["budget"];
  label: string;
}) {
  return (
    <dl className="generation-budget-summary" aria-label={label}>
      <div>
        <dt>累计额度</dt>
        <dd>
          {generationAmountText(budget.limit_minor)}{" "}
          <small>{budget.currency}</small>
        </dd>
      </div>
      <div>
        <dt>已计费</dt>
        <dd>{generationAmountText(budget.charged_minor)}</dd>
      </div>
      <div>
        <dt>仍预留</dt>
        <dd>{generationAmountText(budget.reserved_minor)}</dd>
      </div>
      <div>
        <dt>当前费用敞口</dt>
        <dd>{generationAmountText(budget.exposure_minor)}</dd>
      </div>
      <div>
        <dt>可用余额</dt>
        <dd>{generationAmountText(budget.remaining_minor)}</dd>
      </div>
    </dl>
  );
}
