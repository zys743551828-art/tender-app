import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Node as EditorNode } from "prosemirror-model";
import { api } from "./api";
import type { AuthoringImageView } from "./contracts";
import { executionSha, recordObject } from "./executionInputValidation";
import { readAuthoringContent } from "./richEditorSchema";
import "./AuthoringRichSnapshot.css";

type ImageState = "loading" | "ready" | "failed";
export type SavedImageBinding = {
  asset_id: string;
  asset_revision: number;
  asset_version_id: string;
  version_digest: string;
  normalized_sha256: string;
  media_type: "image/png";
};
const imageIdentity = (node: EditorNode) =>
  `${node.attrs.id}:${node.attrs.asset_id}:${node.attrs.asset_version_id}:${node.attrs.asset_revision}`;

/** Exact historical assets: current asset heads must not silently replace a frozen image. */
function SnapshotImage({
  bidId,
  node,
  onState,
  expectedImage,
}: {
  bidId: string;
  node: EditorNode;
  onState: (identity: string, state: ImageState) => void;
  expectedImage?: SavedImageBinding | null;
}) {
  const {
    asset_id,
    asset_version_id,
    asset_revision,
    alt,
    caption,
    width_twips,
  } = node.attrs;
  const identity = imageIdentity(node);
  const path = `/bids/${bidId}/authoring-images/${asset_id}/versions/${asset_version_id}`;
  const [url, setUrl] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<AuthoringImageView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    let objectUrl: string | null = null;
    const controller = new AbortController();
    setUrl(null);
    setMetadata(null);
    setError(null);
    onState(identity, "loading");
    void (async () => {
      try {
        if (
          expectedImage === null ||
          (expectedImage !== undefined &&
            (expectedImage.asset_id !== asset_id ||
              expectedImage.asset_version_id !== asset_version_id ||
              expectedImage.asset_revision !== asset_revision ||
              expectedImage.media_type !== "image/png" ||
              !executionSha(expectedImage.version_digest) ||
              !executionSha(expectedImage.normalized_sha256)))
        )
          throw new Error(
            "图片没有与所选保存记录一致的完整版本绑定，未显示其他图片。",
          );
        const { data } = await api<AuthoringImageView>(path);
        if (!live) return;
        const proof = data.normalization_proof;
        if (
          data.bid_id !== bidId ||
          data.asset_id !== asset_id ||
          data.id !== asset_version_id ||
          data.revision !== asset_revision ||
          !recordObject(proof) ||
          (expectedImage !== undefined &&
            (data.digest !== expectedImage.version_digest ||
              proof.output_digest !== expectedImage.normalized_sha256)) ||
          proof.protocol !== "authoring-raster-normalization/1" ||
          proof.output_media_type !== "image/png" ||
          !executionSha(proof.output_digest) ||
          !Number.isSafeInteger(proof.output_byte_size) ||
          Number(proof.output_byte_size) < 1 ||
          Number(proof.output_byte_size) > 16 * 1024 * 1024 ||
          !Number.isSafeInteger(data.width_px) ||
          data.width_px < 1 ||
          data.width_px > 10000 ||
          !Number.isSafeInteger(data.height_px) ||
          data.height_px < 1 ||
          data.height_px > 10000 ||
          proof.width_px !== data.width_px ||
          proof.height_px !== data.height_px ||
          data.width_px * data.height_px > 16000000
        )
          throw new Error(
            "图片的项目、历史版本或规范字节证明不一致，未显示其他版本。",
          );
        const response = await fetch(`/api/v1${path}/bytes/normalized`, {
          credentials: "same-origin",
          headers: { Accept: "image/png" },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error("未取得此历史版本的图片，请恢复访问后重试。");
        if (
          response.headers.get("Content-Type")?.split(";")[0].trim() !==
          "image/png"
        )
          throw new Error("图片格式与保存证明不一致，未显示未知内容。");
        const length = response.headers.get("Content-Length");
        if (length !== null && Number(length) !== proof.output_byte_size)
          throw new Error("图片字节长度与保存证明不一致。");
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength !== proof.output_byte_size)
          throw new Error("图片字节长度与保存证明不一致。");
        const digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
          (byte) => byte.toString(16).padStart(2, "0"),
        ).join("");
        if (digest !== proof.output_digest)
          throw new Error("图片摘要与保存证明不一致，尚未确认此预览。");
        if (!live) return;
        objectUrl = URL.createObjectURL(
          new Blob([bytes], { type: "image/png" }),
        );
        setMetadata(data);
        setUrl(objectUrl);
      } catch (failure) {
        if (!live) return;
        setError(
          failure instanceof Error ? failure.message : "图片预览未完成。",
        );
        onState(identity, "failed");
      }
    })();
    return () => {
      live = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    path,
    bidId,
    asset_id,
    asset_version_id,
    asset_revision,
    identity,
    onState,
    attempt,
    expectedImage,
  ]);
  return (
    <figure className="rich-snapshot-image">
      {url && metadata && !error && (
        <img
          src={url}
          alt={alt}
          style={{ width: `${width_twips / 15}px` }}
          onLoad={(event) => {
            if (
              event.currentTarget.naturalWidth !== metadata.width_px ||
              event.currentTarget.naturalHeight !== metadata.height_px
            ) {
              setError("浏览器解码尺寸与保存证明不一致，尚未确认此预览。");
              onState(identity, "failed");
            } else onState(identity, "ready");
          }}
          onError={() => {
            setError("浏览器未能解码此历史图片，请重试。");
            onState(identity, "failed");
          }}
        />
      )}
      {!url && !error && <p role="status">正在读取确切图片版本：{alt}</p>}
      {error && (
        <p className="notice error" role="alert">
          {error}{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重读此历史图片
          </button>
        </p>
      )}
      <figcaption>
        {caption || alt} · 图片版本 {asset_revision}
        {metadata && !metadata.is_current && (
          <span>（历史版本；当前图片头已变化）</span>
        )}
      </figcaption>
    </figure>
  );
}

export function AuthoringRichSnapshot({
  bidId,
  content,
  label,
  changedNodeIds = [],
  onReady,
  expectedImages,
}: {
  bidId: string;
  content: unknown;
  label: string;
  changedNodeIds?: string[];
  onReady?: (ready: boolean) => void;
  expectedImages?: readonly SavedImageBinding[];
}) {
  const parsed = useMemo(() => {
    try {
      return { document: readAuthoringContent(content, true), error: null };
    } catch (failure) {
      return {
        document: null,
        error:
          failure instanceof Error ? failure.message : "章节结构无法完整预览。",
      };
    }
  }, [content]);
  const imageIds = useMemo(() => {
    const ids: string[] = [];
    parsed.document?.descendants((node) => {
      if (node.type.name === "image") ids.push(imageIdentity(node));
    });
    return ids;
  }, [parsed.document]);
  const [imageStates, setImageStates] = useState<Record<string, ImageState>>(
    {},
  );
  const onState = useCallback((identity: string, state: ImageState) => {
    setImageStates((old) =>
      old[identity] === state ? old : { ...old, [identity]: state },
    );
  }, []);
  const ready =
    !!parsed.document &&
    imageIds.every((identity) => imageStates[identity] === "ready");
  useEffect(() => {
    onReady?.(ready);
  }, [onReady, ready]);
  const changes = new Set(changedNodeIds);
  function renderNode(node: EditorNode, key: string): ReactNode {
    const children: ReactNode[] = [];
    node.forEach((child, _offset, index) =>
      children.push(renderNode(child, `${key}.${index}`)),
    );
    const attrs = {
      "data-node-id": node.attrs.id as string | undefined,
      className: changes.has(String(node.attrs.id))
        ? "rich-snapshot-changed"
        : undefined,
    };
    switch (node.type.name) {
      case "text": {
        let value: ReactNode = node.text;
        for (const mark of node.marks) {
          if (mark.type.name === "bold") value = <strong>{value}</strong>;
          else if (mark.type.name === "italic") value = <em>{value}</em>;
        }
        return <Fragment key={key}>{value}</Fragment>;
      }
      case "hardBreak":
        return <br key={key} />;
      case "paragraph":
        return (
          <p key={key} {...attrs}>
            {children.length ? children : <br />}
          </p>
        );
      case "heading":
        return (
          <div
            key={key}
            {...attrs}
            role="heading"
            aria-level={node.attrs.level}
          >
            {children}
          </div>
        );
      case "bulletList":
        return (
          <ul key={key} {...attrs}>
            {children}
          </ul>
        );
      case "orderedList":
        return (
          <ol key={key} {...attrs}>
            {children}
          </ol>
        );
      case "listItem":
        return (
          <li key={key} {...attrs}>
            {children}
          </li>
        );
      case "table":
        return (
          <div
            key={key}
            className="rich-snapshot-table"
            role="region"
            aria-label={node.attrs.caption || "正文表格"}
            tabIndex={0}
          >
            <table
              {...attrs}
              style={{
                width: `${(node.attrs.column_widths_twips as number[]).reduce((sum, width) => sum + width, 0) / 15}px`,
              }}
            >
              <caption>{node.attrs.caption || "正文表格"}</caption>
              <colgroup>
                {(node.attrs.column_widths_twips as number[]).map(
                  (width, index) => (
                    <col key={index} style={{ width: `${width / 15}px` }} />
                  ),
                )}
              </colgroup>
              <tbody>{children}</tbody>
            </table>
          </div>
        );
      case "tableRow":
        return (
          <tr key={key} {...attrs}>
            {children}
          </tr>
        );
      case "tableCell":
        return node.attrs.header ? (
          <th
            key={key}
            {...attrs}
            colSpan={node.attrs.colspan}
            rowSpan={node.attrs.rowspan}
          >
            {children}
          </th>
        ) : (
          <td
            key={key}
            {...attrs}
            colSpan={node.attrs.colspan}
            rowSpan={node.attrs.rowspan}
          >
            {children}
          </td>
        );
      case "image":
        return (
          <SnapshotImage
            key={key}
            bidId={bidId}
            node={node}
            onState={onState}
            expectedImage={
              expectedImages === undefined
                ? undefined
                : (expectedImages.find(
                    (img) =>
                      img.asset_version_id === node.attrs.asset_version_id,
                  ) ?? null)
            }
          />
        );
      default:
        return <Fragment key={key}>{children}</Fragment>;
    }
  }
  return (
    <section className="rich-snapshot" aria-label={label}>
      <h5 className="rich-snapshot-label">{label}</h5>
      {parsed.error && (
        <p className="notice error" role="alert">
          {parsed.error}
        </p>
      )}
      {parsed.document && renderNode(parsed.document, "doc")}
    </section>
  );
}
