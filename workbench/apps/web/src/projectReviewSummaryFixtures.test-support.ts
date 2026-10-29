import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import type { PackageNextActions } from "./contracts";

export function reviewSummaryActions(
  fixture: Awaited<ReturnType<typeof workContextFixture>>,
): PackageNextActions {
  const s = fixture.context.selection;
  if (s.kind !== "package_review_run")
    throw new Error("review fixture required");
  return {
    version: "package-next-actions/1",
    binding: {
      scope: {
        bid_id: s.bid_id,
        package_id: s.package_id,
        revision_id: s.revision_id,
        inventory_id: s.inventory_id,
      },
      run_id: s.run_id,
      input_digest: s.input_digest,
      result_digest: s.result_digest,
      frozen_input_id: s.frozen_input_id,
      frozen_input_digest: s.frozen_input_digest,
      execution_input_id: s.execution_input_id,
      execution_input_digest: s.execution_input_digest,
      dependency_plan_id: s.dependency_plan_id,
      dependency_plan_digest: s.dependency_plan_digest,
      method_digest: s.method_digest,
    },
    method_digest: "a".repeat(64),
    confirmation_digest: "b".repeat(64),
    basis_digest: "c".repeat(64),
    observation_digest: "d".repeat(64),
    observed_at: "2026-10-25T08:00:00Z",
    basis_status: "matched",
    basis_issues: [],
    current_scope_counts: {
      critical: 1,
      suggestions: 0,
      pending_critical_rules: 0,
    },
    historical_scope_counts: { critical: 1, suggestions: 0 },
    primary: {
      level: 3,
      key: "inspect_critical_risks",
      title: "核对所选范围的关键问题",
      requirement_ids: [
        fixture.completed.result!.manifest.matrix[1].requirement_id,
      ],
      item_count: 1,
    },
    other_actions: [],
    remaining_critical_count: 0,
    remaining_suggestion_count: 0,
    action_mode: "navigation_only",
    perspective: "selected_declared_scope",
    original_bytes_reverified: false,
    inventory_complete: false,
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
}
