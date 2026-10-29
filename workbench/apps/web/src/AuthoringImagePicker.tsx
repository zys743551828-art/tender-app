import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type {
  AuthoringImageCreated,
  AuthoringImagePage,
  AuthoringImageUpload,
  AuthoringImageView,
  AuthoringSourceReference,
} from "./contracts";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

type Pending = {
  version: 1;
  bidId: string;
  memberId: string;
  key: string;
  body: AuthoringImageUpload;
};
function restore(
  key: string,
  bidId: string,
  memberId: string,
): { pending: Pending | null; blocked: boolean } {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return { pending: null, blocked: false };
    const value = JSON.parse(raw) as Pending;
    if (
      value.version !== 1 ||
      value.bidId !== bidId ||
      value.memberId !== memberId ||
      typeof value.key !== "string" ||
      !value.key ||
      !value.body ||
      !["image/png", "image/jpeg"].includes(value.body.media_type) ||
      typeof value.body.content_base64 !== "string" ||
      !value.body.content_base64 ||
      value.body.content_base64.length > 11184812 ||
      typeof value.body.title !== "string" ||
      typeof value.body.reason !== "string" ||
      !Array.isArray(value.body.source_refs)
    )
      throw new Error("invalid recovery");
    return { pending: value, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}
function validImage(
  value: AuthoringImageView,
  bidId: string,
  assetId?: string,
) {
  return (
    value?.bid_id === bidId &&
    (!assetId || value.asset_id === assetId) &&
    typeof value.id === "string" &&
    !!value.id &&
    Number.isSafeInteger(value.revision) &&
    value.revision > 0 &&
    Number.isSafeInteger(value.width_px) &&
    value.width_px > 0 &&
    Number.isSafeInteger(value.height_px) &&
    value.height_px > 0 &&
    value.state === "active" &&
    value.is_current === true &&
    value.head_version_id === value.id &&
    value.head_revision === value.revision
  );
}
async function base64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let result = "";
  for (let index = 0; index < bytes.length; index += 16384)
    result += String.fromCharCode(...bytes.subarray(index, index + 16384));
  return btoa(result);
}

export function AuthoringImagePicker({
  bidId,
  memberId,
  disabled,
  maximumBytes,
  sourceRefs,
  onSelect,
}: {
  bidId: string;
  memberId: string;
  disabled: boolean;
  maximumBytes: number;
  sourceRefs: AuthoringSourceReference[];
  onSelect: (image: AuthoringImageView) => void;
}) {
  const path = `/bids/${bidId}/authoring-images`;
  const storageKey = `tender:authoring:${memberId}:${bidId}:image-upload`;
  const [recovery] = useState(() => restore(storageKey, bidId, memberId));
  const [pending, setPending] = useState(recovery.pending);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const catalog = useResource<AuthoringImagePage>(path);
  const [more, setMore] = useState<AuthoringImagePage[]>([]);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("");
  const last = more.at(-1) ?? catalog.data;
  const items = [
    ...new Map(
      [
        ...(catalog.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((item) => [item.asset_id, item]),
    ).values(),
  ];

  async function upload() {
    if (
      working.current ||
      recovery.blocked ||
      (!pendingRef.current && disabled)
    )
      return;
    working.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    let sent = false;
    try {
      let request = pendingRef.current;
      if (!request) {
        if (
          !file ||
          !["image/png", "image/jpeg"].includes(file.type) ||
          !file.size ||
          file.size > maximumBytes ||
          !title.trim() ||
          !reason.trim()
        )
          throw new Error("请选择限额内的 PNG/JPEG，填写图片名称和登记原因。");
        request = {
          version: 1,
          bidId,
          memberId,
          key: crypto.randomUUID(),
          body: {
            title: title.trim(),
            reason: reason.trim(),
            media_type: file.type as "image/png" | "image/jpeg",
            content_base64: await base64(file),
            source_refs: structuredClone(sourceRefs),
          },
        };
        if (!active.current) return;
        sessionStorage.setItem(storageKey, JSON.stringify(request));
        pendingRef.current = request;
        setPending(request);
      }
      const uploadId = await jsonDigest({
        bid: bidId,
        actor: memberId,
        key: request.key,
      });
      if (!active.current) return;
      sent = true;
      const { data } = await api<AuthoringImageCreated>(path, {
        method: "POST",
        body: request.body,
        key: request.key,
      });
      if (!active.current) return;
      if (
        !validImage(data, bidId) ||
        data.created_by !== memberId ||
        data.upload_id !== uploadId
      )
        throw new Error(
          "上传回执身份无法完整核对，保留原请求；请按原记录重试或查阅图片目录。",
        );
      sessionStorage.removeItem(storageKey);
      pendingRef.current = null;
      if (active.current) {
        setPending(null);
        setFile(null);
        setTitle("");
        setReason("");
        setMore([]);
        setNotice(
          `已登记图片“${data.title}”的版本 ${data.revision}。请在目录中明确选入章节。`,
        );
        void catalog.reload();
      }
    } catch (failure) {
      if (active.current) {
        setError(
          failure instanceof DOMException
            ? new Error(
                sent
                  ? "恢复记录未能更新，原上传可能已受理；保留原请求并从图片目录核对。"
                  : "本机恢复存储空间不足，尚未发送此图片；原选择和未决记录保留。",
              )
            : failure,
        );
        if (
          failure instanceof ApiError &&
          [400, 413, 422].includes(failure.status) &&
          failure.code !== "IDEMPOTENCY_CONFLICT"
        ) {
          try {
            sessionStorage.removeItem(storageKey);
            pendingRef.current = null;
            setPending(null);
          } catch {
            setError(
              new Error("未能更新恢复记录，请保留页面和原上传记录后重试。"),
            );
          }
        }
      }
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function select(item: AuthoringImageView) {
    if (working.current || disabled) return;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<AuthoringImageView>(
        `${path}/${item.asset_id}`,
      );
      if (
        !validImage(data, bidId, item.asset_id) ||
        data.id !== item.id ||
        data.revision !== item.revision
      )
        throw new Error("图片版本已变化或停用，请刷新目录后重新选择。");
      if (active.current) onSelect(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function next() {
    if (working.current || !last?.next_cursor) return;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<AuthoringImagePage>(
        `${path}?cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      if (active.current) setMore((pages) => [...pages, data]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section className="authoring-image-picker" aria-label="章节图片资料">
      <h4>本项目图片</h4>
      <p className="small-note">
        选用会固定图片版本；停用和版本变化会在保存、构建时重新核对。登记图片不会自动插入章节。
      </p>
      <ResourceState
        {...catalog}
        hasData={!!catalog.data}
        onRetry={() => void catalog.reload()}
      />
      {items.map((item) => (
        <div className="authoring-reference-row" key={item.asset_id}>
          <span>
            {item.title} · 版本 {item.revision} · {item.width_px}×
            {item.height_px}
          </span>
          <button
            type="button"
            className="text-button"
            disabled={disabled || busy || !validImage(item, bidId)}
            onClick={() => void select(item)}
          >
            选择此图片版本
          </button>
        </div>
      ))}
      {last?.next_cursor && (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void next()}
        >
          读取更多图片
        </button>
      )}
      {recovery.blocked && (
        <div role="alert" className="notice error">
          图片恢复记录无法核对，原记录保留，已停止发起新上传。请先从目录核对原上传。
        </div>
      )}
      {pending && (
        <div className="notice warning">
          原图片上传尚未确认。重试会发送相同图片、登记原因和原幂等键，不会改用现在的文件。
        </div>
      )}
      <div className="authoring-rich-form">
        <label>
          图片原件（PNG/JPEG，最多 {Math.floor(maximumBytes / 1024 / 1024)}{" "}
          MiB）
          <input
            type="file"
            accept="image/png,image/jpeg"
            disabled={disabled || busy || !!pending || recovery.blocked}
            onChange={(event) => {
              const selected = event.target.files?.[0] ?? null;
              setFile(selected);
              if (selected) setTitle(selected.name.slice(0, 200));
            }}
          />
        </label>
        <label>
          图片名称
          <input
            value={title}
            maxLength={200}
            disabled={disabled || busy || !!pending}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          登记原因
          <input
            value={reason}
            maxLength={1000}
            disabled={disabled || busy || !!pending}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="button secondary"
          disabled={
            busy ||
            recovery.blocked ||
            (!pending && (disabled || !file || !title.trim() || !reason.trim()))
          }
          onClick={() => void upload()}
        >
          {busy
            ? "正在核对图片…"
            : pending
              ? "按原记录重试图片上传"
              : "登记图片原件"}
        </button>
      </div>
      <p className="small-note">
        上传会同时记录当前章节已选来源作为登记依据，不把它们视为图片内容的派生证明；本机需有足够空间保留恢复记录。
      </p>
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <ErrorNotice error={error} />
    </section>
  );
}
