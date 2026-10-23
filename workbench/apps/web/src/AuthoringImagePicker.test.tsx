import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthoringImagePicker } from "./AuthoringImagePicker";
import { jsonDigest } from "./editorSchema";
import type { AuthoringImageCreated } from "./contracts";

const storage = "tender:authoring:member:bid:image-upload";
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const selected = vi.fn();
function show(disabled = false) {
  return render(
    <AuthoringImagePicker
      bidId="bid"
      memberId="member"
      disabled={disabled}
      maximumBytes={8388608}
      sourceRefs={[]}
      onSelect={selected}
    />,
  );
}
function install(handler: (options: RequestInit) => Promise<Response>) {
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        return handler(options);
      }
      return json({ items: [], next_cursor: null });
    }),
  );
  return writes;
}
function file(
  read = () => Promise.resolve(new Uint8Array([137, 80, 78, 71]).buffer),
) {
  const value = new File(["tiny synthetic fixture"], "图.png", {
    type: "image/png",
  });
  Object.defineProperty(value, "arrayBuffer", { value: read });
  return value;
}
async function choose(value: File) {
  await userEvent.upload(screen.getByLabelText(/图片原件/), value);
  await userEvent.type(screen.getByLabelText("登记原因"), "本章示意图");
}
async function ack(options: RequestInit) {
  const upload = JSON.parse(String(options.body));
  const result: AuthoringImageCreated = {
    id: "version",
    asset_id: "asset",
    bid_id: "bid",
    revision: 1,
    previous_revision: null,
    previous_version_id: null,
    state: "active",
    reason: upload.reason,
    original_blob_id: "original",
    normalized_blob_id: "normalized",
    original_media_type: "image/png",
    width_px: 1,
    height_px: 1,
    normalization_proof: {},
    source_refs: [],
    digest: "a".repeat(64),
    created_by: "member",
    created_at: "2026-10-21T00:00:00Z",
    title: upload.title,
    head_revision: 1,
    head_version_id: "version",
    is_current: true,
    etag: '"image:1"',
    upload_id: await jsonDigest({
      bid: "bid",
      actor: "member",
      key: new Headers(options.headers).get("Idempotency-Key"),
    }),
  };
  return json(result);
}
beforeEach(() => {
  sessionStorage.clear();
  selected.mockClear();
  vi.restoreAllMocks();
});

it("图片失响应后刷新只重发原图片与 key，成功后仍须明确选择插入", async () => {
  let returnAck = false;
  const writes = install(async (options) => {
    if (!returnAck) throw new TypeError("lost response");
    return ack(options);
  });
  const first = show();
  await choose(file());
  await userEvent.click(screen.getByRole("button", { name: "登记图片原件" }));
  await screen.findByText("暂时无法连接服务。已完成的资料仍保留，请稍后重试。");
  first.unmount();
  returnAck = true;
  show(true);
  await userEvent.click(
    screen.getByRole("button", { name: "按原记录重试图片上传" }),
  );
  await screen.findByText(/已登记图片/);
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toEqual(writes[0].body);
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).toEqual(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
  expect(sessionStorage.getItem(storage)).toBeNull();
  expect(selected).not.toHaveBeenCalled();
});

it("读取图片字节时离开工作面，不应在退出清理后重建原成员记录或发送", async () => {
  let finish!: (value: ArrayBuffer) => void;
  const reading = vi.fn(
    () =>
      new Promise<ArrayBuffer>((resolve) => {
        finish = resolve;
      }),
  );
  const writes = install(ack);
  const view = show();
  await choose(file(reading));
  await userEvent.click(screen.getByRole("button", { name: "登记图片原件" }));
  expect(reading).toHaveBeenCalled();
  view.unmount();
  sessionStorage.clear();
  await act(async () => {
    finish(new Uint8Array([137, 80, 78, 71]).buffer);
  });
  expect(writes).toHaveLength(0);
  expect(sessionStorage.getItem(storage)).toBeNull();
});

it("已发送请求的迟到回执在卸载后保留恢复记录，不自动清理或插入", async () => {
  let finish!: () => Promise<void>;
  const writes = install(
    (options) =>
      new Promise<Response>((resolve) => {
        finish = () => ack(options).then(resolve);
      }),
  );
  const view = show();
  await choose(file());
  await userEvent.click(screen.getByRole("button", { name: "登记图片原件" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  const stored = sessionStorage.getItem(storage);
  view.unmount();
  await act(async () => {
    await finish();
  });
  expect(sessionStorage.getItem(storage)).toBe(stored);
  expect(selected).not.toHaveBeenCalled();
});

it("恢复记录配额失败时未发送图片", async () => {
  const writes = install(ack);
  show();
  await choose(file());
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("quota", "QuotaExceededError");
  });
  await userEvent.click(screen.getByRole("button", { name: "登记图片原件" }));
  await screen.findByText(/本机恢复存储空间不足，尚未发送此图片/);
  expect(writes).toHaveLength(0);
});
