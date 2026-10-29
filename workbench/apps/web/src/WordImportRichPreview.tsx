import { Fragment, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Node as EditorNode } from "prosemirror-model";
import type { AuthoringWordImportCandidate } from "./contracts";
import { readAuthoringContent } from "./richEditorSchema";
import { wordImportPath } from "./authoringWordImportRecovery";
import type { WordImportScope } from "./authoringWordImportRecovery";

export type WordImportImageState = "loading" | "ready" | "failed";
type ImageMetadata = AuthoringWordImportCandidate["images"][number];

function ImportImage({
  scope,
  candidateId,
  image,
  alt,
  caption,
  width,
  onStatus,
}: {
  scope: WordImportScope;
  candidateId: string;
  image: ImageMetadata;
  alt: string;
  caption: string;
  width: number;
  onStatus: (key: string, state: WordImportImageState) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const path = `/api/v1${wordImportPath(scope)}/${candidateId}/images/${image.key}`;
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setError(null);
    onStatus(image.key, "loading");
    void (async () => {
      try {
        const response = await fetch(path, {
          credentials: "same-origin",
          headers: { Accept: "image/png" },
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error("图片读取失败，请确认登录及原件访问权限后重试。");
        if (
          response.headers.get("Content-Type")?.split(";")[0].trim() !==
          "image/png"
        )
          throw new Error("返回的图片格式不符，未显示未知内容。");
        const length = response.headers.get("Content-Length");
        if (length !== null && Number(length) !== image.byte_size)
          throw new Error("图片长度与候选不一致，未采用本次预览。");
        const data = await response.arrayBuffer();
        if (data.byteLength !== image.byte_size)
          throw new Error("图片长度与候选不一致，未采用本次预览。");
        const digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", data)),
          (byte) => byte.toString(16).padStart(2, "0"),
        ).join("");
        if (digest !== image.digest)
          throw new Error("图片摘要与候选不一致，未采用本次预览。");
        if (!live) return;
        objectUrl = URL.createObjectURL(
          new Blob([data], { type: "image/png" }),
        );
        setUrl(objectUrl);
      } catch (failure) {
        if (!live) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "图片预览未完成，请重试。",
        );
        onStatus(image.key, "failed");
      }
    })();
    return () => {
      live = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path, image.key, image.byte_size, image.digest, onStatus, attempt]);
  return (
    <figure className="word-import-image">
      {url && !error && (
        <img
          src={url}
          alt={alt}
          style={{ width: `${width / 15}px` }}
          onLoad={(event) => {
            const loaded = event.currentTarget;
            if (
              loaded.naturalWidth !== image.width_px ||
              loaded.naturalHeight !== image.height_px
            ) {
              setError("实际图片尺寸与候选不一致，未确认该图片预览。");
              onStatus(image.key, "failed");
            } else onStatus(image.key, "ready");
          }}
          onError={() => {
            setError("浏览器未能解码该图片，不能确认图片预览。请重试。");
            onStatus(image.key, "failed");
          }}
        />
      )}
      {!url && !error && <p role="status">正在读取并核对图片：{alt}</p>}
      {error && (
        <p className="notice error" role="alert">
          {error}{" "}
          <button
            className="text-button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            重新读取此图片
          </button>
        </p>
      )}
      <figcaption>
        {caption || alt} · {image.width_px} × {image.height_px} 像素
        <span className="word-import-image-source">
          原稿位置：{image.source_part}
          ；此处展示候选图片，正式正文以明确追加后的草稿为准。
        </span>
      </figcaption>
    </figure>
  );
}

export function WordImportRichPreview({
  scope,
  candidate,
  section,
  onImageStatus,
}: {
  scope: WordImportScope;
  candidate: AuthoringWordImportCandidate;
  section: AuthoringWordImportCandidate["sections"][number];
  onImageStatus: (key: string, state: WordImportImageState) => void;
}) {
  const document = readAuthoringContent(section.content, true);
  function renderNode(node: EditorNode, key: string): ReactNode {
    const children: ReactNode[] = [];
    node.forEach((child, _offset, index) =>
      children.push(renderNode(child, `${key}.${index}`)),
    );
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
        return <p key={key}>{children.length ? children : <br />}</p>;
      case "heading":
        return (
          <div
            key={key}
            role="heading"
            aria-level={node.attrs.level}
            className={`word-import-heading level-${node.attrs.level}`}
          >
            {children}
          </div>
        );
      case "bulletList":
        return <ul key={key}>{children}</ul>;
      case "orderedList":
        return <ol key={key}>{children}</ol>;
      case "listItem":
        return <li key={key}>{children}</li>;
      case "table":
        return (
          <div
            key={key}
            className="word-import-table-scroll"
            role="region"
            aria-label={node.attrs.caption || "导入表格预览"}
            tabIndex={0}
          >
            <table
              style={{
                width: `${(node.attrs.column_widths_twips as number[]).reduce((sum, width) => sum + width, 0) / 15}px`,
              }}
            >
              <caption>{node.attrs.caption || "原稿表格"}</caption>
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
        return <tr key={key}>{children}</tr>;
      case "tableCell":
        return node.attrs.header ? (
          <th
            key={key}
            colSpan={node.attrs.colspan}
            rowSpan={node.attrs.rowspan}
          >
            {children}
          </th>
        ) : (
          <td
            key={key}
            colSpan={node.attrs.colspan}
            rowSpan={node.attrs.rowspan}
          >
            {children}
          </td>
        );
      case "image": {
        const image = candidate.images.find(
          (item) => item.key === node.attrs.asset_id,
        )!;
        return (
          <ImportImage
            key={key}
            scope={scope}
            candidateId={candidate.candidate_id}
            image={image}
            alt={node.attrs.alt}
            caption={node.attrs.caption}
            width={node.attrs.width_twips}
            onStatus={onImageStatus}
          />
        );
      }
      default:
        return <Fragment key={key}>{children}</Fragment>;
    }
  }
  return (
    <div
      className="word-import-rich-preview"
      aria-label={`候选正文：${section.title}`}
    >
      {renderNode(document, section.key)}
    </div>
  );
}
