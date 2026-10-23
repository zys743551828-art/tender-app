// Synthetic protocol counterexamples. Native HTTP responses are tested separately.
import { beforeEach, expect, it, vi } from "vitest";
import type {
  PackageHistoricalJob,
  PackageHistoricalJobView,
  PackageHistoricalProtocolTemplate,
  PackageHistoryAdmissionDirectory,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  historyEtag,
  validateHistoryDirectory,
  validateHistoryJob,
  validateHistoryReceipt,
  validateHistoryTemplate,
  type HistoryPending,
} from "./packageHistoricalResearchProtocol";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const sha = "a".repeat(64),
  at = "2026-10-22T00:00:00.123456+00:00";
const filters = {
  bid_id: null,
  scope_id: null,
  protocol_id: null,
  cohort_id: null,
};
const flags = {
  research_only: true,
  formal_eligibility: "unavailable",
} as const;

beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
});
const job = (): PackageHistoricalJob => ({
  job_id: id(1),
  cohort_id: id(2),
  kind: "train",
  state: "queued",
  generation: 1,
  ...flags,
});
const pending = (): Extract<HistoryPending, { kind: "job" }> => ({
  kind: "job",
  path: `/package-historical-research/cohorts/${id(2)}/jobs`,
  key: id(3),
  etag: `"package-history-cohort-view:${id(2)}:${sha}"`,
  body: { kind: "train", reason: "明确创建合成研究任务" },
  expected: { cohortId: id(2) },
});

it("keeps an original queued ACK distinct from a later paused current GET", async () => {
  const ack = job(),
    current: PackageHistoricalJobView = {
      ...ack,
      state: "paused",
      generation: 2,
      current: true,
      result: null,
      result_digest: null,
    };
  expect(
    await validateHistoryReceipt(
      ack,
      pending(),
      await historyEtag("job", ack.job_id, ack),
    ),
  ).toEqual(ack);
  expect(
    await validateHistoryJob(
      current,
      ack.job_id,
      await historyEtag("job-view", ack.job_id, current),
    ),
  ).toEqual(current);
  await expect(
    validateHistoryReceipt(
      current,
      pending(),
      await historyEtag("job-view", ack.job_id, current),
    ),
  ).rejects.toThrow();
  await expect(
    validateHistoryJob(
      ack,
      ack.job_id,
      await historyEtag("job", ack.job_id, ack),
    ),
  ).rejects.toThrow();
});

it.each([
  "kind",
  "cohort",
  "etag_kind",
  "etag_digest",
  "qualification",
  "extra",
  "generation",
])("rejects resealed wrong job ACK %s", async (mutation) => {
  const value = job();
  if (mutation === "kind") value.kind = "evaluate";
  if (mutation === "cohort") value.cohort_id = id(99);
  if (mutation === "qualification")
    Object.assign(value, { formal_eligibility: "eligible" });
  if (mutation === "extra") Object.assign(value, { current: true });
  if (mutation === "generation") value.generation = Number.MAX_SAFE_INTEGER + 1;
  const etag =
    mutation === "etag_kind"
      ? await historyEtag("job-view", value.job_id, value)
      : mutation === "etag_digest"
        ? `"package-history-job:${id(1)}:${sha}"`
        : await historyEtag("job", value.job_id, value);
  await expect(
    validateHistoryReceipt(value, pending(), etag),
  ).rejects.toThrow();
});

it.each(["pause", "resume", "cancel"] as const)(
  "validates exact %s control generation/state without confusing current status",
  async (action) => {
    const command: HistoryPending = {
      kind: "control",
      path: `/package-historical-research/jobs/${id(1)}/control`,
      key: id(4),
      etag: `"package-history-job-view:${id(1)}:${sha}"`,
      body: { action, generation: 1, reason: "明确控制合成任务" },
      expected: { cohortId: id(2), jobKind: "train" },
    };
    const value: PackageHistoricalJob = {
      ...job(),
      state: (
        { pause: "paused", resume: "queued", cancel: "cancelled" } as const
      )[action],
      generation: 2,
    };
    expect(
      await validateHistoryReceipt(
        value,
        command,
        await historyEtag("job", value.job_id, value),
      ),
    ).toEqual(value);
    const wrong = { ...value, generation: 1 };
    await expect(
      validateHistoryReceipt(
        wrong,
        command,
        await historyEtag("job", wrong.job_id, wrong),
      ),
    ).rejects.toThrow();
  },
);

function directory(): PackageHistoryAdmissionDirectory {
  return {
    version: "package-history-directory/1",
    kind: "admissions",
    filters,
    status: "observed",
    schema_configured: true,
    items: [],
    total: 0,
    observation_digest: sha,
    observed_at: at,
    complete_observation: true,
    has_more: false,
    next_cursor: null,
    currentness_rechecked: false,
    qualification_granted: false,
    ...flags,
  };
}
it("distinguishes an observed empty directory from unavailable/unknown counts", async () => {
  const empty = directory();
  expect(await validateHistoryDirectory("admissions", empty, filters)).toEqual(
    empty,
  );
  const unavailable = {
    ...empty,
    status: "unavailable",
    schema_configured: false,
    total: null,
    observation_digest: null,
    complete_observation: false,
    has_more: null,
  };
  expect(
    await validateHistoryDirectory("admissions", unavailable, filters),
  ).toEqual(unavailable);
  await expect(
    validateHistoryDirectory(
      "admissions",
      { ...unavailable, total: 0 },
      filters,
    ),
  ).rejects.toThrow();
});
it.each([
  "kind",
  "filter",
  "qualification",
  "currentness",
  "cursor",
  "empty_more",
  "extra",
])("rejects directory identity or authority drift %s", async (mutation) => {
  const value = structuredClone(directory());
  if (mutation === "kind") Object.assign(value, { kind: "protocols" });
  if (mutation === "filter") value.filters.bid_id = id(99);
  if (mutation === "qualification")
    Object.assign(value, { qualification_granted: true });
  if (mutation === "currentness")
    Object.assign(value, { currentness_rechecked: true });
  if (mutation === "cursor") value.next_cursor = "unexpected";
  if (mutation === "empty_more")
    Object.assign(value, {
      total: 2,
      has_more: true,
      next_cursor: "unexpected",
    });
  if (mutation === "extra") Object.assign(value, { formal_score: "100" });
  await expect(
    validateHistoryDirectory("admissions", value, filters),
  ).rejects.toThrow();
});

async function template(): Promise<PackageHistoricalProtocolTemplate> {
  const method = {
    version: "package-history-project-baselines/1",
    purpose: "retrospective_research",
    features: "not_required_by_constant_baselines",
    provider_requests: 0,
    sources: Object.fromEntries(
      [
        "packages/model_governance/package_history_cpu.py",
        "packages/model_governance/common.py",
        "packages/model_governance/evaluation.py",
        "packages/model_governance/statistics.py",
      ].map((p) => [p, sha]),
    ),
  };
  const methodDigest = await jsonDigest(method);
  return {
    ...flags,
    schema_configured: true,
    document: {
      schema: "package-history-cpu-protocol/1",
      method: {
        ...method,
        digest: methodDigest,
      } as PackageHistoricalProtocolTemplate["document"]["method"],
      families: ["mean", "median"],
      selection_metric: "project_mae",
      tie_order: ["mean", "median"],
      refit_with_development: false,
      interval_levels: [0.8, 0.9],
      group_spanning_policy: "exclude",
      seed: 17,
      bootstrap_iterations: 100,
    },
    method_digest: methodDigest,
    signed_proof_public_upload: false,
    feature_calibration_available: false,
  };
}
const zero = "00000000-0000-0000-0000-000000000000";
it("accepts the frozen feature-free protocol with a real content-bound ETag", async () => {
  const value = await template();
  expect(
    await validateHistoryTemplate(
      value,
      await historyEtag("protocol-template", zero, value),
    ),
  ).toEqual(value);
});
it.each([
  "method",
  "families",
  "levels",
  "bootstrap",
  "qualification",
  "refit",
  "digest",
])(
  "rejects an incompatible protocol %s even with a freshly computed ETag",
  async (mutation) => {
    const value = await template();
    if (mutation === "method")
      value.document.method.sources["packages/model_governance/common.py"] =
        "b".repeat(64);
    if (mutation === "families")
      Object.assign(value.document, { families: ["mean", "linear"] });
    if (mutation === "levels")
      Object.assign(value.document, { interval_levels: [0.95] });
    if (mutation === "bootstrap") value.document.bootstrap_iterations = 99;
    if (mutation === "qualification")
      Object.assign(value, { feature_calibration_available: true });
    if (mutation === "refit")
      Object.assign(value.document, { refit_with_development: true });
    if (mutation === "digest") value.method_digest = "b".repeat(64);
    await expect(
      validateHistoryTemplate(
        value,
        await historyEtag("protocol-template", zero, value),
      ),
    ).rejects.toThrow();
  },
);
