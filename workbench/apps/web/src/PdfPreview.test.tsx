import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { objectFetch } from "./api";
import { PdfPreview } from "./PdfPreview";

const { getDocument } = vi.hoisted(() => ({ getDocument: vi.fn() }));
vi.mock("pdfjs-dist/legacy/build/pdf.mjs", () => ({
  GlobalWorkerOptions: {},
  getDocument,
}));
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  objectFetch: vi.fn(),
}));

const done = () => undefined;
const bytes = new TextEncoder().encode("%PDF synthetic original").buffer;

beforeEach(() => {
  vi.mocked(objectFetch).mockReset();
  getDocument.mockReset();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function setup(expectedSha256?: string) {
  vi.mocked(objectFetch).mockResolvedValue({
    ok: true,
    arrayBuffer: async () => bytes,
  } as Response);
  getDocument.mockReturnValue({
    promise: new Promise(() => {}),
    destroy: vi.fn(),
  });
  render(
    <PdfPreview
      url="https://fixture.test/document.pdf"
      filename="合成.pdf"
      page={2}
      expectedSha256={expectedSha256}
      onPageCount={done}
      onRefresh={done}
    />,
  );
}

it("refuses a changed PDF before loading it into the historical physical page renderer", async () => {
  setup("a".repeat(64));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "原件字节与固定版本摘要不一致",
  );
  expect(screen.queryByRole("img")).toBeNull();
  expect(getDocument).not.toHaveBeenCalled();
});

it("opens a previously verified local PDF without hashing it again", async () => {
  setup();
  await vi.waitFor(() => expect(getDocument).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).toBeNull();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it.each(["header", "record", "unknown"])(
  "shows received bytes during a delayed %s-length transfer before verification, loading and drawing",
  async (kind) => {
    const total = 2 * 1024 * 1024;
    const chunk = new Uint8Array(total / 2);
    let feed!: ReadableStreamDefaultController<Uint8Array>;
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          feed = controller;
        },
      }),
      {
        headers: kind === "header" ? { "Content-Length": String(total) } : {},
      },
    );
    const checked = deferred<ArrayBuffer>();
    vi.spyOn(crypto.subtle, "digest").mockReturnValueOnce(checked.promise);
    const opening = deferred<{
      numPages: number;
      getPage: () => Promise<never>;
    }>();
    getDocument.mockReturnValue({ promise: opening.promise, destroy: vi.fn() });
    vi.mocked(objectFetch).mockResolvedValue(response);
    render(
      <PdfPreview
        url="/fixture.pdf"
        filename="合成.pdf"
        expectedSha256={"0".repeat(64)}
        byteSize={kind === "record" ? total : undefined}
        page={2}
        onPageCount={done}
        onRefresh={done}
      />,
    );
    await screen.findByText("正在取回 PDF 原件…");
    await act(async () => feed.enqueue(chunk));
    await screen.findByText(
      kind === "unknown" ? "已收到 1.0 MB" : "已收到 1.0 MB / 2.0 MB",
    );
    expect(screen.queryByRole("img")).toBeNull();
    if (kind === "unknown")
      expect(screen.queryByRole("progressbar")).toBeNull();
    else
      expect(screen.getByRole("progressbar")).toHaveAttribute(
        "value",
        String(chunk.byteLength),
      );
    await act(async () => {
      feed.enqueue(chunk);
      feed.close();
    });
    await screen.findByText("正在核验原件摘要…");
    expect(getDocument).not.toHaveBeenCalled();
    await act(async () => checked.resolve(new ArrayBuffer(32)));
    await screen.findByText("正在载入 PDF 文档…");
    await act(async () =>
      opening.resolve({ numPages: 3, getPage: () => new Promise(() => {}) }),
    );
    await screen.findByText("正在绘制物理页 2…");
    expect(objectFetch).toHaveBeenCalledTimes(1);
  },
);

it("aborts a streaming transfer on close and does not start the PDF reader", async () => {
  const cancel = vi.fn();
  const response = new Response(new ReadableStream({ cancel }));
  vi.mocked(objectFetch).mockResolvedValue(response);
  const view = render(
    <PdfPreview
      url="/fixture.pdf"
      filename="合成.pdf"
      page={1}
      onPageCount={done}
      onRefresh={done}
    />,
  );
  await screen.findByText("已收到 0 B");
  view.unmount();
  await waitFor(() => expect(cancel).toHaveBeenCalledTimes(1));
  expect(getDocument).not.toHaveBeenCalled();
  expect(objectFetch).toHaveBeenCalledTimes(1);
});

it("passes byte-matched historical PDFs to the physical page renderer", async () => {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  setup(
    Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
  await vi.waitFor(() => expect(getDocument).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).toBeNull();
});
