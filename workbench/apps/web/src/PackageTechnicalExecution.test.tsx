import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, supportsApi } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import { PackageTechnicalExecution } from "./PackageTechnicalExecution";
import raw from "./test-fixtures/technical-execution-http.json";
import other from "./test-fixtures/technical-scale-http.json";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: vi.fn(),
}));
const mocked = vi.mocked(api),
  supports = vi.mocked(supportsApi);
const saved = raw.scope as unknown as PackageTechnicalScopeView;
const base = raw.basePath.replace("/api/v1", "");
const receiptError = () =>
  new ApiError(
    raw.refusal.message,
    409,
    raw.refusal.code,
    raw.refusal.request_id,
    false,
    raw.refusal.details,
  );
beforeEach(() => {
  supports.mockReset().mockReturnValue(true);
  mocked.mockReset().mockImplementation(async (path, options) => {
    if (path === `${base}/execution-context` && !options?.method)
      return { data: raw.context, etag: raw.etag };
    if (path === `${base}/executions` && options?.method === "POST")
      throw receiptError();
    throw new Error(`Unexpected synthetic route: ${path}`);
  });
});
async function inspect() {
  fireEvent.click(screen.getByRole("button", { name: "读取正式执行条件" }));
  return screen.findByLabelText("正式执行条件结果");
}

it("reads only on explicit request, shows the full refusal gaps, and sends a zero-budget check only on a second click", async () => {
  render(<PackageTechnicalExecution saved={saved} />);
  expect(mocked).not.toHaveBeenCalled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("正式执行拒绝回执")).not.toBeInTheDocument();
  const result = await inspect();
  expect(result).toHaveTextContent("当前服务未安装整包执行基础");
  expect(result).toHaveTextContent("完整必要范围尚无独立权威证明");
  expect(result).toHaveTextContent("三次有效独立判断");
  expect(mocked).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "核对正式执行限制" }));
  const receipt = await screen.findByLabelText("正式执行拒绝回执");
  expect(receipt).toHaveTextContent("本次创建任务：0；发送模型请求：0");
  expect(mocked.mock.calls[1]).toEqual([
    `${base}/executions`,
    {
      method: "POST",
      etag: raw.etag,
      body: {
        ...raw.request,
        reason: "核对本范围的正式执行限制；本次检查预算为零。",
      },
    },
  ]);
});

it("rejects an unsupported success without inventing a refusal receipt", async () => {
  render(<PackageTechnicalExecution saved={saved} />);
  await inspect();
  mocked.mockResolvedValueOnce({ data: { job_id: "unexpected" }, etag: null });
  fireEvent.click(screen.getByRole("button", { name: "核对正式执行限制" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("正式执行拒绝回执")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("正式执行条件结果")).not.toBeInTheDocument();
});

it("clears a stale context and waits for an explicit reread after a conflict", async () => {
  render(<PackageTechnicalExecution saved={saved} />);
  await inspect();
  mocked.mockRejectedValueOnce(
    new ApiError("依据已变化", 412, "REVISION_CONFLICT"),
  );
  fireEvent.click(screen.getByRole("button", { name: "核对正式执行限制" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("正式执行拒绝回执")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("正式执行条件结果")).not.toBeInTheDocument();
  expect(mocked).toHaveBeenCalledTimes(2);
});

it("does not turn a malformed zero-effect claim into a displayed receipt", async () => {
  render(<PackageTechnicalExecution saved={saved} />);
  await inspect();
  const malformed = receiptError();
  malformed.details = { ...raw.refusal.details, model_requests: 1 };
  mocked.mockRejectedValueOnce(malformed);
  fireEvent.click(screen.getByRole("button", { name: "核对正式执行限制" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("正式执行拒绝回执")).not.toBeInTheDocument();
});

it("keeps an old in-flight response out of a newly opened scope", async () => {
  let finish!: (value: { data: typeof raw.context; etag: string }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<PackageTechnicalExecution saved={saved} />);
  fireEvent.click(screen.getByRole("button", { name: "读取正式执行条件" }));
  view.rerender(
    <PackageTechnicalExecution
      saved={other.scope as unknown as PackageTechnicalScopeView}
    />,
  );
  await act(async () => finish({ data: raw.context, etag: raw.etag }));
  expect(screen.queryByLabelText("正式执行条件结果")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "读取正式执行条件" }),
  ).toBeEnabled();
});

it("allows one outstanding check and requires a fresh result after refresh", async () => {
  render(<PackageTechnicalExecution saved={saved} />);
  const button = screen.getByRole("button", { name: "读取正式执行条件" });
  fireEvent.click(button);
  fireEvent.click(button);
  await screen.findByLabelText("正式执行条件结果");
  expect(mocked).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "核对正式执行限制" }));
  await screen.findByLabelText("正式执行拒绝回执");
  fireEvent.click(screen.getByRole("button", { name: "读取正式执行条件" }));
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(3));
  expect(screen.queryByLabelText("正式执行拒绝回执")).not.toBeInTheDocument();
});

it("shows absent endpoint support instead of pretending the service is ready", () => {
  supports.mockReturnValue(false);
  render(<PackageTechnicalExecution saved={saved} />);
  expect(
    screen.getByRole("button", { name: "读取正式执行条件" }),
  ).toBeDisabled();
  expect(
    screen.getByText("当前服务版本尚未提供此执行检查，已保存范围仍保留。"),
  ).toBeInTheDocument();
  expect(mocked).not.toHaveBeenCalled();
});
