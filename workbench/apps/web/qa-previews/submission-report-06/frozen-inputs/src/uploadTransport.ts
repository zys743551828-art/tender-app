import { api, ApiError, objectFetch } from "./api";
import type {
  Accepted,
  RefreshUploadRequest,
  UploadComplete,
  UploadGrant,
  UploadPartReceipt,
  UploadPartsView,
  UploadView,
  UploadLayoutView,
} from "./contracts";

export type UploadCompletion = {
  key: string;
  etag: string;
  body: UploadComplete;
  layout?: UploadLayoutView;
};
export type UploadProgress = {
  mode: "single" | "multipart";
  receivedParts: number;
  totalParts: number;
  receivedBytes: number;
  phase: "observing" | "transferring" | "completing";
};
const completionKey = (id: string) => `tender:upload-completion:${id}`;
export function pendingUploadCompletion(id: string): UploadCompletion | null {
  try {
    return JSON.parse(
      sessionStorage.getItem(completionKey(id)) ?? "null",
    ) as UploadCompletion | null;
  } catch {
    return null;
  }
}
export async function replayUploadCompletion(id: string): Promise<Accepted> {
  const pending = pendingUploadCompletion(id);
  if (!pending)
    throw new Error("此浏览器没有待核对的完成请求，已收到的分片仍可查询。");
  const { data } = await api<Accepted>(`/uploads/${id}/complete`, {
    method: "POST",
    ...pending,
  });
  if (data.resource_kind !== "upload" || data.resource_id !== id)
    throw new Error("完成响应与上传身份不一致，原请求仍保留供核对。");
  const current = pendingUploadCompletion(id);
  if (
    current?.key === pending.key &&
    current.etag === pending.etag &&
    JSON.stringify(current.body) === JSON.stringify(pending.body)
  )
    sessionStorage.removeItem(completionKey(id));
  return data;
}
/** Explicit rebase only after a definitive conflict; uncertain accepted requests replay unchanged. */
export async function rebaseUploadCompletion(id: string): Promise<Accepted> {
  const pending = pendingUploadCompletion(id);
  const cache = JSON.parse(
    sessionStorage.getItem(`tender:upload:${id}`) ?? "null",
  ) as { cachedGrant?: UploadGrant; byteSize: number; digest: string } | null;
  const layout = pending?.layout;
  const grant = layout ?? cache?.cachedGrant;
  const size = layout?.byte_size ?? cache?.byteSize;
  const digest = layout?.declared_sha256 ?? cache?.digest;
  if (
    !pending ||
    !grant ||
    !size ||
    grant.upload_id !== id ||
    digest !== pending.body.declared_sha256
  )
    throw new Error(
      "本地缺少原上传布局或摘要，不能重新声明完成。原请求仍保留，请核对服务器状态。",
    );
  const state = await observedUpload(id);
  if (state.view.state !== "authorized")
    throw new Error(
      "此上传已不在可补传状态。请继续核对原完成请求或查看核验结果，不新建完成声明。",
    );
  const receipts = checkedReceipts(state.parts, grant, size);
  if (receipts.length !== grant.part_count)
    throw new Error("当前仍有缺片，不能重新声明完成。请选择原文件后继续补传。");
  const value: UploadCompletion = {
    key: crypto.randomUUID(),
    etag: state.etag,
    body: {
      declared_sha256: pending.body.declared_sha256,
      parts: state.parts.mode === "single" ? [] : receipts,
    },
    ...(layout ? { layout } : {}),
  };
  const latest = pendingUploadCompletion(id);
  if (latest?.key !== pending.key || latest.etag !== pending.etag)
    throw new Error("另一个接续操作已更新完成请求，请重新核对后继续。");
  sessionStorage.setItem(completionKey(id), JSON.stringify(value));
  return replayUploadCompletion(id);
}
export async function observedUpload(id: string) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const parts = await api<UploadPartsView>(`/uploads/${id}/parts`);
    const view = await api<UploadView>(`/uploads/${id}`);
    if (parts.data.upload_id !== id || view.data.id !== id || !view.etag)
      throw new Error("上传身份或当前保存令牌无法核对，请刷新后继续。");
    if (parts.data.revision === view.data.revision)
      return { parts: parts.data, view: view.data, etag: view.etag };
  }
  throw new Error(
    "上传授权正在被其他窗口更新。已收到的内容保留，请重新查询后继续。",
  );
}
function checkedReceipts(
  parts: UploadPartsView,
  grant: Pick<UploadGrant, "mode" | "part_size" | "part_count">,
  fileSize: number,
) {
  if (
    parts.mode !== grant.mode ||
    !Number.isSafeInteger(grant.part_size) ||
    grant.part_size <= 0 ||
    grant.part_count !== Math.ceil(fileSize / grant.part_size)
  )
    throw new Error("上传分片布局与本地文件不一致，未发送其他内容。");
  const seen = new Set<number>();
  for (const part of parts.completed_parts) {
    const expected = Math.min(
      grant.part_size,
      fileSize - (part.part_number - 1) * grant.part_size,
    );
    if (
      !Number.isSafeInteger(part.part_number) ||
      part.part_number < 1 ||
      part.part_number > grant.part_count ||
      seen.has(part.part_number) ||
      part.byte_size !== expected ||
      !part.etag
    )
      throw new Error("服务端观测到的分片与声明不符，请核对上传状态。");
    seen.add(part.part_number);
  }
  return [...parts.completed_parts].sort(
    (a, b) => a.part_number - b.part_number,
  );
}
export async function finishObservedUpload(
  layout: UploadLayoutView,
  key: string,
) {
  const pending = pendingUploadCompletion(layout.upload_id);
  if (pending) return replayUploadCompletion(layout.upload_id);
  const state = await observedUpload(layout.upload_id);
  if (state.view.state !== "authorized")
    throw new Error("上传已进入其他状态，请刷新核对；不重复声明完成。");
  const receipts = checkedReceipts(state.parts, layout, layout.byte_size);
  if (receipts.length !== layout.part_count)
    throw new Error("还有缺片，请选择摘要相同的原文件继续补传。");
  const completion: UploadCompletion = {
    key,
    etag: state.etag,
    body: {
      declared_sha256: layout.declared_sha256,
      parts: layout.mode === "single" ? [] : receipts,
    },
    layout,
  };
  sessionStorage.setItem(
    completionKey(layout.upload_id),
    JSON.stringify(completion),
  );
  return replayUploadCompletion(layout.upload_id);
}

/** Server-observed receipts drive recovery; PUT responses never fabricate a manifest. */
export async function transferUpload({
  file,
  initialGrant,
  digest,
  key,
  onProgress,
  signal,
  isCurrent = () => true,
}: {
  file: File;
  initialGrant: UploadGrant;
  digest: string;
  key: string;
  onProgress: (state: UploadProgress) => void;
  signal?: AbortSignal;
  isCurrent?: () => boolean;
}): Promise<Accepted> {
  const id = initialGrant.upload_id;
  function active() {
    if (!isCurrent() || signal?.aborted)
      throw new DOMException(
        "上传页面已离开，已收到的分片仍保留。",
        "AbortError",
      );
  }
  const pending = pendingUploadCompletion(id);
  if (pending) {
    if (pending.body.declared_sha256 !== digest)
      throw new Error("待核对的完成请求属于另一份原件，不能用新文件重放。");
    active();
    return replayUploadCompletion(id);
  }
  let grant = initialGrant;
  let observed = await observedUpload(id);
  active();
  function report(
    receipts: UploadPartReceipt[],
    phase: UploadProgress["phase"],
  ) {
    if (isCurrent())
      onProgress({
        mode: grant.mode,
        receivedParts: receipts.length,
        totalParts: grant.part_count,
        receivedBytes: receipts.reduce((sum, part) => sum + part.byte_size, 0),
        phase,
      });
  }
  let receipts = checkedReceipts(observed.parts, grant, file.size);
  report(receipts, "observing");
  async function refresh(numbers: number[]) {
    active();
    const body: RefreshUploadRequest = { part_numbers: numbers };
    const result = await api<UploadGrant>(`/uploads/${id}/authorizations`, {
      method: "POST",
      body,
      etag: observed.etag,
    });
    active();
    if (
      result.data.upload_id !== id ||
      result.data.mode !== grant.mode ||
      result.data.part_count !== grant.part_count ||
      result.data.part_size !== grant.part_size
    )
      throw new Error("刷新授权改变了原上传身份或布局，已停止传输。");
    grant = result.data;
    observed = await observedUpload(id);
    active();
    receipts = checkedReceipts(observed.parts, grant, file.size);
  }
  async function put(url: string, body: Blob, type: string) {
    active();
    const response = await objectFetch(url, {
      method: "PUT",
      body,
      signal,
      headers: { "Content-Type": type },
    });
    active();
    if (response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    if (!response.ok)
      throw new ApiError(
        `传输未完成（${response.status}）。已收到的内容保留，重新查询后可只补缺片。`,
        response.status,
        "UPLOAD_TRANSFER_FAILED",
      );
  }
  if (grant.mode === "single") {
    if (!receipts.length) {
      if (
        !grant.upload_url ||
        grant.revision !== observed.view.revision ||
        Date.parse(grant.expires_at) <= Date.now() + 5000
      )
        await refresh([1]);
      if (!grant.upload_url)
        throw new Error("服务端尚未提供可用的单文件传输授权。");
      report(receipts, "transferring");
      await put(grant.upload_url, file, "application/pdf");
    }
  } else {
    while (receipts.length < grant.part_count) {
      active();
      const present = new Set(receipts.map((part) => part.part_number));
      const missing = Array.from(
        { length: grant.part_count },
        (_, index) => index + 1,
      )
        .filter((number) => !present.has(number))
        .slice(0, 128);
      const usable =
        grant.revision === observed.view.revision &&
        missing.every((number) =>
          grant.parts.some(
            (part) =>
              part.part_number === number &&
              Date.parse(part.expires_at) > Date.now() + 5000,
          ),
        );
      if (!usable) await refresh(missing);
      const grants = missing.map((number) =>
        grant.parts.find((part) => part.part_number === number),
      );
      let cursor = 0;
      let failure: unknown;
      report(receipts, "transferring");
      const workers = Array.from(
        { length: Math.min(4, grants.length) },
        async () => {
          while (cursor < grants.length && !failure) {
            const part = grants[cursor++];
            try {
              if (
                !part ||
                new URL(part.url, window.location.href).origin !==
                  window.location.origin
              )
                throw new Error(
                  "分片授权必须通过当前工作区传输，未向外部地址发送原件。",
                );
              const offset = (part.part_number - 1) * grant.part_size;
              const size = Math.min(grant.part_size, file.size - offset);
              if (part.byte_offset !== offset || part.byte_size !== size)
                throw new Error("分片授权的偏移或长度不符，未发送该分片。");
              await put(
                part.url,
                file.slice(offset, offset + size),
                "application/octet-stream",
              );
            } catch (error) {
              failure = error;
            }
          }
        },
      );
      await Promise.all(workers);
      active();
      observed = await observedUpload(id);
      active();
      const updated = checkedReceipts(observed.parts, grant, file.size);
      report(updated, "observing");
      if (failure) throw failure;
      if (updated.length <= receipts.length)
        throw new Error(
          "服务端尚未观测到新增分片，传输状态保留，请重新查询后继续。",
        );
      receipts = updated;
    }
  }
  observed = await observedUpload(id);
  active();
  receipts = checkedReceipts(observed.parts, grant, file.size);
  if (receipts.length !== grant.part_count)
    throw new Error("仍有未收到的分片，不能声明上传完成。请继续补传。");
  const completion: UploadCompletion = {
    key,
    etag: observed.etag,
    body: {
      parts: grant.mode === "single" ? [] : receipts,
      declared_sha256: digest,
    },
  };
  sessionStorage.setItem(completionKey(id), JSON.stringify(completion));
  report(receipts, "completing");
  active();
  return await replayUploadCompletion(id);
}
