import { useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { useNavigationGuard } from "./navigationGuard";
import { authoringStorageKey } from "./editorStorage";
const draft = vi.hoisted(() => ({ canSave: false }));
// Editor save is controlled here; routing/session behavior is the real application.
vi.mock("./ProjectWorkspace", () => ({
  ProjectWorkspace: ({ onBack }: { onBack: () => void }) => {
    const save = useRef(async () => draft.canSave);
    useNavigationGuard(save);
    return (
      <>
        <h1>未保存章节</h1>
        <button onClick={onBack}>返回项目列表</button>
      </>
    );
  },
}));
let transport: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  draft.canSave = false;
  localStorage.clear();
  sessionStorage.clear();
  history.replaceState({}, "", "/bids/bid-1/authoring");
  transport = vi.fn<typeof fetch>().mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          url === "/api/v1/auth/session"
            ? {
                member: {
                  id: "member-1",
                  display_name: "测试人员",
                  active: true,
                },
                csrf_token: "test",
                expires_at: "2027-01-01T00:00:00Z",
              }
            : { items: [], has_more: false, next_cursor: null },
        ),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", transport);
});
it("顶部或返回导航先等保存确认，失败时章节保持挂载，成功才进入列表", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "未保存章节" });
  await userEvent.click(screen.getByRole("button", { name: "返回项目列表" }));
  expect(screen.getByRole("heading", { name: "未保存章节" })).toBeVisible();
  expect(window.location.pathname).toBe("/bids/bid-1/authoring");
  expect(transport.mock.calls.some(([url]) => url === "/api/v1/bids")).toBe(
    false,
  );
  draft.canSave = true;
  await userEvent.click(screen.getByRole("button", { name: "投标项目" }));
  expect(await screen.findByText("从一份资料，开始一个项目")).toBeVisible();
  expect(window.location.pathname).toBe("/projects");
});
it("未能保存时不退出会话，显式成功退出清理本地章节缓存；会话恢复不混其他成员草稿", async () => {
  const current = authoringStorageKey("member-1", "bid-1", "draft-1");
  const other = authoringStorageKey("other-member", "bid-1", "draft-1");
  sessionStorage.setItem(current, "local unsaved text");
  sessionStorage.setItem(other, "different member text");
  render(<App />);
  await screen.findByRole("heading", { name: "未保存章节" });
  expect(sessionStorage.getItem(other)).toBeNull();
  expect(sessionStorage.getItem(current)).toBe("local unsaved text");
  await userEvent.click(screen.getByRole("button", { name: "退出登录" }));
  expect(
    transport.mock.calls.some(([url]) => url === "/api/v1/auth/logout"),
  ).toBe(false);
  expect(sessionStorage.getItem(current)).not.toBeNull();
  draft.canSave = true;
  await userEvent.click(screen.getByRole("button", { name: "退出登录" }));
  await waitFor(() => expect(sessionStorage.getItem(current)).toBeNull());
  expect(
    await screen.findByRole("heading", { name: "登录投标工作台" }),
  ).toBeVisible();
});
