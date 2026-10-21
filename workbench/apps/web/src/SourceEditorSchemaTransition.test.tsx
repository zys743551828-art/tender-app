import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SourceEditor } from "./SourceEditor";
import {
  readAuthoringContent,
  serializeAuthoringContent,
} from "./richEditorSchema";

const plain = {
  type: "doc",
  attrs: { title: "人工章节", ordinal: 0, rule_ids: [], source_refs: [] },
  content: [
    {
      type: "paragraph",
      attrs: { id: "original-paragraph" },
      content: [{ type: "text", text: "原章节正文" }],
    },
  ],
};
const image = {
  type: "image",
  attrs: {
    id: "fixed-image",
    asset_id: "00000000-0000-4000-8000-000000000001",
    asset_revision: 2,
    asset_version_id: "00000000-0000-4000-8000-000000000002",
    width_twips: 2000,
    height_twips: 1000,
    alt: "已经明确选择的版本图片",
    caption: "",
  },
};

it("文字章节升级为表图结构后预览固定图片版本，粘贴仍保留原正文和图片", () => {
  const onChange = vi.fn();
  const common = { bidId: "bid-1", onChange, onTarget: vi.fn() };
  const view = render(
    <SourceEditor {...common} value={readAuthoringContent(plain, false)} />,
  );
  view.rerender(
    <SourceEditor
      {...common}
      value={readAuthoringContent({
        ...plain,
        content: [...plain.content, image],
      })}
    />,
  );
  expect(screen.getByRole("img", { name: image.attrs.alt })).toHaveAttribute(
    "src",
    `/api/v1/bids/bid-1/authoring-images/${image.attrs.asset_id}/versions/${image.attrs.asset_version_id}/bytes/normalized`,
  );
  const editor = screen.getByRole("textbox", { name: "章节正文" });
  fireEvent.paste(editor, {
    clipboardData: {
      getData: (type: string) => (type === "text/plain" ? "补充的文字" : ""),
      files: [],
      items: [],
    },
  });
  expect(onChange).toHaveBeenCalled();
  const result = serializeAuthoringContent(onChange.mock.lastCall![0]);
  expect(result.content).toContainEqual(image);
  expect(JSON.stringify(result)).toContain("原章节正文");
  expect(JSON.stringify(result)).toContain("补充的文字");
});
