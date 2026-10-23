import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Evidence from "./PackageReviewEvidence";
import {
  packageReviewEvidence,
  packageReviewFixture,
} from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import type { DocumentView } from "./contracts";

vi.mock("./Evidence", () => ({
  Evidence: ({
    document,
    initialPage,
    contextNotice,
    onClose,
  }: {
    document: DocumentView;
    initialPage: number;
    contextNotice?: string;
    onClose: () => void;
  }) => (
    <div role="dialog" aria-label="已校验的引用原件">
      <p>
        {document.id} · 物理页 {initialPage}
      </p>
      <p>{contextNotice}</p>
      <button onClick={onClose}>关闭原页</button>
    </div>
  ),
}));
let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
const fetchMock = vi.fn();
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
  fixture = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const show = () =>
  render(
    <Evidence
      bidId={fixture.props.scope.bidId}
      document={fixture.documents[0]}
      quote={fixture.quotes[0]}
    />,
  );
const open = () =>
  userEvent.click(
    screen.getByRole("button", { name: "查看引用原页 · 物理页 2" }),
  );
it("opens only an explicitly requested, exact parse/page/text/file digest and labels withdrawn originals as historical", async () => {
  const source = packageReviewEvidence(fixture);
  source.evidence.source_status = "withdrawn";
  fetchMock
    .mockResolvedValueOnce(json(source.evidence))
    .mockResolvedValueOnce(json(source.document));
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  await open();
  await screen.findByRole("dialog", { name: "已校验的引用原件" });
  expect(screen.getByText(/来源当前已撤回/)).toBeInTheDocument();
  expect(
    screen.getByText(`${source.document.id} · 物理页 2`),
  ).toBeInTheDocument();
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    `/api/v1/evidence/${source.evidence.id}`,
    `/api/v1/documents/${source.document.id}`,
  ]);
});
it.each(["parse", "page", "text"])(
  "does not open an original for a mismatched %s",
  async (field) => {
    const source = packageReviewEvidence(fixture);
    if (field === "parse") source.evidence.parse_run_id = id(991);
    if (field === "page") source.evidence.physical_page = 3;
    if (field === "text") source.evidence.quote = "同页的其他文字";
    fetchMock.mockResolvedValueOnce(json(source.evidence));
    show();
    await open();
    await screen.findByText(/未打开其他原页/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  },
);
it.each(["bid", "bytes"])(
  "does not open a different original with a mismatched %s",
  async (field) => {
    const source = packageReviewEvidence(fixture);
    if (field === "bid") source.document.bid_id = id(991);
    else source.document.sha256 = "8".repeat(64);
    fetchMock
      .mockResolvedValueOnce(json(source.evidence))
      .mockResolvedValueOnce(json(source.document));
    show();
    await open();
    await screen.findByText(/未打开其他文件/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);
it("ignores a late original lookup after its requirement view has been unmounted", async () => {
  const source = packageReviewEvidence(fixture);
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = show();
  await open();
  view.unmount();
  await act(async () => {
    resolve(json(source.evidence));
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
