import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Original from "./DocumentParseOriginal";
import {
  documentParseTestFixture,
  documentParseTestId as id,
} from "./documentParseTestFixture";

vi.mock("./PdfPreview", () => ({
  PdfPreview: ({
    url,
    filename,
    page,
  }: {
    url: string;
    filename: string;
    page: number;
  }) => (
    <div
      role="img"
      aria-label={`${filename}，物理页${page}原页`}
      data-url={url}
    >
      Synthetic PDF renderer boundary
    </div>
  ),
}));
const fetchMock = vi.fn(),
  createUrl = vi.fn(() => "blob:synthetic-verified-original"),
  revokeUrl = vi.fn();
let f: Awaited<ReturnType<typeof documentParseTestFixture>>;
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = createUrl;
      static revokeObjectURL = revokeUrl;
    },
  );
  f = await documentParseTestFixture();
  fetchMock.mockReset();
  createUrl.mockClear();
  revokeUrl.mockClear();
  fetchMock.mockImplementation(async (url: string) => {
    if (url === `/api/v1/documents/${f.scope.documentId}`)
      return json(f.document);
    if (url === `/api/v1/artifacts/${f.scope.documentId}/download`)
      return json(f.grant);
    if (url === f.grant.download_url) return new Response(f.bytes);
    throw new Error(`unexpected synthetic original ${url}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("opens verified exact bytes without reading or substituting the latest parse evidence list", async () => {
  const mounted = render(<Original view={f.completed} />);
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "查看本次解析绑定的 PDF 原页" }),
  );
  const preview = await screen.findByRole("img", {
    name: "合成解析样例.pdf，物理页1原页",
  });
  expect(preview).toHaveAttribute(
    "data-url",
    "blob:synthetic-verified-original",
  );
  expect(fetchMock.mock.calls).toHaveLength(3);
  expect(
    fetchMock.mock.calls.some(([url]) => String(url).endsWith("/evidence")),
  ).toBe(false);
  mounted.unmount();
  expect(revokeUrl).toHaveBeenCalledWith("blob:synthetic-verified-original");
});
it("rejects a different document before requesting its bytes", async () => {
  f.document = { ...f.document, id: id(88) };
  render(<Original view={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "查看本次解析绑定的 PDF 原页" }),
  );
  await screen.findByText(/原件的项目、版本或字节摘要与这次解析不符/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(createUrl).not.toHaveBeenCalled();
});
it("rejects a mismatched download purpose before downloading", async () => {
  f.grant = { ...f.grant, artifact_kind: "review_report" };
  render(<Original view={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "查看本次解析绑定的 PDF 原页" }),
  );
  await screen.findByText(/原件访问授权与这次解析不符/);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(createUrl).not.toHaveBeenCalled();
});
it("rejects actual bytes whose hash differs from the retained original", async () => {
  const original = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((url: string, options: RequestInit) =>
    url === f.grant.download_url
      ? Promise.resolve(new Response("other bytes"))
      : original(url, options),
  );
  render(<Original view={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "查看本次解析绑定的 PDF 原页" }),
  );
  await screen.findByText(/取回的 PDF 字节与本次解析绑定的原件摘要不符/);
  expect(createUrl).not.toHaveBeenCalled();
});
it("releases preview bytes on explicit close", async () => {
  render(<Original view={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "查看本次解析绑定的 PDF 原页" }),
  );
  await screen.findByRole("img");
  await userEvent.click(screen.getByRole("button", { name: "关闭原页" }));
  await waitFor(() =>
    expect(screen.queryByRole("img")).not.toBeInTheDocument(),
  );
  expect(revokeUrl).toHaveBeenCalledWith("blob:synthetic-verified-original");
});
