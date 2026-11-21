import { api, objectFetch, sha256Hex } from "./api";
import type { DocumentView, DownloadGrant } from "./contracts";

export function hasDocumentDigest(document: DocumentView) {
  return (
    typeof document.sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(document.sha256)
  );
}

export async function readVerifiedDocument(
  document: DocumentView,
  signal: AbortSignal,
) {
  if (
    !hasDocumentDigest(document) ||
    !Number.isSafeInteger(document.byte_size) ||
    document.byte_size < 0
  )
    throw new Error("此版本缺少有效的文件摘要或字节数，请重新读取文件信息。");
  signal.throwIfAborted();
  const { data: grant } = await api<DownloadGrant>(
    `/artifacts/${document.id}/download`,
    { signal },
  );
  signal.throwIfAborted();
  if (grant.artifact_id !== document.id)
    throw new Error("下载授权与文件版本不一致，请重试取件。");
  let response: Response;
  try {
    response = await objectFetch(grant.download_url, { signal });
  } catch (failure) {
    signal.throwIfAborted();
    if (!(failure instanceof TypeError)) throw failure;
    throw new Error(
      "未能取回此版本文件。请检查网络连接和文件存储的访问权限后重试。",
    );
  }
  signal.throwIfAborted();
  if (!response.ok)
    throw new Error(`文件取回失败（${response.status}），请重试取件。`);
  const bytes = await response.arrayBuffer();
  signal.throwIfAborted();
  if (
    bytes.byteLength !== document.byte_size ||
    (await sha256Hex(bytes)) !== document.sha256
  )
    throw new Error(
      "取回字节与本版本的原件摘要或大小不一致，未保存文件。请重试取件。",
    );
  signal.throwIfAborted();
  return new Blob([bytes], { type: document.media_type });
}

export function requestFileSave(blob: Blob, filename: string) {
  const link = window.document.createElement("a");
  const url = URL.createObjectURL(blob);
  try {
    link.download = filename;
    link.href = url;
    link.style.display = "none";
    window.document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export async function downloadDocument(
  document: DocumentView,
  signal: AbortSignal,
  filename = document.filename,
) {
  const blob = await readVerifiedDocument(document, signal);
  signal.throwIfAborted();
  requestFileSave(blob, filename);
}
