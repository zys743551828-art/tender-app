import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SourceEditor } from "./SourceEditor";
import {
  readAuthoringContent,
  serializeAuthoringContent,
} from "./richEditorSchema";
import {
  importCandidateWithImage,
  importScope,
} from "./authoringWordImportFixtures.test-support";

afterEach(cleanup);
it.each([
  [2400, 1600],
  [2400, 2400],
  [12000, 6000],
])("编辑器保留 %i × %i twips 放置比例和原始绑定内容", (width, height) => {
  const candidate = importCandidateWithImage();
  const content = candidate.sections[0].content as {
    content: { type: string; attrs?: Record<string, unknown> }[];
  };
  const attrs = content.content.find((node) => node.type === "image")!.attrs!;
  attrs.width_twips = width;
  attrs.height_twips = height;
  const value = readAuthoringContent(content, true);
  const before = serializeAuthoringContent(value);
  const onChange = vi.fn();
  const props = {
    bidId: importScope.bidId,
    value,
    onChange,
    onTarget: vi.fn(),
  };
  const view = render(<SourceEditor {...props} />);
  const image = screen.getByRole("img", { name: "合成示意图" });
  expect(image).toHaveStyle({
    width: `${width / 15}px`,
    aspectRatio: `${width} / ${height}`,
  });
  expect((image as HTMLImageElement).style.height).toBe("");
  expect(image.closest("figure")).toHaveAttribute(
    "data-node-id",
    String(attrs.id),
  );
  expect(image).toHaveAttribute(
    "src",
    `/api/v1/bids/${importScope.bidId}/authoring-images/${attrs.asset_id}/versions/${attrs.asset_version_id}/bytes/normalized`,
  );
  expect(screen.getByRole("textbox", { name: "章节正文" })).toHaveAttribute(
    "contenteditable",
    "true",
  );
  view.rerender(<SourceEditor {...props} disabled />);
  expect(screen.getByRole("textbox", { name: "章节正文" })).toHaveAttribute(
    "contenteditable",
    "false",
  );
  expect(serializeAuthoringContent(value)).toEqual(before);
  expect(onChange).not.toHaveBeenCalled();
});
