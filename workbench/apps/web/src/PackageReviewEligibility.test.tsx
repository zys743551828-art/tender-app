import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PackageReviewEligibility from "./PackageReviewEligibility";
import type {
  PackageReviewEligibilityObservation,
  PackageReviewExecutionContext,
  PackageReviewFrozenInputView,
} from "./contracts";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const context: PackageReviewExecutionContext = {
  version: "package-review-context/1",
  kind: "candidate",
  input_digest: "a".repeat(64),
  semantic_digest: "b".repeat(64),
  snapshot_digest: "c".repeat(64),
  as_of: "2026-10-19T08:00:00Z",
  purpose: "prebid_compliance",
  method_digest: "d".repeat(64),
  policy_digest: "e".repeat(64),
  facts_digest: "f".repeat(64),
  sources_digest: "1".repeat(64),
  fact_set_id: id(7),
  fact_count: 1,
  confirmed_fact_count: 1,
  facts_binding: "unproven",
  executor_available: false,
  formal_scoring_eligible: false,
};
// The parent already verifies the complete frozen manifest; this child consumes these identities.
const frozen = {
  digest: "2".repeat(64),
  manifest: {
    id: id(6),
    input_digest: context.input_digest,
    execution_context: context,
  },
} as unknown as PackageReviewFrozenInputView;
const reply = (): PackageReviewEligibilityObservation => ({
  kind: "eligibility_observation",
  frozen_input_id: id(6),
  frozen_digest: frozen.digest,
  input_digest: context.input_digest,
  checked_at: "2026-10-19T08:01:00Z",
  current_context: {
    ...context,
    as_of: "2026-10-19T08:01:00Z",
    snapshot_digest: "3".repeat(64),
  },
  parse_evidence_status: "matched",
  original_verification: "not_performed",
  review_ready: false,
  launch_available: false,
  publication_authorized: false,
  blockers: [
    "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
    "PACKAGE_REVIEW_FACTS_UNPROVEN",
  ],
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
const click = () =>
  userEvent.click(
    screen.getByRole("button", { name: "复核此冻结输入的当前条件" }),
  );

it("StrictMode下仅显式检查选定摘要，分清精确解析与未核原件／发布", async () => {
  fetchMock.mockImplementation(async () => respond(reply()));
  render(
    <StrictMode>
      <PackageReviewEligibility scope={scope} frozen={frozen} />
    </StrictMode>,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await click();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "暂不可正式执行或发布",
  );
  expect(screen.getByRole("status")).toHaveTextContent("原件字节未重核");
  expect(screen.getByRole("status")).toHaveTextContent(
    "人工确认数量不代表资格通过",
  );
  expect(fetchMock.mock.calls[0][0]).toContain(
    `/frozen-review-inputs/${id(6)}/execution-check`,
  );
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    frozen_digest: frozen.digest,
  });
  expect(
    screen.queryByRole("button", { name: "启动评审" }),
  ).not.toBeInTheDocument();
});

it.each([
  "record",
  "digest",
  "context",
  "original",
  "publication",
  "ready",
  "unknown",
  "duplicate",
  "parse",
  "method",
  "semantic",
  "counts",
  "microtime",
])("拒绝%s越界或错配观察", async (kind) => {
  const data = reply();
  if (kind === "record") data.frozen_input_id = id(99);
  if (kind === "digest") data.frozen_digest = "0".repeat(64);
  if (kind === "context") data.current_context.input_digest = "0".repeat(64);
  if (kind === "original")
    Object.assign(data, { original_verification: "verified" });
  if (kind === "publication")
    Object.assign(data, { publication_authorized: true });
  if (kind === "ready") Object.assign(data, { review_ready: true });
  if (kind === "unknown") Object.assign(data, { blockers: ["UNKNOWN"] });
  if (kind === "duplicate") data.blockers.push(data.blockers[0]);
  if (kind === "parse") data.parse_evidence_status = "mismatch";
  if (kind === "method") data.current_context.method_digest = "0".repeat(64);
  if (kind === "semantic")
    data.current_context.semantic_digest = "0".repeat(64);
  if (kind === "counts") data.current_context.fact_count = 2;
  if (kind === "microtime") {
    data.checked_at = "2026-10-19T08:01:00.000001Z";
    data.current_context.as_of = "2026-10-19T08:01:00.000002Z";
  }
  fetchMock.mockImplementation(async () => respond(data));
  render(<PackageReviewEligibility scope={scope} frozen={frozen} />);
  await click();
  expect(await screen.findByRole("alert")).toHaveTextContent("观察边界不符");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("方法或解析变化展示当前阻断，不改原冻结记录", async () => {
  const data = reply();
  data.current_context.method_digest = "0".repeat(64);
  data.current_context.semantic_digest = "4".repeat(64);
  data.blockers.push(
    "PACKAGE_REVIEW_METHOD_CHANGED",
    "PACKAGE_REVIEW_EVIDENCE_CHANGED",
  );
  data.parse_evidence_status = "mismatch";
  fetchMock.mockImplementation(async () => respond(data));
  render(<PackageReviewEligibility scope={scope} frozen={frozen} />);
  await click();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "当前方法或模型配置已变化",
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "当前解析证据无法与冻结引用匹配",
  );
  expect(frozen.manifest.execution_context.method_digest).toBe(
    context.method_digest,
  );
});

it("换记录／重新读同一记录均丢弃旧观察和慢响应", async () => {
  let finish!: (value: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(
    <PackageReviewEligibility scope={scope} frozen={frozen} />,
  );
  await click();
  const other = {
    ...frozen,
    digest: "5".repeat(64),
    manifest: { ...frozen.manifest, id: id(99) },
  };
  view.rerender(<PackageReviewEligibility scope={scope} frozen={other} />);
  await act(async () => finish(respond(reply())));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fetchMock.mockImplementation(async () =>
    respond({
      ...reply(),
      frozen_input_id: id(99),
      frozen_digest: other.digest,
    }),
  );
  await click();
  await screen.findByRole("status");
  view.rerender(
    <PackageReviewEligibility scope={scope} frozen={structuredClone(other)} />,
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("失败保留历史记录，仅显式重试复核，不保存或创建任务", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  fetchMock.mockImplementationOnce(async () => respond(reply()));
  render(<PackageReviewEligibility scope={scope} frozen={frozen} />);
  await click();
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: /^重试$/ }));
  await screen.findByRole("status");
  expect(fetchMock.mock.calls).toHaveLength(2);
  expect(fetchMock.mock.calls[0][1].body).toBe(fetchMock.mock.calls[1][1].body);
  expect(
    fetchMock.mock.calls.every((call) => call[0].endsWith("/execution-check")),
  ).toBe(true);
});
