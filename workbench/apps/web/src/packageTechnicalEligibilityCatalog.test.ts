import { expect, it } from "vitest";
import type { PackageTechnicalScopeView } from "./contracts";
import raw from "./test-fixtures/technical-eligibility-catalog-http.json";
import { technicalSubmissions } from "./packageTechnicalEligibilityCatalog";

const saved = raw.scope as unknown as PackageTechnicalScopeView;

it("validates the full real PG package binding and ignores compatible old single-body entries", async () => {
  const legacy = {
    id: "00000000-0000-0000-0000-000000000001",
    bid_id: raw.sampleContext.scope.bid_id,
    body_version_id: "00000000-0000-0000-0000-000000000002",
  };
  const result = await technicalSubmissions(
    { ...raw.submissions, items: [legacy, ...raw.submissions.items] },
    saved,
  );
  expect(result.items).toHaveLength(1);
  expect(result.items[0].id).toBe(raw.sampleRequest.submission_id);
  expect(result.nextCursor).toBeNull();
});

it("rejects incomplete paging, another bid and a corrupted package manifest", async () => {
  await expect(
    technicalSubmissions(
      { ...raw.submissions, has_more: true, next_cursor: null },
      saved,
    ),
  ).rejects.toThrow("目录");
  const foreign = structuredClone(raw.submissions);
  foreign.items[0].bid_id = "00000000-0000-0000-0000-000000000001";
  await expect(technicalSubmissions(foreign, saved)).rejects.toThrow("目录");
  const corrupt = structuredClone(raw.submissions);
  corrupt.items[0].package_binding.digest = "1".repeat(64);
  await expect(technicalSubmissions(corrupt, saved)).rejects.toThrow();
});
