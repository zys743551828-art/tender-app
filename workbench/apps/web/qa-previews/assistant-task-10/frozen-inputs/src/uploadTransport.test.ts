import { beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import type { UploadGrant, UploadPartReceipt } from "./contracts";
import {
  pendingUploadCompletion,
  rebaseUploadCompletion,
  finishObservedUpload,
  transferUpload,
} from "./uploadTransport";

// Tiny synthetic parts exercise scheduling and authoritative recovery, not real OSS acceptance.
const file = new File(["%PDF-" + "0".repeat(75)], "分片原件.pdf", {
  type: "application/pdf",
});
const base: UploadGrant = {
  upload_id: "upload",
  object_ref: "upload",
  file_id: "file",
  mode: "multipart",
  upload_url: null,
  part_size: 10,
  part_count: 8,
  parts: Array.from({ length: 8 }, (_, index) => ({
    part_number: index + 1,
    byte_offset: index * 10,
    byte_size: 10,
    url: `${window.location.origin}/api/v1/object-transfers/uploads/upload/parts/${index + 1}?ticket=synthetic`,
    expires_at: "2099-01-01T00:00:00Z",
  })),
  expires_at: "2099-01-01T00:00:00Z",
  session_expires_at: "2099-01-01T00:00:00Z",
  revision: 1,
};
function response(value: unknown, etag?: string, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
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
function backend({
  losePart = false,
  loseComplete = false,
  rejectComplete = false,
  delayMs = 5,
} = {}) {
  const observed = new Map<number, UploadPartReceipt>([
    [2, { part_number: 2, byte_size: 10, etag: "storage-2" }],
    [8, { part_number: 8, byte_size: 10, etag: "storage-8" }],
  ]);
  const put: number[] = [];
  const completes: RequestInit[] = [];
  let active = 0;
  let peak = 0;
  let revision = 1;
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, window.location.href).pathname;
    if (path === "/api/v1/uploads/upload/parts")
      return response({
        upload_id: "upload",
        revision,
        mode: "multipart",
        completed_parts: [...observed.values()],
        session_expires_at: base.session_expires_at,
      });
    if (path === "/api/v1/uploads/upload")
      return response(
        { id: "upload", revision, state: "authorized", file_id: "file" },
        revision === 1 ? '"actual-upload-etag"' : '"actual-new-upload-etag"',
      );
    const number = path.match(
      /object-transfers\/uploads\/upload\/parts\/(\d+)$/,
    )?.[1];
    if (number) {
      active++;
      peak = Math.max(peak, active);
      put.push(Number(number));
      expect(options?.credentials).toBe("same-origin");
      expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf");
      expect(new Headers(options?.headers).get("Content-Type")).toBe(
        "application/octet-stream",
      );
      expect((options?.body as Blob).size).toBe(10);
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      observed.set(Number(number), {
        part_number: Number(number),
        byte_size: 10,
        etag: `storage-${number}`,
      });
      active--;
      if (losePart && number === "4") {
        losePart = false;
        throw new TypeError("storage received, response dropped");
      }
      return new Response(null, { status: 200 });
    }
    if (path === "/api/v1/uploads/upload/complete") {
      completes.push(options!);
      if (rejectComplete) {
        rejectComplete = false;
        revision++;
        return response(
          { code: "REVISION_CONFLICT", message: "上传状态已有新修订" },
          undefined,
          412,
        );
      }
      if (loseComplete) {
        loseComplete = false;
        throw new TypeError("accepted response dropped");
      }
      return response({
        resource_kind: "upload",
        resource_id: "upload",
        operation: { id: "operation", bid_id: "bid" },
      });
    }
    throw new Error(`Unexpected ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { put, completes, peak: () => peak, observed };
}
it("只补服务端缺片，池最多4并发，完整回执取存储观察而非浏览器PUT头", async () => {
  const server = backend();
  const progress = vi.fn();
  const result = await transferUpload({
    file,
    initialGrant: base,
    digest: "a".repeat(64),
    key: "same-completion",
    onProgress: progress,
  });
  expect(server.put.sort((a, b) => a - b)).toEqual([1, 3, 4, 5, 6, 7]);
  expect(server.peak()).toBe(4);
  expect(result.resource_kind).toBe("upload");
  const complete = server.completes[0];
  expect(new Headers(complete.headers).get("If-Match")).toBe(
    '"actual-upload-etag"',
  );
  expect(
    JSON.parse(complete.body as string).parts.map(
      (part: UploadPartReceipt) => part.etag,
    ),
  ).toEqual(Array.from({ length: 8 }, (_, index) => `storage-${index + 1}`));
  expect(progress.mock.calls.at(-1)?.[0]).toMatchObject({
    receivedParts: 8,
    receivedBytes: 80,
    phase: "completing",
  });
});
it("分片ACK丢失后重新观察并跳过已被存储接收的片，不重传整批", async () => {
  const server = backend({ losePart: true });
  await expect(
    transferUpload({
      file,
      initialGrant: base,
      digest: "a".repeat(64),
      key: "complete",
      onProgress: vi.fn(),
    }),
  ).rejects.toThrow();
  const before = [...server.put];
  await transferUpload({
    file,
    initialGrant: base,
    digest: "a".repeat(64),
    key: "complete",
    onProgress: vi.fn(),
  });
  const resumed = server.put.slice(before.length);
  expect(resumed).not.toContain(4);
  expect(new Set(server.put).size).toBe(6);
  expect(server.completes).toHaveLength(1);
});
it("完成受理失响应跨刷新原key/If-Match/body重放，且不再次传分片", async () => {
  const server = backend({ loseComplete: true });
  await expect(
    transferUpload({
      file,
      initialGrant: base,
      digest: "a".repeat(64),
      key: "original-complete",
      onProgress: vi.fn(),
    }),
  ).rejects.toThrow();
  expect(pendingUploadCompletion("upload")?.etag).toBe('"actual-upload-etag"');
  const sent = server.put.length;
  await transferUpload({
    file,
    initialGrant: base,
    digest: "a".repeat(64),
    key: "must-not-replace-original",
    onProgress: vi.fn(),
  });
  expect(server.put).toHaveLength(sent);
  expect(server.completes[1].body).toBe(server.completes[0].body);
  expect(new Headers(server.completes[1].headers).get("Idempotency-Key")).toBe(
    "original-complete",
  );
  expect(new Headers(server.completes[1].headers).get("If-Match")).toBe(
    '"actual-upload-etag"',
  );
  expect(pendingUploadCompletion("upload")).toBeNull();
});
it("页面已离开后迟到的PUT响应不更新新流程或触发完成命令", async () => {
  const server = backend({ delayMs: 30 });
  let current = true;
  const progress = vi.fn();
  const work = transferUpload({
    file,
    initialGrant: base,
    digest: "a".repeat(64),
    key: "complete",
    onProgress: progress,
    isCurrent: () => current,
  });
  while (!server.put.length)
    await new Promise((resolve) => setTimeout(resolve, 1));
  current = false;
  const eventsBeforeLeaving = progress.mock.calls.length;
  await expect(work).rejects.toMatchObject({ name: "AbortError" });
  expect(progress).toHaveBeenCalledTimes(eventsBeforeLeaving);
  expect(server.completes).toHaveLength(0);
  expect(server.observed.size).toBeGreaterThan(2);
});
it("完成声明明确412后，用户可按真实最新回执与ETag重新核对，已收到片不重传", async () => {
  const server = backend({ rejectComplete: true });
  sessionStorage.setItem(
    "tender:upload:upload",
    JSON.stringify({
      cachedGrant: base,
      byteSize: file.size,
      digest: "a".repeat(64),
    }),
  );
  await expect(
    transferUpload({
      file,
      initialGrant: base,
      digest: "a".repeat(64),
      key: "rejected-key",
      onProgress: vi.fn(),
    }),
  ).rejects.toMatchObject({ status: 412 });
  const sent = server.put.length;
  await rebaseUploadCompletion("upload");
  expect(server.put).toHaveLength(sent);
  expect(new Headers(server.completes[1].headers).get("If-Match")).toBe(
    '"actual-new-upload-etag"',
  );
  expect(
    new Headers(server.completes[1].headers).get("Idempotency-Key"),
  ).not.toBe("rejected-key");
  expect(JSON.parse(server.completes[1].body as string).parts).toHaveLength(8);
  expect(pendingUploadCompletion("upload")).toBeNull();
});

it("新浏览器只依据服务器布局与已有回执完成，412重核不依赖旧浏览器授权缓存", async () => {
  const server = backend({ rejectComplete: true });
  for (let part_number = 1; part_number <= 8; part_number++)
    server.observed.set(part_number, {
      part_number,
      byte_size: 10,
      etag: `storage-${part_number}`,
    });
  await expect(
    finishObservedUpload(
      {
        upload_id: "upload",
        bid_id: "bid",
        mode: "multipart",
        part_size: 10,
        part_count: 8,
        byte_size: 80,
        declared_sha256: "a".repeat(64),
        revision: 1,
        state: "authorized",
        session_expires_at: "2099-01-01T00:00:00Z",
      },
      "new-browser-original-key",
    ),
  ).rejects.toMatchObject({ status: 412 });
  expect(sessionStorage.getItem("tender:upload:upload")).toBeNull();
  await rebaseUploadCompletion("upload");
  expect(server.put).toHaveLength(0);
  expect(new Headers(server.completes[1].headers).get("If-Match")).toBe(
    '"actual-new-upload-etag"',
  );
  expect(JSON.parse(server.completes[1].body as string).parts).toHaveLength(8);
});
