import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageExecutionInputWorkspace";
import type {
  PackageReviewFrozenInputView,
  PackageReviewEligibilityObservation,
} from "./contracts";
import { frozenManifestDigest } from "./packageFrozenInput";
import { prepared } from "../qa-previews/frozen-inputs/prepared";
import { executionScope, executionStorageKey } from "./executionInputRecovery";
import { validateExecutionInput } from "./executionInputValidation";
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const sha = (s: string) => s.repeat(64);
const scope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const frozen = {
  digest: sha("a"),
  manifest: {
    id: id(6),
    bid_id: id(2),
    package_id: id(3),
    revision_id: id(4),
    inventory_id: id(5),
    actor_id: id(1),
    command_id: id(7),
    input_digest: sha("b"),
    evidence_digest: sha("c"),
    frozen_at: "2026-10-19T08:00:00Z",
    execution_context: {
      version: "package-review-context/1",
      kind: "candidate",
      input_digest: sha("b"),
      semantic_digest: sha("d"),
      snapshot_digest: sha("e"),
      as_of: "2026-10-19T08:00:00Z",
      purpose: "prebid_compliance",
      method_digest: sha("1"),
      policy_digest: sha("2"),
      facts_digest: sha("3"),
      sources_digest: sha("4"),
      fact_set_id: null,
      fact_count: 0,
      confirmed_fact_count: 0,
      facts_binding: "empty",
      executor_available: false,
      formal_scoring_eligible: false,
    },
  },
} as PackageReviewFrozenInputView;
const candidate: PackageReviewEligibilityObservation = {
  kind: "eligibility_observation",
  frozen_input_id: id(6),
  frozen_digest: frozen.digest,
  input_digest: sha("b"),
  checked_at: "2026-10-19T08:01:00Z",
  current_context: {
    ...frozen.manifest.execution_context,
    as_of: "2026-10-19T08:01:00Z",
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
};
const expectation = {
  body: { frozen_digest: frozen.digest, context_digest: sha("d"), rerun: null },
  context: candidate.current_context,
};
const storageKey = executionStorageKey(executionScope(scope, frozen));
const fetchMock = vi.fn();
const response = (data: unknown, status = 201) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const save = () =>
  userEvent.click(screen.getByRole("button", { name: "保存当前执行准备输入" }));
const recover = () =>
  userEvent.click(screen.getByRole("button", { name: "恢复原执行准备请求" }));
beforeEach(() => {
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("仅显式保存，先写恢复记录再请求，校验回执且不启动任务", async () => {
  fetchMock.mockImplementation(async (_url, options) => {
    const stored = JSON.parse(sessionStorage.getItem(storageKey)!);
    expect(stored.pending.key).toBe(options.headers["Idempotency-Key"]);
    expect(stored.pending.body).toEqual(JSON.parse(options.body));
    return response(await prepared(frozen, id(20)));
  });
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  expect(fetchMock).not.toHaveBeenCalled();
  await save();
  expect(
    await screen.findByText("执行准备输入已读回并校验，尚未启动评审。"),
  ).toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem(storageKey)!).pending).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("丢失回执后重挂载不自动重发，候选消失仍用原键原体恢复", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  const view = render(
    <Workspace scope={scope} frozen={frozen} candidate={candidate} />,
  );
  await save();
  await screen.findByText(/有一笔执行准备输入保存尚未确认/);
  const first = fetchMock.mock.calls[0];
  view.unmount();
  render(<Workspace scope={scope} frozen={frozen} candidate={null} />);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fetchMock.mockResolvedValueOnce(response(await prepared(frozen, id(20))));
  await recover();
  await screen.findByText("执行准备输入已读回并校验，尚未启动评审。");
  expect(fetchMock.mock.calls[1][1]).toEqual(first[1]);
});
it.each([false, true])(
  "明确拒绝只释放首次请求，恢复拒绝保留：%s",
  async (recovery) => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
    if (recovery) {
      await save();
      await screen.findByText(/有一笔执行准备输入保存尚未确认/);
    }
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(
      response(
        {
          code: "PACKAGE_REVIEW_CONTEXT_CHANGED",
          message: "上下文变化",
        },
        409,
      ),
    );
    if (recovery) await recover();
    else await save();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存当前执行准备输入" }),
      ).not.toHaveTextContent("正在"),
    );
    expect(!!JSON.parse(sessionStorage.getItem(storageKey)!).pending).toBe(
      recovery,
    );
  },
);
it.each([
  "digest",
  "scope",
  "actor",
  "flags",
  "snapshot",
  "blockers",
  "method",
  "micros",
  "rerun",
])("拒绝%s异常回执，即使重新计算外层摘要", async (kind) => {
  const data = await prepared(frozen, id(20));
  const m = data.manifest;
  if (kind === "scope") m.package_id = id(99);
  if (kind === "actor") m.actor_id = id(99);
  if (kind === "flags") Object.assign(m, { launch_available: true });
  if (kind === "snapshot") m.snapshot_digest = "not-a-digest";
  if (kind === "blockers") m.blockers.push("PACKAGE_REVIEW_METHOD_CHANGED");
  if (kind === "method") m.execution_context.method_digest = sha("0");
  if (kind === "micros") {
    m.originals_verified_at = "2026-10-19T08:03:00.000002Z";
    m.execution_context.as_of = m.originals_verified_at;
    m.saved_at = "2026-10-19T08:03:00.000001Z";
  }
  if (kind === "rerun") m.identity.rerun = { nonce: id(99), reason: "rerun" };
  data.digest = kind === "digest" ? sha("0") : await frozenManifestDigest(m);
  await expect(
    validateExecutionInput(data, scope, frozen, expectation),
  ).rejects.toThrow();
});
it("损坏记录或存储失败不得发送新请求", async () => {
  sessionStorage.setItem(storageKey, "{}");
  const view = render(
    <Workspace scope={scope} frozen={frozen} candidate={candidate} />,
  );
  expect(
    screen.getByRole("button", { name: "保存当前执行准备输入" }),
  ).toBeDisabled();
  view.unmount();
  sessionStorage.clear();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  await save();
  expect(fetchMock).not.toHaveBeenCalled();
});
it("回执成功但本机完成记录失败，保留原请求供恢复", async () => {
  const original = Storage.prototype.setItem;
  let calls = 0;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    k,
    v,
  ) {
    if (++calls === 2) throw new Error("full");
    original.call(this, k, v);
  });
  fetchMock.mockResolvedValueOnce(response(await prepared(frozen, id(20))));
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  await save();
  await screen.findByText(/有一笔执行准备输入保存尚未确认/);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原执行准备请求" }),
    ).not.toBeDisabled(),
  );
  expect(
    JSON.parse(sessionStorage.getItem(storageKey)!).pending,
  ).not.toBeNull();
  expect(
    screen.queryByText("执行准备输入已读回并校验，尚未启动评审。"),
  ).not.toBeInTheDocument();
});
it("旧范围迟到回执不清理待恢复记录", async () => {
  let resolve!: (v: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  );
  const view = render(
    <Workspace scope={scope} frozen={frozen} candidate={candidate} />,
  );
  await save();
  view.rerender(
    <Workspace
      scope={{ ...scope, memberId: id(99) }}
      frozen={frozen}
      candidate={null}
    />,
  );
  await act(async () => {
    resolve(response(await prepared(frozen, id(20))));
  });
  expect(
    JSON.parse(sessionStorage.getItem(storageKey)!).pending,
  ).not.toBeNull();
  expect(
    screen.queryByText("执行准备输入已读回并校验，尚未启动评审。"),
  ).not.toBeInTheDocument();
});
it("精确历史读取允许历史操作者，且不释放待恢复保存", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  await save();
  await screen.findByText(/有一笔执行准备输入保存尚未确认/);
  const data = await prepared(frozen, id(20));
  data.manifest.actor_id = id(99);
  data.digest = await frozenManifestDigest(data.manifest);
  fetchMock.mockResolvedValueOnce(response(data, 200));
  await userEvent.click(screen.getByText("读取已有执行准备输入"));
  await userEvent.type(screen.getByLabelText("执行准备输入编号"), id(20));
  await userEvent.click(
    screen.getByRole("button", { name: "读取执行准备输入" }),
  );
  await screen.findByText("执行准备输入已读回并校验，尚未启动评审。");
  expect(
    JSON.parse(sessionStorage.getItem(storageKey)!).pending,
  ).not.toBeNull();
  expect(fetchMock.mock.calls[1][1].method).toBe("GET");
});

it("异常回执不得确认成功或释放原请求", async () => {
  const data = await prepared(frozen, id(20));
  data.digest = sha("0");
  fetchMock.mockResolvedValueOnce(response(data));
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  await save();
  await screen.findByText(/执行准备输入响应身份、摘要或边界不符/);
  expect(
    JSON.parse(sessionStorage.getItem(storageKey)!).pending,
  ).not.toBeNull();
  expect(
    screen.queryByText("执行准备输入已读回并校验，尚未启动评审。"),
  ).not.toBeInTheDocument();
});

it("编辑历史编号后迟到读回不得覆盖当前选择", async () => {
  let resolve!: (v: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  );
  render(<Workspace scope={scope} frozen={frozen} candidate={candidate} />);
  await userEvent.click(screen.getByText("读取已有执行准备输入"));
  const input = screen.getByLabelText("执行准备输入编号");
  await userEvent.type(input, id(20));
  await userEvent.click(
    screen.getByRole("button", { name: "读取执行准备输入" }),
  );
  await userEvent.clear(input);
  await userEvent.type(input, id(21));
  await act(async () => {
    resolve(response(await prepared(frozen, id(20)), 200));
  });
  expect(
    screen.queryByText("执行准备输入已读回并校验，尚未启动评审。"),
  ).not.toBeInTheDocument();
});
