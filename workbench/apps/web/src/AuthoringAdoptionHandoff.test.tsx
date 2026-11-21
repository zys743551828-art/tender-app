import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { AuthoringAdoptionHandoff } from "./AuthoringAdoptionHandoff";
import {
  exactAuthoringFixture,
  exactId,
} from "./authoringExactFixtures.test-support";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { authoringText } from "./richEditorSchema";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
vi.mock("./useProjectStream", () => ({ useProjectStream: () => {} }));
vi.mock("./AuthoringPanel", () => ({
  AuthoringPanel: ({ draftId }: { draftId: string }) => (
    <output>可编辑草稿 {draftId}</output>
  ),
}));
const mocked = vi.mocked(api);

beforeEach(() => {
  mocked.mockReset();
  sessionStorage.clear();
});

async function setup(mode = "advanced") {
  const f = await exactAuthoringFixture();
  const bidId = f.f.bid.id;
  const query = new URLSearchParams({
    draft: f.saved.draft_id,
    adoption: f.action.action_id,
    snapshot: f.saved.snapshot_id,
    snapshot_digest: f.saved.snapshot_digest,
  });
  const fields = {
    action: `/assistant/actions/${f.action.action_id}`,
    frozen: `/bids/${bidId}/draft-snapshots/${f.saved.snapshot_id}`,
    qualification: `/bids/${bidId}/authoring/section-revisions/${f.binding.section_revision_id}/exact-qualification`,
    current: `/bids/${bidId}/drafts/${f.saved.draft_id}`,
  };
  const head = {
    id: f.saved.draft_id,
    bid_id: bidId,
    revision: f.saved.draft_revision + (mode === "matched" ? 0 : 1),
    snapshot_id:
      mode === "matched" || mode === "contradictory"
        ? f.saved.snapshot_id
        : exactId(9920),
    sections: [],
  };
  let qualificationReads = 0;
  mocked.mockImplementation(async (path, options) => {
    if (options?.method && options.method !== "GET")
      throw new Error("This handoff must never write");
    if (path === `/bids/${bidId}`) return { data: f.f.bid, etag: "bid-head" };
    if (path === `/bids/${bidId}/review-state`)
      return { data: { bid_id: bidId }, etag: null };
    if (path === fields.action) {
      return { data: f.executed, etag: f.executedEtag };
    }
    if (path === fields.frozen) {
      return {
        data:
          mode === "bad frozen" ? { ...f.snapshot, sections: [] } : f.snapshot,
        etag: null,
      };
    }
    if (path === fields.qualification) {
      if (mode === "temporary qualification" && !qualificationReads++)
        throw new ApiError(
          "暂时无法读取原章节资格",
          503,
          "SYNTHETIC_UNAVAILABLE",
        );
      return {
        data:
          mode === "bad qualification"
            ? { ...f.qualification, digest: "e".repeat(64) }
            : f.qualification,
        etag: null,
      };
    }
    if (path === fields.current) return { data: head, etag: "current-head" };
    throw new Error(`Unexpected read ${path}`);
  });
  if (mode === "bad digest") query.set("snapshot_digest", "a".repeat(64));
  if (mode === "duplicate") query.append("snapshot", f.saved.snapshot_id);
  return { f, query, bidId, fields, head };
}

it("retains the adopted revision and displays later work separately without any construct/send action", async () => {
  const { f, query, bidId, fields, head } = await setup();
  const user = userEvent.setup();
  render(<AuthoringAdoptionHandoff bidId={bidId} query={query} />);
  expect(
    await screen.findByText(
      `本次采纳固定为草稿修订 ${f.saved.draft_revision}。`,
    ),
  ).toBeVisible();
  expect(
    await screen.findByText(
      `当前草稿已更新到修订 ${head.revision}。本页仍只显示原采纳快照。`,
    ),
  ).toBeVisible();
  expect(screen.getByText(`快照摘要 ${f.saved.snapshot_digest}`)).toBeVisible();
  await user.click(screen.getByText("查看本次采纳的章节正文"));
  expect(screen.getByText(authoringText(f.action.preview.after))).toBeVisible();
  const review = screen.getByRole("link", { name: "查看当前草稿" });
  expect(review).toHaveAttribute(
    "href",
    `/bids/${bidId}/authoring?draft=${f.saved.draft_id}`,
  );
  expect(
    screen.queryByRole("button", { name: /生成文件|采用|提交/ }),
  ).toBeNull();
  expect(mocked.mock.calls.map(([path]) => path)).toEqual([
    fields.action,
    fields.frozen,
    fields.qualification,
    fields.current,
  ]);
  expect(
    mocked.mock.calls.every(
      ([, args]) => !args?.method || args.method === "GET",
    ),
  ).toBe(true);
});

it("shows a truly matched current head and never treats current reading as generation", async () => {
  const { query, bidId, head } = await setup("matched");
  render(<AuthoringAdoptionHandoff bidId={bidId} query={query} />);
  expect(
    await screen.findByText(`当前草稿仍为修订 ${head.revision}。`),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: "查看当前草稿" })).toBeVisible();
  expect(screen.queryByRole("button", { name: /生成文件/ })).toBeNull();
});

it.each([
  ["bad digest", 1, /与原采纳回执不一致/],
  ["bad frozen", 2, /身份|回执|固定整包/],
  ["bad qualification", 3, /身份|回执|固定整包/],
  ["contradictory", 4, /无法核对当前草稿与本次采纳快照的版本关系/],
  ["duplicate", 0, /采纳快照链接缺少有效的固定身份/],
] as const)(
  "fails closed with no fallback editor or build for %s",
  async (scenario, expectedReads, error) => {
    const { query, bidId } = await setup(scenario);
    render(<AuthoringAdoptionHandoff bidId={bidId} query={query} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(error);
    expect(screen.queryByRole("link", { name: "查看当前草稿" })).toBeNull();
    expect(screen.queryByRole("button", { name: /生成文件/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "重试核对原采纳快照" }),
    ).toBeNull();
    expect(mocked).toHaveBeenCalledTimes(expectedReads);
    expect(
      mocked.mock.calls.every(
        ([, args]) => !args?.method || args.method === "GET",
      ),
    ).toBe(true);
  },
);

it("the project authoring route mounts no writable editor until explicitly opening current", async () => {
  const { f, bidId, query } = await setup();
  const props = { id: bidId, onBack: vi.fn(), onNavigate: vi.fn() };
  const view = render(
    <ProjectWorkspace {...props} route={`/bids/${bidId}/authoring?${query}`} />,
  );
  const open = await screen.findByRole("link", { name: "查看当前草稿" });
  expect(screen.queryByText(/可编辑草稿/)).toBeNull();
  expect(open).toHaveAttribute(
    "href",
    `/bids/${bidId}/authoring?draft=${f.saved.draft_id}`,
  );
  view.rerender(
    <ProjectWorkspace {...props} route={open.getAttribute("href")!} />,
  );
  expect(
    await screen.findByText(`可编辑草稿 ${f.saved.draft_id}`),
  ).toBeVisible();
  expect(screen.queryByRole("region", { name: "采纳快照核对" })).toBeNull();
  expect(
    mocked.mock.calls.every(
      ([, args]) => !args?.method || args.method === "GET",
    ),
  ).toBe(true);
});

it("allows explicit retry of the identical historical proof after a read failure, without any write", async () => {
  const { f, query, bidId, fields, head } = await setup(
    "temporary qualification",
  );
  const user = userEvent.setup();
  render(<AuthoringAdoptionHandoff bidId={bidId} query={query} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "暂时无法读取原章节资格",
  );
  expect(screen.queryByText("查看本次采纳的章节正文")).toBeNull();
  expect(screen.queryByRole("link", { name: "查看当前草稿" })).toBeNull();
  const historicalReads = [fields.action, fields.frozen, fields.qualification];
  expect(mocked.mock.calls.map(([path]) => path)).toEqual(historicalReads);
  await user.click(screen.getByRole("button", { name: "重试核对原采纳快照" }));
  expect(
    await screen.findByText(
      `本次采纳固定为草稿修订 ${f.saved.draft_revision}。`,
    ),
  ).toBeVisible();
  expect(
    await screen.findByText(
      `当前草稿已更新到修订 ${head.revision}。本页仍只显示原采纳快照。`,
    ),
  ).toBeVisible();
  expect(mocked.mock.calls.map(([path]) => path)).toEqual([
    ...historicalReads,
    ...historicalReads,
    fields.current,
  ]);
  expect(
    mocked.mock.calls.every(
      ([, args]) => !args?.method || args.method === "GET",
    ),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: "重试核对原采纳快照" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: /生成文件|提交/ })).toBeNull();
});
