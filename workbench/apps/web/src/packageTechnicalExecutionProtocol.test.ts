import { expect, it } from "vitest";
import { ApiError } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  technicalExecutionCheckRequest,
  validateTechnicalExecutionContext,
  validateTechnicalExecutionRefusal,
} from "./packageTechnicalExecutionProtocol";
import raw from "./test-fixtures/technical-execution-http.json";

const saved = raw.scope as unknown as PackageTechnicalScopeView;
const read = () =>
  validateTechnicalExecutionContext(raw.context, raw.etag, saved, null);
async function tag(value: typeof raw.context) {
  const stable = structuredClone(value);
  Reflect.deleteProperty(stable.qualification, "observed_at");
  return `"package-technical-execution:${saved.manifest.id}:${await jsonDigest(stable)}"`;
}
function refusal(details: unknown = raw.refusal.details) {
  return new ApiError(
    raw.refusal.message,
    409,
    raw.refusal.code,
    raw.refusal.request_id,
    false,
    details,
  );
}

it("accepts the paired actual PostgreSQL/ASGI synthetic context and zero-effect refusal", async () => {
  const context = await read();
  expect(context.execution_enabled).toBe(false);
  expect(context.producer.software_foundation).toBe("not_installed");
  expect(validateTechnicalExecutionRefusal(refusal(), context)).toEqual({
    ...raw.refusal.details,
    requestId: raw.refusal.request_id,
  });
  expect(technicalExecutionCheckRequest(context)).toEqual({
    ...raw.request,
    reason: "核对本范围的正式执行限制；本次检查预算为零。",
  });
});

it("accepts an installed foundation only while all formal permissions stay false", async () => {
  const changed = structuredClone(raw.context);
  changed.producer.software_foundation = "installed";
  const checked = await validateTechnicalExecutionContext(
    changed,
    await tag(changed),
    saved,
    null,
  );
  expect(checked.execution_enabled).toBe(false);
  expect(checked.producer.real_provider_configured).toBe(false);
});

it.each([
  [
    "execution permission",
    (v: typeof raw.context) => (v.execution_enabled = true),
  ],
  [
    "mechanism permission",
    (v: typeof raw.context) =>
      (v.producer.mechanism_test_publicly_available = true),
  ],
  [
    "provider permission",
    (v: typeof raw.context) => (v.producer.real_provider_configured = true),
  ],
  [
    "method identity",
    (v: typeof raw.context) => (v.method.model_alias = "other"),
  ],
  [
    "three judgments",
    (v: typeof raw.context) =>
      (v.qualification.judgments.recorded_valid_independent = 3),
  ],
  ["missing blocker", (v: typeof raw.context) => v.blockers.pop()],
  [
    "invented blocker text",
    (v: typeof raw.context) => (v.blockers[0].message = "ready"),
  ],
  [
    "cross-scope context",
    (v: typeof raw.context) =>
      (v.qualification.scope.scope_id = "00000000-0000-4000-8000-000000000001"),
  ],
])(
  "rejects %s even when a changed response carries its own matching tag",
  async (_, mutate) => {
    const changed = structuredClone(raw.context);
    mutate(changed);
    await expect(
      validateTechnicalExecutionContext(
        changed,
        await tag(changed),
        saved,
        null,
      ),
    ).rejects.toThrow();
  },
);

it("requires the exact ETag and explicitly selected scale", async () => {
  await expect(
    validateTechnicalExecutionContext(raw.context, null, saved, null),
  ).rejects.toThrow();
  await expect(
    validateTechnicalExecutionContext(raw.context, '"stale"', saved, null),
  ).rejects.toThrow();
  await expect(
    validateTechnicalExecutionContext(
      raw.context,
      raw.etag,
      saved,
      "00000000-0000-4000-8000-000000000001",
    ),
  ).rejects.toThrow();
});

it.each([
  ["job created", { ...raw.refusal.details, jobs_created: 1 }],
  ["model request sent", { ...raw.refusal.details, model_requests: 1 }],
  ["wrong scope", { ...raw.refusal.details, scope_digest: "a".repeat(64) }],
  ["wrong method", { ...raw.refusal.details, method_digest: "b".repeat(64) }],
  ["partial reasons", { ...raw.refusal.details, blockers: [] }],
  ["extra permission", { ...raw.refusal.details, formal: true }],
])(
  "rejects a %s refusal instead of showing a zero-effect receipt",
  async (_, details) => {
    const context = await read();
    expect(() =>
      validateTechnicalExecutionRefusal(refusal(details), context),
    ).toThrow();
  },
);

it("does not treat an unrelated error, retryable outcome or success as a refusal receipt", async () => {
  const context = await read();
  for (const error of [
    new Error("offline"),
    new ApiError("conflict", 412, "REVISION_CONFLICT"),
    new ApiError(
      "ok",
      201,
      raw.refusal.code,
      raw.refusal.request_id,
      false,
      raw.refusal.details,
    ),
    new ApiError(
      "retry",
      409,
      raw.refusal.code,
      raw.refusal.request_id,
      true,
      raw.refusal.details,
    ),
  ])
    expect(() => validateTechnicalExecutionRefusal(error, context)).toThrow();
});
