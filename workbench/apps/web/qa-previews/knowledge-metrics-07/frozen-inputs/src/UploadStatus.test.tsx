import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { UploadStatus } from "./UploadStatus";
import { setAuth } from "./api";
const layout = {
  upload_id: "upload",
  bid_id: "bid",
  mode: "multipart",
  part_size: 8,
  part_count: 2,
  byte_size: 12,
  declared_sha256: "a".repeat(64),
  revision: 2,
  state: "authorized",
  session_expires_at: "2099-01-01T00:00:00Z",
};
function json(value: unknown, etag?: string) {
  return new Response(JSON.stringify(value), {
    headers: etag ? { ETag: etag } : {},
  });
}
beforeEach(() => {
  sessionStorage.clear();
  setAuth({
    member: { id: "member", display_name: "测试", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
it("没有本地文件也能查询存储回执，全片已到才可按真实布局提交核验，单纯查询不写入", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  const accepted = vi.fn();
  const receipts = [
    { part_number: 1, byte_size: 8, etag: "storage-1" },
    { part_number: 2, byte_size: 4, etag: "storage-2" },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        return json({
          resource_kind: "upload",
          resource_id: "upload",
          operation: { id: "op", bid_id: "bid", state: "queued" },
        });
      }
      if (url.endsWith("/parts"))
        return json({
          upload_id: "upload",
          revision: 2,
          mode: "multipart",
          completed_parts: receipts,
        });
      if (url.endsWith("/layout")) return json(layout, '"actual-upload"');
      return json(
        { id: "upload", revision: 2, state: "authorized" },
        '"actual-upload"',
      );
    }),
  );
  render(
    <UploadStatus
      uploadId="upload"
      hasLocalFile={false}
      disabled={false}
      onWorking={vi.fn()}
      onAccepted={accepted}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "查询已收到的传输状态" }),
  );
  const finish = await screen.findByRole("button", {
    name: "按完整已收内容提交原件核验",
  });
  expect(writes).toHaveLength(0);
  expect(screen.getByText(/完整内容已经收到/)).toBeVisible();
  await user.click(finish);
  await waitFor(() => expect(accepted).toHaveBeenCalledTimes(1));
  expect(JSON.parse(writes[0].body as string)).toEqual({
    declared_sha256: layout.declared_sha256,
    parts: receipts,
  });
  expect(new Headers(writes[0].headers).get("If-Match")).toBe(
    '"actual-upload"',
  );
});
it("有缺片且未选择原文件时只可查询，不伪造完成按钮", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/parts"))
        return json({
          upload_id: "upload",
          revision: 2,
          mode: "multipart",
          completed_parts: [
            { part_number: 1, byte_size: 8, etag: "storage-1" },
          ],
        });
      if (url.endsWith("/layout")) return json(layout);
      return json(
        { id: "upload", revision: 2, state: "authorized" },
        '"actual-upload"',
      );
    }),
  );
  render(
    <UploadStatus
      uploadId="upload"
      hasLocalFile={false}
      disabled={false}
      onWorking={vi.fn()}
      onAccepted={vi.fn()}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "查询已收到的传输状态" }),
  );
  await screen.findByText(/共2片/);
  expect(
    screen.queryByRole("button", { name: "按完整已收内容提交原件核验" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/补传前需重新选择原文件/)).toBeVisible();
});
