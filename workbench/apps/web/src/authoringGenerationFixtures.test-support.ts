// Synthetic protocol fixtures. These never represent real model or business acceptance.
import type {
  AuthoringGenerationBatch,
  AuthoringGenerationBatchCandidate,
  AuthoringGenerationBatchCapabilities,
  AuthoringGenerationBatchCreateRequest,
  AuthoringGenerationBatchReceipt,
  AuthoringGenerationJson,
  AuthoringRichDocument,
  DraftView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import { importCandidate } from "./authoringWordImportFixtures.test-support";
import type { PendingGeneration } from "./authoringGenerationRecovery";

export const generationId = (value: number) =>
  `10000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
export const generationScope = {
  memberId: generationId(1),
  bidId: generationId(2),
  draftId: generationId(3),
};
export const generationHead = {
  data: {
    id: generationScope.draftId,
    bid_id: generationScope.bidId,
    revision: 7,
    snapshot_id: generationId(4),
    sections: [
      {
        id: generationId(10),
        title: "施工组织",
        ordinal: 0,
        revision: 2,
        rule_ids: [],
        save_state: "saved",
      },
      {
        id: generationId(11),
        title: "质量保障",
        ordinal: 1,
        revision: 3,
        rule_ids: [],
        save_state: "saved",
      },
      {
        id: generationId(12),
        title: "未选商务章节",
        ordinal: 2,
        revision: 1,
        rule_ids: [],
        save_state: "saved",
      },
    ],
  } as DraftView,
  etag: '"draft-7"',
};
export const generationCapabilities: AuthoringGenerationBatchCapabilities = {
  enabled: true,
  unavailable_reason: null,
  generation_mode: "section_patch_set/1",
  max_sections: 20,
  max_attempts_per_section: 5,
  max_frozen_bytes: 16 * 1024 * 1024,
  max_instruction_chars: 8000,
  max_limit_minor: Number.MAX_SAFE_INTEGER,
  amount_scale: 1000000000,
  default_max_tokens: 1024,
  price: {
    price_version_id: generationId(20),
    version: "synthetic-price-1",
    provider: "test-provider",
    model: "test-model",
    currency: "CNY",
    amount_scale: 1000000000,
    input_upper: 20000,
    output_upper: 8192,
    input_per_million_minor: 1000000000,
    output_per_million_minor: 2000000000,
    valid_until: "2099-01-01T00:00:00Z",
    source_kind: "test_fixture",
    source_uri: "synthetic:local-test-price",
    source_sha256: "a".repeat(64),
  },
  estimates: [
    { max_tokens: 1024, reservation_minor: 2000000 },
    { max_tokens: 2048, reservation_minor: 4000000 },
  ],
  requires_explicit_selection: true,
  atomic_apply: true,
  requires_verified_identity: true,
  automatic_retry_authorized: false,
};
export function generationCreateBody(): AuthoringGenerationBatchCreateRequest {
  return {
    base_draft_revision: 7,
    price_version_id: generationId(20),
    currency: "CNY",
    amount_scale: 1000000000,
    total_limit_minor: 200000000,
    sections: generationHead.data.sections.slice(0, 2).map((section) => ({
      section_id: section.id,
      base_section_revision: section.revision,
      instruction: `完善${section.title}的多处正文`,
      source_version_ids: [],
      selected_node_ids: null,
      max_tokens: 1024,
      budget_limit_minor: 100000000,
    })),
    reason: "明确预算后逐章核对",
  };
}
const paragraph = (id: string, value: string) => ({
  type: "paragraph",
  attrs: { id },
  content: [{ type: "text", text: value }],
});
function content(index: number) {
  const title = generationHead.data.sections[index].title;
  return {
    type: "doc",
    attrs: { title, ordinal: index, rule_ids: [], source_refs: [] },
    content: [
      paragraph(`chapter-${index}-intro`, `${title}原有目标`),
      paragraph(`chapter-${index}-steps`, `${title}原有步骤`),
      ...(index === 0
        ? structuredClone(
            (importCandidate().sections[1].content as AuthoringRichDocument)
              .content as AuthoringGenerationJson[],
          )
        : []),
      paragraph(
        `chapter-${index}-untouched`,
        "这一段保持原样，人工确认内容不被替换。",
      ),
    ],
  };
}
function budget(limit: number, charged = 2000000, reserved = 0) {
  return {
    currency: "CNY" as const,
    amount_scale: 1000000000 as const,
    limit_minor: limit,
    charged_minor: charged,
    reserved_minor: reserved,
    exposure_minor: charged + reserved,
    remaining_minor: limit - charged - reserved,
    requires_reconciliation: false,
    over_limit: false,
    estimate_not_provider_spend_cap: true as const,
  };
}
export async function generationFixture() {
  const body = generationCreateBody();
  const before = [content(0), content(1)];
  const beforeDigests = await Promise.all(
    before.map((value) => jsonDigest(value)),
  );
  const batch: AuthoringGenerationBatch = {
    protocol: "authoring-generation-batch/1",
    generation_mode: "section_patch_set/1",
    batch_id: generationId(30),
    bid_id: generationScope.bidId,
    draft_id: generationScope.draftId,
    batch_digest: "b".repeat(64),
    base_draft_revision: 7,
    base_snapshot_id: generationId(4),
    base_snapshot_digest: "c".repeat(64),
    base_draft_etag: generationHead.etag,
    state: "open",
    created_at: "2026-10-21T12:00:00Z",
    created_by: generationScope.memberId,
    section_count: 2,
    ready_count: 2,
    failed_count: 0,
    running_count: 0,
    price: structuredClone(generationCapabilities.price!),
    reason: body.reason,
    etag: '"batch-1"',
    budget: budget(body.total_limit_minor, 4000000),
    preparation: {
      command_id: generationId(31),
      actor_id: generationScope.memberId,
      idempotency_key: generationId(32),
      request_digest: await jsonDigest({
        body: {
          bid_id: generationScope.bidId,
          draft_id: generationScope.draftId,
          ...body,
        },
        if_match: generationHead.etag,
      }),
      request: body,
      if_match: generationHead.etag,
    },
    sections: body.sections.map((section, index) => ({
      ...section,
      title: generationHead.data.sections[index].title,
      ordinal: index,
      before_digest: beforeDigests[index],
      current_attempt: 1,
      budget: budget(section.budget_limit_minor),
      attempts: [
        {
          attempt: 1,
          job_id: generationId(40 + index),
          operation_id: generationId(50 + index),
          writing_plan_id: generationId(60 + index),
          created_at: "2026-10-21T12:00:00Z",
          created_by: generationScope.memberId,
          state: "succeeded",
          publication_state: "published",
          action_id: generationId(70 + index),
          candidate_digest: (index === 0 ? "e" : "f").repeat(64),
          candidate_url: `/bids/${generationScope.bidId}/drafts/${generationScope.draftId}/generation-batches/${generationId(30)}/candidates/${generationId(70 + index)}`,
          error_code: null,
          budget_state: "settled",
          reserved_minor: 2000000,
          charged_minor: 2000000,
          requires_reconciliation: false,
          retry_allowed: false,
          retry_blocked_reason: {
            code: "ALREADY_READY",
            message: "候选已就绪，不能重复计费生成。",
          },
        },
      ],
    })),
    resolution: null,
    current_validity: "rechecked_on_retry_and_apply",
    requires_explicit_selection: true,
    atomic_apply: true,
  };
  const candidates: AuthoringGenerationBatchCandidate[] = await Promise.all(
    before.map(async (original, index) => {
      const after = structuredClone(original);
      after.content[0] = paragraph(
        `chapter-${index}-intro`,
        `${generationHead.data.sections[index].title}候选目标`,
      );
      after.content[1] = paragraph(
        `chapter-${index}-steps`,
        `${generationHead.data.sections[index].title}候选步骤`,
      );
      after.content.splice(
        2,
        0,
        paragraph(
          generationId(80 + index),
          "新增的实施与验收步骤，待人工核对事实。",
        ),
      );
      const section = batch.sections[index],
        attempt = section.attempts[0];
      return {
        protocol: "authoring-generation-candidate/1",
        generation_mode: "section_patch_set/1",
        bid_id: generationScope.bidId,
        draft_id: generationScope.draftId,
        batch_id: batch.batch_id,
        batch_digest: batch.batch_digest,
        section_id: section.section_id,
        attempt: 1,
        job_id: attempt.job_id,
        writing_plan_id: attempt.writing_plan_id,
        action_id: attempt.action_id!,
        candidate_digest: attempt.candidate_digest!,
        base_draft_revision: 7,
        base_section_revision: section.base_section_revision,
        base_draft_etag: generationHead.etag,
        before_digest: beforeDigests[index],
        after_digest: await jsonDigest(after),
        scope_digest: "1".repeat(64),
        before: original,
        after,
        changes: {
          replaced_node_ids: [
            `chapter-${index}-intro`,
            `chapter-${index}-steps`,
          ],
          insertions: [
            {
              after_node_id: `chapter-${index}-steps`,
              node_ids: [generationId(80 + index)],
            },
          ],
          added_paragraphs: 1,
        },
        created_at: "2026-10-21T12:02:00Z",
        expires_at: "2099-01-01T00:00:00Z",
        state: "pending",
        etag: `"candidate-${index}"`,
      };
    }),
  );
  return { batch, candidates, body };
}
export async function generationReceipt(
  batch: AuthoringGenerationBatch,
  pending: PendingGeneration,
): Promise<AuthoringGenerationBatchReceipt> {
  const applied =
    pending.kind === "resolve" && pending.body.decision === "apply";
  const resolved = pending.kind === "resolve";
  const selection = resolved
    ? pending.body.selections.map((item) => item.section_id)
    : [];
  return {
    protocol: "authoring-generation-batch-command/1",
    bid_id: batch.bid_id,
    draft_id: batch.draft_id,
    batch_id: batch.batch_id,
    batch_digest: batch.batch_digest,
    kind:
      pending.kind === "create"
        ? "created"
        : pending.kind === "retry"
          ? "retried"
          : applied
            ? "applied"
            : "rejected",
    batch_state: resolved ? (applied ? "applied" : "rejected") : "open",
    created_job_ids:
      pending.kind === "create"
        ? pending.body.sections.map((_item, index) => generationId(40 + index))
        : pending.kind === "retry"
          ? [generationId(90)]
          : [],
    applied_section_ids: selection,
    unselected_section_ids: resolved
      ? batch.sections
          .map((section) => section.section_id)
          .filter((id) => !selection.includes(id))
      : [],
    draft_revision: applied ? pending.baseDraftRevision + 1 : null,
    snapshot_id: applied ? generationId(91) : null,
    snapshot_digest: applied ? "9".repeat(64) : null,
    recorded_at: "2026-10-21T12:05:00Z",
    command: {
      command_id: generationId(92),
      actor_id: generationScope.memberId,
      idempotency_key: pending.key,
      request_digest: await jsonDigest({
        body: {
          bid_id: generationScope.bidId,
          draft_id: generationScope.draftId,
          ...pending.body,
        },
        if_match: pending.etag,
      }),
      request: pending.body,
      if_match: pending.etag,
    },
  };
}
