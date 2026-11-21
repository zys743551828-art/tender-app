import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useContext } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import type { BidPackageStoredView } from "./contracts";
import { PackageTechnicalDraftHandoff } from "./PackageTechnicalDraftHandoff";
import { TechnicalDraftContext } from "./technicalAuthoringHandoff";

const focus = {
  protocol: "technical-authoring-handoff/1",
  bid_id: id(1),
  package_id: id(2),
  revision_id: id(3),
  package_digest: "a".repeat(64),
  revision_status: "head_at_read",
  record: {
    member_id: "word",
    document_version_id: id(4),
    artifact_sha256: "b".repeat(64),
    format: "docx",
    build_id: id(5),
    snapshot_id: id(6),
    snapshot_digest: "c".repeat(64),
    parse_run_id: null,
  },
  independent_approval_available: false,
  publication_authorized: false,
};
function packageRevision(revisionId = focus.revision_id) {
  return {
    digest: focus.package_digest,
    manifest: {
      kind: "bid",
      package_id: focus.package_id,
      revision_id: revisionId,
      revision: 2,
      scope: { bid_id: focus.bid_id },
      members: [
        {
          member_id: focus.record.member_id,
          document_version_id: focus.record.document_version_id,
          file_digest: focus.record.artifact_sha256,
          parse: { parse_run_id: null, status: "not_frozen" },
        },
      ],
    },
  } as unknown as BidPackageStoredView;
}
const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code });
function Child() {
  const current = useContext(TechnicalDraftContext);
  return <div>{current ? "下方看到相同交接" : "下方不采用交接"}</div>;
}
const workspace = (revisionId = focus.revision_id) => (
  <PackageTechnicalDraftHandoff
    key={revisionId}
    packageView={packageRevision(revisionId)}
  >
    <Child />
  </PackageTechnicalDraftHandoff>
);
afterEach(() => vi.unstubAllGlobals());

it("only reads on demand, records the exact historical handoff, and clears it on a failed refresh", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json({ ...focus, revision_status: "historical" }))
    .mockResolvedValueOnce(json({ code: "SERVICE_UNAVAILABLE" }, 503));
  vi.stubGlobal("fetch", fetch);
  render(workspace());
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "读取技术稿交接" }));
  expect(await screen.findByText(/不继承到新修订/)).toBeInTheDocument();
  expect(screen.getByText(/采用时未冻结解析/)).toBeInTheDocument();
  expect(
    screen.getByText(/正式独立审批与候选件下载尚未开放/),
  ).toBeInTheDocument();
  expect(screen.getByText("下方看到相同交接")).toBeInTheDocument();
  expect(fetch.mock.calls[0][0]).toBe(
    `/api/v1/bids/${focus.bid_id}/packages/${focus.package_id}/revisions/${focus.revision_id}/technical-authoring-handoff`,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "重新核对技术稿交接" }),
  );
  expect(await screen.findByText("下方不采用交接")).toBeInTheDocument();
  expect(screen.queryByText(/采用时未冻结解析/)).not.toBeInTheDocument();
  expect(fetch.mock.calls.map((entry) => entry[1].method)).toEqual([
    "GET",
    "GET",
  ]);
});

it.each([
  { package_id: id(99) },
  { revision_id: id(99) },
  { record: { ...focus.record, document_version_id: id(99) } },
  { record: { ...focus.record, artifact_sha256: "e".repeat(64) } },
  { record: { ...focus.record, parse_run_id: id(99) } },
  { independent_approval_available: true },
])(
  "blocks mismatched data before providing nested progress: %o",
  async (bad) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json({ ...focus, ...bad })),
    );
    render(workspace());
    await userEvent.click(
      screen.getByRole("button", { name: "读取技术稿交接" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/文件身份不符/);
    expect(screen.getByText("下方不采用交接")).toBeInTheDocument();
    expect(screen.queryByText(/已生成，并明确采用/)).not.toBeInTheDocument();
  },
);

it("does not carry an in-flight old revision, and no direct receipt stays pending", async () => {
  let finish!: (response: Response) => void;
  const next = id(99);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce(
        json({ ...focus, revision_id: next, record: null }),
      ),
  );
  const { rerender } = render(workspace());
  await userEvent.click(screen.getByRole("button", { name: "读取技术稿交接" }));
  rerender(workspace(next));
  await act(async () => finish(json(focus)));
  expect(screen.getByText("下方不采用交接")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "读取技术稿交接" }));
  expect(await screen.findByText(/未找到这版直接采用/)).toBeInTheDocument();
});
