import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import type {
  BidPackageStoredView,
  CreatePackageCoverageAttempt,
  PackageCoverageAttemptView,
  PackageRequirementInventoryView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { CoverageEditor, type CoverageEditorValue } from "./CoverageEditor";
import "./PackageCoverageWorkspace.css";

type Props = {
  bidId: string;
  memberId: string;
  packageView: BidPackageStoredView;
  authorityView: BidPackageStoredView | null;
  inventory: PackageRequirementInventoryView | null;
  currentInventoryId: string | null;
  currentKnown: boolean;
  disabled: boolean;
  onSaved: (inventoryId: string, attemptId: string) => void;
  onPendingChange?: (locked: boolean) => void;
};
type Context = {
  inventory: PackageRequirementInventoryView;
  authority: BidPackageStoredView;
};
type Pending = {
  version: 1;
  scope: {
    bidId: string;
    memberId: string;
    packageId: string;
    revisionId: string;
    digest: string;
  };
  context: Context;
  body: CreatePackageCoverageAttempt;
  key: string;
};
const sha = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const states = [
  "not_provided",
  "missing",
  "pending_parse",
  "parse_gap",
  "unsupported",
  "verified",
  "not_applicable",
  "conflict",
  "unknown",
];
const identifier = (s: unknown): s is string =>
  typeof s === "string" &&
  !!s.trim() &&
  Array.from(s).length <= 200 &&
  !s.includes("\0") &&
  !/[\uD800-\uDFFF]/u.test(s);
const keyFor = (s: Pending["scope"]) =>
  `tender:coverage-pending:${s.memberId}:${s.bidId}:${s.packageId}:${s.revisionId}`;
function sameContext(
  context: Context | undefined,
  own: BidPackageStoredView,
  bidId: string,
): context is Context {
  const inv = context?.inventory,
    authority = context?.authority;
  if (
    !inv ||
    !authority ||
    !sha.test(inv.digest) ||
    !sha.test(authority.digest)
  )
    return false;
  const m = inv.manifest,
    p = own.manifest,
    a = authority.manifest;
  return (
    uuid.test(m.id) &&
    m.bid_id === bidId &&
    m.package_id === p.package_id &&
    m.target_revision_id === p.revision_id &&
    m.package_digest === own.digest &&
    a.kind === "authority" &&
    a.revision_id === m.authority_revision_id &&
    m.authority_digest === authority.digest &&
    Object.keys(p.scope).every(
      (k) =>
        a.scope[k as keyof typeof p.scope] ===
        p.scope[k as keyof typeof p.scope],
    ) &&
    Array.isArray(m.requirements) &&
    m.requirements.every(
      (r) =>
        uuid.test(r.rule_id) &&
        sha.test(r.requirement_digest) &&
        r.requirement.requirement_id === r.rule_id &&
        Object.keys(p.scope).every(
          (k) =>
            r.requirement.scope[k as keyof typeof p.scope] ===
            p.scope[k as keyof typeof p.scope],
        ),
    )
  );
}
function validBody(
  body: CreatePackageCoverageAttempt,
  context: Context,
  own: BidPackageStoredView,
) {
  if (
    !body ||
    Object.keys(body).sort().join(",") !==
      "inventory_digest,package_digest,results" ||
    body.inventory_digest !== context.inventory.digest ||
    body.package_digest !== own.digest ||
    !Array.isArray(body.results) ||
    body.results.length < 1 ||
    body.results.length > 500
  )
    return false;
  const seen = new Set<string>();
  return body.results.every((r) => {
    const binding = context.inventory.manifest.requirements.find(
      (b) => b.rule_id === r?.rule_id,
    );
    if (!binding || seen.has(r.rule_id)) return false;
    seen.add(r.rule_id);
    const declaration = r.state === "verified" || r.state === "not_applicable";
    const targets = own.manifest.members
      .flatMap((m) => m.parts)
      .filter((p) =>
        binding.requirement.target_part_ids.length
          ? binding.requirement.target_part_ids.includes(p.part_id)
          : binding.requirement.categories.includes(p.category),
      );
    return (
      Object.keys(r).sort().join(",") ===
        "basis_type,evidence_ids,inspected,reason,requirement_digest,rule_id,state" &&
      r.requirement_digest === binding.requirement_digest &&
      states.includes(r.state) &&
      identifier(r.reason) &&
      r.basis_type ===
        (declaration ? "human_scope_declaration" : "human_observation") &&
      Array.isArray(r.evidence_ids) &&
      r.evidence_ids.length <= 500 &&
      new Set(r.evidence_ids).size === r.evidence_ids.length &&
      r.evidence_ids.every((id) => typeof id === "string" && uuid.test(id)) &&
      (!declaration || r.evidence_ids.length > 0) &&
      Array.isArray(r.inspected) &&
      r.inspected.every(
        (range) =>
          Object.keys(range).sort().join(",") ===
            "first_page,last_page,part_id" &&
          targets.some(
            (p) =>
              p.part_id === range.part_id &&
              Number.isSafeInteger(range.first_page) &&
              Number.isSafeInteger(range.last_page) &&
              p.first_page <= range.first_page &&
              range.first_page <= range.last_page &&
              range.last_page <= p.last_page,
          ),
      )
    );
  });
}
function restore(scope: Pending["scope"], own: BidPackageStoredView) {
  try {
    const raw = sessionStorage.getItem(keyFor(scope));
    if (!raw) return { pending: null, blocked: false };
    const value = JSON.parse(raw) as Pending;
    if (
      value.version !== 1 ||
      !value.scope ||
      Object.keys(scope).some(
        (k) =>
          scope[k as keyof typeof scope] !==
          value.scope[k as keyof typeof scope],
      ) ||
      typeof value.key !== "string" ||
      !uuid.test(value.key) ||
      !sameContext(value.context, own, scope.bidId) ||
      !validBody(value.body, value.context, own)
    )
      throw new Error("invalid pending coverage");
    return { pending: value, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}

export function PackageCoverageWorkspace({
  bidId,
  memberId,
  packageView,
  authorityView,
  inventory,
  currentInventoryId,
  currentKnown,
  disabled,
  onSaved,
  onPendingChange,
}: Props) {
  const p = packageView.manifest;
  const scope: Pending["scope"] = {
    bidId,
    memberId,
    packageId: p.package_id,
    revisionId: p.revision_id,
    digest: packageView.digest,
  };
  const [recovery] = useState(() => restore(scope, packageView));
  const [pending, setPending] = useState<Pending | null>(recovery.pending);
  const [draft, setDraft] = useState<{
    context: Context;
    initialResults: CreatePackageCoverageAttempt["results"];
    serial: number;
  } | null>(() =>
    recovery.pending
      ? {
          context: recovery.pending.context,
          initialResults: recovery.pending.body.results,
          serial: 1,
        }
      : null,
  );
  const [value, setValue] = useState<CoverageEditorValue>({
    results: [],
    valid: false,
    dirty: false,
  });
  const onChange = useCallback(
    (next: CoverageEditorValue) => setValue(next),
    [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    onPendingChange?.(busy || !!pending || recovery.blocked);
  }, [busy, pending, recovery.blocked, onPendingChange]);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const selected =
    inventory && authorityView
      ? { inventory, authority: authorityView }
      : undefined;
  const selectedValid = sameContext(selected, packageView, bidId);
  const prefix = `/bids/${bidId}/packages/${p.package_id}/revisions/${p.revision_id}/requirement-inventories`;
  const available = supportsApi(
    "POST",
    `${prefix}/${inventory?.manifest.id ?? "_"}/coverage-attempts`,
  );
  const locked = disabled || busy || !!pending || recovery.blocked;
  const draftCurrent =
    !!draft &&
    currentKnown &&
    draft.context.inventory.manifest.id === currentInventoryId;
  const canStart =
    available &&
    !locked &&
    !draft &&
    selectedValid &&
    currentKnown &&
    inventory?.manifest.id === currentInventoryId;
  const canSave =
    !!draft &&
    !locked &&
    draftCurrent &&
    value.valid &&
    validBody(
      {
        inventory_digest: draft.context.inventory.digest,
        package_digest: packageView.digest,
        results: value.results,
      },
      draft.context,
      packageView,
    );
  function begin() {
    if (!canStart || !selected) return;
    setDraft({
      context: structuredClone(selected),
      initialResults: [],
      serial: Date.now(),
    });
    setValue({ results: [], valid: false, dirty: false });
    setError(null);
    setNotice("");
  }
  async function save() {
    if (busy || recovery.blocked || (!pending && !canSave)) return;
    const operation: Pending = pending ?? {
      version: 1,
      scope,
      context: draft!.context,
      key: crypto.randomUUID(),
      body: {
        inventory_digest: draft!.context.inventory.digest,
        package_digest: packageView.digest,
        results: structuredClone(value.results),
      },
    };
    setBusy(true);
    setError(null);
    setNotice("");
    let sent = false;
    try {
      sessionStorage.setItem(keyFor(scope), JSON.stringify(operation));
      setPending(operation);
      sent = true;
      const result = await api<PackageCoverageAttemptView>(
        `${prefix}/${operation.context.inventory.manifest.id}/coverage-attempts`,
        { method: "POST", key: operation.key, body: operation.body },
      );
      if (!active.current) return;
      const saved = result.data.manifest;
      if (
        !sha.test(result.data.digest) ||
        !uuid.test(saved.id) ||
        saved.bid_id !== bidId ||
        saved.actor_id !== memberId ||
        saved.inventory_id !== operation.context.inventory.manifest.id ||
        saved.inventory_digest !== operation.body.inventory_digest ||
        saved.package_digest !== operation.body.package_digest ||
        saved.review_ready !== false ||
        saved.assessment.complete !== false ||
        saved.assessment.package_digest !== operation.body.package_digest ||
        saved.assessment.requirement_inventory_complete !== false ||
        operation.context.inventory.manifest.requirements.some(
          (binding) =>
            saved.assessment.requirement_digests[binding.rule_id] !==
              binding.requirement_digest ||
            saved.assessment.requirement_states[binding.rule_id] !==
              (operation.body.results.find(
                (row) => row.rule_id === binding.rule_id,
              )?.state ?? "unknown"),
        ) ||
        saved.results.length !== operation.body.results.length ||
        operation.body.results.some(
          (request) =>
            !saved.results.some(
              (row) =>
                row.coverage.requirement_id === request.rule_id &&
                row.coverage.package_digest === operation.body.package_digest &&
                row.coverage.requirement_digest ===
                  request.requirement_digest &&
                row.coverage.state === request.state &&
                row.basis_type === request.basis_type &&
                row.coverage.reason === request.reason &&
                row.coverage.inspected.length === request.inspected.length &&
                row.coverage.inspected.every(
                  (range, i) =>
                    range.part_id === request.inspected[i].part_id &&
                    range.first_page === request.inspected[i].first_page &&
                    range.last_page === request.inspected[i].last_page,
                ) &&
                JSON.stringify(row.evidence_ids) ===
                  JSON.stringify(request.evidence_ids) &&
                JSON.stringify(row.coverage.evidence_refs) ===
                  JSON.stringify(
                    request.evidence_ids.map((id) => `evidence:${id}`),
                  ),
            ),
        )
      )
        throw new Error("范围声明响应身份或内容不一致，保留原操作待核对。");
      sessionStorage.removeItem(keyFor(scope));
      setPending(null);
      setDraft(null);
      setNotice(
        "已保存本次人工范围记录；未记录条款保持未知，整包完整性与正式审查资格仍未取得。",
      );
      onSaved(saved.inventory_id, saved.id);
    } catch (failure) {
      if (!active.current) return;
      setError(
        sent
          ? failure
          : new Error(
              "本地操作记录无法保存，请求尚未发送。请恢复浏览器存储后重试。",
            ),
      );
      if (
        failure instanceof ApiError &&
        [409, 412, 422, 428].includes(failure.status) &&
        !failure.retryable &&
        (!pending ||
          failure.code.startsWith("PACKAGE_") ||
          failure.code === "PROJECT_WORK_CLOSED")
      ) {
        try {
          sessionStorage.removeItem(keyFor(scope));
          setPending(null);
          setDraft({
            context: operation.context,
            initialResults: operation.body.results,
            serial: Date.now(),
          });
          setValue({
            results: operation.body.results,
            valid: false,
            dirty: true,
          });
        } catch {
          setError(new Error("无法清理本地未决记录，保留原请求等待核对。"));
        }
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section
      className="package-coverage-workspace"
      aria-label="填写人工范围记录"
    >
      <h4>填写人工范围记录</h4>
      <p>
        每次单独记录实际检查的条款与页段，不拼接上次结论。人工声明已检查范围不表示材料合规、评分通过或正式审查通过。
      </p>
      {!inventory && !pending && <p>先在上方读取一版要求清单。</p>}
      {inventory && !selectedValid && !pending && (
        <p>请在上方选择与这版清单一致的权威依据包修订，再开始填写。</p>
      )}
      {inventory &&
        currentKnown &&
        currentInventoryId !== inventory.manifest.id &&
        !pending && <p>所选为历史清单，仅可追溯；新记录须明确读取当前清单。</p>}
      {!draft && (
        <button
          type="button"
          className="button secondary"
          disabled={!canStart}
          onClick={begin}
        >
          开始填写本次人工范围记录
        </button>
      )}
      {draft && (
        <>
          <p>
            本次固定清单修订 {draft.context.inventory.manifest.revision}
            ，不随其他历史选择切换。
          </p>
          {!draftCurrent && !pending && (
            <p role="alert">
              当前清单状态未知或已变化，保留原填写；请核对当前清单，不能自动套用新版本。
            </p>
          )}
          <CoverageEditor
            key={draft.serial}
            bidId={bidId}
            packageView={packageView}
            authorityView={draft.context.authority}
            inventory={draft.context.inventory}
            disabled={locked}
            initialResults={draft.initialResults}
            onChange={onChange}
          />
          <div className="coverage-workspace-actions">
            <button
              type="button"
              className="button"
              disabled={!canSave}
              onClick={() => void save()}
            >
              保存本次人工范围记录
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy || !!pending || recovery.blocked}
              onClick={() => {
                setDraft(null);
                setError(null);
              }}
            >
              放弃未发送或已明确失败的填写
            </button>
          </div>
        </>
      )}
      {recovery.blocked && (
        <p role="alert">
          本地未决范围记录损坏或范围不符，创建已锁定。请保留原记录核对，不能另发新操作。
        </p>
      )}
      {pending && (
        <div role="status">
          <p>
            保存结果未知，已保留原清单、完整内容及幂等键。刷新后仍可重试原操作；不能改成新清单或另发新键。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={() => void save()}
          >
            重试原人工范围操作
          </button>
        </div>
      )}
      {!!error && <ErrorNotice error={error} />}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
