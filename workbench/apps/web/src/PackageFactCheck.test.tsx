import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PackageFactCheck from "./PackageFactCheck";
import type {
  PackageExecutionInputView,
  PackageExecutionFactCheck,
} from "./contracts";
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const sha = (s: string) => s.repeat(64);
const scope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const prepared = {
  digest: sha("a"),
  manifest: {
    id: id(7),
    identity: { binding: { context_digest: sha("b") } },
    execution_context: {
      facts_digest: sha("c"),
      fact_count: 1,
      confirmed_fact_count: 1,
    },
  },
} as PackageExecutionInputView;
const reply = (): PackageExecutionFactCheck => ({
  kind: "fact_validation_observation",
  bid_id: id(2),
  package_id: id(3),
  revision_id: id(4),
  inventory_id: id(5),
  frozen_input_id: id(6),
  execution_input_id: id(7),
  execution_input_digest: sha("a"),
  prepared_context_digest: sha("b"),
  observed_context_digest: sha("b"),
  observed_facts_digest: sha("c"),
  matches_prepared_context: true,
  checked_at: "2026-10-20T08:00:00.000001Z",
  fact_count: 1,
  provenance_verified_count: 1,
  fact_checks: [
    {
      fact_id: id(8),
      provenance_status: "verified",
      scope_binding: "unproven",
      facts_qualified: false,
      blockers: ["FACT_SCOPE_MAPPING_REQUIRED"],
    },
  ],
  blockers: [],
  facts_qualified: false,
  original_verification: "not_performed",
  review_ready: false,
  launch_available: false,
  publication_authorized: false,
});
const fetchMock = vi.fn();
const response = (data: unknown) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const click = () =>
  userEvent.click(screen.getByRole("button", { name: "核对事实依据" }));
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
it("仅显式核对当前准备记录，不把依据链相符当事实执行资格", async () => {
  fetchMock.mockResolvedValueOnce(response(reply()));
  render(
    <PackageFactCheck scope={scope} frozenId={id(6)} prepared={prepared} />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await click();
  await screen.findByText(
    "当前 1 条事实，1 条依据链相符。事实执行资格仍未通过。",
  );
  expect(fetchMock.mock.calls[0][0]).toContain(
    `/execution-inputs/${id(7)}/fact-check`,
  );
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    execution_input_digest: prepared.digest,
  });
  await userEvent.click(screen.getByText("逐项核对结果"));
  expect(
    screen.getByText("仍需明确绑定投标主体、标段和适用范围。"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "启动评审" }),
  ).not.toBeInTheDocument();
});
it.each([
  "scope",
  "prepared",
  "digest",
  "counts",
  "fact_digest",
  "duplicate",
  "unknown",
  "qualified",
  "original",
  "context",
  "provenance",
  "date",
])("拒绝%s错配或越界响应", async (kind) => {
  const data = reply();
  if (kind === "scope") data.package_id = id(99);
  if (kind === "prepared") data.execution_input_id = id(99);
  if (kind === "digest") data.execution_input_digest = sha("0");
  if (kind === "counts") data.provenance_verified_count = 0;
  if (kind === "fact_digest") data.observed_facts_digest = sha("0");
  if (kind === "duplicate") {
    data.fact_checks.push(data.fact_checks[0]);
    data.fact_count = 2;
    data.provenance_verified_count = 2;
  }
  if (kind === "unknown")
    Object.assign(data.fact_checks[0], { blockers: ["UNKNOWN"] });
  if (kind === "qualified") Object.assign(data, { facts_qualified: true });
  if (kind === "original")
    Object.assign(data, { original_verification: "verified" });
  if (kind === "context") data.matches_prepared_context = false;
  if (kind === "provenance")
    data.fact_checks[0].blockers.push("FACT_SOURCE_NOT_EFFECTIVE");
  if (kind === "date") data.checked_at = "2026-02-30T08:00:00Z";
  fetchMock.mockResolvedValueOnce(response(data));
  render(
    <PackageFactCheck scope={scope} frozenId={id(6)} prepared={prepared} />,
  );
  await click();
  await screen.findByText("事实核对响应身份、数量或资格边界不符，未采纳。");
  expect(screen.queryByText(/当前 1 条事实/)).not.toBeInTheDocument();
});
it("新上下文和空事实均明确提示，不替换准备快照", async () => {
  const data = reply();
  Object.assign(data, {
    observed_context_digest: sha("0"),
    observed_facts_digest: sha("1"),
    matches_prepared_context: false,
    fact_count: 0,
    provenance_verified_count: 0,
    fact_checks: [],
    blockers: ["FACT_SET_EMPTY"],
  });
  fetchMock.mockResolvedValueOnce(response(data));
  render(
    <PackageFactCheck scope={scope} frozenId={id(6)} prepared={prepared} />,
  );
  await click();
  await screen.findByText(/当前上下文已变化/);
  expect(
    screen.getByText("当前尚无可核对事实，不能默认无事实要求。"),
  ).toBeInTheDocument();
  expect(prepared.manifest.execution_context.fact_count).toBe(1);
});
it("切换准备记录后旧核对响应不能覆盖当前状态", async () => {
  let resolve!: (v: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  );
  const view = render(
    <PackageFactCheck scope={scope} frozenId={id(6)} prepared={prepared} />,
  );
  await click();
  view.rerender(
    <PackageFactCheck
      scope={scope}
      frozenId={id(6)}
      prepared={{ ...prepared, manifest: { ...prepared.manifest, id: id(99) } }}
    />,
  );
  await act(async () => {
    resolve(response(reply()));
  });
  expect(screen.queryByText(/当前 1 条事实/)).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
