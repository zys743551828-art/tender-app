import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Download from "./PackageReviewReportDownload";
import { packageReviewReportFixture } from "../qa-previews/frozen-inputs/packageReviewReport";
const fetchMock = vi.fn(),
  create = vi.fn(() => "blob:synthetic-report");
let f: Awaited<ReturnType<typeof packageReviewReportFixture>>;
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
  fetchMock.mockReset();
  create.mockClear();
  f = await packageReviewReportFixture();
  const NativeURL = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeURL {
      static createObjectURL = create;
      static revokeObjectURL = vi.fn();
    },
  );
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  fetchMock.mockImplementation(async (url: string) => {
    if (url === `/api/v1/documents/${f.document.id}`) return json(f.document);
    if (url === `/api/v1/artifacts/${f.document.id}/download`)
      return json(f.grant);
    if (url === f.grant.download_url) return new Response(f.bytes);
    throw new Error(`unexpected synthetic download ${url}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("downloads only the bound report artifact after metadata, grant, size and content-digest verification", async () => {
  render(<Download report={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "下载本份 Word 报告" }),
  );
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(3);
  const options = fetchMock.mock.calls[2][1] as RequestInit;
  expect(options.credentials).toBe("omit");
  expect(new Headers(options.headers).has("X-CSRF-Token")).toBe(false);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
});
it.each([
  "wrong-kind",
  "wrong-grant-kind",
  "wrong-metadata-digest",
  "wrong-bytes",
])("does not download a substituted or corrupt artifact: %s", async (kind) => {
  if (kind === "wrong-kind") f.document.artifact_kind = "source_original";
  if (kind === "wrong-grant-kind") f.grant.artifact_kind = "submission_body";
  if (kind === "wrong-metadata-digest") f.document.sha256 = "0".repeat(64);
  if (kind === "wrong-bytes") f.bytes[0] ^= 1;
  render(<Download report={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "下载本份 Word 报告" }),
  );
  await screen.findByText(
    kind === "wrong-bytes"
      ? /实际报告字节与已发布摘要不符/
      : kind === "wrong-grant-kind"
        ? /下载授权与这份报告不符/
        : /报告文件的用途、原运行产物摘要或格式不符/,
  );
  expect(create).not.toHaveBeenCalled();
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});
it("does not trigger a late download after the original report is unmounted", async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = render(<Download report={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "下载本份 Word 报告" }),
  );
  view.unmount();
  await act(async () => {
    resolve(json(f.document));
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(create).not.toHaveBeenCalled();
});
