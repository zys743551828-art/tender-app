import type {
  PackageReviewHumanDecisionCurrent,
  PackageReviewHumanDecisionPage,
  PackageReviewHumanDecisionView,
  SavePackageReviewHumanDecision,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { changeId as id } from "./factChange";
import type { packageReviewFixture } from "./packageReview";
type Fixture = Awaited<ReturnType<typeof packageReviewFixture>>;
export async function packageReviewDecisionBody(
  f: Fixture,
  rowIndex = 0,
  head: PackageReviewHumanDecisionView | null = null,
  state: SavePackageReviewHumanDecision["state"] = "confirmed",
): Promise<SavePackageReviewHumanDecision> {
  const row = f.completed.result!.manifest.matrix[rowIndex];
  return {
    result_digest: f.completed.result!.digest,
    row_digest: await frozenManifestDigest(row),
    expected_head: head ? { id: head.manifest.id, digest: head.digest } : null,
    state,
    reason: "合成人工理由：已逐字核对原引用",
    selected_quotes: row.target_quotes.slice(0, 1),
  };
}
export async function packageReviewDecisionReply(
  f: Fixture,
  body: SavePackageReviewHumanDecision,
  rowIndex = 0,
  sequence = 1,
  actor = f.props.scope.memberId,
): Promise<PackageReviewHumanDecisionView> {
  const run = f.completed,
    row = run.result!.manifest.matrix[rowIndex];
  const manifest: PackageReviewHumanDecisionView["manifest"] = {
    version: "package-review-human-decision/1",
    id: id(7000 + rowIndex * 100 + sequence),
    actor_id: actor,
    created_at: `2026-10-21T08:${String(1 + Math.floor(sequence / 60)).padStart(2, "0")}:${String(sequence % 60).padStart(2, "0")}.000001Z`,
    sequence_no: sequence,
    scope: run.scope,
    frozen_input_id: run.frozen_input_id,
    execution_input_id: run.execution_input_id,
    run_id: run.id,
    requirement_id: row.requirement_id,
    input_digest: run.input_digest,
    result_digest: body.result_digest,
    row_digest: body.row_digest,
    previous_head: body.expected_head,
    state: body.state,
    reason: body.reason,
    selected_quotes: body.selected_quotes,
    inventory_complete: false,
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
export async function packageReviewDecisionCurrent(
  f: Fixture,
  heads: PackageReviewHumanDecisionView[] = [],
): Promise<PackageReviewHumanDecisionCurrent> {
  const run = f.completed,
    byId = new Map(heads.map((head) => [head.manifest.requirement_id, head]));
  return {
    scope: run.scope,
    frozen_input_id: run.frozen_input_id,
    execution_input_id: run.execution_input_id,
    run_id: run.id,
    result_digest: run.result!.digest,
    items: await Promise.all(
      run.result!.manifest.matrix.map(async (row) => {
        const head = byId.get(row.requirement_id),
          m = head?.manifest;
        return {
          requirement_id: row.requirement_id,
          row_digest: await frozenManifestDigest(row),
          current:
            head && m
              ? {
                  id: m.id,
                  digest: head.digest,
                  sequence_no: m.sequence_no,
                  actor_id: m.actor_id,
                  created_at: m.created_at,
                  state: m.state,
                  reason: m.reason,
                }
              : null,
        };
      }),
    ),
  };
}
export async function packageReviewDecisionPage(
  f: Fixture,
  items: PackageReviewHumanDecisionView[],
  rowIndex = 0,
): Promise<PackageReviewHumanDecisionPage> {
  const run = f.completed,
    row = run.result!.manifest.matrix[rowIndex];
  return {
    scope: run.scope,
    frozen_input_id: run.frozen_input_id,
    execution_input_id: run.execution_input_id,
    run_id: run.id,
    result_digest: run.result!.digest,
    requirement_id: row.requirement_id,
    row_digest: await frozenManifestDigest(row),
    items,
    has_more: false,
    next_cursor: null,
  };
}
