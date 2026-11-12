import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WordImportRichPreview } from "./WordImportRichPreview";
import {
  importCandidateWithImage,
  importImageBytes,
  importScope,
} from "./authoringWordImportFixtures.test-support";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([
  [2400, 2400],
  [2400, 1600],
  [12000, 6000],
])(
  "图片按声明的 %i × %i twips 放置，不以像素比例覆盖",
  async (width, height) => {
    const candidate = importCandidateWithImage();
    const content = candidate.sections[0].content as {
      content: { type: string; attrs?: Record<string, unknown> }[];
    };
    const imageNode = content.content.find((node) => node.type === "image")!;
    imageNode.attrs!.width_twips = width;
    imageNode.attrs!.height_twips = height;
    const revoke = vi.fn();
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = vi.fn(() => "blob:placement-preview");
        static revokeObjectURL = revoke;
      },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(importImageBytes.slice(), {
            headers: {
              "Content-Type": "image/png",
              "Content-Length": String(importImageBytes.length),
            },
          }),
      ),
    );
    const onStatus = vi.fn();
    const view = render(
      <WordImportRichPreview
        scope={importScope}
        candidate={candidate}
        section={candidate.sections[0]}
        onImageStatus={onStatus}
      />,
    );
    const image = await screen.findByRole("img", { name: "合成示意图" });
    expect(image).toHaveStyle({
      width: `${width / 15}px`,
      aspectRatio: `${width} / ${height}`,
    });
    Object.defineProperties(image, {
      naturalWidth: { value: 2 },
      naturalHeight: { value: 2 },
    });
    fireEvent.load(image);
    expect(onStatus).toHaveBeenLastCalledWith(candidate.images[0].key, "ready");
    view.unmount();
    expect(revoke).toHaveBeenCalledWith("blob:placement-preview");
  },
);
