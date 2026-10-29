import { beforeEach, expect, it, vi } from "vitest";
import {
  sealContext,
  workContextFixture,
} from "../qa-previews/frozen-inputs/workContext";
import {
  parseWorkContextLocation,
  workContextLocation,
} from "./workContextNavigation";
import { validatePackageWorkContext } from "./workContextProtocol";

let f: Awaited<ReturnType<typeof workContextFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await workContextFixture();
});
it("validates exact immutable selection, observation and bounded native counts", async () => {
  expect(
    await validatePackageWorkContext(f.context, f.props.scope.bidId, f.target),
  ).toBe(f.context);
  const route = workContextLocation(f.props.scope.bidId, {
    stage: f.target.kind,
    selected: f.target,
  });
  expect(parseWorkContextLocation(f.props.scope.bidId, route)).toEqual({
    ok: true,
    position: { stage: f.target.kind, selected: f.target },
  });
});
it.each([
  "identity",
  "native_target",
  "counts",
  "human_counts",
  "formal_score",
  "whole_package_risks",
  "whole_package_pass",
  "later_result",
  "unexpected_url",
])("rejects resealed but invalid summary semantics: %s", async (mutation) => {
  const value = structuredClone(f.context);
  if (mutation === "identity")
    value.identity = {
      ...value.identity,
      identity_version: "bid-identity/2",
      lot_id: null,
    };
  else if (mutation === "native_target")
    value.native_targets.package_revision.revision_id =
      "00000000-0000-0000-0000-999999999999";
  else if (mutation === "counts")
    value.summary.review!.machine_counts.violated += 1;
  else if (mutation === "human_counts")
    value.summary.review!.human_counts.confirmed += 1;
  else if (mutation === "formal_score")
    Object.assign(value.summary.formal_scoring, { numeric_prediction: 0 });
  else if (mutation === "whole_package_risks")
    Object.assign(value.summary, { whole_package_blocking_risk_count: 0 });
  else if (mutation === "whole_package_pass")
    Object.assign(value.summary, { whole_package_passed: true });
  else if (mutation === "later_result")
    value.summary.review!.result_digest = "f".repeat(64);
  else Object.assign(value.native_targets, { url: "https://foreign.invalid" });
  await sealContext(value);
  await expect(
    validatePackageWorkContext(value, f.props.scope.bidId, f.target),
  ).rejects.toThrow(/不能一致核验/);
});
it("rejects changed digest, foreign project and another fixed selection", async () => {
  const changed = structuredClone(f.context);
  changed.current_observation.sources.status = "changed";
  await expect(
    validatePackageWorkContext(changed, f.props.scope.bidId, f.target),
  ).rejects.toThrow();
  await expect(
    validatePackageWorkContext(
      f.context,
      "00000000-0000-0000-0000-999999999999",
      f.target,
    ),
  ).rejects.toThrow();
  await expect(
    validatePackageWorkContext(f.context, f.props.scope.bidId, {
      ...f.target,
      selectionDigest: "f".repeat(64),
    }),
  ).rejects.toThrow();
});
it("keeps an explicitly bound missing submission result missing", async () => {
  const value = structuredClone(f.context),
    run = value.selection;
  if (run.kind !== "package_review_run") throw new Error("fixture");
  value.selection = {
    kind: "package_submission",
    bid_id: run.bid_id,
    package_id: run.package_id,
    revision_id: run.revision_id,
    package_digest: run.package_digest,
    submission_id: "00000000-0000-0000-0000-000000009001",
    package_binding_digest: "c".repeat(64),
    inventory: { id: run.inventory_id, digest: run.inventory_digest },
    review_run: { ...run, result_digest: null },
  };
  value.state = {
    kind: "package_submission",
    registration_kind: "offline_fact",
    submitted_at: value.observed_at,
    recorded_at: value.observed_at,
    supersedes_id: null,
    gate_checked_at_registration: false,
    platform_submission_verified: false,
    pre_submission_system_check_verified: false,
  };
  value.summary = {
    ...value.summary,
    perspective: "submission_history",
    review_status: "bound_result_missing",
    review: null,
    primary_action: "open_selected_submission",
  };
  value.native_targets.package_review_run!.result_digest = null;
  value.native_targets.package_submission = {
    kind: "package_submission",
    bid_id: run.bid_id,
    submission_id: value.selection.submission_id,
    package_binding_digest: value.selection.package_binding_digest,
  };
  await sealContext(value);
  const target = {
    kind: "package_submission" as const,
    id: value.selection.submission_id,
    selectionDigest: value.selection_digest,
  };
  expect(await validatePackageWorkContext(value, run.bid_id, target)).toBe(
    value,
  );
  value.summary.review = f.context.summary.review;
  value.summary.review_status = "result_available";
  await sealContext(value);
  await expect(
    validatePackageWorkContext(value, run.bid_id, target),
  ).rejects.toThrow();
});
it.each([
  "stage=build&id=latest",
  "stage=build&id=x&selection=x",
  "stage=build&stage=build",
  "stage=build&current=true",
  "id=00000000-0000-0000-0000-000000000001",
  "stage=build?ignored=true",
])("rejects ambiguous deep links: %s", (query) => {
  expect(
    parseWorkContextLocation(
      f.props.scope.bidId,
      `/bids/${f.props.scope.bidId}/work-context?${query}`,
    ).ok,
  ).toBe(false);
});
