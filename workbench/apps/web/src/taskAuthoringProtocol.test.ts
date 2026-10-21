import { expect, it } from "vitest";
import type { TaskAuthoringResult } from "./contracts";
import { taskChapterFixtures } from "./taskChapterFixtures.test-support";
import {
  readTaskAuthoringProposal,
  readTaskAuthoringResult,
} from "./taskAuthoringProtocol";

const fixtures = taskChapterFixtures();
it.each(Object.keys(fixtures) as (keyof typeof fixtures)[])(
  "accepts actual PG native publication response: %s",
  (name) => {
    const { run, proposal } = fixtures[name];
    const result = readTaskAuthoringResult(run, run.bid_id, run.id);
    expect(result.source_scope).toBe("legacy_section_and_source_versions");
    expect(result.automatic_apply).toBe(false);
    if (proposal)
      expect(
        readTaskAuthoringProposal(proposal, result, run.bid_id).action_id,
      ).toBe(result.action_id);
  },
);

it.each([
  "job_id",
  "job_input_digest",
  "operation_id",
  "writing_plan_id",
  "section_id",
  "base_section_revision",
  "job_ref",
  "action_ref",
  "source_scope",
  "automatic_apply",
  "candidate_digest",
  "publication_state",
] as const)("rejects a mismatched native task field: %s", (field) => {
  const run = structuredClone(fixtures.published.run);
  const result = run.result as unknown as Record<string, unknown>;
  result[field] =
    field === "base_section_revision"
      ? 999
      : field === "automatic_apply"
        ? true
        : "incorrect";
  expect(() => readTaskAuthoringResult(run, run.bid_id, run.id)).toThrow(
    /关联未通过核验/,
  );
});

it("requires publication before claiming success even when the native operation succeeded", () => {
  const record = structuredClone(fixtures["awaiting-publication"]);
  expect(record.operation.state).toBe("succeeded");
  expect(record.run.state).toBe("awaiting_publication");
  record.run.state = "succeeded";
  expect(() =>
    readTaskAuthoringResult(record.run, record.run.bid_id, record.run.id),
  ).toThrow();
});

it("supports already accepted legacy records without substituting current or latest inputs", () => {
  const run = structuredClone(fixtures.published.run);
  delete run.frozen_manifest.authoring_binding;
  expect(readTaskAuthoringResult(run, run.bid_id, run.id).job_id).toBe(
    run.frozen_manifest.assistant_job_id,
  );
});

it.each([
  "action_id",
  "job_id",
  "target_bid_id",
  "section_id",
  "base_section_revision",
] as const)("rejects another proposal identity: %s", (field) => {
  const record = structuredClone(fixtures.published);
  const value = record.proposal!;
  if (field === "section_id" || field === "base_section_revision") {
    if (value.preview.kind !== "authoring_patch")
      throw new Error("expected native fixture");
    if (field === "section_id") value.preview.section_id = "unrelated-section";
    else value.preview.base_section_revision++;
  } else value[field] = "unrelated";
  expect(() =>
    readTaskAuthoringProposal(
      value,
      record.run.result as TaskAuthoringResult,
      record.run.bid_id,
    ),
  ).toThrow(/不一致/);
});
