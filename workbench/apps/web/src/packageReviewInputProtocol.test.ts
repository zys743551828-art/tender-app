import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import { validatePackageReviewInputView } from "./packageReviewInputProtocol";
let f: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.unstubAllGlobals();
});
it("validates the retained input without requiring current actor or model configuration", async () => {
  const p = { ...f.props, scope: { ...f.props.scope, memberId: id(901) } };
  await expect(
    validatePackageReviewInputView(f.input, p, f.run),
  ).resolves.toEqual(f.input);
});
it.each(["execution", "plan", "frozen", "method", "qualification"])(
  "rejects a correctly rehashed input with changed %s binding",
  async (field) => {
    const input = structuredClone(f.input),
      run = structuredClone(f.run);
    if (field === "execution")
      input.manifest.execution_input.identity.rerun = {
        nonce: id(902),
        reason: "其他复检",
      };
    if (field === "plan") input.manifest.dependency_plan.id = id(902);
    if (field === "frozen")
      input.manifest.frozen_input.evidence_digest = "a".repeat(64);
    if (field === "method")
      input.manifest.executor_method.profile.batch_limit = 5 as 4;
    if (field === "qualification")
      input.manifest.executor_method.profile.submission_eligible =
        true as false;
    input.manifest.executor_method.digest = await frozenManifestDigest(
      input.manifest.executor_method.profile,
    );
    run.method_digest = input.manifest.executor_method.digest;
    input.digest = await frozenManifestDigest(input.manifest);
    run.input_digest = input.digest;
    await expect(
      validatePackageReviewInputView(input, f.props, run),
    ).rejects.toThrow(/执行依据/);
  },
);
it("rejects duplicate fact identities even when their declaration IDs and envelope digest differ", async () => {
  const input = structuredClone(f.input),
    run = structuredClone(f.run);
  input.manifest.fact_admission.fact_declarations = [1, 2].map((n) => ({
    fact_id: id(901),
    declaration_id: id(910 + n),
    declaration_digest: String(n).repeat(64),
  }));
  input.digest = await frozenManifestDigest(input.manifest);
  run.input_digest = input.digest;
  await expect(
    validatePackageReviewInputView(input, f.props, run),
  ).rejects.toThrow(/执行依据/);
});
it("rejects altered historical contents and a mismatched frozen scope", async () => {
  const changed = structuredClone(f.input);
  changed.manifest.model_input_digest = "f".repeat(64);
  await expect(
    validatePackageReviewInputView(changed, f.props, f.run),
  ).rejects.toThrow(/执行依据/);
  await expect(
    validatePackageReviewInputView(
      f.input,
      { ...f.props, scope: { ...f.props.scope, bidId: id(930) } },
      f.run,
    ),
  ).rejects.toThrow(/执行依据/);
});
