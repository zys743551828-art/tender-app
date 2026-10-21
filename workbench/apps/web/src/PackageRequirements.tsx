import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, ApiError, supportsApi } from "./api";
import type {
  BidPackageHeadPage,
  BidPackageRevisionSummaryPage,
  BidPackageStoredView,
  CreatePackageRequirementInventory,
  PackageCoverageAttemptView,
  PackageRequirementHistoryPage,
  PackageRequirementInventoryPage,
  PackageRequirementInventoryView,
  RuleSetView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { PackageReviewInputPreview } from "./PackageReviewInputPreview";
import { useDirectory } from "./useDirectory";
import { useResource } from "./useResource";
import {
  emptyPackageNavigationState,
  validatePackageNavigationInventory,
  type PackageNavigationState,
} from "./packageNavigation";
import { usePackageScopeState } from "./packageScopeGuard";
import {
  RequirementCheckPlan,
  type CheckPlanValue,
} from "./RequirementCheckPlan";

const PackageCoverageWorkspace = lazy(async () => {
  const module = await import("./PackageCoverageWorkspace");
  return { default: module.PackageCoverageWorkspace };
});
const PackageRuleCorrections = lazy(async () => {
  const module = await import("./PackageRuleCorrections");
  return { default: module.PackageRuleCorrections };
});
const PackageTechnicalScope = lazy(async () => {
  const module = await import("./PackageTechnicalScope");
  return { default: module.PackageTechnicalScope };
});

type Props = {
  bidId: string;
  memberId: string;
  packageView: BidPackageStoredView;
  disabled?: boolean;
  navigation?: {
    inventoryId: string | null;
    onInventory: (inventoryId: string, replace?: boolean) => void;
    onState: (state: PackageNavigationState) => void;
  };
};
type Scope = {
  bidId: string;
  memberId: string;
  packageId: string;
  revisionId: string;
  digest: string;
};
type Context = { authority: BidPackageStoredView; rules: RuleSetView };
type Conditions = { etag: string | null; ifNoneMatch: "*" | null };
type Pending = Conditions & {
  version: 1 | 2;
  scope: Scope;
  body: CreatePackageRequirementInventory;
  key: string;
  context?: Context;
};
type Draft = Conditions & {
  context: Context;
  initialMappings: CreatePackageRequirementInventory["mappings"];
  serial: number;
  sent: boolean;
  rejected?: boolean;
};
type Rebase = Conditions & {
  head: string | null;
  view: PackageRequirementInventoryView | null;
};
const sha = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const storageKey = (scope: Scope) =>
  `tender:requirements-pending:${scope.memberId}:${scope.bidId}:${scope.packageId}:${scope.revisionId}`;
const validIdentifier = (value: unknown): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= 200 &&
  !value.includes("\0") &&
  !/[\uD800-\uDFFF]/u.test(value);
const validTime = (value: string) =>
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
    value,
  ) && !Number.isNaN(Date.parse(value));
function restore(
  scope: Scope,
  expectedScope: BidPackageStoredView["manifest"]["scope"],
): { pending: Pending | null; blocked: boolean } {
  try {
    const raw = sessionStorage.getItem(storageKey(scope));
    if (!raw) return { pending: null, blocked: false };
    const value = JSON.parse(raw) as Pending;
    if (
      ![1, 2].includes(value.version) ||
      !value.scope ||
      Object.keys(scope).some(
        (k) => value.scope[k as keyof Scope] !== scope[k as keyof Scope],
      ) ||
      typeof value.key !== "string" ||
      !uuid.test(value.key) ||
      !value.body ||
      Object.keys(value.body).sort().join(",") !==
        "authority_revision_id,mappings,rule_set_id" ||
      !uuid.test(value.body.authority_revision_id) ||
      !uuid.test(value.body.rule_set_id) ||
      !Array.isArray(value.body.mappings) ||
      (value.version === 1 && value.body.mappings.length !== 0) ||
      (value.version === 2 &&
        (!validContext(value.context, scope, value.body, expectedScope) ||
          !validMappings(value.body.mappings, value.context!))) ||
      !(
        (value.ifNoneMatch === "*" && value.etag === null) ||
        (value.ifNoneMatch === null &&
          typeof value.etag === "string" &&
          value.etag.length > 0)
      )
    )
      throw new Error("invalid pending scope");
    return { pending: value, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}
function validContext(
  context: Context | undefined,
  scope: Scope,
  body: CreatePackageRequirementInventory,
  expectedScope: BidPackageStoredView["manifest"]["scope"],
) {
  const a = context?.authority;
  const r = context?.rules;
  return !!(
    a &&
    r &&
    a.manifest?.kind === "authority" &&
    sha.test(a.digest) &&
    a.manifest.revision_id === body.authority_revision_id &&
    a.manifest.scope?.bid_id === scope.bidId &&
    Object.keys(expectedScope).every(
      (key) =>
        a.manifest.scope[key as keyof typeof expectedScope] ===
        expectedScope[key as keyof typeof expectedScope],
    ) &&
    r.bid_id === scope.bidId &&
    uuid.test(r.id) &&
    r.id === body.rule_set_id &&
    Array.isArray(r.rules) &&
    r.rules.every(
      (rule) =>
        uuid.test(rule.id) &&
        rule.rule_set_id === r.id &&
        rule.scope?.bid_id === scope.bidId,
    )
  );
}
function validMappings(
  mappings: CreatePackageRequirementInventory["mappings"],
  context: Context,
) {
  const seen = new Set<string>();
  const identifiers = (v: unknown, nonempty = false): v is string[] =>
    Array.isArray(v) &&
    (!nonempty || v.length > 0) &&
    v.every(validIdentifier) &&
    new Set(v).size === v.length;
  return mappings.every((item) => {
    const rule = context.rules.rules.find((r) => r.id === item?.rule_id);
    if (!rule || !uuid.test(item.rule_id) || seen.has(item.rule_id))
      return false;
    seen.add(item.rule_id);
    return (
      Object.keys(item).sort().join(",") ===
        "applicability,applicability_evidence_ids,basis_evidence_ids,categories,checks,minimum_count,reason,rule_id,target_part_ids,valid_at" &&
      identifiers(item.categories, true) &&
      identifiers(item.target_part_ids) &&
      identifiers(item.checks) &&
      identifiers(item.basis_evidence_ids, true) &&
      identifiers(item.applicability_evidence_ids) &&
      [...item.basis_evidence_ids, ...item.applicability_evidence_ids].every(
        (id) => uuid.test(id) && rule.evidence_ids.includes(id),
      ) &&
      (item.minimum_count === null ||
        (Number.isSafeInteger(item.minimum_count) &&
          item.minimum_count >= 0)) &&
      ["unknown", "applicable", "not_applicable"].includes(
        item.applicability,
      ) &&
      (item.applicability !== "not_applicable" ||
        item.applicability_evidence_ids.length > 0) &&
      (item.valid_at === null ||
        (typeof item.valid_at === "string" && validTime(item.valid_at))) &&
      validIdentifier(item.reason)
    );
  });
}
const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
const text = (value: unknown) => (typeof value === "string" ? value : "未记录");
const categories: Record<string, string> = {
  unclassified: "未分类",
  qualification: "资格",
  business: "商务",
  technical: "技术",
  price: "报价",
  commercial: "商务",
  attachment: "附件",
  annex: "附件",
};
const decisions: Record<string, string> = {
  confirmed: "已确认",
  rejected: "已否决",
  deferred: "暂缓",
  pending: "待确认",
};
const gapNames: Record<string, string> = {
  page_count_unknown: "页数未知",
  parts_unassigned: "逻辑范围未分配",
  parse_identity_not_frozen: "解析身份尚未冻结",
};
function inspectedLabel(
  view: BidPackageStoredView,
  partId: unknown,
  first: unknown,
  last: unknown,
) {
  for (const [fileIndex, member] of view.manifest.members.entries()) {
    const partIndex = member.parts.findIndex((part) => part.part_id === partId);
    if (partIndex >= 0) {
      const part = member.parts[partIndex];
      return `文件 ${fileIndex + 1} · 分册 ${partIndex + 1} · ${categories[part.category] ?? part.category} · 物理页 ${typeof first === "number" ? first : "待核"}—${typeof last === "number" ? last : "待核"}`;
    }
  }
  return "受检范围未能定位，须核对冻结身份";
}
const checkNames: Record<string, string> = {
  quantity: "数量逐项核对",
  expiry: "有效期",
  signature: "签字盖章",
  format: "格式要求",
  scope: "适用范围",
};
function Conditions({ value, label }: { value: unknown; label: string }) {
  const valid =
    Array.isArray(value) && value.every((v) => typeof v === "string");
  return (
    <>
      <p>
        {label}：
        {valid
          ? value.join("；") || `原规则未列${label.replace("原始", "")}`
          : "记录格式待核"}
      </p>
      {!valid && (
        <details>
          <summary>{label}原始记录</summary>
          <pre>{JSON.stringify(value ?? null, null, 2)}</pre>
        </details>
      )}
    </>
  );
}
const names: Record<string, string> = {
  unknown: "未知",
  not_provided: "未提供",
  missing: "缺项",
  pending_parse: "待解析",
  parse_gap: "解析有缺口",
  unsupported: "不支持",
  verified: "人工声明已核对范围",
  not_applicable: "人工声明不适用",
  conflict: "存在冲突",
};

export function PackageRequirements(props: Props) {
  const [expanded, setExpanded] = useState(!!props.navigation);
  const [childState, setChildState] = useState<PackageNavigationState>(
    emptyPackageNavigationState,
  );
  const reportState = props.navigation?.onState;
  const onState = useCallback(
    (state: PackageNavigationState) => {
      setChildState(state);
      reportState?.(state);
    },
    [reportState],
  );
  const m = props.packageView.manifest;
  if (
    m.kind !== "bid" ||
    m.scope.bid_id !== props.bidId ||
    !sha.test(props.packageView.digest)
  )
    return (
      <p role="alert">要求工作面的本方资料包身份不一致，未加载其他记录。</p>
    );
  return (
    <>
      <button
        type="button"
        className="button secondary requirements-toggle"
        aria-expanded={expanded}
        disabled={
          !!props.navigation &&
          (childState.busy || childState.dirty || childState.pending)
        }
        onClick={() => setExpanded((value) => !value)}
      >
        要求清单与覆盖
      </button>
      {expanded && (
        <Workspace
          key={`${props.bidId}:${props.memberId}:${m.package_id}:${m.revision_id}:${props.packageView.digest}`}
          {...props}
          navigation={
            props.navigation ? { ...props.navigation, onState } : undefined
          }
        />
      )}
    </>
  );
}

function Workspace({
  bidId,
  memberId,
  packageView,
  disabled = false,
  navigation,
}: Props) {
  const deepState = usePackageScopeState();
  const deepLocked =
    !!navigation && (deepState.busy || deepState.pending || deepState.dirty);
  const m = packageView.manifest;
  const scope: Scope = {
    bidId,
    memberId,
    packageId: m.package_id,
    revisionId: m.revision_id,
    digest: packageView.digest,
  };
  const base = `/bids/${bidId}/packages/${m.package_id}/revisions/${m.revision_id}/requirement-inventories`;
  const [recovery] = useState(() => restore(scope, m.scope));
  const [pending, setPending] = useState<Pending | null>(recovery.pending);
  const [draft, setDraft] = useState<Draft | null>(() =>
    recovery.pending?.version === 2 && recovery.pending.context
      ? {
          context: recovery.pending.context,
          initialMappings: recovery.pending.body.mappings,
          etag: recovery.pending.etag,
          ifNoneMatch: recovery.pending.ifNoneMatch,
          serial: 1,
          sent: true,
        }
      : null,
  );
  const [plan, setPlan] = useState<CheckPlanValue>({
    mappings: [],
    valid: false,
    dirty: false,
  });
  const onPlanChange = useCallback(
    (value: CheckPlanValue) => setPlan(value),
    [],
  );
  const [planStale, setPlanStale] = useState(false);
  const [needsRebase, setNeedsRebase] = useState(false);
  const [rebase, setRebase] = useState<Rebase | null>(null);
  const [emptyBaseline, setEmptyBaseline] = useState<Conditions | null>(null);
  const [authorityId, setAuthorityId] = useState(
    recovery.pending?.context?.authority.manifest.package_id ?? "",
  );
  const [authorityRevision, setAuthorityRevision] = useState(
    recovery.pending?.context?.authority.manifest.revision_id ?? "",
  );
  const [inventoryId, setInventoryId] = useState(navigation?.inventoryId ?? "");
  const [attemptId, setAttemptId] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [coverageWriteLocked, setCoverageWriteLocked] = useState(false);
  const onCoveragePending = useCallback(
    (value: boolean) => setCoverageWriteLocked(value),
    [],
  );
  const [ruleCorrectionWriteLocked, setRuleCorrectionWriteLocked] =
    useState(false);
  const [coverageDirty, setCoverageDirty] = useState(false);
  const [ruleCorrectionDirty, setRuleCorrectionDirty] = useState(false);
  const onCoverageDirty = useCallback(
    (value: boolean) => setCoverageDirty(value),
    [],
  );
  const onRuleCorrectionDirty = useCallback(
    (value: boolean) => setRuleCorrectionDirty(value),
    [],
  );
  const [checkedInventory, setCheckedInventory] =
    useState<PackageRequirementInventoryView | null>(null);
  const [inventoryIdentityError, setInventoryIdentityError] =
    useState<unknown>(null);
  const [checkingInventory, setCheckingInventory] = useState(false);
  const navigationEnabled = !!navigation;
  const localScopeLocked =
    busy ||
    !!pending ||
    recovery.blocked ||
    !!draft ||
    coverageDirty ||
    ruleCorrectionDirty ||
    coverageWriteLocked ||
    ruleCorrectionWriteLocked ||
    deepLocked;
  const requestedInventory = navigation?.inventoryId ?? "";
  const routeChanging = !!navigation && requestedInventory !== inventoryId;
  const reportState = navigation?.onState;
  const hasDraft = !!draft;
  const hasPending = !!pending;
  useEffect(() => {
    reportState?.({
      busy: busy || deepState.busy,
      dirty:
        hasDraft || coverageDirty || ruleCorrectionDirty || deepState.dirty,
      pending:
        hasPending ||
        recovery.blocked ||
        coverageWriteLocked ||
        ruleCorrectionWriteLocked ||
        deepState.pending,
    });
    return () => reportState?.(emptyPackageNavigationState);
  }, [
    reportState,
    busy,
    hasDraft,
    coverageDirty,
    ruleCorrectionDirty,
    hasPending,
    recovery.blocked,
    coverageWriteLocked,
    ruleCorrectionWriteLocked,
    deepState.busy,
    deepState.dirty,
    deepState.pending,
  ]);
  useEffect(() => {
    if (
      navigationEnabled &&
      requestedInventory !== inventoryId &&
      !localScopeLocked
    ) {
      setInventoryId(requestedInventory);
      setAttemptId("");
    }
  }, [navigationEnabled, requestedInventory, inventoryId, localScopeLocked]);
  function selectInventory(id: string, replace = false) {
    setInventoryId(id);
    navigation?.onInventory(id, replace);
  }
  const onRuleCorrectionPending = useCallback(
    (value: boolean) => setRuleCorrectionWriteLocked(value),
    [],
  );
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const authorities = useDirectory<BidPackageHeadPage>(
    `/bids/${bidId}/packages?kind=authority&limit=20`,
  );
  const revisions = useDirectory<BidPackageRevisionSummaryPage>(
    authorityId
      ? `/bids/${bidId}/packages/${authorityId}/revisions?limit=20`
      : null,
  );
  const authority = useResource<BidPackageStoredView>(
    authorityId && authorityRevision
      ? `/bids/${bidId}/packages/${authorityId}/revisions/${authorityRevision}`
      : null,
  );
  const rules = useResource<RuleSetView>(`/bids/${bidId}/rules`);
  const inventories = useDirectory<PackageRequirementInventoryPage>(
    `${base}?limit=20`,
  );
  const inventory = useResource<PackageRequirementInventoryView>(
    inventoryId ? `${base}/${inventoryId}` : null,
  );
  useEffect(() => {
    let current = true;
    setInventoryIdentityError(null);
    setCheckingInventory(
      !!(navigationEnabled && inventory.data && inventoryId),
    );
    if (navigationEnabled && inventory.data && inventoryId)
      void validatePackageNavigationInventory(
        inventory.data,
        packageView,
        inventoryId,
      )
        .then((value) => {
          if (current)
            setCheckedInventory((old) =>
              old?.digest === value.digest ? old : value,
            );
        })
        .catch((failure) => {
          if (current) setInventoryIdentityError(failure);
        })
        .finally(() => {
          if (current) setCheckingInventory(false);
        });
    return () => {
      current = false;
    };
  }, [navigationEnabled, inventory.data, inventoryId, packageView]);
  const attempts = useDirectory<PackageRequirementHistoryPage>(
    inventoryId ? `${base}/${inventoryId}/coverage-attempts?limit=20` : null,
  );
  const attempt = useResource<PackageCoverageAttemptView>(
    inventoryId && attemptId
      ? `${base}/${inventoryId}/coverage-attempts/${attemptId}`
      : null,
  );
  const a = authority.data;
  const authorityValid =
    !!a &&
    a.manifest.kind === "authority" &&
    a.manifest.package_id === authorityId &&
    a.manifest.revision_id === authorityRevision &&
    sha.test(a.digest) &&
    Object.keys(m.scope).every(
      (key) =>
        m.scope[key as keyof typeof m.scope] ===
        a.manifest.scope[key as keyof typeof m.scope],
    );
  const rulesValid =
    !!rules.data &&
    uuid.test(rules.data.id) &&
    rules.data.bid_id === bidId &&
    Array.isArray(rules.data.rules) &&
    rules.data.rules.every(
      (r) => r.rule_set_id === rules.data?.id && r.scope.bid_id === bidId,
    );
  const displayedInventory = navigation
    ? checkedInventory?.manifest.id === inventoryId
      ? checkedInventory
      : undefined
    : inventory.data;
  const frozen = displayedInventory?.manifest;
  const inventoryValid =
    !!frozen &&
    frozen.bid_id === bidId &&
    frozen.package_id === m.package_id &&
    frozen.target_revision_id === m.revision_id &&
    frozen.package_digest === packageView.digest &&
    frozen.id === inventoryId &&
    (!navigation || !routeChanging);
  const checked = attempt.data?.manifest;
  const attemptValid =
    inventoryValid &&
    !!checked &&
    checked.bid_id === bidId &&
    checked.inventory_id === inventoryId &&
    checked.id === attemptId &&
    checked.inventory_digest === displayedInventory?.digest &&
    checked.package_digest === packageView.digest;
  const locked =
    disabled ||
    busy ||
    !!pending ||
    recovery.blocked ||
    coverageWriteLocked ||
    ruleCorrectionWriteLocked ||
    coverageDirty ||
    ruleCorrectionDirty ||
    deepLocked;
  const selectedReadUnverified =
    navigationEnabled &&
    (checkingInventory ||
      !!inventoryIdentityError ||
      inventory.loading ||
      !!inventory.error ||
      routeChanging);
  const canCreate =
    supportsApi("POST", base) &&
    !locked &&
    !needsRebase &&
    authorityValid &&
    rulesValid &&
    !authority.error &&
    !rules.error &&
    !inventories.error &&
    !inventories.loading &&
    !authority.loading &&
    !rules.loading &&
    !!inventories.data &&
    (!inventories.data.current_inventory_id || !!inventories.etag);
  useEffect(() => {
    if (
      draft &&
      rules.data &&
      JSON.stringify(rules.data) !== JSON.stringify(draft.context.rules)
    )
      setPlanStale(true);
    if (
      draft &&
      a &&
      JSON.stringify(a) !== JSON.stringify(draft.context.authority)
    )
      setPlanStale(true);
  }, [draft, rules.data, a]);
  const planSaveAllowed =
    !!draft &&
    !locked &&
    !planStale &&
    !needsRebase &&
    supportsApi("POST", base) &&
    !inventories.error &&
    !inventories.loading &&
    !rules.error &&
    !authority.error &&
    !rules.loading &&
    !authority.loading &&
    plan.valid &&
    plan.mappings.length > 0 &&
    validMappings(plan.mappings, draft.context);

  function beginPlan() {
    if (!canCreate || draft) return;
    setDraft({
      context: structuredClone({ authority: a!, rules: rules.data! }),
      initialMappings: [],
      etag: inventories.data?.current_inventory_id ? inventories.etag : null,
      ifNoneMatch: inventories.data?.current_inventory_id ? null : "*",
      serial: Date.now(),
      sent: false,
    });
    setPlanStale(false);
    setNeedsRebase(false);
    setRebase(null);
    setFailure(null);
  }
  async function inspectBaseline() {
    if (!needsRebase || locked) return;
    setBusy(true);
    setRebase(null);
    try {
      const current = await api<PackageRequirementInventoryPage>(
        `${base}?limit=20`,
      );
      if (!active.current) return;
      const head = current.data.current_inventory_id;
      if (head && !current.etag)
        throw new Error("当前清单缺少版本条件，不能采用新基线。");
      let view: PackageRequirementInventoryView | null = null;
      if (head) {
        if (!uuid.test(head))
          throw new Error("当前清单身份无效，不能采用新基线。");
        const exact = await api<PackageRequirementInventoryView>(
          `${base}/${head}`,
        );
        if (!active.current) return;
        const value = exact.data.manifest;
        if (
          value.id !== head ||
          value.bid_id !== bidId ||
          value.package_id !== m.package_id ||
          value.target_revision_id !== m.revision_id ||
          value.package_digest !== packageView.digest ||
          !sha.test(exact.data.digest) ||
          !Array.isArray(value.requirements) ||
          !Number.isSafeInteger(value.revision) ||
          value.revision < 1 ||
          !current.data.items.some(
            (item) => item.id === head && item.digest === exact.data.digest,
          )
        )
          throw new Error("当前清单范围或摘要不一致，不能采用新基线。");
        view = exact.data;
      }
      setRebase({
        head,
        view,
        etag: head ? current.etag : null,
        ifNoneMatch: head ? null : "*",
      });
    } catch (error) {
      if (active.current) setFailure(error);
    } finally {
      if (active.current) setBusy(false);
    }
  }

  async function save(withPlan = false) {
    if (
      busy ||
      recovery.blocked ||
      (!pending &&
        (disabled || (withPlan ? !planSaveAllowed : !canCreate || !!draft)))
    )
      return;
    const operation: Pending = pending ?? {
      version: withPlan ? 2 : 1,
      scope,
      body: {
        authority_revision_id: withPlan
          ? draft!.context.authority.manifest.revision_id
          : authorityRevision,
        rule_set_id: withPlan ? draft!.context.rules.id : rules.data!.id,
        mappings: withPlan ? structuredClone(plan.mappings) : [],
      },
      ...(withPlan ? { context: draft!.context } : {}),
      key: crypto.randomUUID(),
      etag: withPlan
        ? draft!.etag
        : emptyBaseline
          ? emptyBaseline.etag
          : inventories.data?.current_inventory_id
            ? inventories.etag
            : null,
      ifNoneMatch: withPlan
        ? draft!.ifNoneMatch
        : emptyBaseline
          ? emptyBaseline.ifNoneMatch
          : inventories.data?.current_inventory_id
            ? null
            : "*",
    };
    setBusy(true);
    setFailure(null);
    setNotice("");
    let sent = false;
    try {
      sessionStorage.setItem(storageKey(scope), JSON.stringify(operation));
      setPending(operation);
      if (operation.version === 2)
        setDraft((old) => (old ? { ...old, sent: true } : old));
      sent = true;
      const result = await api<PackageRequirementInventoryView>(base, {
        method: "POST",
        body: operation.body,
        key: operation.key,
        etag: operation.etag,
        ifNoneMatch: operation.ifNoneMatch,
      });
      if (!active.current) return;
      const saved = result.data.manifest;
      if (
        saved.bid_id !== bidId ||
        saved.package_id !== m.package_id ||
        saved.target_revision_id !== m.revision_id ||
        saved.package_digest !== packageView.digest ||
        saved.authority_revision_id !== operation.body.authority_revision_id ||
        saved.rule_set_id !== operation.body.rule_set_id ||
        !sha.test(result.data.digest)
      )
        throw new Error("保存响应身份不一致，保留原操作待核对。");
      sessionStorage.removeItem(storageKey(scope));
      setPending(null);
      setDraft(null);
      setPlanStale(false);
      setNeedsRebase(false);
      setRebase(null);
      setEmptyBaseline(null);
      selectInventory(saved.id, true);
      setAttemptId("");
      setNotice(
        `已保存要求清单修订 ${saved.revision}，${operation.body.mappings.length ? "已冻结人工检查计划；清单完整性仍未知" : "所有条款保持未映射"}；未形成完整覆盖结论。`,
      );
      void inventories.reload();
    } catch (error) {
      if (!active.current) return;
      setFailure(
        sent
          ? error
          : new Error(
              "本地操作记录无法保存，请求尚未发送；请恢复浏览器存储后重试。",
            ),
      );
      if (
        error instanceof ApiError &&
        [409, 412, 422, 428].includes(error.status) &&
        !error.retryable &&
        (!pending ||
          error.code.startsWith("PACKAGE_REQUIREMENT_") ||
          ["REVISION_CONFLICT", "PROJECT_WORK_CLOSED"].includes(error.code))
      ) {
        try {
          sessionStorage.removeItem(storageKey(scope));
          setPending(null);
          if (operation.version === 2 && operation.context) {
            setPlan({
              mappings: operation.body.mappings,
              valid: false,
              dirty: true,
            });
            setDraft({
              context: operation.context,
              initialMappings: operation.body.mappings,
              etag: operation.etag,
              ifNoneMatch: operation.ifNoneMatch,
              serial: Date.now(),
              sent: false,
              rejected: true,
            });
          }
          if (error.status === 412) {
            setNeedsRebase(true);
            setRebase(null);
          }
          void inventories.reload();
        } catch {
          setFailure(new Error("无法清理本地未决记录，保留原操作等待核对。"));
        }
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section className="package-requirements" aria-label="整包要求与覆盖">
      <h3>整包要求与覆盖</h3>
      <p>
        本方资料包修订 {m.revision} · {m.members.length}{" "}
        份文件。本工作面固定到当前明确修订，切换包或修订分别读取。
      </p>
      <p role="note">
        历史规则集与新清单的抽取身份应按原版本核对。清单完整性未知，仍须单独验收。人工范围声明不等于系统独立验收或合规结论。
      </p>
      {routeChanging && localScopeLocked && (
        <p role="alert">
          当前清单仍有未保存或待核操作，未切换到链接中的另一清单。原输入与原请求仍保留。
        </p>
      )}
      <ErrorNotice error={inventoryIdentityError} />
      <details>
        <summary>本方冻结身份</summary>
        <p>
          包 {m.package_id} · 修订 {m.revision_id} · SHA256 {packageView.digest}
        </p>
        <p>
          标段 {m.scope.lot_id} · 轮次 {m.scope.round_id} · 主体{" "}
          {m.scope.bidder_id}
        </p>
      </details>
      <fieldset disabled={locked || !!draft}>
        <legend>选择本次要求清单依据</legend>
        <p>
          创建未映射清单保留未知；编辑检查计划需逐条明确范围与依据。两者均追加版本，不自动沿用上版计划或覆盖声明。
        </p>
        <p>
          新建清单须使用当前本方修订与当前依据修订；历史修订仍可读取，服务端会核对是否允许新建。
        </p>
        {!!inventories.data?.current_inventory_id && (
          <p>当前已有要求清单。本次将追加修订；旧版及原检查计划仍保留可读。</p>
        )}
        <ResourceState
          {...authorities}
          hasData={!!authorities.data}
          onRetry={() => void authorities.reload()}
        />
        <label>
          权威依据包
          <select
            value={authorityId}
            onChange={(e) => {
              setAuthorityId(e.target.value);
              setAuthorityRevision("");
            }}
          >
            <option value="">请选择依据包</option>
            {authorities.items
              .filter((p) => p.kind === "authority")
              .map((p, i) => (
                <option key={p.id} value={p.id}>
                  依据包 {i + 1} · 当前修订 {p.revision}
                </option>
              ))}
          </select>
        </label>
        {authorities.hasMore && (
          <button
            type="button"
            disabled={authorities.moreBusy}
            onClick={() => void authorities.loadMore()}
          >
            更多依据包
          </button>
        )}
        {!!authorities.moreError && (
          <ErrorNotice
            error={authorities.moreError}
            onRetry={() => void authorities.loadMore()}
          />
        )}
        {authorityId && (
          <>
            <ResourceState
              {...revisions}
              hasData={!!revisions.data}
              onRetry={() => void revisions.reload()}
            />
            <label>
              依据包明确修订
              <select
                value={authorityRevision}
                onChange={(e) => setAuthorityRevision(e.target.value)}
              >
                <option value="">请选择修订，不自动取最新</option>
                {revisions.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    修订 {p.revision} ·{" "}
                    {new Date(p.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            {revisions.hasMore && (
              <button
                type="button"
                onClick={() => void revisions.loadMore()}
                disabled={revisions.moreBusy}
              >
                更多依据修订
              </button>
            )}
            {!!revisions.moreError && (
              <ErrorNotice
                error={revisions.moreError}
                onRetry={() => void revisions.loadMore()}
              />
            )}
          </>
        )}
        {authorityRevision && (
          <ResourceState
            {...authority}
            hasData={!!authority.data}
            onRetry={() => void authority.reload()}
          />
        )}
        {a && !authorityValid && (
          <p role="alert">
            依据包与本方工程、标段、轮次或主体不一致，禁止创建。
          </p>
        )}
        {authorityValid && a && (
          <details>
            <summary>已选依据修订 {a.manifest.revision} 的冻结身份</summary>
            <p>
              {a.manifest.revision_id} · SHA256 {a.digest}
            </p>
          </details>
        )}
        <ResourceState
          {...rules}
          hasData={!!rules.data}
          onRetry={() => void rules.reload()}
        />
        {rulesValid && (
          <p>
            现有规则 {rules.data!.rules.length} 条 · 抽取范围{" "}
            {
              {
                complete: "完整范围",
                partial: "部分范围",
                conflict: "范围冲突",
              }[rules.data!.coverage]
            }
            （不表示整包完整）
          </p>
        )}
        {rules.data && !rulesValid && (
          <p role="alert">规则集精确身份或项目范围不一致，禁止推算或创建。</p>
        )}
        <div className="requirement-plan-actions">
          <button
            type="button"
            className="button"
            disabled={!canCreate}
            onClick={() => void save()}
          >
            创建未映射清单
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={!canCreate || !!draft}
            onClick={beginPlan}
          >
            开始编辑检查计划
          </button>
        </div>
      </fieldset>
      {draft && (
        <section
          className="requirement-plan-draft"
          aria-label="人工检查计划草稿"
        >
          <p>
            依据和原规则已固定到开始编辑时的快照。检查计划不是覆盖声明，清单完整性仍未知。
          </p>
          <RequirementCheckPlan
            key={draft.serial}
            bidId={bidId}
            packageView={packageView}
            authorityView={draft.context.authority}
            rules={draft.context.rules}
            disabled={locked}
            initialMappings={draft.initialMappings}
            onChange={onPlanChange}
          />
          {planStale && (
            <p role="alert">
              原规则或依据已变化，保留原检查计划；禁止把新快照自动代入保存。
            </p>
          )}
          <div className="requirement-plan-actions">
            <button
              type="button"
              disabled={locked}
              onClick={() => {
                void rules.reload();
                void authority.reload();
              }}
            >
              核对原规则与依据
            </button>
            <button
              type="button"
              className="button"
              disabled={!planSaveAllowed}
              onClick={() => void save(true)}
            >
              保存检查计划清单
            </button>
            <button
              type="button"
              disabled={locked || draft.sent}
              onClick={() => {
                setDraft(null);
                setPlanStale(false);
                setRebase(null);
              }}
            >
              {draft.rejected ? "放弃已明确失败的草稿" : "取消未发送的检查计划"}
            </button>
          </div>
        </section>
      )}
      {needsRebase && (
        <div role="status">
          <p>
            清单基线冲突。原计划已保留；先读取当前清单，再明确确认采用新基线，不会自动重发。
          </p>
          <button
            type="button"
            disabled={locked}
            onClick={() => void inspectBaseline()}
          >
            读取当前清单基线
          </button>
          {rebase && (
            <>
              {!rebase.view && (
                <p>已核对当前尚无清单，采用后仍须明确提交首次创建。</p>
              )}
              {rebase.view && (
                <>
                  <p>已核对当前清单修订 {rebase.view.manifest.revision}</p>
                  <p>
                    当前映射{" "}
                    {
                      rebase.view.manifest.requirements.filter(
                        (r) => r.annotation.mapped,
                      ).length
                    }{" "}
                    / 总要求 {rebase.view.manifest.requirements.length}
                    ；原草稿映射 {draft ? plan.mappings.length : 0}
                  </p>
                  <p>采用基线只更新版本条件，保留原草稿内容，不自动提交。</p>
                </>
              )}
              <details>
                <summary>已核对的新基线冻结身份</summary>
                <p>
                  {rebase.head ?? "尚无清单"} · 版本条件{" "}
                  {rebase.etag ?? "首次创建"} · SHA256{" "}
                  {rebase.view?.digest ?? "待首次生成"}
                </p>
                {rebase.view && (
                  <p>
                    依据修订 {rebase.view.manifest.authority_revision_id} ·
                    原规则集 {rebase.view.manifest.rule_set_id}
                  </p>
                )}
              </details>
              <button
                type="button"
                disabled={locked || planStale}
                onClick={() => {
                  setDraft((old) =>
                    old
                      ? {
                          ...old,
                          etag: rebase.etag,
                          ifNoneMatch: rebase.ifNoneMatch,
                        }
                      : old,
                  );
                  if (!draft)
                    setEmptyBaseline({
                      etag: rebase.etag,
                      ifNoneMatch: rebase.ifNoneMatch,
                    });
                  setNeedsRebase(false);
                  setRebase(null);
                }}
              >
                确认采用已核对的新基线
              </button>
            </>
          )}
        </div>
      )}
      {recovery.blocked && (
        <p role="alert">
          本地未决操作记录损坏或范围不符，创建已锁定。请保留记录核对，不能另发新操作。
        </p>
      )}
      {pending && (
        <div role="status">
          <p>
            保存结果未知，已保留原请求、幂等键和版本条件。请重试同一操作或读取历史核对；刷新也会恢复，不能修改成新操作。
          </p>
          <details>
            <summary>待核原操作身份</summary>
            <p>
              依据修订 {pending.body.authority_revision_id} · 规则集{" "}
              {pending.body.rule_set_id}
            </p>
          </details>
          <button type="button" disabled={busy} onClick={() => void save()}>
            重试原清单操作
          </button>
        </div>
      )}
      {!!failure && <ErrorNotice error={failure} />}
      {notice && <p role="status">{notice}</p>}
      <h4>要求清单历史</h4>
      <ResourceState
        {...inventories}
        hasData={!!inventories.data}
        onRetry={() => void inventories.reload()}
      />
      <button type="button" onClick={() => void inventories.reload()}>
        刷新清单历史
      </button>
      {inventories.data &&
        !inventories.loading &&
        !inventories.error &&
        !inventories.moreError &&
        !inventories.hasMore &&
        !inventories.items.length && (
          <p>此包修订尚无冻结要求清单；不能据此认定无要求。</p>
        )}
      {inventories.items.map((item, i) => (
        <button
          type="button"
          key={item.id}
          aria-pressed={inventoryId === item.id}
          disabled={
            navigation
              ? localScopeLocked || !!inventories.error || inventories.loading
              : ruleCorrectionWriteLocked
          }
          onClick={() => {
            if (navigation && localScopeLocked) return;
            selectInventory(item.id);
            setAttemptId("");
          }}
        >
          读取清单 {i + 1} · {new Date(item.created_at).toLocaleString()}
          {inventories.data?.current_inventory_id === item.id
            ? "（当前）"
            : "（历史）"}
        </button>
      ))}
      {inventories.hasMore && (
        <button
          type="button"
          disabled={inventories.moreBusy}
          onClick={() => void inventories.loadMore()}
        >
          更多清单
        </button>
      )}
      {!!inventories.moreError && (
        <ErrorNotice
          error={inventories.moreError}
          onRetry={() => void inventories.loadMore()}
        />
      )}
      {inventoryId && (
        <ResourceState
          {...inventory}
          hasData={!!inventory.data}
          onRetry={() => void inventory.reload()}
        />
      )}
      {inventory.data && !inventoryValid && !checkingInventory && (
        <p role="alert">清单冻结范围不一致，未展示其他包的条款。</p>
      )}
      {inventoryValid && frozen && (
        <>
          <h4>
            清单修订 {frozen.revision} · {frozen.requirements.length} 条冻结要求
          </h4>
          <details>
            <summary>清单冻结依据及摘要</summary>
            <p>
              清单 {frozen.id} · SHA256 {displayedInventory!.digest}
            </p>
            <p>
              依据修订 {frozen.authority_revision_id} · SHA256{" "}
              {frozen.authority_digest}
            </p>
            <p>
              原规则集 {frozen.rule_set_id} · SHA256 {frozen.rule_set_digest}
            </p>
            <p>抽取身份 {frozen.extraction_binding}</p>
            <p>inventory_complete=false · review_ready=false</p>
          </details>
          {frozen.requirements.map((binding, i) => {
            const r = binding.requirement;
            return (
              <article key={binding.rule_id}>
                <h5>
                  要求 {i + 1} ·{" "}
                  {r.categories.map((v) => categories[v] ?? v).join("、")}
                </h5>
                <p>{text(binding.rule_snapshot.statement)}</p>
                <p>
                  来源绑定：
                  {binding.source_bound ? "有精确引用关联" : "未知／未绑定"} ·
                  原规则决定：
                  {decisions[text(binding.decision_snapshot?.decision)] ??
                    "未知／未记录"}{" "}
                  · 人工检查计划：
                  {binding.annotation.mapped ? "已映射" : "未映射"}
                </p>
                <p>
                  数量：{r.minimum_count === null ? "未知" : r.minimum_count} ·
                  适用性：
                  {
                    {
                      unknown: "未知",
                      applicable: "适用",
                      not_applicable: "有据不适用",
                    }[r.applicability]
                  }{" "}
                  · 有效时点：{r.valid_at ?? "未知"}
                </p>
                {!r.target_part_ids.length && (
                  <p>目标范围：分类内范围，尚未指定具体页段</p>
                )}
                {r.target_part_ids.map((partId) => {
                  const fileIndex = m.members.findIndex((member) =>
                    member.parts.some((part) => part.part_id === partId),
                  );
                  const partIndex =
                    fileIndex < 0
                      ? -1
                      : m.members[fileIndex].parts.findIndex(
                          (part) => part.part_id === partId,
                        );
                  const part =
                    fileIndex < 0
                      ? undefined
                      : m.members[fileIndex].parts[partIndex];
                  return (
                    <p key={partId}>
                      目标范围：
                      {part
                        ? `文件 ${fileIndex + 1} · 分册 ${partIndex + 1} · ${categories[part.category] ?? part.category} · 物理页 ${part.first_page}—${part.last_page}`
                        : "未定位范围，请核对冻结身份"}
                    </p>
                  );
                })}
                <p>
                  核验项：
                  {r.checks.length
                    ? r.checks
                        .map((value) => checkNames[value] ?? "其他检查项")
                        .join("、")
                    : "未声明"}
                </p>
                <p>检查计划理由：{binding.annotation.reason ?? "未声明"}</p>
                <EvidenceLinks
                  ids={binding.annotation.basis_evidence_ids}
                  label={`查看要求 ${i + 1} 检查计划采用依据`}
                />
                <EvidenceLinks
                  ids={r.applicability_evidence
                    .filter(
                      (value) =>
                        value.startsWith("evidence:") &&
                        uuid.test(value.slice(9)),
                    )
                    .map((value) => value.slice(9))}
                  label={`查看要求 ${i + 1} 的适用性依据`}
                />
                <Conditions
                  value={binding.rule_snapshot.conditions}
                  label="原始条件"
                />
                <Conditions
                  value={binding.rule_snapshot.exceptions}
                  label="原始例外"
                />
                <EvidenceLinks
                  ids={strings(binding.rule_snapshot.evidence_ids)}
                  label={`查看要求 ${i + 1} 的原页依据`}
                />
                <details>
                  <summary>要求及来源身份</summary>
                  <p>
                    {binding.rule_id} · SHA256 {binding.requirement_digest}
                  </p>
                  <p>{r.source_refs.join("；")}</p>
                  <p>
                    目标范围身份：{r.target_part_ids.join("；") || "未指定"} ·
                    检查项原始标识：{r.checks.join("；") || "未声明"}
                  </p>
                  <p>
                    适用依据：{r.applicability_evidence.join("；") || "未记录"}
                  </p>
                </details>
              </article>
            );
          })}
          <h4>人工范围声明历史</h4>
          <p>每次人工记录单独读取。新增记录在下方填写，不沿用历史结果。</p>
          <ResourceState
            {...attempts}
            hasData={!!attempts.data}
            onRetry={() => void attempts.reload()}
          />
          {attempts.data && !attempts.items.length && (
            <p>尚无人工范围声明，所有条款核验状态为未知。</p>
          )}
          {attempts.items.map((item, i) => (
            <button
              type="button"
              key={item.id}
              aria-pressed={attemptId === item.id}
              onClick={() => setAttemptId(item.id)}
            >
              读取范围声明 {i + 1} ·{" "}
              {new Date(item.created_at).toLocaleString()}
            </button>
          ))}
          {attempts.hasMore && (
            <button
              type="button"
              disabled={attempts.moreBusy}
              onClick={() => void attempts.loadMore()}
            >
              更多范围声明
            </button>
          )}
          {!!attempts.moreError && (
            <ErrorNotice
              error={attempts.moreError}
              onRetry={() => void attempts.loadMore()}
            />
          )}
          {attemptId && (
            <ResourceState
              {...attempt}
              hasData={!!attempt.data}
              onRetry={() => void attempt.reload()}
            />
          )}
          {attempt.data && !attemptValid && (
            <p role="alert">范围声明的包、清单或摘要不一致，未显示其他记录。</p>
          )}
          {attemptValid && checked && (
            <>
              <h5>本次人工记录 · 整包完整性仍未知</h5>
              <p>
                完整核验：否 ·
                可正式审查：否。下列状态是人工记录，不是系统验收。
              </p>
              {frozen.requirements.map((r, i) => (
                <p key={r.rule_id}>
                  要求 {i + 1}：
                  {names[
                    checked.assessment.requirement_states[r.rule_id] ??
                      "unknown"
                  ] ?? "未知"}
                </p>
              ))}
              <h6>成员缺口</h6>
              {!checked.assessment.member_gaps.length && (
                <p>本次未记录成员缺口；不代表整包完整。</p>
              )}
              {checked.assessment.member_gaps.map((gap, i) => (
                <div key={i}>
                  <p>
                    {strings(gap.purposes)
                      .map((v) => categories[v] ?? v)
                      .join("、") || `文件 ${i + 1}`}
                    ：
                    {strings(gap.codes)
                      .map((v) => gapNames[v] ?? "有待核对的缺口")
                      .join("、") || "缺口类型待核"}{" "}
                    ·{" "}
                    {typeof gap.reason === "string" ? gap.reason : "原因未记录"}
                  </p>
                  <details>
                    <summary>缺口成员身份</summary>
                    <p>
                      {text(gap.member_id)} · 文件版本{" "}
                      {text(gap.document_version_id)}
                    </p>
                  </details>
                </div>
              ))}
              <h6>本次受检物理范围</h6>
              {!checked.assessment.inspected_ranges.length && (
                <p>未记录受检范围，不能认定已检查。</p>
              )}
              <ul>
                {checked.assessment.inspected_ranges.map((range, i) => (
                  <li key={i}>
                    {inspectedLabel(
                      packageView,
                      range.part_id,
                      range.first_page,
                      range.last_page,
                    )}
                    <details>
                      <summary>受检范围冻结身份</summary>
                      <p>
                        范围 {text(range.part_id)} · 要求{" "}
                        {text(range.requirement_id)} · 文件版本{" "}
                        {text(range.document_version_id)} · 要求摘要{" "}
                        {text(range.requirement_digest)}
                      </p>
                    </details>
                  </li>
                ))}
              </ul>
              {checked.results.map((result) => (
                <div key={result.coverage.requirement_id}>
                  <h6>
                    要求{" "}
                    {frozen.requirements.findIndex(
                      (binding) =>
                        binding.rule_id === result.coverage.requirement_id,
                    ) + 1}{" "}
                    · {names[result.coverage.state] ?? "未知"}
                  </h6>
                  <p>
                    依据类型：
                    {result.basis_type === "human_scope_declaration"
                      ? "人工范围声明"
                      : "人工观察"}{" "}
                    · {result.coverage.reason}
                  </p>
                  <ul>
                    {result.coverage.inspected.map((range, i) => (
                      <li key={i}>
                        {inspectedLabel(
                          packageView,
                          range.part_id,
                          range.first_page,
                          range.last_page,
                        )}
                      </li>
                    ))}
                  </ul>
                  <EvidenceLinks
                    ids={result.evidence_ids}
                    label="查看本次声明证据"
                  />
                </div>
              ))}
              <details>
                <summary>本次声明冻结身份</summary>
                <p>
                  {checked.id} · SHA256 {attempt.data!.digest}
                </p>
              </details>
            </>
          )}
        </>
      )}
      <Suspense fallback={<p role="status">正在加载有据规则修订…</p>}>
        <PackageRuleCorrections
          bidId={bidId}
          memberId={memberId}
          packageView={packageView}
          inventory={inventoryValid ? displayedInventory! : null}
          inventoryEtag={inventoryValid ? inventory.etag : null}
          currentInventoryId={inventories.data?.current_inventory_id ?? null}
          currentKnown={
            !!inventories.data && !inventories.loading && !inventories.error
          }
          disabled={
            disabled ||
            busy ||
            !!pending ||
            recovery.blocked ||
            coverageWriteLocked ||
            coverageDirty ||
            !!draft ||
            deepLocked ||
            selectedReadUnverified
          }
          onPendingChange={onRuleCorrectionPending}
          onDirtyChange={onRuleCorrectionDirty}
          onRefresh={() => {
            void inventories.reload();
            void inventory.reload();
          }}
          onApplied={(newInventoryId) => {
            if (deepLocked || coverageWriteLocked || coverageDirty) {
              setNotice(
                `新清单 ${newInventoryId} 已保存；原清单仍有其他未决操作或未保存输入，保留当前位置。请先处理原输入，再从历史明确选择新清单。`,
              );
            } else selectInventory(newInventoryId, true);
            setAttemptId("");
            setDraft(null);
            setPlan({ mappings: [], valid: false, dirty: false });
            setPlanStale(false);
            setNeedsRebase(false);
            setRebase(null);
            setEmptyBaseline(null);
            void inventories.reload();
            void rules.reload();
          }}
        />
      </Suspense>
      <Suspense fallback={<p role="status">正在加载人工范围填写…</p>}>
        <PackageCoverageWorkspace
          bidId={bidId}
          memberId={memberId}
          packageView={packageView}
          authorityView={authorityValid ? a! : null}
          inventory={inventoryValid ? displayedInventory! : null}
          currentInventoryId={inventories.data?.current_inventory_id ?? null}
          currentKnown={
            !!inventories.data && !inventories.loading && !inventories.error
          }
          onPendingChange={onCoveragePending}
          onDirtyChange={onCoverageDirty}
          disabled={
            disabled ||
            !!pending ||
            recovery.blocked ||
            busy ||
            ruleCorrectionWriteLocked ||
            ruleCorrectionDirty ||
            !!draft ||
            deepLocked ||
            selectedReadUnverified
          }
          onSaved={(savedInventoryId, savedAttemptId) => {
            selectInventory(savedInventoryId, true);
            setAttemptId(savedAttemptId);
            if (inventoryId === savedInventoryId) void attempts.reload();
          }}
        />
      </Suspense>
      {inventoryValid && (
        <Suspense fallback={<p role="status">正在加载施组评分范围…</p>}>
          <PackageTechnicalScope
            bidId={bidId}
            memberId={memberId}
            packageView={packageView}
            inventory={inventoryValid ? displayedInventory! : null}
            disabled={
              disabled ||
              busy ||
              !!pending ||
              recovery.blocked ||
              coverageWriteLocked ||
              coverageDirty ||
              ruleCorrectionWriteLocked ||
              ruleCorrectionDirty ||
              !!draft ||
              selectedReadUnverified
            }
          />
        </Suspense>
      )}
      <PackageReviewInputPreview
        memberId={memberId}
        bidId={bidId}
        packageView={packageView}
        inventory={inventoryValid ? displayedInventory! : null}
        coverage={attemptValid ? attempt.data! : null}
        coveragePending={!!attemptId && !attemptValid}
        disabled={
          busy ||
          !!pending ||
          recovery.blocked ||
          coverageWriteLocked ||
          ruleCorrectionWriteLocked ||
          coverageDirty ||
          ruleCorrectionDirty ||
          !!draft ||
          selectedReadUnverified
        }
      />
      {!supportsApi("POST", base) && (
        <p>当前服务尚未提供清单创建接口，保留只读历史。</p>
      )}
    </section>
  );
}
