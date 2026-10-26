// These are the unchanged responses captured through the actual public API with
// PG17 and the separate non-owner CPU runner. All business material is synthetic.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import type {
  PackageHistoricalAdmission,
  PackageHistoricalAdmissionContext,
  PackageHistoricalAdmissionView,
  PackageHistoricalCohort,
  PackageHistoricalCohortView,
  PackageHistoricalJob,
  PackageHistoricalJobView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  historyEtag,
  definitiveHistoryFailure,
  validateHistoryAdmission,
  validateHistoryAdmissionContext,
  validateHistoryCohort,
  validateHistoryDirectory,
  validateHistoryJob,
  validateHistoryPending,
  validateHistoryReceipt,
  validateHistoryTemplate,
  type HistoryDirectoryFilters,
  type HistoryDirectoryKind,
} from "./packageHistoricalResearchProtocol";
import captured from "./test-fixtures/package-history-ui-complete-http.json";
import directoryChange from "./test-fixtures/package-history-ui-directory-change-http.json";
import methodRecovery from "./test-fixtures/package-history-ui-method-recovery-http.json";
import unavailable from "./test-fixtures/package-history-ui-unavailable-http.json";
import roleBoundaries from "./test-fixtures/package-history-ui-role-boundaries-http.json";

type Response = {
  name: string;
  method: string;
  path: string;
  query: Record<string, unknown>;
  request_body: unknown;
  request_headers: Partial<Record<string, string>>;
  status: number;
  etag: string | null;
  body: unknown;
};
const responses: Response[] = captured.responses;
function entry(name: string) {
  const found = responses.find((r) => r.name === name);
  if (!found) throw new Error(`Missing actual HTTP capture: ${name}`);
  return found;
}
function body<T>(name: string): T {
  return structuredClone(entry(name).body) as T;
}
function nativeError(response: Response) {
  const value = response.body as {
    message: string;
    code: string;
    request_id?: string;
    retryable: boolean;
    details?: unknown;
  };
  return new ApiError(
    value.message,
    response.status,
    value.code,
    value.request_id,
    value.retryable,
    value.details,
  );
}
const cohort = body<PackageHistoricalCohort>("cohort_created");
function pathId(path: string, segment: string) {
  const parts = path.split("/");
  const index = parts.indexOf(segment);
  if (index < 0 || !parts[index + 1]) throw new Error("Missing path identity");
  return parts[index + 1];
}
function expectedFilters(response: Response): HistoryDirectoryFilters {
  const filter = (key: string) => {
    const value = response.query[key];
    if (value === undefined || value === null) return null;
    if (typeof value !== "string") throw new Error("Unexpected query filter");
    return value;
  };
  return {
    bid_id: filter("bid_id"),
    scope_id: filter("scope_id"),
    protocol_id: filter("protocol_id"),
    cohort_id: response.path.endsWith("/jobs")
      ? pathId(response.path, "cohorts")
      : null,
  };
}
// Reconstruct the original client command from the captured request, retaining
// the original path/body/condition/key. Expected identities use the separately
// read, fixed native records; they are never taken from a mutated test response.
function pending(response: Response) {
  const value = {
    path: response.path.replace(/^\/api\/v1/, ""),
    body: structuredClone(response.request_body),
    key: response.request_headers["idempotency-key"],
    etag: response.request_headers["if-match"] ?? null,
  };
  if (response.path.endsWith("/historical-admissions")) {
    const original = response.body as PackageHistoricalAdmission;
    return validateHistoryPending({
      ...value,
      kind: "admission",
      expected: {
        bidId: pathId(response.path, "bids"),
        packageId: pathId(response.path, "packages"),
        revisionId: pathId(response.path, "revisions"),
        scopeId: pathId(response.path, "technical-scopes"),
        scopeDigest: original.scope_digest,
        submissionBindingDigest: original.submission_binding_digest,
        proofOrigin: original.origin,
      },
    });
  }
  if (response.path.endsWith("/protocols"))
    return validateHistoryPending({ ...value, kind: "protocol", expected: {} });
  if (response.path.endsWith("/cohorts"))
    return validateHistoryPending({
      ...value,
      kind: "cohort",
      expected: { protocolDigest: cohort.protocol_digest },
    });
  const original = response.body as PackageHistoricalJob;
  if (response.path.endsWith("/control"))
    return validateHistoryPending({
      ...value,
      kind: "control",
      expected: { cohortId: cohort.id, jobKind: original.kind },
    });
  return validateHistoryPending({
    ...value,
    kind: "job",
    expected: { cohortId: pathId(response.path, "cohorts") },
  });
}
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
});

it("keeps actual infrastructure verification separate from real business qualification", () => {
  expect(captured.synthetic).toBe(true);
  expect(captured.real_qualification).toBe(false);
  expect(captured.paid_calls).toBe(0);
  expect(captured.provider_requests).toBe(0);
});

describe("unchanged native responses", () => {
  it.each(
    responses.filter(
      (r) =>
        r.status === 200 && r.path.endsWith("/historical-admission-context"),
    ),
  )(
    "validates context $name with its original tag and selected identities",
    async (r) => {
      const value = await validateHistoryAdmissionContext(
        r.body,
        {
          scopeId: pathId(r.path, "technical-scopes"),
          submissionId: String(r.query.submission_id),
          outcomeId: String(r.query.outcome_id),
        },
        r.etag,
      );
      expect(value).toEqual(r.body);
    },
  );

  it.each(responses.filter((r) => r.status < 300 && r.method === "POST"))(
    "validates original command ACK $name",
    async (r) => {
      expect(await validateHistoryReceipt(r.body, pending(r), r.etag)).toEqual(
        r.body,
      );
    },
  );

  it("validates the CPU template and exact method fingerprint", async () => {
    const r = entry("protocol_template");
    expect(await validateHistoryTemplate(r.body, r.etag)).toEqual(r.body);
  });

  it.each(
    responses.filter(
      (r) =>
        r.method === "GET" &&
        /\/admissions\/[^/]+$/.test(r.path) &&
        r.status === 200,
    ),
  )(
    "accepts the native admission history view $name without re-granting eligibility",
    async (r) => {
      const original = r.body as PackageHistoricalAdmissionView;
      expect(
        await validateHistoryAdmission(r.body, original.admission.id, r.etag),
      ).toEqual(original);
    },
  );
  it.each(["cohort_current", "cohort_after_train", "cohort_stale"])(
    "accepts the full native cohort %s including transitive excluded closure",
    async (name) => {
      const r = entry(name);
      expect(
        await validateHistoryCohort(
          r.body,
          cohort.id,
          r.etag,
          cohort.protocol_digest,
        ),
      ).toEqual(r.body);
    },
  );
  it.each(
    responses.filter(
      (r) =>
        r.method === "GET" && /\/jobs\/[^/]+$/.test(r.path) && r.status === 200,
    ),
  )("validates native job $name and its cohort bindings", async (r) => {
    expect(
      await validateHistoryJob(r.body, pathId(r.path, "jobs"), r.etag, cohort),
    ).toEqual(r.body);
  });
  it.each([
    ["admissions_directory", "admissions"],
    ["protocols_directory", "protocols"],
    ["cohorts_directory", "cohorts"],
    ["jobs_directory", "jobs"],
    ["admissions_page_one", "admissions"],
    ["admissions_page_two", "admissions"],
  ] as const)(
    "validates metadata directory %s",
    async (name, kind: HistoryDirectoryKind) => {
      const r = entry(name);
      expect(
        await validateHistoryDirectory(kind, r.body, expectedFilters(r)),
      ).toEqual(r.body);
    },
  );
});

describe("native unavailable and recovery boundaries", () => {
  it.each(unavailable.responses.filter((r) => r.status === 200))(
    "keeps directory $name unknown or empty exactly as observed",
    async (raw) => {
      const r: Response = raw;
      const kind = r.path.split("/").at(-1) as HistoryDirectoryKind;
      const result = await validateHistoryDirectory(
        kind,
        r.body,
        expectedFilters(r),
      );
      expect(result).toEqual(r.body);
      if (result.status === "unavailable") {
        expect(result.total).toBeNull();
        expect(result.has_more).toBeNull();
        expect(result.observation_digest).toBeNull();
      } else {
        expect(result.total).toBe(0);
        expect(result.has_more).toBe(false);
      }
    },
  );
  it.each(
    directoryChange.responses.filter(
      (r) => r.method === "GET" && r.name !== "protocol_template",
    ),
  )("verifies original directory response $name", async (raw) => {
    const r: Response = raw;
    const kind = r.path.split("/").at(-1) as HistoryDirectoryKind;
    if (r.status >= 400)
      await expect(
        validateHistoryDirectory(kind, r.body, expectedFilters(r)),
      ).rejects.toThrow();
    else
      expect(
        await validateHistoryDirectory(kind, r.body, expectedFilters(r)),
      ).toEqual(r.body);
  });
  it("restores the exact protocol ACK after the installed method changes while rejecting a new-key response", async () => {
    const original = methodRecovery.responses.find(
      (r) => r.name === "protocol_created",
    );
    const replay = methodRecovery.responses.find(
      (r) => r.name === "protocol_original_replayed",
    );
    const denied = methodRecovery.responses.find(
      (r) => r.name === "protocol_new_key_rejected",
    );
    if (!original || !replay || !denied)
      throw new Error("Incomplete native method recovery capture");
    expect(replay.body).toEqual(original.body);
    expect(replay.request_body).toEqual(original.request_body);
    expect(replay.request_headers).toEqual(original.request_headers);
    expect(
      await validateHistoryReceipt(replay.body, pending(original), replay.etag),
    ).toEqual(original.body);
    await expect(
      validateHistoryReceipt(denied.body, pending(original), denied.etag),
    ).rejects.toThrow();
    expect(definitiveHistoryFailure(nativeError(denied))).toBe(true);
  });
  it("retains a command after the ordinary API denies synthetic role access; that denial is not an ACK", async () => {
    const original = roleBoundaries.responses.find(
      (r) => r.name === "admission_created",
    );
    const denied = roleBoundaries.responses.find(
      (r) => r.name === "ordinary_api_synthetic_rejected",
    );
    if (!original || !denied)
      throw new Error("Incomplete native role boundary capture");
    expect(
      await validateHistoryReceipt(
        original.body,
        pending(original),
        original.etag,
      ),
    ).toEqual(original.body);
    await expect(
      validateHistoryReceipt(denied.body, pending(original), denied.etag),
    ).rejects.toThrow();
    expect(definitiveHistoryFailure(nativeError(denied))).toBe(false);
  });
});

it("preserves the original admission and pause ACKs when later observations change", async () => {
  const ack = entry("admission_created"),
    replay = entry("admission_replayed_after_revocation");
  expect(replay.body).toEqual(ack.body);
  expect(replay.etag).toBe(ack.etag);
  expect(
    await validateHistoryReceipt(replay.body, pending(ack), replay.etag),
  ).toEqual(ack.body);
  const stale = entry("admission_stale"),
    view = stale.body as PackageHistoricalAdmissionView;
  expect(
    (await validateHistoryAdmission(stale.body, view.admission.id, stale.etag))
      .current,
  ).toBe(false);
  expect(view.admission).toEqual(ack.body);
  const pause = entry("pause_ack"),
    pauseReplay = entry("pause_replayed"),
    current = entry("train_succeeded");
  expect(
    await validateHistoryReceipt(
      pauseReplay.body,
      pending(pause),
      pauseReplay.etag,
    ),
  ).toEqual(pause.body);
  await expect(
    validateHistoryReceipt(current.body, pending(pause), current.etag),
  ).rejects.toThrow();
  await expect(
    validateHistoryJob(
      pause.body,
      pathId(pause.path, "jobs"),
      pause.etag,
      cohort,
    ),
  ).rejects.toThrow();
});

it.each([
  "historical_as_of",
  "scope_frozen_at",
  "label_known_at",
  "official_technical_value",
  "official_maximum",
] as const)(
  "rejects a resealed proved admission context with missing %s",
  async (field) => {
    const value = body<PackageHistoricalAdmissionContext>("admission_context");
    expect(value.context_digest).not.toBeNull();
    expect(value.proofs.length).toBeGreaterThan(0);
    value[field] = null;
    await expect(
      validateHistoryAdmissionContext(
        value,
        {
          scopeId: value.scope_id,
          submissionId: value.submission_id,
          outcomeId: value.outcome_id,
        },
        await historyEtag("context", value.scope_id, value),
      ),
    ).rejects.toThrow();
  },
);

it("accepts complete native synthetic proof with the external-adapter advisory still visible", async () => {
  const r = entry("admission_context"),
    original = r.body as PackageHistoricalAdmissionContext;
  const value = await validateHistoryAdmissionContext(
    original,
    {
      scopeId: original.scope_id,
      submissionId: original.submission_id,
      outcomeId: original.outcome_id,
    },
    r.etag,
  );
  expect(value.proofs.some((p) => p.origin === "synthetic")).toBe(true);
  expect(
    value.blockers.some(
      (b) => b.code === "PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED",
    ),
  ).toBe(true);
  expect(value.official_technical_value).toBe("0");
  expect(value).toEqual(original);
});

it("preserves zero baseline gain, null intervals and all independent evaluation denominators", async () => {
  const r = entry("evaluate_succeeded");
  const result = (
    await validateHistoryJob(r.body, pathId(r.path, "jobs"), r.etag, cohort)
  ).result;
  if (result?.schema !== "package-history-independent-evaluation/1")
    throw new Error("Missing native evaluation");
  expect(result.selection_denominator).toEqual({
    selected_submissions: 6,
    excluded_submissions: 2,
    final_side_candidates: 3,
  });
  expect(result.report.counts).toEqual({
    succeeded: 1,
    failed: 0,
    rejected: 1,
    unlabeled: 1,
  });
  expect(result.report.denominator).toBe(3);
  expect(result.report.success_coverage).toBe("0.3333333333333333");
  expect(result.report.paired_baselines.mean?.gain).toBe("0.0");
  expect(result.report.paired_baselines.median?.gain).toBe("0.0");
  expect(result.report.project_within_three).toBe("0.0");
  expect(result.report.intervals["0.8"].coverage).toBeNull();
  expect(result.report.intervals["0.8"].width).toBeNull();
  expect(result.report.group_bootstrap_project_mae_95).toBeNull();
  expect(result.report.project_mae).toBe("10.0");
  expect(result.report.original_scale_project_mae).toBe("2.0");
  expect(result.official_source_subset.origin).toBe("synthetic");
  expect(result.acceptance_decision).toBe("unavailable");
});

it("preserves real zero in the synthetic admission and unavailable calibration in training", async () => {
  const admission = entry("admission_created");
  const value = await validateHistoryReceipt(
    admission.body,
    pending(admission),
    admission.etag,
  );
  expect((value as PackageHistoricalAdmission).official_technical_value).toBe(
    "0",
  );
  const r = entry("train_succeeded");
  const result = (
    await validateHistoryJob(r.body, pathId(r.path, "jobs"), r.etag, cohort)
  ).result;
  if (result?.schema !== "package-history-training-result/1")
    throw new Error("Missing native training");
  expect(result.model.family).toBe("mean");
  expect(result.model.constant).toBe("20.0");
  expect(result.baselines).toEqual({ mean: "20.0", median: "20.0" });
  expect(result.intervals["0.9"].groups).toBe(0);
  expect(result.intervals["0.9"].radius).toBeNull();
});

it.each(["binding", "proof_origin", "future_label", "qualification"])(
  "rejects a resealed native admission with corrupted %s",
  async (mutation) => {
    const original = entry("admission_created"),
      value = body<PackageHistoricalAdmission>(original.name);
    if (mutation === "binding")
      value.submission_binding_digest = "0".repeat(64);
    if (mutation === "proof_origin") {
      value.origin = "external_evidence";
      value.state = "retrospective_candidate";
    }
    if (mutation === "future_label")
      value.historical_as_of = "2999-01-01T00:00:00Z";
    if (mutation === "qualification")
      Object.assign(value, { formal_sample_created: true });
    value.digest = await jsonDigest(
      Object.fromEntries(Object.entries(value).filter(([k]) => k !== "digest")),
    );
    await expect(
      validateHistoryReceipt(
        value,
        pending(original),
        await historyEtag("admission", value.id, value),
      ),
    ).rejects.toThrow();
  },
);

it.each([
  "selected_denominator",
  "report_denominator",
  "silently_dropped_unlabeled",
  "zero_to_null",
  "wrong_cohort",
  "wrong_membership",
  "wrong_protocol",
  "fake_origin",
  "paid_call",
  "qualification",
  "false_coverage",
  "cohort_timing",
])(
  "rejects a resealed native evaluation with corrupted %s",
  async (mutation) => {
    const value = body<PackageHistoricalJobView>("evaluate_succeeded"),
      result = value.result;
    if (result?.schema !== "package-history-independent-evaluation/1")
      throw new Error();
    if (mutation === "selected_denominator")
      result.selection_denominator.selected_submissions = 5;
    if (mutation === "report_denominator") result.report.denominator = 2;
    if (mutation === "silently_dropped_unlabeled")
      result.report.counts.unlabeled = 0;
    if (mutation === "zero_to_null") {
      const mean = result.report.paired_baselines.mean;
      if (!mean) throw new Error("Missing native paired mean baseline");
      Object.assign(mean, { gain: null });
    }
    if (mutation === "wrong_cohort")
      result.cohort_id = "00000000-0000-4000-8000-000000000099";
    if (mutation === "wrong_membership")
      result.membership_digest = "0".repeat(64);
    if (mutation === "wrong_protocol") result.protocol_digest = "0".repeat(64);
    if (mutation === "fake_origin") {
      result.origin = "external_evidence";
      result.official_source_subset.origin = "external_evidence";
    }
    if (mutation === "paid_call") Object.assign(result, { paid_calls: 1 });
    if (mutation === "qualification")
      Object.assign(result, { acceptance_decision: "accepted" });
    if (mutation === "false_coverage") result.report.success_coverage = "1.0";
    if (mutation === "cohort_timing")
      result.timing.submission_split_at = "2020-01-01T00:00:00Z";
    value.result_digest = await jsonDigest(result);
    await expect(
      validateHistoryJob(
        value,
        value.job_id,
        await historyEtag("job-view", value.job_id, value),
        cohort,
      ),
    ).rejects.toThrow();
  },
);

it.each(["family", "model_export", "loss_selection", "false_interval"])(
  "rejects a resealed native training result with corrupted %s",
  async (mutation) => {
    const value = body<PackageHistoricalJobView>("train_succeeded"),
      result = value.result;
    if (result?.schema !== "package-history-training-result/1")
      throw new Error();
    if (mutation === "family") result.model.family = "median";
    if (mutation === "model_export")
      result.model.training_export_digest = "0".repeat(64);
    if (mutation === "loss_selection")
      result.selection.development_project_mae.median = "0.0";
    if (mutation === "false_interval")
      Object.assign(result.intervals["0.8"], {
        radius: "0.0",
        unavailable_reason: null,
      });
    result.model_digest = await jsonDigest(result.model);
    value.result_digest = await jsonDigest(result);
    await expect(
      validateHistoryJob(
        value,
        value.job_id,
        await historyEtag("job-view", value.job_id, value),
        cohort,
      ),
    ).rejects.toThrow();
  },
);

it("rejects a resealed cohort that removes the declared group root from a transitive member closure", async () => {
  const value = body<PackageHistoricalCohortView>("cohort_current");
  const member = value.cohort.members.find(
    (m) => m.exclusion_reason === "group_spans_submission_split",
  );
  if (!member || member.closure_ids.length < 2)
    throw new Error("Missing native bridge case");
  // The lexicographic group root can be either the selected admission or the
  // unselected bridge. Check the declared root without assuming random UUID order.
  member.closure_ids = member.closure_ids.filter(
    (id) => id !== member.group_id,
  );
  value.cohort.membership_digest = await jsonDigest(value.cohort.members);
  value.cohort.digest = await jsonDigest(
    Object.fromEntries(
      Object.entries(value.cohort).filter(([k]) => k !== "digest"),
    ),
  );
  await expect(
    validateHistoryCohort(
      value,
      cohort.id,
      await historyEtag("cohort-view", cohort.id, value),
      cohort.protocol_digest,
    ),
  ).rejects.toThrow();
});

// Explicit synthetic extension; this is not a newly captured native PG result.
function completeConsumerResult() {
  const value = body<PackageHistoricalJobView>("train_succeeded");
  if (value.result?.schema !== "package-history-training-result/1")
    throw new Error();
  value.result.complete_material_consumer = {
    version: "package-history-complete-consumer/1",
    method_digest: "a".repeat(64),
    reference_digest: "b".repeat(64),
    bindings_digest: "c".repeat(64),
    receipts: cohort.members
      .filter((m) => ["fit", "development", "calibration"].includes(m.purpose))
      .map((m, i) => ({
        admission_id: m.admission_id,
        proof_id: m.proof_id,
        context_digest: "a".repeat(64),
        source_commit: "b".repeat(64),
        artifact_digest: "c".repeat(64),
        input_digest: String(i + 1).repeat(64),
        features_digest: "d".repeat(64),
      })),
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
  return value;
}

it.each(["valid", "duplicate", "missing", "proof", "qualification", "extra"])(
  "checks synthetic complete-material extension: %s",
  async (attack) => {
    const value = completeConsumerResult();
    if (value.result?.schema !== "package-history-training-result/1")
      throw new Error();
    const consumer = value.result.complete_material_consumer!;
    if (attack === "duplicate")
      consumer.receipts[1] = { ...consumer.receipts[0] };
    if (attack === "missing") consumer.receipts.pop();
    if (attack === "proof")
      consumer.receipts[0].proof_id = "00000000-0000-0000-0000-000000000123";
    if (attack === "qualification")
      Object.assign(consumer, { training_eligible: true });
    if (attack === "extra") Object.assign(consumer, { verified: true });
    value.result_digest = await jsonDigest(value.result);
    const check = validateHistoryJob(
      value,
      value.job_id,
      await historyEtag("job-view", value.job_id, value),
      cohort,
    );
    if (attack === "valid") expect((await check).result).toEqual(value.result);
    else await expect(check).rejects.toThrow();
  },
);
