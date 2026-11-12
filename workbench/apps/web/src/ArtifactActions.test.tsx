import { act, fireEvent, render, screen } from "@testing-library/react";
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
  }: {
    document: { id: string };
    onClose: () => void;
  }) => (
    <div role="dialog" aria-label="文件预览">
      {document.id}
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
  fireEvent.click(screen.getByRole("button", { name: "下载生成文件" }));
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
    fireEvent.click(screen.getByRole("button", { name: "下载生成文件" }));
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
  const blob = vi.fn().mockResolvedValue(new Blob(["old output"]));
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  vi.mocked(objectFetch).mockReturnValueOnce(pending.promise);
  const view = render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载生成文件" }));
  });
  expect(objectFetch).toHaveBeenCalledTimes(1);
  view.rerender(<ArtifactActions {...props} documentId="second" />);
  await act(async () => {
    pending.resolve({ ok: true, blob } as unknown as Response);
  });
  expect(blob).not.toHaveBeenCalled();
  expect(createUrl).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "下载生成文件" })).toBeEnabled();
});

it("does not initiate a browser download when blob completes after unmount", async () => {
  const pending = deferred<Blob>();
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  const blob = vi.fn(() => pending.promise);
  vi.mocked(objectFetch).mockResolvedValueOnce({
    ok: true,
    blob,
  } as unknown as Response);
  const view = render(<ArtifactActions {...props} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载生成文件" }));
  });
  expect(blob).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => {
    pending.resolve(new Blob(["old output"]));
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
  vi.mocked(objectFetch).mockResolvedValue({
    ok: true,
    blob: async () => new Blob(["output"]),
  } as Response);
  render(
    <StrictMode>
      <ArtifactActions {...props} />
    </StrictMode>,
  );
  const button = screen.getByRole("button", { name: "下载生成文件" });
  act(() => {
    button.click();
    button.click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => {
    pending.resolve(metadata());
  });
  expect(createUrl).toHaveBeenCalledTimes(1);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  vi.mocked(api)
    .mockResolvedValueOnce(metadata())
    .mockResolvedValueOnce(grant());
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "下载生成文件" }));
  });
  expect(createUrl).toHaveBeenCalledTimes(2);
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
