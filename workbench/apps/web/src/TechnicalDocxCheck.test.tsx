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

it("distinguishes a measured page-margin mismatch from required manual visual review", async () => {
  mock({ ...response, blocking_codes: ["DOCX_PAGE_MARGINS_MISMATCH"] });
  const user = await open();
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  const region = await screen.findByRole("status");
  expect(
    within(region).getByText(/页面边距与本稿冻结的已确认要求不一致/),
  ).toBeInTheDocument();
  expect(
    within(region).getByText(/打开 Word 核对实际排版/),
  ).toBeInTheDocument();
  expect(within(region).queryByText(/未发现问题/)).not.toBeInTheDocument();
});

it("makes missing frozen page-margin basis an explicit manual check", async () => {
  mock({
    ...response,
    manual_check_codes: [
      ...response.manual_check_codes,
      "DOCX_PAGE_MARGINS_NO_FROZEN_BASIS",
    ],
  });
  const user = await open();
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  const region = await screen.findByRole("status");
  expect(within(region).getByText(/须按招标原文人工核对/)).toBeInTheDocument();
  expect(
    within(region).getByText(/在可核范围内未发现问题/),
  ).toBeInTheDocument();
  expect(
    within(region).getByText(/也不代表已通过独立审核/),
  ).toBeInTheDocument();
});

it("reports explicit placeholders as an internal check finding, not clearance", async () => {
  const calls = mock({
    ...response,
    blocking_codes: ["DOCX_EXPLICIT_PLACEHOLDER"],
  });
  const user = await open();
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  const region = await screen.findByRole("status");
  expect(within(region).getByText(/发现明确的占位标记/)).toBeInTheDocument();
  expect(within(region).getByText(/人工核对正文/)).toBeInTheDocument();
  expect(within(region).queryByText(/未发现问题/)).not.toBeInTheDocument();
  expect(calls).toHaveLength(1);
});

it("copies a separate internal summary pinned to the checked file without copying the names or transmitting it", async () => {
  const calls = mock({
    ...response,
    blocking_codes: ["PROHIBITED_NAME_FILENAME"],
  });
  const user = await open();
  await user.type(
    screen.getByLabelText(/本项目禁用标识/),
    "不应复制的合成单位",
  );
  await user.clear(screen.getByLabelText("拟用文件名"));
  await user.type(
    screen.getByLabelText("拟用文件名"),
    "不应复制的拟用名称.docx",
  );
  expect(
    screen.queryByText("内部核查摘要（单独留存）"),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  await user.click(await screen.findByText("内部核查摘要（单独留存）"));
  const summary = screen.getByLabelText(
    "本次 Word 内部核查摘要",
  ) as HTMLTextAreaElement;
  expect(summary).toHaveAttribute("readonly");
  expect(summary.value).toContain(
    `受检文件 SHA-256：${response.artifact_sha256}`,
  );
  expect(summary.value).toContain(
    `检查范围 SHA-256：${response.policy_sha256}`,
  );
  expect(summary.value).toContain(
    `草稿快照 SHA-256：${response.snapshot_digest}`,
  );
  expect(summary.value).toContain("PROHIBITED_NAME_FILENAME");
  expect(summary.value).toContain("FORMAT_AND_RENDER_REVIEW");
  expect(summary.value).toContain("不是签收、独立审批、提交许可");
  expect(summary.value).toContain("本次提交了 1 条自填禁用标识");
  expect(summary.value).not.toMatch(/不应复制的合成单位|不应复制的拟用名称/);
  await user.click(screen.getByRole("button", { name: "复制内部核查摘要" }));
  await screen.findByText("已复制，仅供内部核对。");
  expect(await navigator.clipboard.readText()).toBe(summary.value);
  expect(calls).toHaveLength(1);
  await user.clear(screen.getByLabelText(/本项目禁用标识/));
  expect(
    screen.queryByText("内部核查摘要（单独留存）"),
  ).not.toBeInTheDocument();
});

it("makes unperformed identifier checking and a clipboard failure clear without affecting the original", async () => {
  const calls = mock(response);
  const user = await open();
  const rejected = vi
    .spyOn(navigator.clipboard, "writeText")
    .mockRejectedValueOnce(new Error("unavailable"));
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  await user.click(await screen.findByText("内部核查摘要（单独留存）"));
  const summary = screen.getByLabelText(
    "本次 Word 内部核查摘要",
  ) as HTMLTextAreaElement;
  expect(summary.value).toContain("未提供项目禁用标识，未做该项比对");
  await user.click(screen.getByRole("button", { name: "复制内部核查摘要" }));
  await screen.findByText(/当前不能访问剪贴板/);
  expect(summary.value).toContain(response.artifact_sha256);
  expect(calls).toHaveLength(1);
  rejected.mockRestore();
});

it("does not leave the previous summary visible if the immutable build context changes", async () => {
  mock(response);
  const view = render(<TechnicalDocxCheck {...scope} />);
  const user = userEvent.setup();
  await user.click(screen.getByText("技术标 Word 检查（送审前）"));
  await user.click(screen.getByRole("button", { name: "检查这个 Word" }));
  await screen.findByText("内部核查摘要（单独留存）");
  view.rerender(
    <TechnicalDocxCheck {...scope} snapshotDigest={"e".repeat(64)} />,
  );
  expect(
    screen.queryByText("内部核查摘要（单独留存）"),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  view.rerender(<TechnicalDocxCheck {...scope} />);
  await user.click(screen.getByText("技术标 Word 检查（送审前）"));
  expect(
    screen.queryByText("内部核查摘要（单独留存）"),
  ).not.toBeInTheDocument();
});
