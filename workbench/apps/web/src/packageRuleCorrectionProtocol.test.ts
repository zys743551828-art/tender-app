import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  correctionBase,
  type PendingCorrection,
} from "./packageRuleCorrectionRecovery";
import {
  correctionInventoryMatches,
  sameCorrectionInstant,
  validateCorrectionApplied,
  validateCorrectionEvidenceDetail,
  validateCorrectionEvidencePage,
  validateCorrectionHistory,
  validateCorrectionPreview,
} from "./packageRuleCorrectionProtocol";
import {
  correctionApplied,
  correctionFixture,
  correctionId,
  correctionPreview,
  correctionRule,
  correctionScope,
} from "./packageRuleCorrectionFixtures.test-support";

it("matches PostgreSQL offset timestamps to UTC manifests without dropping microseconds", () => {
  expect(
    sameCorrectionInstant(
      "2026-10-21T02:47:39.300646Z",
      "2026-10-20T22:47:39.300646-04:00",
    ),
  ).toBe(true);
  expect(
    sameCorrectionInstant(
      "2026-10-21T02:47:39.300646Z",
      "2026-10-20T22:47:39.300647-04:00",
    ),
  ).toBe(false);
  expect(
    sameCorrectionInstant(
      "2026-10-21T02:47:39Z",
      "2026-10-21T10:47:39.000000+08:00",
    ),
  ).toBe(true);
  expect(
    sameCorrectionInstant("2026-10-21T02:47:39Z", "2026-10-21T02:47:39"),
  ).toBe(false);
});

it("verifies combined add/replace/withdraw with complete conditions, exceptions, decimal scoring and unchanged extraction coverage", async () => {
  const f = await correctionFixture(),
    [first, second] = f.inventory.manifest.requirements;
  f.request.changes = [
    { op: "add", rule: correctionRule() },
    {
      op: "replace",
      rule_id: first.rule_id,
      rule_digest: first.rule_digest,
      rule: {
        ...correctionRule(),
        kind: "scoring",
        maximum: "12.50",
        bands: [
          {
            label: "优良",
            description: "优良方案",
            points: "10.25",
            evidence_ids: [correctionId(40)],
          },
        ],
      },
    },
    {
      op: "withdraw",
      rule_id: second.rule_id,
      rule_digest: second.rule_digest,
      evidence_quotes: correctionRule().evidence_quotes,
    },
  ];
  const preview = await correctionPreview(f.inventory, f.request, f.evidence);
  expect(
    await validateCorrectionPreview(
      preview,
      correctionScope,
      f.inventory,
      f.request,
    ),
  ).toEqual(preview);
  const applied = await correctionApplied(f.inventory, preview);
  const etag = `"requirement-inventory:${correctionScope.revisionId}:${applied.inventory.digest}"`;
  expect(
    await validateCorrectionApplied(
      applied,
      correctionScope,
      { base: correctionBase(f.inventory) },
      etag,
    ),
  ).toEqual(applied);
  expect(applied.inventory.manifest.inventory_complete).toBe(false);
  expect(applied.inventory.manifest.review_ready).toBe(false);
  expect(preview.manifest.extraction_basis.extraction_coverage).toBe("partial");
});
it("requires the inventory-bound authority, frozen parse, physical page and file digest in evidence", async () => {
  const f = await correctionFixture(),
    base = correctionBase(f.inventory);
  expect(validateCorrectionEvidencePage(f.page, correctionScope, base)).toEqual(
    f.page,
  );
  expect(
    await validateCorrectionEvidenceDetail(
      f.evidence,
      correctionScope,
      base,
      f.page.items[0],
    ),
  ).toEqual(f.evidence);
  for (const patch of [
    { parse_run_id: correctionId(999) },
    { physical_page: 4 },
    { file_digest: "0".repeat(64) },
    { part_ids: ["其他分册"] },
    { text_content: "同一身份下被替换的伪原文" },
  ])
    await expect(
      validateCorrectionEvidenceDetail(
        { ...f.evidence, evidence: { ...f.evidence.evidence, ...patch } },
        correctionScope,
        base,
        f.page.items[0],
      ),
    ).rejects.toThrow();
  expect(() =>
    validateCorrectionEvidencePage(
      {
        ...f.page,
        authority: { ...f.page.authority, revision_id: correctionId(888) },
      },
      correctionScope,
      base,
    ),
  ).toThrow();
});
it("preserves a valid legacy rule's undeclared applicability scope when withdrawing it", async () => {
  const f = await correctionFixture();
  const old = f.inventory.manifest.requirements[0];
  old.rule_snapshot.applicability_scope = {};
  old.rule_digest = await jsonDigest(old.rule_snapshot);
  f.inventory.digest = await jsonDigest(f.inventory.manifest);
  f.request.base_inventory_digest = f.inventory.digest;
  f.request.changes = [
    {
      op: "withdraw",
      rule_id: old.rule_id,
      rule_digest: old.rule_digest,
      evidence_quotes: correctionRule().evidence_quotes,
    },
  ];
  const preview = await correctionPreview(f.inventory, f.request, f.evidence);
  const checked = await validateCorrectionPreview(
    preview,
    correctionScope,
    f.inventory,
    f.request,
  );
  expect(checked.manifest.changes[0].before?.applicability_scope).toEqual({});
  expect(checked.manifest.changes[0].after.applicability_scope).toEqual({});
  const applied = await correctionApplied(f.inventory, preview);
  await expect(
    validateCorrectionApplied(
      applied,
      correctionScope,
      { base: correctionBase(f.inventory) },
      `"requirement-inventory:${correctionScope.revisionId}:${applied.inventory.digest}"`,
    ),
  ).resolves.toEqual(applied);
});
it("rejects rehashed preview changes that omit an exception, change the request or claim complete root coverage", async () => {
  const f = await correctionFixture();
  for (const mutate of [
    (value: Awaited<ReturnType<typeof correctionPreview>>) => {
      value.manifest.changes[0].after.exceptions = [];
    },
    (value: Awaited<ReturnType<typeof correctionPreview>>) => {
      value.manifest.request = {
        ...value.manifest.request,
        reason: "另一操作",
      };
    },
    (value: Awaited<ReturnType<typeof correctionPreview>>) => {
      value.manifest.extraction_basis.extraction_coverage = "complete";
    },
    (value: Awaited<ReturnType<typeof correctionPreview>>) => {
      value.manifest.counts.added = 2;
    },
  ]) {
    const preview = await correctionPreview(
      f.inventory,
      structuredClone(f.request),
      f.evidence,
    );
    mutate(preview);
    preview.digest = await jsonDigest(preview.manifest);
    await expect(
      validateCorrectionPreview(
        preview,
        correctionScope,
        f.inventory,
        f.request,
      ),
    ).rejects.toThrow();
  }
});
it("validates original apply ACK actor/key/body/etag and recomputes the scoped command digest", async () => {
  const f = await correctionFixture(),
    preview = await correctionPreview(f.inventory, f.request, f.evidence);
  const pending: PendingCorrection = {
    key: correctionId(700),
    etag: f.etag,
    base: correctionBase(f.inventory),
    body: { request: f.request, preview_digest: preview.digest },
  };
  const applied = await correctionApplied(f.inventory, preview, pending),
    etag = `"requirement-inventory:${correctionScope.revisionId}:${applied.inventory.digest}"`;
  expect(
    await validateCorrectionApplied(
      applied,
      correctionScope,
      { base: pending.base, pending },
      etag,
    ),
  ).toEqual(applied);
  for (const patch of [
    { actor_id: correctionId(999) },
    { idempotency_key: correctionId(998) },
    { if_match: '"new-head"' },
    { request_digest: "f".repeat(64) },
    { request: { ...pending.body, preview_digest: "0".repeat(64) } },
  ])
    await expect(
      validateCorrectionApplied(
        { ...applied, command: { ...applied.command, ...patch } },
        correctionScope,
        { base: pending.base, pending },
        etag,
      ),
    ).rejects.toThrow();
});
it("rejects a rehashed saved result that silently reuses a replaced rule's check plan or loses withdrawal", async () => {
  const f = await correctionFixture(),
    [old] = f.inventory.manifest.requirements;
  f.request.changes = [
    {
      op: "replace",
      rule_id: old.rule_id,
      rule_digest: old.rule_digest,
      rule: correctionRule(),
    },
  ];
  const preview = await correctionPreview(f.inventory, f.request, f.evidence),
    applied = await correctionApplied(f.inventory, preview);
  applied.inventory.manifest.requirements[0].annotation.mapped = true;
  applied.inventory.digest = await jsonDigest(applied.inventory.manifest);
  await expect(
    validateCorrectionApplied(
      applied,
      correctionScope,
      { base: correctionBase(f.inventory) },
      `"requirement-inventory:${correctionScope.revisionId}:${applied.inventory.digest}"`,
    ),
  ).rejects.toThrow();
});
it("keeps history scoped while allowing the saved command to retain its original base inventory", async () => {
  const f = await correctionFixture(),
    preview = await correctionPreview(f.inventory, f.request, f.evidence),
    applied = await correctionApplied(f.inventory, preview);
  const m = applied.correction.manifest;
  const page = {
    scope: {
      ...preview.manifest.scope,
      inventory_id: applied.inventory.manifest.id,
    },
    items: [
      {
        id: m.id,
        digest: applied.correction.digest,
        created_at: m.created_at,
        actor_id: m.actor_id,
        base_inventory_id: f.inventory.manifest.id,
        result_inventory_id: applied.inventory.manifest.id,
        added: 1,
        replaced: 0,
        withdrawn: 0,
      },
    ],
    has_more: false,
    next_cursor: null,
  };
  expect(
    validateCorrectionHistory(
      page,
      correctionScope,
      applied.inventory.manifest.id,
    ).items,
  ).toHaveLength(1);
  expect(() =>
    validateCorrectionHistory(
      page,
      { ...correctionScope, revisionId: correctionId(999) },
      applied.inventory.manifest.id,
    ),
  ).toThrow();
  expect(correctionInventoryMatches(applied.inventory, correctionScope)).toBe(
    true,
  );
});
