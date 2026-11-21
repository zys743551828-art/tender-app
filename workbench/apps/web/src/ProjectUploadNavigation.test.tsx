import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import * as api from "./api";
import * as transport from "./uploadTransport";
import {
  navigationFixture,
  navResponse,
} from "./packageNavigationFixtures.test-support";

beforeEach(async () => {
  localStorage.clear();
  sessionStorage.clear();
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
  const fixture = await navigationFixture();
  const materials = `/bids/${fixture.scope.bidId}/materials`;
  history.replaceState({}, "", materials);
  const app = render(<App />);
  const user = userEvent.setup();
  const file = new File(["synthetic PDF selection"], "待核对.pdf", {
    type: "application/pdf",
  });
  await user.upload(await screen.findByLabelText(/选择需要上传的资料/), file);
  const role = () => screen.queryByLabelText("待核对.pdf的资料用途");
  await user.selectOptions(role()!, "tender");
  return { ...fixture, app, user, file, role, materials };
}

it("同一项目内切换页面再返回时保留未上传的原件和用途", async () => {
  const { user, role, file, server } = await setup();
  await user.click(screen.getByRole("link", { name: "项目概览" }));
  expect(role()).toBeNull();
  await user.click(screen.getByRole("link", { name: "项目资料" }));
  expect(await screen.findByLabelText(`${file.name}的资料用途`)).toHaveValue(
    "tender",
  );
  expect(server.writes).toHaveLength(0);
  expect(JSON.stringify([localStorage, sessionStorage])).not.toContain(
    file.name,
  );
  const hash = vi
    .spyOn(api, "fileSha256")
    .mockRejectedValue(new Error("测试终止在读取文件处"));
  await user.click(screen.getByRole("button", { name: "上传并核验原件" }));
  expect(hash.mock.calls[0][0]).toBe(file);
  expect(server.writes).toHaveLength(0);
});

it("切换项目后再回到原项目，不携带离开时的本地选择", async () => {
  const { role, materials, server } = await setup();
  const other = "other-project";
  server.onRead = (path) =>
    path === `/api/v1/bids/${other}`
      ? navResponse({ ...server.bid, id: other, title: "另一项目" })
      : null;
  const visit = (route: string) =>
    act(() => {
      history.pushState({}, "", route);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
  visit(`/bids/${other}/materials`);
  await screen.findByRole("heading", { name: "另一项目" });
  expect(role()).toBeNull();
  visit(materials);
  await screen.findByRole("heading", { name: server.bid.title });
  expect(role()).toBeNull();
  expect(server.writes).toHaveLength(0);
});

it("换账号重新登录同一项目时释放原成员的选择", async () => {
  const { role, user, server } = await setup();
  act(() => window.dispatchEvent(new Event("session-expired")));
  await screen.findByRole("dialog", { name: "重新登录工作区" });
  server.onWrite = async (path) => {
    expect(path).toBe("/api/v1/auth/login");
    return navResponse({
      member: { id: "other-member", display_name: "另一成员", active: true },
      csrf_token: "synthetic",
    });
  };
  await user.type(screen.getByLabelText("账号"), "other");
  await user.type(screen.getByLabelText("密码"), "synthetic");
  await user.click(screen.getByRole("button", { name: "登录工作区" }));
  await screen.findByText("另一成员");
  await screen.findByRole("heading", { name: server.bid.title });
  expect(role()).toBeNull();
  expect(server.writes.map((w) => w.path)).toEqual(["/api/v1/auth/login"]);
});

it("重新打开当前地址时不从浏览器存储恢复待选原件", async () => {
  const { app, role, server } = await setup();
  app.unmount();
  render(<App />);
  await screen.findByLabelText(/选择需要上传的资料/);
  expect(role()).toBeNull();
  expect(server.writes).toHaveLength(0);
});

it("已授权的传输离开前确认，返回时只恢复尚未开始的文件", async () => {
  const { user, server, file, role } = await setup();
  const queued = new File(["synthetic"], "后续文件.pdf", {
    type: "application/pdf",
  });
  await user.upload(screen.getByLabelText(/选择需要上传的资料/), queued);
  await user.selectOptions(
    screen.getByLabelText("后续文件.pdf的资料用途"),
    "supplement",
  );
  const batch = {
    id: "batch-1",
    bid_id: server.bid.id,
    state: "open",
    uploads: [],
  };
  server.onWrite = async (path) =>
    navResponse(
      path.endsWith("/upload-batches")
        ? batch
        : { upload_id: "upload-1", parts: [] },
    );
  server.onRead = (path) =>
    path.endsWith("/upload-batches/batch-1") ? navResponse(batch) : null;
  vi.spyOn(api, "fileSha256").mockResolvedValue("a".repeat(64));
  const transferring = vi
    .spyOn(transport, "transferUpload")
    .mockImplementation(
      ({ signal }) =>
        new Promise((_resolve, reject) =>
          signal!.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          ),
        ),
    );
  await user.click(screen.getByRole("button", { name: "上传并核验原件" }));
  await waitFor(() => expect(transferring).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("选择需要上传的资料")).toBeDisabled();
  const current = transferring.mock.calls[0][0];
  expect(current.file).toBe(file);
  const confirm = vi
    .spyOn(window, "confirm")
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(true);
  const overview = screen.getByRole("link", { name: "项目概览" });
  await user.click(overview);
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(current.signal?.aborted).toBe(false);
  await user.click(overview);
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(current.signal?.aborted).toBe(true);
  await user.click(screen.getByRole("link", { name: "项目资料" }));
  expect(await screen.findByLabelText("后续文件.pdf的资料用途")).toHaveValue(
    "supplement",
  );
  expect(role()).toBeNull();
  expect(transferring).toHaveBeenCalledTimes(1);
  expect(server.writes.map((w) => w.path)).toEqual([
    `/api/v1/bids/${server.bid.id}/upload-batches`,
    `/api/v1/bids/${server.bid.id}/uploads`,
  ]);
});
