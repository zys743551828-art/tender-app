import { expect, it } from "vitest";
import { ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import { taskPackageCommandFixture } from "./taskPackageFixtures.test-support";
import {
  definitiveTaskPackageFailure,
  normalizeTaskPackageRequest,
  taskPackageTemplateEtag,
  validateCurrentRun,
  validateRunACK,
  validateTaskPackagePending,
  validateTaskPackageTemplate,
  validateTemplateACK,
  verifyTaskPackagePending,
} from "./taskPackageProtocol";

const other = "00000000-0000-4000-8000-000000000999";
const digest = "0".repeat(64);
function changed<T>(source: T, path: string, value: unknown): T {
  const copy = structuredClone(source);
  const keys = path.split(".");
  let cursor = copy as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    cursor = cursor[key] as Record<string, unknown>;
  cursor[keys.at(-1)!] = value;
  return copy;
}

it("accepts original native HTTP create/revise and their exact template digests without rewriting fixtures", async () => {
  const { f, createScope, reviseScope, pendingCreate, pendingRevise } =
    taskPackageCommandFixture();
  await expect(
    validateTemplateACK(
      f.created.data,
      f.created.headers.etag,
      pendingCreate,
      createScope,
    ),
  ).resolves.toEqual(f.created.data);
  await expect(
    validateTemplateACK(
      f.revised.data,
      f.revised.headers.etag,
      pendingRevise,
      reviseScope,
    ),
  ).resolves.toEqual(f.revised.data);
  await expect(
    validateTaskPackageTemplate(
      f.revised.data,
      f.revised.headers.etag,
      createScope.bidId,
      f.revised.data.id,
    ),
  ).resolves.toEqual(f.revised.data);
  expect(normalizeTaskPackageRequest(pendingCreate.body)).toEqual(
    f.created.data.configuration,
  );
});

it.each([
  ["bid_id", other],
  ["revision", 2],
  ["digest", digest],
  ["purpose", "assist"],
  ["paused", true],
  ["run_created", true],
  ["active_runs_cancelled", true],
  ["next_run_at", "2026-10-22T00:00:00Z"],
  ["configuration.task_kind", "scoring_review"],
  ["configuration.trigger.mode", "schedule"],
  ["configuration.trigger.cron", "0 0 * * *"],
  ["configuration.section_id", other],
  ["configuration.source_selection.input.frozen_input_id", other],
  ["configuration.source_selection.input.method_digest", digest],
  ["unexpected", true],
])("rejects a template ACK with altered %s", async (path, value) => {
  const { f, pendingCreate, createScope } = taskPackageCommandFixture();
  await expect(
    validateTemplateACK(
      changed(f.created.data, path as string, value),
      f.created.headers.etag,
      pendingCreate,
      createScope,
    ),
  ).rejects.toThrow();
});

it("binds revision, old snapshot and ETag, while allowing server-generated new identity only for create", async () => {
  const { f, pendingRevise, reviseScope, pendingCreate, createScope } =
    taskPackageCommandFixture();
  for (const value of [
    changed(f.revised.data, "id", other),
    changed(f.revised.data, "version_id", f.created.data.version_id),
    changed(f.revised.data, "revision", 3),
  ]) {
    await expect(
      validateTemplateACK(
        value,
        taskPackageTemplateEtag(value.id, value.revision),
        pendingRevise,
        reviseScope,
      ),
    ).rejects.toThrow();
  }
  await expect(
    validateTemplateACK(f.created.data, null, pendingCreate, createScope),
  ).rejects.toThrow();
  await expect(
    validateTemplateACK(
      f.created.data,
      `W/${f.created.headers.etag}`,
      pendingCreate,
      createScope,
    ),
  ).rejects.toThrow();
  await expect(
    verifyTaskPackagePending(
      changed(pendingRevise, "expected.previous.digest", digest),
      reviseScope,
    ),
  ).rejects.toThrow();
});

it.each([
  ["source_selection.mode", undefined],
  ["source_selection.mode", "current_project"],
  ["source_selection.version_ids", []],
  ["source_selection.input.extra", other],
  ["source_selection.input.execution_input_digest", "abc"],
  ["trigger", null],
  ["trigger", { timezone: null }],
  ["trigger", { timezone: "not/a/timezone" }],
  ["trigger", { mode: "material_updated" }],
  ["trigger", { cron: "0 0 * * *" }],
  ["name", " "],
  ["instructions", "x".repeat(8001)],
  ["formal_decisions_allowed", false],
])(
  "rejects implicit exact modes or malformed request field %s",
  (path, value) => {
    const { create } = taskPackageCommandFixture();
    expect(() =>
      normalizeTaskPackageRequest(changed(create.body, path as string, value)),
    ).toThrow();
  },
);

it("accepts only the selected creation prepared/plan identity and exact server write paths", () => {
  const { f, pendingCreate, createScope, pendingRun, runScope } =
    taskPackageCommandFixture();
  const selection = f.created.data.configuration.source_selection;
  if (selection?.mode !== "exact_package_review") throw new Error("fixture");
  const scoped = {
    ...createScope,
    identity: `package:${selection.input.execution_input_id}:${selection.input.dependency_plan_id}`,
  };
  expect(validateTaskPackagePending(pendingCreate, scoped)).toEqual(
    pendingCreate,
  );
  expect(() =>
    validateTaskPackagePending(pendingCreate, {
      ...scoped,
      identity: `package:${other}:${selection.input.dependency_plan_id}`,
    }),
  ).toThrow();
  for (const modified of [
    { ...pendingRun, path: pendingRun.path + "?latest=true" },
    {
      ...pendingRun,
      path: `/bids/${other}/task-definitions/${runScope.identity}/runs`,
    },
    { ...pendingRun, path: `https://example.com${pendingRun.path}` },
    { ...pendingRun, method: "PUT" },
    { ...pendingRun, body: { rerun: true } },
    { ...pendingRun, body: {} },
    { ...pendingRun, key: "not-uuid" },
    { ...pendingRun, etag: f.revised.headers.etag },
  ])
    expect(() => validateTaskPackagePending(modified, runScope)).toThrow();
});

it("separates immutable queued original HTTP ACK from current completion and explicit native reuse", async () => {
  const { f, pendingRun, runScope } = taskPackageCommandFixture();
  expect(f.replay.data).toEqual(f.queued.data);
  await expect(
    validateRunACK(f.queued.data, null, pendingRun, runScope),
  ).resolves.toMatchObject({ state: "queued", result: null });
  await expect(
    validateRunACK(f.replay.data, null, pendingRun, runScope),
  ).resolves.toMatchObject({ state: "queued" });
  await expect(
    validateCurrentRun(
      f.completed.data,
      runScope.bidId,
      f.queued.data.id,
      f.queued.data,
    ),
  ).resolves.toMatchObject({
    state: "succeeded",
    result: { overall_coverage: "partial", formal_scoring_eligible: false },
  });
  // A later explicit POST can reuse a completed native operation. The transport
  // chooses POST or GET; state alone cannot prove which response was requested.
  await expect(
    validateRunACK(f.completed.data, null, pendingRun, runScope),
  ).resolves.toMatchObject({ state: "succeeded" });
  await expect(
    validateRunACK(
      f.queued.data,
      null,
      {
        ...pendingRun,
        etag: f.revised.headers.etag,
        expected: { kind: "run", template: f.revised.data },
      },
      runScope,
    ),
  ).rejects.toThrow();
  await expect(
    validateCurrentRun(f.completed.data, runScope.bidId, other),
  ).rejects.toThrow();
  await expect(
    validateRunACK(f.queued.data, '"unexpected"', pendingRun, runScope),
  ).rejects.toThrow();
});

it.each([
  ["bid_id", other],
  ["definition_version_id", other],
  ["root_operation_id", other],
  ["final_operation_id", null],
  ["stage", "preparation"],
  ["coverage", "registered_effectivity_only_semantic_unknown"],
  ["formal_decisions_created", true],
  ["state", "awaiting_review"],
  ["state", ["queued"]],
  ["state", "succeeded"],
  ["frozen_manifest.schema", "task-run/1"],
  ["frozen_manifest.definition_id", other],
  ["frozen_manifest.definition_version_id", other],
  ["frozen_manifest.configuration_digest", digest],
  ["frozen_manifest.configuration.name", "Changed input"],
  ["frozen_manifest.input_digest", digest],
  ["frozen_manifest.fee_scope", digest],
  ["frozen_manifest.trigger", "schedule"],
  ["frozen_manifest.scheduled_at", "2026-10-22T00:00:00Z"],
  ["frozen_manifest.trigger_event_id", other],
  ["frozen_manifest.formal_decisions_allowed", true],
  ["frozen_manifest.accepted_at", "2026-02-30T12:00:00Z"],
  ["frozen_manifest.actor_id", "member"],
  ["frozen_manifest.request_id", "request"],
  ["frozen_manifest.context.subject.package_id", other],
  ["frozen_manifest.context.selection.execution_input_id", other],
  ["frozen_manifest.context.review_input_digest", digest],
  ["frozen_manifest.context.model_input_digest", digest],
  ["frozen_manifest.context.limitations", []],
  ["frozen_manifest.context.overall_coverage", "complete"],
  ["frozen_manifest.context.formal_scoring_eligible", true],
  ["frozen_manifest.context.submission_eligible", true],
  ["frozen_manifest.package_review.operation_id", other],
  ["frozen_manifest.package_review.run_id", other],
  ["frozen_manifest.package_review.start_command_id", "command"],
  ["frozen_manifest.package_review.input_digest", digest],
  ["frozen_manifest.package_review.method_digest", digest],
  ["frozen_manifest.package_review.run_ref", "https://example.com"],
  ["frozen_manifest.extra", true],
  ["extra", true],
])("rejects an altered run ACK field %s", async (path, value) => {
  const { f, pendingRun, runScope } = taskPackageCommandFixture();
  await expect(
    validateRunACK(
      changed(f.queued.data, path as string, value),
      null,
      pendingRun,
      runScope,
    ),
  ).rejects.toThrow();
});

it.each([
  ["result.kind", "formal_score"],
  ["result.run_id", other],
  ["result.run_ref", "/wrong"],
  ["result.input_digest", digest],
  ["result.result_digest", "invalid"],
  ["result.overall_coverage", "complete"],
  ["result.formal_scoring_eligible", true],
  ["result.submission_eligible", true],
  ["result.extra", true],
  ["state", "queued"],
  ["error_code", "FAILED"],
])(
  "current GET preserves partial result and rejects %s",
  async (path, value) => {
    const { f, runScope } = taskPackageCommandFixture();
    await expect(
      validateCurrentRun(
        changed(f.completed.data, path as string, value),
        runScope.bidId,
        f.completed.data.id,
      ),
    ).rejects.toThrow();
  },
);

it("checks fee scope independently after a self-consistent changed input digest, and binds current GET to original frozen bytes", async () => {
  const { f, pendingRun, runScope } = taskPackageCommandFixture();
  const altered = changed(
    f.queued.data,
    "frozen_manifest.context.model_input_digest",
    digest,
  );
  const m = altered.frozen_manifest;
  m.input_digest = await jsonDigest({
    schema: "task-package-run/1",
    definition_version_id: m.definition_version_id,
    configuration_digest: m.configuration_digest,
    context: m.context,
  });
  await expect(
    validateRunACK(altered, null, pendingRun, runScope),
  ).rejects.toThrow();
  const later = changed(
    f.completed.data,
    "frozen_manifest.accepted_at",
    "2026-10-22T00:00:00Z",
  );
  await expect(
    validateCurrentRun(later, runScope.bidId, f.queued.data.id, f.queued.data),
  ).rejects.toThrow();
});

it("only current GET exposes reconciliation and does not let an unknown charge become a new ACK", async () => {
  const { f, pendingRun, runScope } = taskPackageCommandFixture();
  const unresolved = {
    ...f.queued.data,
    state: "reconciliation_required",
    error_code: "MODEL_CALL_REQUIRES_RECONCILIATION",
  };
  await expect(
    validateCurrentRun(
      unresolved,
      runScope.bidId,
      f.queued.data.id,
      f.queued.data,
    ),
  ).resolves.toBeDefined();
  await expect(
    validateRunACK(unresolved, null, pendingRun, runScope),
  ).rejects.toThrow();
});

it.each([0, 401, 403, 408, 429, 500, 503])(
  "keeps uncertain or authorization failure %i recoverable",
  (status) => {
    expect(
      definitiveTaskPackageFailure(
        new ApiError("failure", status, "REVISION_CONFLICT"),
      ),
    ).toBe(false);
  },
);
it("only clears well-defined business refusals, retaining incomplete commands and key conflicts", () => {
  expect(
    definitiveTaskPackageFailure(
      new ApiError("stale", 412, "REVISION_CONFLICT"),
    ),
  ).toBe(true);
  expect(
    definitiveTaskPackageFailure(
      new ApiError("paused", 409, "TASK_TEMPLATE_PAUSED"),
    ),
  ).toBe(true);
  for (const code of [
    "COMMAND_INCOMPLETE",
    "IDEMPOTENCY_CONFLICT",
    "REQUEST_FAILED",
  ])
    expect(
      definitiveTaskPackageFailure(new ApiError("unknown", 409, code)),
    ).toBe(false);
  expect(
    definitiveTaskPackageFailure(
      new ApiError("retry", 412, "REVISION_CONFLICT", undefined, true),
    ),
  ).toBe(false);
});
