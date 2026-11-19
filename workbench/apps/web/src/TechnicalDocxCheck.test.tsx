import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TechnicalDocxCheck } from "./TechnicalDocxCheck";

const scope = {
  bidId: "bid",
  buildId: "build",
  documentId: "document",
  snapshotId: "snapshot",
  snapshotDigest: "a".repeat(64),
  suggestedFilename: "施工组织设计.docx",
};
const response = {
  protocol: "technical-candidate-docx-check/1",
  bid_id: scope.bidId,
  build_id: scope.buildId,
  document_version_id: scope.documentId,
  snapshot_id: scope.snapshotId,
  snapshot_digest: scope.snapshotDigest,
  artifact_sha256: "b".repeat(64),
  policy_sha256: "c".repeat(64),
  blocking_codes: [],
  manual_check_codes: [
    "CONTENT_AND_PROJECT_RULE_REVIEW",
    "FORMAT_AND_RENDER_REVIEW",
  ],
  historical_advisory: true,
  publication_authorized: false,
};
function mock(data: Record<string, unknown>) {
  const calls: { path: string; method: string | undefined; body: unknown }[] =
    [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      calls.push({
        path,
        method: init.method,
        body: JSON.parse(init.body as string),
      });
      return new Response(JSON.stringify(data), { status: 200 });
    }),
  );
  return calls;
}
async function open() {
  render(<TechnicalDocxCheck {...scope} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("技术标 Word 检查（送审前）"));
  return user;
}
afterEach(() => vi.unstubAllGlobals());

it("checks exactly the selected immutable Word and leaves independent review outstanding", async () => {
  const calls = mock(response);
  const user = await open();
  await user.type(
    screen.getByLabelText(/本项目禁用标识/),
    "合成单位一{enter}合成单位二",
  );
  expect(calls).toEqual([]);
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  const region = await screen.findByRole("status");
  expect(
    within(region).getByText(/也不代表已通过独立审核/),
  ).toBeInTheDocument();
  expect(within(region).getByText(/人工核对正文/)).toBeInTheDocument();
  expect(calls).toEqual([
    {
      path: "/api/v1/bids/bid/builds/build/technical-docx-check",
      method: "POST",
      body: {
        document_version_id: "document",
        filename: scope.suggestedFilename,
        prohibited_names: ["合成单位一", "合成单位二"],
      },
    },
  ]);
  await user.type(screen.getByLabelText("拟用文件名"), "改");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("never shows a stale or publication-authorized result as an advisory pass", async () => {
  mock({ ...response, snapshot_id: "other", publication_authorized: true });
  const user = await open();
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  expect(await screen.findByText(/固定快照不一致/)).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
