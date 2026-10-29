import { useState } from "react";
import type { Node as EditorNode } from "prosemirror-model";
import type {
  AuthoringImageView,
  AuthoringRichCapabilities,
  AuthoringRichImage,
  AuthoringRichTable,
} from "./contracts";
import { AuthoringImagePicker } from "./AuthoringImagePicker";
import { ErrorNotice } from "./components";
import { createTable, mergeTable, splitTableCell } from "./richTableTools";
import {
  readAuthoringContent,
  serializeAuthoringContent,
} from "./richEditorSchema";
import type { EditorDocument } from "./richEditorSchema";
import "./authoringRich.css";

export function AuthoringRichTools({
  bidId,
  memberId,
  value,
  capabilities,
  disabled,
  onChange,
}: {
  bidId: string;
  memberId: string;
  value: EditorNode;
  capabilities: AuthoringRichCapabilities;
  disabled: boolean;
  onChange: (value: EditorNode) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState(2),
    [columns, setColumns] = useState(2);
  const [width, setWidth] = useState(14),
    [caption, setCaption] = useState("");
  const [header, setHeader] = useState(true);
  const [repeatHeader, setRepeatHeader] = useState(false);
  const [selectedTable, setSelectedTable] = useState("");
  const [firstRow, setFirstRow] = useState(1),
    [firstColumn, setFirstColumn] = useState(1);
  const [rowSpan, setRowSpan] = useState(1),
    [columnSpan, setColumnSpan] = useState(2);
  const [image, setImage] = useState<AuthoringImageView | null>(null);
  const [imageWidth, setImageWidth] = useState(12),
    [alt, setAlt] = useState("");
  const [imageCaption, setImageCaption] = useState("");
  const [error, setError] = useState<unknown>(null);
  const document = serializeAuthoringContent(value);
  const tables: AuthoringRichTable[] = [];
  for (const node of document.content)
    if (node.type === "table") tables.push(node);
  const current = tables.find((table) => table.attrs.id === selectedTable);
  function apply(next: EditorDocument) {
    if (disabled) return;
    try {
      const node = readAuthoringContent(next);
      onChange(node);
      setError(null);
    } catch (failure) {
      setError(failure);
    }
  }
  function addTable() {
    if (disabled) return;
    try {
      const table = createTable(
        rows,
        columns,
        Math.round(width * 567),
        caption,
        header,
        repeatHeader,
      );
      apply({ ...document, content: [...document.content, table] });
      setSelectedTable(table.attrs.id);
    } catch (failure) {
      setError(failure);
    }
  }
  function changeTable(kind: "merge" | "split") {
    if (!current || disabled) return;
    try {
      const next =
        kind === "merge"
          ? mergeTable(current, firstRow, firstColumn, rowSpan, columnSpan)
          : splitTableCell(current, firstRow, firstColumn);
      apply({
        ...document,
        content: document.content.map((node) =>
          node === current ? next : node,
        ),
      });
    } catch (failure) {
      setError(failure);
    }
  }
  function addImage() {
    if (!image || disabled) return;
    const widthTwips = Math.round(imageWidth * 567);
    const node: AuthoringRichImage = {
      type: "image",
      attrs: {
        id: crypto.randomUUID(),
        asset_id: image.asset_id,
        asset_revision: image.revision,
        asset_version_id: image.id,
        width_twips: widthTwips,
        height_twips: Math.round(
          (widthTwips * image.height_px) / image.width_px,
        ),
        alt: alt.trim(),
        caption: imageCaption,
      },
    };
    apply({ ...document, content: [...document.content, node] });
  }
  return (
    <details
      className="coverage-details authoring-rich-tools"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>编制表格与图片 · 保留结构及固定图片版本</summary>
      {open && (
        <>
          <p className="small-note">
            表格原生保存，合并保留全部单元格文字；图片仅使用已登记版本。宽度按厘米输入，最终还会核对当前版式的版心范围。
          </p>
          <fieldset disabled={disabled} className="authoring-rich-form">
            <legend>在章末插入表格</legend>
            <label>
              行数
              <input
                type="number"
                min={1}
                max={200}
                value={rows}
                onChange={(event) => setRows(Number(event.target.value))}
              />
            </label>
            <label>
              列数
              <input
                type="number"
                min={1}
                max={100}
                value={columns}
                onChange={(event) => setColumns(Number(event.target.value))}
              />
            </label>
            <label>
              总宽（厘米）
              <input
                type="number"
                min={0.1}
                max={35}
                step={0.1}
                value={width}
                onChange={(event) => setWidth(Number(event.target.value))}
              />
            </label>
            <label>
              表格说明
              <input
                maxLength={1000}
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={header}
                onChange={(event) => setHeader(event.target.checked)}
              />
              首行作为表头
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={repeatHeader}
                onChange={(event) => setRepeatHeader(event.target.checked)}
              />
              跨页重复首行表头（2–12行、无合并单元格；PDF仍需验证）
            </label>
            <button
              type="button"
              className="button secondary"
              onClick={addTable}
            >
              插入表格到章末
            </button>
          </fieldset>
          {!!tables.length && (
            <fieldset disabled={disabled} className="authoring-rich-form">
              <legend>调整已有表格</legend>
              <label>
                选择表格
                <select
                  value={selectedTable}
                  onChange={(event) => setSelectedTable(event.target.value)}
                >
                  <option value="">选择需要调整的表格</option>
                  {tables.map((table, index) => (
                    <option key={table.attrs.id} value={table.attrs.id}>
                      {index + 1} · {table.attrs.caption || "未填说明"} ·{" "}
                      {table.content.length}行{" "}
                      {table.attrs.column_widths_twips.length}列
                    </option>
                  ))}
                </select>
              </label>
              <label>
                起始行
                <input
                  type="number"
                  min={1}
                  value={firstRow}
                  onChange={(event) => setFirstRow(Number(event.target.value))}
                />
              </label>
              <label>
                起始列
                <input
                  type="number"
                  min={1}
                  value={firstColumn}
                  onChange={(event) =>
                    setFirstColumn(Number(event.target.value))
                  }
                />
              </label>
              <label>
                合并行数
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={rowSpan}
                  onChange={(event) => setRowSpan(Number(event.target.value))}
                />
              </label>
              <label>
                合并列数
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={columnSpan}
                  onChange={(event) =>
                    setColumnSpan(Number(event.target.value))
                  }
                />
              </label>
              <button
                type="button"
                className="button secondary"
                disabled={!current}
                onClick={() => changeTable("merge")}
              >
                合并所选完整范围
              </button>
              <button
                type="button"
                className="text-button"
                disabled={!current}
                onClick={() => changeTable("split")}
              >
                拆分起始单元格
              </button>
            </fieldset>
          )}
          <AuthoringImagePicker
            key={`${memberId}:${bidId}`}
            bidId={bidId}
            memberId={memberId}
            disabled={disabled}
            maximumBytes={capabilities.image_upload_max_bytes}
            sourceRefs={document.attrs.source_refs}
            onSelect={(selected) => {
              setImage(selected);
              setAlt(selected.title);
            }}
          />
          {image && (
            <fieldset disabled={disabled} className="authoring-rich-form">
              <legend>
                明确插入：{image.title} · 版本 {image.revision}
              </legend>
              <label>
                图片宽度（厘米，按原比例）
                <input
                  type="number"
                  min={0.1}
                  max={35}
                  step={0.1}
                  value={imageWidth}
                  onChange={(event) =>
                    setImageWidth(Number(event.target.value))
                  }
                />
              </label>
              <label>
                图片内容说明
                <input
                  value={alt}
                  maxLength={1000}
                  onChange={(event) => setAlt(event.target.value)}
                />
              </label>
              <label>
                图注
                <input
                  value={imageCaption}
                  maxLength={1000}
                  onChange={(event) => setImageCaption(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="button secondary"
                disabled={!alt.trim()}
                onClick={addImage}
              >
                插入此图片版本到章末
              </button>
            </fieldset>
          )}
          <p className="small-note">
            当前接口未对外部 Word
            的结构导入作承诺。图片与表格的实际分页、遮挡、目录和章页范围，以固定构建的逐项结果及原页核对为准。
          </p>
          <ErrorNotice error={error} />
        </>
      )}
    </details>
  );
}
