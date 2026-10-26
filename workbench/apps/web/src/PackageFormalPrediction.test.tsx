import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { PackageFormalPrediction } from "./PackageFormalPrediction";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
}));
const mock = vi.mocked(api);
const p = { bidId: "bid", scopeId: "scope", memberId: "member" };
const certificate = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
const key = `package-formal-prediction/1:${p.memberId}:${p.bidId}:${p.scopeId}`;
function result(body: unknown, extra: object = {}) {
  return {
    data: {
      ...(body as object),
      schema: "package-formal-prediction/1",
      actor_id: p.memberId,
      bid_id: p.bidId,
      scope_id: p.scopeId,
      state: "valid",
      value: "50",
      maximum: "100",
      provider_requests: 0,
      low: "40",
      high: "60",
      interval_level: "0.8",
      training_groups: { fit: 3, development: 2, calibration: 9 },
      evaluation_project_mae: "5",
      ...extra,
    },
    etag: null,
    headers: new Headers(),
  };
}
function start() {
  fireEvent.change(screen.getByLabelText("认证编号"), {
    target: { value: certificate },
  });
  fireEvent.click(screen.getByText("验证并生成预测"));
}
beforeEach(() => {
  mock.mockReset();
  localStorage.clear();
});
it("persists command before request and displays qualified result", async () => {
  mock.mockImplementation(async (_, options) => {
    expect(localStorage.getItem(key)).not.toBeNull();
    return result(options?.body);
  });
  render(<PackageFormalPrediction {...p} />);
  start();
  expect(await screen.findByText(/正式预测：50/)).toBeTruthy();
  expect(mock).toHaveBeenCalledTimes(1);
});
it("lost ACK remount retries the identical command", async () => {
  mock.mockRejectedValueOnce(new Error("ACK lost"));
  const view = render(<PackageFormalPrediction {...p} />);
  start();
  await screen.findByText(/ACK lost/);
  const first = mock.mock.calls[0][1]?.body;
  view.unmount();
  mock.mockImplementation(async (_, options) => result(options?.body));
  render(<PackageFormalPrediction {...p} />);
  fireEvent.click(screen.getByText("恢复同一预测请求"));
  await screen.findByText(/正式预测：50/);
  expect(mock.mock.calls[1][1]?.body).toEqual(first);
});
it.each(["stale", "hidden"])(
  "does not display value for %s history",
  async (state) => {
    mock.mockImplementation(async (_, options) =>
      result(options?.body, {
        state,
        value: null,
        maximum: null,
        low: null,
        high: null,
        interval_level: null,
        training_groups: null,
        evaluation_project_mae: null,
      }),
    );
    render(<PackageFormalPrediction {...p} />);
    start();
    await screen.findByText(
      state === "stale" ? /历史结果已失效/ : /项目设置已隐藏/,
    );
    expect(screen.queryByText(/正式预测：50/)).toBeNull();
  },
);
it("rejects a cross-scope ACK", async () => {
  mock.mockImplementation(async (_, options) =>
    result(options?.body, { scope_id: "other" }),
  );
  render(<PackageFormalPrediction {...p} />);
  start();
  await screen.findByText(/预测回执身份或展示状态异常/);
  expect(screen.queryByText(/正式预测：50/)).toBeNull();
});
it("discards late result after selection switches", async () => {
  let finish!: (v: ReturnType<typeof result>) => void;
  mock.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<PackageFormalPrediction {...p} />);
  start();
  const body = mock.mock.calls[0][1]?.body;
  view.rerender(<PackageFormalPrediction {...p} scopeId="other" />);
  await act(async () => finish(result(body)));
  expect(screen.queryByText(/正式预测：50/)).toBeNull();
});
it("fails closed on corrupted recovery state", () => {
  localStorage.setItem(key, '{"verified":true}');
  render(<PackageFormalPrediction {...p} />);
  fireEvent.click(screen.getByText("验证并生成预测"));
  expect(mock).not.toHaveBeenCalled();
  expect(screen.getByText(/保存的请求身份损坏/)).toBeTruthy();
});

it("allows correction after a first definite server rejection", async () => {
  mock.mockRejectedValueOnce(
    new ApiError("证书不匹配", 409, "PACKAGE_PREDICTION_REJECTED"),
  );
  render(<PackageFormalPrediction {...p} />);
  start();
  await screen.findByText(/证书不匹配/);
  expect(localStorage.getItem(key)).toBeNull();
  expect((screen.getByLabelText("认证编号") as HTMLInputElement).disabled).toBe(
    false,
  );
});
it("clears the displayed numeric snapshot before a failing report authority refresh", async () => {
  mock.mockImplementationOnce(async (_, options) => result(options?.body));
  render(<PackageFormalPrediction {...p} />);
  start();
  await screen.findByText(/正式预测：50/);
  mock.mockRejectedValueOnce(new Error("certificate revoked"));
  fireEvent.click(screen.getByText("复验并查看预测报告"));
  expect(screen.queryByText(/正式预测：50/)).toBeNull();
  await screen.findByText(/certificate revoked/);
});
