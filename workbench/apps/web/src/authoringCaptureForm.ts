import type {
  AuthoringWorkContext,
  BidPackageStoredView,
  PackageAuthoringFactCatalog,
  PackageAuthoringInputRequest,
  PackageAuthoringNodeCatalog,
  PackageRequirementInventoryView,
  WorkContextDraftSelection,
} from "./contracts";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalSame as same } from "./historicalImportProtocol";
import {
  authoringInteger as integer,
  validateAuthoringInputRequest,
} from "./packageAuthoringInputProtocol";
import { validAuthoringSelection } from "./workContextAuthoringProtocol";
import {
  captureFailure,
  captureIdentityNames,
  type CaptureFact,
  type CaptureIdentityName,
  type CapturePackageReference,
} from "./authoringInputCatalogProtocol";

export type CaptureSnapshotChoice = {
  id: string;
  label: string;
  selection_digest: string;
  selection: WorkContextDraftSelection;
};
export type CaptureDraft = {
  version: 1;
  target: CapturePackageReference | null;
  authority: CapturePackageReference | null;
  inventory: { id: string; digest: string } | null;
  snapshot: CaptureSnapshotChoice | null;
  section: { id: string; digest: string } | null;
  node: { id: string; digest: string } | null;
  factSet: { id: string; digest: string; head_revision: number } | null;
  identities: Record<CaptureIdentityName, string>;
  uses: {
    fact_id: string;
    subject_kind:
      | ""
      | PackageAuthoringInputRequest["facts"]["uses"][number]["subject"]["kind"];
    reason: string;
  }[];
};
export function emptyCaptureDraft(): CaptureDraft {
  return {
    version: 1,
    target: null,
    authority: null,
    inventory: null,
    snapshot: null,
    section: null,
    node: null,
    factSet: null,
    identities: Object.fromEntries(
      captureIdentityNames.map((n) => [n, ""]),
    ) as CaptureDraft["identities"],
    uses: [],
  };
}
export function readCaptureDraft(v: unknown, bid: string): CaptureDraft {
  if (
    !object(v) ||
    !exactKeys(v, [
      "version",
      "target",
      "authority",
      "inventory",
      "snapshot",
      "section",
      "node",
      "factSet",
      "identities",
      "uses",
    ]) ||
    v.version !== 1 ||
    !object(v.identities) ||
    !exactKeys(v.identities, [...captureIdentityNames]) ||
    Object.values(v.identities).some((id) => id !== "" && !uuid(id)) ||
    !Array.isArray(v.uses) ||
    v.uses.length > 500
  )
    captureFailure("本机采集草稿格式不完整；没有发送或替换为默认选择。");
  for (const role of ["target", "authority"]) {
    const p = v[role];
    if (
      p !== null &&
      (!object(p) ||
        !exactKeys(p, ["package_id", "revision_id", "manifest_digest"]) ||
        !uuid(p.package_id) ||
        !uuid(p.revision_id) ||
        !sha(p.manifest_digest))
    )
      captureFailure();
  }
  for (const name of ["inventory", "section", "node", "factSet"]) {
    const p = v[name];
    if (
      p !== null &&
      (!object(p) ||
        !exactKeys(
          p,
          name === "factSet"
            ? ["id", "digest", "head_revision"]
            : ["id", "digest"],
        ) ||
        !(name === "node"
          ? typeof p.id === "string" && !!p.id && p.id.length <= 200
          : uuid(p.id)) ||
        !sha(p.digest) ||
        (name === "factSet" && !integer(p.head_revision)))
    )
      captureFailure();
  }
  if (
    v.snapshot !== null &&
    (!object(v.snapshot) ||
      !exactKeys(v.snapshot, [
        "id",
        "label",
        "selection_digest",
        "selection",
      ]) ||
      !uuid(v.snapshot.id) ||
      typeof v.snapshot.label !== "string" ||
      !v.snapshot.label ||
      !sha(v.snapshot.selection_digest) ||
      !validAuthoringSelection(v.snapshot.selection, bid) ||
      v.snapshot.selection.kind !== "draft_snapshot" ||
      v.snapshot.id !== v.snapshot.selection.snapshot_id)
  )
    captureFailure();
  if (
    v.uses.some(
      (u) =>
        !object(u) ||
        !exactKeys(u, ["fact_id", "subject_kind", "reason"]) ||
        !uuid(u.fact_id) ||
        !["", "engineering_project", "lot", "round", "bidder"].includes(
          String(u.subject_kind),
        ) ||
        typeof u.reason !== "string" ||
        u.reason.length > 2000,
    ) ||
    new Set(v.uses.map((u) => u.fact_id)).size !== v.uses.length
  )
    captureFailure();
  return v as CaptureDraft;
}
export type CaptureVerified = {
  target: BidPackageStoredView;
  authority: BidPackageStoredView;
  inventory: PackageRequirementInventoryView;
  snapshot: AuthoringWorkContext;
  nodes: PackageAuthoringNodeCatalog;
  facts: PackageAuthoringFactCatalog;
  items: CaptureFact[];
};
export function buildCaptureRequest(
  d: CaptureDraft,
  verified: CaptureVerified,
): PackageAuthoringInputRequest {
  const { target, authority, inventory, snapshot, nodes, facts, items } =
    verified;
  if (
    !d.target ||
    !d.authority ||
    !d.inventory ||
    !d.snapshot ||
    !d.section ||
    !d.node ||
    !d.factSet ||
    nodes.blocking_reasons.length ||
    facts.blocking_reasons.length ||
    !nodes.whole_snapshot_plain ||
    !nodes.structure_supported ||
    !facts.head_matches ||
    !facts.package_identity_matches ||
    snapshot.selection.kind !== "draft_snapshot" ||
    !same(snapshot.selection, d.snapshot.selection) ||
    snapshot.selection_digest !== d.snapshot.selection_digest
  )
    captureFailure("请完成明确选择，并重新核对当前依据后保存。");
  for (const [p, selection] of [
    [target, d.target],
    [authority, d.authority],
  ] as const)
    if (
      p.manifest.package_id !== selection.package_id ||
      p.manifest.revision_id !== selection.revision_id ||
      p.digest !== selection.manifest_digest
    )
      captureFailure();
  if (
    inventory.manifest.id !== d.inventory.id ||
    inventory.digest !== d.inventory.digest ||
    inventory.manifest.target_revision_id !== d.target.revision_id ||
    inventory.manifest.package_digest !== d.target.manifest_digest ||
    inventory.manifest.authority_revision_id !== d.authority.revision_id ||
    inventory.manifest.authority_digest !== d.authority.manifest_digest ||
    nodes.bid_id !== snapshot.selection.bid_id ||
    nodes.target.snapshot_id !== d.snapshot.id ||
    nodes.target.snapshot_digest !== d.snapshot.selection.snapshot_digest ||
    nodes.target.draft_id !== d.snapshot.selection.draft_id ||
    nodes.target.base_draft_revision !== d.snapshot.selection.draft_revision ||
    nodes.target.section_id !== d.section.id ||
    nodes.target.section_digest !== d.section.digest ||
    !nodes.nodes.some(
      (n) =>
        n.node_id === d.node!.id && n.before_node_digest === d.node!.digest,
    ) ||
    !same(facts.selection, {
      fact_set_id: d.factSet.id,
      fact_set_digest: d.factSet.digest,
      fact_head_revision: d.factSet.head_revision,
      target: d.target,
      authority: d.authority,
    })
  )
    captureFailure();
  const byId = new Map(items.map((item) => [item.fact_id, item]));
  const identityIds = captureIdentityNames.map((name) => {
    const item = byId.get(d.identities[name]);
    if (
      !item ||
      item.identity_name !== name ||
      !item.identity_value_usable ||
      item.provenance_status !== "verified"
    )
      captureFailure("五项编号都需要明确选择本次已核验的原页事实。");
    return item.fact_id;
  });
  const uses = d.uses.map((use) => {
    const item = byId.get(use.fact_id),
      subject = facts.subject_choices.find((s) => s.kind === use.subject_kind);
    if (
      !item ||
      item.provenance_status !== "verified" ||
      !subject ||
      !use.reason.trim()
    )
      captureFailure("已选择的事实用途还需要明确作用对象与理由。");
    return {
      fact_id: item.fact_id,
      fact_item_digest: item.fact_item_digest,
      subject,
      reason: use.reason,
    };
  });
  return validateAuthoringInputRequest({
    protocol: "package-authoring-input-request/1",
    purpose: "authoring",
    target_relation: "draft_using_package_context",
    package_context: {
      target: d.target,
      authority: d.authority,
      inventory: {
        id: d.inventory.id,
        digest: d.inventory.digest,
        rule_set_id: inventory.manifest.rule_set_id,
      },
    },
    target_section: {
      ...nodes.target,
      node_id: d.node.id,
      before_node_digest: d.node.digest,
    },
    facts: {
      fact_set_id: d.factSet.id,
      fact_head_revision: d.factSet.head_revision,
      identity_fact_ids: identityIds,
      uses,
    },
  });
}
