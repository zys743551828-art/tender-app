import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AuthoringRichSnapshot } from "./AuthoringRichSnapshot";
import type { AuthoringImageView } from "./contracts";
import {
  importCandidate,
  importCandidateWithImage,
  importId,
  importImageBytes,
  importScope,
} from "./authoringWordImportFixtures.test-support";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function setup() {
  const candidate = importCandidateWithImage();
  const image: AuthoringImageView = {
    id: importId(31),
    bid_id: importScope.bidId,
    asset_id: importId(30),
    revision: 1,
    previous_revision: null,
    previous_version_id: null,
    state: "active",
    reason: "合成测试图片",
    original_blob_id: importId(40),
    normalized_blob_id: importId(41),
    original_media_type: "image/png",
    width_px: 2,
    height_px: 2,
    normalization_proof: {
      protocol: "authoring-raster-normalization/1",
      output_digest: candidate.images[0].digest,
      output_byte_size: importImageBytes.length,
      output_media_type: "image/png",
      width_px: 2,
      height_px: 2,
    },
    source_refs: [],
    digest: "a".repeat(64),
    created_by: importScope.memberId,
    created_at: "2026-10-21T10:00:00Z",
    title: "合成图片",
    head_revision: 2,
    head_version_id: importId(42),
    is_current: false,
    etag: '"image-2"',
  };
  const state = {
    image,
    bytes: importImageBytes.slice(),
    hold: null as null | (() => Promise<Response>),
  };
  const fetch = vi.fn(async (input: string) => {
    if (String(input).endsWith("/bytes/normalized"))
      return state.hold
        ? state.hold()
        : new Response(state.bytes, {
            headers: { "Content-Type": "image/png" },
          });
    return new Response(JSON.stringify(state.image), {
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  const create = vi.fn(() => "blob:historical-image"),
    revoke = vi.fn();
  const OriginalURL = globalThis.URL;
  vi.stubGlobal(
    "URL",
    class extends OriginalURL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  const ready = vi.fn();
  const show = () =>
    render(
      <AuthoringRichSnapshot
        bidId={importScope.bidId}
        content={candidate.sections[0].content}
        label="修改前完整正文"
        onReady={ready}
      />,
    );
  return { candidate, state, fetch, create, revoke, ready, show };
}
function loadedImage(element: HTMLElement) {
  Object.defineProperty(element, "naturalWidth", {
    configurable: true,
    value: 2,
  });
  Object.defineProperty(element, "naturalHeight", {
    configurable: true,
    value: 2,
  });
  fireEvent.load(element);
}

it("完整表格保留合并单元格，修改标记不会将未选内容拍平成文字", async () => {
  const candidate = importCandidate(),
    ready = vi.fn();
  render(
    <AuthoringRichSnapshot
      bidId={importScope.bidId}
      content={candidate.sections[1].content}
      label="完整候选"
      changedNodeIds={[importId(27)]}
      onReady={ready}
    />,
  );
  expect(
    screen.getByRole("columnheader", { name: "合并表头" }),
  ).toHaveAttribute("colspan", "2");
  expect(screen.getByText("第一阶段")).toHaveClass("rich-snapshot-changed");
  expect(screen.getByText("120天")).not.toHaveClass("rich-snapshot-changed");
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(true));
});

it("按确切历史版本核对PNG后显示，不替换为当前头；卸载回收URL", async () => {
  const fixture = setup(),
    view = fixture.show();
  const image = await screen.findByRole("img", { name: "合成示意图" });
  expect(fixture.ready).toHaveBeenLastCalledWith(false);
  loadedImage(image);
  await waitFor(() => expect(fixture.ready).toHaveBeenLastCalledWith(true));
  expect(screen.getByText(/历史版本；当前图片头已变化/)).toBeInTheDocument();
  expect(fixture.fetch.mock.calls.map((call) => String(call[0]))).toEqual([
    `/api/v1/bids/${importScope.bidId}/authoring-images/${importId(30)}/versions/${importId(31)}`,
    `/api/v1/bids/${importScope.bidId}/authoring-images/${importId(30)}/versions/${importId(31)}/bytes/normalized`,
  ]);
  view.unmount();
  expect(fixture.revoke).toHaveBeenCalledWith("blob:historical-image");
});

it("另一项目或版本的图片元数据不能授权读取图片字节", async () => {
  const fixture = setup();
  fixture.state.image.bid_id = importId(999);
  fixture.show();
  await screen.findByText(/图片的项目、历史版本或规范字节证明不一致/);
  expect(fixture.fetch).toHaveBeenCalledTimes(1);
  expect(fixture.create).not.toHaveBeenCalled();
  expect(fixture.ready).toHaveBeenLastCalledWith(false);
});

it("同长度错误SHA的图片不会被标为可确认", async () => {
  const fixture = setup();
  fixture.state.bytes[0] ^= 1;
  fixture.show();
  await screen.findByText(/图片摘要与保存证明不一致/);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(fixture.create).not.toHaveBeenCalled();
  expect(fixture.ready).toHaveBeenLastCalledWith(false);
});

it("图片加载中离开后，迟到字节不能创建遗留Blob URL", async () => {
  const fixture = setup();
  let finish: ((response: Response) => void) | undefined;
  fixture.state.hold = () =>
    new Promise<Response>((resolve) => {
      finish = resolve;
    });
  const view = fixture.show();
  await waitFor(() => expect(fixture.fetch).toHaveBeenCalledTimes(2));
  view.unmount();
  await act(async () => {
    finish!(
      new Response(importImageBytes, {
        headers: { "Content-Type": "image/png" },
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  expect(fixture.create).not.toHaveBeenCalled();
});

it("未知结构拒绝预览并保持未确认，不能静默丢失节点", async () => {
  const ready = vi.fn();
  render(
    <AuthoringRichSnapshot
      bidId={importScope.bidId}
      content={{ type: "doc", content: [{ type: "unknown" }] }}
      label="无效候选"
      onReady={ready}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("章节结构无法完整核对");
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(false));
});
