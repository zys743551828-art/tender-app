import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  DraftView,
  TechnicalChapterRunPage,
  TechnicalChapterTemplatePage,
} from "./contracts";
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
const runsPath = path + "/" + activeTemplate.template_version_id + "/runs";
const runId = "ad1531d9-4bb8-4793-8fb9-5609f456a436";
const publishedRun = "ad1531d9-4bb8-4793-8fb9-5609f456a437";
const unknownRun = "ad1531d9-4bb8-4793-8fb9-5609f456a438";
const runPage: TechnicalChapterRunPage = {
  bid_id: f.bidId,
  draft_id: draft.id,
  section_id: ref.section_id,
  template_id: activeTemplate.template_id,
  template_version_id: activeTemplate.template_version_id,
  template_digest: activeTemplate.template_digest,
  input_id: activeTemplate.input_id,
  input_digest: activeTemplate.input_digest,
  available: true,
  has_more: false,
  items: [
    {
      run_id: runId,
      recorded_at: "2026-07-01T12:01:10Z",
      stage: "reconciliation_required",
    },
    {
      run_id: publishedRun,
      recorded_at: "2026-07-01T12:01:09Z",
      stage: "candidate_published",
    },
    {
      run_id: unknownRun,
      recorded_at: "2026-07-01T12:01:08Z",
      stage: "unverified",
    },
  ],
};
const open = "查看本章已保存的固定编写模板";
const link = "到任务页核对模板当前版本";
function fixture(
  response: () => unknown,
  navigationDisabled = false,
  runResponse?: () => unknown,
) {
  const read = vi.fn(async (input: string, options: RequestInit) => {
    expect(options.method).toBe("GET");
    if (runResponse && input === runsPath)
      return new Response(JSON.stringify(runResponse()), { status: 200 });
    expect(input).toBe(path);
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
    screen.queryByRole("button", { name: /^(运行|启动|重新运行)/ }),
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

it("reads one chosen exact version on demand and distinguishes publication, unknown and billing conditions", async () => {
  const { user, read } = fixture(
    () => page,
    false,
    () => runPage,
  );
  await user.click(screen.getByRole("button", { name: open }));
  const versions = await screen.findAllByRole("button", {
    name: "查看此版本运行",
  });
  expect(read).toHaveBeenCalledOnce();
  await user.click(versions[0]);
  expect(
    await screen.findByText(/模型费用或回执待核对，不应重复运行/),
  ).toBeInTheDocument();
  expect(screen.getByText(/候选已发布，不代表已采纳/)).toBeInTheDocument();
  expect(screen.getByText(/状态待核，尚无可确认结果/)).toBeInTheDocument();
  expect(
    screen.getByText(/候选发布不等于已采用、批准或形成可提交文件/),
  ).toBeInTheDocument();
  const links = screen.getAllByRole("link", { name: "在任务页核对这次运行" });
  expect(links).toHaveLength(2);
  expect(links[0]).toHaveAttribute(
    "href",
    `/bids/${f.bidId}/tasks?run=${runId}`,
  );
  expect(links[1]).toHaveAttribute(
    "href",
    `/bids/${f.bidId}/tasks?run=${publishedRun}`,
  );
  expect(read).toHaveBeenCalledTimes(2);
});
it("does not retain another input's run results when the selected-version read changes", async () => {
  let observed = runPage;
  const { user } = fixture(
    () => page,
    false,
    () => observed,
  );
  await user.click(screen.getByRole("button", { name: open }));
  await user.click(
    (await screen.findAllByRole("button", { name: "查看此版本运行" }))[0],
  );
  await screen.findByText(/候选已发布，不代表已采纳/);
  observed = { ...runPage, input_digest: "e".repeat(64) };
  await user.click(screen.getByRole("button", { name: "刷新此版本运行记录" }));
  await screen.findByText(/固定运行记录与所选章节、模板版本或输入摘要不一致/);
  expect(
    screen.queryByRole("link", { name: "在任务页核对这次运行" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(/候选已发布，不代表已采纳/),
  ).not.toBeInTheDocument();
});
