import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DraftView, TechnicalChapterTemplatePage } from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { TechnicalChapterTemplates } from "./TechnicalChapterTemplates";

const f = captureFixture();
const ref = f.request.target_section;
const draft: DraftView = {
  id: ref.draft_id,
  bid_id: f.bidId,
  snapshot_id: ref.snapshot_id,
  revision: ref.base_draft_revision,
  sections: [
    {
      id: ref.section_id,
      title: "合成技术章节",
      revision: ref.base_section_revision,
      ordinal: 0,
      rule_ids: [],
      save_state: "saved",
    },
  ],
};
const inputId = f.saved.manifest.id;
if (typeof inputId !== "string") throw new Error("Missing synthetic input ID");
const activeTemplate = {
  template_id: "dafe815f-d0da-497f-abc9-504e5aff1553",
  template_version_id: "dafe815f-d0da-497f-abc9-504e5aff1556",
  template_revision: 4,
  template_digest: "d".repeat(64),
  name: "合成当前模板",
  paused: false,
  input_id: inputId,
  input_digest: f.saved.digest,
  input_snapshot_id: ref.snapshot_id,
  input_draft_revision: ref.base_draft_revision,
  input_section_revision: ref.base_section_revision,
  bound_to_observed_chapter: true,
};
const old = {
  ...activeTemplate,
  template_id: "dafe815f-d0da-497f-abc9-504e5aff1555",
  template_version_id: "dafe815f-d0da-497f-abc9-504e5aff1557",
  name: "合成历史模板",
  input_snapshot_id: "dafe815f-d0da-497f-abc9-504e5aff1558",
  bound_to_observed_chapter: false,
};
const page: TechnicalChapterTemplatePage = {
  bid_id: f.bidId,
  draft_id: draft.id,
  section_id: ref.section_id,
  observed_snapshot_id: draft.snapshot_id,
  observed_draft_revision: draft.revision,
  observed_section_revision: ref.base_section_revision,
  available: true,
  has_more: false,
  items: [activeTemplate, old],
};
const path = `/api/v1/bids/${f.bidId}/drafts/${draft.id}/sections/${ref.section_id}/technical-authoring-templates`;
const open = "查看本章已保存的固定编写模板";
const link = "到任务页核对模板当前版本";
function fixture(response: () => unknown, navigationDisabled = false) {
  const read = vi.fn(async (input: string, options: RequestInit) => {
    expect(input).toBe(path);
    expect(options.method).toBe("GET");
    return new Response(JSON.stringify(response()), { status: 200 });
  });
  vi.stubGlobal("fetch", read);
  return {
    read,
    user: userEvent.setup(),
    ...render(
      <TechnicalChapterTemplates
        bidId={f.bidId}
        draft={draft}
        sectionId={ref.section_id}
        navigationDisabled={navigationDisabled}
      />,
    ),
  };
}
afterEach(() => vi.unstubAllGlobals());

it("reads exact saved templates only on demand and distinguishes old scope without implying any run", async () => {
  const { user, read } = fixture(() => page);
  expect(read).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: open }));
  await waitFor(() =>
    expect(screen.getAllByRole("link", { name: link })).toHaveLength(2),
  );
  expect(read).toHaveBeenCalledOnce();
  expect(screen.getByText("合成当前模板")).toBeInTheDocument();
  expect(screen.getByText(/绑定本次已保存章节版本/)).toBeInTheDocument();
  expect(screen.getByText(/绑定早期或不同正文版本/)).toBeInTheDocument();
  expect(screen.getByText(/不判断运行、采用状态/)).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: link })[0]).toHaveAttribute(
    "href",
    `/bids/${f.bidId}/tasks?task_template=${activeTemplate.template_id}`,
  );
  expect(
    screen.queryByRole("button", { name: /运行/ }),
  ).not.toBeInTheDocument();
});
it("detaches old data when a refresh no longer has the same scope", async () => {
  let value = page;
  const { user } = fixture(() => value);
  await user.click(screen.getByRole("button", { name: open }));
  await screen.findByText("合成当前模板");
  value = { ...page, section_id: crypto.randomUUID() };
  await user.click(screen.getByRole("button", { name: "刷新本章模板目录" }));
  await screen.findByText(/模板目录的项目、草稿、章节或固定输入身份不一致/);
  expect(screen.queryByText("合成当前模板")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: link })).not.toBeInTheDocument();
});
describe("conservative template read states", () => {
  it("does not present a valid observation of a newer saved draft as this editor's scope", async () => {
    const { user } = fixture(() => ({
      ...page,
      observed_draft_revision: draft.revision + 1,
      observed_snapshot_id: crypto.randomUUID(),
      items: page.items.map((item) => ({
        ...item,
        bound_to_observed_chapter: false,
      })),
    }));
    await user.click(screen.getByRole("button", { name: open }));
    await screen.findByText(/读到的草稿或章节版本已变化/);
    expect(screen.queryByRole("link", { name: link })).not.toBeInTheDocument();
  });
  it("does not conflate unconfigured storage with having no matching saved templates", async () => {
    const { user } = fixture(() => ({ ...page, available: false, items: [] }));
    await user.click(screen.getByRole("button", { name: open }));
    await screen.findByText(/未开放固定编写模板目录/);
    expect(screen.queryByText(/没有读到与本章绑定/)).not.toBeInTheDocument();
  });
  it("does not open task links while the caller's writing flow is busy", async () => {
    const { user } = fixture(() => page, true);
    await user.click(screen.getByRole("button", { name: open }));
    await screen.findByText("合成当前模板");
    expect(screen.queryByRole("link", { name: link })).not.toBeInTheDocument();
  });
});
