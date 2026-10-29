import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { MaterialExecutionStatus } from "./MaterialExecutionStatus";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const props = {
  base: "/scope",
  memberId: "member",
  scopeId: "scope",
  intentId: "intent",
  requestDigest: "a".repeat(64),
  job: { job_id: "job", job_digest: "b".repeat(64), generation: 1 },
};
function result(change: Record<string, unknown> = {}) {
  return {
    data: {
      version: "material-execution-status/1",
      intent_id: props.intentId,
      actor_id: props.memberId,
      scope_id: props.scopeId,
      request_digest: props.requestDigest,
      job: props.job,
      task_state: "accepted_preparation",
      send_authorized: false,
      accuracy_verified: false,
      invoice_reconciled: false,
      available: true,
      qualification_state: "revoked",
      execution_state: "unknown",
      execution_mode: "isolated_synthetic_mechanism",
      fee_state: "unknown",
      currency: "USD",
      reserved_minor: 100,
      held_minor: 100,
      known_estimated_minor: 0,
      released_minor: 0,
      attempt_count: 1,
      unsettled_count: 0,
      unknown_count: 1,
      final_fee_minor: null,
      last_settled_at: null,
      observed_at: "2026-10-26T12:00:00Z",
      ...change,
    },
    etag: null,
  };
}
const click = () => fireEvent.click(screen.getByText("读取权威执行与费用状态"));
beforeEach(() => mocked.mockReset().mockResolvedValue(result()));
it("separates unknown fees from known zero estimate and revoked qualification", async () => {
  render(<MaterialExecutionStatus {...props} />);
  click();
  await screen.findByText(/费用未知，不自动重发/);
  expect(screen.getByText(/审核已撤销/)).toBeInTheDocument();
  expect(screen.getByText(/最终账单尚未核对/)).toBeInTheDocument();
  expect(mocked.mock.calls[0][1]).toBeUndefined();
});
it("refreshes late settlement without suggesting a new send", async () => {
  mocked.mockResolvedValueOnce(
    result({
      execution_state: "in_flight",
      fee_state: "in_flight",
      unknown_count: 0,
      unsettled_count: 1,
    }),
  );
  render(<MaterialExecutionStatus {...props} />);
  click();
  await screen.findByText(/在途，费用未确定/);
  mocked.mockResolvedValueOnce(
    result({
      execution_state: "completed",
      fee_state: "settled_estimate",
      unknown_count: 0,
      held_minor: 0,
      known_estimated_minor: 24,
      released_minor: 76,
      last_settled_at: "2026-10-26T12:01:00Z",
    }),
  );
  click();
  await screen.findByText(/已按用量结算估算/);
  expect(screen.getByText("24")).toBeInTheDocument();
  expect(screen.getByText(/执行完成不等于准确性验收/)).toBeInTheDocument();
});
it.each([
  { actor_id: "other" },
  { request_digest: "bad" },
  { job: { ...props.job, job_digest: "bad" } },
  { final_fee_minor: 0 },
  { known_estimated_minor: -1 },
  { send_authorized: true },
  { fee_state: "settled_estimate" },
])("rejects mismatched or misleading receipts %j", async (change) => {
  mocked.mockResolvedValueOnce(result(change));
  render(<MaterialExecutionStatus {...props} />);
  click();
  await screen.findByRole("alert");
  expect(screen.queryByText(/费用状态：/)).not.toBeInTheDocument();
});
it("drops late responses after switching member without requiring remount", async () => {
  let resolve!: (value: ReturnType<typeof result>) => void;
  mocked.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = render(<MaterialExecutionStatus {...props} />);
  click();
  view.rerender(<MaterialExecutionStatus {...props} memberId="other" />);
  await act(async () => resolve(result()));
  expect(screen.queryByText(/费用状态：/)).not.toBeInTheDocument();
});
it("distinguishes unavailable observation from zero charge", async () => {
  mocked.mockResolvedValueOnce(
    result({ available: false, reason: "EXECUTION_OBSERVER_UNAVAILABLE" }),
  );
  render(<MaterialExecutionStatus {...props} />);
  click();
  await screen.findByText(/执行观察尚未配置，费用未读取/);
  expect(screen.queryByText(/已知用量估算/)).not.toBeInTheDocument();
});

it("drops an old result after leaving and returning to the same selection", async () => {
  let resolve!: (value: ReturnType<typeof result>) => void;
  mocked.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = render(<MaterialExecutionStatus {...props} />);
  click();
  view.rerender(<MaterialExecutionStatus {...props} memberId="other" />);
  view.rerender(<MaterialExecutionStatus {...props} />);
  await act(async () => resolve(result()));
  expect(screen.queryByText(/费用状态：/)).not.toBeInTheDocument();
});
