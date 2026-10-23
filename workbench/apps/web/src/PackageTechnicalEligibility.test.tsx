import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import { jsonDigest } from "./editorSchema";
import { PackageTechnicalEligibility } from "./PackageTechnicalEligibility";
import raw from "./test-fixtures/technical-eligibility-catalog-http.json";
import scaled from "./test-fixtures/technical-scale-http.json";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));
const mocked = vi.mocked(api);
const saved = raw.scope as unknown as PackageTechnicalScopeView;
beforeEach(() => {
  mocked.mockReset();
  mocked.mockImplementation(async (path) => {
    if (path.includes("scoring-context"))
      return { data: raw.scoringContext, etag: raw.scoringEtag };
    if (path.includes("sample-context"))
      return { data: raw.sampleContext, etag: raw.sampleEtag };
    if (path.endsWith("submissions?limit=20"))
      return { data: raw.submissions, etag: null };
    if (path.endsWith("/outcomes")) return { data: raw.outcomes, etag: null };
    if (path === "/technical-scale-capabilities")
      return { data: raw.capabilities, etag: null };
    throw new Error(`Unexpected synthetic route: ${path}`);
  });
});

it("reads only current conditions on explicit request and handles an unconfigured denominator", async () => {
  render(<PackageTechnicalEligibility saved={saved} />);
  expect(mocked).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "检查当前评分条件" }));
  const result = await screen.findByLabelText("技术条件检查结果");
  expect(result).toHaveTextContent("当前输入与保存范围已变化");
  expect(result).toHaveTextContent("数值估分尚不可生成");
  expect(result).not.toHaveTextContent("官方技术分");
  fireEvent.click(screen.getByRole("button", { name: "读取可选量尺" }));
  await screen.findByText("当前服务尚未配置有据满分登记。可继续检查其他缺口。");
  expect(mocked.mock.calls.map(([path]) => path)).toEqual([
    `${raw.basePath.replace("/api/v1", "")}/scoring-context`,
    "/technical-scale-capabilities",
  ]);
});

it("requires an explicit authoritative scale and clears a stale maximum when selection changes", async () => {
  mocked.mockImplementation(async (path) => {
    if (path === "/technical-scale-capabilities")
      return {
        data: {
          ...raw.capabilities,
          schema_configured: true,
          sourced_denominator_registration: true,
        },
        etag: null,
      };
    if (path.endsWith("/technical-scales"))
      return {
        data: {
          items: [scaled.scale],
          limit: 200,
          formal_eligibility: "unavailable",
        },
        etag: null,
      };
    return { data: scaled.scoringContext, etag: scaled.scoringEtag };
  });
  render(
    <PackageTechnicalEligibility
      saved={scaled.scope as unknown as PackageTechnicalScopeView}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "读取可选量尺" }));
  await screen.findByText("已读取1条量尺记录。选择后将重新核对原文及适用性。");
  const select = screen.getByLabelText("检查所用技术量尺");
  expect(select).toHaveValue("");
  expect(screen.queryByText(/60.00 分/)).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: scaled.scale.id } });
  fireEvent.click(screen.getByRole("button", { name: "检查当前评分条件" }));
  const result = await screen.findByLabelText("技术条件检查结果");
  expect(result).toHaveTextContent("60.00 分 · 未加权原始分");
  expect(result).toHaveTextContent("官方聚合规则尚不可执行");
  expect(mocked.mock.calls.at(-1)?.[0]).toContain(
    `?scale_id=${scaled.scale.id}`,
  );
  fireEvent.change(select, { target: { value: "" } });
  expect(screen.queryByLabelText("技术条件检查结果")).not.toBeInTheDocument();
});

async function chooseHistorical() {
  fireEvent.change(screen.getByLabelText("技术范围检查用途"), {
    target: { value: "historical_backtest" },
  });
  expect(mocked).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "读取实交记录" }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("检查所用实交记录")).getAllByRole("option"),
    ).toHaveLength(2),
  );
  expect(screen.getByLabelText("检查所用实交记录")).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "检查历史样本条件" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("检查所用实交记录"), {
    target: { value: raw.sampleRequest.submission_id },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取该实交的成绩记录" }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("检查所用成绩记录")).getAllByRole("option"),
    ).toHaveLength(2),
  );
  expect(screen.getByLabelText("检查所用成绩记录")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("检查所用成绩记录"), {
    target: { value: raw.sampleRequest.outcome_id },
  });
}

it("keeps actual PG official zero distinct from unknown, and does not promote a sample", async () => {
  render(<PackageTechnicalEligibility saved={saved} />);
  await chooseHistorical();
  fireEvent.click(screen.getByRole("button", { name: "检查历史样本条件" }));
  const result = await screen.findByLabelText("技术条件检查结果");
  expect(result).toHaveTextContent("官方技术分0 分（关联已核验）");
  expect(result).toHaveTextContent("有据技术满分未知");
  expect(result).toHaveTextContent("待补条件，尚未创建正式样本");
  expect(mocked.mock.calls.at(-1)?.[0]).toBe(
    `${raw.basePath.replace("/api/v1", "")}/sample-context?submission_id=${raw.sampleRequest.submission_id}&outcome_id=${raw.sampleRequest.outcome_id}`,
  );
  fireEvent.change(screen.getByLabelText("技术范围检查用途"), {
    target: { value: "current_prebid" },
  });
  expect(screen.queryByLabelText("技术条件检查结果")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("检查所用成绩记录")).not.toBeInTheDocument();
  expect(mocked.mock.calls).toHaveLength(3);
});

it("rejects a changed official value even when the returned context has a matching digest", async () => {
  render(<PackageTechnicalEligibility saved={saved} />);
  await chooseHistorical();
  const changed = structuredClone(raw.sampleContext);
  changed.official_result.technical_value = "1";
  const stable = Object.fromEntries(
    Object.entries(changed).filter(([key]) => key !== "observed_at"),
  );
  mocked.mockResolvedValueOnce({
    data: changed,
    etag: `"package-technical-eligibility:${saved.manifest.id}:${await jsonDigest(stable)}"`,
  });
  fireEvent.click(screen.getByRole("button", { name: "检查历史样本条件" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("技术条件检查结果")).not.toBeInTheDocument();
});

it("does not apply an old response to a newly opened scope", async () => {
  let resolve!: (value: {
    data: typeof raw.scoringContext;
    etag: string;
  }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = render(<PackageTechnicalEligibility saved={saved} />);
  fireEvent.click(screen.getByRole("button", { name: "检查当前评分条件" }));
  view.rerender(
    <PackageTechnicalEligibility
      saved={scaled.scope as unknown as PackageTechnicalScopeView}
    />,
  );
  await act(async () => {
    resolve({ data: raw.scoringContext, etag: raw.scoringEtag });
  });
  expect(screen.queryByLabelText("技术条件检查结果")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "检查当前评分条件" }),
  ).toBeEnabled();
});
