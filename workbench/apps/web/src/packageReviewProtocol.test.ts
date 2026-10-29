import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PackageReviewRunView } from "./contracts";
import {
  packageReviewFixture,
  packageReviewPage,
} from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  validatePackageReviewPage,
  validatePackageReviewRun,
} from "./packageReviewProtocol";

let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  fixture = await packageReviewFixture();
});
afterEach(() => vi.unstubAllGlobals());
it("accepts the stable acknowledgement and verified result for the original prepared input and plan", async () => {
  const pending = { key: id(150), body: fixture.body };
  await expect(
    validatePackageReviewRun(fixture.run, fixture.props, pending),
  ).resolves.toEqual(fixture.run);
  await expect(
    validatePackageReviewRun(fixture.completed, fixture.props, fixture.run.id),
  ).resolves.toEqual(fixture.completed);
});
it("accepts reuse of an identical run first created by another member without confusing actor with input identity", async () => {
  const reused = { ...fixture.run, actor_id: id(999) };
  await expect(
    validatePackageReviewRun(reused, fixture.props, {
      key: id(150),
      body: fixture.body,
    }),
  ).resolves.toEqual(reused);
});
it.each([
  [
    "other prepared input",
    (run: PackageReviewRunView) => {
      run.execution_input_id = id(901);
    },
  ],
  [
    "other scope",
    (run: PackageReviewRunView) => {
      run.scope.revision_id = id(902);
    },
  ],
  [
    "other frozen digest",
    (run: PackageReviewRunView) => {
      run.frozen_input_digest = "1".repeat(64);
    },
  ],
  [
    "other plan",
    (run: PackageReviewRunView) => {
      run.dependency_plan_id = id(903);
    },
  ],
  [
    "other plan digest",
    (run: PackageReviewRunView) => {
      run.dependency_plan_digest = "2".repeat(64);
    },
  ],
  [
    "other operation input",
    (run: PackageReviewRunView) => {
      run.operation.input_digest = "3".repeat(64);
    },
  ],
  [
    "unsupported state",
    (run: PackageReviewRunView) => {
      Object.assign(run.operation, { state: "retry_wait" });
    },
  ],
] as const)(
  "rejects an acknowledgement with %s before clearing the original request",
  async (_name, mutate) => {
    const run = structuredClone(fixture.run);
    mutate(run);
    await expect(
      validatePackageReviewRun(run, fixture.props, {
        key: id(150),
        body: fixture.body,
      }),
    ).rejects.toThrow("未确认的原请求仍保留");
  },
);
it.each([
  [
    "promoted full coverage",
    (run: PackageReviewRunView) => {
      Object.assign(run.result!.manifest, { overall_coverage: "complete" });
    },
  ],
  [
    "promoted scoring",
    (run: PackageReviewRunView) => {
      Object.assign(run.result!.manifest, { formal_scoring_eligible: true });
    },
  ],
  [
    "incorrect verdict counts",
    (run: PackageReviewRunView) => {
      run.result!.manifest.counts.satisfied++;
    },
  ],
  [
    "lost inspected range",
    (run: PackageReviewRunView) => {
      run.result!.manifest.matrix[0].inspected_ranges = [];
    },
  ],
  [
    "other quoted parse",
    (run: PackageReviewRunView) => {
      run.result!.manifest.matrix[0].target_quotes[0].parse_run_id = id(909);
    },
  ],
  [
    "unbound page",
    (run: PackageReviewRunView) => {
      run.result!.manifest.matrix[0].target_quotes[0].physical_page = 11;
    },
  ],
  [
    "hidden unresolved row",
    (run: PackageReviewRunView) => {
      run.result!.manifest.matrix_coverage = "complete";
    },
  ],
  [
    "changed method",
    (run: PackageReviewRunView) => {
      run.result!.manifest.method_digest = "7".repeat(64);
    },
  ],
  [
    "duplicate requirement",
    (run: PackageReviewRunView) => {
      run.result!.manifest.matrix[1].requirement_id =
        run.result!.manifest.matrix[0].requirement_id;
    },
  ],
] as const)("rejects a recomputed result with %s", async (_name, mutate) => {
  const run = structuredClone(fixture.completed);
  mutate(run);
  run.result!.digest = await frozenManifestDigest(run.result!.manifest);
  await expect(
    validatePackageReviewRun(run, fixture.props, run.id),
  ).rejects.toThrow("结果边界不符");
});
it("rejects an authentic quote in another undeclared part of the same document", async () => {
  const run = structuredClone(fixture.completed),
    m = run.result!.manifest;
  m.submitted_documents[0].parts[0].last_page = 5;
  m.submitted_documents[0].parts.push({
    ...m.submitted_documents[0].parts[0],
    part_id: "financial-body",
    category: "financial",
    first_page: 6,
    last_page: 10,
  });
  m.matrix.forEach((row) => {
    row.inspected_ranges[0].last_page = 5;
  });
  Object.assign(m.matrix[0].target_quotes[0], {
    physical_page: 6,
    part_ids: ["financial-body"],
  });
  run.result!.digest = await frozenManifestDigest(m);
  await expect(
    validatePackageReviewRun(run, fixture.props, run.id),
  ).rejects.toThrow();
});
it("reads succeeded without a result as an unfinished retrieval, without inventing a report", async () => {
  const run = structuredClone(fixture.completed);
  run.result = null;
  await expect(
    validatePackageReviewRun(run, fixture.props, run.id),
  ).resolves.toEqual(run);
});
it("accepts a declared not-applicable requirement without a target range, retaining its authority basis", async () => {
  const run = structuredClone(fixture.completed),
    m = run.result!.manifest;
  Object.assign(m.matrix[0], {
    applicability: "not_applicable",
    target_part_ids: [],
    inspected_ranges: [],
    target_quotes: [],
    verdict: "not_applicable",
  });
  m.counts.satisfied = 0;
  m.counts.not_applicable = 1;
  run.result!.digest = await frozenManifestDigest(m);
  await expect(
    validatePackageReviewRun(run, fixture.props, run.id),
  ).resolves.toEqual(run);
});
it("rejects a satisfied claim for a requirement declared not applicable, even with valid original quotes", async () => {
  const run = structuredClone(fixture.completed);
  run.result!.manifest.matrix[0].applicability = "not_applicable";
  run.result!.digest = await frozenManifestDigest(run.result!.manifest);
  await expect(
    validatePackageReviewRun(run, fixture.props, run.id),
  ).rejects.toThrow();
});
it("validates the full page scope, unique runs and bounded cursor protocol", async () => {
  const page = packageReviewPage(fixture, [fixture.completed]);
  await expect(
    validatePackageReviewPage(page, fixture.props, 10),
  ).resolves.toEqual(page);
  await expect(
    validatePackageReviewPage(
      { ...page, items: [fixture.run, fixture.run] },
      fixture.props,
      10,
    ),
  ).rejects.toThrow();
  await expect(
    validatePackageReviewPage(
      { ...page, has_more: true, next_cursor: null },
      fixture.props,
      10,
    ),
  ).rejects.toThrow();
  await expect(
    validatePackageReviewPage(
      { ...page, execution_input_digest: "9".repeat(64) },
      fixture.props,
      10,
    ),
  ).rejects.toThrow();
});
