import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthoringStructure } from "./AuthoringStructure";
import { treeMoveKey, type TreeMoveIntent } from "./authoringTreeMoves";
import type {
  AuthoringTreeView,
  AuthoringStructurePreview,
  AuthoringStructureResult,
} from "./contracts";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";

// The actual controls have independent component and native-browser coverage.
// This boundary isolates ACK/fresh-head sequencing from drag-event mechanics.
vi.mock("./AuthoringChapterTree", () => ({
  AuthoringChapterTree: ({
    tree,
    moveDisabled,
    onMove,
  }: {
    tree: AuthoringTreeView;
    moveDisabled: boolean;
    onMove: (intent: TreeMoveIntent, key: string) => Promise<void>;
  }) => {
    const request = () =>
      onMove(
        {
          sourceId: tree.nodes[1].section_id,
          targetId: tree.nodes[0].section_id,
          placement: "inside",
        },
        treeMoveKey(tree),
      );
    return (
      <>
        <button disabled={moveDisabled} onClick={() => void request()}>
          Synthetic move request
        </button>
        <button
          disabled={moveDisabled}
          onClick={() => {
            void request();
            void request();
          }}
        >
          Synthetic repeated move request
        </button>
      </>
    );
  },
}));
vi.mock("./AuthoringPlan", () => ({ AuthoringPlan: () => null }));

const sample = authoringLayoutFixture();
const [a, b] = sample.state.sections.map((section) => section.id);
const child = "20000000-0000-4000-8000-000000000099";
function node(
  id: string,
  title: string,
  parent: string | null,
  ordinal: number,
): AuthoringTreeView["nodes"][number] {
  return {
    section_id: id,
    title,
    parent_id: parent,
    ordinal,
    node_type: "chapter",
    deleted: false,
    section_revision: 1,
    plan_version_id: null,
    template_family_id: null,
    template_key: null,
    rule_ids: [],
    source_refs: [],
    plan: null,
    plan_content_basis_state: "none",
    actual_page_range: null,
  };
}
const initialTree: AuthoringTreeView = {
  draft_id: layoutScope.draftId,
  draft_revision: 1,
  snapshot_id: "synthetic-snapshot-1",
  structure_version_id: "synthetic-tree-1",
  nodes: [
    node(a, "合成章A", null, 0),
    node(b, "合成章B", null, 1),
    node(child, "合成子章", a, 0),
  ],
  directory_template_version_id: "directory",
  style_template_version_id: "style",
  metadata: {},
  page_budget: {
    planned_total: 0,
    unknown_section_ids: [a, b, child],
    actual_total: null,
    actual_ranges_state: "unknown",
  },
};
function savedTree() {
  const tree = structuredClone(initialTree);
  tree.draft_revision = 2;
  tree.snapshot_id = "synthetic-saved-text";
  tree.structure_version_id = "synthetic-tree-after-text-save";
  tree.nodes.forEach((node) => node.section_revision++);
  return tree;
}
function head() {
  return {
    data: {
      ...structuredClone(sample.state.draft),
      revision: 2,
      snapshot_id: "synthetic-saved-text",
      sections: [
        ...sample.state.draft.sections.map((section) => ({
          ...section,
          revision: 2,
        })),
        {
          id: child,
          title: "合成子章",
          ordinal: 2,
          revision: 2,
          rule_ids: [],
          save_state: "saved" as const,
        },
      ],
    },
    etag: '"draft:2"',
  };
}
function json(data: unknown, status = 200, etag = '"draft:1"') {
  const response = new Response(JSON.stringify(data), {
    status,
    headers: { ETag: etag },
  });
  // Deferred fetch delivery and parsing are intentionally separate from native
  // Body stream scheduling, so act can drain late negative paths deterministically.
  response.json = async () => structuredClone(data);
  return response;
}
function preview(): AuthoringStructurePreview {
  const before = savedTree().nodes;
  const after = structuredClone(before);
  Object.assign(after[1], { parent_id: a, ordinal: 1 });
  const content = Object.fromEntries(
    before.map((node) => [
      node.section_id,
      { type: "doc", attrs: { title: node.title }, content: [] },
    ]),
  );
  return {
    action_id: "synthetic-action",
    base_draft_revision: 2,
    created_ids: {},
    plan_suggestions: {},
    before,
    after,
    before_sections: content,
    after_sections: structuredClone(content),
    directory_template_version_id: "directory",
    style_template_version_id: "style",
    deletion_impact: [],
    format_report: null,
    expires_in_seconds: 300,
  };
}
function reads(url: string) {
  if (url.endsWith("/rules")) return json({ rules: [] });
  if (url.endsWith("/materials")) return json({ documents: [], conflicts: [] });
  if (url.includes("/template-versions/"))
    return json({
      id: url.endsWith("style") ? "style" : "directory",
      name: "合成模板",
      kind: url.endsWith("style") ? "layout" : "outline",
      revision: 1,
      config: url.endsWith("style")
        ? {
            schema_version: 1,
            page: "A4",
            font: "Noto Sans CJK SC",
            font_size_halfpoints: 22,
            margin_top_twips: 1440,
            margin_right_twips: 1440,
            margin_bottom_twips: 1440,
            margin_left_twips: 1440,
            paragraph_after_twips: 0,
            cover_enabled: false,
            cover_title: "合成",
            header_text: "",
            footer_text: "",
            page_number: true,
            chapter_numbering: "decimal",
            toc_enabled: true,
          }
        : { schema_version: 1, nodes: [] },
      previous_version_id: null,
    });
  return json({
    items: [],
    next_cursor: null,
    coverage: "partial",
    notice: "synthetic",
  });
}
function setup(
  options: {
    latest?: () => Response | Promise<Response>;
    prepare?: () => Promise<ReturnType<typeof head> | null>;
    post?: (
      url: string,
      init: RequestInit,
      count: number,
    ) => Response | Promise<Response>;
  } = {},
) {
  let structureReads = 0;
  const writes: { url: string; init: RequestInit }[] = [];
  const prepare = vi.fn(options.prepare ?? (async () => head()));
  const onChanged = vi.fn(async () => undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        writes.push({ url, init });
        if (options.post) return options.post(url, init, writes.length);
        if (url.endsWith("/resolve"))
          return json(
            {
              action_id: "synthetic-action",
              state: "rejected",
            } satisfies AuthoringStructureResult,
            200,
            '"draft:2"',
          );
        return json(preview(), 201, '"draft:2"');
      }
      if (url.endsWith("/structure")) {
        structureReads++;
        return structureReads === 1
          ? json(initialTree)
          : (options.latest?.() ?? json(savedTree(), 200, '"draft:2"'));
      }
      return reads(url);
    }),
  );
  const props = {
    ...layoutScope,
    draftRevision: 1,
    sectionId: child,
    disabled: false,
    onChoose: vi.fn(async () => undefined),
    prepare,
    onChanged,
    onBusy: vi.fn(),
  };
  const view = render(<AuthoringStructure {...props} />);
  return {
    ...view,
    props,
    writes,
    prepare,
    onChanged,
    reads: () => structureReads,
  };
}
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});

it("saves pending text first, derives the move from the acknowledged tree, and only previews until explicit resolution", async () => {
  let acknowledge!: (value: ReturnType<typeof head>) => void;
  const f = setup({
    prepare: () =>
      new Promise((resolve) => {
        acknowledge = resolve;
      }),
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Synthetic move request" }),
  );
  expect(f.prepare).toHaveBeenCalledTimes(1);
  expect(f.writes).toHaveLength(0);
  expect(f.reads()).toBe(1);
  await act(async () => acknowledge(head()));
  await screen.findByRole("button", { name: "应用这次变更" });
  expect(f.writes).toHaveLength(1);
  expect(f.writes[0].url).toMatch(/\/structure\/preview$/);
  expect(JSON.parse(f.writes[0].init.body as string)).toEqual({
    base_draft_revision: 2,
    changes: [
      { op: "move", section_id: b, parent: { section_id: a }, ordinal: 1 },
    ],
  });
  expect(new Headers(f.writes[0].init.headers).get("If-Match")).toBe(
    '"draft:2"',
  );
  expect(f.onChanged).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "放弃这次变更" }));
  await waitFor(() => expect(f.onChanged).toHaveBeenCalledTimes(1));
  expect(JSON.parse(f.writes[1].init.body as string)).toEqual({
    decision: "reject",
  });
  expect(initialTree.nodes[1].parent_id).toBeNull();
});

it("locks synchronous repeated move gestures before the save ACK", async () => {
  let acknowledge!: (value: ReturnType<typeof head>) => void;
  const f = setup({
    prepare: () =>
      new Promise((resolve) => {
        acknowledge = resolve;
      }),
  });
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Synthetic repeated move request",
    }),
  );
  expect(f.prepare).toHaveBeenCalledTimes(1);
  expect(f.writes).toHaveLength(0);
  await act(async () => acknowledge(head()));
  await screen.findByRole("button", { name: "应用这次变更" });
  expect(f.writes).toHaveLength(1);
});

it.each(["draft", "revision", "snapshot", "etag", "parent", "title"])(
  "rejects a changed %s after the save instead of posting an ordinal from an older tree",
  async (kind) => {
    let reads = 0;
    const f = setup({
      latest: () => {
        reads++;
        const value = savedTree();
        if (kind === "draft") value.draft_id = "other-draft";
        if (kind === "revision") value.draft_revision++;
        if (kind === "snapshot") value.snapshot_id = "unexpected-snapshot";
        if (kind === "parent")
          Object.assign(value.nodes[1], { parent_id: a, ordinal: 1 });
        if (kind === "title") value.nodes[0].title = "另一份新标题";
        return json(
          value,
          200,
          kind === "etag" ? '"different-head"' : '"draft:2"',
        );
      },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Synthetic move request" }),
    );
    await screen.findByText(/未创建移动预览/);
    expect(reads).toBeGreaterThan(0);
    expect(f.writes).toHaveLength(0);
    expect(f.onChanged).not.toHaveBeenCalled();
  },
);

it.each(["unmount", "scope", "readonly"])(
  "does not start the fresh read or preview when %s supersedes pending preparation",
  async (kind) => {
    let acknowledge!: (value: ReturnType<typeof head>) => void;
    const f = setup({
      prepare: () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Synthetic move request" }),
    );
    if (kind === "unmount") f.unmount();
    else
      f.rerender(
        <AuthoringStructure
          {...f.props}
          {...(kind === "scope"
            ? { draftId: "other-draft" }
            : { readOnly: true })}
        />,
      );
    const reads = f.reads();
    await act(async () => acknowledge(head()));
    expect(f.writes).toHaveLength(0);
    expect(f.reads()).toBe(reads);
    expect(f.onChanged).not.toHaveBeenCalled();
  },
);

it.each(["unmount", "readonly"])(
  "does not post after a fresh-tree read arrives following %s",
  async (kind) => {
    let finish!: (response: Response) => void;
    const f = setup({
      latest: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Synthetic move request" }),
    );
    await waitFor(() => expect(f.reads()).toBe(2));
    if (kind === "unmount") f.unmount();
    else f.rerender(<AuthoringStructure {...f.props} readOnly />);
    await act(async () => finish(json(savedTree(), 200, '"draft:2"')));
    expect(f.writes).toHaveLength(0);
    expect(f.onChanged).not.toHaveBeenCalled();
  },
);

it("preserves the exact uncertain preview request for recovery without preparing a new head", async () => {
  const f = setup({
    post: (_url, _init, count) => {
      if (count === 1) throw new TypeError("lost ACK");
      return json(preview(), 201, '"draft:2"');
    },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Synthetic move request" }),
  );
  await screen.findByRole("button", { name: "恢复原目录预览结果" });
  f.unmount();
  render(<AuthoringStructure {...f.props} draftRevision={99} readOnly />);
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原目录预览结果" }),
  );
  await screen.findByRole("button", { name: "应用这次变更" });
  expect(f.writes).toHaveLength(2);
  expect(f.writes[1].init.body).toBe(f.writes[0].init.body);
  for (const name of ["If-Match", "Idempotency-Key"])
    expect(new Headers(f.writes[1].init.headers).get(name)).toBe(
      new Headers(f.writes[0].init.headers).get(name),
    );
  expect(f.prepare).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "应用这次变更" })).toBeDisabled();
});

it("keeps a conflicted move preview without declaring or automatically retrying an application", async () => {
  const f = setup({
    post: (url) =>
      url.endsWith("/resolve")
        ? json(
            {
              code: "PRECONDITION_FAILED",
              message: "原草稿已变化",
              retryable: false,
              request_id: "synthetic",
              details: null,
            },
            412,
          )
        : json(preview(), 201, '"draft:2"'),
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Synthetic move request" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "应用这次变更" }),
  );
  await screen.findByText(/原预览不能覆盖当前稿/);
  expect(screen.getByText("变更尚未应用")).toBeVisible();
  expect(f.writes).toHaveLength(2);
  expect(f.onChanged).not.toHaveBeenCalled();
});

it("does not create a preview when pending text cannot receive a save ACK", async () => {
  const f = setup({ prepare: async () => null });
  const request = await screen.findByRole("button", {
    name: "Synthetic move request",
  });
  await act(async () => fireEvent.click(request));
  expect(f.prepare).toHaveBeenCalledTimes(1);
  expect(f.reads()).toBe(1);
  expect(f.writes).toHaveLength(0);
  expect(
    screen.queryByRole("button", { name: "应用这次变更" }),
  ).not.toBeInTheDocument();
});
