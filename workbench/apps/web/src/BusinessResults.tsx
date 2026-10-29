import { useState } from "react";
import { api, supportsApi } from "./api";
import type { ApiResult } from "./api";
import type {
  BusinessResultPage,
  BusinessResultRequest,
  BusinessResultView,
  BusinessResultCorrectionRequest,
  BusinessResultVerificationRequest,
  DocumentEvidenceView,
  SubmissionView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import {
  businessReason,
  businessStages,
  localDateTime,
  resultVerifications,
} from "./businessNames";
import { ArtifactActions } from "./ArtifactActions";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";
import { useSubmissionDocuments } from "./useSubmissionDocuments";

type Input = {
  open: boolean;
  baseId: string | null;
  stage: BusinessResultRequest["stage"];
  sourceType: BusinessResultRequest["source_type"];
  sourceId: string;
  refs: BusinessResultRequest["evidence_refs"];
  announced: string;
  known: string;
  reason: string;
  correction: string;
};
const empty: Input = {
  open: false,
  baseId: null,
  stage: "pending",
  sourceType: "user_reported",
  sourceId: "",
  refs: [],
  announced: "",
  known: "",
  reason: "",
  correction: "",
};

export function BusinessResults({
  bidId,
  memberId,
  submission,
}: {
  bidId: string;
  memberId: string;
  submission: SubmissionView;
}) {
  const [open, setOpen] = useState(false);
  const available = supportsApi(
    "GET",
    `/bids/${bidId}/submissions/${submission.id}/business-results`,
  );
  return available ? (
    <div className="business-results">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起实际结果与历史" : "登记／查看此实交的实际结果"}
      </button>
      {open && (
        <ResultWorkspace
          key={submission.id}
          bidId={bidId}
          memberId={memberId}
          submission={submission}
        />
      )}
    </div>
  ) : null;
}

function ResultWorkspace({
  bidId,
  memberId,
  submission,
}: {
  bidId: string;
  memberId: string;
  submission: SubmissionView;
}) {
  const path = `/bids/${bidId}/submissions/${submission.id}/business-results`;
  const resource = useResource<BusinessResultPage>(`${path}?limit=20`);
  const [pages, setPages] = useState<
    { root: BusinessResultPage; page: BusinessResultPage }[]
  >([]);
  const currentPages = pages.filter((item) => item.root === resource.data);
  const last = currentPages.at(-1)?.page ?? resource.data;
  const items = [
    ...new Map(
      [
        ...(resource.data?.items ?? []),
        ...currentPages.flatMap((item) => item.page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const [reading, setReading] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [input, setInput] = useKnowledgeInput<Input>(
    knowledgeStorageKey(memberId, submission.id) + "business-result",
    empty,
  );
  const [basis, setBasis] = useState<ApiResult<BusinessResultPage> | null>(
    null,
  );
  const command = useRecordedCommand(
    `business-result:${memberId}:${submission.id}`,
  );
  const valid =
    resource.data?.bid_id === bidId &&
    resource.data.submission_id === submission.id;
  const head = valid ? resource.data?.current_result : undefined;
  const eligible =
    submission.current && submission.identity?.binding_status === "confirmed";
  function accept(value: BusinessResultView) {
    if (value.bid_id !== bidId || value.submission_id !== submission.id) {
      setFailure(new Error("结果与实交身份不一致，请重新读取。"));
      return;
    }
    setInput(empty);
    setBasis(null);
    void resource.reload();
    window.dispatchEvent(new Event("server-snapshot-change"));
  }
  async function read(openNew = false) {
    setReading(true);
    setFailure(null);
    try {
      const result = await api<BusinessResultPage>(`${path}?limit=20`);
      if (
        result.data.bid_id !== bidId ||
        result.data.submission_id !== submission.id
      )
        throw new Error("结果集合身份不一致。");
      setBasis(result);
      if (openNew && (input.known || input.reason)) {
        setInput((old) => ({ ...old, open: true }));
      } else if (openNew) {
        const value = result.data.current_result;
        setInput(
          value
            ? {
                open: true,
                baseId: value.id,
                stage: value.stage,
                sourceType: value.source_type,
                sourceId: value.source_version_id ?? "",
                refs: value.evidence_refs,
                announced: value.announced_at
                  ? localDateTime(value.announced_at)
                  : "",
                known: localDateTime(value.known_at),
                reason: value.reason,
                correction: "",
              }
            : { ...empty, open: true },
        );
      }
    } catch (error) {
      setFailure(error);
    } finally {
      setReading(false);
    }
  }
  const conflictBase =
    !!basis && input.baseId !== (basis.data.current_result?.id ?? null);
  return (
    <section aria-label="实际结果工作面">
      <h3>阶段结果与核验</h3>
      <p className="small-note">
        技术成绩另行登记。中标候选不等于已中标；阶段未知不等于未中标。保存结果不自动核实。
      </p>
      <ResourceState
        {...resource}
        hasData={!!resource.data}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !valid ? (
        <p className="notice error">结果集合与当前实交身份不一致。</p>
      ) : (
        <>
          {head ? (
            <ResultSummary item={head} />
          ) : (
            resource.data && (
              <p className="small-empty">此实际提交尚无阶段结果，保持未知。</p>
            )
          )}
          {!eligible && (
            <p className="notice warning">
              新增结果需当前实际提交具有可靠的投标主体与工程身份；请在原实交详情核对依据。历史仍可查，不用当前身份补填当时身份。
            </p>
          )}
          {!input.open && eligible && (
            <button
              type="button"
              className="button secondary"
              disabled={reading || command.busy || !!command.pending}
              onClick={() => void read(true)}
            >
              {head ? "追加更正实际结果" : "登记实际结果"}
            </button>
          )}
          {input.open && (
            <form
              className="decision-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!basis?.etag || conflictBase) return;
                const body: BusinessResultRequest = {
                  submission_id: submission.id,
                  stage: input.stage,
                  source_type: input.sourceType,
                  source_version_id: input.sourceId || null,
                  evidence_refs: input.refs,
                  announced_at: input.announced
                    ? new Date(input.announced).toISOString()
                    : null,
                  known_at: new Date(input.known).toISOString(),
                  reason: input.reason.trim(),
                };
                const correction: BusinessResultCorrectionRequest | null =
                  input.baseId
                    ? {
                        ...body,
                        base_result_id: input.baseId,
                        correction_reason: input.correction.trim(),
                      }
                    : null;
                void command
                  .run<BusinessResultView>(
                    input.baseId
                      ? `/business-results/${input.baseId}/corrections`
                      : path,
                    correction ?? body,
                    basis.etag,
                  )
                  .then((value) => {
                    if (value) accept(value.data);
                  });
              }}
            >
              <fieldset disabled={command.busy || !!command.pending}>
                <legend>
                  {input.baseId
                    ? "追加更正，原结果保留"
                    : "登记已获知的实际结果"}
                </legend>
                {input.baseId && (
                  <p className="small-note">
                    原结果：
                    {basis?.data.current_result?.id === input.baseId
                      ? businessStages[basis.data.current_result.stage]
                      : "原记录身份保留，请读取当前依据"}
                    ；下方新值仅在保存成功后生效。
                  </p>
                )}
                <label>
                  真实阶段
                  <select
                    aria-label="真实阶段"
                    value={input.stage}
                    onChange={(event) =>
                      setInput((old) => ({
                        ...old,
                        stage: event.target.value as Input["stage"],
                      }))
                    }
                  >
                    {Object.entries(businessStages).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  来源性质
                  <select
                    aria-label="来源性质"
                    value={input.sourceType}
                    onChange={(event) =>
                      setInput((old) => ({
                        ...old,
                        sourceType: event.target.value as Input["sourceType"],
                      }))
                    }
                  >
                    <option value="user_reported">用户报送，尚未核实</option>
                    <option value="official">官方来源，仍需单独核实</option>
                  </select>
                </label>
                <ResultSource
                  bidId={bidId}
                  sourceId={input.sourceId}
                  refs={input.refs}
                  required={input.sourceType === "official"}
                  onChange={(sourceId, refs) =>
                    setInput((old) => ({ ...old, sourceId, refs }))
                  }
                />
                <label>
                  公布时间（未知可留空）
                  <input
                    type="datetime-local"
                    value={input.announced}
                    min={localDateTime(submission.submitted_at)}
                    max={input.known || undefined}
                    onChange={(event) =>
                      setInput((old) => ({
                        ...old,
                        announced: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  实际获知时间
                  <input
                    required
                    type="datetime-local"
                    value={input.known}
                    min={localDateTime(submission.submitted_at)}
                    max={localDateTime(new Date().toISOString())}
                    onChange={(event) =>
                      setInput((old) => ({ ...old, known: event.target.value }))
                    }
                  />
                </label>
                <label>
                  事实说明与来源理由
                  <textarea
                    required
                    maxLength={4000}
                    value={input.reason}
                    onChange={(event) =>
                      setInput((old) => ({
                        ...old,
                        reason: event.target.value,
                      }))
                    }
                  />
                </label>
                {input.baseId && (
                  <label>
                    本次更正原因
                    <textarea
                      required
                      maxLength={4000}
                      value={input.correction}
                      onChange={(event) =>
                        setInput((old) => ({
                          ...old,
                          correction: event.target.value,
                        }))
                      }
                    />
                  </label>
                )}
              </fieldset>
              {(command.conflict || !basis || conflictBase) && (
                <div className="notice warning">
                  <div>
                    <p>
                      {conflictBase
                        ? "当前结果头已改变，未将输入悄悄改到另一结果。请保留本地输入，核对历史差异后收起并明确选择新的更正目标。"
                        : "请读取当前结果依据。并发变化时输入保留，不自动重放核验。"}
                    </p>
                    <button
                      type="button"
                      className="text-button"
                      disabled={reading || command.busy || !!command.pending}
                      onClick={() => void read()}
                    >
                      读取当前结果依据，保留输入
                    </button>
                  </div>
                </div>
              )}
              <button
                className="button primary"
                disabled={
                  !eligible ||
                  reading ||
                  command.busy ||
                  !!command.pending ||
                  !basis?.etag ||
                  conflictBase
                }
              >
                {command.busy
                  ? "正在保存…"
                  : input.baseId
                    ? "保存更正"
                    : "保存实际结果"}
              </button>
              <button
                type="button"
                className="text-button"
                disabled={command.busy || !!command.pending}
                onClick={() => {
                  setInput((old) => ({ ...old, open: false }));
                  setBasis(null);
                }}
              >
                收起表单，保留输入
              </button>
            </form>
          )}
          <ErrorNotice error={command.error ?? failure} />
          {command.pending && !command.busy && (
            <div className="notice warning">
              <p>上次写入结果未取得，先恢复同一请求。</p>
              <button
                className="button secondary"
                onClick={() =>
                  void command.retry<BusinessResultView>().then((value) => {
                    if (value) accept(value.data);
                  })
                }
              >
                恢复原结果登记
              </button>
            </div>
          )}
          {head && eligible && (
            <ResultVerification
              key={head.id}
              memberId={memberId}
              item={head}
              onSaved={() => void resource.reload()}
            />
          )}
          <details className="coverage-details">
            <summary>
              查看结果历史（已加载{items.length}／共
              {resource.data?.total ?? "未知"}条）
            </summary>
            {items.map((item) => (
              <div className="result-history-item" key={item.id}>
                <ResultSummary item={item} />
                {item.source_version_id && (
                  <ArtifactActions
                    bidId={bidId}
                    documentId={item.source_version_id}
                    isPdf
                    downloadLabel="下载此结果的来源原件"
                    expectedArtifactKind="source_original"
                  />
                )}
                <EvidenceLinks
                  ids={item.evidence_refs.map((ref) => ref.evidence_id)}
                />
              </div>
            ))}
            {last?.next_offset != null && (
              <button
                className="text-button"
                disabled={reading}
                onClick={async () => {
                  setReading(true);
                  try {
                    const value = await api<BusinessResultPage>(
                      `${path}?limit=20&offset=${last.next_offset}`,
                    );
                    if (
                      value.data.bid_id !== bidId ||
                      value.data.submission_id !== submission.id
                    )
                      throw new Error("历史集合身份不一致。");
                    if (resource.data)
                      setPages((old) => [
                        ...old,
                        { root: resource.data!, page: value.data },
                      ]);
                  } catch (error) {
                    setFailure(error);
                  } finally {
                    setReading(false);
                  }
                }}
              >
                加载更多结果记录
              </button>
            )}
          </details>
        </>
      )}
    </section>
  );
}

function ResultSummary({ item }: { item: BusinessResultView }) {
  return (
    <div className="result-summary">
      <h4>{businessStages[item.stage]}</h4>
      <Badge>{item.current ? "当前结果头" : "历史结果"}</Badge>{" "}
      <Badge tone={item.verification === "verified" ? "success" : "warning"}>
        {resultVerifications[item.verification]}
      </Badge>
      <p>{item.reason}</p>
      <p className="small-note">
        {item.source_type === "official" ? "官方来源报送" : "用户报送"} · 公布{" "}
        {item.announced_at
          ? new Date(item.announced_at).toLocaleString("zh-CN")
          : "未知"}{" "}
        · 获知 {new Date(item.known_at).toLocaleString("zh-CN")}
      </p>
      {item.correction_reason && <p>更正原因：{item.correction_reason}</p>}
      {!item.usable && (
        <div className="notice warning">
          <div>
            当前统计不可用：
            {item.unusable_reasons.map(businessReason).join("；")}
          </div>
        </div>
      )}
      <details className="identity-details">
        <summary>结果及核验身份</summary>
        <p>
          记录{item.id} · 修订{item.head_revision} · 核验依据
          {item.verification_authority_id ?? "未有核验决定"}
        </p>
        {item.verification_details && (
          <p>核验说明：{item.verification_details.reason}</p>
        )}
      </details>
    </div>
  );
}

function ResultSource({
  bidId,
  sourceId,
  refs,
  required = false,
  locked = false,
  onChange,
}: {
  bidId: string;
  sourceId: string;
  refs: BusinessResultRequest["evidence_refs"];
  required?: boolean;
  locked?: boolean;
  onChange: (id: string, refs: BusinessResultRequest["evidence_refs"]) => void;
}) {
  const documents = useSubmissionDocuments(bidId);
  const evidence = useResource<DocumentEvidenceView>(
    sourceId ? `/documents/${sourceId}/evidence` : null,
  );
  return (
    <div className="result-source">
      <label>
        结果来源原件
        <select
          aria-label="结果来源原件"
          disabled={locked}
          required={required}
          value={sourceId}
          onChange={(event) => onChange(event.target.value, [])}
        >
          <option value="">尚无原件，仅作未核实报送</option>
          {documents.items
            .filter((item) => item.artifact_kind === "source_original")
            .map((item) => (
              <option
                key={item.document_version_id}
                value={item.document_version_id}
              >
                {item.original_name}
              </option>
            ))}
          {sourceId &&
            !documents.items.some(
              (item) => item.document_version_id === sourceId,
            ) && <option value={sourceId}>已选原来源（请核对可读性）</option>}
        </select>
      </label>
      <ResourceState
        {...documents}
        hasData={!!documents.data}
        onRetry={() => void documents.reload()}
      />
      <ErrorNotice error={documents.moreError} />
      {documents.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={documents.moreBusy}
          onClick={() => void documents.more()}
        >
          加载更多结果来源原件
        </button>
      )}
      {sourceId && (
        <>
          <ResourceState
            {...evidence}
            hasData={!!evidence.data}
            onRetry={() => void evidence.reload()}
          />
          {evidence.data?.gaps.map((gap, i) => (
            <p className="small-note" key={i}>
              {gap}
            </p>
          ))}
          <p className="small-note">
            勾选明确对应本工程、轮次、主体和阶段结论的逐字原页。选中文本不代表核验通过。
          </p>
          {evidence.data?.document_version_id === sourceId &&
            evidence.data.items.map((item) => (
              <label className="evidence-select-item" key={item.id}>
                <input
                  type="checkbox"
                  checked={refs.some((ref) => ref.evidence_id === item.id)}
                  disabled={
                    item.source_status === "withdrawn" ||
                    (!refs.some((ref) => ref.evidence_id === item.id) &&
                      refs.length >= 100)
                  }
                  onChange={(event) =>
                    onChange(
                      sourceId,
                      event.target.checked
                        ? [
                            ...refs,
                            {
                              document_version_id: sourceId,
                              evidence_id: item.id,
                              physical_page: item.physical_page,
                              quote: item.quote,
                            },
                          ]
                        : refs.filter((ref) => ref.evidence_id !== item.id),
                    )
                  }
                />
                <span>
                  物理页{item.physical_page} · {item.quote}
                </span>
              </label>
            ))}
          <EvidenceLinks ids={refs.map((ref) => ref.evidence_id)} />
        </>
      )}
    </div>
  );
}

function ResultVerification({
  memberId,
  item,
  onSaved,
}: {
  memberId: string;
  item: BusinessResultView;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] =
    useState<BusinessResultVerificationRequest["state"]>("verified");
  const [reason, setReason] = useKnowledgeInput(
    knowledgeStorageKey(memberId, item.id) + "verification-reason",
    "",
  );
  const [identity, setIdentity] = useState(false);
  const current = useResource<BusinessResultView>(
    open ? `/business-results/${item.id}` : null,
  );
  const command = useRecordedCommand(
    `business-verification:${memberId}:${item.id}`,
  );
  const [refs, setRefs] = useState(item.evidence_refs);
  const valid =
    current.data?.id === item.id &&
    current.data.bid_id === item.bid_id &&
    current.data.submission_id === item.submission_id &&
    current.data.current;
  const canVerify = !!(
    valid &&
    current.data?.source_type === "official" &&
    current.data.source_version_id &&
    current.data.announced_at &&
    identity &&
    refs.length
  );
  function accepted(value: BusinessResultView | undefined) {
    if (value && value.id === item.id && value.bid_id === item.bid_id) {
      setOpen(false);
      onSaved();
      window.dispatchEvent(new Event("server-snapshot-change"));
    }
  }
  return (
    <div>
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        核实／标注此结果
      </button>
      {open && (
        <form
          className="decision-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid || !current.etag) return;
            const body: BusinessResultVerificationRequest = {
              state,
              reason: reason.trim(),
              identity_confirmed: identity,
              evidence_refs: refs,
            };
            void command
              .run<BusinessResultView>(
                `/business-results/${item.id}/verification-decisions`,
                body,
                current.etag,
              )
              .then((value) => accepted(value?.data));
          }}
        >
          <ResourceState
            {...current}
            hasData={!!current.data}
            onRetry={() => void current.reload()}
          />
          <fieldset disabled={command.busy || !!command.pending}>
            <legend>一次明确核验决定，不代替交易平台</legend>
            <label>
              核验结论
              <select
                aria-label="核验结论"
                value={state}
                onChange={(event) =>
                  setState(event.target.value as typeof state)
                }
              >
                {Object.entries(resultVerifications).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {state === "verified" && (
              <>
                <p className="small-note">
                  须有官方原件、公布时间、实际取得时间与精确原页。来源或身份变更由服务器重新检查；报送不等于已核实。
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={identity}
                    onChange={(event) => setIdentity(event.target.checked)}
                  />
                  我已核对原页对应本方、工程／标段／轮次及此实际提交，且阶段结论有据
                </label>
                {current.data?.source_version_id ? (
                  <ResultSource
                    bidId={item.bid_id}
                    sourceId={current.data.source_version_id}
                    refs={refs}
                    required
                    locked
                    onChange={(sourceId, next) => {
                      if (sourceId === current.data?.source_version_id)
                        setRefs(next);
                    }}
                  />
                ) : (
                  <p className="notice warning">
                    缺少官方来源，请先追加更正结果内容。
                  </p>
                )}
              </>
            )}
            <label>
              核验理由
              <textarea
                required
                maxLength={4000}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          </fieldset>
          <ErrorNotice error={command.error} />
          {(command.conflict || !valid) && (
            <p className="notice warning">
              结果状态尚未核对或已变化。保留理由，读取最新头后再次明确决定；旧结果不能覆盖新头。
            </p>
          )}
          <button
            type="button"
            className="text-button"
            disabled={command.busy || !!command.pending}
            onClick={() => void current.reload()}
          >
            刷新当前结果头，保留理由
          </button>
          <button
            className="button secondary"
            disabled={
              !valid ||
              !current.etag ||
              command.busy ||
              !!command.pending ||
              (state === "verified" && !canVerify)
            }
          >
            {state === "verified" ? "核实此结果" : "保存此核验标注"}
          </button>
        </form>
      )}
      {command.pending && !command.busy && (
        <button
          className="button secondary"
          onClick={() =>
            void command
              .retry<BusinessResultView>()
              .then((value) => accepted(value?.data))
          }
        >
          恢复原核验结果
        </button>
      )}
    </div>
  );
}
