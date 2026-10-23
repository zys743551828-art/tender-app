import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import type { PackageNextActions, PackageSubmissionView } from "./contracts";
import { PackageSubmissionReviewActions } from "./PackageSubmissionReviewActions";
import { PackageSubmissionCard } from "./PackageSubmissionCard";
import { WorkContextSubmissionDetails } from "./WorkContextSubmissionDetails";
import { nextActionSelection } from "./packageNextActionsProtocol";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { jsonDigest } from "./editorSchema";
import { validatePackageSubmission } from "./packageSubmissionProtocol";
import {
  submissionFixture,
  submissionReceipt,
  submissionScope,
  submissionId,
  submissionEtag,
} from "./packageSubmissionFixtures.test-support";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
vi.mock("./BusinessResults", () => ({ BusinessResults: () => null }));
vi.mock("./PackageOfficialOutcomes", () => ({
  PackageOfficialOutcomes: () => null,
}));
vi.mock("./PackageReviewOriginalRunDetails", () => ({
  default: (p: {
    reference: { id: string; result: { digest: string } | null };
    onClose: () => void;
  }) => (
    <section aria-label="实交原核查测试详情">
      {p.reference.id} · {p.reference.result?.digest}
      <button onClick={p.onClose}>关闭测试原核查</button>
    </section>
  ),
}));
const answer = (data: unknown) => ({ data, etag: null, replay: false });
let record: PackageSubmissionView;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.mocked(api).mockReset();
  record = await saved("complete");
});

// A synthetic frozen submission packet, validated through the real submission reader.
async function saved(mode: "complete" | "pending" | "none", number = 100) {
  const f = await submissionFixture(true);
  const ack = await submissionReceipt(
    f,
    {
      key: submissionId(77),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: null,
    },
    number,
  );
  const value = ack.submission;
  const m = value.package_binding.manifest;
  if (mode !== "none") {
    const run = (await workContextFixture()).completed;
    run.scope = {
      bid_id: value.bid_id,
      package_id: m.subject.package_id,
      revision_id: m.subject.revision_id,
      inventory_id: m.selection_request.inventory!.id,
    };
    run.result!.manifest.scope = run.scope;
    run.result!.digest = await jsonDigest(run.result!.manifest);
    if (mode === "pending") {
      run.result = null;
      run.operation.state = "queued";
      run.operation.finished_at = null;
    }
    m.review_run = run;
    m.selection_request.review_run = {
      id: run.id,
      input_digest: run.input_digest,
      result_digest: run.result?.digest ?? null,
    };
    m.gate.manifest.selection.run_id = run.id;
    m.gate.manifest.selection.result_digest = run.result?.digest ?? null;
    m.gate.digest = await jsonDigest(m.gate.manifest);
  }
  m.input_digest = await jsonDigest({
    selection: m.selection,
    selection_request: m.selection_request,
    context: m.context,
    review_run: m.review_run,
    inventory_proof: m.inventory_proof,
  });
  m.request.input_digest = m.input_digest;
  m.request_digest = await jsonDigest({
    body: {
      scope: [value.bid_id, m.subject.package_id, m.subject.revision_id],
      supersedes_id: m.supersedes_id,
      ...m.request,
    },
    if_match: m.if_match,
  });
  value.package_binding.digest = await jsonDigest(m);
  return validatePackageSubmission(value, value.bid_id, value.id);
}
function response(value = record): PackageNextActions {
  const r = value.package_binding.manifest.review_run!;
  return {
    version: "package-next-actions/1",
    binding: {
      scope: r.scope,
      run_id: r.id,
      input_digest: r.input_digest,
      result_digest: r.result!.digest,
      frozen_input_id: r.frozen_input_id,
      frozen_input_digest: r.frozen_input_digest,
      execution_input_id: r.execution_input_id,
      execution_input_digest: r.execution_input_digest,
      dependency_plan_id: r.dependency_plan_id,
      dependency_plan_digest: r.dependency_plan_digest,
      method_digest: r.method_digest,
    },
    method_digest: "a".repeat(64),
    confirmation_digest: "b".repeat(64),
    basis_digest: "c".repeat(64),
    observation_digest: "d".repeat(64),
    observed_at: "2026-10-23T12:00:00.000000Z",
    basis_status: "matched",
    basis_issues: [],
    current_scope_counts: {
      critical: 1,
      suggestions: 0,
      pending_critical_rules: 0,
    },
    historical_scope_counts: { critical: 1, suggestions: 0 },
    primary: {
      key: "inspect_critical_risks",
      level: 3,
      title: "核对实交所关联的关键问题",
      item_count: 1,
      requirement_ids: [r.result!.manifest.matrix[1].requirement_id],
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
const events = () => ({ onOpenPackage: vi.fn(), onOpenRules: vi.fn() });
it("实交阶段原记录使用同一冻结绑定和动作入口", async () => {
  const m = record.package_binding.manifest;
  vi.mocked(api).mockImplementation((path) =>
    Promise.resolve(
      answer(path.startsWith("/submissions/") ? record : response()),
    ),
  );
  render(
    <WorkContextSubmissionDetails
      memberId={submissionScope.memberId}
      onClose={vi.fn()}
      {...events()}
      selection={{
        kind: "package_submission",
        bid_id: record.bid_id,
        package_id: m.subject.package_id,
        revision_id: m.subject.revision_id,
        package_digest: m.subject.package_digest,
        submission_id: record.id,
        package_binding_digest: record.package_binding.digest,
        inventory: m.selection_request.inventory,
        review_run: {
          ...nextActionSelection(m.review_run!)!,
          kind: "package_review_run",
          package_digest: m.subject.package_digest,
          inventory_digest: m.selection_request.inventory!.digest,
        },
      }}
    />,
  );
  await screen.findByRole("region", { name: "实交关联核查的当前下一步" });
  expect(vi.mocked(api).mock.calls.map(([path]) => path)).toEqual([
    `/submissions/${record.id}`,
    `/bids/${record.bid_id}/package-next-actions/${m.review_run!.id}?expected_input_digest=${m.review_run!.input_digest}`,
  ]);
});
it.each(["none", "pending"] as const)(
  "%s关联不读其他核查、不填零数量",
  async (mode) => {
    render(
      <PackageSubmissionReviewActions
        record={await saved(mode)}
        memberId={submissionScope.memberId}
        {...events()}
      />,
    );
    expect(screen.getByText(/关键问题与建议数量未知/)).toBeInTheDocument();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  },
);
it("实交卡完整核验后按保存的运行读取，原报告只按原引用打开", async () => {
  vi.mocked(api).mockResolvedValue(answer(response()));
  render(
    <PackageSubmissionCard
      record={record}
      bidId={record.bid_id}
      memberId={submissionScope.memberId}
      disabled={false}
      onCorrect={vi.fn()}
      {...events()}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "核对实交所关联的关键问题（1项）",
    }),
  );
  const original = await screen.findByRole("region", {
    name: "实交原核查测试详情",
  });
  expect(original).toHaveTextContent(
    record.package_binding.manifest.review_run!.id,
  );
  expect(original).toHaveTextContent(
    record.package_binding.manifest.review_run!.result!.digest,
  );
  expect(vi.mocked(api).mock.calls.map(([path]) => path)).toEqual([
    `/bids/${record.bid_id}/package-next-actions/${record.package_binding.manifest.review_run!.id}?expected_input_digest=${record.package_binding.manifest.review_run!.input_digest}`,
  ]);
  fireEvent.click(screen.getByRole("button", { name: "关闭测试原核查" }));
  expect(
    screen.queryByRole("region", { name: "实交原核查测试详情" }),
  ).not.toBeInTheDocument();
});
it("登记编辑互锁期间保留数量但禁用定位，不自动确认或提交", async () => {
  vi.mocked(api).mockResolvedValue(answer(response()));
  render(
    <PackageSubmissionReviewActions
      record={record}
      memberId={submissionScope.memberId}
      disabled
      {...events()}
    />,
  );
  expect(
    await screen.findByRole("button", { name: /核对实交所关联的关键问题/ }),
  ).toBeDisabled();
  expect(screen.getByText(/请先完成或收起当前登记/)).toBeInTheDocument();
  expect(
    vi
      .mocked(api)
      .mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
  ).toBe(true);
});
it("固定选择与内嵌核查范围不符时不发动作请求", () => {
  record.package_binding.manifest.review_run!.scope.package_id =
    submissionId(999);
  render(
    <PackageSubmissionReviewActions
      record={record}
      memberId={submissionScope.memberId}
      {...events()}
    />,
  );
  expect(screen.getByText(/实交关联核查与固定选择不一致/)).toBeInTheDocument();
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});
it("服务器返回另一结果时不显示动作或数量", async () => {
  const bad = response();
  bad.binding.result_digest = "f".repeat(64);
  vi.mocked(api).mockResolvedValue(answer(bad));
  render(
    <PackageSubmissionReviewActions
      record={record}
      memberId={submissionScope.memberId}
      {...events()}
    />,
  );
  await screen.findByText(/下一步与明确选择的核查身份/);
  expect(screen.queryByText(/剩余关键问题 0项/)).not.toBeInTheDocument();
});
it("重读失败隐藏当前数量，登记时历史检查不改写", async () => {
  const historical = structuredClone(record.package_binding.manifest.gate);
  vi.mocked(api)
    .mockResolvedValueOnce(answer(response()))
    .mockRejectedValueOnce(new Error("关联核查观察中断"));
  render(
    <PackageSubmissionReviewActions
      record={record}
      memberId={submissionScope.memberId}
      {...events()}
    />,
  );
  await screen.findByRole("button", { name: /核对实交所关联的关键问题/ });
  fireEvent.click(screen.getByRole("button", { name: "重新核对下一步" }));
  await screen.findByText("关联核查观察中断");
  expect(screen.queryByText(/剩余关键问题 0项/)).not.toBeInTheDocument();
  expect(record.package_binding.manifest.gate).toEqual(historical);
});
it("切换实交绑定后不恢复晚到的旧动作", async () => {
  let resolveOld!: (v: ReturnType<typeof answer>) => void;
  vi.mocked(api)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue(answer(response()));
  const view = render(
    <PackageSubmissionReviewActions
      record={record}
      memberId={submissionScope.memberId}
      {...events()}
    />,
  );
  await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
  view.rerender(
    <PackageSubmissionReviewActions
      record={await saved("complete", 110)}
      memberId={submissionScope.memberId}
      {...events()}
    />,
  );
  await screen.findByRole("button", { name: /核对实交所关联的关键问题/ });
  const stale = response();
  stale.primary.title = "旧实交动作不应恢复";
  await act(async () => resolveOld(answer(stale)));
  expect(screen.queryByText("旧实交动作不应恢复")).not.toBeInTheDocument();
});
