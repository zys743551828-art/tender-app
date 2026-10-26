import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { HistoryJobResult } from "./PackageHistoricalResearchDetails";
import type { PackageHistoricalJobView } from "./contracts";
import captured from "./test-fixtures/package-history-ui-complete-http.json";

it("shows synthetic complete-material receipt without implying feature fitting", () => {
  const value = structuredClone(
    captured.responses.find((r) => r.name === "train_succeeded")!.body,
  ) as PackageHistoricalJobView;
  if (value.result?.schema !== "package-history-training-result/1")
    throw new Error();
  value.result.complete_material_consumer = {
    version: "package-history-complete-consumer/1",
    method_digest: "a".repeat(64),
    reference_digest: "b".repeat(64),
    bindings_digest: "c".repeat(64),
    receipts: [
      {
        admission_id: value.cohort_id,
        proof_id: value.cohort_id,
        context_digest: "a".repeat(64),
        source_commit: "b".repeat(64),
        artifact_digest: "c".repeat(64),
        input_digest: "d".repeat(64),
        features_digest: "e".repeat(64),
      },
    ],
    features_used_for_fit: false,
    formal_prediction: null,
    native_binding_verified: false,
    current_native_facts_rechecked: false,
    input_authority_granted: false,
    execution_authorized: false,
    training_eligible: false,
    metrics_eligible: false,
    formal_prediction_eligible: false,
  };
  render(<HistoryJobResult value={value} />);
  expect(
    screen.getByText(/材料特征未参与拟合，不具备正式评分资格/),
  ).toBeInTheDocument();
  expect(screen.getByText("材料引用摘要")).toBeInTheDocument();
  expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
});
