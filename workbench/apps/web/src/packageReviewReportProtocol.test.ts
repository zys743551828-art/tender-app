import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewReportFixture } from "../qa-previews/frozen-inputs/packageReviewReport";
import {
  validatePackageReviewReport,
  validatePackageReviewReportContext,
  validatePackageReviewReportPage,
} from "./packageReviewReportProtocol";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => vi.unstubAllGlobals());
it.each(["docx", "pdf"] as const)(
  "accepts a bound %s report and reused original actor with independent report input identity",
  async (format) => {
    const f = await packageReviewReportFixture(format),
      report = { ...f.completed, actor_id: id(900) };
    expect(
      validatePackageReviewReportContext(f.context, f.f.completed),
    ).toEqual(f.context);
    expect(
      validatePackageReviewReport(report, f.f.completed, {
        key: id(901),
        body: f.body,
      }),
    ).toEqual(report);
    expect(report.report_input_digest).not.toBe(report.input_digest);
    expect(
      validatePackageReviewReportPage(f.page(), f.f.completed).items,
    ).toHaveLength(1);
  },
);
it.each([
  "wrong-run",
  "wrong-context",
  "wrong-format",
  "wrong-operation-input",
  "false-success",
  "wrong-media",
  "wrong-artifact",
  "qualification",
])("rejects substituted report metadata: %s", async (kind) => {
  const f = await packageReviewReportFixture(),
    value = structuredClone(f.completed);
  if (kind === "wrong-run") value.run_id = id(999);
  if (kind === "wrong-context") value.context_digest = "0".repeat(64);
  if (kind === "wrong-format") value.format = "pdf";
  if (kind === "wrong-operation-input")
    value.operation.input_digest = value.input_digest;
  if (kind === "false-success") value.result = null;
  if (kind === "wrong-media") value.result!.media_type = "application/pdf";
  if (kind === "wrong-artifact")
    Object.assign(value, { artifact_kind: "submission_body" });
  if (kind === "qualification")
    Object.assign(value, { submission_eligible: true });
  expect(() =>
    validatePackageReviewReport(value, f.f.completed, {
      key: id(901),
      body: f.body,
    }),
  ).toThrow();
});
it("rejects an unavailable PDF advertised as available and a foreign human/result context", async () => {
  const f = await packageReviewReportFixture();
  expect(() =>
    validatePackageReviewReportContext(
      { ...f.context, formats: ["docx", "pdf"] },
      f.f.completed,
    ),
  ).toThrow();
  expect(() =>
    validatePackageReviewReportContext(
      { ...f.context, result_digest: "0".repeat(64) },
      f.f.completed,
    ),
  ).toThrow();
  expect(() =>
    validatePackageReviewReportPage(
      f.page([f.completed, f.completed]),
      f.f.completed,
    ),
  ).toThrow();
});
