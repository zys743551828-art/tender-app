import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, sizeLabel } from "./api";
import type { ApiResult } from "./api";
import type {
  AuthoringWordImportCandidate,
  AuthoringWordImportCapabilities,
  AuthoringWordImportPage,
  AuthoringWordImportResult,
  DraftView,
  WordOriginalPage,
  WordOriginalView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { executionId, executionSha } from "./executionInputValidation";
import {
  definitiveWordImportFailure,
  readWordImportRecovery,
  storeWordImportRecovery,
  wordImportPath,
  wordImportReasonValid,
} from "./authoringWordImportRecovery";
import type {
  PendingWordImport,
  WordImportRecovery,
} from "./authoringWordImportRecovery";
import {
  validateWordImportCandidate,
  validateWordImportCapabilities,
  validateWordImportPage,
  validateWordImportResult,
  wordImportSectionOrder,
} from "./authoringWordImportProtocol";
import { WordImportRichPreview } from "./WordImportRichPreview";
import type { WordImportImageState } from "./WordImportRichPreview";
import "./AuthoringWordImport.css";

const stateLabel = {
  ready: "待确认",
  blocked: "存在阻断",
  applied: "已追加",
  rejected: "已拒绝",
} as const;
function originalValid(value: WordOriginalView, bidId: string) {
  return (
    value?.bid_id === bidId &&
    executionId(value.id) &&
    value.original_saved === true &&
    executionSha(value.source_sha256) &&
    Number.isSafeInteger(value.byte_size) &&
    value.byte_size > 0 &&
    typeof value.original_name === "string"
  );
}
function checked<T>(read: () => T): { value: T | undefined; error: unknown } {
  try {
    return { value: read(), error: null };
  } catch (error) {
    return { value: undefined, error };
  }
}

export function AuthoringWordImport({
  bidId,
  memberId,
  draftId,
  draftRevision,
  disabled,
  prepare,
  onChanged,
  onBusy,
  onPackages,
}: {
  bidId: string;
  memberId: string;
  draftId: string;
  draftRevision: number;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onChanged: () => Promise<unknown>;
  onBusy: (busy: boolean) => void;
  onPackages?: () => void;
}) {
  const scope = useMemo(
    () => ({ bidId, memberId, draftId }),
    [bidId, memberId, draftId],
  );
  const path = wordImportPath(scope);
  const capabilities = useResource<AuthoringWordImportCapabilities>(
    "/authoring/word-import-capabilities",
  );
  const capability = useMemo(
    () =>
      capabilities.data
        ? checked(() => validateWordImportCapabilities(capabilities.data))
        : { value: undefined, error: null },
    [capabilities.data],
  );
  const [opened, setOpened] = useState(false);
  const originals = useResource<WordOriginalPage>(
    opened ? `/bids/${bidId}/word-originals` : null,
  );
  const [moreOriginals, setMoreOriginals] = useState<WordOriginalPage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [sourceId, setSourceId] = useState("");
  const [reason, setReason] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [initial] = useState(() =>
    checked(() => readWordImportRecovery(scope)),
  );
  const [record, setRecord] = useState<WordImportRecovery>(
    initial.value ?? {
      version: 1,
      scope,
      pending: null,
      lastCandidateId: null,
    },
  );
  const recordRef = useRef(record);
  const [candidate, setCandidate] =
    useState<AuthoringWordImportCandidate | null>(null);
  const candidateRef = useRef(candidate);
  const [result, setResult] = useState<AuthoringWordImportResult | null>(null);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [imageStates, setImageStates] = useState<
    Record<string, WordImportImageState>
  >({});
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const active = useRef(true);
  const reading = useRef(0);
  const [loadingCandidate, setLoadingCandidate] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const history = useResource<AuthoringWordImportPage>(
    showHistory ? path : null,
  );
  const [moreHistory, setMoreHistory] = useState<AuthoringWordImportPage[]>([]);
  const [mappingPage, setMappingPage] = useState(0);
  const [showMapping, setShowMapping] = useState(false);
  const candidateId = candidate?.candidate_id;
  const onImageStatus = useCallback(
    (key: string, state: WordImportImageState) => {
      setImageStates((old) =>
        old[key] === state ? old : { ...old, [key]: state },
      );
    },
    [],
  );

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
    setAcknowledged([]);
    setDecisionReason("");
    setImageStates({});
    setMappingPage(0);
    setShowMapping(false);
  }, [candidateId]);

  const acceptCandidate = useCallback((value: AuthoringWordImportCandidate) => {
    candidateRef.current = value;
    setCandidate(value);
    if (value.resolution) setResult(value.resolution);
  }, []);
  const loadCandidate = useCallback(
    async (id: string) => {
      const ticket = ++reading.current;
      setLoadingCandidate(true);
      try {
        const response = await api<AuthoringWordImportCandidate>(
          `${path}/${id}`,
        );
        const value = validateWordImportCandidate(response.data, scope, id);
        if (active.current && reading.current === ticket)
          acceptCandidate(value);
        return value;
      } catch (failure) {
        if (active.current && reading.current === ticket) setError(failure);
        return null;
      } finally {
        if (active.current && reading.current === ticket)
          setLoadingCandidate(false);
      }
    },
    [path, scope, acceptCandidate],
  );
  useEffect(() => {
    const id = record.lastCandidateId;
    if (id && candidateRef.current?.candidate_id !== id) void loadCandidate(id);
  }, [record.lastCandidateId, loadCandidate]);

  function persist(value: WordImportRecovery) {
    storeWordImportRecovery(value);
    recordRef.current = value;
    if (active.current) setRecord(value);
  }
  const pages = [originals.data, ...moreOriginals].filter(
    (page): page is WordOriginalPage => !!page,
  );
  const originalsInvalid = pages.some(
    (page) =>
      !Array.isArray(page.items) ||
      page.items.some((item) => !originalValid(item, bidId)) ||
      typeof page.has_more !== "boolean" ||
      (page.has_more
        ? !executionId(page.next_after)
        : page.next_after !== null),
  );
  const sourceRows = originalsInvalid
    ? []
    : [
        ...new Map(
          pages.flatMap((page) => page.items).map((item) => [item.id, item]),
        ).values(),
      ];
  const source = sourceRows.find((item) => item.id === sourceId);
  const lastOriginals = moreOriginals.at(-1) ?? originals.data;
  const checkedHistory = useMemo(
    () =>
      checked(() =>
        [history.data, ...moreHistory]
          .filter((page) => page !== undefined)
          .map((page) => validateWordImportPage(page, scope)),
      ),
    [history.data, moreHistory, scope],
  );
  const historyRows = [
    ...new Map(
      (checkedHistory.value ?? [])
        .flatMap((page) => page.items)
        .map((item) => [item.candidate_id, item]),
    ).values(),
  ];
  const lastHistory = checkedHistory.value?.at(-1);
  const current =
    candidate?.candidate_id === record.lastCandidateId ? candidate : null;
  const pending = !!record.pending;
  const stale = !!current && current.base_draft_revision !== draftRevision;
  const warnings =
    current?.issues.filter((issue) => issue.severity === "warning") ?? [];
  const savedAcknowledgements =
    current?.resolution?.decision === "append"
      ? current.resolution.command.request.acknowledged_issue_ids
      : null;
  const displayedAcknowledgements = Array.isArray(savedAcknowledgements)
    ? savedAcknowledgements
    : acknowledged;
  const allAcknowledged = warnings.every((issue) =>
    acknowledged.includes(issue.id),
  );
  const allImagesReady =
    current?.images.every((item) => imageStates[item.key] === "ready") ?? false;
  const canAppend =
    !!current?.can_apply &&
    !stale &&
    allAcknowledged &&
    allImagesReady &&
    wordImportReasonValid(decisionReason.trim());

  async function act(action: "prepare" | "append" | "reject" | "retry") {
    if (
      working.current ||
      initial.error ||
      (action !== "retry" && recordRef.current.pending) ||
      (action !== "retry" && action !== "reject" && disabled)
    )
      return;
    working.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    let responseReceived = false;
    try {
      let request: PendingWordImport | null =
        action === "retry" ? recordRef.current.pending : null;
      let expected = candidateRef.current;
      if (!request) {
        if (action === "retry") return;
        if (action === "prepare") {
          if (
            !capability.value?.enabled ||
            !source ||
            !wordImportReasonValid(reason.trim())
          )
            return;
          const head = await prepare();
          if (!head || !active.current) return;
          if (
            head.data.id !== draftId ||
            head.data.bid_id !== bidId ||
            !head.etag ||
            !Number.isSafeInteger(head.data.revision) ||
            head.data.revision < 1
          )
            throw new Error("无法核对当前草稿的保存确认，未创建导入候选。");
          request = {
            kind: "prepare",
            key: crypto.randomUUID(),
            etag: head.etag,
            body: {
              source_document_version_id: source.id,
              source_digest: source.source_sha256,
              source_byte_size: source.byte_size,
              base_draft_revision: head.data.revision,
              method_digest: capability.value.method_digest,
              reason: reason.trim(),
            },
          };
        } else {
          if (
            !expected ||
            !["ready", "blocked"].includes(expected.state) ||
            !wordImportReasonValid(decisionReason.trim())
          )
            return;
          if (action === "append") {
            if (!canAppend) return;
            const head = await prepare();
            if (!head || !active.current) return;
            if (
              head.data.id !== draftId ||
              head.data.bid_id !== bidId ||
              head.data.revision !== expected.base_draft_revision ||
              head.etag !== expected.base_draft_etag
            )
              throw new Error(
                "保存后的草稿修订与候选基准不同。候选已保留，请按当前草稿重新生成并核对候选。",
              );
          }
          request = {
            kind: "resolve",
            candidateId: expected.candidate_id,
            key: crypto.randomUUID(),
            etag: expected.base_draft_etag,
            body: {
              decision: action,
              candidate_digest: expected.candidate_digest,
              acknowledged_issue_ids:
                action === "append" ? [...acknowledged].sort() : [],
              reason: decisionReason.trim(),
            },
          };
        }
        persist({ ...recordRef.current, pending: request });
      }
      if (!active.current) return;
      if (request.kind === "prepare") {
        const response = await api<AuthoringWordImportCandidate>(path, {
          method: "POST",
          body: request.body,
          etag: request.etag,
          key: request.key,
        });
        responseReceived = true;
        const value = validateWordImportCandidate(
          response.data,
          scope,
          undefined,
          request,
        );
        if (!active.current) return;
        acceptCandidate(value);
        persist({
          ...recordRef.current,
          pending: null,
          lastCandidateId: value.candidate_id,
        });
        setResult(value.resolution);
        setNotice(
          "导入候选已保存，当前草稿尚未改变。请核对结构、图片和全部转换说明。",
        );
      } else {
        if (expected?.candidate_id !== request.candidateId)
          expected = await loadCandidate(request.candidateId);
        if (!expected || !active.current) return;
        const response = await api<AuthoringWordImportResult>(
          `${path}/${request.candidateId}/resolve`,
          {
            method: "POST",
            body: request.body,
            etag: request.etag,
            key: request.key,
          },
        );
        responseReceived = true;
        const value = validateWordImportResult(
          response.data,
          scope,
          expected,
          request,
        );
        if (!active.current) return;
        persist({
          ...recordRef.current,
          pending: null,
          lastCandidateId: request.candidateId,
        });
        setResult(value);
        acceptCandidate({
          ...expected,
          state: value.state,
          can_apply: false,
          resolution: value,
        });
        if (value.decision === "append") await onChanged();
      }
      if (active.current && showHistory) {
        setMoreHistory([]);
        await history.reload();
      }
    } catch (failure) {
      if (!active.current) return;
      setError(failure);
      if (
        !responseReceived &&
        recordRef.current.pending &&
        definitiveWordImportFailure(failure)
      ) {
        try {
          persist({ ...recordRef.current, pending: null });
          if (failure instanceof ApiError) {
            if (failure.code === "AUTHORING_WORD_IMPORT_METHOD_CHANGED")
              await capabilities.reload();
            if (
              failure.code === "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED" &&
              recordRef.current.lastCandidateId
            ) {
              await loadCandidate(recordRef.current.lastCandidateId);
              await onChanged();
            }
          }
        } catch (storageFailure) {
          setError(storageFailure);
        }
      }
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function nextOriginals() {
    if (!lastOriginals?.next_after || loadingMore) return;
    setLoadingMore(true);
    try {
      const { data } = await api<WordOriginalPage>(
        `/bids/${bidId}/word-originals?after=${encodeURIComponent(lastOriginals.next_after)}`,
      );
      if (active.current) setMoreOriginals((old) => [...old, data]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setLoadingMore(false);
    }
  }
  async function nextHistory() {
    if (!lastHistory?.next_cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const { data } = await api<AuthoringWordImportPage>(
        `${path}?cursor=${encodeURIComponent(lastHistory.next_cursor)}`,
      );
      const page = validateWordImportPage(data, scope);
      if (active.current) setMoreHistory((old) => [...old, page]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setLoadingMore(false);
    }
  }
  function chooseCandidate(id: string) {
    if (busy || pending) return;
    try {
      setError(null);
      setResult(null);
      setNotice("");
      if (initial.error) setRecord((old) => ({ ...old, lastCandidateId: id }));
      else persist({ ...recordRef.current, lastCandidateId: id });
      if (record.lastCandidateId === id) void loadCandidate(id);
    } catch (failure) {
      setError(failure);
    }
  }
  const resolved =
    current?.resolution ??
    (result?.candidate_id === record.lastCandidateId ? result : null);
  return (
    <section
      className="panel word-import-panel"
      aria-label="从Word导入章节"
      aria-busy={busy || loadingCandidate}
    >
      <div className="section-heading">
        <div>
          <h2>从Word导入章节</h2>
          <p className="muted">
            选择已保存的确切原件，先核对章节、表格、图片与转换损失，再明确追加到当前草稿。
          </p>
        </div>
        <Badge>只追加新章节</Badge>
      </div>
      <ResourceState
        {...capabilities}
        hasData={!!capability.value}
        onRetry={() => void capabilities.reload()}
      />
      <ErrorNotice error={initial.error ?? capability.error ?? error} />
      {capability.value && (
        <>
          {!capability.value.enabled && (
            <p className="notice warning">
              {capability.value.unavailable_reason?.message ??
                "当前环境尚未启用Word结构导入。已有候选和回执仍可核对。"}
            </p>
          )}
          <details>
            <summary>本次支持范围与限制</summary>
            <ul>
              {capability.value.supported.map((item, index) => (
                <li key={`supported-${index}`}>{item}</li>
              ))}
              {capability.value.limitations.map((item, index) => (
                <li key={`limitation-${index}`}>{item}</li>
              ))}
            </ul>
            <p className="small-note">
              单个原件上限 {sizeLabel(capability.value.limits.max_docx_bytes)}
              ，最多 {capability.value.limits.max_sections} 个新章节、
              {capability.value.limits.max_images}{" "}
              张图片。导入不等于Word排版或正式投递资格已核验。
            </p>
          </details>
        </>
      )}
      {record.pending && (
        <div className="notice warning" role="status">
          <p>
            上次
            {record.pending.kind === "prepare"
              ? "创建候选"
              : record.pending.body.decision === "append"
                ? "追加章节"
                : "拒绝候选"}
            的回执尚未核对。原键、原内容和原保存条件已保留；请先恢复。
          </p>
          <button
            className="button secondary"
            disabled={busy || !!initial.error}
            onClick={() => void act("retry")}
          >
            {busy ? "正在恢复原请求…" : "恢复原导入请求结果"}
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="inline-success">
          {notice}
        </p>
      )}
      <button
        className="button secondary"
        aria-expanded={opened}
        onClick={() => setOpened((value) => !value)}
      >
        {opened ? "收起原件选择" : "选择已保存的Word原件"}
      </button>
      {opened && (
        <form
          className="word-import-form"
          onSubmit={(event) => {
            event.preventDefault();
            void act("prepare");
          }}
        >
          <ResourceState
            {...originals}
            hasData={!!originals.data}
            onRetry={() => {
              setMoreOriginals([]);
              void originals.reload();
            }}
          />
          {originalsInvalid && (
            <p className="notice error" role="alert">
              原件目录的项目或版本身份无法核对，未显示其他原件。请重新读取目录。
            </p>
          )}
          <label>
            选择本项目的确切Word版本
            <select
              aria-label="选择本项目的确切Word版本"
              value={sourceId}
              disabled={busy || pending || disabled}
              onChange={(event) => setSourceId(event.target.value)}
            >
              <option value="">请选择已保存原件</option>
              {sourceRows.map((item) => (
                <option
                  key={item.id}
                  value={item.id}
                  disabled={
                    item.byte_size >
                    (capability.value?.limits.max_docx_bytes ?? 0)
                  }
                >
                  {item.original_name} · {sizeLabel(item.byte_size)} ·{" "}
                  {item.id.slice(-8)}
                </option>
              ))}
            </select>
          </label>
          {source && (
            <dl className="word-import-original">
              <dt>原件版本</dt>
              <dd>{source.id}</dd>
              <dt>文件摘要</dt>
              <dd>{source.source_sha256}</dd>
              <dt>文件大小</dt>
              <dd>{source.byte_size.toLocaleString()} 字节</dd>
            </dl>
          )}
          {lastOriginals?.has_more && (
            <button
              type="button"
              className="text-button"
              disabled={loadingMore}
              onClick={() => void nextOriginals()}
            >
              加载更多Word原件
            </button>
          )}
          {!originals.loading &&
            originals.data &&
            !sourceRows.length &&
            !originalsInvalid && (
              <p className="small-empty">
                还没有可选择的Word原件。先到资料中上传并保存原件，再回来明确选择此版本。
              </p>
            )}
          {onPackages && (
            <button
              type="button"
              className="text-button"
              disabled={busy || pending}
              onClick={onPackages}
            >
              打开资料与原件
            </button>
          )}
          <label>
            创建候选的理由
            <input
              aria-label="创建候选的理由"
              value={reason}
              maxLength={1000}
              disabled={busy || pending || disabled}
              onChange={(event) => setReason(event.target.value)}
              placeholder="例如：将已核对的施工方案作为新章节"
            />
          </label>
          <div className="word-import-actions">
            <button
              className="button secondary"
              disabled={
                busy ||
                pending ||
                disabled ||
                !!initial.error ||
                !capability.value?.enabled ||
                !source ||
                !wordImportReasonValid(reason.trim())
              }
            >
              {busy ? "正在保存并核对原件…" : "保存当前编辑并生成导入候选"}
            </button>
            <span className="small-note">
              先等待当前编辑保存成功；创建候选不会修改草稿。
            </span>
          </div>
        </form>
      )}
      {loadingCandidate && <p role="status">正在读取指定导入候选…</p>}
      {current && (
        <div className="word-import-candidate">
          <div className="section-heading">
            <div>
              <h3>{current.source.filename}</h3>
              <p>
                基于草稿修订 {current.base_draft_revision} · 新增{" "}
                {current.section_count} 章 · {current.image_count} 张图片
              </p>
            </div>
            <Badge>{stateLabel[current.state]}</Badge>
          </div>
          <details>
            <summary>核对原件、候选与方法身份</summary>
            <dl className="word-import-identity">
              <dt>原件版本</dt>
              <dd>{current.source.document_version_id}</dd>
              <dt>原件摘要</dt>
              <dd>{current.source.digest}</dd>
              <dt>候选</dt>
              <dd>{current.candidate_id}</dd>
              <dt>候选摘要</dt>
              <dd>{current.candidate_digest}</dd>
              <dt>转换方法</dt>
              <dd>{current.method_digest}</dd>
            </dl>
          </details>
          <div className="notice neutral">
            仅追加新的根章节及其子章节。现有 {current.existing_sections.length}{" "}
            个章节保持原样；不替换正文、不启动核查。
          </div>
          <details>
            <summary>
              查看保持不变的现有章节（{current.existing_sections.length}）
            </summary>
            <ul>
              {current.existing_sections.map((section) => (
                <li key={section.section_id}>{section.title}</li>
              ))}
            </ul>
          </details>
          {current.sections.length > 0 && (
            <>
              <h4>拟追加的章节层级</h4>
              <ol className="word-import-tree" aria-label="拟追加章节层级">
                {wordImportSectionOrder(current).map(({ section, depth }) => (
                  <li
                    key={section.key}
                    style={{
                      paddingInlineStart: `${Math.min(depth, 10) * 16 + 12}px`,
                    }}
                  >
                    {depth === 0 ? "新根章节" : `第${depth + 1}层子章节`} ·{" "}
                    {section.title}
                  </li>
                ))}
              </ol>
            </>
          )}
          <h4>
            转换说明与损失（{current.blocker_count} 项阻断，
            {current.warning_count} 项需确认）
          </h4>
          {!current.issues.length && (
            <p>
              转换器未报告本次支持范围内的损失；请继续核对下方实际结构预览。
            </p>
          )}
          <ul className="word-import-issues">
            {current.issues.map((issue) => (
              <li
                key={issue.id}
                className={`word-import-issue ${issue.severity}`}
              >
                {issue.severity === "warning" ? (
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`确认损失：${issue.message}`}
                      checked={displayedAcknowledgements.includes(issue.id)}
                      disabled={
                        busy || pending || disabled || current.state !== "ready"
                      }
                      onChange={(event) =>
                        setAcknowledged((old) =>
                          event.target.checked
                            ? [...old, issue.id]
                            : old.filter((id) => id !== issue.id),
                        )
                      }
                    />
                    <span>
                      {issue.message}
                      <small>
                        原稿位置：{issue.source_path} · {issue.code}
                      </small>
                    </span>
                  </label>
                ) : (
                  <>
                    <strong>无法追加：{issue.message}</strong>
                    <small>
                      原稿位置：{issue.source_path} · {issue.code}
                    </small>
                  </>
                )}
              </li>
            ))}
          </ul>
          {current.blocker_count > 0 && (
            <p className="notice error">
              存在阻断项，确认警告也不能继续追加。请保留原稿，处理不支持内容后上传新版本；此候选仍保留在历史中。
            </p>
          )}
          {wordImportSectionOrder(current).map(({ section, depth }) => (
            <section
              className="word-import-section"
              key={section.key}
              aria-label={`章节预览：${section.title}`}
            >
              <h4>
                {depth > 0 ? "子章节 · " : "新章节 · "}
                {section.title}
              </h4>
              <WordImportRichPreview
                scope={scope}
                candidate={current}
                section={section}
                onImageStatus={onImageStatus}
              />
            </section>
          ))}
          <details
            onToggle={(event) => setShowMapping(event.currentTarget.open)}
          >
            <summary>
              逐项核对原稿位置映射（{current.mapping.length} 项）
            </summary>
            {showMapping && (
              <>
                <p className="small-note">
                  显示第 {current.mapping.length ? mappingPage * 20 + 1 : 0}—
                  {Math.min((mappingPage + 1) * 20, current.mapping.length)}{" "}
                  项，共 {current.mapping.length} 项。
                </p>
                <ul>
                  {current.mapping
                    .slice(mappingPage * 20, (mappingPage + 1) * 20)
                    .map((item, index) => (
                      <li key={`${item.node_id}:${index}`}>
                        {item.source_path} →{" "}
                        {
                          current.sections.find(
                            (section) => section.key === item.section_key,
                          )?.title
                        }{" "}
                        · {item.kind}
                      </li>
                    ))}
                </ul>
                <div className="word-import-actions">
                  <button
                    className="text-button"
                    disabled={!mappingPage}
                    onClick={() => setMappingPage((value) => value - 1)}
                  >
                    上一页映射
                  </button>
                  <button
                    className="text-button"
                    disabled={(mappingPage + 1) * 20 >= current.mapping.length}
                    onClick={() => setMappingPage((value) => value + 1)}
                  >
                    下一页映射
                  </button>
                </div>
              </>
            )}
          </details>
          {resolved ? (
            <div className="notice neutral" role="status">
              {resolved.decision === "append"
                ? `已追加 ${resolved.created_section_ids.length} 个章节，生成草稿修订 ${resolved.draft_revision}。原章节与历史保留；请继续编辑并按实际版式构建核对。`
                : "此候选已明确拒绝，草稿未改变。原件和候选历史保留。"}
            </div>
          ) : (
            <div className="word-import-decision">
              {stale && (
                <p className="notice warning">
                  当前草稿已变为修订 {draftRevision}
                  ，与候选基准不同。旧候选保留供核对；请按当前草稿重新生成候选。
                </p>
              )}
              {current.image_count > 0 && !allImagesReady && (
                <p className="notice warning">
                  候选图片尚未全部读取并核验。请等待实际图片显示，失败时重新读取；完成前不能追加。
                </p>
              )}
              {warnings.length > 0 && (
                <p className="small-note">
                  已明确确认{" "}
                  {
                    warnings.filter((issue) => acknowledged.includes(issue.id))
                      .length
                  }{" "}
                  / {warnings.length} 项转换损失；每项均需单独选择。
                </p>
              )}
              <label>
                本次处理理由
                <input
                  aria-label="本次处理理由"
                  value={decisionReason}
                  maxLength={1000}
                  disabled={busy || pending}
                  onChange={(event) => setDecisionReason(event.target.value)}
                  placeholder="填写追加或拒绝此候选的理由"
                />
              </label>
              <div className="word-import-actions">
                <button
                  className="button primary"
                  disabled={
                    busy || pending || disabled || !!initial.error || !canAppend
                  }
                  onClick={() => void act("append")}
                >
                  明确追加这些新章节
                </button>
                <button
                  className="button secondary"
                  disabled={
                    busy ||
                    pending ||
                    !!initial.error ||
                    !wordImportReasonValid(decisionReason.trim())
                  }
                  onClick={() => void act("reject")}
                >
                  拒绝此候选并保留历史
                </button>
                <button
                  className="text-button"
                  disabled={busy || pending}
                  onClick={() => void loadCandidate(current.candidate_id)}
                >
                  重新读取此候选
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      <div className="word-import-history">
        <button
          className="text-button"
          aria-expanded={showHistory}
          onClick={() => setShowHistory((value) => !value)}
        >
          {showHistory ? "收起导入历史" : "查看导入历史"}
        </button>
        {showHistory && (
          <>
            <ResourceState
              {...history}
              hasData={!!history.data && !checkedHistory.error}
              onRetry={() => {
                setMoreHistory([]);
                void history.reload();
              }}
            />
            <ErrorNotice error={checkedHistory.error} />
            {!history.loading &&
              history.data &&
              !historyRows.length &&
              !checkedHistory.error && (
                <p className="small-empty">此草稿尚无导入候选。</p>
              )}
            <ul>
              {historyRows.map((item) => (
                <li key={item.candidate_id}>
                  <div>
                    <strong>{item.source.filename}</strong>
                    <p>
                      基于修订 {item.base_draft_revision} ·{" "}
                      {stateLabel[item.state]} · {item.section_count} 章 ·{" "}
                      {item.warning_count} 项警告 · {item.blocker_count} 项阻断
                    </p>
                  </div>
                  <button
                    className="button secondary"
                    disabled={busy || pending}
                    onClick={() => chooseCandidate(item.candidate_id)}
                  >
                    查看此候选
                  </button>
                </li>
              ))}
            </ul>
            {lastHistory?.has_more && (
              <button
                className="text-button"
                disabled={loadingMore}
                onClick={() => void nextHistory()}
              >
                加载更多导入历史
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
