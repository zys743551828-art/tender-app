// Synthetic feature sidecar verifies the closed UI contract, not real accuracy.
import { act, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { HistoryJobResult } from "./PackageHistoricalResearchDetails";
import { HistoryJobsWorkspace } from "./PackageHistoricalResearchJobs";
import type {
  PackageHistoricalJobView,
  PackageHistoricalCohortView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  historyEtag,
  validateHistoryJob,
} from "./packageHistoricalResearchProtocol";
import captured from "./test-fixtures/package-history-ui-complete-http.json";

function fixture() {
  const value = structuredClone(
    captured.responses.find((r) => r.name === "evaluate_succeeded")!.body,
  ) as PackageHistoricalJobView;
  if (value.result?.schema !== "package-history-independent-evaluation/1")
    throw new Error();
  const result = value.result;
  result.feature_final_evaluation = {
    version: "package-history-feature-evaluation/1",
    cohort_id: result.cohort_id,
    origin: result.origin,
    membership_digest: result.membership_digest,
    method_digest: "1".repeat(64),
    freeze_method_digest: "2".repeat(64),
    candidate_digest: "3".repeat(64),
    model_digest: "4".repeat(64),
    predictions_digest: "5".repeat(64),
    labels_digest: result.labels_digest,
    input_digest: "6".repeat(64),
    exposure_id: value.job_id,
    report: structuredClone(result.report),
    research_only: true,
    formal_prediction: null,
    acceptance_decision: "unavailable",
    provider_requests: 0,
    paid_calls: 0,
  };
  return value;
}
async function seal(value: PackageHistoricalJobView) {
  value.result_digest = await jsonDigest(value.result);
  return historyEtag("job-view", value.job_id, value);
}
it("renders feature metrics separately without claiming formal accuracy", async () => {
  const value = fixture();
  const checked = await validateHistoryJob(
    value,
    value.job_id,
    await seal(value),
  );
  render(<HistoryJobResult value={checked} />);
  expect(
    screen.getByRole("region", { name: "冻结特征候选独立评价" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "特征候选最终评估记录" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/研究机制结果不代表真实精度通过/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "全部最终评估记录" }),
  ).toBeInTheDocument();
});
it.each([
  "cohort",
  "labels",
  "membership",
  "origin",
  "denominator",
  "exclusions",
  "version",
  "formal",
  "unknown",
])("rejects inconsistent feature result: %s", async (change) => {
  const value = fixture();
  if (value.result?.schema !== "package-history-independent-evaluation/1")
    throw new Error();
  const feature = value.result.feature_final_evaluation!;
  if (change === "cohort") feature.cohort_id = value.job_id;
  if (change === "labels") feature.labels_digest = "f".repeat(64);
  if (change === "membership") feature.membership_digest = "f".repeat(64);
  if (change === "origin") feature.origin = "external_evidence";
  if (change === "denominator") feature.report.denominator++;
  if (change === "exclusions") {
    feature.report.counts.rejected--;
    feature.report.counts.failed++;
  }
  if (change === "version") Object.assign(feature, { version: "future/2" });
  if (change === "formal") Object.assign(feature, { formal_prediction: "88" });
  if (change === "unknown") Object.assign(feature, { exposed: true });
  await expect(
    validateHistoryJob(value, value.job_id, await seal(value)),
  ).rejects.toThrow();
});
it("discards a late feature result when selection changes", async () => {
  const value = fixture(),
    tag = await seal(value);
  const current = captured.responses.find((r) => r.name === "cohort_current")!;
  const cohort = current.body as PackageHistoricalCohortView;
  let finish!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/cohorts/${cohort.cohort.id}`))
        return new Response(JSON.stringify(current.body), {
          headers: { "Content-Type": "application/json", ETag: current.etag! },
        });
      if (url.includes(`/jobs/${value.job_id}`))
        return new Promise<Response>((resolve) => {
          finish = resolve;
        });
      throw new Error(`Unexpected read ${url}`);
    }),
  );
  const props = {
    commands: { blocked: false, busy: false, send: async () => null },
    cohortId: cohort.cohort.id,
    cohortDigest: cohort.cohort.digest,
    jobId: value.job_id,
    jobKind: "evaluate" as const,
    revision: 0,
    onSelectCohort: vi.fn(),
    onSelectJob: vi.fn(),
  };
  const view = render(<HistoryJobsWorkspace {...props} />);
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  view.rerender(
    <HistoryJobsWorkspace {...props} jobId={null} jobKind={null} />,
  );
  await act(async () => {
    finish(
      new Response(JSON.stringify(value), {
        headers: { "Content-Type": "application/json", ETag: tag },
      }),
    );
  });
  expect(
    screen.queryByRole("region", { name: "冻结特征候选独立评价" }),
  ).not.toBeInTheDocument();
});
