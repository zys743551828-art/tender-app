// Synthetic frontend protocol fixtures; domain/PG acceptance is separate.
import type {
  BidPackageStoredView,
  PackageRequirementInventoryView,
  PackageRuleCorrectionAppliedView,
  PackageRuleCorrectionEvidenceDetail,
  PackageRuleCorrectionEvidencePage,
  PackageRuleCorrectionPreviewView,
  PackageRuleCorrectionRequest,
  PackageRuleCorrection_RuleAddition as RuleAddition,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  correctionEvidenceTextDigest,
  type CorrectionSemantic,
} from "./packageRuleCorrectionProtocol";
import {
  correctionBase,
  type PendingCorrection,
} from "./packageRuleCorrectionRecovery";

export function omitCorrectionFixture<T extends object, K extends keyof T>(
  value: T,
  keys: K[],
): Omit<T, K> {
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => !keys.includes(key as K)),
  ) as Omit<T, K>;
}
export const correctionId = (value: number) =>
  `20000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
const scope = {
  engineering_project_id: correctionId(30),
  lot_id: correctionId(31),
  round_id: correctionId(32),
  bid_id: correctionId(2),
  bidder_id: correctionId(33),
  bidder_status: "confirmed" as const,
};
export const correctionScope = {
  memberId: correctionId(1),
  bidId: scope.bid_id,
  packageId: correctionId(3),
  revisionId: correctionId(4),
  packageDigest: "a".repeat(64),
};
export const correctionPackage: BidPackageStoredView = {
  digest: correctionScope.packageDigest,
  storage_eligible: true,
  review_ready: false,
  manifest: {
    package_id: correctionScope.packageId,
    revision_id: correctionScope.revisionId,
    revision: 1,
    identity_version: "bid-package/1",
    kind: "bid",
    scope,
    predecessor_digest: null,
    members: [
      {
        member_id: "本方技术册",
        document_version_id: correctionId(34),
        file_digest: "b".repeat(64),
        source_kind: "own",
        source_ref: "synthetic:body",
        scope,
        purposes: ["技术"],
        page_count: 3,
        parse: {
          status: "frozen",
          parse_run_id: correctionId(35),
          parser_digest: "c".repeat(64),
          config_digest: "d".repeat(64),
          evidence_digest: "e".repeat(64),
          reason: null,
        },
        parts: [
          {
            part_id: "技术正文",
            category: "技术",
            first_page: 1,
            last_page: 3,
            shared_attachment: false,
            heading_path: [],
          },
        ],
      },
    ],
  },
  identity: {
    identity_version: "bid-identity/2",
    bidder_id: scope.bidder_id,
    bidder_name: "合成投标单位",
    round_id: scope.round_id,
    engineering_project_id: scope.engineering_project_id,
    engineering_title: "合成验收项目",
    region: null,
    engineering_type: null,
    lot: "一标段",
    lot_id: scope.lot_id,
    round_no: 1,
    binding_status: "confirmed",
    authority_id: correctionId(36),
    digest: "f".repeat(64),
  },
};
export const correctionSourceText =
  "仅本标段适用。须提交施工方案。除正式补遗另有说明。安全保障须列明责任人。最高12.50分；优良方案得10.25分；一般方案得5.00分。原投标保证金要求取消。";
export const correctionRule = (): RuleAddition => ({
  kind: "mandatory",
  statement: "安全保障须列明责任人",
  conditions: ["仅本标段适用"],
  exceptions: ["除正式补遗另有说明"],
  scope: { bid_id: correctionScope.bidId, description: "一标段" },
  maximum: null,
  bands: [],
  evidence_quotes: [
    { evidence_id: correctionId(40), quote: correctionSourceText },
  ],
});
function semantic(rule: RuleAddition): CorrectionSemantic {
  return {
    kind: rule.kind,
    statement: rule.statement,
    conditions: rule.conditions,
    exceptions: rule.exceptions,
    max_points: rule.maximum,
    bands: rule.bands,
    evidence_ids: [...new Set(rule.evidence_quotes.map((q) => q.evidence_id))],
    applicability_scope: rule.scope,
    provenance_status: "effective",
  };
}
function originalSemantic(index: number): CorrectionSemantic {
  return {
    ...semantic(correctionRule()),
    statement: ["须提交施工方案", "须提供原投标保证金", "未选商务条件保持原样"][
      index
    ],
    conditions: ["仅本标段适用"],
    exceptions: ["除正式补遗另有说明"],
  };
}
export async function correctionFixture() {
  const bindings = await Promise.all(
    [0, 1, 2].map(async (index) => {
      const ruleId = correctionId(60 + index);
      const snapshot = {
        id: ruleId,
        bid_id: correctionScope.bidId,
        rule_set_id: correctionId(7),
        ...originalSemantic(index),
        origin_kind: "model_extracted",
        manual_origin_rule_id: null,
      };
      const requirement = {
        requirement_id: ruleId,
        scope,
        origin: "authority" as const,
        source_refs: [`evidence:${correctionId(40)}`],
        categories: ["技术"],
        target_part_ids: ["技术正文"],
        minimum_count: null,
        applicability: "unknown" as const,
        applicability_evidence: [],
        valid_at: null,
        conditions: [],
        checks: [],
        identity_version: "bid-requirement/1" as const,
      };
      return {
        rule_id: ruleId,
        rule_digest: await jsonDigest(snapshot),
        rule_snapshot: snapshot,
        decision_id: null,
        decision_snapshot: null,
        requirement,
        requirement_digest: await jsonDigest(requirement),
        source_bound: true,
        annotation: {
          kind: "human_check_plan_declaration" as const,
          mapped: index === 0,
          reason: index === 0 ? "旧范围记录" : null,
          basis_evidence_ids: index === 0 ? [correctionId(40)] : [],
        },
      };
    }),
  );
  const manifest: PackageRequirementInventoryView["manifest"] = {
    version: "bid-package-requirements/2",
    id: correctionId(5),
    bid_id: correctionScope.bidId,
    package_id: correctionScope.packageId,
    target_revision_id: correctionScope.revisionId,
    package_digest: correctionScope.packageDigest,
    authority_revision_id: correctionId(6),
    authority_digest: "b".repeat(64),
    rule_set_id: correctionId(7),
    rule_set_digest: "c".repeat(64),
    revision: 2,
    predecessor_digest: null,
    identity_digest: correctionPackage.identity.digest,
    source_snapshot: [
      { source_id: correctionId(8), source_digest: "d".repeat(64) },
    ],
    requirements: bindings,
    inventory_complete: false,
    review_ready: false,
    actor_id: correctionScope.memberId,
    extraction_binding: "exact_frozen_input_result",
    extraction_input_digest: "1".repeat(64),
    extraction_result_digest: "2".repeat(64),
    extraction_result_id: correctionId(9),
    extraction_range_status: "all_frozen_evidence_submitted",
    extraction_coverage: "partial",
    extraction_quality_status: "not_measured",
  };
  const inventory: PackageRequirementInventoryView = {
    manifest,
    digest: await jsonDigest(manifest),
  };
  const evidence: PackageRuleCorrectionEvidenceDetail = {
    scope: {
      bid_id: correctionScope.bidId,
      package_id: correctionScope.packageId,
      revision_id: correctionScope.revisionId,
      inventory_id: manifest.id,
    },
    inventory_digest: inventory.digest,
    authority: {
      revision_id: manifest.authority_revision_id,
      digest: manifest.authority_digest,
      identity_digest: manifest.identity_digest,
    },
    evidence: {
      evidence_id: correctionId(40),
      member_id: "招标原件",
      document_version_id: correctionId(41),
      parse_run_id: correctionId(42),
      physical_page: 3,
      evidence_digest: await correctionEvidenceTextDigest(correctionSourceText),
      file_digest: "4".repeat(64),
      ordinal: 0,
      kind: "text",
      part_ids: ["招标条款"],
      text_content: correctionSourceText,
    },
  };
  const entry = omitCorrectionFixture(evidence.evidence, ["text_content"]);
  const page: PackageRuleCorrectionEvidencePage = {
    scope: evidence.scope,
    inventory_digest: inventory.digest,
    authority: evidence.authority,
    items: [{ ...entry, excerpt: "仅摘要，不能直接作为逐字引用" }],
    has_more: false,
    next_cursor: null,
  };
  const request: PackageRuleCorrectionRequest = {
    base_inventory_digest: inventory.digest,
    base_rule_set_digest: manifest.rule_set_digest,
    reason: "核对冻结招标原页，补齐安全保障责任",
    changes: [{ op: "add", rule: correctionRule() }],
  };
  return {
    inventory,
    evidence,
    page,
    request,
    etag: `"requirement-inventory:${correctionScope.revisionId}:${inventory.digest}"`,
  };
}
export async function correctionPreview(
  inventory: PackageRequirementInventoryView,
  request: PackageRuleCorrectionRequest,
  detail: PackageRuleCorrectionEvidenceDetail,
) {
  const m = inventory.manifest;
  if (m.version === "bid-package-requirements/1")
    throw new Error("Fixture requires an exact root");
  const basis =
    m.version === "bid-package-requirements/3"
      ? m.extraction_basis
      : {
          inventory_id: m.id,
          inventory_digest: inventory.digest,
          rule_set_id: m.rule_set_id,
          rule_set_digest: m.rule_set_digest,
          extraction_result_id: m.extraction_result_id,
          extraction_input_digest: m.extraction_input_digest,
          extraction_result_digest: m.extraction_result_digest,
          extraction_range_status: m.extraction_range_status,
          extraction_coverage: m.extraction_coverage,
          extraction_quality_status: m.extraction_quality_status,
        };
  const changes = request.changes.map((change, index) => {
    const old =
      change.op === "add"
        ? null
        : m.requirements.find((item) => item.rule_id === change.rule_id)!;
    const before = old
      ? (Object.fromEntries(
          Object.keys(originalSemantic(0)).map((key) => [
            key,
            old.rule_snapshot[key],
          ]),
        ) as CorrectionSemantic)
      : null;
    const selected =
      change.op === "withdraw"
        ? change.evidence_quotes
        : change.rule.evidence_quotes;
    return {
      index,
      op: change.op,
      rule_id: change.op === "add" ? null : change.rule_id,
      rule_digest: change.op === "add" ? null : change.rule_digest,
      before,
      after:
        change.op === "withdraw"
          ? { ...before!, provenance_status: "superseded" as const }
          : semantic(change.rule),
      quotes: selected.map((quote) => ({
        evidence_id: quote.evidence_id,
        quote: quote.quote,
        member_id: detail.evidence.member_id,
        document_version_id: detail.evidence.document_version_id,
        parse_run_id: detail.evidence.parse_run_id,
        physical_page: detail.evidence.physical_page,
        evidence_digest: detail.evidence.evidence_digest,
        part_ids: detail.evidence.part_ids,
      })),
    };
  });
  const added = changes.filter((change) => change.op === "add").length,
    replaced = changes.filter((change) => change.op === "replace").length,
    withdrawn = changes.filter((change) => change.op === "withdraw").length;
  const preview: PackageRuleCorrectionPreviewView = {
    digest: "",
    manifest: {
      version: "package-rule-correction-preview/1",
      scope: detail.scope,
      base: {
        inventory_digest: inventory.digest,
        rule_set_id: m.rule_set_id,
        rule_set_digest: m.rule_set_digest,
      },
      authority: detail.authority,
      extraction_basis: basis,
      previous:
        m.version === "bid-package-requirements/3"
          ? {
              id: m.human_derivation.head_id,
              digest: m.human_derivation.head_digest,
            }
          : null,
      sequence_no:
        m.version === "bid-package-requirements/3"
          ? m.human_derivation.length + 1
          : 1,
      policy_digest: "5".repeat(64),
      request,
      request_digest: await jsonDigest(request),
      source_snapshot_digest: await jsonDigest(m.source_snapshot),
      changes,
      counts: {
        before: m.requirements.length,
        after: m.requirements.length + added,
        carried: m.requirements.length - replaced - withdrawn,
        added,
        replaced,
        withdrawn,
        active_after: m.requirements.length + added - withdrawn,
      },
      limitations: [
        "ROOT_EXTRACTION_PARTIAL",
        "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
      ],
      inventory_complete: false,
      review_ready: false,
      original_bytes_verified: false,
    },
  };
  preview.digest = await jsonDigest(preview.manifest);
  return preview;
}
export async function correctionApplied(
  inventory: PackageRequirementInventoryView,
  preview: PackageRuleCorrectionPreviewView,
  pending?: PendingCorrection,
): Promise<PackageRuleCorrectionAppliedView> {
  const m = inventory.manifest,
    pm = preview.manifest;
  const newSet = correctionId(100),
    newInventory = correctionId(101);
  const mappings: PackageRuleCorrectionAppliedView["correction"]["manifest"]["mappings"] =
    [];
  const additions: PackageRuleCorrectionAppliedView["correction"]["manifest"]["additions"] =
    [];
  const requirements: typeof m.requirements = [];
  for (const [index, old] of m.requirements.entries()) {
    const change = pm.changes.find((item) => item.rule_id === old.rule_id);
    const newId = correctionId(200 + index);
    const snapshot = {
      ...old.rule_snapshot,
      ...(change?.after ?? {}),
      id: newId,
      rule_set_id: newSet,
      ...(change?.op === "replace"
        ? { origin_kind: "human_added", manual_origin_rule_id: newId }
        : {}),
    };
    const digest = await jsonDigest(snapshot);
    mappings.push({
      from_rule_id: old.rule_id,
      from_rule_digest: old.rule_digest,
      to_rule_id: newId,
      to_rule_digest: digest,
      op:
        change?.op === "replace" || change?.op === "withdraw"
          ? change.op
          : "carry",
      change_index: change?.index ?? null,
    });
    const requirement = { ...old.requirement, requirement_id: newId };
    const reset = change?.op === "replace";
    requirements.push({
      ...old,
      rule_id: newId,
      rule_digest: digest,
      rule_snapshot: snapshot,
      requirement,
      requirement_digest: await jsonDigest(requirement),
      decision_id: change ? correctionId(300 + index) : old.decision_id,
      decision_snapshot: change
        ? {
            id: correctionId(300 + index),
            decision: change.op === "withdraw" ? "rejected" : "confirmed",
          }
        : old.decision_snapshot,
      annotation: reset
        ? {
            kind: "human_check_plan_declaration",
            mapped: false,
            reason: null,
            basis_evidence_ids: [],
          }
        : old.annotation,
    });
  }
  for (const change of pm.changes.filter((item) => item.op === "add")) {
    const newId = correctionId(400 + change.index);
    const snapshot = {
      ...change.after,
      id: newId,
      bid_id: correctionScope.bidId,
      rule_set_id: newSet,
      origin_kind: "human_added",
      manual_origin_rule_id: newId,
    };
    const digest = await jsonDigest(snapshot);
    additions.push({
      change_index: change.index,
      to_rule_id: newId,
      to_rule_digest: digest,
    });
    const requirement = {
      ...m.requirements[0].requirement,
      requirement_id: newId,
      origin: "manual" as const,
      target_part_ids: [],
    };
    requirements.push({
      ...m.requirements[0],
      rule_id: newId,
      rule_digest: digest,
      rule_snapshot: snapshot,
      requirement,
      requirement_digest: await jsonDigest(requirement),
      decision_id: correctionId(500 + change.index),
      decision_snapshot: {
        id: correctionId(500 + change.index),
        decision: "confirmed",
      },
      annotation: {
        kind: "human_check_plan_declaration",
        mapped: false,
        reason: null,
        basis_evidence_ids: [],
      },
    });
  }
  const common = omitCorrectionFixture(pm, [
    "changes",
    "counts",
    "limitations",
    "inventory_complete",
    "review_ready",
    "original_bytes_verified",
  ]);
  const correction: PackageRuleCorrectionAppliedView["correction"] = {
    digest: "",
    manifest: {
      ...common,
      version: "package-rule-correction/1",
      id: correctionId(102),
      preview_digest: preview.digest,
      actor_id: correctionScope.memberId,
      command_id: correctionId(103),
      created_at: "2026-10-21T12:30:00Z",
      result: {
        inventory_id: newInventory,
        rule_set_id: newSet,
        rule_set_digest: "6".repeat(64),
        rule_count: requirements.length,
        rules_digest: await jsonDigest(
          requirements.map((item) => item.rule_snapshot),
        ),
      },
      mappings,
      additions,
      decision_bindings: requirements
        .filter((item) => item.decision_id)
        .map((item) => ({
          rule_id: item.rule_id,
          decision_id: item.decision_id!,
          decision_digest: "7".repeat(64),
          mode:
            item.decision_snapshot?.decision === "rejected"
              ? "rejected"
              : "confirmed",
        })),
    },
  };
  correction.digest = await jsonDigest(correction.manifest);
  const next: PackageRequirementInventoryView = {
    digest: "",
    manifest: {
      version: "bid-package-requirements/3",
      id: newInventory,
      bid_id: m.bid_id,
      package_id: m.package_id,
      target_revision_id: m.target_revision_id,
      package_digest: m.package_digest,
      authority_revision_id: m.authority_revision_id,
      authority_digest: m.authority_digest,
      rule_set_id: newSet,
      rule_set_digest: correction.manifest.result.rule_set_digest,
      revision: m.revision + 1,
      predecessor_digest: inventory.digest,
      identity_digest: m.identity_digest,
      source_snapshot: m.source_snapshot,
      requirements,
      inventory_complete: false,
      review_ready: false,
      actor_id: correctionScope.memberId,
      extraction_binding: "frozen_extraction_plus_human_derivation",
      extraction_basis: pm.extraction_basis,
      human_derivation: {
        version: "package-rule-derivation/1",
        head_id: correction.manifest.id,
        head_digest: correction.digest,
        length: pm.sequence_no,
      },
    },
  };
  next.digest = await jsonDigest(next.manifest);
  const operation = pending ?? {
    key: correctionId(700),
    etag: `"requirement-inventory:${correctionScope.revisionId}:${inventory.digest}"`,
    base: correctionBase(inventory),
    body: { request: pm.request, preview_digest: preview.digest },
  };
  const command = {
    command_id: correction.manifest.command_id,
    actor_id: correctionScope.memberId,
    idempotency_key: operation.key,
    request_digest: await jsonDigest({
      body: {
        scope: [
          correctionScope.bidId,
          correctionScope.packageId,
          correctionScope.revisionId,
          m.id,
        ],
        ...operation.body,
      },
      if_match: operation.etag,
    }),
    request: operation.body,
    if_match: operation.etag,
  };
  return { correction, inventory: next, command };
}
