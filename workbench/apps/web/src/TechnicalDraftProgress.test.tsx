import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type {
  AuthoringTreeView,
  AuthoringWorkContext,
  WorkContextReadOnlyAuthoringRichDocument,
} from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { jsonDigest } from "./editorSchema";
import { TechnicalDraftProgress } from "./TechnicalDraftProgress.tsx";
import { chapterBodyState } from "./technicalDraftProgress.ts";

const f = captureFixture();
const ids = [
  "fdc9d5ef-e6bf-4747-9e7d-27a9f907c1cc",
  "fdc9d5ef-e6bf-4747-9e7d-27a9f907c1cd",
  "fdc9d5ef-e6bf-4747-9e7d-27a9f907c1ce",
  "fdc9d5ef-e6bf-4747-9e7d-27a9f907c1cf",
];
const titles = [
  "合成已写进度章",
  "合成仅标题章",
  "合成空白质量章",
  "合成表格章",
];

function paragraph(
  text?: string,
): WorkContextReadOnlyAuthoringRichDocument["content"][number] {
  return {
    type: "paragraph",
    attrs: { id: crypto.randomUUID() },
    content: text ? [{ type: "text", text }] : [],
  };
}
function sectionContent(
  ordinal: number,
  content: WorkContextReadOnlyAuthoringRichDocument["content"],
): WorkContextReadOnlyAuthoringRichDocument {
  return {
    type: "doc",
    attrs: { title: titles[ordinal], ordinal, rule_ids: [], source_refs: [] },
    content,
  };
}
async function observationDigest(view: AuthoringWorkContext) {
  const observable: Partial<AuthoringWorkContext> = { ...view };
  delete observable.observed_at;
  delete observable.observation_digest;
  return jsonDigest(observable);
}
async function observed() {
  const view = structuredClone(f.snapshot);
  if (view.selection.kind !== "draft_snapshot" || !view.document)
    throw new Error("missing native fixture");
  const raw = view.document.sections[0];
  const texts = [
    sectionContent(0, [paragraph("施工进度仍待人工核对")]),
    sectionContent(1, [
      {
        type: "heading",
        attrs: { id: crypto.randomUUID(), level: 2 },
        content: [{ type: "text", text: "检查小标题" }],
      },
    ]),
    sectionContent(2, [paragraph("\u00a0\u200b\u3000")]),
  ];
  view.document.sections = await Promise.all(
    texts.map(async (content, ordinal) => ({
      ...raw,
      section_id: ids[ordinal],
      section_revision_id: crypto.randomUUID(),
      section_revision: ordinal + 1,
      title: titles[ordinal],
      ordinal,
      content,
      digest: await jsonDigest(content),
    })),
  );
  view.document.outline = view.document.sections.map((section) => ({
    section_id: section.section_id,
    parent_id: null,
    ordinal: section.ordinal,
    node_type: "chapter",
  }));
  view.snapshot.section_count = texts.length;
  view.selection.snapshot_digest = await jsonDigest({
    draft_id: view.selection.draft_id,
    revision: view.selection.draft_revision,
    title: view.snapshot.title,
    sections: view.document.sections.map(
      ({
        section_id,
        section_revision_id,
        section_revision,
        digest,
        ordinal,
      }) => ({
        id: section_id,
        revision_id: section_revision_id,
        revision: section_revision,
        digest,
        ordinal,
      }),
    ),
  });
  view.snapshot.snapshot_digest = view.selection.snapshot_digest;
  view.native_targets.draft_snapshot = { ...view.selection };
  view.selection_digest = await jsonDigest(view.selection);
  const digest = await jsonDigest({
    revision: view.selection.draft_revision,
    snapshot_id: view.selection.snapshot_id,
    snapshot_digest: view.selection.snapshot_digest,
  });
  view.current_observation.draft_head = {
    status: "matched",
    selected_digest: digest,
    observed_digest: digest,
    reason: "EXACT_VALUE_MATCH",
  };
  view.observation_digest = await observationDigest(view);
  const tree: AuthoringTreeView = {
    draft_id: view.selection.draft_id,
    draft_revision: view.selection.draft_revision,
    snapshot_id: view.selection.snapshot_id,
    structure_version_id: crypto.randomUUID(),
    directory_template_version_id: crypto.randomUUID(),
    style_template_version_id: crypto.randomUUID(),
    metadata: {},
    nodes: view.document.outline.map((node, i) => ({
      ...node,
      section_revision: i + 1,
      title: titles[i],
      deleted: false,
      plan_version_id: null,
      template_family_id: null,
      template_key: null,
      rule_ids: [],
      source_refs: [],
      plan: null,
      plan_content_basis_state: "none",
      actual_page_range: null,
    })),
    page_budget: {
      planned_total: 0,
      unknown_section_ids: ids.slice(0, 3),
      actual_total: null,
      actual_ranges_state: "unknown",
    },
  };
  // Tombstones can exist in the tree but never count as a draft chapter.
  tree.nodes.push({
    ...tree.nodes[0],
    section_id: ids[3],
    title: "已删除合成章",
    deleted: true,
  });
  return { view, tree };
}
function fetchFixture(
  tree: AuthoringTreeView,
  body: () => AuthoringWorkContext,
) {
  const read = vi.fn(async (input: string, init: RequestInit) => {
    expect(init.method).toBe("GET");
    expect(input).toBe(
      `/api/v1/bids/${f.bidId}/work-contexts/draft_snapshot/${tree.snapshot_id}`,
    );
    return new Response(JSON.stringify(body()), { status: 200 });
  });
  vi.stubGlobal("fetch", read);
  return read;
}
const open = "查看本稿哪些章节还空白";
const scoped = () =>
  within(screen.getByRole("region", { name: "当前草稿的已存正文进度" }));
afterEach(() => vi.unstubAllGlobals());

it("observes saved body, titles, whitespace and tombstones and jumps only on an explicit click", async () => {
  const { tree, view } = await observed();
  const read = fetchFixture(tree, () => view);
  const navigate = vi.fn().mockResolvedValue(undefined);
  const props = { bidId: f.bidId, tree, onOpenSection: navigate };
  const display = render(
    <TechnicalDraftProgress {...props} navigationDisabled={false} />,
  );
  expect(read).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(scoped().getByRole("button", { name: open }));
  await scoped().findByText(/共 3 章；2 章为空白或仅标题/);
  expect(scoped().getByText(/有已保存的正文文字/)).toBeInTheDocument();
  expect(
    scoped().getByText(/仅有段内标题，未看到正文文字/),
  ).toBeInTheDocument();
  expect(scoped().getByText(/未看到可读正文/)).toBeInTheDocument();
  expect(
    scoped().queryByText(/已删除合成章|施工进度仍待人工核对/),
  ).not.toBeInTheDocument();
  expect(scoped().getByText(/文字存在不等于回答了要求/)).toBeInTheDocument();
  expect(navigate).not.toHaveBeenCalled();
  await user.click(
    scoped().getByRole("checkbox", { name: "只看空白或仅标题章" }),
  );
  expect(
    scoped().queryByRole("button", { name: "定位：" + titles[0] }),
  ).not.toBeInTheDocument();
  await user.click(
    scoped().getByRole("button", { name: "定位首个空白或仅标题章" }),
  );
  expect(navigate).toHaveBeenCalledExactlyOnceWith(ids[1]);
  display.rerender(<TechnicalDraftProgress {...props} navigationDisabled />);
  expect(
    scoped().getByRole("button", { name: "定位：" + titles[2] }),
  ).toBeDisabled();
  expect(read).toHaveBeenCalledOnce();
});

it("clears verified rows when the service observes a newer draft, and does not substitute it", async () => {
  const { tree, view } = await observed();
  const read = fetchFixture(tree, () => view);
  const navigation = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(
    <TechnicalDraftProgress
      bidId={f.bidId}
      tree={tree}
      navigationDisabled={false}
      onOpenSection={navigation}
    />,
  );
  await user.click(scoped().getByRole("button", { name: open }));
  await scoped().findByRole("button", { name: "定位：" + titles[2] });
  view.current_observation.draft_head.status = "changed";
  view.current_observation.draft_head.observed_digest = "c".repeat(64);
  view.current_observation.draft_head.reason = "EXACT_VALUE_CHANGED";
  view.observation_digest = await observationDigest(view);
  await user.click(scoped().getByRole("button", { name: "重新核对本稿正文" }));
  await scoped().findByText(/已保存的草稿不是当前版本/);
  expect(
    scoped().queryByRole("button", { name: "定位：" + titles[2] }),
  ).not.toBeInTheDocument();
  expect(read).toHaveBeenCalledTimes(2);
  expect(navigation).not.toHaveBeenCalled();
});

it("rejects the entire card when chapter scope differs rather than mixing title or revision records", async () => {
  const { tree, view } = await observed();
  tree.nodes[2].section_revision += 1;
  const navigate = vi.fn().mockResolvedValue(undefined);
  fetchFixture(tree, () => view);
  render(
    <TechnicalDraftProgress
      bidId={f.bidId}
      tree={tree}
      navigationDisabled={false}
      onOpenSection={navigate}
    />,
  );
  await userEvent.click(scoped().getByRole("button", { name: open }));
  await scoped().findByText(/目录与已保存正文的章节身份不一致/);
  expect(scoped().queryAllByRole("button", { name: /^定位/ })).toEqual([]);
  expect(navigate).not.toHaveBeenCalled();
});

it("keeps tables or images explicitly in the manual-review bucket, not in blank or text-only", () => {
  expect(
    chapterBodyState(
      sectionContent(3, [
        {
          type: "table",
          attrs: {
            id: crypto.randomUUID(),
            column_widths_twips: [400, 400],
            caption: "合成",
          },
          content: [],
        },
        paragraph("其他可见文字"),
      ]),
    ),
  ).toBe("objects_to_review");
});

it("does not flash the old chapter rows when reopened while a new read is pending", async () => {
  const { tree, view } = await observed();
  let release: (value: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    release = resolve;
  });
  const reply = () => new Response(JSON.stringify(view), { status: 200 });
  let requestNumber = 0;
  const read = vi.fn((_input: string, init: RequestInit) => {
    expect(init.method).toBe("GET");
    return ++requestNumber === 1 ? Promise.resolve(reply()) : pending;
  });
  vi.stubGlobal("fetch", read);
  const navigate = vi.fn().mockResolvedValue(undefined);
  render(
    <TechnicalDraftProgress
      bidId={f.bidId}
      tree={tree}
      navigationDisabled={false}
      onOpenSection={navigate}
    />,
  );
  const user = userEvent.setup();
  await user.click(scoped().getByRole("button", { name: open }));
  await scoped().findByRole("button", { name: "定位：" + titles[2] });
  await user.click(scoped().getByRole("button", { name: "收起已存正文进度" }));
  await user.click(scoped().getByRole("button", { name: open }));
  expect(scoped().queryAllByRole("button", { name: /^定位/ })).toEqual([]);
  expect(scoped().getByText(/正在核对当前草稿和各章修订/)).toBeInTheDocument();
  release(reply());
  await scoped().findByRole("button", { name: "定位：" + titles[2] });
  expect(read).toHaveBeenCalledTimes(2);
  expect(navigate).not.toHaveBeenCalled();
});
