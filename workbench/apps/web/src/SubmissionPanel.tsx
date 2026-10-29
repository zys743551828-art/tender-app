import { BusinessResults } from "./BusinessResults";
import { lazy, Suspense, useCallback, useState } from "react";
import { api, supportsApi } from "./api";
import type { ApiResult } from "./api";
import type { FindingView } from "./contracts";
import type {
  GateView,
  OfflineSubmissionRequest,
  SubmissionCorrectionRequest,
  SubmissionPage,
  SubmissionRequest,
  SubmissionView,
  SingleBodySubmissionView,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { SubmissionDocumentChoices } from "./SubmissionDocuments";
import { useSubmissionDocuments } from "./useSubmissionDocuments";
import { useDirectory } from "./useDirectory";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";
import type { WorkspacePage } from "./workspaceTypes";
import { PackageSubmissionPanel } from "./PackageSubmissionPanel";
import type { PackageSubmissionOpenRequest } from "./PackageSubmissionPanel";
import { PackageSubmissionCard } from "./PackageSubmissionCard";
import type { PackageNavigationTarget } from "./packageNavigation";

const PackageRetrospectives = lazy(() =>
  import("./PackageRetrospectives").then((module) => ({
    default: module.PackageRetrospectives,
  })),
);

type FormInput = {
  open: boolean;
  kind: "standard" | "offline_fact";
  correctionId: string | null;
  actualId: string;
  evidenceId: string;
  submittedAt: string;
  explanation: string;
  reason: string;
};
const empty: FormInput = {
  open: false,
  kind: "standard",
  correctionId: null,
  actualId: "",
  evidenceId: "",
  submittedAt: "",
  explanation: "",
  reason: "",
};

export function SubmissionPanel({
  bidId,
  memberId,
  onNavigate,
  onChanged,
  onOpenKnowledge,
  onOpenPackage,
}: {
  bidId: string;
  memberId: string;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
  onChanged: () => void;
  onOpenKnowledge?: (knowledgeId: string) => void;
  onOpenPackage?: (target: PackageNavigationTarget) => void;
}) {
  const available = supportsApi("GET", `/bids/${bidId}/submission-gate`);
  const packageAvailable = supportsApi(
    "POST",
    `/bids/${bidId}/packages/_/revisions/_/submissions`,
  );
  const gate = useResource<GateView>(
    available ? `/bids/${bidId}/submission-gate` : null,
  );
  const history = useDirectory<SubmissionPage>(
    supportsApi("GET", `/bids/${bidId}/submissions`)
      ? `/bids/${bidId}/submissions?limit=20`
      : null,
  );
  const [input, setInput] = useKnowledgeInput<FormInput>(
    knowledgeStorageKey(memberId, bidId) + "submission",
    empty,
  );
  const [basis, setBasis] = useState<ApiResult<GateView> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<SubmissionView | null>(null);
  const [retrospectivesStarted, setRetrospectivesStarted] = useState(false);
  const [packageLocked, setPackageLocked] = useState(false);
  const [packageRequest, setPackageRequest] =
    useState<PackageSubmissionOpenRequest | null>(null);
  const packageLock = useCallback(
    (value: boolean) => setPackageLocked(value),
    [],
  );
  const foreign = history.items.some((item) => item.bid_id !== bidId);
  async function begin(
    kind: FormInput["kind"],
    correction?: SingleBodySubmissionView,
  ) {
    if (busy || packageLocked) return;
    setBusy(true);
    setError(null);
    try {
      if (correction) {
        const { data } = await api<SubmissionView>(
          `/submissions/${correction.id}`,
        );
        if (
          data.subject_kind === "bid_package" ||
          data.id !== correction.id ||
          data.bid_id !== bidId ||
          !data.current
        )
          throw new Error(
            "原记录已不是当前实交记录，请刷新历史后选择更正目标。",
          );
        correction = data;
      }
      const snapshot = await api<GateView>(`/bids/${bidId}/submission-gate`);
      setBasis(snapshot);
      setSaved(null);
      setInput((old) => ({
        ...old,
        open: true,
        kind,
        correctionId: correction?.id ?? null,
        ...(correction
          ? {
              actualId: correction.body_version_id,
              evidenceId: correction.evidence_ref ?? "",
              submittedAt: localTime(correction.submitted_at),
              explanation: correction.explanation ?? "",
              reason: "",
            }
          : {}),
      }));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  function beginPackageCorrection(record: SubmissionView) {
    if (busy || input.open || packageLocked || foreign || !record.current)
      return;
    setPackageRequest((previous) => ({
      sequence: (previous?.sequence ?? 0) + 1,
      correction: record,
    }));
  }
  function refresh() {
    void gate.reload();
    void history.reload();
    onChanged();
    window.dispatchEvent(new Event("server-snapshot-change"));
  }
  if (!available && !packageAvailable) return null;
  return (
    <>
      <PackageSubmissionPanel
        key={`${bidId}:${memberId}`}
        bidId={bidId}
        memberId={memberId}
        disabled={
          busy || input.open || foreign || history.loading || !!history.error
        }
        hasCurrent={history.items.some((item) => item.current)}
        request={packageRequest}
        onLock={packageLock}
        onSaved={(record) => {
          setSaved(record);
          setPackageRequest(null);
          refresh();
        }}
      />
      {available && (
        <section className="panel submission-panel">
          <div className="section-heading">
            <div>
              <h2>提交检查与实交登记</h2>
              <p className="small-note">
                登记已经发生的提交。用户声明，未核验交易平台回执；这里不会代替您向交易平台提交。
              </p>
            </div>
            <button className="text-button" onClick={refresh}>
              刷新提交检查与记录
            </button>
          </div>
          <ResourceState
            {...gate}
            hasData={!!gate.data}
            onRetry={() => void gate.reload()}
          />
          {gate.data && (
            <>
              <div
                className={`notice ${gate.data.allowed ? "neutral" : "warning"}`}
              >
                <div>
                  <strong>
                    {gate.data.allowed
                      ? "当前核心提交检查满足登记条件"
                      : "标准登记仍有待处理阻断"}
                  </strong>
                  <p>
                    资料修订 {gate.data.material_revision} ·{" "}
                    {gate.data.body_version_id
                      ? `受检稿 ${gate.data.body_version_id.slice(0, 8)}`
                      : "尚无受检稿"}
                    。保存时服务端会重新核对，当前检查不能证明过去时点已经满足。
                  </p>
                </div>
              </div>
              <ul className="gate-blockers">
                {gate.data.blockers.map((blocker, index) => (
                  <li key={`${blocker.code}:${blocker.object_id}:${index}`}>
                    <GateBlocker blocker={blocker} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
              {gate.data.warnings.map((warning, index) => (
                <p className="small-note" key={index}>
                  {warning}
                </p>
              ))}
            </>
          )}
          <ErrorNotice error={error} />
          {saved && (
            <div className="notice neutral" role="status">
              <div>
                <strong>已保存实交记录</strong>
                <p>
                  {saved.checks_label} ·
                  用户声明，未核验交易平台回执。原稿和登记身份已留存。
                </p>
              </div>
            </div>
          )}
          {!input.open && (
            <div className="review-shortcuts">
              <button
                className="button primary"
                disabled={
                  busy ||
                  packageLocked ||
                  gate.loading ||
                  !!gate.error ||
                  !gate.data?.allowed ||
                  history.loading ||
                  foreign ||
                  history.items.some((item) => item.current)
                }
                onClick={() => void begin("standard")}
              >
                登记已检查的实际提交
              </button>
              <button
                className="button secondary"
                disabled={
                  busy ||
                  packageLocked ||
                  foreign ||
                  history.loading ||
                  history.items.some((item) => item.current)
                }
                onClick={() => void begin("offline_fact")}
              >
                补录线下已发生的提交
              </button>
            </div>
          )}
          {input.open && (
            <SubmissionEditor
              key={input.correctionId ?? "new"}
              bidId={bidId}
              memberId={memberId}
              input={input}
              setInput={setInput}
              initialBasis={basis}
              externalDisabled={packageLocked}
              onSaved={(record) => {
                setSaved(record);
                setInput(empty);
                setBasis(null);
                refresh();
              }}
              onClose={() => setInput((old) => ({ ...old, open: false }))}
            />
          )}
        </section>
      )}
      <section className="panel">
        <h2>实交记录与更正历史</h2>
        <ResourceState
          {...history}
          hasData={!!history.data}
          onRetry={() => void history.reload()}
        />
        <ErrorNotice error={history.moreError} />
        {foreign ? (
          <div className="notice error" role="alert">
            实交记录项目身份不一致，未展示其他项目记录。
          </div>
        ) : (
          history.items.map((record) =>
            record.subject_kind === "bid_package" ? (
              <PackageSubmissionCard
                key={record.id}
                bidId={bidId}
                memberId={memberId}
                record={record}
                disabled={busy || input.open || packageLocked}
                onCorrect={() => beginPackageCorrection(record)}
                onOpenPackage={onOpenPackage}
                onOpenRules={() => onNavigate("rules")}
              />
            ) : (
              <SubmissionCard
                key={record.id}
                bidId={bidId}
                memberId={memberId}
                record={record}
                onNavigate={onNavigate}
                onCorrect={() => void begin(record.kind, record)}
                disabled={busy || input.open || packageLocked}
                onPackageCorrect={
                  packageAvailable
                    ? () => beginPackageCorrection(record)
                    : undefined
                }
              />
            ),
          )
        )}
        {history.data && !history.items.length && (
          <p className="small-empty">
            尚无实交登记记录。这不表示线下没有发生提交。
          </p>
        )}
        {history.hasMore && (
          <button
            className="button secondary"
            disabled={history.moreBusy}
            onClick={() => void history.loadMore()}
          >
            加载更早的实交记录
          </button>
        )}
      </section>
      {supportsApi("GET", `/bids/${bidId}/package-retrospectives`) && (
        <details
          className="panel"
          onToggle={(event) => {
            if (event.currentTarget.open) setRetrospectivesStarted(true);
          }}
        >
          <summary>整包复盘与知识候选</summary>
          {retrospectivesStarted && (
            <Suspense fallback={<p role="status">正在打开整包复盘…</p>}>
              <PackageRetrospectives
                key={`${bidId}:${memberId}`}
                bidId={bidId}
                memberId={memberId}
                onKnowledgeCreated={onOpenKnowledge}
              />
            </Suspense>
          )}
        </details>
      )}
    </>
  );
}

function SubmissionEditor({
  bidId,
  memberId,
  input,
  setInput,
  initialBasis,
  externalDisabled,
  onSaved,
  onClose,
}: {
  bidId: string;
  memberId: string;
  input: FormInput;
  setInput: (next: FormInput | ((old: FormInput) => FormInput)) => void;
  initialBasis: ApiResult<GateView> | null;
  externalDisabled: boolean;
  onSaved: (record: SingleBodySubmissionView) => void;
  onClose: () => void;
}) {
  const docs = useSubmissionDocuments(bidId);
  const [basis, setBasis] = useState(initialBasis);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const command = useRecordedCommand(
    `submission:${memberId}:${bidId}:${input.correctionId ?? "new"}`,
  );
  const change = (field: keyof FormInput, value: string) =>
    setInput((old) => ({ ...old, [field]: value }));
  const gate = basis?.data;
  const locked = externalDisabled || command.busy || !!command.pending;
  const actualId =
    input.kind === "standard" ? gate?.body_version_id : input.actualId;
  const actual = docs.items.find(
    (document) => document.document_version_id === actualId,
  );
  const proof = docs.items.find(
    (document) => document.document_version_id === input.evidenceId,
  );
  async function reread() {
    if (reading || command.busy || command.pending) return;
    setReading(true);
    setError(null);
    try {
      if (input.correctionId) {
        const { data } = await api<SubmissionView>(
          `/submissions/${input.correctionId}`,
        );
        if (
          data.bid_id !== bidId ||
          data.subject_kind === "bid_package" ||
          data.id !== input.correctionId ||
          !data.current
        )
          throw new Error(
            "更正目标已变化，输入保留。请返回实交历史选择当前记录。",
          );
      }
      const next = await api<GateView>(`/bids/${bidId}/submission-gate`);
      setBasis(next);
      command.clearError();
    } catch (failure) {
      setError(failure);
    } finally {
      setReading(false);
    }
  }
  function received(record: SubmissionView) {
    if (
      record.subject_kind === "bid_package" ||
      record.bid_id !== bidId ||
      record.supersedes_id !== input.correctionId
    )
      throw new Error(
        "登记返回身份不一致，请刷新实交历史核对，未套用其他记录。",
      );
    onSaved(record);
  }
  async function submit() {
    if (locked) return;
    setError(null);
    try {
      if (!basis?.etag || !actualId || !proof || !input.submittedAt)
        throw new Error(
          "请核对当前检查依据、真实稿件、提交时间和本项目已核验附件。",
        );
      const at = new Date(input.submittedAt);
      if (!Number.isFinite(at.getTime()) || at.getTime() > Date.now())
        throw new Error("只能登记已经发生的提交，请填写准确的实际时间。");
      let body: SubmissionRequest | OfflineSubmissionRequest;
      if (input.kind === "standard") {
        if (!gate?.allowed || !gate.review_id || !gate.body_version_id)
          throw new Error(
            "当前标准登记仍有阻断，请先处理；已发生的线下事实可独立补录。",
          );
        body = {
          body_version_id: gate.body_version_id,
          review_id: gate.review_id,
          material_revision: gate.material_revision,
          submitted_at: at.toISOString(),
          evidence_ref: proof.document_version_id,
        };
      } else {
        if (!actual || !input.explanation.trim())
          throw new Error(
            "请明确选择实际提交的原件，并说明未经过完整检查的原因与事实依据。",
          );
        body = {
          actual_document_version_id: actual.document_version_id,
          submitted_at: at.toISOString(),
          evidence_ref: proof.document_version_id,
          explanation: input.explanation.trim(),
        };
      }
      if (input.correctionId && !input.reason.trim())
        throw new Error("请填写本次追加更正的理由。");
      const correction: SubmissionCorrectionRequest | null = input.correctionId
        ? input.kind === "standard"
          ? {
              kind: "standard",
              submission: body as SubmissionRequest,
              reason: input.reason.trim(),
            }
          : {
              kind: "offline_fact",
              submission: body as OfflineSubmissionRequest,
              reason: input.reason.trim(),
            }
        : null;
      const path = input.correctionId
        ? `/submissions/${input.correctionId}/corrections`
        : `/bids/${bidId}/${input.kind === "standard" ? "submissions" : "submission-facts"}`;
      const result = await command.run<SubmissionView>(
        path,
        correction ?? body,
        basis.etag,
      );
      if (result) received(result.data);
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <form
      className="submission-editor"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3>
        {input.correctionId
          ? "追加更正实交记录"
          : input.kind === "standard"
            ? "登记已检查的实际提交"
            : "补录线下已发生的提交"}
      </h3>
      {input.correctionId && (
        <p className="small-note">
          更正原记录 {input.correctionId.slice(0, 8)}
          ；原登记与当时身份保留，不回写过去结论。
        </p>
      )}
      <fieldset disabled={locked}>
        <label>
          登记类型
          <select
            value={input.kind}
            onChange={(event) => change("kind", event.target.value)}
          >
            <option value="standard">经过系统核心检查的标准登记</option>
            <option value="offline_fact">
              线下事实补录 · 未经过系统完整检查
            </option>
          </select>
        </label>
        {input.kind === "standard" ? (
          <div className="notice neutral">
            <div>
              <strong>固定本次检查对应的实际PDF正文</strong>
              <p>
                {actual?.original_name ??
                  (actualId
                    ? `稿件 ${actualId.slice(0, 8)}`
                    : "请读取当前检查依据")}{" "}
                · 评审 {gate?.review_id?.slice(0, 8) ?? "尚无"} · 资料修订{" "}
                {gate?.material_revision ?? "待读取"}
              </p>
              {gate && !gate.allowed && (
                <p>
                  当前检查有阻断，不能以标准登记写入。可保留表单先去处理，或据实选择线下补录。
                </p>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="notice warning">
              此记录将永久标记“未经过系统完整检查”，不补造当时预测或通过结论。
            </div>
            <SubmissionDocumentChoices
              resource={docs}
              value={input.actualId}
              label="实际提交的原件"
              onChange={(value) => change("actualId", value)}
            />
            {actual && (
              <ArtifactActions
                bidId={bidId}
                documentId={actual.document_version_id}
                isPdf={actual.media_type === "application/pdf"}
                downloadLabel="下载此实际稿件核对"
              />
            )}
            <label>
              未经过完整检查的原因与已发生事实依据
              <textarea
                value={input.explanation}
                maxLength={2000}
                required
                rows={3}
                onChange={(event) => change("explanation", event.target.value)}
              />
            </label>
          </>
        )}
        <label>
          真实提交时间（本地时间）
          <input
            type="datetime-local"
            step="1"
            value={input.submittedAt}
            onChange={(event) => change("submittedAt", event.target.value)}
            required
          />
        </label>
        <p className="small-note">
          填写已发生的准确时间。评审、必要身份或核心确认在该时间后完成的，应据实补录，不能回写为事前检查通过。
        </p>
        <SubmissionDocumentChoices
          resource={docs}
          value={input.evidenceId}
          label="本项目提交声明附件"
          onChange={(value) => change("evidenceId", value)}
        />
        {actualId && (
          <button
            type="button"
            className="text-button"
            onClick={() => change("evidenceId", actualId)}
          >
            使用实交稿自身作为声明附件
          </button>
        )}
        <p className="small-note">
          可选择实交稿自身，无须另传回执。原件字节已核验不表示交易平台回执真实；本次始终按用户声明保存。
        </p>
        {proof && (
          <ArtifactActions
            bidId={bidId}
            documentId={proof.document_version_id}
            isPdf={proof.media_type === "application/pdf"}
            downloadLabel="下载此声明附件核对"
          />
        )}
        {input.correctionId && (
          <label>
            本次追加更正理由
            <textarea
              value={input.reason}
              maxLength={2000}
              required
              rows={3}
              onChange={(event) => change("reason", event.target.value)}
            />
          </label>
        )}
      </fieldset>
      <ErrorNotice error={error ?? command.error} />
      {command.pending && !command.busy && (
        <div className="notice warning">
          <div>
            <strong>上次登记结果尚未取得</strong>
            <p>
              恢复原请求将复用相同稿件、时间、条件版本与请求身份，不新建一次登记。
            </p>
            <button
              type="button"
              className="button secondary"
              disabled={command.busy}
              onClick={() =>
                void command.retry<SubmissionView>().then((result) => {
                  if (result)
                    try {
                      received(result.data);
                    } catch (failure) {
                      setError(failure);
                    }
                })
              }
            >
              恢复原登记结果
            </button>
          </div>
        </div>
      )}
      {(!basis || command.conflict) && !command.pending && (
        <button
          type="button"
          className="button secondary"
          disabled={reading || command.busy}
          onClick={() => void reread()}
        >
          {reading ? "正在核对…" : "读取当前检查依据，保留表单"}
        </button>
      )}
      {basis && (
        <p className="small-note">
          本表依据项目修订 {basis.data.bid_revision}
          。并发更新时服务端会拒绝写入，输入保留。
        </p>
      )}
      <div className="review-shortcuts">
        <button
          className="button primary"
          disabled={
            locked ||
            reading ||
            !basis?.etag ||
            (input.kind === "standard" && !gate?.allowed)
          }
        >
          {command.busy
            ? "正在保存…"
            : input.correctionId
              ? "保存追加更正"
              : input.kind === "standard"
                ? "登记实际提交"
                : "保存线下提交事实"}
        </button>
        <button
          type="button"
          className="text-button"
          disabled={locked}
          onClick={onClose}
        >
          收起表单，保留输入
        </button>
      </div>
    </form>
  );
}

function GateBlocker({
  blocker,
  onNavigate,
}: {
  blocker: GateView["blockers"][number];
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const finding = useResource<FindingView>(
    open && blocker.code === "OPEN_BLOCKING_FINDING"
      ? `/findings/${blocker.object_id}`
      : null,
  );
  const target: WorkspacePage = blocker.code.includes("IDENTITY")
    ? "settings"
    : blocker.code.includes("RULE_CONFIRMATION")
      ? "rules"
      : blocker.code.includes("BODY") || blocker.code.includes("SOURCE")
        ? "materials"
        : "review";
  return (
    <div>
      <p>{blocker.message}</p>
      {blocker.code === "OPEN_BLOCKING_FINDING" ? (
        <>
          <button
            type="button"
            className="text-button"
            onClick={() => setOpen(!open)}
          >
            {open ? "收起此阻断风险" : "定位此阻断风险与原页"}
          </button>
          {open && (
            <>
              <ResourceState
                {...finding}
                hasData={!!finding.data}
                onRetry={() => void finding.reload()}
              />
              {finding.data?.id === blocker.object_id && (
                <div className="gate-finding">
                  <p>{finding.data.statement}</p>
                  <EvidenceLinks ids={finding.data.evidence_ids} />
                  {finding.data.detection_run_state ===
                    "not_run_this_round" && (
                    <p className="small-note">
                      先前检测发现，本轮未运行；尚未有效解决。
                    </p>
                  )}
                  <button
                    type="button"
                    className="text-button"
                    onClick={() =>
                      onNavigate("review", finding.data?.origin_review_id)
                    }
                  >
                    打开发现此问题的评审轮次
                  </button>
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <button
          type="button"
          className="text-button"
          onClick={() => onNavigate(target)}
        >
          前往处理此阻断
        </button>
      )}
    </div>
  );
}

function SubmissionCard({
  bidId,
  memberId,
  record,
  onNavigate,
  onCorrect,
  onPackageCorrect,
  disabled,
}: {
  bidId: string;
  memberId: string;
  record: SingleBodySubmissionView;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
  onCorrect: () => void;
  onPackageCorrect?: () => void;
  disabled: boolean;
}) {
  return (
    <article className="submission-card">
      <div className="section-heading">
        <h3>{record.original_name}</h3>
        <Badge tone={record.kind === "offline_fact" ? "warning" : ""}>
          {record.checks_label}
        </Badge>
        <Badge>{record.current ? "当前实交记录" : "已留存的历史记录"}</Badge>
      </div>
      <p>
        实际提交于 {new Date(record.submitted_at).toLocaleString("zh-CN")} ·
        记录 {record.id.slice(0, 8)}
      </p>
      <p className="small-note">
        {record.identity
          ? `${record.identity.bidder_name} · ${record.identity.engineering_title} · 第${record.identity.round_no}轮${record.identity.binding_status === "pending" ? " · 登记时身份待确认" : ""}`
          : "登记时身份未知，不用当前身份补填"}
      </p>
      <p className="small-note">
        用户声明，未核验交易平台回执。{record.explanation}
      </p>
      {record.correction_reason && <p>更正理由：{record.correction_reason}</p>}
      {record.open_risk_snapshot ? (
        record.open_risk_snapshot.submission_id === record.id &&
        record.open_risk_snapshot.body_version_id === record.body_version_id ? (
          <details className="identity-details">
            <summary>查看实际提交时风险快照</summary>
            <p>{record.open_risk_snapshot.scope_note}</p>
            <p>
              当时风险范围：
              {record.open_risk_snapshot.basis === "unknown"
                ? "未知，不补成零风险"
                : "按当时已存在审计证据重建，不是交易平台瞬时观测"}
              。
            </p>
            <p>
              已识别{record.open_risk_snapshot.identified ?? "未知"}；未解决
              {record.open_risk_snapshot.open ?? "未知"}；有效复检解决
              {record.open_risk_snapshot.resolved ?? "未知"}；有理由驳回
              {record.open_risk_snapshot.dismissed ?? "未知"}。
            </p>
            <p>
              实际评估时点
              {new Date(
                record.open_risk_snapshot.assessment_as_of,
              ).toLocaleString("zh-CN")}
              ；系统冻结时点
              {new Date(record.open_risk_snapshot.frozen_at).toLocaleString(
                "zh-CN",
              )}
              。后续处理不改写此快照。
            </p>
          </details>
        ) : (
          <p className="notice error">实交风险快照身份不一致，请重新读取。</p>
        )
      ) : (
        <p className="small-note">
          此记录未提供可核对的当时风险快照，不补成0项。
        </p>
      )}
      {record.supersedes_id && (
        <p className="small-note">
          追加更正自记录 {record.supersedes_id.slice(0, 8)}；原记录仍在历史中。
        </p>
      )}
      <ArtifactActions
        bidId={bidId}
        documentId={record.body_version_id}
        isPdf={record.artifact_kind === "bid_body"}
        downloadLabel="下载此记录的实际提交稿"
      />
      {record.evidence_ref &&
        record.evidence_ref !== record.body_version_id && (
          <ArtifactActions
            bidId={bidId}
            documentId={record.evidence_ref}
            isPdf={false}
            downloadLabel="下载此记录的声明附件"
          />
        )}
      {record.review_id && (
        <button
          className="text-button"
          onClick={() => onNavigate("review", record.review_id ?? undefined)}
        >
          查看此实交对应评审
        </button>
      )}
      <BusinessResults bidId={bidId} memberId={memberId} submission={record} />
      {record.current && (
        <div className="review-shortcuts">
          <button
            className="button secondary"
            disabled={disabled}
            onClick={onCorrect}
          >
            追加更正此实交记录
          </button>
          {onPackageCorrect && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={onPackageCorrect}
            >
              按完整整包追加更正
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function localTime(value: string) {
  const at = new Date(value);
  return new Date(at.getTime() - at.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 19);
}
