import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { Evidence } from "./Evidence";
import { api, objectFetch } from "./api";
import {
  sourceDocument,
  sourceEvidence,
  sourceGrant,
} from "./sourceSurfaceFixtures.test-support";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
  objectFetch: vi.fn(),
}));
vi.mock("./PdfPreview", () => ({ PdfPreview: () => <div>PDF</div> }));
vi.mock("./PartialPageSelection", () => ({ PartialPageSelection: () => null }));
vi.mock("./SourceSurface", () => ({
  SourceSurface: ({
    children,
    onClose,
  }: {
    children: (single: boolean) => ReactNode;
    onClose: () => void;
  }) => (
    <div>
      <button onClick={onClose}>关闭侧栏</button>
      {children(false)}
    </div>
  ),
}));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const result = <T,>(data: T) => ({ data, etag: null });
const createUrl = vi.fn(() => "blob:source");
beforeEach(() => {
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) =>
      result(path.endsWith("/evidence") ? sourceEvidence : sourceGrant),
    );
  vi.mocked(objectFetch).mockReset();
  createUrl.mockClear();
  vi.stubGlobal(
    "URL",
    Object.assign(class extends URL {}, {
      createObjectURL: createUrl,
      revokeObjectURL: vi.fn(),
    }),
  );
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function show() {
  const onClose = vi.fn();
  const view = render(<Evidence document={sourceDocument} onClose={onClose} />);
  await screen.findByRole("button", { name: /下载资料原件/ });
  return { ...view, onClose };
}
const start = () =>
  fireEvent.click(screen.getByRole("button", { name: /下载资料原件/ }));

it.each(["关闭原件", "关闭侧栏", "unmount"])(
  "ignores late grants after %s",
  async (close) => {
    const view = await show();
    const pending = deferred<ReturnType<typeof result<typeof sourceGrant>>>();
    vi.mocked(api).mockReturnValueOnce(pending.promise);
    start();
    if (close === "unmount") view.unmount();
    else fireEvent.click(screen.getByRole("button", { name: close }));
    await act(async () => {
      pending.resolve(result(sourceGrant));
    });
    expect(objectFetch).not.toHaveBeenCalled();
    expect(createUrl).not.toHaveBeenCalled();
  },
);

it("does not read bytes from a response that arrives after close", async () => {
  await show();
  const pending = deferred<Response>();
  const blob = vi.fn().mockResolvedValue(new Blob(["old"]));
  vi.mocked(objectFetch).mockReturnValueOnce(pending.promise);
  await act(async () => {
    start();
  });
  expect(objectFetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "关闭原件" }));
  await act(async () => {
    pending.resolve({ ok: true, blob } as unknown as Response);
  });
  expect(blob).not.toHaveBeenCalled();
});

it("does not download a blob that finishes after unmount", async () => {
  const view = await show();
  const pending = deferred<Blob>();
  const blob = vi.fn(() => pending.promise);
  vi.mocked(objectFetch).mockResolvedValueOnce({
    ok: true,
    blob,
  } as unknown as Response);
  await act(async () => {
    start();
  });
  expect(blob).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => {
    pending.resolve(new Blob(["old"]));
  });
  expect(createUrl).not.toHaveBeenCalled();
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});

it.each(["grant", "error"])(
  "ignores a late old %s after a document switch and allows new downloads",
  async (kind) => {
    const view = await show();
    const pending = deferred<ReturnType<typeof result<typeof sourceGrant>>>();
    vi.mocked(api).mockReturnValueOnce(pending.promise);
    start();
    const newer = {
      ...sourceDocument,
      id: "source-v2",
      file_head_version_id: "source-v2",
    };
    const newGrant = {
      ...sourceGrant,
      artifact_id: newer.id,
      download_url: "/new.pdf",
    };
    vi.mocked(api).mockImplementation(async (path) =>
      result(
        path.endsWith("/evidence")
          ? { ...sourceEvidence, document_version_id: newer.id, items: [] }
          : newGrant,
      ),
    );
    view.rerender(<Evidence document={newer} onClose={view.onClose} />);
    expect(
      await screen.findByRole("button", { name: /下载资料原件/ }),
    ).toBeEnabled();
    await act(async () => {
      if (kind === "grant") pending.resolve(result(sourceGrant));
      else pending.reject(new Error("old download failure"));
    });
    expect(objectFetch).not.toHaveBeenCalled();
    expect(screen.queryByText("old download failure")).not.toBeInTheDocument();
    vi.mocked(objectFetch).mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["new"]),
    } as Response);
    await act(async () => {
      start();
    });
    expect(objectFetch).toHaveBeenCalledWith("/new.pdf");
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  },
);

it("suppresses duplicate starts but permits a subsequent deliberate download", async () => {
  await show();
  const pending = deferred<ReturnType<typeof result<typeof sourceGrant>>>();
  vi.mocked(api).mockClear().mockReturnValueOnce(pending.promise);
  const button = screen.getByRole("button", { name: /下载资料原件/ });
  act(() => {
    button.click();
    button.click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  vi.mocked(objectFetch).mockResolvedValue({
    ok: true,
    blob: async () => new Blob(["source"]),
  } as Response);
  await act(async () => {
    pending.resolve(result(sourceGrant));
  });
  expect(createUrl).toHaveBeenCalledTimes(1);
  await act(async () => {
    start();
  });
  expect(createUrl).toHaveBeenCalledTimes(2);
});
