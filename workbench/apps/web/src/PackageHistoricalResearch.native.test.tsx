import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageHistoricalResearch } from "./PackageHistoricalResearch";
import type {
  PackageHistoricalAdmissionView,
  PackageHistoricalJobView,
  PackageHistoryAdmissionDirectory,
  PackageHistoryCohortRequest,
  PackageHistoryJobControl,
  PackageHistoryJobRequest,
  PackageHistoryProtocolRequest,
} from "./contracts";
import { readHistoryRecovery } from "./packageHistoricalResearchRecovery";
import capturedHttp from "./test-fixtures/package-history-ui-complete-http.json";

// Replay unmodified HTTP JSON and ETags from public-main + PG17 with independent
// API/runner LOGINs. Business records are explicitly synthetic; this suite tests
// the actual UI against those receipts, not browser-to-PG or model quality.
type Capture = {
  name: string;
  method: string;
  path: string;
  status: number;
  etag: string | null;
  headers: Record<string, string>;
  body: unknown;
  request_body: unknown;
  request_headers: Record<string, string>;
};
const captures = capturedHttp.responses as unknown as Capture[];
const member = capturedHttp.actor_id;
const base = "/api/v1/package-historical-research";
function capture(name: string) {
  const value = captures.find((entry) => entry.name === name);
  if (!value) throw new Error(`Missing original HTTP capture: ${name}`);
  return value;
}
function body<T>(name: string): T {
  return capture(name).body as T;
}
function request<T>(name: string): T {
  return capture(name).request_body as T;
}
function response(name: string) {
  const value = capture(name);
  return new Response(JSON.stringify(value.body), {
    status: value.status,
    headers: { "Content-Type": "application/json", ...value.headers },
  });
}
const cohortRequest = request<PackageHistoryCohortRequest>("cohort_created");
const protocolRequest =
  request<PackageHistoryProtocolRequest>("protocol_created");
const training = body<PackageHistoricalJobView>("train_queued");
const evaluation = body<PackageHistoricalJobView>("evaluate_succeeded");
const admissions = body<PackageHistoryAdmissionDirectory>(
  "admissions_directory",
);
const currentAdmissions = [
  "admission_current",
  "fit_second_current",
  "development_current",
  "unselected_bridge_current",
  "final_known_current",
  "final_crossing_current",
  "final_unknown_current",
];

function transport() {
  const state = {
    cohort: "cohort_current",
    train: "train_queued",
    evaluation: "evaluate_queued",
    admission: "admission_current",
    loseProtocolReceipt: false,
    rejectStaleControl: false,
  };
  const writes: { path: string; body: unknown; headers: Headers }[] = [];
  const reads: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      if (init?.method === "POST") {
        const value = JSON.parse(String(init.body)) as Record<string, unknown>;
        const headers = new Headers(init.headers);
        writes.push({ path, body: value, headers });
        let name: string;
        if (path === `${base}/protocols`) {
          name = "protocol_created";
          if (state.loseProtocolReceipt) {
            state.loseProtocolReceipt = false;
            throw new Error(
              "Explicit simulated loss after native protocol commit",
            );
          }
        } else if (path === `${base}/cohorts`) name = "cohort_created";
        else if (path === `${base}/cohorts/${training.cohort_id}/jobs`) {
          name = value.kind === "train" ? "train_created" : "evaluate_created";
        } else if (path === `${base}/jobs/${training.job_id}/control`) {
          if (state.rejectStaleControl) {
            state.rejectStaleControl = false;
            state.train = "train_paused";
            name = "pause_stale_condition";
          } else if (value.action === "pause") {
            name = "pause_ack";
            state.train = "train_paused";
          } else {
            name = "resume_ack";
            state.train = "train_resumed";
          }
        } else throw new Error(`Unexpected native UI write: ${path}`);
        expect(value).toEqual(capture(name).request_body);
        expect(headers.get("If-Match")).toBe(
          capture(name).request_headers["if-match"] ?? null,
        );
        expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
        return response(name);
      }
      reads.push(path);
      const catalog: Record<string, string> = {
        [`${base}/admissions`]: "admissions_directory",
        [`${base}/protocols`]: "protocols_directory",
        [`${base}/cpu-protocol-template`]: "protocol_template",
        [`${base}/cohorts`]: "cohorts_directory",
        [`${base}/cohorts/${training.cohort_id}`]: state.cohort,
        [`${base}/cohorts/${training.cohort_id}/jobs`]: "jobs_directory",
        [`${base}/jobs/${training.job_id}`]: state.train,
        [`${base}/jobs/${evaluation.job_id}`]: state.evaluation,
      };
      if (catalog[path]) return response(catalog[path]);
      for (const name of currentAdmissions) {
        if (capture(name).path === path)
          return response(
            name === "admission_current" ? state.admission : name,
          );
      }
      throw new Error(`Unexpected native UI read: ${path}`);
    }),
  );
  return { state, writes, reads };
}
const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
async function openCohort(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "3. 任务与结果" }));
  await user.click(screen.getByRole("button", { name: "读取研究组目录" }));
  await user.click(await screen.findByRole("button", { name: "打开研究组 1" }));
  await screen.findByRole("heading", { name: "明确登记研究任务" });
}
async function createJob(
  user: ReturnType<typeof userEvent.setup>,
  kind: "train" | "evaluate",
) {
  const expected = request<PackageHistoryJobRequest>(`${kind}_created`);
  await user.selectOptions(screen.getByLabelText("本次任务"), kind);
  change("创建任务的原因", expected.reason);
  await user.click(
    screen.getByRole("checkbox", {
      name: /我已核对本研究组、任务用途和当前依据/,
    }),
  );
  await user.click(screen.getByRole("button", { name: "明确创建研究任务" }));
  await screen.findByText(
    "任务已登记，等待独立研究服务领取；尚未证明训练或评估完成。",
  );
}
async function controlJob(
  user: ReturnType<typeof userEvent.setup>,
  action: "pause" | "resume",
) {
  const expected = request<PackageHistoryJobControl>(`${action}_ack`);
  await user.selectOptions(screen.getByLabelText("任务控制动作"), action);
  change("控制任务的原因", expected.reason);
  await user.click(
    screen.getByRole("checkbox", { name: /我已核对当前任务、第/ }),
  );
  await user.click(screen.getByRole("button", { name: "明确执行任务控制" }));
}
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it("freezes the exact selected native admissions, protocol and microsecond boundaries, then controls and independently reads results", async () => {
  const network = transport();
  const user = userEvent.setup();
  render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  for (const [index, selected] of cohortRequest.selections.entries()) {
    const item = admissions.items.findIndex(
      (entry) => entry.id === selected.admission_id,
    );
    await user.click(
      await screen.findByRole("button", {
        name: `核对资料 ${item + 1} 的准入详情`,
      }),
    );
    const detail = await screen.findByRole("region", { name: "当前准入详情" });
    if (index === 0)
      expect(within(detail).getByText("0 / 20")).toBeInTheDocument();
    await user.click(
      within(detail).getByRole("button", { name: "明确选入研究方案" }),
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: `资料 ${index + 1} 的请求用途` }),
      selected.purpose,
    );
  }
  expect(network.writes).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "2. 冻结研究方案" }));
  await user.click(screen.getByText("冻结新 CPU 研究协议"));
  await user.click(screen.getByRole("button", { name: "读取当前 CPU 方法" }));
  await screen.findByLabelText("随机种子");
  change("随机种子", String(protocolRequest.seed));
  change("组级重采样次数", String(protocolRequest.bootstrap_iterations));
  change("冻结协议的原因", protocolRequest.reason);
  await user.click(
    screen.getByRole("checkbox", {
      name: /我已核对 CPU 方法、种子与重采样设置/,
    }),
  );
  await user.click(screen.getByRole("button", { name: "明确冻结 CPU 协议" }));
  await screen.findByText(/已确认协议冻结回执/);
  await user.click(
    screen.getByRole("checkbox", {
      name: "使用含时区的精确时间（可保留微秒）",
    }),
  );
  change("精确实交分界（必须含时区）", cohortRequest.submission_split_at);
  change("精确标签可用截止（必须含时区）", cohortRequest.label_available_as_of);
  change("冻结研究组的原因", cohortRequest.reason);
  await user.click(
    screen.getByRole("checkbox", {
      name: /我已核对所选协议、全部资料用途和两个时间边界/,
    }),
  );
  await user.click(screen.getByRole("button", { name: "明确冻结研究组" }));
  await screen.findByText(/已确认研究组冻结回执：6 份记录/);
  await screen.findByRole("heading", { name: "明确登记研究任务" });
  expect(screen.getAllByText("关联组跨越实交分界，整组排除")).toHaveLength(1);
  expect(screen.getByText("标签晚于截止时点，保留未知")).toBeInTheDocument();
  await createJob(user, "train");
  expect(screen.queryByText("CPU 基线训练结果")).not.toBeInTheDocument();
  await controlJob(user, "pause");
  await waitFor(() =>
    expect(
      within(screen.getByRole("article", { name: "当前研究任务" })).getByText(
        "已暂停",
      ),
    ).toBeInTheDocument(),
  );
  await controlJob(user, "resume");
  await waitFor(() =>
    expect(
      within(screen.getByRole("article", { name: "当前研究任务" })).getByText(
        "第 3 代",
      ),
    ).toBeInTheDocument(),
  );
  network.state.train = "train_succeeded";
  network.state.cohort = "cohort_after_train";
  await user.click(
    screen.getByRole("button", { name: "读取所选任务当前状态" }),
  );
  await screen.findByText("CPU 基线训练结果");
  expect(
    screen.getByText("固定常数（百分制）").nextElementSibling,
  ).toHaveTextContent("20.0");
  await createJob(user, "evaluate");
  network.state.evaluation = "evaluate_succeeded";
  await user.click(
    screen.getByRole("button", { name: "读取所选任务当前状态" }),
  );
  await screen.findByText("独立最终评估记录");
  const report = screen.getByRole("region", { name: "全部最终评估记录" });
  expect(
    within(report).getByText("总分母").nextElementSibling,
  ).toHaveTextContent("3");
  expect(within(report).getByText("拒绝").nextElementSibling).toHaveTextContent(
    "1",
  );
  expect(
    within(report).getByText("未标注").nextElementSibling,
  ).toHaveTextContent("1");
  expect(
    within(report).getByText("项目等权 ±3 分内比例（0—1）").nextElementSibling,
  ).toHaveTextContent("0.0");
  expect(within(report).getByText(/平均值基线增益：0.0/)).toBeInTheDocument();
  expect(
    within(report).getByText(/独立组或标签不足，未取得/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/只证明软件执行与统计流程，不代表真实模型准确率/),
  ).toBeInTheDocument();
  expect(network.writes.map((item) => item.body)).toEqual([
    capture("protocol_created").request_body,
    capture("cohort_created").request_body,
    capture("train_created").request_body,
    capture("pause_ack").request_body,
    capture("resume_ack").request_body,
    capture("evaluate_created").request_body,
  ]);
  expect(readHistoryRecovery(member)).toBeNull();
}, 15000);

it("requires fresh state and reconfirmation after the native 412 without losing the control reason", async () => {
  const network = transport();
  network.state.rejectStaleControl = true;
  const user = userEvent.setup();
  render(<PackageHistoricalResearch memberId={member} />);
  await openCohort(user);
  await createJob(user, "train");
  await controlJob(user, "pause");
  await screen.findByText("历史研究上下文已经变化，请重新核对");
  expect(readHistoryRecovery(member)).toBeNull();
  expect(screen.getByLabelText("控制任务的原因")).toHaveValue(
    request<PackageHistoryJobControl>("pause_ack").reason,
  );
  expect(
    screen.getByRole("button", { name: "明确执行任务控制" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("任务控制动作")).toBeDisabled();
  expect(network.writes).toHaveLength(2);
  await user.click(
    screen.getByRole("button", { name: "读取所选任务当前状态" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("任务控制动作")).toBeEnabled(),
  );
  expect(screen.getByLabelText("任务控制动作")).toHaveValue("");
  expect(
    within(screen.getByRole("article", { name: "当前研究任务" })).getByText(
      "第 2 代",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "明确执行任务控制" }),
  ).toBeDisabled();
  await controlJob(user, "resume");
  await waitFor(() =>
    expect(
      within(screen.getByRole("article", { name: "当前研究任务" })).getByText(
        "第 3 代",
      ),
    ).toBeInTheDocument(),
  );
  expect(network.writes[2].headers.get("If-Match")).toBe(
    capture("train_paused").etag,
  );
});

it("recovers a lost protocol ACK using the same stored native request and key after remount", async () => {
  const network = transport();
  network.state.loseProtocolReceipt = true;
  const user = userEvent.setup();
  const view = render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "2. 冻结研究方案" }));
  await user.click(screen.getByText("冻结新 CPU 研究协议"));
  await user.click(screen.getByRole("button", { name: "读取当前 CPU 方法" }));
  await screen.findByLabelText("随机种子");
  change("随机种子", String(protocolRequest.seed));
  change("组级重采样次数", String(protocolRequest.bootstrap_iterations));
  change("冻结协议的原因", protocolRequest.reason);
  await user.click(
    screen.getByRole("checkbox", {
      name: /我已核对 CPU 方法、种子与重采样设置/,
    }),
  );
  await user.click(screen.getByRole("button", { name: "明确冻结 CPU 协议" }));
  await screen.findByText(/暂时无法连接服务/);
  const original = readHistoryRecovery(member);
  expect(original?.body).toEqual(protocolRequest);
  view.unmount();
  render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
  await screen.findByText(/已确认协议冻结回执/);
  expect(network.writes).toHaveLength(2);
  expect(network.writes[1].body).toEqual(network.writes[0].body);
  expect(network.writes[1].headers.get("Idempotency-Key")).toBe(
    network.writes[0].headers.get("Idempotency-Key"),
  );
  expect(readHistoryRecovery(member)).toBeNull();
  expect(
    screen.getByRole("heading", { name: "本次明确选择的协议" }),
  ).toBeInTheDocument();
});

it("reads the stale original evaluation without regranting execution or hiding zero and unavailable statistics", async () => {
  const network = transport();
  network.state.cohort = "cohort_stale";
  network.state.evaluation = "evaluation_stale";
  const user = userEvent.setup();
  render(<PackageHistoricalResearch memberId={member} />);
  await openCohort(user);
  expect(
    screen.getByRole("button", { name: "明确创建研究任务" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "读取组内任务目录" }));
  await user.click(await screen.findByRole("button", { name: "打开任务 1" }));
  await screen.findByText("独立最终评估记录");
  expect(
    screen.getByText(/历史结果仍按原版本读取；不恢复执行或授予新用途资格/),
  ).toBeInTheDocument();
  const report = screen.getByRole("region", { name: "全部最终评估记录" });
  expect(within(report).getByText("失败").nextElementSibling).toHaveTextContent(
    "0",
  );
  expect(
    within(report).getByText("同输入独立复跑极差 P90").nextElementSibling,
  ).toHaveTextContent("未取得");
  expect(screen.queryByLabelText("任务控制动作")).not.toBeInTheDocument();
  expect(network.writes).toHaveLength(0);
});

it("does not turn a stale native admission into a newly selected research input", async () => {
  const network = transport();
  network.state.admission = "admission_stale";
  const original = body<PackageHistoricalAdmissionView>("admission_stale");
  const index = admissions.items.findIndex(
    (entry) => entry.id === original.admission.id,
  );
  const user = userEvent.setup();
  render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  await user.click(
    await screen.findByRole("button", {
      name: `核对资料 ${index + 1} 的准入详情`,
    }),
  );
  await screen.findByText(/原准入记录保留；当前来源、官方结果或关联关系已变化/);
  expect(
    screen.getByRole("button", { name: "明确选入研究方案" }),
  ).toBeDisabled();
  expect(screen.getByText("0 / 20")).toBeInTheDocument();
  expect(network.writes).toHaveLength(0);
});
