import { useEffect, useRef, useState } from "react";
import { api, ApiError, roleNames, supportsApi } from "./api";
import type {
  AppendBidPackage,
  BidPackageDocumentPage,
  BidPackageHeadPage,
  BidPackageParsePage,
  BidPackageRevisionSummaryPage,
  BidPackageStoredView,
  CreateBidPackage,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";
import { useResource } from "./useResource";
import { PackageRequirements } from "./PackageRequirements";
import DocumentParseWorkspace from "./DocumentParseWorkspace";

type Member = CreateBidPackage["members"][number];
type Part = Member["parts"][number];
type Document = BidPackageDocumentPage["items"][number];
type Base = { id: string; etag: string };
type Pending = {
  version: 1;
  bidId: string;
  memberId: string;
  kind: CreateBidPackage["kind"];
  base: Base | null;
  body: CreateBidPackage | AppendBidPackage;
  key: string;
};
function pendingStorage(bidId: string, memberId: string) {
  return `tender:package-pending:${memberId}:${bidId}`;
}
function restorePending(
  bidId: string,
  memberId: string,
): { pending: Pending | null; blocked: boolean } {
  try {
    const raw = sessionStorage.getItem(pendingStorage(bidId, memberId));
    if (!raw) return { pending: null, blocked: false };
    const value = JSON.parse(raw) as Pending;
    if (
      value.version !== 1 ||
      value.bidId !== bidId ||
      value.memberId !== memberId ||
      !["bid", "authority"].includes(value.kind) ||
      typeof value.key !== "string" ||
      !value.key ||
      (value.base !== null &&
        (!value.base ||
          typeof value.base.id !== "string" ||
          typeof value.base.etag !== "string")) ||
      !Array.isArray(value.body?.members) ||
      !value.body.members.length ||
      !value.body.members.every(
        (m) =>
          typeof m.member_id === "string" &&
          typeof m.document_version_id === "string" &&
          Array.isArray(m.purposes) &&
          m.purposes.every((p) => typeof p === "string") &&
          Array.isArray(m.parts) &&
          m.parts.every(
            (p) =>
              typeof p.part_id === "string" &&
              typeof p.category === "string" &&
              typeof p.first_page === "number" &&
              typeof p.last_page === "number" &&
              Array.isArray(p.heading_path),
          ),
      )
    )
      throw new Error("invalid pending");
    return { pending: value, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}

export function BidPackages({
  bidId,
  memberId = "current",
  disabled = false,
}: {
  bidId: string;
  memberId?: string;
  disabled?: boolean;
}) {
  if (!supportsApi("GET", `/bids/${bidId}/packages`)) return null;
  return (
    <PackageWorkspace
      key={`${bidId}:${memberId}`}
      bidId={bidId}
      memberId={memberId}
      disabled={disabled}
    />
  );
}

function PackageWorkspace({
  bidId,
  memberId,
  disabled,
}: {
  bidId: string;
  memberId: string;
  disabled: boolean;
}) {
  const path = `/bids/${bidId}/packages`;
  const [recovery] = useState(() => restorePending(bidId, memberId));
  const [pending, setPending] = useState<Pending | null>(recovery.pending);
  const [kind, setKind] = useState<CreateBidPackage["kind"]>(
    pending?.kind ?? "bid",
  );
  const [draft, setDraft] = useState<Member[]>(() =>
    structuredClone(pending?.body.members ?? []),
  );
  const [base, setBase] = useState<Base | null>(pending?.base ?? null);
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [candidateBase, setCandidateBase] = useState<
    (Base & { digest: string; revision: number }) | null
  >(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const packages = useDirectory<BidPackageHeadPage>(
    `${path}?kind=${kind}&limit=20`,
  );
  const documents = useDirectory<BidPackageDocumentPage>(
    `/bids/${bidId}/package-documents?kind=${kind}&limit=20`,
  );
  const history = useDirectory<BidPackageRevisionSummaryPage>(
    selected ? `${path}/${selected}/revisions?limit=20` : null,
  );
  const view = useResource<BidPackageStoredView>(
    selected
      ? `${path}/${selected}${revision ? `/revisions/${revision}` : ""}`
      : null,
  );
  const verifiedView =
    view.data?.manifest.scope.bid_id === bidId &&
    view.data.manifest.package_id === selected &&
    (!revision || view.data.manifest.revision_id === revision)
      ? view.data
      : undefined;

  function patch(id: string, value: Partial<Member>) {
    setDraft((old) =>
      old.map((m) => (m.document_version_id === id ? { ...m, ...value } : m)),
    );
  }
  async function editCurrent() {
    if (!selected || busy || draft.length) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<BidPackageStoredView>(`${path}/${selected}`);
      if (!active.current) return;
      if (
        !result.etag ||
        result.data.manifest.scope.bid_id !== bidId ||
        result.data.manifest.package_id !== selected
      )
        throw new Error("资料包身份或版本响应不一致，请重新读取。");
      setBase({ id: selected, etag: result.etag });
      setKind(result.data.manifest.kind);
      setDraft(
        result.data.manifest.members.map((m) => ({
          member_id: m.member_id,
          document_version_id: m.document_version_id,
          ...(m.parse.parse_run_id
            ? { parse_run_id: m.parse.parse_run_id }
            : {}),
          purposes: [...m.purposes],
          parts: structuredClone(m.parts),
        })),
      );
      setNotice("本地选择来自刚读取的当前修订；修改后将保存为新修订。");
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function save() {
    if (
      !draft.length ||
      busy ||
      (!pending && disabled) ||
      conflict ||
      recovery.blocked
    )
      return;
    if (
      !pending &&
      draft.some(
        (m) =>
          !m.purposes.length ||
          new Set(m.purposes).size !== m.purposes.length ||
          m.purposes.some(
            (p) =>
              !p.trim() ||
              Array.from(p).length > 200 ||
              p.includes("\0") ||
              /[\uD800-\uDFFF]/u.test(p),
          ) ||
          (!!m.parse_run_id && !m.parts.length) ||
          m.parts.some(
            (p) =>
              !p.category.trim() ||
              Array.from(p.category).length > 200 ||
              p.category.includes("\0") ||
              /[\uD800-\uDFFF]/u.test(p.category) ||
              !Number.isSafeInteger(p.first_page) ||
              !Number.isSafeInteger(p.last_page) ||
              p.first_page < 1 ||
              p.last_page < p.first_page,
          ),
      )
    ) {
      setError(
        new Error(
          "请填写有效且不重复的用途；选择精确解析后须明确逻辑页段，页码使用正整数且结束页不小于起始页。",
        ),
      );
      return;
    }
    setBusy(true);
    setError(null);
    setNotice("");
    const body: CreateBidPackage | AppendBidPackage = base
      ? { members: draft }
      : { kind, members: draft };
    const operation: Pending = pending ?? {
      version: 1,
      bidId,
      memberId,
      kind,
      base: base ? { id: base.id, etag: base.etag } : null,
      body: structuredClone(body),
      key: crypto.randomUUID(),
    };
    const endpoint = operation.base
      ? `${path}/${operation.base.id}/revisions`
      : path;
    let sent = false;
    try {
      sessionStorage.setItem(
        pendingStorage(bidId, memberId),
        JSON.stringify(operation),
      );
      setPending(operation);
      sent = true;
      const result = await api<BidPackageStoredView>(endpoint, {
        method: "POST",
        body: operation.body,
        etag: operation.base?.etag,
        key: operation.key,
      });
      if (!active.current) return;
      if (
        result.data.manifest.scope.bid_id !== bidId ||
        result.data.manifest.kind !== operation.kind ||
        (operation.base &&
          result.data.manifest.package_id !== operation.base.id)
      )
        throw new Error("保存结果项目身份不一致，请重新读取。");
      sessionStorage.removeItem(pendingStorage(bidId, memberId));
      setPending(null);
      setSelected(result.data.manifest.package_id);
      setRevision(result.data.manifest.revision_id);
      setDraft([]);
      setBase(null);
      setNotice(
        `已保存修订 ${result.data.manifest.revision}。这是该次操作的冻结记录；当前版本请单独读取。`,
      );
      void packages.reload();
    } catch (failure) {
      if (active.current) {
        setError(failure);
        const definitive =
          failure instanceof ApiError &&
          failure.status >= 400 &&
          failure.status < 500 &&
          (!pending ||
            ["REVISION_CONFLICT", "PROJECT_WORK_CLOSED"].includes(
              failure.code,
            ) ||
            failure.code.startsWith("PACKAGE_"));
        if (definitive) {
          try {
            sessionStorage.removeItem(pendingStorage(bidId, memberId));
            setPending(null);
          } catch {
            setError(
              new Error(
                "无法更新本地操作记录；请保留原操作，恢复浏览器存储后再核对。",
              ),
            );
          }
        } else if (!sent) {
          setError(
            new Error(
              "无法保存本地待核操作，请求尚未发送。请恢复浏览器存储后重试；原未决记录仍保留。",
            ),
          );
        }
        if (failure instanceof ApiError && failure.status === 412)
          setConflict(true);
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function inspectConflict() {
    if (!base) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<BidPackageStoredView>(`${path}/${base.id}`);
      if (!active.current) return;
      if (
        !result.etag ||
        result.data.manifest.scope.bid_id !== bidId ||
        result.data.manifest.package_id !== base.id
      )
        throw new Error("最新资料包身份不一致。");
      setCandidateBase({
        id: base.id,
        etag: result.etag,
        digest: result.data.digest,
        revision: result.data.manifest.revision,
      });
      setSelected(base.id);
      setRevision("");
      await view.reload();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section
      className="panel bid-package-workspace"
      aria-label="整份标书资料包"
    >
      <div className="panel-heading">
        <div>
          <h2>整份标书资料包</h2>
          <p className="muted">
            按版本保存权威依据与本方标书，不自动选择最后上传的正文。
          </p>
        </div>
        <Badge>尚未接入正式评审</Badge>
      </div>
      <p className="notice neutral">
        保存只冻结本次选择的原件、解析和逻辑范围；不代表材料齐全、合规、评分通过或正式提交。未选择明确解析的原件将保持未冻结。
      </p>
      {disabled && (
        <p className="notice warning">
          当前项目暂不可新增工作，已保存资料包与历史仍可查看。
        </p>
      )}
      {recovery.blocked && (
        <p className="notice warning">
          本地待核保存记录无法恢复。请先核对服务器资料包记录；为避免重复保存，这里暂停新增操作。
        </p>
      )}
      {pending && (
        <p className="notice warning" role="status">
          上次保存结果尚待确认，已锁定原选择、幂等键与版本基线，刷新后可继续。可查看目录核对，或使用“核对并重试原保存”取得原操作回执；不会自动另建资料包。
        </p>
      )}
      <label>
        资料包类型
        <select
          aria-label="资料包类型"
          value={kind}
          disabled={
            busy || !!draft.length || !!base || !!pending || recovery.blocked
          }
          onChange={(e) => {
            setKind(e.target.value as CreateBidPackage["kind"]);
            setSelected("");
            setRevision("");
          }}
        >
          <option value="bid">本方投标包</option>
          <option value="authority">权威依据包</option>
        </select>
      </label>
      <ResourceState
        {...packages}
        hasData={!!packages.data}
        onRetry={() => void packages.reload()}
      />
      {packages.data && !packages.items.length && (
        <p className="small-empty">尚无此类资料包，可从已入库文件明确建立。</p>
      )}
      <div className="batch-choices">
        {packages.items
          .filter((p) => p.bid_id === bidId)
          .map((p) => (
            <article key={p.id}>
              <span>
                {p.kind === "bid" ? "本方投标包" : "权威依据包"} ·{" "}
                {p.id.slice(0, 8)} · 当前修订 {p.revision}
              </span>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setSelected(p.id);
                  setRevision("");
                }}
              >
                查看资料包 {p.id.slice(0, 8)}
              </button>
            </article>
          ))}
      </div>
      {packages.hasMore && (
        <button
          className="text-button"
          disabled={packages.moreBusy}
          onClick={() => void packages.loadMore()}
        >
          加载更多资料包
        </button>
      )}
      <ErrorNotice error={packages.moreError} />
      {selected && (
        <div>
          <ResourceState
            {...view}
            hasData={!!verifiedView}
            onRetry={() => void view.reload()}
          />
          {verifiedView && (
            <>
              <h3>
                {revision ? "历史冻结记录" : "当前冻结记录"} · 修订{" "}
                {verifiedView.manifest.revision}
              </h3>
              <p className="small-note">
                主体 {verifiedView.identity.bidder_name} · 标段{" "}
                {verifiedView.identity.lot ?? "名称待核"} · 第{" "}
                {verifiedView.identity.round_no} 轮 ·{" "}
                {verifiedView.storage_eligible
                  ? "存储结构已冻结，仍待业务核验"
                  : "含未冻结或待核身份"}
              </p>
              <ul>
                {verifiedView.manifest.members.map((m, index) => (
                  <li key={m.member_id}>
                    {documents.items.find((d) => d.id === m.document_version_id)
                      ?.filename ?? `原件 ${index + 1}`}{" "}
                    ·{" "}
                    {m.parse.status === "frozen"
                      ? "解析已精确冻结"
                      : "解析未冻结"}{" "}
                    · {m.parts.length} 个逻辑范围
                  </li>
                ))}
              </ul>
              <details>
                <summary>冻结摘要与身份</summary>
                <p className="small-note">{verifiedView.digest}</p>
                <pre>{JSON.stringify(verifiedView.identity, null, 2)}</pre>
                <pre>{JSON.stringify(verifiedView.manifest, null, 2)}</pre>
              </details>
              <a
                className="text-button"
                href={`/api/v1${path}/${selected}/revisions/${verifiedView.manifest.revision_id}/manifest`}
                download
              >
                下载规范清单
              </a>
              <button
                className="button secondary"
                disabled={
                  disabled ||
                  busy ||
                  !!draft.length ||
                  !!pending ||
                  recovery.blocked
                }
                onClick={() => void editCurrent()}
              >
                基于当前修订编辑
              </button>
              {verifiedView.manifest.kind === "bid" && (
                <PackageRequirements
                  key={`${bidId}:${memberId}:${verifiedView.manifest.package_id}:${verifiedView.manifest.revision_id}`}
                  bidId={bidId}
                  memberId={memberId}
                  packageView={verifiedView}
                  disabled={disabled}
                />
              )}
            </>
          )}
          <h3>修订历史</h3>
          <ResourceState
            {...history}
            hasData={!!history.data}
            onRetry={() => void history.reload()}
          />
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              setRevision("");
              void view.reload();
            }}
          >
            读取当前修订
          </button>
          {history.items.map((r) => (
            <button
              key={r.id}
              className="text-button"
              disabled={busy}
              onClick={() => setRevision(r.id)}
            >
              查看历史修订 {r.revision}
            </button>
          ))}
          {history.hasMore && (
            <button
              className="text-button"
              disabled={history.moreBusy}
              onClick={() => void history.loadMore()}
            >
              加载更多修订
            </button>
          )}
          <ErrorNotice error={history.moreError} />
        </div>
      )}
      <h3>{base ? "编辑下一修订" : "建立新资料包"}</h3>
      <ResourceState
        {...documents}
        hasData={!!documents.data}
        onRetry={() => void documents.reload()}
      />
      {documents.data && !documents.items.length && (
        <p className="small-empty">
          没有此类已提交文件版本。先在资料入库区上传并明确入库。
        </p>
      )}
      {documents.items
        .filter((d) => d.bid_id === bidId)
        .map((document) => (
          <label className="evidence-select-item" key={document.id}>
            <input
              type="checkbox"
              aria-label={`选择 ${document.filename} 版本 ${document.file_revision}`}
              checked={draft.some((m) => m.document_version_id === document.id)}
              disabled={
                disabled ||
                !!pending ||
                recovery.blocked ||
                busy ||
                !document.verified_upload ||
                conflict ||
                document.artifact_kind !==
                  (kind === "bid" ? "bid_body" : "source_original")
              }
              onChange={(e) =>
                setDraft((old) =>
                  e.target.checked
                    ? [
                        ...old,
                        {
                          member_id: `document-${document.id}`,
                          document_version_id: document.id,
                          purposes: [kind === "bid" ? "技术" : "要求依据"],
                          parts: [],
                        },
                      ]
                    : old.filter((m) => m.document_version_id !== document.id),
                )
              }
            />
            <span>
              {document.filename} · {roleNames[document.role]} · 文件版本{" "}
              {document.file_revision}
              {!document.verified_upload && " · 上传核验依据不足"}
              {document.artifact_kind !==
                (kind === "bid" ? "bid_body" : "source_original") &&
                " · 不是此类原件"}
            </span>
          </label>
        ))}
      {documents.hasMore && (
        <button
          className="text-button"
          disabled={documents.moreBusy}
          onClick={() => void documents.loadMore()}
        >
          加载更多文件版本
        </button>
      )}
      <ErrorNotice error={documents.moreError} />
      {draft.map((m) => (
        <MemberEditor
          key={m.document_version_id}
          bidId={bidId}
          memberId={memberId}
          member={m}
          document={documents.items.find((d) => d.id === m.document_version_id)}
          disabled={
            disabled || busy || conflict || !!pending || recovery.blocked
          }
          onChange={(value) => patch(m.document_version_id, value)}
          onRemove={() =>
            setDraft((old) =>
              old.filter(
                (item) => item.document_version_id !== m.document_version_id,
              ),
            )
          }
        />
      ))}
      <ErrorNotice error={error} />
      {notice && (
        <p role="status" className="notice neutral">
          {notice}
        </p>
      )}
      {conflict && (
        <div className="notice warning">
          <p>资料包已有更新。本地选择保留，未自动覆盖或重试。</p>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void inspectConflict()}
          >
            读取最新修订，保留本地选择
          </button>
          {candidateBase && (
            <button
              className="button secondary"
              disabled={
                busy ||
                view.loading ||
                !!view.error ||
                !!revision ||
                verifiedView?.digest !== candidateBase.digest
              }
              onClick={() => {
                setBase(candidateBase);
                setConflict(false);
                setCandidateBase(null);
                setError(null);
              }}
            >
              已核对最新修订 {candidateBase.revision}，以此版本继续
            </button>
          )}
        </div>
      )}
      <div className="upload-actions">
        <button
          className="button secondary"
          disabled={
            busy || !!pending || recovery.blocked || (!draft.length && !base)
          }
          onClick={() => {
            setDraft([]);
            setBase(null);
            setConflict(false);
            setCandidateBase(null);
            setError(null);
            setNotice("已清空本地选择；服务器已保存历史仍保留。");
          }}
        >
          清空选择并新建
        </button>
        <button
          className="button primary"
          disabled={
            (!pending && disabled) ||
            busy ||
            conflict ||
            !draft.length ||
            recovery.blocked
          }
          onClick={() => void save()}
        >
          {busy
            ? "正在处理…"
            : pending
              ? "核对并重试原保存"
              : base
                ? "保存新修订"
                : "保存新资料包"}
        </button>
      </div>
    </section>
  );
}

function MemberEditor({
  bidId,
  memberId,
  member,
  document,
  disabled,
  onChange,
  onRemove,
}: {
  bidId: string;
  memberId: string;
  member: Member;
  document?: Document;
  disabled: boolean;
  onChange: (value: Partial<Member>) => void;
  onRemove: () => void;
}) {
  const [purposeText, setPurposeText] = useState(member.purposes.join(","));
  const parses = useDirectory<BidPackageParsePage>(
    `/bids/${bidId}/package-documents/${member.document_version_id}/parses?limit=20`,
  );
  function part(index: number, value: Partial<Part>) {
    onChange({
      parts: member.parts.map((p, i) => (i === index ? { ...p, ...value } : p)),
    });
  }
  return (
    <>
      <fieldset disabled={disabled}>
        <legend>{document?.filename ?? "已选原件（版本身份见详情）"}</legend>
        <button className="text-button" onClick={onRemove}>
          从本次选择移除
        </button>
        <label>
          用途（逗号分隔）
          <input
            list={`package-purposes-${member.document_version_id}`}
            aria-label={`用途 ${member.document_version_id}`}
            value={purposeText}
            onChange={(e) => {
              setPurposeText(e.target.value);
              onChange({
                purposes: e.target.value
                  .split(/[,，]/)
                  .map((s) => s.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
        <datalist id={`package-purposes-${member.document_version_id}`}>
          {["资格", "商务", "技术", "报价", "附件", "要求依据"].map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
        <p className="small-note">
          可选资格、商务、技术、报价、附件，也可输入自定义用途；多个用途以逗号分隔。
        </p>
        <details>
          <summary>原件与解析身份</summary>
          <p>文件版本 {member.document_version_id}</p>
          {parses.items.map((p) => (
            <p key={p.id}>
              {new Date(p.created_at).toLocaleString()} · {p.id} ·{" "}
              {p.parser_digest}
            </p>
          ))}
        </details>
        <ResourceState
          {...parses}
          hasData={!!parses.data}
          onRetry={() => void parses.reload()}
        />
        <label>
          明确选择解析记录
          <select
            aria-label={`解析记录 ${member.document_version_id}`}
            value={member.parse_run_id ?? ""}
            onChange={(e) =>
              onChange({ parse_run_id: e.target.value || undefined, parts: [] })
            }
          >
            <option value="">不冻结解析（未知页数，不划逻辑范围）</option>
            {member.parse_run_id &&
              !parses.items.some((p) => p.id === member.parse_run_id) && (
                <option value={member.parse_run_id}>
                  已保存的精确解析 {member.parse_run_id}（待目录核对）
                </option>
              )}
            {parses.items
              .filter(
                (p) => p.document_version_id === member.document_version_id,
              )
              .map((p) => (
                <option
                  value={p.id}
                  key={p.id}
                  disabled={p.coverage !== "complete" || p.page_count < 1}
                >
                  {new Date(p.created_at).toLocaleString()} · {p.id.slice(0, 8)}{" "}
                  ·{" "}
                  {p.coverage === "complete"
                    ? "完整标记，保存时重核"
                    : p.coverage === "partial"
                      ? "存在缺口，不可冻结"
                      : "失败，不可冻结"}{" "}
                  · {p.page_count} 页
                </option>
              ))}
          </select>
        </label>
        {parses.hasMore && (
          <button
            className="text-button"
            disabled={parses.moreBusy}
            onClick={() => void parses.loadMore()}
          >
            加载更多解析记录
          </button>
        )}
        <ErrorNotice error={parses.moreError} />
        <p className="small-note">
          更换解析会清空本地页段，需重新明确范围；不会自动选最新解析。历史已冻结记录保持原样。
        </p>
        {member.parts.map((p, index) => (
          <fieldset key={index}>
            <legend>逻辑范围 {index + 1}</legend>
            <label>
              范围分类
              <input
                aria-label={`范围分类 ${member.document_version_id} ${index}`}
                value={p.category}
                onChange={(e) => part(index, { category: e.target.value })}
              />
            </label>
            <label>
              起始物理页
              <input
                type="number"
                min="1"
                aria-label={`起始页 ${member.document_version_id} ${index}`}
                value={p.first_page}
                onChange={(e) =>
                  part(index, { first_page: Number(e.target.value) })
                }
              />
            </label>
            <label>
              结束物理页
              <input
                type="number"
                min="1"
                aria-label={`结束页 ${member.document_version_id} ${index}`}
                value={p.last_page}
                onChange={(e) =>
                  part(index, { last_page: Number(e.target.value) })
                }
              />
            </label>
            <label className="evidence-select-item">
              <input
                type="checkbox"
                checked={p.shared_attachment}
                onChange={(e) =>
                  part(index, { shared_attachment: e.target.checked })
                }
              />
              共享附件范围（仅明确重叠双方均声明时允许）
            </label>
            <button
              className="text-button"
              onClick={() =>
                onChange({ parts: member.parts.filter((_, i) => i !== index) })
              }
            >
              移除此范围
            </button>
          </fieldset>
        ))}
        <button
          className="button secondary"
          disabled={!member.parse_run_id}
          onClick={() =>
            onChange({
              parts: [
                ...member.parts,
                {
                  part_id: crypto.randomUUID(),
                  category: member.purposes[0] || "技术",
                  first_page: 1,
                  last_page: 1,
                  shared_attachment: false,
                  heading_path: [],
                },
              ],
            })
          }
        >
          添加明确逻辑范围
        </button>
      </fieldset>
      <DocumentParseWorkspace
        bidId={bidId}
        memberId={memberId}
        documentId={member.document_version_id}
        disabled={disabled}
        onParsed={() => void parses.reload()}
      />
    </>
  );
}
