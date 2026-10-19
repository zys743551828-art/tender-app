import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PackageFrozenInputWorkspace from "./PackageFrozenInputWorkspace";
import {
  freezeStorageKey,
  frozenManifestDigest,
  loadFreezeRecord,
  storeFreezeRecord,
} from "./packageFrozenInput";
import { clearRecordedCommands } from "./useRecordedCommand";
import type { FreezeScope } from "./packageFrozenInput";
import type {
  FreezePackageReviewInput,
  PackageReviewFrozenInputView,
} from "./contracts";

const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
  "node:crypto",
);
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope: FreezeScope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const body: FreezePackageReviewInput = {
  package_digest: "a".repeat(64),
  inventory_digest: "b".repeat(64),
  input_digest: "c".repeat(64),
  context_digest: "d".repeat(64),
  coverage_attempt_id: null,
  coverage_digest: null,
};
async function reply(): Promise<PackageReviewFrozenInputView> {
  const manifest: PackageReviewFrozenInputView["manifest"] = {
    version: "package-review-frozen-input/1",
    kind: "frozen_input",
    id: id(6),
    bid_id: scope.bidId,
    package_id: scope.packageId,
    revision_id: scope.revisionId,
    inventory_id: scope.inventoryId,
    actor_id: scope.memberId,
    command_id: id(7),
    input_digest: body.input_digest,
    context_digest: body.context_digest,
    evidence_digest: "e".repeat(64),
    as_of: "2026-10-19T08:00:00Z",
    frozen_at: "2026-10-19T08:00:01Z",
    blockers: ["PACKAGE_REVIEW_EXECUTOR_NOT_READY"],
    review_ready: false,
    launch_available: false,
    execution_context: {
      version: "package-review-context/1",
      kind: "candidate",
      input_digest: body.input_digest,
      semantic_digest: body.context_digest,
      snapshot_digest: "1".repeat(64),
      as_of: "2026-10-19T08:00:00Z",
      purpose: "prebid_compliance",
      method_digest: "2".repeat(64),
      policy_digest: "3".repeat(64),
      facts_digest: "4".repeat(64),
      sources_digest: "5".repeat(64),
      fact_set_id: null,
      fact_count: 0,
      confirmed_fact_count: 0,
      facts_binding: "empty",
      executor_available: false,
      formal_scoring_eligible: false,
    },
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
const respond = (data: unknown, status = 201) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const fetchMock = vi.fn();
beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", webcrypto);
  fetchMock.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const renderWorkspace = (candidate: FreezePackageReviewInput | null = body) =>
  render(
    <StrictMode>
      <PackageFrozenInputWorkspace scope={scope} candidate={candidate} />
    </StrictMode>,
  );
const save = () =>
  userEvent.click(screen.getByRole("button", { name: "保存本次冻结输入" }));
const recover = () =>
  userEvent.click(screen.getByRole("button", { name: "恢复原保存请求" }));

it("规范摘要与Python固定向量一致，保留中文和非BMP值", async () => {
  expect(
    await frozenManifestDigest({ z: false, 摘要: "标书", a: [1, null, "😀"] }),
  ).toBe("456907dbd43bf84dc88fc30fc1662e775071be87e01a89d473cccc8844fd47bc");
});

it("切换到另一成员，迟到响应不能改新成员的记录", async () => {
  let finish!: (response: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  const view = renderWorkspace();
  await save();
  const original = loadFreezeRecord(scope).pending;
  const other = { ...scope, memberId: id(99) };
  view.rerender(<PackageFrozenInputWorkspace scope={other} candidate={null} />);
  await act(async () => {
    finish(respond(await reply()));
  });
  expect(loadFreezeRecord(scope).pending).toEqual(original);
  expect(loadFreezeRecord(other).pending).toBeNull();
  expect(screen.queryByText("冻结输入已保存。")).not.toBeInTheDocument();
});

it("显式保存，先持久化原请求，再核对完整回执后解锁", async () => {
  const response = await reply();
  fetchMock.mockImplementation(async () => {
    expect(loadFreezeRecord(scope).pending?.body).toEqual(body);
    return respond(response);
  });
  renderWorkspace();
  expect(fetchMock).not.toHaveBeenCalled();
  await save();
  expect(await screen.findByText("冻结输入已保存。")).toBeInTheDocument();
  expect(loadFreezeRecord(scope)).toMatchObject({
    pending: null,
    lastId: id(6),
  });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(body);
  expect(screen.getByText(/尚不可正式评审/)).toBeInTheDocument();
});

it("丢失ACK并刷新，即使候选消失也以相同body和key恢复", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  const view = renderWorkspace();
  await save();
  await screen.findByRole("alert");
  const original = loadFreezeRecord(scope).pending;
  view.unmount();
  fetchMock.mockResolvedValueOnce(respond(await reply()));
  renderWorkspace(null);
  await recover();
  await screen.findByText("冻结输入已保存。");
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toBe(
    original!.key,
  );
});

it.each([400, 401, 403, 404, 409, 422, 428, 500])(
  "未知请求后重试收到%s仍保留，不换成当前候选",
  async (status) => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    const view = renderWorkspace();
    await save();
    await screen.findByRole("alert");
    const original = loadFreezeRecord(scope).pending;
    view.unmount();
    renderWorkspace({ ...body, context_digest: "f".repeat(64) });
    fetchMock.mockResolvedValueOnce(
      respond(
        { code: "PACKAGE_REVIEW_CONTEXT_CHANGED", message: "changed" },
        status,
      ),
    );
    await recover();
    await screen.findByRole("alert");
    expect(loadFreezeRecord(scope).pending).toEqual(original);
    expect(
      screen.getByRole("button", { name: "保存本次冻结输入" }),
    ).toBeDisabled();
  },
);

it.each([
  "actor",
  "scope",
  "input",
  "context",
  "executor",
  "digest",
  "blockers",
])("拒绝%s错误回执，保留原请求", async (field) => {
  const response = await reply();
  if (field === "actor") response.manifest.actor_id = id(99);
  if (field === "scope") response.manifest.inventory_id = id(99);
  if (field === "input") response.manifest.input_digest = "f".repeat(64);
  if (field === "context")
    response.manifest.execution_context.semantic_digest = "f".repeat(64);
  if (field === "executor")
    Object.assign(response.manifest, { launch_available: true });
  if (field === "blockers") response.manifest.blockers = [];
  if (field !== "digest")
    response.digest = await frozenManifestDigest(response.manifest);
  else response.digest = "0".repeat(64);
  fetchMock.mockResolvedValue(respond(response));
  renderWorkspace();
  await save();
  await screen.findByRole("alert");
  expect(loadFreezeRecord(scope).pending).not.toBeNull();
  expect(screen.queryByText("冻结输入已保存。")).not.toBeInTheDocument();
});

it("存储失败时不发POST，保留候选供重试", async () => {
  renderWorkspace();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage full");
  });
  await save();
  await screen.findByRole("alert");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "保存本次冻结输入" }),
  ).toBeEnabled();
});

it("首次明确拒绝可重新核验；已未知后的同类拒绝不能清除", async () => {
  fetchMock.mockResolvedValue(
    respond(
      { code: "PACKAGE_REVIEW_CONTEXT_CHANGED", message: "changed" },
      409,
    ),
  );
  renderWorkspace();
  await save();
  await screen.findByRole("alert");
  expect(loadFreezeRecord(scope).pending).toBeNull();
});

it("恢复记录损坏则阻止保存，不静默删除", async () => {
  sessionStorage.setItem(freezeStorageKey(scope), "{broken");
  renderWorkspace();
  expect(screen.getByRole("alert")).toBeInTheDocument();
  await save();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(freezeStorageKey(scope))).toBe("{broken");
});

it("不同成员或清单的伪装恢复记录不被采用，退出清理仅清相应成员", () => {
  const record = {
    version: 1 as const,
    scope,
    pending: { key: id(10), body },
    lastId: null,
  };
  storeFreezeRecord(record);
  const key = freezeStorageKey(scope);
  sessionStorage.setItem(
    key,
    JSON.stringify({ ...record, scope: { ...scope, inventoryId: id(99) } }),
  );
  expect(() => loadFreezeRecord(scope)).toThrow(/身份不符/);
  clearRecordedCommands(scope.memberId);
  expect(sessionStorage.getItem(key)).not.toBeNull();
  clearRecordedCommands(id(99));
  expect(sessionStorage.getItem(key)).toBeNull();
});

it("历史GET不依赖当前候选或可写状态，允许原记录的其他创建人", async () => {
  const response = await reply();
  response.manifest.actor_id = id(99);
  response.digest = await frozenManifestDigest(response.manifest);
  fetchMock.mockResolvedValue(respond(response, 200));
  render(
    <PackageFrozenInputWorkspace scope={scope} candidate={null} disabled />,
  );
  await userEvent.click(screen.getByText("读取历史冻结输入"));
  await userEvent.type(screen.getByLabelText("冻结输入记录编号"), id(6));
  await userEvent.click(screen.getByRole("button", { name: "读取历史记录" }));
  expect(await screen.findByText(/记录编号：/)).toHaveTextContent(id(6));
  expect(fetchMock.mock.calls[0][0]).toContain(
    `/frozen-review-inputs/${id(6)}`,
  );
  expect(fetchMock.mock.calls[0][1].method).toBe("GET");
  expect(loadFreezeRecord(scope).pending).toBeNull();
});

it("离开页面后晚到ACK不清理未决请求，不覆盖下一页面", async () => {
  let finish!: (response: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  const view = renderWorkspace();
  await save();
  const original = loadFreezeRecord(scope).pending;
  view.unmount();
  renderWorkspace(null);
  await act(async () => {
    finish(respond(await reply()));
  });
  expect(loadFreezeRecord(scope).pending).toEqual(original);
  expect(screen.queryByText("冻结输入已保存。")).not.toBeInTheDocument();
});
