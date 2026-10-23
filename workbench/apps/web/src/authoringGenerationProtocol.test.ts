import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import type { AuthoringGenerationJson } from "./contracts";
import type { PendingGeneration } from "./authoringGenerationRecovery";
import {
  currentGenerationAttempt,
  publishedGenerationAttempt,
  validateGenerationBatch,
  validateGenerationCandidate,
  validateGenerationCapabilities,
  validateGenerationCommandDigest,
  validateGenerationPage,
  validateGenerationReceipt,
} from "./authoringGenerationProtocol";
import {
  generationCapabilities,
  generationFixture,
  generationId,
  generationReceipt,
  generationScope,
} from "./authoringGenerationFixtures.test-support";

it("validates actual full Rich candidates with multiple replacements, additions and unchanged merged tables", async () => {
  const { batch, candidates } = await generationFixture();
  expect(validateGenerationCapabilities(generationCapabilities)).toEqual(
    generationCapabilities,
  );
  expect(
    validateGenerationBatch(batch, generationScope, batch.batch_id),
  ).toEqual(batch);
  expect(
    validateGenerationPage(
      {
        bid_id: batch.bid_id,
        draft_id: batch.draft_id,
        items: [batch],
        has_more: false,
        next_cursor: null,
      },
      generationScope,
    ).items,
  ).toHaveLength(1);
  for (let index = 0; index < candidates.length; index++) {
    expect(
      await validateGenerationCandidate(
        candidates[index],
        generationScope,
        batch,
        batch.sections[index],
        currentGenerationAttempt(batch.sections[index]),
      ),
    ).toEqual(candidates[index]);
  }
});
it("treats worker success with pending publication as unfinished candidate preparation", async () => {
  const { batch } = await generationFixture();
  const attempt = batch.sections[0].attempts[0];
  Object.assign(attempt, {
    publication_state: "pending",
    action_id: null,
    candidate_digest: null,
    candidate_url: null,
  });
  expect(validateGenerationBatch(batch, generationScope)).toEqual(batch);
  expect(publishedGenerationAttempt(attempt)).toBe(false);
});
it("rejects cross-project batches, mismatched frozen requests and altered cumulative limits", async () => {
  const { batch } = await generationFixture();
  for (const changed of [
    { ...batch, bid_id: generationId(900) },
    { ...batch, base_draft_revision: 8 },
    {
      ...batch,
      sections: [
        { ...batch.sections[0], budget_limit_minor: 3 },
        batch.sections[1],
      ],
    },
    { ...batch, price: { ...batch.price, currency: "USD" } },
    {
      ...batch,
      preparation: { ...batch.preparation, if_match: '"other-head"' },
    },
  ])
    expect(() => validateGenerationBatch(changed, generationScope)).toThrow();
});
it("rejects retry authorization while a published result or unreconciled provider charge is present", async () => {
  const { batch } = await generationFixture();
  const attempt = batch.sections[0].attempts[0];
  Object.assign(attempt, { retry_allowed: true, retry_blocked_reason: null });
  expect(() => validateGenerationBatch(batch, generationScope)).toThrow();
  Object.assign(attempt, {
    state: "failed",
    publication_state: "failed",
    action_id: null,
    candidate_digest: null,
    candidate_url: null,
    budget_state: "unknown",
    requires_reconciliation: true,
  });
  expect(() => validateGenerationBatch(batch, generationScope)).toThrow();
});
it("binds receipts to actor, original key/body/etag and exact applied section set", async () => {
  const { batch } = await generationFixture();
  const section = batch.sections[0],
    attempt = currentGenerationAttempt(section);
  const pending: PendingGeneration = {
    kind: "resolve",
    batchId: batch.batch_id,
    baseDraftRevision: 7,
    key: generationId(200),
    etag: batch.base_draft_etag,
    body: {
      decision: "apply",
      batch_digest: batch.batch_digest,
      selections: [
        {
          section_id: section.section_id,
          attempt: attempt.attempt,
          job_id: attempt.job_id,
          action_id: attempt.action_id!,
          candidate_digest: attempt.candidate_digest!,
        },
      ],
      reason: "逐章完整核对",
    },
  };
  const receipt = await generationReceipt(batch, pending);
  await expect(
    validateGenerationCommandDigest(receipt.command, generationScope),
  ).resolves.toBeUndefined();
  await expect(
    validateGenerationCommandDigest(
      { ...receipt.command, request_digest: "0".repeat(64) },
      generationScope,
    ),
  ).rejects.toThrow();
  expect(
    validateGenerationReceipt(receipt, generationScope, pending, batch),
  ).toEqual(receipt);
  for (const changed of [
    {
      ...receipt,
      command: { ...receipt.command, actor_id: generationId(999) },
    },
    {
      ...receipt,
      command: { ...receipt.command, idempotency_key: generationId(998) },
    },
    { ...receipt, command: { ...receipt.command, if_match: '"new-head"' } },
    {
      ...receipt,
      command: {
        ...receipt.command,
        request: { ...pending.body, reason: "偷偷换了理由" },
      },
    },
    { ...receipt, applied_section_ids: [batch.sections[1].section_id] },
    { ...receipt, unselected_section_ids: [] },
    { ...receipt, draft_revision: 9 },
  ])
    expect(() =>
      validateGenerationReceipt(changed, generationScope, pending, batch),
    ).toThrow();
});
it("validates recovered apply receipts without needing a new current head or detail read", async () => {
  const { batch } = await generationFixture();
  const candidate = batch.sections[0].attempts[0];
  const pending: PendingGeneration = {
    kind: "resolve",
    batchId: batch.batch_id,
    baseDraftRevision: 7,
    key: generationId(202),
    etag: batch.base_draft_etag,
    body: {
      decision: "apply",
      batch_digest: batch.batch_digest,
      selections: [
        {
          section_id: batch.sections[0].section_id,
          attempt: 1,
          job_id: candidate.job_id,
          action_id: candidate.action_id!,
          candidate_digest: candidate.candidate_digest!,
        },
      ],
      reason: "原理由",
    },
  };
  expect(
    validateGenerationReceipt(
      await generationReceipt(batch, pending),
      generationScope,
      pending,
    ).draft_revision,
  ).toBe(8);
});
it("rejects candidate identity substitution and raw Rich digest tampering before selection", async () => {
  const { batch, candidates } = await generationFixture();
  const section = batch.sections[0],
    attempt = currentGenerationAttempt(section),
    candidate = candidates[0];
  for (const changed of [
    { ...candidate, bid_id: generationId(203) },
    { ...candidate, job_id: generationId(204) },
    { ...candidate, base_section_revision: 9 },
    { ...candidate, candidate_digest: "0".repeat(64) },
    { ...candidate, after_digest: "0".repeat(64) },
  ])
    await expect(
      validateGenerationCandidate(
        changed,
        generationScope,
        batch,
        section,
        attempt,
      ),
    ).rejects.toThrow();
});
it("rejects changed tables or untouched paragraphs even when an attacker supplies a matching raw JSON digest", async () => {
  const { batch, candidates } = await generationFixture();
  const section = batch.sections[0],
    attempt = currentGenerationAttempt(section);
  for (const target of ["table", "untouched"]) {
    const candidate = structuredClone(candidates[0]);
    const after = candidate.after as {
      type: string;
      attrs: AuthoringGenerationJson;
      content: {
        type: string;
        attrs: { id: string; caption?: string };
        content: AuthoringGenerationJson[];
      }[];
    };
    if (target === "table")
      after.content.find((node) => node.type === "table")!.attrs.caption =
        "未经选择的修改";
    else
      after.content.find(
        (node) => node.attrs.id === "chapter-0-untouched",
      )!.content = [{ type: "text", text: "未经选择的修改" }];
    candidate.after_digest = await jsonDigest(candidate.after);
    await expect(
      validateGenerationCandidate(
        candidate,
        generationScope,
        batch,
        section,
        attempt,
      ),
    ).rejects.toThrow();
  }
});
it("rejects undeclared additions and replacement outside the explicit frozen node scope", async () => {
  const { batch, candidates } = await generationFixture();
  const section = batch.sections[0],
    attempt = currentGenerationAttempt(section);
  await expect(
    validateGenerationCandidate(
      {
        ...candidates[0],
        changes: {
          ...candidates[0].changes,
          insertions: [],
          added_paragraphs: 0,
        },
      },
      generationScope,
      batch,
      section,
      attempt,
    ),
  ).rejects.toThrow();
  await expect(
    validateGenerationCandidate(
      candidates[0],
      generationScope,
      batch,
      { ...section, selected_node_ids: ["chapter-0-intro"] },
      attempt,
    ),
  ).rejects.toThrow();
});
it("rejects unknown price scale, unsafe money and another project's history before rendering financial figures", async () => {
  expect(() =>
    validateGenerationCapabilities({
      ...generationCapabilities,
      amount_scale: 100,
    }),
  ).toThrow();
  const { batch } = await generationFixture();
  expect(() =>
    validateGenerationBatch(
      {
        ...batch,
        budget: { ...batch.budget, charged_minor: Number.MAX_SAFE_INTEGER + 1 },
      },
      generationScope,
    ),
  ).toThrow();
  expect(() =>
    validateGenerationPage(
      {
        bid_id: generationId(700),
        draft_id: batch.draft_id,
        items: [batch],
        has_more: false,
        next_cursor: null,
      },
      generationScope,
    ),
  ).toThrow();
});
