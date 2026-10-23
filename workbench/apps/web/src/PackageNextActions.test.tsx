import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { api } from "./api";
import type {
  PackageNextActions as NextActions,
  PackageWorkContext,
} from "./contracts";
import { PackageNextActions } from "./PackageNextActions";
import { checkedPackageNextActions } from "./packageNextActionsProtocol";
import Progress from "./PackageReviewProgress";
import { PackageReviewActionNavigation } from "./packageReviewActionNavigation";

vi.mock("./PackageReviewInputDetails", () => ({ default: () => null }));
vi.mock("./PackageReviewCancel", () => ({ default: () => null }));
vi.mock("./PackageReviewHumanDecisions", () => ({
  default: () => <p>所选逐条原报告</p>,
}));
vi.mock("./PackageReviewReportExports", () => ({ default: () => null }));

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
let fixture: Awaited<ReturnType<typeof workContextFixture>>;
const answer = (data: unknown) => ({ data, etag: null, replay: false });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.mocked(api).mockReset();
  fixture = await workContextFixture();
});
function response(context: PackageWorkContext = fixture.context): NextActions {
  const s = context.selection;
  if (s.kind !== "package_review_run") throw new Error("run fixture required");
  const requirement =
    fixture.completed.result!.manifest.matrix[1].requirement_id;
  return {
    version: "package-next-actions/1",
    binding: {
      scope: {
        bid_id: s.bid_id,
        package_id: s.package_id,
        revision_id: s.revision_id,
        inventory_id: s.inventory_id,
      },
      run_id: s.run_id,
      input_digest: s.input_digest,
      result_digest: s.result_digest,
      frozen_input_id: s.frozen_input_id,
      frozen_input_digest: s.frozen_input_digest,
      execution_input_id: s.execution_input_id,
      execution_input_digest: s.execution_input_digest,
      dependency_plan_id: s.dependency_plan_id,
      dependency_plan_digest: s.dependency_plan_digest,
      method_digest: s.method_digest,
    },
    method_digest: "a".repeat(64),
    confirmation_digest: "b".repeat(64),
    basis_digest: "c".repeat(64),
    observation_digest: "d".repeat(64),
    observed_at: "2026-10-23T00:00:00.000000Z",
    basis_status: "matched",
    basis_issues: [],
    current_scope_counts: {
      critical: 1,
      suggestions: 0,
      pending_critical_rules: 0,
    },
    historical_scope_counts: { critical: 1, suggestions: 0 },
    primary: {
      level: 3,
      key: "inspect_critical_risks",
      title: "核对所选范围的关键问题",
      requirement_ids: [requirement],
      item_count: 1,
    },
    other_actions: [],
    remaining_critical_count: 0,
    remaining_suggestion_count: 0,
    action_mode: "navigation_only",
    perspective: "selected_declared_scope",
    original_bytes_reverified: false,
    inventory_complete: false,
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
}
function callbacks() {
  return {
    onOpenOriginal: vi.fn(),
    onOpenPackage: vi.fn(),
    onOpenRules: vi.fn(),
  };
}

describe("所选运行的六级下一步", () => {
  it("直接报告的关键规则按钮使用宿主项目导航，保留同轮原报告", async () => {
    const value = response();
    value.current_scope_counts!.pending_critical_rules = 1;
    value.other_actions = [
      {
        level: 4,
        key: "confirm_critical_rules",
        title: "确认本次关键规则",
        item_count: 1,
        requirement_ids: [
          fixture.completed.result!.manifest.matrix[0].requirement_id,
        ],
      },
    ];
    vi.mocked(api).mockImplementation((path) =>
      Promise.resolve(
        answer(
          path.includes("/package-next-actions/") ? value : fixture.completed,
        ),
      ),
    );
    const events = callbacks();
    render(
      <PackageReviewActionNavigation.Provider
        value={{ bidId: fixture.completed.scope.bid_id, ...events }}
      >
        <Progress
          {...fixture.props}
          run={fixture.completed}
          onChange={vi.fn()}
          showComparison={false}
        />
      </PackageReviewActionNavigation.Provider>,
    );
    await screen.findByRole("button", { name: /核对所选范围的关键问题/ });
    fireEvent.click(screen.getByText(/剩余关键问题/));
    fireEvent.click(
      screen.getByRole("button", { name: "确认本次关键规则（1项）" }),
    );
    expect(events.onOpenRules).toHaveBeenCalledOnce();
    expect(screen.getByText("所选逐条原报告")).toBeInTheDocument();
  });

  it("直接报告拒绝将同等数量的关键问题移入建议计数", () => {
    const value = response();
    value.historical_scope_counts = { critical: 0, suggestions: 1 };
    value.current_scope_counts = {
      critical: 0,
      suggestions: 1,
      pending_critical_rules: 0,
    };
    expect(() => checkedPackageNextActions(value, fixture.completed)).toThrow();
  });

  it("未完成的明确运行只显示处理动作，不借其他报告填数量", async () => {
    const value = response();
    value.binding.result_digest = null;
    value.primary = {
      level: 2,
      key: "observe_run",
      title: "查看所选运行的处理状态",
      requirement_ids: [],
      item_count: null,
    };
    value.current_scope_counts = value.historical_scope_counts = null;
    value.remaining_critical_count = value.remaining_suggestion_count = null;
    vi.mocked(api).mockResolvedValue(answer(value));
    const events = callbacks();
    render(<PackageNextActions run={fixture.run} {...events} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "查看所选运行的处理状态" }),
    );
    expect(events.onOpenOriginal).toHaveBeenCalledOnce();
    expect(screen.getByText(/剩余关键问题 未知/)).toBeInTheDocument();
    expect(screen.queryByText(/所选原报告的历史计数/)).not.toBeInTheDocument();
  });

  it("直接报告无需构造工作上下文，读取相同确切运行并定位本轮原报告", async () => {
    vi.mocked(api).mockImplementation((path) =>
      Promise.resolve(
        answer(
          path.includes("/package-next-actions/")
            ? response()
            : fixture.completed,
        ),
      ),
    );
    const events = callbacks();
    render(
      <PackageReviewActionNavigation.Provider
        value={{ bidId: fixture.completed.scope.bid_id, ...events }}
      >
        <Progress
          {...fixture.props}
          run={fixture.completed}
          onChange={vi.fn()}
          showComparison={false}
        />
      </PackageReviewActionNavigation.Provider>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /核对所选范围的关键问题/ }),
    );
    expect(screen.getByLabelText("本轮逐条原报告")).toHaveFocus();
    const paths = vi.mocked(api).mock.calls.map(([path]) => path);
    expect(paths).toContain(
      `/bids/${fixture.completed.scope.bid_id}/package-next-actions/${fixture.completed.id}?expected_input_digest=${fixture.completed.input_digest}`,
    );
    expect(paths.some((path) => path.includes("work-context"))).toBe(false);
    expect(events.onOpenPackage).not.toHaveBeenCalled();
  });

  it("其他项目的导航不提供本报告动作，也不读其他运行", async () => {
    vi.mocked(api).mockResolvedValue(answer(fixture.completed));
    render(
      <PackageReviewActionNavigation.Provider
        value={{
          bidId: "00000000-0000-4000-8000-000000000099",
          ...callbacks(),
        }}
      >
        <Progress
          {...fixture.props}
          run={fixture.completed}
          onChange={vi.fn()}
          showComparison={false}
        />
      </PackageReviewActionNavigation.Provider>,
    );
    await screen.findByText(/最近成功读取/);
    expect(
      screen.queryByRole("region", { name: "本轮主要下一步" }),
    ).not.toBeInTheDocument();
    expect(
      vi
        .mocked(api)
        .mock.calls.some(([path]) => path.includes("/package-next-actions/")),
    ).toBe(false);
  });

  it.each([
    "run_id",
    "input_digest",
    "result_digest",
    "frozen_input_digest",
    "execution_input_digest",
    "dependency_plan_digest",
    "method_digest",
    "package_id",
    "revision_id",
    "inventory_id",
    "bid_id",
  ] as const)("直接报告拒绝%s绑定不一致", (field) => {
    const value = response();
    if (field in value.binding.scope)
      value.binding.scope[field as keyof typeof value.binding.scope] =
        "00000000-0000-4000-8000-000000000099";
    else
      value.binding[
        field as Exclude<typeof field, keyof typeof value.binding.scope>
      ] = field.endsWith("_id")
        ? "00000000-0000-4000-8000-000000000099"
        : "f".repeat(64);
    expect(() => checkedPackageNextActions(value, fixture.completed)).toThrow();
  });

  it("直接报告拒绝数量相同但不属于所选原矩阵的要求", () => {
    const value = response();
    value.primary.requirement_ids = ["00000000-0000-4000-8000-000000000099"];
    expect(() => checkedPackageNextActions(value, fixture.completed)).toThrow();
  });

  it("直接报告重读失败隐藏之前数量，原报告保留", async () => {
    let reads = 0;
    vi.mocked(api).mockImplementation((path) =>
      path.includes("/package-next-actions/")
        ? ++reads === 1
          ? Promise.resolve(answer(response()))
          : Promise.reject(new Error("下一步观察失败"))
        : Promise.resolve(answer(fixture.completed)),
    );
    render(
      <PackageReviewActionNavigation.Provider
        value={{ bidId: fixture.completed.scope.bid_id, ...callbacks() }}
      >
        <Progress
          {...fixture.props}
          run={fixture.completed}
          onChange={vi.fn()}
          showComparison={false}
        />
      </PackageReviewActionNavigation.Provider>,
    );
    await screen.findByRole("button", { name: /核对所选范围的关键问题/ });
    fireEvent.click(screen.getByRole("button", { name: "重新核对下一步" }));
    await screen.findByText("下一步观察失败");
    expect(screen.queryByText(/剩余关键问题 0项/)).not.toBeInTheDocument();
    expect(screen.getByText("所选逐条原报告")).toBeInTheDocument();
  });

  it("仅定位同一原报告，不自动启动或确认", async () => {
    vi.mocked(api).mockResolvedValue(answer(response()));
    const events = callbacks();
    render(<PackageNextActions context={fixture.context} {...events} />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "核对所选范围的关键问题（1项）",
      }),
    );
    expect(events.onOpenOriginal).toHaveBeenCalledOnce();
    expect(screen.getByText(/剩余关键问题 0项/)).toBeInTheDocument();
    expect(screen.getByText(/只统计已选核查范围/)).not.toBeVisible();
    expect(
      vi
        .mocked(api)
        .mock.calls.every(
          ([, options]) => !options?.method || options.method === "GET",
        ),
    ).toBe(true);
  });

  it("依据变化只显示历史计数，按钮打开此次返回的新依据缺口", async () => {
    const value = response();
    value.basis_status = "changed";
    value.current_scope_counts = null;
    value.remaining_critical_count = value.remaining_suggestion_count = null;
    value.primary = {
      level: 1,
      key: "inspect_changed_basis",
      title: "先核对变化依据",
      requirement_ids: [],
      item_count: null,
    };
    value.basis_issues = [
      {
        dimension: "sources",
        status: "changed",
        message: "来源当前效力已变化，请核对本次选择",
      },
    ];
    vi.mocked(api).mockResolvedValue(answer(value));
    const events = callbacks();
    render(<PackageNextActions context={fixture.context} {...events} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "先核对变化依据" }),
    );
    await waitFor(() =>
      expect(screen.getByText("本次下一步所依据的变化与缺口")).toHaveFocus(),
    );
    expect(screen.getByText(value.basis_issues[0].message)).toBeVisible();
    expect(screen.getByText(/剩余关键问题 未知/)).toBeInTheDocument();
    expect(screen.getByText(/所选原报告的历史计数/)).toBeInTheDocument();
    expect(events.onOpenOriginal).not.toHaveBeenCalled();
  });

  it.each(["input_digest", "result_digest", "run_id"] as const)(
    "拒绝跨%s结果而不回退旧动作",
    async (field) => {
      const value = response();
      value.binding[field] =
        field === "run_id"
          ? "00000000-0000-4000-8000-000000000099"
          : "f".repeat(64);
      vi.mocked(api).mockResolvedValue(answer(value));
      render(<PackageNextActions context={fixture.context} {...callbacks()} />);
      expect(
        await screen.findByText(/下一步与明确选择的核查身份/),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /核对所选范围的关键问题/ }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([
    "inventory_complete",
    "formal_scoring_eligible",
    "submission_eligible",
  ] as const)("拒绝把%s资格转绿", (field) => {
    const value = { ...response(), [field]: true };
    expect(() => checkedPackageNextActions(value, fixture.context)).toThrow();
  });

  it("拒绝重复定位同一要求和伪造的历史零计数", () => {
    const value = response();
    value.other_actions = [
      { ...value.primary, key: "confirm_critical_rules", level: 4 },
    ];
    expect(() => checkedPackageNextActions(value, fixture.context)).toThrow();
    const zero = response();
    zero.historical_scope_counts!.critical = 0;
    zero.current_scope_counts!.critical = 0;
    expect(() => checkedPackageNextActions(zero, fixture.context)).toThrow();
  });

  it("关键规则动作使用规则工作面，原报告仍保持所选身份", async () => {
    const context = structuredClone(fixture.context);
    context.summary.review!.machine_counts = {
      satisfied: 2,
      violated: 0,
      not_found: 0,
      unable_to_judge: 0,
      not_applicable: 0,
    };
    const value = response(context);
    value.historical_scope_counts!.critical =
      value.current_scope_counts!.critical = 0;
    value.current_scope_counts!.pending_critical_rules = 1;
    value.primary = {
      ...value.primary,
      level: 4,
      key: "confirm_critical_rules",
      title: "核对本次仍待确认的关键规则",
    };
    vi.mocked(api).mockResolvedValue(answer(value));
    const events = callbacks();
    render(<PackageNextActions context={context} {...events} />);
    fireEvent.click(
      await screen.findByRole("button", { name: /核对本次仍待确认的关键规则/ }),
    );
    expect(events.onOpenRules).toHaveBeenCalledOnce();
    expect(events.onOpenOriginal).not.toHaveBeenCalled();
  });

  it("重读失败隐藏此前动作和计数", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce(answer(response()))
      .mockRejectedValueOnce(new Error("本轮观察读取中断"));
    render(<PackageNextActions context={fixture.context} {...callbacks()} />);
    await screen.findByRole("button", { name: /核对所选范围的关键问题/ });
    fireEvent.click(screen.getByRole("button", { name: "重新核对下一步" }));
    expect(await screen.findByText("本轮观察读取中断")).toBeInTheDocument();
    expect(screen.queryByText(/剩余关键问题 0项/)).not.toBeInTheDocument();
  });

  it("切换原运行后丢弃晚到响应", async () => {
    let resolveOld!: (value: ReturnType<typeof answer>) => void;
    const next = structuredClone(fixture.context);
    if (next.selection.kind !== "package_review_run")
      throw new Error("run fixture");
    next.selection.run_id = "00000000-0000-4000-8000-000000000099";
    vi.mocked(api).mockImplementation((path) =>
      path.includes("000000000099")
        ? Promise.resolve(answer(response(next)))
        : new Promise((resolve) => {
            resolveOld = resolve;
          }),
    );
    const view = render(
      <PackageNextActions context={fixture.context} {...callbacks()} />,
    );
    await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
    view.rerender(<PackageNextActions context={next} {...callbacks()} />);
    await screen.findByRole("button", { name: /核对所选范围的关键问题/ });
    const stale = response();
    stale.primary.title = "不应出现的旧轮次动作";
    await act(async () => resolveOld(answer(stale)));
    expect(screen.queryByText(/不应出现的旧轮次动作/)).not.toBeInTheDocument();
  });
});
