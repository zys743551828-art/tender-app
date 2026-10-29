import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackageOriginalVerification } from "./PackageOriginalVerification";
import type {
  PackageReviewInputPreview as Preview,
  PackageReviewOriginalVerification as Observation,
} from "./contracts";

// This component consumes these selected fields; full API schema is tested against PG separately.
const preview = {
  digest: "a".repeat(64),
  blockers: ["PACKAGE_REVIEW_EXECUTOR_NOT_READY"],
  manifest: {
    bid_id: "bid",
    target: {
      digest: "b".repeat(64),
      manifest: {
        package_id: "package",
        revision_id: "revision",
        members: [
          {
            member_id: "own",
            document_version_id: "own-version",
            file_digest: "c".repeat(64),
            parse: { parse_run_id: "own-parse" },
          },
        ],
      },
    },
    authority: {
      manifest: {
        members: [
          {
            member_id: "authority",
            document_version_id: "official-version",
            file_digest: "d".repeat(64),
            parse: { parse_run_id: "official-parse" },
          },
        ],
      },
    },
    inventory: { digest: "e".repeat(64), manifest: { id: "inventory" } },
    coverage: null,
  },
} as unknown as Preview;
const reply = (): Observation => ({
  execution_context: {
    version: "package-review-context/1",
    kind: "candidate",
    input_digest: preview.digest,
    semantic_digest: "1".repeat(64),
    snapshot_digest: "2".repeat(64),
    method_digest: "3".repeat(64),
    policy_digest: "4".repeat(64),
    facts_digest: "5".repeat(64),
    sources_digest: "6".repeat(64),
    as_of: "2026-10-19T07:00:00Z",
    purpose: "prebid_compliance",
    fact_set_id: null,
    fact_count: 0,
    confirmed_fact_count: 0,
    facts_binding: "empty",
    executor_available: false,
    formal_scoring_eligible: false,
  },
  kind: "observation",
  input_digest: preview.digest,
  checked_at: "2026-10-19T07:00:00Z",
  originals_verified: true,
  review_ready: false,
  launch_available: false,
  blockers: [...preview.blockers],
  originals: (["target", "authority"] as const).flatMap((role) =>
    preview.manifest[role].manifest.members.map((member) => ({
      role,
      member_id: member.member_id,
      document_version_id: member.document_version_id,
      parse_run_id: member.parse.parse_run_id!,
      file_digest: member.file_digest,
      byte_size: 42,
    })),
  ),
});
const respond = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

it("仅完整核验响应可交给保存入口，重新核验先撤销候选", async () => {
  const onVerified = vi.fn();
  fetchMock.mockResolvedValue(respond(reply()));
  render(
    <PackageOriginalVerification preview={preview} onVerified={onVerified} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  await screen.findByRole("status");
  expect(onVerified.mock.calls[0]).toEqual([null]);
  expect(onVerified.mock.calls[1]).toEqual([reply()]);
  fetchMock.mockResolvedValue(
    respond({ ...reply(), input_digest: "f".repeat(64) }),
  );
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  await screen.findByRole("alert");
  expect(onVerified).toHaveBeenCalledTimes(3);
  expect(onVerified).toHaveBeenLastCalledWith(null);
});

it("显式核验全部明确成员，只显示本次观察且仍不可正式评审", async () => {
  fetchMock.mockResolvedValue(respond(reply()));
  render(
    <StrictMode>
      <PackageOriginalVerification preview={preview} />
    </StrictMode>,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "本次已核对 2 个成员原件，正式评审仍未就绪",
  );
  const [path, options] = fetchMock.mock.calls[0];
  expect(path).toContain("/inventory/review-original-verification");
  expect(JSON.parse(options.body)).toEqual({
    package_digest: preview.manifest.target.digest,
    inventory_digest: preview.manifest.inventory.digest,
    input_digest: preview.digest,
    coverage_attempt_id: null,
    coverage_digest: null,
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it.each([
  "missing",
  "cross_member",
  "cross_parse",
  "cross_digest",
  "ready",
  "blockers",
  "date",
  "context_digest",
  "context_scoring",
  "context_time",
  "context_count",
])("拒绝不一致响应：%s", async (kind) => {
  const value = reply();
  if (kind === "missing") value.originals.pop();
  if (kind === "cross_member") value.originals[0].document_version_id = "other";
  if (kind === "cross_parse") value.originals[0].parse_run_id = "other";
  if (kind === "cross_digest") value.input_digest = "f".repeat(64);
  if (kind === "ready")
    (value as unknown as { review_ready: boolean }).review_ready = true;
  if (kind === "blockers") value.blockers = [];
  if (kind === "date") value.checked_at = "invalid";
  if (kind === "context_digest")
    value.execution_context.semantic_digest = "bad";
  if (kind === "context_scoring")
    (
      value.execution_context as unknown as { formal_scoring_eligible: boolean }
    ).formal_scoring_eligible = true;
  if (kind === "context_time")
    value.execution_context.as_of = "2026-10-19T07:01:00Z";
  if (kind === "context_count")
    value.execution_context.confirmed_fact_count = 1;
  fetchMock.mockResolvedValue(respond(value));
  render(<PackageOriginalVerification preview={preview} />);
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  expect(
    await screen.findByText("原件核验响应与所选输入不一致，未采用该结果。"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("重新预检即使摘要相同也丢弃旧核验响应", async () => {
  let complete!: (r: Response) => void;
  fetchMock.mockReturnValue(
    new Promise<Response>((r) => {
      complete = r;
    }),
  );
  const { rerender } = render(
    <PackageOriginalVerification preview={preview} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  rerender(<PackageOriginalVerification preview={structuredClone(preview)} />);
  await act(async () => complete(respond(reply())));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核对所选原件" })).toBeEnabled();
});

it("存储未配置时呈现错误，禁用状态不发送", async () => {
  fetchMock.mockResolvedValue(
    respond(
      {
        code: "OBJECT_STORE_NOT_CONFIGURED",
        message: "尚未配置对象存储",
        retryable: false,
        details: {},
      },
      503,
    ),
  );
  const { rerender } = render(
    <PackageOriginalVerification preview={preview} disabled />,
  );
  expect(screen.getByRole("button", { name: "核对所选原件" })).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
  rerender(<PackageOriginalVerification preview={preview} />);
  await userEvent.click(screen.getByRole("button", { name: "核对所选原件" }));
  expect(await screen.findByText(/尚未配置对象存储/)).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
