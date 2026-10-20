import { beforeEach, expect, it, vi } from "vitest";
import {
  dependencyPlanAssessment,
  dependencyPlanFixture,
  dependencyPlanPage,
  dependencyPlanReply,
} from "../qa-previews/frozen-inputs/dependencyPlan";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import {
  dependencyPlanScope,
  validPlanBody,
  validPlanPage,
  validatePlan,
} from "./dependencyPlanProtocol";
import {
  dependencyPlanStorageKey,
  loadDependencyPlanRecord,
  storeDependencyPlanRecord,
} from "./dependencyPlanRecovery";
import { frozenManifestDigest } from "./packageFrozenInput";

beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
});
async function fixture() {
  const f = await dependencyPlanFixture();
  const request = {
    execution_input_digest: f.props.prepared.digest,
    purpose: "prebid_compliance" as const,
    fact_ids: [id(51)],
    dependencies: [],
  };
  const assessment = await dependencyPlanAssessment(f, request);
  const body = {
    ...request,
    assessment_digest: assessment.digest,
    reason: "保存本轮明确人工计划",
  };
  const pending = { key: id(97), body };
  return { f, pending, value: await dependencyPlanReply(f, body) };
}
it("binds the original full request and original private usage digest without qualifying it", async () => {
  const { f, pending, value } = await fixture();
  expect(validPlanBody(pending.body, f.props)).toBe(true);
  await expect(validatePlan(value, f.props, pending)).resolves.toBeUndefined();
  await expect(validatePlan(value, f.props)).resolves.toBeUndefined();
  expect(value.manifest.assessment.manifest.required_facts_assessment).toBe(
    "unknown",
  );
  expect(value.manifest.launch_available).toBe(false);
});
it.each([
  "facts_qualified",
  "inventory_complete",
  "review_ready",
  "launch_available",
  "publication_authorized",
] as const)("rejects resealed %s authority", async (key) => {
  const { f, pending, value } = await fixture();
  Object.assign(value.manifest, { [key]: true });
  value.digest = await frozenManifestDigest(value.manifest);
  await expect(validatePlan(value, f.props, pending)).rejects.toThrow();
});
it("rejects a same-scope ACK for a different complete body", async () => {
  const { f, pending, value } = await fixture();
  pending.body.reason = "另一笔明确意图";
  await expect(validatePlan(value, f.props, pending)).rejects.toThrow();
});
it.each(["prepared", "assessment", "usage", "identity"])(
  "rejects resealed changed %s proof",
  async (kind) => {
    const { f, pending, value } = await fixture();
    if (kind === "prepared")
      value.manifest.prepared.execution_input_id = id(99);
    if (kind === "assessment")
      value.manifest.assessment.digest = "a".repeat(64);
    if (kind === "usage")
      value.manifest.usage.manifest.selected[0].fact_item_digest = "a".repeat(
        64,
      );
    if (kind === "identity")
      value.manifest.usage.manifest.identity_digest = "a".repeat(64);
    value.digest = await frozenManifestDigest(value.manifest);
    await expect(validatePlan(value, f.props, pending)).rejects.toThrow();
  },
);
it("reads a saved policy as recorded rather than replacing it with a current policy", async () => {
  const { f, value } = await fixture();
  value.manifest.assessment.manifest.policy_digest = "1".repeat(64);
  value.manifest.assessment.digest = await frozenManifestDigest(
    value.manifest.assessment.manifest,
  );
  value.digest = await frozenManifestDigest(value.manifest);
  await expect(validatePlan(value, f.props)).resolves.toBeUndefined();
});
it("checks bounded ordered history and exact prepared binding", async () => {
  const { f, value } = await fixture();
  const page = dependencyPlanPage(f, [value]);
  const scope = dependencyPlanScope(f.props);
  expect(validPlanPage(page, scope)).toBe(true);
  page.items.push(page.items[0]);
  expect(validPlanPage(page, scope)).toBe(false);
  expect(
    validPlanPage(dependencyPlanPage(f, [value]), {
      ...scope,
      preparedId: id(99),
    }),
  ).toBe(false);
});
it("keeps pending complete intent across reload and refuses malformed or cross-scope recovery", async () => {
  const { f, pending } = await fixture();
  const scope = dependencyPlanScope(f.props);
  const record = { version: 1 as const, scope, pending, lastId: null };
  storeDependencyPlanRecord(record);
  expect(loadDependencyPlanRecord(f.props)).toEqual(record);
  const key = dependencyPlanStorageKey(scope);
  sessionStorage.setItem(
    key,
    JSON.stringify({ ...record, scope: { ...scope, memberId: id(99) } }),
  );
  expect(() => loadDependencyPlanRecord(f.props)).toThrow();
  expect(sessionStorage.getItem(key)).not.toBeNull();
});
it("rejects added private usage and malformed save selection before transport", async () => {
  const { f, pending } = await fixture();
  expect(
    validPlanBody({ ...pending.body, usage_digest: "a".repeat(64) }, f.props),
  ).toBe(false);
  expect(
    validPlanBody({ ...pending.body, fact_ids: [id(51), id(51)] }, f.props),
  ).toBe(false);
});
