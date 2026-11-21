import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
const original = {
  ...sourceDocument,
  byte_size: 6,
  sha256: "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d", // "source"
};
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
  const view = render(<Evidence document={original} onClose={onClose} />);
  await screen.findByRole("button", { name: /下载资料原件/ });
  return { ...view, onClose };
}
const start = () =>
  fireEvent.click(screen.getByRole("button", { name: /下载资料原件/ }));

it.each([undefined, "invalid"])(
  "keeps a document without a valid registered digest out of the original renderer",
  async (sha256) => {
    render(
      <Evidence
        document={{ ...original, sha256 } as typeof original}
        onClose={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(/该版本缺少有效的原件 SHA-256 摘要/),
    ).toBeVisible();
    expect(screen.queryByText("PDF")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载资料原件" })).toBeNull();
    expect(vi.mocked(api).mock.calls.map(([path]) => path)).toEqual([
      `/documents/${original.id}/evidence`,
    ]);
  },
);

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
  const arrayBuffer = vi.fn();
  vi.mocked(objectFetch).mockReturnValueOnce(pending.promise);
  await act(async () => {
    start();
  });
  expect(objectFetch).toHaveBeenCalledTimes(1);
  const signal = vi.mocked(objectFetch).mock.calls[0][1]?.signal;
  fireEvent.click(screen.getByRole("button", { name: "关闭原件" }));
  expect(signal?.aborted).toBe(true);
  await act(async () => {
    pending.resolve({ ok: true, arrayBuffer } as unknown as Response);
  });
  expect(arrayBuffer).not.toHaveBeenCalled();
});

it("does not download a response that finishes reading after unmount", async () => {
  const view = await show();
  const pending = deferred<ArrayBuffer>();
  const arrayBuffer = vi.fn(() => pending.promise);
  vi.mocked(objectFetch).mockResolvedValueOnce({
    ok: true,
    arrayBuffer,
  } as unknown as Response);
  await act(async () => {
    start();
  });
  expect(arrayBuffer).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => {
    pending.resolve(new TextEncoder().encode("source").buffer);
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
      ...original,
      id: "source-v2",
      file_head_version_id: "source-v2",
      byte_size: 3,
      sha256:
        "11507a0e2f5e69d5dfa40a62a1bd7b6ee57e6bcd85c67c9b8431b36fff21c437", // "new"
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
    vi.mocked(objectFetch).mockResolvedValue(new Response("new"));
    await act(async () => {
      start();
    });
    expect(objectFetch).toHaveBeenCalledWith("/new.pdf", {
      signal: expect.any(AbortSignal),
    });
    await waitFor(() =>
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1),
    );
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
  vi.mocked(objectFetch).mockImplementation(async () => new Response("source"));
  await act(async () => {
    pending.resolve(result(sourceGrant));
  });
  await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(1));
  await act(async () => {
    start();
  });
  await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(2));
});

it.each(["sourcE", "short"])(
  "rejects changed object bytes (%s) and retries exactly once on request",
  async (wrong) => {
    await show();
    vi.mocked(objectFetch)
      .mockResolvedValueOnce(new Response(wrong))
      .mockResolvedValueOnce(new Response("source"));
    start();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "本版本的原件摘要或大小不一致",
    );
    expect(createUrl).not.toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() =>
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1),
    );
    expect(objectFetch).toHaveBeenCalledTimes(2);
  },
);

it("keeps a separate retry for evidence and failed file verification", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith("/evidence")) throw Error("合成解析依据读取中断");
    return result(sourceGrant);
  });
  await show();
  vi.mocked(objectFetch)
    .mockResolvedValueOnce(new Response("sourcE"))
    .mockResolvedValueOnce(new Response("source"));
  start();
  const warning = await screen.findByText(/本版本的原件摘要或大小不一致/);
  expect(screen.getByText("合成解析依据读取中断")).toBeVisible();
  fireEvent.click(
    within(warning.closest('[role="alert"]') as HTMLElement).getByRole(
      "button",
      { name: "重试" },
    ),
  );
  await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(1));
  expect(
    vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/evidence")),
  ).toHaveLength(1);
  expect(screen.getByText("合成解析依据读取中断")).toBeVisible();
});

it("discards a verified download if the drawer closes while hashing", async () => {
  await show();
  const pending = deferred<ArrayBuffer>();
  const verified = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode("source"),
  );
  const digest = vi
    .spyOn(crypto.subtle, "digest")
    .mockReturnValueOnce(pending.promise);
  vi.mocked(objectFetch).mockResolvedValueOnce(new Response("source"));
  start();
  await waitFor(() => expect(digest).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "关闭原件" }));
  await act(async () => pending.resolve(verified));
  expect(createUrl).not.toHaveBeenCalled();
});
