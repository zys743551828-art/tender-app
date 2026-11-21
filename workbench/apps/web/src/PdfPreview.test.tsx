import { render, screen } from "@testing-library/react";
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
afterEach(() => vi.unstubAllGlobals());

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

it("does not impose the new historical hash condition on the general evidence renderer", async () => {
  setup();
  await vi.waitFor(() => expect(getDocument).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("passes byte-matched historical PDFs to the physical page renderer", async () => {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  setup(
    Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
  await vi.waitFor(() => expect(getDocument).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).toBeNull();
});
