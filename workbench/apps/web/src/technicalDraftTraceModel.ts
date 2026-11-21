import type {
  AuthoringSourceReference,
  AuthoringTreeView,
  BidPackageStoredView,
} from "./contracts";
import { executionId } from "./executionInputValidation";
import { sourceRefs, strings, treeOrder } from "./authoringStructureState";
import type { technicalOutline } from "./technicalBidOutlinePlan";

type Rule = ReturnType<typeof technicalOutline>["rows"][number];
type TraceOrigin = "body" | "plan" | "old_plan";
type TraceState =
  | "matched_reference"
  | "check_reference"
  | "old_plan"
  | "unlinked";
type TraceSection = {
  sectionId: string;
  sectionRevision: number;
  title: string;
  origins: TraceOrigin[];
  evidenceIds: string[];
};
export type TechnicalDraftTraceRow = {
  rule: Rule;
  state: TraceState;
  chapters: TraceSection[];
};
export type FrozenEvidenceScope = {
  documentVersionId: string;
  parseRunId: string;
}[];

export function frozenOutlineAuthority(
  view: BidPackageStoredView,
): FrozenEvidenceScope {
  const matches: FrozenEvidenceScope = [];
  const seen = new Set<string>();
  for (const member of view.manifest.members) {
    if (
      member.parse.status !== "frozen" ||
      !executionId(member.parse.parse_run_id) ||
      !executionId(member.document_version_id)
    )
      continue;
    const key = member.document_version_id + ":" + member.parse.parse_run_id;
    if (seen.has(key)) continue;
    seen.add(key);
    matches.push({
      documentVersionId: member.document_version_id,
      parseRunId: member.parse.parse_run_id,
    });
  }
  return matches;
}

/** Explicit stored identities only. A heading, text similarity or a plan status is not coverage. */
export function technicalDraftTrace(
  bidId: string,
  tree: AuthoringTreeView,
  rules: Rule[],
  authority: FrozenEvidenceScope,
): TechnicalDraftTraceRow[] {
  const documents = new Set(authority.map((row) => row.documentVersionId));
  const indexed = new Map(
    rules.map((rule) => [
      rule.ruleId,
      {
        rule,
        ids: new Set(rule.evidenceIds),
        chapters: new Map<string, TraceSection>(),
      },
    ]),
  );
  for (const { node } of treeOrder(tree.nodes)) {
    const plan = node.plan;
    const validPlan =
      plan &&
      plan.id === node.plan_version_id &&
      plan.bid_id === bidId &&
      plan.draft_id === tree.draft_id &&
      plan.section_id === node.section_id;
    function associate(
      origin: TraceOrigin,
      ruleIds: string[],
      refs: AuthoringSourceReference[],
    ) {
      for (const id of new Set(ruleIds)) {
        const entry = indexed.get(id);
        if (!entry) continue;
        const match = entry.chapters.get(node.section_id) ?? {
          sectionId: node.section_id,
          sectionRevision: node.section_revision,
          title: node.title,
          origins: [],
          evidenceIds: [],
        };
        match.origins.push(origin);
        if (origin !== "old_plan") {
          const scopeEvidence = refs
            .filter(
              (ref) =>
                Number.isSafeInteger(ref.source_revision) &&
                ref.source_revision > 0 &&
                executionId(ref.source_id) &&
                documents.has(ref.document_version_id) &&
                entry.ids.has(ref.evidence_id),
            )
            .map((ref) => ref.evidence_id);
          match.evidenceIds = [
            ...new Set([...match.evidenceIds, ...scopeEvidence]),
          ];
        }
        entry.chapters.set(node.section_id, match);
      }
    }
    associate("body", strings(node.rule_ids), sourceRefs(node.source_refs));
    if (validPlan && plan) {
      const current =
        node.plan_content_basis_state === "current" &&
        plan.base_section_revision === node.section_revision;
      associate(
        current ? "plan" : "old_plan",
        strings(plan.payload.rule_ids),
        current ? sourceRefs(plan.payload.source_refs) : [],
      );
    }
  }
  return Array.from(indexed.values(), ({ rule, chapters }) => {
    const matches = [...chapters.values()];
    const state = matches.some((chapter) => chapter.evidenceIds.length > 0)
      ? "matched_reference"
      : matches.some((chapter) =>
            chapter.origins.some((origin) => origin !== "old_plan"),
          )
        ? "check_reference"
        : matches.length
          ? "old_plan"
          : "unlinked";
    return { rule, state, chapters: matches };
  });
}
