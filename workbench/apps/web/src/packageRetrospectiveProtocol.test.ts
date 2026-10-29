import { beforeEach, expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  retrospectiveFixture,
  retrospectiveScope,
  retrospectiveCandidateScope,
} from "./packageRetrospectiveFixtures.test-support";
import {
  retrospectiveBase,
  validateRetrospectivePreview,
  validateRetrospectiveAck,
  validateRetrospectiveDetail,
  validateRetrospectiveKnowledgeAck,
  validateRetrospectiveChoices,
  validRetrospectiveSelection,
} from "./packageRetrospectiveProtocol";

beforeEach(() => sessionStorage.clear());

it("accepts exact native PostgreSQL/ASGI snapshots, zero score, comparison and both explicit command receipts", async () => {
  const f = retrospectiveFixture();
  expect(
    await validateRetrospectivePreview(f.preview, f.bid_id, f.selection),
  ).toEqual(f.preview);
  expect(f.preview.manifest.outcome?.value).toBe("0");
  expect(f.preview.manifest.formal_sample_eligible).toBe(false);
  expect(
    await validateRetrospectiveDetail(
      f.detail,
      f.bid_id,
      f.saved.retrospective.manifest.id,
    ),
  ).toEqual(f.detail);
  sessionStorage.setItem(
    `tender:command-record:${retrospectiveScope(f)}`,
    JSON.stringify({
      path: retrospectiveBase(f.bid_id),
      body: f.request,
      key: f.save_key,
      etag: f.preview_etag,
    }),
  );
  expect(
    await validateRetrospectiveAck(
      { data: f.saved, etag: f.saved_etag },
      f.bid_id,
      f.member_id,
      retrospectiveScope(f),
    ),
  ).toEqual(f.saved);
  sessionStorage.setItem(
    `tender:command-record:${retrospectiveCandidateScope(f)}`,
    JSON.stringify({
      path: `${retrospectiveBase(f.bid_id)}/${f.saved.retrospective.manifest.id}/knowledge-candidate`,
      body: f.candidate_request,
      key: f.candidate_key,
      etag: f.saved_etag,
    }),
  );
  expect(
    await validateRetrospectiveKnowledgeAck(
      { data: f.candidate, etag: f.saved_etag },
      f.saved.retrospective,
      f.member_id,
      retrospectiveCandidateScope(f),
    ),
  ).toEqual(f.candidate);
});

it.each([
  "identity",
  "foreign_outcome",
  "counts",
  "transition",
  "privilege",
  "missing_side",
])(
  "rejects a rehashed %s interpretation of the selected native evidence",
  async (field) => {
    const f = retrospectiveFixture(),
      p = f.preview.manifest;
    if (field === "identity") p.submission.identity.digest = "d".repeat(64);
    if (field === "foreign_outcome")
      p.outcome!.submission_id = "00000000-0000-0000-0000-000000000099";
    if (field === "counts") p.comparison!.manifest.counts.verdict_changed++;
    if (field === "transition")
      p.comparison!.manifest.items[0].verdict_transition!.changed = true;
    if (field === "privilege")
      Object.assign(p, { risk_resolution_assessed: true });
    if (field === "missing_side") p.comparison!.manifest.items[0].left = null;
    if (p.comparison)
      p.comparison.digest = await jsonDigest(p.comparison.manifest);
    f.preview.digest = await jsonDigest(p);
    await expect(
      validateRetrospectivePreview(f.preview, f.bid_id, f.selection),
    ).rejects.toThrow();
  },
);

it("requires exact missing-material declarations or a distinct explicit review pair", () => {
  const f = retrospectiveFixture();
  expect(validRetrospectiveSelection(f.selection)).toBe(true);
  expect(
    validRetrospectiveSelection({ ...f.selection, outcome_id: null }),
  ).toBe(false);
  expect(
    validRetrospectiveSelection({
      ...f.selection,
      submitted_run_id: f.selection.baseline_run_id,
    }),
  ).toBe(false);
  expect(
    validRetrospectiveSelection({ ...f.selection, submitted_run_id: null }),
  ).toBe(false);
});

it("does not accept another actor, original command, scope or frozen request as the save acknowledgement", async () => {
  const f = retrospectiveFixture(),
    scope = retrospectiveScope(f);
  sessionStorage.setItem(
    `tender:command-record:${scope}`,
    JSON.stringify({
      path: retrospectiveBase(f.bid_id),
      body: f.request,
      key: f.save_key,
      etag: f.preview_etag,
    }),
  );
  for (const field of [
    "actor_id",
    "idempotency_key",
    "request_digest",
  ] as const) {
    const changed = structuredClone(f.saved);
    changed.command[field] = "00000000-0000-0000-0000-000000000099";
    await expect(
      validateRetrospectiveAck(
        { data: changed, etag: f.saved_etag },
        f.bid_id,
        f.member_id,
        scope,
      ),
    ).rejects.toThrow();
  }
  expect(
    sessionStorage.getItem(`tender:command-record:${scope}`),
  ).not.toBeNull();
});

it("rejects unrelated history/detail and choices before they can populate the current project", async () => {
  const f = retrospectiveFixture();
  expect(
    validateRetrospectiveChoices(
      f.choices.submissions,
      f.bid_id,
      "submissions",
      null,
    ),
  ).toEqual(f.choices.submissions);
  expect(() =>
    validateRetrospectiveChoices(
      f.choices.runs,
      f.bid_id,
      "runs",
      "00000000-0000-0000-0000-000000000099",
    ),
  ).toThrow();
  await expect(
    validateRetrospectiveDetail(
      f.detail,
      f.bid_id,
      "00000000-0000-0000-0000-000000000099",
    ),
  ).rejects.toThrow();
});
