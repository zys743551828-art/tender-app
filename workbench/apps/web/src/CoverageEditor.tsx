import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  BidPackageStoredView,
  CreatePackageCoverageAttempt,
  EvidenceView,
  PackageRequirementInventoryView,
  PackageEvidencePage,
} from "./contracts";
import "./CoverageEditor.css";

export type CoverageEditorValue = {
  results: CreatePackageCoverageAttempt["results"];
  valid: boolean;
  dirty: boolean;
};
type Result = CoverageEditorValue["results"][number];
type Props = {
  bidId: string;
  packageView: BidPackageStoredView;
  authorityView: BidPackageStoredView;
  inventory: PackageRequirementInventoryView;
  disabled: boolean;
  onChange: (value: CoverageEditorValue) => void;
  initialResults?: CoverageEditorValue["results"];
};
type Entry = PackageEvidencePage["items"][number];
type EvidencePage = PackageEvidencePage;
type Range = { enabled: boolean; first: string; last: string };
type Draft = {
  enabled: boolean;
  state: Result["state"];
  reason: string;
  confirmed: boolean;
  ranges: Record<string, Range>;
  evidenceIds: string[];
};
type Citation = {
  value?: EvidenceView;
  loading?: boolean;
  issue?: string;
  ownParts: string[];
  authorityParts: string[];
};
const labels: Record<Result["state"], string> = {
  unknown: "未知",
  not_provided: "未提供",
  missing: "缺项",
  pending_parse: "待解析",
  parse_gap: "解析有缺口",
  unsupported: "不支持",
  conflict: "存在冲突",
  verified: "人工声明已检查完整范围",
  not_applicable: "人工声明有据不适用",
};
const categoryNames: Record<string, string> = {
  technical: "技术",
  business: "商务",
  qualification: "资格",
  price: "报价",
  commercial: "商务",
  attachment: "附件",
  annex: "附件",
};
const isPositive = (state: Result["state"]) =>
  state === "verified" || state === "not_applicable";
const validReason = (text: string) =>
  text.trim().length > 0 &&
  Array.from(text).length <= 200 &&
  !text.includes("\0") &&
  !/[\uD800-\uDFFF]/u.test(text);
const pageNumber = (text: string) =>
  /^\d+$/.test(text) && Number.isSafeInteger(Number(text)) && Number(text) > 0
    ? Number(text)
    : NaN;
const partsOf = (view: BidPackageStoredView) =>
  view.manifest.members.flatMap((member, fileIndex) =>
    member.parts.map((part, partIndex) => ({
      member,
      part,
      fileIndex: fileIndex + 1,
      partIndex: partIndex + 1,
    })),
  );
function memberships(
  view: BidPackageStoredView,
  value: Pick<
    EvidenceView,
    "document_version_id" | "parse_run_id" | "physical_page"
  >,
) {
  return partsOf(view)
    .filter(
      ({ member, part }) =>
        member.document_version_id === value.document_version_id &&
        member.parse.status === "frozen" &&
        member.parse.parse_run_id === value.parse_run_id &&
        part.first_page <= value.physical_page &&
        value.physical_page <= part.last_page,
    )
    .map((p) => p.part.part_id);
}
function validateDirectory(page: EvidencePage, view: BidPackageStoredView) {
  if (
    page.revision_id !== view.manifest.revision_id ||
    page.package_digest !== view.digest ||
    !Array.isArray(page.items) ||
    typeof page.has_more !== "boolean" ||
    (page.has_more &&
      (!page.next_cursor || typeof page.next_cursor !== "string"))
  )
    throw new Error("证据目录的包修订或摘要不一致，未采用其他范围。");
  for (const item of page.items) {
    const actual = memberships(view, item).sort();
    if (
      typeof item.id !== "string" ||
      !item.id ||
      !Number.isSafeInteger(item.physical_page) ||
      item.physical_page < 1 ||
      !Array.isArray(item.part_ids) ||
      !item.part_ids.length ||
      [...item.part_ids].sort().join("\0") !== actual.join("\0")
    )
      throw new Error("证据目录的文件、解析或逻辑页范围不一致。");
  }
}

function EvidenceDirectory({
  bidId,
  view,
  disabled,
  renderEntry,
}: {
  bidId: string;
  view: BidPackageStoredView;
  disabled: boolean;
  renderEntry: (entry: Entry, index: number) => React.ReactNode;
}) {
  const path = `/bids/${bidId}/packages/${view.manifest.package_id}/revisions/${view.manifest.revision_id}/evidence?limit=20`;
  const generation = useRef(0);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  const [snapshot, setSnapshot] = useState<{
    path: string;
    items: Entry[];
    next: string | null;
    hasMore: boolean;
    loading: boolean;
    error?: unknown;
  }>({ path, items: [], next: null, hasMore: false, loading: true });
  async function load(cursor: string | null = null) {
    const token = ++generation.current;
    setSnapshot((old) => ({ ...old, path, loading: true, error: undefined }));
    try {
      const { data } = await api<EvidencePage>(
        path + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""),
      );
      validateDirectory(data, view);
      if (data.has_more && cursor === data.next_cursor)
        throw new Error("证据目录游标没有推进，请重读后继续。");
      if (generation.current !== token) return;
      setSnapshot((old) => {
        const merged = new Map(
          (cursor && old.path === path ? old.items : []).map((item) => [
            item.id,
            item,
          ]),
        );
        for (const item of data.items) merged.set(item.id, item);
        return {
          path,
          items: [...merged.values()],
          next: data.next_cursor,
          hasMore: data.has_more,
          loading: false,
        };
      });
    } catch (error) {
      if (generation.current === token)
        setSnapshot((old) => ({ ...old, path, loading: false, error }));
    }
  }
  useEffect(() => {
    void load();
    return invalidate;
    // One immutable directory instance per captured package revision.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, view.digest, invalidate]);
  const current = snapshot.path === path ? snapshot : null;
  return (
    <div className="coverage-editor-directory">
      {current?.loading && <p>正在读取冻结解析的证据目录…</p>}
      {!!current?.error && (
        <p role="alert">
          {current.error instanceof Error
            ? current.error.message
            : "目录读取失败"}
          <button
            type="button"
            disabled={disabled || current.loading}
            onClick={() => void load(current.next)}
          >
            重读证据目录
          </button>
        </p>
      )}
      {current?.items.map(renderEntry)}
      {current &&
        !current.loading &&
        !current.items.length &&
        !current.error && <p>此冻结包暂无可定位证据，不会改取最新解析。</p>}
      {current?.hasMore && (
        <button
          type="button"
          disabled={disabled || current.loading}
          onClick={() => void load(current.next)}
        >
          更多冻结证据
        </button>
      )}
    </div>
  );
}

function Picker({
  label,
  bidId,
  view,
  disabled,
  renderEntry,
}: {
  label: string;
  bidId: string;
  view: BidPackageStoredView;
  disabled: boolean;
  renderEntry: (entry: Entry, index: number) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <EvidenceDirectory
          key={`${view.manifest.revision_id}:${view.digest}`}
          bidId={bidId}
          view={view}
          disabled={disabled}
          renderEntry={renderEntry}
        />
      )}
    </div>
  );
}

export function CoverageEditor({
  bidId,
  packageView,
  authorityView,
  inventory,
  disabled,
  onChange,
  initialResults,
}: Props) {
  const context = JSON.stringify({
    bidId,
    package: packageView.manifest,
    digest: packageView.digest,
    authority: authorityView.manifest,
    authorityDigest: authorityView.digest,
    inventory,
    initialResults,
  });
  const first = useRef(context);
  const changed = first.current !== context;
  const ownParts = partsOf(packageView);
  const inv = inventory.manifest;
  const contextValid =
    packageView.manifest.kind === "bid" &&
    authorityView.manifest.kind === "authority" &&
    inv.bid_id === bidId &&
    packageView.manifest.scope.bid_id === bidId &&
    authorityView.manifest.scope.bid_id === bidId &&
    inv.package_id === packageView.manifest.package_id &&
    inv.target_revision_id === packageView.manifest.revision_id &&
    inv.package_digest === packageView.digest &&
    inv.authority_revision_id === authorityView.manifest.revision_id &&
    inv.authority_digest === authorityView.digest &&
    inv.requirements.every((binding) =>
      Object.keys(packageView.manifest.scope).every(
        (key) =>
          binding.requirement.scope[
            key as keyof typeof packageView.manifest.scope
          ] ===
          packageView.manifest.scope[
            key as keyof typeof packageView.manifest.scope
          ],
      ),
    ) &&
    Object.keys(packageView.manifest.scope).every(
      (key) =>
        packageView.manifest.scope[
          key as keyof typeof packageView.manifest.scope
        ] ===
        authorityView.manifest.scope[
          key as keyof typeof packageView.manifest.scope
        ],
    ) &&
    new Set((initialResults ?? []).map((r) => r.rule_id)).size ===
      (initialResults ?? []).length &&
    (initialResults ?? []).every(
      (r) =>
        inv.requirements.some(
          (b) =>
            b.rule_id === r.rule_id &&
            b.requirement_digest === r.requirement_digest,
        ) &&
        r.basis_type ===
          (isPositive(r.state)
            ? "human_scope_declaration"
            : "human_observation") &&
        Object.hasOwn(labels, r.state) &&
        new Set(r.inspected.map((range) => range.part_id)).size ===
          r.inspected.length,
    );
  const locked = disabled || changed || !contextValid;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(
      (initialResults ?? []).map((result) => [
        result.rule_id,
        {
          enabled: true,
          state: result.state,
          reason: result.reason,
          confirmed:
            isPositive(result.state) &&
            result.basis_type === "human_scope_declaration",
          evidenceIds: [...result.evidence_ids],
          ranges: Object.fromEntries(
            result.inspected.map((r) => [
              r.part_id,
              {
                enabled: true,
                first: String(r.first_page),
                last: String(r.last_page),
              },
            ]),
          ),
        },
      ]),
    ),
  );
  const [dirty, setDirty] = useState(!!initialResults?.length);
  const [citations, setCitations] = useState<Record<string, Citation>>({});
  const generation = useRef(0);
  const pending = useRef(new Set<string>());
  const invalidate = useCallback(() => {
    generation.current++;
    pending.current.clear();
  }, []);
  useEffect(() => {
    invalidate();
    return invalidate;
  }, [context, invalidate]);
  async function read(id: string, entry?: Entry, view?: BidPackageStoredView) {
    if (changed || !contextValid || pending.current.has(id)) return;
    const token = generation.current;
    pending.current.add(id);
    setCitations((old) => ({
      ...old,
      [id]: { loading: true, ownParts: [], authorityParts: [] },
    }));
    try {
      const { data } = await api<EvidenceView>(`/evidence/${id}`);
      const own = memberships(packageView, data),
        authority = memberships(authorityView, data);
      let issue: string | undefined;
      if (
        data.id !== id ||
        !Number.isSafeInteger(data.physical_page) ||
        data.physical_page < 1 ||
        (!own.length && !authority.length)
      )
        issue = "引用不属于所冻文件、解析及物理范围";
      else if (data.source_status !== "published")
        issue =
          data.source_status === "withdrawn"
            ? "引用已撤回，不可选用"
            : "引用尚未发布，不可选用";
      else if (
        entry &&
        view &&
        (entry.document_version_id !== data.document_version_id ||
          entry.parse_run_id !== data.parse_run_id ||
          entry.physical_page !== data.physical_page ||
          [...entry.part_ids].sort().join("\0") !==
            memberships(view, data).sort().join("\0"))
      )
        issue = "原页引用与目录的精确身份不一致";
      if (generation.current === token)
        setCitations((old) => ({
          ...old,
          [id]: {
            value: data,
            ownParts: own,
            authorityParts: authority,
            ...(issue ? { issue } : {}),
          },
        }));
    } catch {
      if (generation.current === token)
        setCitations((old) => ({
          ...old,
          [id]: {
            issue: "精确引用读取失败，请重新读取",
            ownParts: [],
            authorityParts: [],
          },
        }));
    } finally {
      if (generation.current === token) pending.current.delete(id);
    }
  }
  const restored = JSON.stringify([
    ...new Set((initialResults ?? []).flatMap((r) => r.evidence_ids)),
  ]);
  useEffect(() => {
    for (const id of JSON.parse(restored) as string[]) void read(id);
    // Restored IDs are a prior explicit choice, never a latest-parse discovery.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restored, context]);
  function draftFor(id: string): Draft {
    return (
      drafts[id] ?? {
        enabled: false,
        state: "unknown",
        reason: "",
        confirmed: false,
        ranges: {},
        evidenceIds: [],
      }
    );
  }
  function patch(id: string, value: Partial<Draft>) {
    if (locked) return;
    setDirty(true);
    setDrafts((old) => ({ ...old, [id]: { ...draftFor(id), ...value } }));
  }
  function targets(binding: (typeof inv.requirements)[number]) {
    const req = binding.requirement;
    return ownParts.filter(({ part }) =>
      req.target_part_ids.length
        ? req.target_part_ids.includes(part.part_id)
        : req.categories.includes(part.category),
    );
  }
  function gates(binding: (typeof inv.requirements)[number]) {
    const req = binding.requirement;
    const common =
      binding.source_bound &&
      binding.decision_snapshot?.decision === "confirmed" &&
      binding.rule_snapshot.provenance_status === "effective";
    const selected = targets(binding);
    return {
      verified:
        common &&
        req.applicability === "applicable" &&
        selected.length > 0 &&
        selected.every(
          (p) =>
            p.member.parse.status === "frozen" && p.member.page_count !== null,
        ) &&
        (req.minimum_count === null || req.checks.includes("quantity")),
      not_applicable:
        common &&
        req.applicability === "not_applicable" &&
        req.applicability_evidence.length > 0,
    };
  }
  function rangesFor(draft: Draft, binding: (typeof inv.requirements)[number]) {
    const selected = targets(binding);
    const ranges: Result["inspected"] = [];
    let valid = true;
    for (const [partId, row] of Object.entries(draft.ranges)) {
      if (!row.enabled) continue;
      const part = selected.find((p) => p.part.part_id === partId)?.part;
      const first = pageNumber(row.first),
        last = pageNumber(row.last);
      if (
        !part ||
        !Number.isFinite(first) ||
        !Number.isFinite(last) ||
        first < part.first_page ||
        last > part.last_page ||
        first > last
      ) {
        valid = false;
        continue;
      }
      ranges.push({ part_id: partId, first_page: first, last_page: last });
    }
    const complete =
      selected.length > 0 &&
      selected.every(({ part }) =>
        ranges.some(
          (r) =>
            r.part_id === part.part_id &&
            r.first_page === part.first_page &&
            r.last_page === part.last_page,
        ),
      );
    return { ranges, valid, complete };
  }
  function usable(
    id: string,
    draft: Draft,
    binding: (typeof inv.requirements)[number],
  ) {
    const record = citations[id];
    if (!record?.value || record.issue || record.loading) return false;
    if (draft.state !== "verified")
      return record.ownParts.length > 0 || record.authorityParts.length > 0;
    return rangesFor(draft, binding).ranges.some(
      (range) =>
        record.ownParts.includes(range.part_id) &&
        range.first_page <= record.value!.physical_page &&
        record.value!.physical_page <= range.last_page,
    );
  }
  const value = useMemo<CoverageEditorValue>(() => {
    const results: Result[] = [];
    let valid = contextValid && !changed;
    for (const binding of inv.requirements) {
      const draft = draftFor(binding.rule_id);
      if (!draft.enabled) continue;
      const range = rangesFor(draft, binding),
        positive = isPositive(draft.state),
        gate = gates(binding);
      const good =
        validReason(draft.reason) &&
        range.valid &&
        new Set(draft.evidenceIds).size === draft.evidenceIds.length &&
        draft.evidenceIds.every((id) => usable(id, draft, binding)) &&
        (!positive ||
          (draft.confirmed &&
            draft.evidenceIds.length > 0 &&
            (draft.state === "verified"
              ? gate.verified && range.complete
              : gate.not_applicable)));
      if (!good) {
        valid = false;
        continue;
      }
      results.push({
        rule_id: binding.rule_id,
        requirement_digest: binding.requirement_digest,
        state: draft.state,
        reason: draft.reason.trim(),
        basis_type: positive ? "human_scope_declaration" : "human_observation",
        inspected: range.ranges,
        evidence_ids: [...draft.evidenceIds],
      });
    }
    return { results: changed ? [] : results, valid, dirty: dirty || changed };
    // Local helpers read these immutable snapshots and current draft/citation state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextValid, changed, context, drafts, citations, dirty]);
  const signature = JSON.stringify(value);
  const callback = useRef(onChange);
  callback.current = onChange;
  useEffect(() => {
    callback.current(JSON.parse(signature) as CoverageEditorValue);
  }, [signature]);

  return (
    <section className="coverage-editor" aria-label="本次人工覆盖记录">
      <h4>本次人工覆盖记录</h4>
      <p>
        每次记录独立保存。不勾选的条款在本次为未知，不继承旧记录；这里只声明人工观察或检查范围，不表示合规通过或正式审查完成。
      </p>
      <h5>本方成员解析缺口</h5>
      {packageView.manifest.members.map((member, i) => {
        const gaps = [
          member.page_count === null ? "页数未知" : "",
          !member.parts.length ? "逻辑范围未分配" : "",
          member.parse.status !== "frozen" ? "解析身份尚未冻结" : "",
        ].filter(Boolean);
        return gaps.length ? (
          <p key={member.member_id}>
            文件 {i + 1}：{gaps.join("、")}
            。这是解析范围缺口，不自动认定某条要求缺件。
          </p>
        ) : null;
      })}
      {packageView.manifest.members.every(
        (member) =>
          member.page_count !== null &&
          member.parts.length > 0 &&
          member.parse.status === "frozen",
      ) && <p>当前未列成员解析缺口；不表示整包完整或符合全部要求。</p>}
      {(!contextValid || changed) && (
        <p role="alert">
          包、要求清单或冻结依据已变化，原输入已锁定；请保留原记录并重新核对当前上下文。
        </p>
      )}
      {!contextValid && !!initialResults?.length && (
        <details>
          <summary>保留的恢复原记录（待核）</summary>
          <p>
            同一分册的多个独立页段尚不在本编辑器的填写范围内，或原记录身份不匹配；不会合并、丢弃或改发为新记录。
          </p>
          <pre>{JSON.stringify(initialResults, null, 2)}</pre>
        </details>
      )}
      {inv.requirements.map((binding, index) => {
        const draft = draftFor(binding.rule_id),
          gate = gates(binding),
          target = targets(binding);
        const pos = isPositive(draft.state);
        function toggleEvidence(id: string) {
          patch(binding.rule_id, {
            evidenceIds: draft.evidenceIds.includes(id)
              ? draft.evidenceIds.filter((v) => v !== id)
              : [...draft.evidenceIds, id],
          });
        }
        function renderEntry(
          entry: Entry,
          n: number,
          view: BidPackageStoredView,
        ) {
          const citation = citations[entry.id],
            selected = draft.evidenceIds.includes(entry.id);
          return (
            <div key={entry.id} className="coverage-editor-evidence">
              <p>
                证据 {n + 1} · 物理页 {entry.physical_page} ·{" "}
                {entry.part_ids.length} 个冻结逻辑范围
              </p>
              <button
                type="button"
                disabled={locked || citation?.loading}
                onClick={() => void read(entry.id, entry, view)}
              >
                读取证据 {n + 1} 原句
              </button>
              {citation?.loading && <p>正在核对精确引用…</p>}
              {citation?.issue && <p role="alert">{citation.issue}</p>}
              {citation?.value &&
                !citation.issue &&
                !citation.loading &&
                !selected && <blockquote>{citation.value.quote}</blockquote>}
              <label>
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={
                    locked || (!selected && !usable(entry.id, draft, binding))
                  }
                  onChange={() => toggleEvidence(entry.id)}
                />
                要求 {index + 1} 采用证据 {n + 1}
              </label>
              {citation?.value &&
                !citation.issue &&
                !usable(entry.id, draft, binding) &&
                draft.state === "verified" && (
                  <p>
                    此证据不属于本次已填受检范围内的本方材料，不能代替本方证明。
                  </p>
                )}
            </div>
          );
        }
        return (
          <article key={binding.rule_id}>
            <label>
              <input
                type="checkbox"
                checked={draft.enabled}
                disabled={locked}
                onChange={() =>
                  patch(binding.rule_id, { enabled: !draft.enabled })
                }
              />
              纳入本次要求 {index + 1}
            </label>
            <p>
              {typeof binding.rule_snapshot.statement === "string"
                ? binding.rule_snapshot.statement
                : `要求 ${index + 1}`}
            </p>
            {draft.enabled && (
              <fieldset disabled={locked}>
                <legend>要求 {index + 1} 的本次记录</legend>
                <label>
                  要求 {index + 1} 本次状态
                  <select
                    value={draft.state}
                    onChange={(e) =>
                      patch(binding.rule_id, {
                        state: e.target.value as Result["state"],
                        confirmed: false,
                      })
                    }
                  >
                    {Object.entries(labels).map(([state, label]) => (
                      <option
                        key={state}
                        value={state}
                        disabled={
                          state === "verified"
                            ? !gate.verified
                            : state === "not_applicable"
                              ? !gate.not_applicable
                              : false
                        }
                      >
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {!gate.verified && !gate.not_applicable && (
                  <p>
                    本条冻结的来源、决定、适用性或解析条件尚不允许正向人工声明；仍可记录明确的负向观察或未知。
                  </p>
                )}
                <label>
                  要求 {index + 1} 理由（最多200字）
                  <textarea
                    value={draft.reason}
                    onChange={(e) =>
                      patch(binding.rule_id, { reason: e.target.value })
                    }
                  />
                </label>
                <p>
                  明确受检物理范围（可不填写负向观察的范围；完整范围声明须覆盖所有目标）
                </p>
                {!target.length && (
                  <p>
                    尚无可定位的本方目标范围，可以记录观察，不能声明完整范围。
                  </p>
                )}
                {target.map(({ part, fileIndex, partIndex }) => {
                  const range = draft.ranges[part.part_id] ?? {
                    enabled: false,
                    first: "",
                    last: "",
                  };
                  return (
                    <div className="coverage-editor-range" key={part.part_id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={range.enabled}
                          onChange={() =>
                            patch(binding.rule_id, {
                              ranges: {
                                ...draft.ranges,
                                [part.part_id]: {
                                  ...range,
                                  enabled: !range.enabled,
                                },
                              },
                            })
                          }
                        />
                        要求 {index + 1} 文件 {fileIndex} · 分册 {partIndex} ·{" "}
                        {categoryNames[part.category] ?? part.category} · 物理页{" "}
                        {part.first_page}—{part.last_page}
                      </label>
                      {range.enabled && (
                        <>
                          <label>
                            要求 {index + 1} 文件 {fileIndex} 分册 {partIndex}{" "}
                            起始物理页
                            <input
                              inputMode="numeric"
                              value={range.first}
                              onChange={(e) =>
                                patch(binding.rule_id, {
                                  ranges: {
                                    ...draft.ranges,
                                    [part.part_id]: {
                                      ...range,
                                      first: e.target.value,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                          <label>
                            要求 {index + 1} 文件 {fileIndex} 分册 {partIndex}{" "}
                            结束物理页
                            <input
                              inputMode="numeric"
                              value={range.last}
                              onChange={(e) =>
                                patch(binding.rule_id, {
                                  ranges: {
                                    ...draft.ranges,
                                    [part.part_id]: {
                                      ...range,
                                      last: e.target.value,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                        </>
                      )}
                    </div>
                  );
                })}
                {pos && (
                  <label>
                    <input
                      type="checkbox"
                      checked={draft.confirmed}
                      onChange={() =>
                        patch(binding.rule_id, { confirmed: !draft.confirmed })
                      }
                    />
                    {draft.state === "verified"
                      ? "我明确声明已人工检查本次全部目标范围与所选本方证据；这不表示合规通过"
                      : "我明确声明已人工核对本条不适用依据与所选证据；这不表示系统验收"}
                  </label>
                )}
                <Picker
                  label={`选择要求 ${index + 1} 本方证据`}
                  bidId={bidId}
                  view={packageView}
                  disabled={locked}
                  renderEntry={(e, n) => renderEntry(e, n, packageView)}
                />
                {draft.state !== "verified" && (
                  <Picker
                    label={`选择要求 ${index + 1} 权威依据证据`}
                    bidId={bidId}
                    view={authorityView}
                    disabled={locked}
                    renderEntry={(e, n) => renderEntry(e, n, authorityView)}
                  />
                )}
                {!!draft.evidenceIds.length && (
                  <div>
                    <p>已明确选择的引用</p>
                    {draft.evidenceIds.map((id, n) => {
                      const citation = citations[id];
                      return (
                        <div key={id}>
                          <p>
                            已选证据 {n + 1}
                            {citation?.value
                              ? ` · 物理页 ${citation.value.physical_page}`
                              : ""}
                          </p>
                          {citation?.loading && <p>正在重新核对所冻引用…</p>}
                          {citation?.issue && (
                            <p role="alert">{citation.issue}</p>
                          )}
                          {citation?.value &&
                            !citation.issue &&
                            !citation.loading && (
                              <blockquote>{citation.value.quote}</blockquote>
                            )}
                          {!usable(id, draft, binding) && (
                            <p>
                              所选引用当前不可用于本条状态或范围；保留原选择等待核对。
                            </p>
                          )}
                          <button
                            type="button"
                            onClick={() => void read(id)}
                            disabled={citation?.loading}
                          >
                            重读已选证据 {n + 1}
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleEvidence(id)}
                          >
                            移除已选证据 {n + 1}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
                <details>
                  <summary>要求与目标冻结身份</summary>
                  <p>
                    {binding.rule_id} · 要求摘要 {binding.requirement_digest}
                  </p>
                  {target.map((p) => (
                    <p key={p.part.part_id}>
                      文件 {p.fileIndex} · 分册 {p.partIndex}：{p.part.part_id}{" "}
                      · 文件版本 {p.member.document_version_id} · 解析{" "}
                      {p.member.parse.parse_run_id ?? "未冻结"}
                    </p>
                  ))}
                </details>
              </fieldset>
            )}
          </article>
        );
      })}
      <p role="status">
        {value.valid
          ? `${value.results.length} 条本次记录可提交核对；整体完整性与正式审查资格仍未形成。`
          : "本次记录尚不完整，或状态门槛、物理范围、明确声明、理由及证据仍需核对。"}
      </p>
    </section>
  );
}
