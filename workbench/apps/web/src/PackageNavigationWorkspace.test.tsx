import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackageNavigationWorkspace } from "./PackageNavigationWorkspace";
import { PackageOverviewNextStep } from "./PackageOverviewNextStep";
import { packageLocation } from "./packageNavigation";
import {
  navigationFixture,
  navResponse,
} from "./packageNavigationFixtures.test-support";
import { jsonDigest } from "./editorSchema";
import { submissionId as id } from "./packageSubmissionFixtures.test-support";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("keeps an unread or failed package directory unknown, with no false empty-project instruction", async () => {
  const f = await navigationFixture();
  let finish!: (value: Response) => void;
  f.server.onRead = (path) =>
    path.includes("/packages?kind=bid")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : null;
  render(
    <PackageOverviewNextStep
      bidId={f.scope.bidId}
      onOpen={vi.fn()}
      onMaterials={vi.fn()}
    />,
  );
  expect(screen.getByText(/资料包数量与可继续位置保持未知/)).toBeVisible();
  expect(screen.queryByText(/尚未登记投标包/)).not.toBeInTheDocument();
  await act(async () =>
    finish(
      navResponse(
        { code: "DIRECTORY_UNAVAILABLE", message: "合成目录读取失败" },
        503,
      ),
    ),
  );
  expect(await screen.findByText("DIRECTORY_UNAVAILABLE")).toBeVisible();
  expect(
    screen.queryByText(/尚未登记投标包|已读取 0 个/),
  ).not.toBeInTheDocument();
});

it("does not confuse an empty first page with no packages and selects only the explicit later-page revision", async () => {
  const f = await navigationFixture(),
    onOpen = vi.fn(),
    user = userEvent.setup();
  f.server.page = { items: [], has_more: true, next_cursor: "synthetic-next" };
  f.server.onRead = (path) =>
    path.includes("cursor=synthetic-next") ? navResponse(f.page) : null;
  render(
    <PackageOverviewNextStep
      bidId={f.scope.bidId}
      onOpen={onOpen}
      onMaterials={vi.fn()}
    />,
  );
  expect(await screen.findByText(/还有未读取的目录页/)).toBeVisible();
  expect(screen.queryByText(/尚未登记投标包/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "读取更多投标包" }));
  await user.click(
    await screen.findByRole("button", { name: "打开此包修订 1" }),
  );
  expect(onOpen).toHaveBeenCalledWith({ ...f.target, inventoryId: null });
  expect(f.server.writes).toHaveLength(0);
});

it("keeps malformed later-page pagination unresolved rather than declaring the directory empty", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup();
  f.server.page = { items: [], has_more: true, next_cursor: "next" };
  f.server.onRead = (path) =>
    path.includes("cursor=next")
      ? navResponse({
          items: [],
          has_more: false,
          next_cursor: "contradiction",
        })
      : null;
  render(
    <PackageOverviewNextStep
      bidId={f.scope.bidId}
      onOpen={vi.fn()}
      onMaterials={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "读取更多投标包" }),
  );
  expect(await screen.findByText(/未把未读取内容当作空目录/)).toBeVisible();
  expect(screen.queryByText(/尚未登记投标包/)).not.toBeInTheDocument();
});

it("offers package creation only after a valid complete empty directory", async () => {
  const f = await navigationFixture();
  f.server.page = { items: [], has_more: false, next_cursor: null };
  render(
    <PackageOverviewNextStep
      bidId={f.scope.bidId}
      onOpen={vi.fn()}
      onMaterials={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("heading", { name: "建立本次投标的确切资料包" }),
  ).toBeVisible();
  expect(screen.getByText(/此目录已读完，尚未登记投标包/)).toBeVisible();
});

it("rejects an incomplete URL before issuing any package request", async () => {
  const f = await navigationFixture();
  render(
    <PackageNavigationWorkspace
      bidId={f.scope.bidId}
      memberId={f.scope.memberId}
      route={`/bids/${f.scope.bidId}/packages?inventory=${f.target.inventoryId}`}
      disabled={false}
      onLocation={vi.fn()}
      onReset={vi.fn()}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("整包链接不完整");
  expect(f.server.reads).toHaveLength(0);
  expect(f.server.writes).toHaveLength(0);
});

it("restores only the exact package revision and inventory from a link, without creating anything or reading a head as substitute", async () => {
  const f = await navigationFixture();
  render(
    <PackageNavigationWorkspace
      bidId={f.scope.bidId}
      memberId={f.scope.memberId}
      route={packageLocation(f.scope.bidId, f.target)}
      disabled={false}
      onLocation={vi.fn()}
      onReset={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("heading", { name: /清单修订 2/ }),
  ).toBeVisible();
  expect(f.server.reads).toContain(f.base);
  expect(f.server.reads).toContain(
    `${f.base}/requirement-inventories/${f.target.inventoryId}`,
  );
  expect(f.server.reads).not.toContain(
    `/api/v1/bids/${f.scope.bidId}/packages/${f.target.packageId}`,
  );
  expect(f.server.writes).toHaveLength(0);
});

it.each(["missing", "foreign", "digest"])(
  "does not fall back to a directory head when the exact package is %s",
  async (failure) => {
    const f = await navigationFixture();
    if (failure === "missing")
      f.server.onRead = (path) =>
        path === f.base
          ? navResponse(
              { code: "PACKAGE_NOT_FOUND", message: "合成修订不存在" },
              404,
            )
          : null;
    else if (failure === "foreign") {
      f.server.package.manifest.scope.bid_id = id(799);
      f.server.package.digest = await jsonDigest(f.server.package.manifest);
    } else f.server.package.digest = "f".repeat(64);
    render(
      <PackageNavigationWorkspace
        bidId={f.scope.bidId}
        memberId={f.scope.memberId}
        route={packageLocation(f.scope.bidId, f.target)}
        disabled={false}
        onLocation={vi.fn()}
        onReset={vi.fn()}
      />,
    );
    await waitFor(() => expect(f.server.reads).toContain(f.base));
    expect(
      await screen.findByText(
        failure === "missing"
          ? "PACKAGE_NOT_FOUND"
          : /链接所指包修订的身份或摘要不一致/,
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: /明确选择的冻结记录/ }),
    ).not.toBeInTheDocument();
    expect(f.server.reads).not.toContain(
      `/api/v1/bids/${f.scope.bidId}/packages/${f.target.packageId}`,
    );
    expect(f.server.writes).toHaveLength(0);
  },
);

it("rejects a hash-valid inventory for another revision without selecting the current inventory", async () => {
  const f = await navigationFixture();
  f.server.inventory.manifest.target_revision_id = id(798);
  f.server.inventory.digest = await jsonDigest(f.server.inventory.manifest);
  const onLocation = vi.fn();
  render(
    <PackageNavigationWorkspace
      bidId={f.scope.bidId}
      memberId={f.scope.memberId}
      route={packageLocation(f.scope.bidId, f.target)}
      disabled={false}
      onLocation={onLocation}
      onReset={vi.fn()}
    />,
  );
  expect(
    await screen.findByText(/链接所指清单的范围或摘要不一致/),
  ).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: /清单修订 2/ }),
  ).not.toBeInTheDocument();
  expect(onLocation).not.toHaveBeenCalled();
  expect(f.server.writes).toHaveLength(0);
});
