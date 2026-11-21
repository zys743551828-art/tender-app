import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ArtifactActions } from "./ArtifactActions";
import { api, objectFetch } from "./api";
import { StrictMode } from "react";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
  objectFetch: vi.fn(),
}));
vi.mock("./Evidence", () => ({
  Evidence: ({
    document,
    onClose,
    contextNotice,
  }: {
    document: { id: string };
    onClose: () => void;
    contextNotice: string;
  }) => (
    <div role="dialog" aria-label="文件预览">
      {document.id}
      <p>{contextNotice}</p>
      <button onClick={onClose}>关闭原件</button>
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
const metadata = (id = "first", bid = "bid") => ({
  data: {
    id,
    bid_id: bid,
    media_type: "application/pdf",
    artifact_kind: "bid_body",
    filename: `登记版本-${id}.pdf`,
    byte_size: 6,
    sha256: "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d",
  },
  etag: null,
});
const props = { bidId: "bid", documentId: "first", isPdf: true };
const grant = (id = "first") => ({
  data: {
    artifact_id: id,
    download_url: `/bytes/${id}`,
    filename: `${id}.pdf`,
  },
  etag: null,
});
const createUrl = vi.fn(() => "blob:artifact");
beforeEach(() => {
  vi.mocked(api).mockReset();
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

it("does not request a download grant when metadata arrives after unmount", async () => {
  const pending = deferred<ReturnType<typeof metadata>>();
  vi.mocked(api).mockReturnValueOnce(pending.promise);
  const view = render(<ArtifactActions {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  view.unmount();
  await act(async () => {
    pending.resolve(metadata());
  });
  expect(api).toHaveBeenCalledTimes(1);
  expect(objectFetch).not.toHaveBeenCalled();
});

it("clears the previous preview when the document changes", async () => {
  vi.mocked(api).mockResolvedValueOnce(metadata());
  const view = render(<ArtifactActions {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
  expect(await screen.findByRole("dialog")).toHaveTextContent("first");
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "当前预览的是这条记录引用的文件版本",
  );
  view.rerender(<ArtifactActions {...props} documentId="second" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("discards late authorization after unmount without fetching bytes", async () => {
  const pending = deferred<ReturnType<typeof grant>>();
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockReturnValueOnce(pending.promise);
  const view = render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  });
  expect(api).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(async () => {
    pending.resolve(grant());
  });
  expect(objectFetch).not.toHaveBeenCalled();
});

it("does not read a late byte response after scope change", async () => {
  const pending = deferred<Response>();
  const arrayBuffer = vi.fn();
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  vi.mocked(objectFetch).mockReturnValueOnce(pending.promise);
  const view = render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  });
  expect(objectFetch).toHaveBeenCalledTimes(1);
  view.rerender(<ArtifactActions {...props} documentId="second" />);
  await act(async () => {
    pending.resolve({ ok: true, arrayBuffer } as unknown as Response);
  });
  expect(vi.mocked(objectFetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(arrayBuffer).not.toHaveBeenCalled();
  expect(createUrl).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "下载此版本文件" })).toBeEnabled();
});

it("does not initiate a browser download when bytes arrive after unmount", async () => {
  const pending = deferred<ArrayBuffer>();
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  const arrayBuffer = vi.fn(() => pending.promise);
  vi.mocked(objectFetch).mockResolvedValueOnce({
    ok: true,
    arrayBuffer,
  } as unknown as Response);
  const view = render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  });
  expect(arrayBuffer).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => {
    pending.resolve(new TextEncoder().encode("source").buffer);
  });
  expect(createUrl).not.toHaveBeenCalled();
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});

it.each(["metadata", "error"])(
  "does not replace the new scope preview with a late old %s",
  async (kind) => {
    const pending = deferred<ReturnType<typeof metadata>>();
    vi.mocked(api)
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(metadata("second", "new-bid"));
    const view = render(<ArtifactActions {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
    view.rerender(
      <ArtifactActions {...props} bidId="new-bid" documentId="second" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("second");
    await act(async () => {
      if (kind === "metadata") pending.resolve(metadata());
      else pending.reject(new Error("late old failure"));
    });
    expect(screen.getByRole("dialog")).toHaveTextContent("second");
    expect(screen.queryByText("late old failure")).not.toBeInTheDocument();
  },
);

it("invalidates the old request when the expected qualification changes", async () => {
  const pending = deferred<ReturnType<typeof metadata>>();
  vi.mocked(api).mockReturnValueOnce(pending.promise);
  const view = render(
    <ArtifactActions {...props} expectedArtifactKind="bid_body" />,
  );
  fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
  view.rerender(
    <ArtifactActions {...props} expectedArtifactKind="review_report" />,
  );
  await act(async () => {
    pending.resolve(metadata());
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看此版PDF原页" })).toBeEnabled();
});

it("suppresses same-turn repeated clicks and allows a new explicit download after completion", async () => {
  const pending = deferred<ReturnType<typeof metadata>>();
  vi.mocked(api)
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce(grant());
  vi.mocked(objectFetch).mockImplementation(async () => new Response("source"));
  render(
    <StrictMode>
      <ArtifactActions {...props} />
    </StrictMode>,
  );
  const button = screen.getByRole("button", { name: "下载此版本文件" });
  act(() => {
    button.click();
    button.click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => {
    pending.resolve(metadata());
  });
  await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(1));
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  });
  await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(2));
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(2);
});

it("allows retry after a current failure and closes/reopens the same preview", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("current failure"));
  render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
  });
  expect(screen.getByText("current failure")).toBeInTheDocument();
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(metadata());
  fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
  await screen.findByRole("dialog");
  expect(screen.queryByText("current failure")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "关闭原件" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看此版PDF原页" }));
  expect(await screen.findByRole("dialog")).toHaveTextContent("first");
});

it.each(["sourcE", "short"])(
  "rejects mismatched bytes (%s) and saves a verified retry under the registered name",
  async (wrong) => {
    vi.mocked(api).mockImplementation(async (path) =>
      path.endsWith("/download") ? grant() : metadata(),
    );
    vi.mocked(objectFetch)
      .mockResolvedValueOnce(new Response(wrong))
      .mockResolvedValueOnce(new Response("source"));
    const names: string[] = [];
    vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    render(<ArtifactActions {...props} />);
    const download = () =>
      fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
    download();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "原件摘要或大小不一致",
    );
    expect(createUrl).not.toHaveBeenCalled();
    download();
    await waitFor(() => expect(names).toEqual(["登记版本-first.pdf"]));
    expect(objectFetch).toHaveBeenCalledTimes(2);
    expect(api).toHaveBeenCalledTimes(4);
  },
);

it("cancels a pending download before saving and allows a new explicit download during the old hash", async () => {
  const verified = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode("source"),
  );
  const pending = deferred<ArrayBuffer>();
  const digest = vi
    .spyOn(crypto.subtle, "digest")
    .mockReturnValueOnce(pending.promise);
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith("/download") ? grant() : metadata(),
  );
  vi.mocked(objectFetch).mockImplementation(async () => new Response("source"));
  render(<ArtifactActions {...props} suggestedFilename="合成报告.pdf" />);
  const download = () =>
    fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  download();
  await waitFor(() => expect(digest).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "取消下载" }));
  expect(vi.mocked(objectFetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  download();
  await waitFor(() =>
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1),
  );
  await act(async () => pending.resolve(verified));
  expect(createUrl).toHaveBeenCalledTimes(1);
  expect(
    vi.mocked(HTMLAnchorElement.prototype.click).mock.contexts[0],
  ).toHaveProperty("download", "合成报告.pdf");
  expect(objectFetch).toHaveBeenCalledTimes(2);
});

it("rejects malformed registration before asking for a download grant", async () => {
  vi.mocked(api).mockResolvedValueOnce({
    ...metadata(),
    data: { ...metadata().data, sha256: "" },
  });
  render(<ArtifactActions {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "下载此版本文件" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "缺少有效的文件摘要或字节数",
  );
  expect(api).toHaveBeenCalledTimes(1);
  expect(objectFetch).not.toHaveBeenCalled();
});
