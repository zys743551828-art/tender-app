import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { packageLocation } from "./packageNavigation";
import {
  navigationFixture,
  navResponse,
} from "./packageNavigationFixtures.test-support";
import { submissionId as id } from "./packageSubmissionFixtures.test-support";
import { jsonDigest } from "./editorSchema";
import { storeFreezeRecord, freezeStorageKey } from "./packageFrozenInput";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const currentLocation = () => window.location.pathname + window.location.search;

it("opens a new project at the whole-package overview even when a legacy review pointer exists", async () => {
  const f = await navigationFixture();
  f.server.bid.current_review_id = id(797);
  history.replaceState({}, "", `/bids/${f.scope.bidId}`);
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "选择确切投标包继续核查" }),
  ).toBeVisible();
  expect(currentLocation()).toBe(`/bids/${f.scope.bidId}/overview`);
  fireEvent.click(screen.getByRole("button", { name: "更多工作区" }));
  expect(screen.getByRole("link", { name: "单稿评审历史" })).toHaveAttribute(
    "href",
    `/bids/${f.scope.bidId}/review`,
  );
  expect(f.server.writes).toHaveLength(0);
});

it("retains exact package and inventory across a real App unmount/reload without following a new directory head", async () => {
  const f = await navigationFixture(),
    route = packageLocation(f.scope.bidId, f.target);
  history.replaceState({}, "", route);
  const first = render(<App />);
  await screen.findByRole("heading", { name: /清单修订 2/ });
  first.unmount();
  f.server.page = {
    ...f.page,
    items: f.page.items.map((item) => ({
      ...item,
      revision_id: id(796),
      revision: 2,
    })),
  };
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: /清单修订 2/ }),
  ).toBeVisible();
  expect(currentLocation()).toBe(route);
  expect(f.server.reads.filter((path) => path === f.base)).toHaveLength(2);
  expect(f.server.reads).not.toContain(
    `/api/v1/bids/${f.scope.bidId}/packages/${f.target.packageId}`,
  );
  expect(f.server.writes).toHaveLength(0);
});

it("records explicit revision changes, clears their old inventory, and restores the original chain with browser back/forward", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup(),
    route = packageLocation(f.scope.bidId, f.target);
  const other = structuredClone(f.f.target);
  other.manifest.revision_id = id(795);
  other.manifest.revision = 2;
  other.digest = await jsonDigest(other.manifest);
  const otherTarget = {
    ...f.target,
    revisionId: other.manifest.revision_id,
    inventoryId: null,
  };
  f.server.onRead = (path) => {
    if (path.endsWith(`/packages/${f.target.packageId}/revisions?limit=20`))
      return navResponse({
        items: [
          {
            id: f.target.revisionId,
            package_id: f.target.packageId,
            revision: 1,
            digest: f.f.target.digest,
            created_at: "2025-01-01T00:00:00Z",
          },
          {
            id: other.manifest.revision_id,
            package_id: f.target.packageId,
            revision: 2,
            digest: other.digest,
            created_at: "2025-01-02T00:00:00Z",
          },
        ],
        has_more: false,
        next_cursor: null,
      });
    if (
      path === f.base.replace(f.target.revisionId, other.manifest.revision_id)
    )
      return navResponse(other);
    if (
      path.includes(other.manifest.revision_id) &&
      path.endsWith("/requirement-inventories?limit=20")
    )
      return navResponse({
        items: [],
        current_inventory_id: null,
        has_more: false,
        next_cursor: null,
      });
    return null;
  };
  history.replaceState({}, "", route);
  render(<App />);
  await screen.findByRole("heading", { name: /清单修订 2/ });
  await user.click(
    await screen.findByRole("button", { name: "查看历史修订 2" }),
  );
  await waitFor(() =>
    expect(currentLocation()).toBe(packageLocation(f.scope.bidId, otherTarget)),
  );
  expect(
    await screen.findByRole("heading", { name: "明确选择的冻结记录 · 修订 2" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: /清单修订 2/ }),
  ).not.toBeInTheDocument();
  act(() => history.back());
  expect(
    await screen.findByRole("heading", { name: /清单修订 2/ }),
  ).toBeVisible();
  expect(currentLocation()).toBe(route);
  act(() => history.forward());
  expect(
    await screen.findByRole("heading", { name: "明确选择的冻结记录 · 修订 2" }),
  ).toBeVisible();
  expect(currentLocation()).toBe(packageLocation(f.scope.bidId, otherTarget));
  expect(f.server.writes).toHaveLength(0);
});

it("blocks normal navigation and popstate with unsent package input, then permits leaving after explicit cancellation", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup(),
    route = packageLocation(f.scope.bidId, null);
  history.replaceState({}, "", route);
  render(<App />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 合成技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(currentLocation()).toBe(route);
  expect(screen.getByText(/未保存输入或进行中的操作/)).toBeVisible();
  act(() => {
    history.pushState({}, "", `/bids/${f.scope.bidId}/overview`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await waitFor(() => expect(currentLocation()).toBe(route));
  expect(
    screen.getByRole("checkbox", { name: "选择 合成技术册.pdf 版本 1" }),
  ).toBeChecked();
  const before = new Event("beforeunload", { cancelable: true });
  fireEvent(window, before);
  expect(before.defaultPrevented).toBe(true);
  await user.click(screen.getByRole("button", { name: "清空选择并新建" }));
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(
    await screen.findByRole("heading", { name: "选择确切投标包继续核查" }),
  ).toBeVisible();
  expect(f.server.writes).toHaveLength(0);
});

it("keeps a lost package-save request locked across reload and replays only its original body/key before location changes", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup(),
    route = packageLocation(f.scope.bidId, null);
  f.server.onWrite = async () => {
    throw new TypeError("synthetic lost package ACK");
  };
  history.replaceState({}, "", route);
  const first = render(<App />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 合成技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await screen.findByText("NETWORK_ERROR");
  const original = f.server.writes[0].options;
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(currentLocation()).toBe(route);
  expect(screen.getByText(/已持久化的待核原请求/)).toBeVisible();
  first.unmount();
  f.server.onWrite = (_path, options) => f.acceptedPackage(options);
  render(<App />);
  const retry = await screen.findByRole("button", { name: "核对并重试原保存" });
  expect(screen.getByRole("button", { name: "清空选择并新建" })).toBeDisabled();
  await user.click(retry);
  await screen.findByText(/已保存修订 1/);
  expect(f.server.writes).toHaveLength(2);
  const recovered = f.server.writes[1].options;
  expect(recovered.body).toBe(original.body);
  expect(new Headers(recovered.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(new Headers(recovered.headers).get("If-Match")).toBe(
    new Headers(original.headers).get("If-Match"),
  );
  await waitFor(() =>
    expect(currentLocation()).toBe(
      packageLocation(f.scope.bidId, { ...f.target, inventoryId: null }),
    ),
  );
  expect(
    sessionStorage.getItem(
      `tender:package-pending:${f.scope.memberId}:${f.scope.bidId}`,
    ),
  ).toBeNull();
});

it("protects unsent rule correction input and releases navigation after explicit cancellation", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup(),
    route = packageLocation(f.scope.bidId, f.target);
  history.replaceState({}, "", route);
  render(<App />);
  await screen.findByRole("heading", { name: /清单修订 2/ });
  await user.click(await screen.findByRole("button", { name: "打开规则修订" }));
  fireEvent.change(screen.getByLabelText("本次修订理由"), {
    target: { value: "尚未发送的合成修订理由" },
  });
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(currentLocation()).toBe(route);
  expect(screen.getByLabelText("本次修订理由")).toHaveValue(
    "尚未发送的合成修订理由",
  );
  expect(screen.getByRole("button", { name: "读取当前修订" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "放弃未发送或已明确失败的规则修订" }),
  );
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(
    await screen.findByRole("heading", { name: "选择确切投标包继续核查" }),
  ).toBeVisible();
  expect(f.server.writes).toHaveLength(0);
});

it("propagates an existing deep freeze pending through the real App guard and restores only that request after reload", async () => {
  const f = await navigationFixture(),
    user = userEvent.setup(),
    route = packageLocation(f.scope.bidId, f.target);
  const scope = { ...f.scope, ...f.target, inventoryId: f.target.inventoryId! };
  const pending = {
    key: id(790),
    body: {
      package_digest: f.f.target.digest,
      inventory_digest: f.inventory.digest,
      input_digest: "1".repeat(64),
      context_digest: "2".repeat(64),
      coverage_attempt_id: null,
      coverage_digest: null,
    },
  };
  storeFreezeRecord({ version: 1, scope, pending, lastId: null });
  const original = sessionStorage.getItem(freezeStorageKey(scope));
  history.replaceState({}, "", route);
  const first = render(<App />);
  await screen.findByRole("button", { name: "恢复原保存请求" });
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(currentLocation()).toBe(route);
  expect(screen.getByText(/已持久化的待核原请求/)).toBeVisible();
  expect(screen.getByRole("button", { name: "要求清单与覆盖" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "读取当前修订" })).toBeDisabled();
  first.unmount();
  f.server.onWrite = async () =>
    navResponse(
      { code: "COMMAND_INCOMPLETE", message: "合成原命令尚未核清" },
      409,
    );
  render(<App />);
  await user.click(
    await screen.findByRole("button", { name: "恢复原保存请求" }),
  );
  await screen.findByText("COMMAND_INCOMPLETE");
  expect(f.server.writes).toHaveLength(1);
  expect(f.server.writes[0].path).toBe(
    `${f.base}/requirement-inventories/${scope.inventoryId}/frozen-review-inputs`,
  );
  expect(JSON.parse(String(f.server.writes[0].options.body))).toEqual(
    pending.body,
  );
  expect(
    new Headers(f.server.writes[0].options.headers).get("Idempotency-Key"),
  ).toBe(pending.key);
  expect(sessionStorage.getItem(freezeStorageKey(scope))).toBe(original);
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(currentLocation()).toBe(route);
});
