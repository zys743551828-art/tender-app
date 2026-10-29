import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  documentParseTestFixture,
  documentParseTestId as id,
} from "./documentParseTestFixture";
import {
  assertDocumentParseUpdate,
  definitelyRejectedDocumentParse,
  validDocumentParseReason,
  validateDocumentParseContext,
  validateDocumentParsePage,
  validateDocumentParseStarted,
  validateDocumentParseView,
} from "./documentParseProtocol";
let f: Awaited<ReturnType<typeof documentParseTestFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await documentParseTestFixture();
});
afterEach(() => vi.unstubAllGlobals());
it("accepts exact context, stable acknowledgement, and a partial result with ISO offset timestamps", async () => {
  await expect(
    validateDocumentParseContext(f.wrapper, f.scope),
  ).resolves.toEqual(f.wrapper);
  await expect(
    validateDocumentParseStarted(await f.ack(), f.scope, f.pending),
  ).resolves.toMatchObject({ request: f.request });
  await expect(
    validateDocumentParseView(f.completed, f.scope, f.request.id),
  ).resolves.toEqual(f.completed);
});
it("binds the canonical context bytes and both the project and document", async () => {
  const wrong = structuredClone(f.wrapper);
  wrong.context.document.filename = "其他文件.pdf";
  await expect(validateDocumentParseContext(wrong, f.scope)).rejects.toThrow(
    /身份无法核验/,
  );
  wrong.context_digest = await frozenManifestDigest(wrong.context);
  wrong.context.bid_id = id(80);
  wrong.context_digest = await frozenManifestDigest(wrong.context);
  await expect(validateDocumentParseContext(wrong, f.scope)).rejects.toThrow();
  await expect(
    validateDocumentParseView(f.completed, { ...f.scope, documentId: id(81) }),
  ).rejects.toThrow();
});
it("allows a reused original request from another member but verifies the current ACK actor and request reason", async () => {
  const original = {
      ...f.completed,
      actor_id: id(70),
      reason: "另一成员的原申请",
    },
    ack = await f.ack(f.pending.body, original, true);
  await expect(
    validateDocumentParseStarted(ack, f.scope, f.pending),
  ).resolves.toEqual(ack);
  await expect(
    validateDocumentParseStarted(
      { ...ack, actor_id: id(70) },
      f.scope,
      f.pending,
    ),
  ).rejects.toThrow();
  await expect(
    validateDocumentParseStarted({ ...ack, reused: false }, f.scope, f.pending),
  ).rejects.toThrow();
  await expect(
    validateDocumentParseStarted(ack, f.scope, {
      ...f.pending,
      body: { ...f.pending.body, reason: "不同的新申请理由" },
    }),
  ).rejects.toThrow();
});
it.each([
  "source_digest",
  "parser_digest",
  "config_digest",
  "document_version_id",
] as const)("rejects a result bound to the wrong %s", async (key) => {
  const wrong = structuredClone(f.completed);
  wrong.result![key] = key === "document_version_id" ? id(90) : "f".repeat(64);
  await expect(validateDocumentParseView(wrong, f.scope)).rejects.toThrow();
});
it("does not turn physical-text completion into full coverage or Word qualification", async () => {
  const wrong = structuredClone(f.completed);
  wrong.result!.coverage = "complete";
  wrong.result!.gaps = [];
  wrong.result!.gap_count = 0;
  await expect(validateDocumentParseView(wrong, f.scope)).rejects.toThrow();
  wrong.context.method.mode = "configured_local";
  wrong.context_digest = await frozenManifestDigest(wrong.context);
  wrong.operation.input_digest = wrong.context_digest;
  await expect(validateDocumentParseView(wrong, f.scope)).resolves.toEqual(
    wrong,
  );
  await expect(
    validateDocumentParseView(
      { ...wrong, current_body_changed: true },
      f.scope,
    ),
  ).rejects.toThrow();
  await expect(
    validateDocumentParseView(
      { ...wrong, result: { ...wrong.result, word_coverage_claimed: true } },
      f.scope,
    ),
  ).rejects.toThrow();
});
it("accepts a succeeded worker with failed content coverage and validates gap truncation separately", async () => {
  const result = structuredClone(f.completed);
  result.result!.coverage = "failed";
  result.result!.page_count = 0;
  result.result!.gaps = Array.from(
    { length: 100 },
    (_, index) => `合成缺口 ${index}`,
  );
  result.result!.gap_count = 120;
  await expect(validateDocumentParseView(result, f.scope)).resolves.toEqual(
    result,
  );
  result.result!.gap_count = 3;
  await expect(validateDocumentParseView(result, f.scope)).rejects.toThrow();
});
it("rejects missing successful results, nonterminal results, and another operation handler", async () => {
  await expect(
    validateDocumentParseView({ ...f.completed, result: null }, f.scope),
  ).rejects.toThrow();
  await expect(
    validateDocumentParseView(
      { ...f.request, result: f.completed.result },
      f.scope,
    ),
  ).rejects.toThrow();
  await expect(
    validateDocumentParseView(
      {
        ...f.completed,
        operation: { ...f.completed.operation, handler_version: "other/1" },
      },
      f.scope,
    ),
  ).rejects.toThrow();
});
it("rejects terminal regressions, mutable results, and operation identity switches", async () => {
  await expect(
    assertDocumentParseUpdate(f.request, f.completed),
  ).resolves.toBeUndefined();
  await expect(
    assertDocumentParseUpdate(f.completed, f.request),
  ).rejects.toThrow(/已确认终态/);
  await expect(
    assertDocumentParseUpdate(f.completed, {
      ...f.completed,
      result: { ...f.completed.result!, evidence_count: 4 },
    }),
  ).rejects.toThrow();
  await expect(
    assertDocumentParseUpdate(f.request, {
      ...f.request,
      operation: { ...f.request.operation, id: id(99) },
    }),
  ).rejects.toThrow();
});
it("checks page scope, strict UUID order, duplicate ids, and cursors", async () => {
  await expect(validateDocumentParsePage(f.page(), f.scope)).resolves.toEqual(
    f.page(),
  );
  await expect(
    validateDocumentParsePage(f.page([f.completed, f.completed]), f.scope),
  ).rejects.toThrow();
  await expect(
    validateDocumentParsePage({ ...f.page(), bid_id: id(80) }, f.scope),
  ).rejects.toThrow();
  await expect(
    validateDocumentParsePage({ ...f.page(), has_more: true }, f.scope),
  ).rejects.toThrow();
});
it("uses Unicode code points for reasons and rejects controls and isolated surrogates", () => {
  expect(validDocumentParseReason("证据😀".repeat(333))).toBe(true);
  expect(validDocumentParseReason("😀".repeat(1001))).toBe(false);
  expect(validDocumentParseReason("只含\n换行")).toBe(false);
  expect(validDocumentParseReason("孤立\ud800字符")).toBe(false);
  expect(validDocumentParseReason("   ")).toBe(false);
});
it("keeps incomplete, conflicting, unauthenticated, and transient commands recoverable", () => {
  for (const [code, status] of [
    ["COMMAND_INCOMPLETE", 409],
    ["IDEMPOTENCY_CONFLICT", 409],
    ["DOCUMENT_PARSE_SCOPE_MISMATCH", 409],
    ["DOCUMENT_PARSE_RECORD_CORRUPT", 500],
    ["UNKNOWN", 409],
    ["LOGIN_REQUIRED", 401],
    ["RATE_LIMITED", 429],
  ] as const)
    expect(
      definitelyRejectedDocumentParse(new ApiError("synthetic", status, code)),
    ).toBe(false);
  expect(
    definitelyRejectedDocumentParse(
      new ApiError("synthetic", 409, "DOCUMENT_PARSE_CONTEXT_CHANGED"),
    ),
  ).toBe(true);
  expect(
    definitelyRejectedDocumentParse(
      new ApiError("synthetic", 409, "PROJECT_WORK_CLOSED"),
    ),
  ).toBe(true);
  expect(
    definitelyRejectedDocumentParse(
      new ApiError("synthetic", 404, "DOCUMENT_PARSE_ORIGINAL_NOT_FOUND"),
    ),
  ).toBe(true);
});
