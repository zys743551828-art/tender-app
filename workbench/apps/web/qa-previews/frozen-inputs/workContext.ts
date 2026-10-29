// Explicit synthetic UI fixtures; no actual business qualification or model effect.
import type { PackageWorkContext } from "../../src/contracts";
import { jsonDigest } from "../../src/editorSchema";
import { workContextDimensions } from "../../src/workContextProtocol";
import type { WorkContextRunSelection } from "../../src/workContextProtocol";
import type { WorkContextTarget } from "../../src/workContextNavigation";
import { packageReviewFixture } from "./packageReview";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
export async function sealContext(value: PackageWorkContext) {
  value.selection_digest = await jsonDigest(value.selection);
  const basis: Record<string, unknown> = { ...value };
  delete basis.observed_at;
  delete basis.observation_digest;
  value.observation_digest = await jsonDigest(basis);
  return value;
}
export async function workContextFixture() {
  const f = await packageReviewFixture(),
    run = f.completed;
  const selection: WorkContextRunSelection = {
    kind: "package_review_run",
    ...run.scope,
    package_digest: f.inventory.manifest.package_digest,
    inventory_digest: f.inventory.digest,
    frozen_input_id: run.frozen_input_id,
    frozen_input_digest: run.frozen_input_digest,
    execution_input_id: run.execution_input_id,
    execution_input_digest: run.execution_input_digest,
    dependency_plan_id: run.dependency_plan_id,
    dependency_plan_digest: run.dependency_plan_digest,
    run_id: run.id,
    input_digest: run.input_digest,
    method_digest: run.method_digest,
    result_digest: run.result!.digest,
  };
  const observation = Object.fromEntries(
    workContextDimensions.map((key) => [
      key,
      {
        status:
          key === "review_run_head"
            ? "unknown"
            : key === "submission_head"
              ? "not_applicable"
              : "matched",
        selected_digest: null,
        observed_digest: null,
        reason:
          key === "review_run_head"
            ? "NO_CURRENT_REVIEW_RUN_HEAD"
            : "EXPLICIT_SYNTHETIC_OBSERVATION",
      },
    ]),
  ) as PackageWorkContext["current_observation"];
  const context: PackageWorkContext = await sealContext({
    version: "package-work-context/1",
    selection,
    selection_digest: "",
    observation_digest: "",
    observed_at: "2026-10-21T08:06:00.000001Z",
    identity: {
      bidder_id: id(801),
      bidder_name: "合成投标单位",
      round_id: id(802),
      engineering_project_id: id(803),
      engineering_title: "合成工程",
      region: null,
      engineering_type: null,
      lot: "合成标段",
      lot_id: id(804),
      round_no: 1,
      binding_status: "confirmed",
      authority_id: id(805),
      digest: "a".repeat(64),
      identity_version: "bid-identity/2",
    },
    state: {
      kind: "package_review_run",
      operation_id: run.operation.id,
      operation_state: "succeeded",
      result_available: true,
    },
    current_observation: observation,
    summary: {
      perspective: "declared_scope_history",
      review_status: "result_available",
      review: {
        run_id: run.id,
        input_digest: run.input_digest,
        result_digest: run.result!.digest,
        requirement_count: run.result!.manifest.requirement_count,
        machine_counts: run.result!.manifest.counts,
        human_counts: {
          unreviewed: run.result!.manifest.requirement_count,
          confirmed: 0,
          rejected: 0,
          needs_review: 0,
        },
        human_heads_digest: "b".repeat(64),
        human_basis: "current_heads_for_exact_result",
        matrix_coverage: run.result!.manifest.matrix_coverage,
        overall_coverage: "partial",
        inventory_complete: false,
        quality_status: "not_measured",
        risk_resolution_assessed: false,
      },
      whole_package_blocking_risk_count: null,
      whole_package_passed: null,
      formal_scoring: {
        status: "scope_not_selected",
        scope_id: null,
        numeric_prediction: null,
      },
      official_labels_read: false,
      primary_action: "open_selected_review",
      action_mode: "navigation_only",
    },
    native_targets: {
      package_revision: {
        kind: "package_revision",
        bid_id: run.scope.bid_id,
        package_id: run.scope.package_id,
        revision_id: run.scope.revision_id,
        package_digest: selection.package_digest,
      },
      authority_revision: null,
      package_review_run: {
        kind: "package_review_run",
        ...run.scope,
        frozen_input_id: run.frozen_input_id,
        execution_input_id: run.execution_input_id,
        run_id: run.id,
        input_digest: run.input_digest,
        result_digest: run.result!.digest,
      },
      package_submission: null,
    },
    original_bytes_reverified: false,
    limitations: [
      "DECLARED_SCOPE_ONLY",
      "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
      "WHOLE_PACKAGE_RISK_NOT_ASSESSED",
      "FORMAL_SCORING_SCOPE_NOT_SELECTED",
      "OFFICIAL_LABELS_NOT_READ",
      "ORIGINAL_BYTES_NOT_REVERIFIED",
      "READ_CONTEXT_IS_NOT_WRITE_AUTHORITY",
    ],
  });
  const target: WorkContextTarget = {
    kind: "package_review_run",
    id: run.id,
    selectionDigest: context.selection_digest,
  };
  return { ...f, context, target };
}
