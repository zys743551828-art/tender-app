import { beforeEach, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  definitiveGenerationFailure,
  generationStorageKey,
  readGenerationRecovery,
  storeGenerationRecovery,
  validGenerationCreate,
  validGenerationResolve,
} from "./authoringGenerationRecovery";
import type { GenerationRecovery } from "./authoringGenerationRecovery";
import {
  generationCreateBody,
  generationId,
  generationScope,
} from "./authoringGenerationFixtures.test-support";

beforeEach(() => sessionStorage.clear());
function record(): GenerationRecovery {
  return {
    version: 1,
    scope: generationScope,
    lastBatchId: null,
    pending: {
      kind: "create",
      key: generationId(200),
      etag: '"original-draft-7"',
      baseDraftRevision: 7,
      body: generationCreateBody(),
    },
  };
}
it("round-trips the original exact paid body, key and ETag within member/project/draft scope", () => {
  const value = record();
  storeGenerationRecovery(value);
  expect(readGenerationRecovery(generationScope)).toEqual(value);
  expect(
    readGenerationRecovery({ ...generationScope, memberId: generationId(201) })
      .pending,
  ).toBeNull();
  expect(
    readGenerationRecovery({ ...generationScope, bidId: generationId(202) })
      .pending,
  ).toBeNull();
  expect(
    readGenerationRecovery({ ...generationScope, draftId: generationId(203) })
      .pending,
  ).toBeNull();
});
it("retains a corrupt record byte-for-byte and refuses a fresh paid operation", () => {
  const raw = '{"version":1,"pending":"truncated"}';
  sessionStorage.setItem(generationStorageKey(generationScope), raw);
  expect(() => readGenerationRecovery(generationScope)).toThrow(
    "恢复记录无法核验",
  );
  expect(sessionStorage.getItem(generationStorageKey(generationScope))).toBe(
    raw,
  );
});
it("rejects copied scope, weak ETags, mismatched base revision and unknown paid request keys", () => {
  for (const mutate of [
    (value: GenerationRecovery) => {
      value.scope = { ...value.scope, bidId: generationId(204) };
    },
    (value: GenerationRecovery) => {
      value.pending!.etag = 'W/"original-draft-7"';
    },
    (value: GenerationRecovery) => {
      value.pending!.baseDraftRevision = 8;
    },
    (value: GenerationRecovery) => {
      Object.assign(value.pending!.body, { automatic_retry: true });
    },
  ]) {
    const value = record();
    mutate(value);
    const raw = JSON.stringify(value);
    sessionStorage.setItem(generationStorageKey(generationScope), raw);
    expect(() => readGenerationRecovery(generationScope)).toThrow();
    expect(sessionStorage.getItem(generationStorageKey(generationScope))).toBe(
      raw,
    );
  }
});
it("allows stable legacy text node IDs and rejects duplicate sections, sources and inexact money", () => {
  const body = generationCreateBody();
  body.sections[0].selected_node_ids = ["legacy-intro-1", "chapter.steps"];
  expect(validGenerationCreate(body)).toBe(true);
  for (const changed of [
    { ...body, sections: [body.sections[0], body.sections[0]] },
    {
      ...body,
      sections: [
        {
          ...body.sections[0],
          source_version_ids: [generationId(50), generationId(50)],
        },
      ],
    },
    { ...body, total_limit_minor: 0.2 },
    { ...body, total_limit_minor: Number.MAX_SAFE_INTEGER + 1 },
    {
      ...body,
      sections: [{ ...body.sections[0], instruction: "\u0000unsafe" }],
    },
    {
      ...body,
      sections: [{ ...body.sections[0], selected_node_ids: ["same", "same"] }],
    },
    { ...body, total_limit_minor: 1 },
  ])
    expect(validGenerationCreate(changed)).toBe(false);
});
it("requires explicit distinct apply selections and an empty reject selection", () => {
  const selection = {
    section_id: generationId(10),
    attempt: 1,
    job_id: generationId(40),
    action_id: generationId(70),
    candidate_digest: "e".repeat(64),
  };
  const request = {
    decision: "apply",
    batch_digest: "b".repeat(64),
    selections: [selection],
    reason: "已完整核对",
  };
  expect(validGenerationResolve(request)).toBe(true);
  expect(validGenerationResolve({ ...request, selections: [] })).toBe(false);
  expect(
    validGenerationResolve({ ...request, selections: [selection, selection] }),
  ).toBe(false);
  expect(validGenerationResolve({ ...request, decision: "reject" })).toBe(
    false,
  );
  expect(
    validGenerationResolve({ ...request, decision: "reject", selections: [] }),
  ).toBe(true);
});
it("clears only proven transaction rejection, including CAS, and preserves ambiguous/auth/unknown errors", () => {
  for (const [status, code] of [
    [409, "AUTHORING_GENERATION_BATCH_BUDGET_INSUFFICIENT"],
    [409, "AUTHORING_GENERATION_BATCH_RUNNING"],
    [422, "AUTHORING_GENERATION_BATCH_SELECTION_INVALID"],
    [412, "CAS_CONFLICT"],
  ] as const)
    expect(
      definitiveGenerationFailure(new ApiError("rejected", status, code)),
    ).toBe(true);
  for (const [status, code] of [
    [409, "IDEMPOTENCY_CONFLICT"],
    [409, "COMMAND_INCOMPLETE"],
    [409, "UNKNOWN_409"],
    [422, "SCOPE_MISMATCH"],
    [422, "UNKNOWN_422"],
    [401, "UNAUTHENTICATED"],
    [403, "FORBIDDEN"],
    [404, "SERVICE_VERSION_NOT_READY"],
    [0, "NETWORK_ERROR"],
    [500, "REQUEST_FAILED"],
  ] as const)
    expect(
      definitiveGenerationFailure(new ApiError("uncertain", status, code)),
    ).toBe(false);
  expect(
    definitiveGenerationFailure(
      new ApiError("retryable", 412, "CAS_CONFLICT", undefined, true),
    ),
  ).toBe(false);
});
