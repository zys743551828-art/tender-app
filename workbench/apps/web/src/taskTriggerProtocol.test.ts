import { expect, it } from "vitest";
import { packageTaskTriggerCapability } from "./packageTaskTemplateSelection";
import { taskTriggerFixtures } from "./taskTriggerFixtures.test-support";
import {
  normalizeTaskPackageRequest,
  taskTriggerIntentEtag,
  validateCurrentRun,
  validateTaskPackagePending,
  validateTaskPackageTemplate,
  validateTaskTriggerCancelACK,
  validateTaskTriggerIntent,
  validateTaskTriggerPage,
  type PendingTaskPackageCommand,
  type TaskPackageScope,
} from "./taskPackageProtocol";
import { isExactPackageTask, claimsExactPackageRun } from "./taskState";

const f = taskTriggerFixtures();
const actor = String(f["event-succeeded-run"].data.frozen_manifest.actor_id);

it.each(["event-template", "schedule-template"] as const)(
  "validates the real automatic template %s without changing manual defaults or creating a manual run request",
  async (name) => {
    const row = f[name];
    const item = await validateTaskPackageTemplate(
      row.data,
      row.headers.etag,
      row.data.bid_id,
    );
    expect(isExactPackageTask(item.configuration)).toBe(true);
    expect(item.configuration.source_selection.mode).toBe(
      "exact_package_trigger",
    );
    expect(() =>
      validateTaskPackagePending(
        {
          path: `/bids/${item.bid_id}/task-definitions/${item.id}/runs`,
          method: "POST",
          body: { rerun: false },
          etag: row.headers.etag,
          key: crypto.randomUUID(),
          expected: { kind: "run", template: item },
        },
        { kind: "run", bidId: item.bid_id, memberId: actor, identity: item.id },
      ),
    ).toThrow();
  },
);

it("keeps both explicit mode checks: auto needs an explicit trigger and old exact mode remains manual only", () => {
  const config = structuredClone(f["event-template"].data.configuration);
  expect(() =>
    normalizeTaskPackageRequest({ ...config, trigger: undefined }),
  ).toThrow();
  expect(() =>
    normalizeTaskPackageRequest({ ...config, trigger: { mode: "manual" } }),
  ).toThrow();
  expect(() =>
    normalizeTaskPackageRequest({
      ...config,
      source_selection: {
        ...config.source_selection,
        mode: "exact_package_review",
      },
    }),
  ).toThrow();
  expect(() =>
    normalizeTaskPackageRequest({
      ...config,
      source_selection: { mode: "current_project", version_ids: [] },
    }),
  ).toThrow();
});

it("validates actual event intent, reuse, blocked and native completion without claiming the opaque server digest was recomputed", async () => {
  const pending = f["event-pending"].data;
  const accepted = validateTaskTriggerIntent(
    f["event-accepted"].data,
    pending.bid_id,
    pending.id,
    pending,
  );
  expect(taskTriggerIntentEtag(pending)).toBe(f["event-pending"].headers.etag);
  expect(accepted.state).toBe("accepted");
  const page = validateTaskTriggerPage(f["event-intents"].data, pending.bid_id);
  expect(page.items).toHaveLength(2);
  expect(page.items[1].reused).toBe(true);
  for (const name of [
    "blocked-template",
    "blocked-pause",
    "blocked-close",
    "blocked-source",
    "blocked-event",
  ] as const) {
    const row = f[name].data;
    expect(validateTaskTriggerIntent(row, row.bid_id, row.id).state).toBe(
      "blocked",
    );
  }
  const run = f["event-succeeded-run"].data;
  expect(claimsExactPackageRun(run)).toBe(true);
  expect(
    (await validateCurrentRun(run, run.bid_id, run.id)).frozen_manifest
      .trigger_intent_id,
  ).toBe(pending.id);
});

it("rejects identity changes and hidden manual fallbacks in an automatic task", async () => {
  const pending = f["event-pending"].data;
  expect(() =>
    validateTaskTriggerIntent(
      { ...pending, bid_id: crypto.randomUUID() },
      pending.bid_id,
      pending.id,
    ),
  ).toThrow();
  expect(() =>
    validateTaskTriggerIntent(
      {
        ...pending,
        selection: { ...pending.selection, revision_id: crypto.randomUUID() },
      },
      pending.bid_id,
      pending.id,
      pending,
    ),
  ).toThrow();
  const accepted = f["event-accepted"].data;
  expect(() =>
    validateTaskTriggerIntent(
      { ...accepted, run_ref: "/api/v1/bids/other/task-runs/other" },
      pending.bid_id,
      pending.id,
    ),
  ).toThrow();
  expect(() =>
    validateTaskTriggerIntent(pending, pending.bid_id, pending.id, accepted),
  ).toThrow();
  const run = structuredClone(f["event-succeeded-run"].data);
  run.frozen_manifest.trigger = "manual";
  await expect(validateCurrentRun(run, run.bid_id, run.id)).rejects.toThrow();
  expect(() =>
    validateTaskTriggerPage(
      { ...f["event-intents"].data, next_after: crypto.randomUUID() },
      pending.bid_id,
    ),
  ).toThrow();
});

it("binds a real cancel ACK to the original pending intent, exact ETag and allowed endpoint", async () => {
  const intent = f["cancel-pending"].data,
    receipt = f.cancelled;
  const scope: TaskPackageScope<"trigger_cancel"> = {
    kind: "trigger_cancel",
    bidId: intent.bid_id,
    memberId: actor,
    identity: intent.id,
  };
  const pending: PendingTaskPackageCommand = {
    path: receipt.request.path.replace(/^\/api\/v1/, ""),
    method: "POST",
    body: receipt.request.body as { reason: string },
    etag: receipt.request.headers!["if-match"],
    key: receipt.request.headers!["idempotency-key"],
    expected: { kind: "trigger_cancel", intent },
  };
  expect(
    await validateTaskTriggerCancelACK(receipt.data, null, pending, scope),
  ).toEqual(receipt.data);
  expect(() =>
    validateTaskPackagePending(
      {
        ...pending,
        path: pending.path.replace(intent.id, crypto.randomUUID()),
      },
      scope,
    ),
  ).toThrow();
  expect(() =>
    validateTaskPackagePending({ ...pending, etag: '"other"' }, scope),
  ).toThrow();
  expect(() =>
    validateTaskPackagePending(
      {
        ...pending,
        expected: { kind: "trigger_cancel", intent: receipt.data },
      },
      scope,
    ),
  ).toThrow();
  await expect(
    validateTaskTriggerCancelACK(
      { ...receipt.data, state: "pending", error_code: null },
      null,
      pending,
      scope,
    ),
  ).rejects.toThrow();
});

it("requires the server's explicit bounded automatic capability", () => {
  const kinds = structuredClone(f["task-kinds"].data);
  expect(packageTaskTriggerCapability(kinds)?.available).toBe(true);
  kinds.items[0].exact_package_triggers!.automatic_input_selection =
    true as false;
  expect(() => packageTaskTriggerCapability(kinds)).toThrow();
});
