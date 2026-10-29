import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  authoringContextFixture,
  contextChoicePage,
  contextId,
  contextTarget,
} from "../qa-previews/frozen-inputs/workContextAuthoring";
import { WorkContextWorkspace } from "./WorkContextWorkspace";
import {
  workContextLocation,
  type WorkContextPosition,
} from "./workContextNavigation";
import type { WorkContextChoicePage } from "./contracts";

const fetchMock = vi.fn(),
  openDraft = vi.fn(),
  openPackage = vi.fn();
let f: Awaited<ReturnType<typeof authoringContextFixture>>,
  directory: Record<string, WorkContextChoicePage>;
const reply = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  openDraft.mockReset();
  openPackage.mockReset();
  f = await authoringContextFixture();
  directory = {
    draft_snapshot: await contextChoicePage(
      [f.saved.selection],
      "draft_snapshot",
      f.bid,
    ),
    build: await contextChoicePage([f.built.selection], "build", f.bid),
  };
  fetchMock.mockImplementation(async (input: string) => {
    const path = new URL(input, "http://localhost");
    if (path.pathname.endsWith("/choices"))
      return reply(directory[path.searchParams.get("kind")!]);
    if (path.pathname.endsWith("/relations")) return reply(f.relations);
    if (path.pathname.includes("/draft_snapshot/")) return reply(f.saved);
    if (path.pathname.includes("/build/")) return reply(f.built);
    throw new Error(`unexpected ${path.pathname}`);
  });
});
afterEach(() => vi.unstubAllGlobals());
function Harness({
  initial = { stage: "draft_snapshot", selected: null },
}: {
  initial?: WorkContextPosition;
}) {
  const [position, setPosition] = useState(initial);
  return (
    <WorkContextWorkspace
      bidId={f.bid}
      memberId={f.member}
      route={workContextLocation(f.bid, position)}
      onLocation={setPosition}
      onOpenDraft={openDraft}
      onOpenPackage={openPackage}
    />
  );
}
it("requires an explicit directory choice and keeps the original full table and tree", async () => {
  render(<Harness />);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "选择此记录" });
  expect(screen.getByText("尚未选择记录")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "选择此记录" }));
  await user.click(
    await screen.findByRole("button", { name: "阅读全文与目录" }),
  );
  expect(
    screen.getByRole("columnheader", { name: "合并表头" }),
  ).toHaveAttribute("colspan", "2");
  expect(screen.getByText("120天")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "打开这份草稿的当前编辑稿" }),
  );
  expect(openDraft).toHaveBeenCalledWith(f.saved.selection.draft_id);
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET",
    ),
  ).toBe(true);
});
it("opens the exact deep-linked build and preserves Word success with PDF failure", async () => {
  render(
    <Harness initial={{ stage: "build", selected: contextTarget(f.built) }} />,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "查看此次生成文件" }),
  );
  expect(screen.getByText("此格式生成失败")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "下载此次 DOCX" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "下载此次 PDF" }),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "核对这次生成文件的入包关系" }),
  );
  await user.click(await screen.findByRole("button", { name: "打开这版包" }));
  expect(openPackage).toHaveBeenCalledWith({
    packageId: contextId(140),
    revisionId: contextId(141),
    inventoryId: null,
  });
  await user.click(
    screen.getByRole("button", { name: "查看生成时的已保存稿" }),
  );
  await screen.findByRole("button", { name: "阅读全文与目录" });
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes(
        `draft_snapshot/${f.saved.selection.snapshot_id}?expected_selection_digest=${f.saved.selection_digest}`,
      ),
    ),
  ).toBe(true);
});
it("rejects a changed observation across directory pages without dropping the selected record", async () => {
  const first = structuredClone(directory.draft_snapshot);
  first.total = 2;
  first.has_more = true;
  first.next_cursor = "first-cursor";
  const second = structuredClone(first);
  second.items[0].id = contextId(901);
  second.items[0].selection = {
    ...f.saved.selection,
    snapshot_id: contextId(901),
  };
  const { jsonDigest } = await import("./editorSchema");
  second.items[0].selection_digest = await jsonDigest(
    second.items[0].selection,
  );
  second.observation_digest = "7".repeat(64);
  second.has_more = false;
  second.next_cursor = null;
  fetchMock.mockImplementation(async (input: string) =>
    input.includes("/choices")
      ? reply(input.includes("cursor=") ? second : first)
      : reply(f.saved),
  );
  render(
    <Harness
      initial={{ stage: "draft_snapshot", selected: contextTarget(f.saved) }}
    />,
  );
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "阅读全文与目录" });
  await user.click(await screen.findByRole("button", { name: "显示更多记录" }));
  await screen.findByText(/目录分页的观察或顺序已变化/);
  expect(
    screen.getByRole("button", { name: "阅读全文与目录" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/已列出 1 \/ 2 条/)).toBeInTheDocument();
});
it("discards late selected content and directory responses after member or project switches", async () => {
  const replies: (() => void)[] = [];
  fetchMock.mockImplementation(
    (url: string) =>
      new Promise<Response>((resolve) =>
        replies.push(() =>
          resolve(
            reply(
              url.includes("/choices") ? directory.draft_snapshot : f.saved,
            ),
          ),
        ),
      ),
  );
  const view = render(
    <WorkContextWorkspace
      bidId={f.bid}
      memberId={f.member}
      route={workContextLocation(f.bid, {
        stage: "draft_snapshot",
        selected: contextTarget(f.saved),
      })}
      onLocation={vi.fn()}
      onOpenDraft={openDraft}
      onOpenPackage={openPackage}
    />,
  );
  expect(replies).toHaveLength(2);
  const next = contextId(999),
    empty = await contextChoicePage([], "draft_snapshot", next);
  fetchMock.mockResolvedValue(reply(empty));
  view.rerender(
    <WorkContextWorkspace
      bidId={next}
      memberId={contextId(998)}
      route={workContextLocation(next, {
        stage: "draft_snapshot",
        selected: null,
      })}
      onLocation={vi.fn()}
      onOpenDraft={openDraft}
      onOpenPackage={openPackage}
    />,
  );
  await screen.findByText(/此阶段尚无已保存记录/);
  await act(async () => replies.forEach((resolve) => resolve()));
  expect(screen.queryByText("合成项目已保存方案")).not.toBeInTheDocument();
  expect(screen.getByText("尚未选择记录")).toBeInTheDocument();
});
it("retains verified historical content when rereading receives a foreign selection", async () => {
  render(
    <Harness
      initial={{ stage: "draft_snapshot", selected: contextTarget(f.saved) }}
    />,
  );
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "阅读全文与目录" });
  fetchMock.mockResolvedValue(
    reply({
      ...f.saved,
      selection: { ...f.saved.selection, bid_id: contextId(999) },
    }),
  );
  await user.click(screen.getByRole("button", { name: "重读同一记录" }));
  await screen.findByText(/下方保留上次核验的历史内容/);
  expect(
    screen.getByRole("button", { name: "阅读全文与目录" }),
  ).toBeInTheDocument();
});
it("clearing a selected record cannot let a late response select it again", async () => {
  let resolveSelected: (() => void) | undefined;
  fetchMock.mockImplementation(async (url: string) =>
    url.includes("/choices")
      ? reply(directory.draft_snapshot)
      : new Promise<Response>((resolve) => {
          resolveSelected = () => resolve(reply(f.saved));
        }),
  );
  render(
    <Harness
      initial={{ stage: "draft_snapshot", selected: contextTarget(f.saved) }}
    />,
  );
  const user = userEvent.setup();
  await waitFor(() => expect(resolveSelected).toBeDefined());
  await user.click(screen.getByRole("button", { name: "清除本次选择" }));
  await act(async () => resolveSelected!());
  expect(
    screen.queryByRole("button", { name: "阅读全文与目录" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("尚未选择记录")).toBeInTheDocument();
});
