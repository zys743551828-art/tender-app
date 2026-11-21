import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TechnicalBidChapter } from "./TechnicalBidChapter";
import type { DraftView, TechnicalChapterLayoutView } from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import {
  matchesFixedAuthoringChapter,
  validateAuthoringInput,
} from "./packageAuthoringInputProtocol";

const f = captureFixture();
const ref = f.request.target_section;
const draft: DraftView = {
  id: ref.draft_id,
  bid_id: f.bidId,
  revision: ref.base_draft_revision,
  snapshot_id: ref.snapshot_id,
  sections: [
    {
      id: ref.section_id,
      title: "合成施工进度章节",
      revision: ref.base_section_revision,
      ordinal: 0,
      rule_ids: [],
      save_state: "saved",
    },
  ],
};
const props = {
  bidId: f.bidId,
  memberId: f.memberId,
  draft,
  sectionId: ref.section_id,
  disabled: false,
  onPreparing: vi.fn(),
  onOpenLayoutTemplates: vi.fn(),
};

const layoutPath = `/api/v1/bids/${f.bidId}/drafts/${ref.draft_id}/sections/${ref.section_id}/technical-authoring-layout`;
function protectTransport(overrides: Partial<TechnicalChapterLayoutView> = {}) {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    expect(init?.method).toBe("GET");
    if (path === layoutPath)
      return new Response(
        JSON.stringify({
          bid_id: f.bidId,
          draft_id: ref.draft_id,
          section_id: ref.section_id,
          snapshot_id: ref.snapshot_id,
          draft_revision: ref.base_draft_revision,
          section_revision: ref.base_section_revision,
          state: "plain_draft",
          unsupported_reasons: [],
          plan_state: "none",
          section_plan_revision: null,
          ordinary_structure_protected: false,
          ...overrides,
        }),
        { status: 200 },
      );
    expect(path).toBe("/api/v1/bids/" + f.bidId);
    return new Response(JSON.stringify({ id: f.bidId }), {
      status: 200,
      headers: { ETag: '"bid:' + f.bidId + ":" + "a".repeat(64) + '"' },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

it("prepares only the current saved snapshot, without sending any model or template request", async () => {
  const transport = protectTransport();
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  const result = render(<TechnicalBidChapter {...props} prepare={prepare} />);
  expect(transport).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  expect(
    await screen.findByRole("region", { name: "固定整包编写模板编辑" }),
  ).toBeInTheDocument();
  expect(prepare).toHaveBeenCalledOnce();
  expect(transport.mock.calls.map(([path]) => path)).toEqual([
    layoutPath,
    "/api/v1/bids/" + f.bidId,
  ]);
  expect(
    screen.getByRole("button", { name: "保存固定整包编写模板，不运行" }),
  ).toBeDisabled();

  result.rerender(
    <TechnicalBidChapter
      {...props}
      draft={{ ...draft, revision: draft.revision + 1 }}
      prepare={prepare}
    />,
  );
  expect(await screen.findByText(/草稿或章节已变化/)).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "固定整包编写要求" }),
  ).toBeDisabled();
});

it("preserves the editor boundary when no trusted save receipt is returned", async () => {
  const transport = protectTransport();
  const prepare = vi.fn().mockResolvedValue(null);
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  await waitFor(() =>
    expect(screen.getByText(/未核对本章已保存版本/)).toBeInTheDocument(),
  );
  expect(transport).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
});

it("rejects a stored input from another revision, chapter, or snapshot even in same project", async () => {
  const verified = await validateAuthoringInput(f.saved, f.bidId);
  expect(matchesFixedAuthoringChapter(verified, ref)).toBe(true);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      section_id: crypto.randomUUID(),
    }),
  ).toBe(false);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      snapshot_id: crypto.randomUUID(),
    }),
  ).toBe(false);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      base_draft_revision: ref.base_draft_revision + 1,
    }),
  ).toBe(false);
});

it("does not start any reads from a malformed saved chapter or snapshot identity", async () => {
  const transport = protectTransport();
  const user = userEvent.setup();
  render(
    <TechnicalBidChapter
      {...props}
      prepare={vi.fn().mockResolvedValue({
        data: { ...draft, snapshot_id: "../../other-resource" },
        etag: '"synthetic-draft"',
      })}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  expect(await screen.findByText(/未核对本章已保存版本/)).toBeInTheDocument();
  expect(transport).not.toHaveBeenCalled();
});

it("stops before opening authoring when the current structured layout needs review", async () => {
  const transport = protectTransport({ state: "layout_review_required" });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  const shortcut = await screen.findByRole("button", {
    name: "打开目录模板与版式模板",
  });
  expect(shortcut).toHaveAttribute(
    "aria-controls",
    "authoring-layout-templates",
  );
  await user.click(shortcut);
  expect(props.onOpenLayoutTemplates).toHaveBeenCalledExactlyOnceWith(shortcut);
  expect(screen.getByText(/未打开生成表单，也未启动模型/)).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
  expect(
    transport.mock.calls.map(([path, init]) => [path, init?.method]),
  ).toEqual([[layoutPath, "GET"]]);
});

it("does not direct a protected draft to an unavailable ordinary structure write", async () => {
  const transport = protectTransport({
    state: "layout_basis_changed",
    ordinary_structure_protected: true,
  });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  await screen.findByText(/不能通过普通版式操作补做确认/);
  expect(
    screen.queryByRole("button", { name: "打开目录模板与版式模板" }),
  ).not.toBeInTheDocument();
  expect(transport).toHaveBeenCalledOnce();
});

it("does not open the form when a seemingly healthy layout response describes a different snapshot", async () => {
  const transport = protectTransport({
    state: "structured_layout_rechecked",
    snapshot_id: crypto.randomUUID(),
  });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  await screen.findByText(/本章保存版本已变化或版式结果无法核对/);
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
  expect(transport).toHaveBeenCalledOnce();
});

it("identifies a plan on the exact saved draft and leaves manual editing reachable without any write", async () => {
  const transport = protectTransport({
    state: "structure_not_supported",
    unsupported_reasons: ["saved_chapter_plans"],
    plan_state: "not_configured",
    section_plan_revision: 1,
  });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  const view = render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  expect(
    await screen.findByRole("link", { name: "返回本章正文" }),
  ).toHaveAttribute("href", "#authoring-current-section");
  expect(screen.getByText(/当前工作台未配置固定编写的计划核验/)).toBeVisible();
  expect(screen.queryByText(/绑定了项目版式字段/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Word 导入来源/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
  expect(
    transport.mock.calls.map(([path, init]) => [path, init?.method]),
  ).toEqual([[layoutPath, "GET"]]);
  view.rerender(
    <TechnicalBidChapter
      {...props}
      draft={{
        ...draft,
        snapshot_id: crypto.randomUUID(),
        revision: draft.revision + 1,
      }}
      prepare={prepare}
    />,
  );
  expect(screen.queryByText(/这份草稿已有章节计划/)).not.toBeInTheDocument();
});

it.each<Partial<TechnicalChapterLayoutView>>([
  { state: "structure_not_supported", unsupported_reasons: [] },
  { state: "plain_draft", unsupported_reasons: ["saved_chapter_plans"] },
  {
    state: "structure_not_supported",
    unsupported_reasons: ["saved_chapter_plans", "saved_chapter_plans"],
  },
])(
  "fails closed on an internally inconsistent prerequisite response",
  async (bad) => {
    const transport = protectTransport(bad);
    const prepare = vi
      .fn()
      .mockResolvedValue({ data: draft, etag: '"draft-head"' });
    const user = userEvent.setup();
    render(<TechnicalBidChapter {...props} prepare={prepare} />);
    await user.click(
      screen.getByRole("button", { name: "准备生成本章技术标候选" }),
    );
    await screen.findByText(/本章保存版本已变化或版式结果无法核对/);
    expect(transport).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
    ).not.toBeInTheDocument();
  },
);

it("opens the exact frozen chapter when plan scope can be checked and shows what is excluded from the model", async () => {
  const transport = protectTransport({
    state: "structured_layout_rechecked",
    plan_state: "requires_fixed_evidence",
    section_plan_revision: 2,
  });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  const form = await screen.findByRole("region", {
    name: "固定整包编写模板编辑",
  });
  expect(form).toBeVisible();
  expect(screen.getByText(/原本章计划修订 2 会保留；/)).toBeVisible();
  expect(
    screen.getByText(/不发送计划正文、人工计划页数或待核事实/),
  ).toBeVisible();
  expect(
    transport.mock.calls.map(([path, init]) => [path, init?.method]),
  ).toEqual([
    [layoutPath, "GET"],
    ["/api/v1/bids/" + f.bidId, "GET"],
  ]);
});

it("does not prepare paid authoring when the selected saved plan relates to old chapter content", async () => {
  const transport = protectTransport({
    state: "structure_not_supported",
    unsupported_reasons: ["saved_chapter_plans"],
    plan_state: "target_stale",
    section_plan_revision: 2,
    ordinary_structure_protected: true,
  });
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  await screen.findByText(/本章计划修订 2 仍对照旧正文，不随正文自动更新/);
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
  expect(transport).toHaveBeenCalledOnce();
});
