import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  authoringContextFixture,
  contextChoicePage,
  contextId,
  contextTarget,
  sealAuthoringContext,
} from "../qa-previews/frozen-inputs/workContextAuthoring";
import { validateAuthoringWorkContext } from "./workContextAuthoringProtocol";
import {
  validateWorkContextChoices,
  validateWorkContextRelations,
} from "./workContextDirectoryProtocol";
import { jsonDigest } from "./editorSchema";
import type { AuthoringWorkContext } from "./contracts";

let f: Awaited<ReturnType<typeof authoringContextFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await authoringContextFixture();
});
afterEach(() => vi.unstubAllGlobals());
it("retains full saved sections, merged tables, outline and real per-format output state", async () => {
  expect(
    await validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).toEqual(f.saved);
  expect(
    await validateAuthoringWorkContext(f.built, f.bid, contextTarget(f.built)),
  ).toEqual(f.built);
  expect(f.built.build?.outputs[1]).toMatchObject({
    state: "failed",
    document: null,
  });
});
it("supports a native saved snapshot with no remaining active chapters", async () => {
  f.saved.document!.sections = [];
  f.saved.document!.outline = [];
  f.saved.snapshot.section_count = 0;
  await sealAuthoringContext(f.saved);
  await expect(
    validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).resolves.toBe(f.saved);
});
it("preserves sparse legacy body ordinals separately from the saved display order", async () => {
  f.saved.document!.outline = null;
  for (const [index, section] of f.saved.document!.sections.entries()) {
    section.content.attrs.ordinal = index * 3 + 7;
    section.digest = await jsonDigest(section.content);
  }
  await sealAuthoringContext(f.saved);
  await expect(
    validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).resolves.toBe(f.saved);
  expect(f.saved.document!.sections[0].ordinal).toBe(0);
  expect(f.saved.document!.sections[0].content.attrs.ordinal).toBe(7);
  f.saved.document!.sections[0].content.attrs.ordinal = 500;
  f.saved.document!.sections[0].digest = await jsonDigest(
    f.saved.document!.sections[0].content,
  );
  await sealAuthoringContext(f.saved);
  await expect(
    validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).rejects.toThrow();
});
it.each([
  (c: AuthoringWorkContext) => {
    c.document!.sections[0].content.attrs.title = "a different body";
  },
  (c: AuthoringWorkContext) => {
    c.document!.sections[0].section_id = c.document!.sections[1].section_id;
  },
  (c: AuthoringWorkContext) => {
    c.document!.outline![0].parent_id = c.document!.outline![1].section_id;
  },
  (c: AuthoringWorkContext) => {
    c.native_targets.current_draft.draft_id = contextId(999);
  },
  (c: AuthoringWorkContext) => {
    Object.assign(c.summary, { whole_package_passed: true });
  },
  (c: AuthoringWorkContext) => {
    Object.assign(c.summary.formal_scoring, { numeric_prediction: 0 });
  },
  (c: AuthoringWorkContext) => {
    Object.assign(c.document!.sections[0].content, { html: "lost attrs" });
  },
])(
  "rejects corrupt history or invented qualification even if the outer digest is resealed %#",
  async (alter) => {
    alter(f.saved);
    await sealAuthoringContext(f.saved);
    await expect(
      validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
    ).rejects.toThrow();
  },
);
it("requires each displayed image to match the exact recorded asset version", async () => {
  const section = f.saved.document!.sections[0];
  section.content.content.push({
    type: "image",
    attrs: {
      id: "historic-image",
      asset_id: contextId(201),
      asset_revision: 3,
      asset_version_id: contextId(202),
      width_twips: 1500,
      height_twips: 1200,
      alt: "合成历史图片",
      caption: "原图版本",
    },
  });
  f.saved.document!.images = [
    {
      asset_id: contextId(201),
      asset_revision: 3,
      asset_version_id: contextId(202),
      version_digest: "c".repeat(64),
      normalized_sha256: "d".repeat(64),
      media_type: "image/png",
    },
  ];
  section.digest = await jsonDigest(section.content);
  await sealAuthoringContext(f.saved);
  await expect(
    validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).resolves.toBe(f.saved);
  f.saved.document!.images[0].asset_revision = 4;
  await sealAuthoringContext(f.saved);
  await expect(
    validateAuthoringWorkContext(f.saved, f.bid, contextTarget(f.saved)),
  ).rejects.toThrow();
});
it("rejects a file advertised as published after a failed build", async () => {
  f.built.build!.operation_state = "failed";
  await sealAuthoringContext(f.built);
  await expect(
    validateAuthoringWorkContext(f.built, f.bid, contextTarget(f.built)),
  ).rejects.toThrow();
});
it("requires exact record identity and a closed discovery response", async () => {
  const page = await contextChoicePage(
    [f.saved.selection],
    "draft_snapshot",
    f.bid,
  );
  await expect(
    validateWorkContextChoices(page, f.bid, "draft_snapshot"),
  ).resolves.toBe(page);
  await expect(
    validateWorkContextChoices(page, contextId(999), "draft_snapshot"),
  ).rejects.toThrow();
  page.items[0].selection_digest = "f".repeat(64);
  await expect(
    validateWorkContextChoices(page, f.bid, "draft_snapshot"),
  ).rejects.toThrow();
});
it("rejects repeated identities, filtered data relabelled as unfiltered, and qualification claims", async () => {
  const page = await contextChoicePage(
    [f.saved.selection],
    "draft_snapshot",
    f.bid,
  );
  await expect(
    validateWorkContextChoices(
      { ...page, items: [...page.items, ...page.items], total: 2 },
      f.bid,
      "draft_snapshot",
    ),
  ).rejects.toThrow();
  await expect(
    validateWorkContextChoices(
      {
        ...page,
        filters: { ...page.filters, draft_id: f.saved.selection.draft_id },
      },
      f.bid,
      "draft_snapshot",
    ),
  ).rejects.toThrow();
  await expect(
    validateWorkContextChoices(
      { ...page, qualification_assessed: true },
      f.bid,
      "draft_snapshot",
    ),
  ).rejects.toThrow();
});
it("keeps proven adoption distinct from mere output membership", async () => {
  if (f.built.selection.kind !== "build") throw new Error("fixture");
  await expect(
    validateWorkContextRelations(
      f.relations,
      f.built.selection,
      f.built.build!.outputs,
    ),
  ).resolves.toBe(f.relations);
  f.relations.items[0].kind = "contains_output";
  await expect(
    validateWorkContextRelations(
      f.relations,
      f.built.selection,
      f.built.build!.outputs,
    ),
  ).rejects.toThrow();
  f.relations.items[0].adoption_command_id = null;
  f.relations.items[0].adopted_at = null;
  await expect(
    validateWorkContextRelations(
      f.relations,
      f.built.selection,
      f.built.build!.outputs,
    ),
  ).resolves.toBe(f.relations);
  f.relations.seed.snapshot_id = contextId(999);
  await expect(
    validateWorkContextRelations(
      f.relations,
      f.built.selection,
      f.built.build!.outputs,
    ),
  ).rejects.toThrow();
});

it.each(["failed-format", "foreign-version", "foreign-bytes"])(
  "does not invent an input/output relationship from a valid build seed: %s",
  async (kind) => {
    if (f.built.selection.kind !== "build") throw new Error("fixture");
    const output = f.relations.items[0].output;
    if (kind === "failed-format") output.format = "pdf";
    else if (kind === "foreign-version")
      output.document_version_id = contextId(999);
    else output.sha256 = "7".repeat(64);
    await expect(
      validateWorkContextRelations(
        f.relations,
        f.built.selection,
        f.built.build!.outputs,
      ),
    ).rejects.toThrow();
  },
);
