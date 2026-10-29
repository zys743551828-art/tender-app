import { expect, it } from "vitest";
import {
  packageAuthoringCommandFixture,
  packageAuthoringFixture,
} from "./packageAuthoringFixtures.test-support";
import {
  validateAuthoringInput,
  validateAuthoringInputPage,
  validateAuthoringPublicContext,
  packageAuthoringCapability,
} from "./packageAuthoringInputProtocol";
import {
  claimsPackageAuthoringRun,
  readPackageAuthoringProposal,
  validatePackageAuthoringRun,
  validatePackageAuthoringRunACK,
  validatePackageAuthoringTemplate,
  validatePackageAuthoringTemplateACK,
} from "./taskPackageAuthoringProtocol";
import { claimsExactPackageRun } from "./taskState";
import { jsonDigest } from "./editorSchema";
import { verifyTaskPackagePending } from "./taskPackageProtocol";

const other = "00000000-0000-4000-8000-000000009999";
it("reads the original native saved input, public context and distinct B1/B2 capability without rewriting digests", async () => {
  const f = packageAuthoringFixture(),
    bidId = f.template.bid_id;
  const input = await validateAuthoringInput(f.input, bidId);
  expect(await validateAuthoringInputPage(f.input_page, bidId)).toMatchObject({
    items: [input],
  });
  expect(validateAuthoringPublicContext(f.context, input)).toEqual(f.context);
  expect(input.manifest.generation_available).toBe(false);
  expect(packageAuthoringCapability(f.kinds)).toMatchObject({
    available: true,
    automatic_input_selection: false,
    apply_available: false,
    build_available: false,
  });
  expect(
    await validatePackageAuthoringTemplate(f.template, f.template_etag, bidId),
  ).toEqual(f.template);
});
it.each([
  "queued",
  "awaiting-publication",
  "published",
  "unknown-fee",
  "cancelled-before",
  "cancelled-during_http",
] as const)(
  "validates unmodified native %s task projection separately from legacy and package review",
  async (state) => {
    const f = packageAuthoringFixture(),
      run = f.runs[state];
    expect(claimsPackageAuthoringRun(run)).toBe(true);
    expect(claimsExactPackageRun(run)).toBe(false);
    expect(await validatePackageAuthoringRun(run, run.bid_id, run.id)).toEqual(
      run,
    );
  },
);
it("checks the complete proposal, original section and frozen input relationship", async () => {
  const f = packageAuthoringFixture(),
    run = f.runs.published;
  const verified = await validatePackageAuthoringRun(run, run.bid_id, run.id);
  expect(
    readPackageAuthoringProposal(f.proposal, run.bid_id, verified.result),
  ).toEqual(f.proposal);
  const changed = structuredClone(f.proposal);
  changed.job_id = other;
  expect(() =>
    readPackageAuthoringProposal(changed, run.bid_id, verified.result),
  ).toThrow();
});
it.each(["bid", "digest", "section", "scope", "declaration"])(
  "rejects a native input with changed %s, including a newly computed outer digest",
  async (field) => {
    const f = packageAuthoringFixture(),
      value = structuredClone(f.input),
      m = value.manifest;
    if (field === "bid") m.bid_id = other;
    if (field === "digest") value.digest = "f".repeat(64);
    if (field === "section")
      (
        m.selection as { target_section: { base_section_revision: number } }
      ).target_section.base_section_revision = 0;
    if (field === "scope")
      (m.scope as { bidder_status: string }).bidder_status = "unconfirmed";
    if (field === "declaration")
      (
        m.fact_declarations as { manifest: { fact_id: string } }[]
      )[0].manifest.fact_id = other;
    if (field !== "digest") value.digest = await jsonDigest(m);
    await expect(
      validateAuthoringInput(value, f.template.bid_id),
    ).rejects.toThrow();
  },
);
it.each([
  "cross-input",
  "config-digest",
  "job",
  "apply",
  "publication",
  "external-link",
  "legacy",
])("refuses wrong or downgraded %s run data", async (field) => {
  const f = packageAuthoringFixture(),
    run = await validatePackageAuthoringRun(
      f.runs.published,
      f.template.bid_id,
      f.runs.published.id,
    );
  const changed = structuredClone(run);
  if (field === "cross-input") changed.result.authoring_input_id = other;
  if (field === "config-digest")
    changed.frozen_manifest.configuration_digest = "f".repeat(64);
  if (field === "job") changed.result.job_id = other;
  if (field === "apply")
    Object.assign(changed.result, { apply_available: true });
  if (field === "publication") changed.state = "queued";
  if (field === "external-link")
    changed.result.action_ref = "https://invalid.example/action";
  if (field === "legacy")
    Object.assign(changed.frozen_manifest, { schema: "task-run/1" });
  await expect(
    validatePackageAuthoringRun(changed, changed.bid_id, changed.id),
  ).rejects.toThrow();
});
it("validates exact stored request and complete template/run acknowledgements", async () => {
  const { f, create, createScope, run, runScope } =
    packageAuthoringCommandFixture();
  const createPending = { ...create, key: other },
    runPending = { ...run, key: other };
  expect(await verifyTaskPackagePending(createPending, createScope)).toEqual(
    createPending,
  );
  expect(
    await validatePackageAuthoringTemplateACK(
      f.template,
      f.template_etag,
      createPending,
      createScope,
    ),
  ).toEqual(f.template);
  expect(
    await validatePackageAuthoringRunACK(
      f.runs.queued,
      null,
      runPending,
      runScope,
    ),
  ).toEqual(f.runs.queued);
  const wrong = structuredClone(f.template);
  wrong.configuration.instructions += " changed";
  await expect(
    validatePackageAuthoringTemplateACK(
      wrong,
      f.template_etag,
      createPending,
      createScope,
    ),
  ).rejects.toThrow();
});
it("rejects duplicate directory records, looping cursors and foreign public context without pretending to hash redacted private bytes", async () => {
  const f = packageAuthoringFixture(),
    input = await validateAuthoringInput(f.input, f.template.bid_id);
  await expect(
    validateAuthoringInputPage(
      { items: [f.input, f.input], has_more: false, next_cursor: null },
      f.template.bid_id,
    ),
  ).rejects.toThrow();
  await expect(
    validateAuthoringInputPage(
      { items: [f.input], has_more: true, next_cursor: "same" },
      f.template.bid_id,
      [],
      "same",
    ),
  ).rejects.toThrow();
  const changed = structuredClone(f.context);
  changed.input_id = other;
  expect(() => validateAuthoringPublicContext(changed, input)).toThrow();
});
