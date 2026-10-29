import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import type {
  AdoptAuthoringOutput,
  AuthoringOutputAdopted,
  BidPackageHeadPage,
  BidPackageParsePage,
  BidPackageStoredView,
  BuildView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import DocumentParseWorkspace from "./DocumentParseWorkspace";
import { useDirectory } from "./useDirectory";
import { useResource } from "./useResource";
import {
  adoptionStorageKey,
  checkedAdoptionBase,
  readAdoption,
  validAdoptionBody,
  validateAdoption,
} from "./authoringAdoptionProtocol";
import type {
  AdoptionScope,
  PendingAdoption,
} from "./authoringAdoptionProtocol";

type Part = AdoptAuthoringOutput["member"]["parts"][number];
const roles = ["技术", "资格", "商务", "报价", "附件"];

export function AuthoringOutputAdoption({
  bidId,
  memberId,
  build,
  documentId,
  disabled = false,
  onPackages,
}: {
  bidId: string;
  memberId: string;
  build: BuildView;
  documentId: string;
  disabled?: boolean;
  onPackages?: () => void;
}) {
  const scope = { bidId, memberId, buildId: build.id, documentId };
  const [open, setOpen] = useState(() => {
    const restored = readAdoption(scope);
    return restored.blocked || !!restored.pending;
  });
  if (
    !supportsApi("POST", `/bids/${bidId}/builds/${build.id}/package-adoptions`)
  )
    return null;
  return (
    <section
      className="authoring-output-adoption"
      aria-label="采用生成文件到投标包"
    >
      <button
        type="button"
        className="button secondary"
        aria-expanded={open}
        onClick={() => setOpen((old) => !old)}
      >
        {open ? "收起文件采用" : "选择投标包并采用此文件"}
      </button>
      {open && (
        <AdoptionForm
          key={`${memberId}:${bidId}:${build.id}:${documentId}`}
          scope={scope}
          build={build}
          disabled={disabled}
          onPackages={onPackages}
        />
      )}
    </section>
  );
}

function AdoptionForm({
  scope,
  build,
  disabled,
  onPackages,
}: {
  scope: AdoptionScope;
  build: BuildView;
  disabled: boolean;
  onPackages?: () => void;
}) {
  const [restored] = useState(() => readAdoption(scope));
  const [pending, setPending] = useState(restored.pending);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const [selected, setSelected] = useState(pending?.body.package_id ?? "");
  const [purposes, setPurposes] = useState(
    pending?.body.member.purposes.join("，") ?? "技术",
  );
  const [parseId, setParseId] = useState(
    pending?.body.member.parse_run_id ?? "",
  );
  const [parts, setParts] = useState<Part[]>(pending?.body.member.parts ?? []);
  const [reason, setReason] = useState(pending?.body.reason ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [received, setReceived] = useState<AuthoringOutputAdopted | null>(null);
  const [stale, setStale] = useState(false);
  const active = useRef(true);
  const working = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const packages = useDirectory<BidPackageHeadPage>(
    `/bids/${scope.bidId}/packages?kind=bid&limit=20`,
  );
  const head = useResource<BidPackageStoredView>(
    selected ? `/bids/${scope.bidId}/packages/${selected}` : null,
  );
  const parses = useDirectory<BidPackageParsePage>(
    `/bids/${scope.bidId}/package-documents/${scope.documentId}/parses?limit=20`,
  );
  const selectedParse = parses.items.find(
    (row) =>
      row.id === parseId &&
      row.document_version_id === scope.documentId &&
      row.coverage === "complete" &&
      row.page_count > 0,
  );
  const output = build.outputs.find(
    (item) => item.document_version_id === scope.documentId,
  );
  const locked =
    disabled || busy || !!pending || restored.blocked || !!received;
  function store(value: PendingAdoption | null) {
    if (value)
      sessionStorage.setItem(adoptionStorageKey(scope), JSON.stringify(value));
    else sessionStorage.removeItem(adoptionStorageKey(scope));
    pendingRef.current = value;
    setPending(value);
  }
  async function save() {
    if (
      working.current ||
      restored.blocked ||
      received ||
      (!pendingRef.current && (disabled || stale))
    )
      return;
    working.current = true;
    setBusy(true);
    setError(null);
    let sent = false;
    let returned = false;
    try {
      let request = pendingRef.current;
      if (!request) {
        const base = selected
          ? await checkedAdoptionBase(
              head.data!,
              scope.bidId,
              selected,
              head.etag,
            )
          : null;
        if (
          selected &&
          head.data?.manifest.members.some(
            (member) => member.document_version_id === scope.documentId,
          )
        )
          throw new Error(
            "此文件已在所选包中；如需更新解析或分册，请到投标包编辑现有成员。",
          );
        if (
          parseId &&
          (!selectedParse ||
            parts.some((part) => part.last_page > selectedParse.page_count))
        )
          throw new Error("请核对精确解析与分册的物理页范围。");
        const body: AdoptAuthoringOutput = {
          snapshot_id: build.identity.snapshot_id,
          snapshot_digest: build.identity.snapshot_digest,
          package_id: base?.id ?? null,
          member: {
            member_id: `generated-${scope.documentId}`,
            document_version_id: scope.documentId,
            purposes: [
              ...new Set(
                purposes
                  .split(/[,，]/)
                  .map((item) => item.trim())
                  .filter(Boolean),
              ),
            ],
            parts: structuredClone(parts),
            ...(parseId ? { parse_run_id: parseId } : {}),
          },
          reason: reason.trim(),
        };
        if (!validAdoptionBody(body))
          throw new Error(
            "请填写用途、采用原因，并核对分册范围；未选择完整解析时不划分页范围。",
          );
        request = { version: 1, scope, key: crypto.randomUUID(), body, base };
        if (!active.current) return;
        store(request);
      }
      if (
        request.body.snapshot_id !== build.identity.snapshot_id ||
        request.body.snapshot_digest !== build.identity.snapshot_digest
      )
        throw new Error("原采用请求的固定快照无法与当前输出核对，原记录保留。");
      if (!active.current) return;
      sent = true;
      const response = await api<AuthoringOutputAdopted>(
        `/bids/${scope.bidId}/builds/${scope.buildId}/package-adoptions`,
        {
          method: "POST",
          body: request.body,
          key: request.key,
          etag: request.base?.etag,
        },
      );
      returned = true;
      if (!active.current) return;
      const ack = await validateAdoption(
        response.data,
        request,
        build,
        response.etag,
      );
      if (!active.current) return;
      store(null);
      setReceived(ack);
      window.dispatchEvent(new Event("server-snapshot-change"));
    } catch (failure) {
      if (!active.current) return;
      if (
        sent &&
        !returned &&
        failure instanceof ApiError &&
        !failure.retryable &&
        [400, 409, 412, 422].includes(failure.status) &&
        !["IDEMPOTENCY_CONFLICT", "COMMAND_INCOMPLETE"].includes(failure.code)
      ) {
        try {
          store(null);
        } catch {
          setError(
            new Error("无法更新采用恢复记录，原请求仍需按原 key 核对。"),
          );
          return;
        }
        if (failure.status === 412) setStale(true);
      }
      setError(
        failure instanceof DOMException
          ? new Error(
              sent
                ? "采用请求已发送，但浏览器未能更新恢复记录；请保留原记录并按原 key 核对。"
                : "浏览器无法保存采用恢复记录，本次尚未发送。请释放存储空间后重试。",
            )
          : failure,
      );
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div className="authoring-adoption-form">
      <p className="small-note">
        将本次草稿修订 {build.identity.draft_revision} 的
        {output?.format === "docx" ? " Word" : " PDF"}
        加入明确选择的投标包。所选包的其他文件会完整保留，本次新增一个冻结修订。
      </p>
      {output?.format === "docx" && (
        <p className="notice neutral">
          Word 可先作为未解析原件保存。原页核查需使用受控生成的
          PDF，并明确选择已完成的解析与分册范围。
        </p>
      )}
      {output?.format === "pdf" && (
        <p className="small-note">
          采用前将核对实际字节、固定快照及同一次构建的 Word→PDF
          关系；转换覆盖不完整的 PDF 仍可下载，但不能通过此处的采用资格检查。
        </p>
      )}
      <fieldset disabled={locked}>
        <legend>本次采用范围</legend>
        <label>
          目标投标包
          <select
            aria-label="采用到哪个投标包"
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value);
              setStale(false);
            }}
          >
            <option value="">新建投标包</option>
            {pending?.body.package_id &&
              !packages.items.some(
                (row) => row.id === pending.body.package_id,
              ) && (
                <option value={pending.body.package_id}>
                  原请求投标包 {pending.body.package_id.slice(0, 8)}
                </option>
              )}
            {packages.items
              .filter((row) => row.bid_id === scope.bidId && row.kind === "bid")
              .map((row) => (
                <option key={row.id} value={row.id}>
                  投标包 {row.id.slice(0, 8)} · 修订 {row.revision}
                </option>
              ))}
          </select>
        </label>
        {packages.hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={packages.moreBusy}
            onClick={() => void packages.loadMore()}
          >
            加载更多投标包
          </button>
        )}
        <ResourceState
          {...packages}
          hasData={!!packages.data}
          onRetry={() => void packages.reload()}
        />
        <ErrorNotice error={packages.moreError} />
        {selected && (
          <>
            <ResourceState
              {...head}
              hasData={!!head.data}
              onRetry={() => void head.reload()}
            />
            {head.data?.manifest.package_id === selected && (
              <p className="small-note">
                当前所选包修订 {head.data.manifest.revision}，含{" "}
                {head.data.manifest.members.length}{" "}
                个文件；保存会以这个版本令牌核对。
              </p>
            )}
          </>
        )}
        <label>
          文件用途
          <input
            aria-label="采用文件用途"
            list={`adoption-purposes-${scope.documentId}`}
            value={purposes}
            onChange={(event) => setPurposes(event.target.value)}
          />
        </label>
        <datalist id={`adoption-purposes-${scope.documentId}`}>
          {roles.map((role) => (
            <option key={role} value={role} />
          ))}
        </datalist>
        <p className="small-note">
          可填写技术、资格、商务、报价、附件；多个用途以逗号分隔。
        </p>
        <label>
          采用的精确解析
          <select
            aria-label="采用的精确解析"
            value={parseId}
            onChange={(event) => {
              const value = parses.items.find(
                (row) => row.id === event.target.value,
              );
              setParseId(event.target.value);
              setParts(
                value
                  ? [
                      {
                        part_id: `part-${crypto.randomUUID()}`,
                        category: purposes.split(/[,，]/)[0] || "技术",
                        first_page: 1,
                        last_page: value.page_count,
                        shared_attachment: false,
                        heading_path: [],
                      },
                    ]
                  : [],
              );
            }}
          >
            <option value="">先保存原件，暂不冻结解析与页范围</option>
            {parseId && !parses.items.some((row) => row.id === parseId) && (
              <option value={parseId}>原请求解析 {parseId.slice(0, 8)}</option>
            )}
            {parses.items
              .filter((row) => row.document_version_id === scope.documentId)
              .map((row) => (
                <option
                  key={row.id}
                  value={row.id}
                  disabled={row.coverage !== "complete" || row.page_count < 1}
                >
                  {row.id.slice(0, 8)} · {row.page_count} 页 ·{" "}
                  {row.coverage === "complete"
                    ? "完整标记，保存时重核"
                    : "存在解析缺口，不能冻结"}
                </option>
              ))}
          </select>
        </label>
        <ResourceState
          {...parses}
          hasData={!!parses.data}
          onRetry={() => void parses.reload()}
        />
        {parses.hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={parses.moreBusy}
            onClick={() => void parses.loadMore()}
          >
            加载更多解析记录
          </button>
        )}
        <ErrorNotice error={parses.moreError} />
        {parts.map((part, index) => (
          <div key={part.part_id} className="authoring-adoption-part">
            <label>
              分册 {index + 1} 类别
              <input
                aria-label={`采用分册 ${index + 1} 类别`}
                value={part.category}
                onChange={(event) =>
                  setParts((old) =>
                    old.map((item, i) =>
                      i === index
                        ? { ...item, category: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label>
              起始物理页
              <input
                aria-label={`采用分册 ${index + 1} 起始页`}
                type="number"
                min={1}
                max={selectedParse?.page_count}
                value={part.first_page}
                onChange={(event) =>
                  setParts((old) =>
                    old.map((item, i) =>
                      i === index
                        ? { ...item, first_page: Number(event.target.value) }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label>
              末物理页
              <input
                aria-label={`采用分册 ${index + 1} 末页`}
                type="number"
                min={1}
                max={selectedParse?.page_count}
                value={part.last_page}
                onChange={(event) =>
                  setParts((old) =>
                    old.map((item, i) =>
                      i === index
                        ? { ...item, last_page: Number(event.target.value) }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={part.shared_attachment}
                onChange={(event) =>
                  setParts((old) =>
                    old.map((item, i) =>
                      i === index
                        ? { ...item, shared_attachment: event.target.checked }
                        : item,
                    ),
                  )
                }
              />
              此范围为共享附件，允许与同样声明的范围重叠
            </label>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                setParts((old) => old.filter((_, i) => i !== index))
              }
            >
              移除此分册范围
            </button>
          </div>
        ))}
        {!!selectedParse && (
          <button
            type="button"
            className="text-button"
            onClick={() =>
              setParts((old) => [
                ...old,
                {
                  part_id: `part-${crypto.randomUUID()}`,
                  category: "附件",
                  first_page: 1,
                  last_page: selectedParse.page_count,
                  shared_attachment: false,
                  heading_path: [],
                },
              ])
            }
          >
            增加逻辑分册范围
          </button>
        )}
        <label>
          采用原因
          <textarea
            aria-label="生成文件采用原因"
            rows={2}
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </fieldset>
      {stale && !pending && (
        <div className="notice warning">
          <p>
            所选投标包已有新修订，本地文件与分册选择保留。请读取并核对新包后重新明确保存。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || head.loading}
            onClick={async () => {
              await head.reload();
              if (active.current) setStale(false);
            }}
          >
            读取最新包并继续核对
          </button>
        </div>
      )}
      {pending && (
        <p className="notice warning">
          采用结果尚未确认。恢复会沿用原文件、原包版本与原
          key；当前包变化不会替换原请求。
        </p>
      )}
      {restored.blocked && (
        <p role="alert" className="notice error">
          采用恢复记录无法核对，原记录已保留，停止新请求。请先从投标包历史核对。
        </p>
      )}
      <ErrorNotice error={error} />
      {!received && (
        <button
          type="button"
          className="button primary"
          disabled={
            busy ||
            restored.blocked ||
            (!pending &&
              (disabled ||
                stale ||
                !reason.trim() ||
                !purposes.trim() ||
                (!!selected &&
                  (!head.data || !head.etag || head.loading || !!head.error))))
          }
          onClick={() => void save()}
        >
          {busy
            ? "正在核对并采用…"
            : pending
              ? "恢复原文件采用请求"
              : selected
                ? "采用文件并保存包新修订"
                : "采用文件并新建投标包"}
        </button>
      )}
      {received && (
        <div role="status" className="notice success">
          <p>
            生成文件已采用到投标包{" "}
            {received.package.manifest.package_id.slice(0, 8)}，修订{" "}
            {received.package.manifest.revision}。
            {received.package.manifest.members.at(-1)?.parse.status ===
            "not_frozen"
              ? "此文件尚未冻结解析与页范围。"
              : "已冻结本次明确选择的解析与分册。"}
          </p>
          <p>资料包保存结果不代表评审完成或内容通过。</p>
        </div>
      )}
      {received && output?.format === "pdf" && (
        <DocumentParseWorkspace
          bidId={scope.bidId}
          memberId={scope.memberId}
          documentId={scope.documentId}
          disabled={disabled}
          onParsed={() => void parses.reload()}
        />
      )}
      {onPackages && (
        <button type="button" className="text-button" onClick={onPackages}>
          打开投标包与原件解析
        </button>
      )}
    </div>
  );
}
