import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  navigationFixture,
  navResponse,
} from "./packageNavigationFixtures.test-support";
import {
  authoringContextFixture,
  contextChoicePage,
  contextId,
  contextTarget,
  sealAuthoringContext,
} from "../qa-previews/frozen-inputs/workContextAuthoring";
import { workContextLocation } from "./workContextNavigation";
import { saveWorkspacePosition } from "./workspacePosition";
import { packageLocation } from "./packageNavigation";

beforeEach(async () => {
  localStorage.clear();
  sessionStorage.clear();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function setup() {
  const f = await navigationFixture(),
    a = await authoringContextFixture(),
    c = a.saved;
  c.selection.bid_id = f.scope.bidId;
  c.snapshot.bid_id = f.scope.bidId;
  c.native_targets.draft_snapshot.bid_id = f.scope.bidId;
  c.native_targets.current_draft.bid_id = f.scope.bidId;
  await sealAuthoringContext(c);
  const page = await contextChoicePage(
      [c.selection],
      "draft_snapshot",
      f.scope.bidId,
    ),
    empty = await contextChoicePage([], "build", f.scope.bidId);
  f.server.onRead = (path) =>
    path.includes("/work-contexts/choices")
      ? navResponse(path.includes("kind=build") ? empty : page)
      : path.includes("/work-contexts/draft_snapshot/")
        ? navResponse(c)
        : null;
  return {
    ...f,
    c,
    position: { stage: "draft_snapshot" as const, selected: contextTarget(c) },
  };
}
it("restores the exact saved stage on a real project-home visit and browser back/forward", async () => {
  const f = await setup(),
    route = workContextLocation(f.scope.bidId, f.position),
    user = userEvent.setup();
  saveWorkspacePosition(f.scope.memberId, f.scope.bidId, route);
  history.replaceState({}, "", `/bids/${f.scope.bidId}`);
  render(<App />);
  // A cold test worker must transform the lazy workspace before resolving it.
  await screen.findByRole(
    "button",
    { name: "阅读全文与目录" },
    { timeout: 5000 },
  );
  expect(window.location.pathname + window.location.search).toBe(route);
  await user.click(screen.getByRole("radio", { name: "生成记录" }));
  await screen.findByText("尚未选择记录");
  act(() => history.back());
  await screen.findByRole("button", { name: "阅读全文与目录" });
  expect(window.location.pathname + window.location.search).toBe(route);
  act(() => history.forward());
  await screen.findByText("尚未选择记录");
  expect(f.server.writes).toHaveLength(0);
});
it("does not restore another member's last selected snapshot", async () => {
  const f = await setup();
  saveWorkspacePosition(
    contextId(909),
    f.scope.bidId,
    workContextLocation(f.scope.bidId, f.position),
  );
  history.replaceState({}, "", `/bids/${f.scope.bidId}`);
  render(<App />);
  await screen.findByRole("heading", { name: "选择确切投标包继续核查" });
  expect(window.location.pathname).toBe(`/bids/${f.scope.bidId}/overview`);
  expect(f.server.reads.some((p) => p.includes("/work-contexts/"))).toBe(false);
});
it("routes the new page through the existing unsaved-package navigation guard", async () => {
  const f = await setup(),
    route = packageLocation(f.scope.bidId, null),
    user = userEvent.setup();
  history.replaceState({}, "", route);
  render(<App />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 合成技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "更多工作区" }));
  await user.click(screen.getByRole("link", { name: "稿件与阶段" }));
  await waitFor(() =>
    expect(screen.getByText(/未保存输入或进行中的操作/)).toBeVisible(),
  );
  expect(window.location.pathname + window.location.search).toBe(route);
  expect(f.server.reads.some((p) => p.includes("/work-contexts/"))).toBe(false);
  expect(f.server.writes).toHaveLength(0);
});
