import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageFactScopeWorkspace";
import type {
  ChangePackageFactScope,
  PackageExecutionInputView,
} from "./contracts";
import {
  scopeId as id,
  scopeObservation,
  scopeReply,
} from "../qa-previews/frozen-inputs/factScope";
import { loadFactScopeRecord, storeFactScopeRecord } from "./factScopeRecovery";
import {
  validateScopeObservation,
  validateScopeRecord,
} from "./factScopeValidation";
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
    identity: {
      binding: {
        bid_id: id(2),
        package_id: id(3),
        revision_id: id(4),
        inventory_id: id(5),
        frozen_input_id: id(6),
        identity_digest: sha("1"),
        frozen_digest: sha("2"),
        input_digest: sha("3"),
        evidence_digest: sha("4"),
        context_digest: sha("b"),
        method_digest: sha("5"),
        policy_digest: sha("6"),
        purpose: "prebid_compliance",
      },
    },
    execution_context: { facts_digest: sha("c"), fact_set_id: id(50) },
  },
} as PackageExecutionInputView;
const keyScope = {
  ...scope,
  frozenId: id(6),
  preparedId: id(7),
  preparedDigest: sha("a"),
};
const body = (): ChangePackageFactScope => ({
  execution_input_digest: prepared.digest,
  fact_id: id(90),
  action: "bind",
  subject: { kind: "lot", id: id(61) },
  reason: "人工明确范围",
  previous_digest: null,
});
const props = { scope, frozenId: id(6), prepared, factIds: [id(90)] };
const fetchMock = vi.fn();
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
async function open() {
  await userEvent.click(
    screen.getByText("事实适用范围", { selector: "summary" }),
  );
}
async function observe() {
  await userEvent.type(screen.getByLabelText("待核对的事实编号"), id(90));
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前事实范围" }),
  );
  await screen.findByText("此事实尚无范围声明。");
}
async function fill() {
  await userEvent.selectOptions(screen.getByLabelText("明确适用对象"), "lot");
  await userEvent.type(screen.getByLabelText("声明或撤回理由"), body().reason);
}
beforeEach(() => {
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("仅显式读取和选择；先保存恢复体，再发送声明，不授执行资格", async () => {
  fetchMock.mockResolvedValueOnce(response(scopeObservation(prepared, id(90))));
  fetchMock.mockImplementationOnce(async (_url, options) => {
    const saved = loadFactScopeRecord(keyScope);
    expect(saved.pending?.key).toBe(options.headers["Idempotency-Key"]);
    expect(saved.pending?.body).toEqual(JSON.parse(options.body));
    return response(
      await scopeReply(
        prepared,
        JSON.parse(options.body),
        scope.memberId,
        id(100),
      ),
      201,
    );
  });
  render(<Workspace {...props} />);
  expect(fetchMock).not.toHaveBeenCalled();
  await open();
  await observe();
  expect(screen.getByRole("button", { name: "保存范围声明" })).toBeDisabled();
  await fill();
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  await screen.findByText("范围声明记录已读回校验；当前有效性需另行重读。");
  expect(loadFactScopeRecord(keyScope).pending).toBeNull();
  expect(loadFactScopeRecord(keyScope).lastFactId).toBe(id(90));
});
it("丢失ACK后重挂载不自动重发，按原键原体恢复已提交声明", async () => {
  let accepted: Awaited<ReturnType<typeof scopeReply>>;
  fetchMock.mockResolvedValueOnce(response(scopeObservation(prepared, id(90))));
  fetchMock.mockImplementationOnce(async (_url, options) => {
    accepted = await scopeReply(
      prepared,
      JSON.parse(options.body),
      scope.memberId,
      id(100),
    );
    throw new Error("ACK lost after commit");
  });
  const view = render(<Workspace {...props} />);
  await open();
  await observe();
  await fill();
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  await screen.findByText(/有一条范围操作的结果尚未确认/);
  const first = fetchMock.mock.calls[1];
  view.unmount();
  render(<Workspace {...props} />);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  fetchMock.mockResolvedValueOnce(response(accepted!, 201));
  await userEvent.click(screen.getByRole("button", { name: "恢复范围原请求" }));
  await screen.findByText("范围声明记录已读回校验；当前有效性需另行重读。");
  const second = fetchMock.mock.calls[2];
  expect(second[1].body).toBe(first[1].body);
  expect(second[1].headers["Idempotency-Key"]).toBe(
    first[1].headers["Idempotency-Key"],
  );
});
it("历史读回不清除未决请求", async () => {
  const previous = await scopeReply(prepared, body(), scope.memberId, id(100));
  storeFactScopeRecord({
    version: 1,
    scope: keyScope,
    pending: { key: id(101), body: body() },
    lastId: id(100),
    lastFactId: id(90),
  });
  fetchMock.mockResolvedValueOnce(response(previous));
  render(<Workspace {...props} />);
  await userEvent.click(
    screen.getByText("读取已有范围记录", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取范围原记录" }));
  await screen.findByText("范围声明记录已读回校验；当前有效性需另行重读。");
  expect(loadFactScopeRecord(keyScope).pending?.key).toBe(id(101));
});
it("来源失效时只允许追加撤回，旧记录不被改写", async () => {
  const previous = await scopeReply(prepared, body(), scope.memberId, id(100));
  fetchMock.mockResolvedValueOnce(
    response(scopeObservation(prepared, id(90), previous, true)),
  );
  fetchMock.mockImplementationOnce(async (_url, options) => {
    const value = JSON.parse(options.body) as ChangePackageFactScope;
    expect(value).toEqual({
      ...body(),
      action: "withdraw",
      subject: null,
      previous_digest: previous.digest,
    });
    return response(
      await scopeReply(prepared, value, scope.memberId, id(101), previous),
      201,
    );
  });
  render(<Workspace {...props} />);
  await open();
  await userEvent.type(screen.getByLabelText("待核对的事实编号"), id(90));
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前事实范围" }),
  );
  await screen.findByText("已有声明，但当前适用性仍待核对。");
  await userEvent.type(screen.getByLabelText("声明或撤回理由"), body().reason);
  expect(screen.getByRole("button", { name: "保存范围声明" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "撤回范围声明" }));
  await screen.findByText("范围撤回记录已读回校验；当前有效性需另行重读。");
  expect(previous.manifest.action).toBe("bind");
});
it("存储失败时不发送写请求", async () => {
  fetchMock.mockResolvedValueOnce(response(scopeObservation(prepared, id(90))));
  render(<Workspace {...props} />);
  await open();
  await observe();
  await fill();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage full");
  });
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  await screen.findByText("storage full");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("换事实编号后迟到观察不覆盖新选择", async () => {
  let resolve!: (r: Response) => void;
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((r) => {
      resolve = r;
    }),
  );
  render(<Workspace {...props} />);
  await open();
  await userEvent.type(screen.getByLabelText("待核对的事实编号"), id(90));
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前事实范围" }),
  );
  await userEvent.clear(screen.getByLabelText("待核对的事实编号"));
  await act(async () => {
    resolve(response(scopeObservation(prepared, id(90))));
  });
  expect(screen.queryByText("此事实尚无范围声明。")).not.toBeInTheDocument();
});
it.each(["digest", "scope", "grant", "actor", "previous"])(
  "异常回执%s不清未决请求",
  async (change) => {
    fetchMock.mockResolvedValueOnce(
      response(scopeObservation(prepared, id(90))),
    );
    fetchMock.mockImplementationOnce(async (_url, options) => {
      const v = await scopeReply(
        prepared,
        JSON.parse(options.body),
        scope.memberId,
        id(100),
      );
      if (change === "digest") v.digest = sha("0");
      if (change === "scope") v.manifest.binding.revision_id = id(99);
      if (change === "grant")
        Object.assign(v.manifest, { facts_qualified: true });
      if (change === "actor") v.manifest.actor_id = id(99);
      if (change === "previous") v.manifest.previous_digest = sha("f");
      return response(v, 201);
    });
    render(<Workspace {...props} />);
    await open();
    await observe();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
    await screen.findByText(/事实范围记录身份、摘要或资格边界不符/);
    expect(loadFactScopeRecord(keyScope).pending).not.toBeNull();
  },
);
it.each(["facts", "head", "count", "time", "grant", "context"])(
  "观察%s不符不能用于保存",
  async (change) => {
    const v = scopeObservation(prepared, id(90));
    if (change === "facts") v.fact_id = id(99);
    if (change === "head") v.binding_status = "matches_current_input";
    if (change === "count") v.subject_choices.pop();
    if (change === "time") v.checked_at = "2026-02-30T00:00:00.000000Z";
    if (change === "grant") Object.assign(v, { launch_available: true });
    if (change === "context") v.observed_context_digest = sha("f");
    await expect(
      validateScopeObservation(v, scope, id(6), prepared, id(90)),
    ).rejects.toThrow();
  },
);
it("错误历史摘要与损坏恢复记录均拒绝，不发送恢复", async () => {
  const v = await scopeReply(prepared, body(), scope.memberId, id(100));
  v.manifest.reason = "另一个理由";
  await expect(validateScopeRecord(v, prepared)).rejects.toThrow();
  const record = {
    version: 1 as const,
    scope: keyScope,
    pending: {
      key: id(100),
      body: { ...body(), execution_input_digest: sha("f") },
    },
    lastId: null,
    lastFactId: null,
  };
  storeFactScopeRecord(record);
  render(<Workspace {...props} />);
  await screen.findByText(/事实范围恢复记录损坏或身份不符/);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("再次保存先清旧成功，断网不能留下当前保存已成功的提示", async () => {
  const v = await scopeReply(prepared, body(), scope.memberId, id(100));
  storeFactScopeRecord({
    version: 1,
    scope: keyScope,
    pending: null,
    lastId: v.manifest.id,
    lastFactId: id(90),
  });
  fetchMock.mockResolvedValueOnce(response(v));
  fetchMock.mockResolvedValueOnce(
    response(scopeObservation(prepared, id(90), v)),
  );
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  render(<Workspace {...props} />);
  await open();
  await userEvent.click(
    screen.getByText("读取已有范围记录", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取范围原记录" }));
  await screen.findByText("范围声明记录已读回校验；当前有效性需另行重读。");
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前事实范围" }),
  );
  await screen.findByText("范围声明与当前输入匹配。");
  await fill();
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  await waitFor(() =>
    expect(loadFactScopeRecord(keyScope).pending).not.toBeNull(),
  );
  expect(
    screen.queryByText("范围声明记录已读回校验；当前有效性需另行重读。"),
  ).not.toBeInTheDocument();
});
it("首次明确拒绝释放待确认记录，仍须重读后才能再次保存", async () => {
  fetchMock.mockResolvedValueOnce(response(scopeObservation(prepared, id(90))));
  fetchMock.mockResolvedValueOnce(
    response(
      { code: "PACKAGE_FACT_SCOPE_CHANGED", message: "范围已变化" },
      409,
    ),
  );
  render(<Workspace {...props} />);
  await open();
  await observe();
  await fill();
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  await screen.findByText(/范围已变化/);
  expect(loadFactScopeRecord(keyScope).pending).toBeNull();
  expect(screen.queryByLabelText("明确适用对象")).not.toBeInTheDocument();
});
it("恢复原请求被拒仍保留原键原体，不能冒充新请求", async () => {
  const pending = { key: id(100), body: body() };
  storeFactScopeRecord({
    version: 1,
    scope: keyScope,
    pending,
    lastId: null,
    lastFactId: null,
  });
  fetchMock.mockResolvedValueOnce(
    response(
      { code: "PACKAGE_FACT_SCOPE_CHANGED", message: "范围已变化" },
      409,
    ),
  );
  render(<Workspace {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "恢复范围原请求" }));
  await screen.findByText(/范围已变化/);
  expect(loadFactScopeRecord(keyScope).pending).toEqual(pending);
});
it("切换准备记录后旧保存迟到，不改已保留的原请求", async () => {
  let resolve!: (r: Response) => void;
  fetchMock.mockResolvedValueOnce(response(scopeObservation(prepared, id(90))));
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((r) => {
      resolve = r;
    }),
  );
  const view = render(<Workspace {...props} />);
  await open();
  await observe();
  await fill();
  await userEvent.click(screen.getByRole("button", { name: "保存范围声明" }));
  const pending = loadFactScopeRecord(keyScope).pending!;
  view.rerender(
    <Workspace
      {...props}
      prepared={{
        ...prepared,
        manifest: { ...prepared.manifest, id: id(999) },
      }}
    />,
  );
  await act(async () => {
    resolve(
      response(
        await scopeReply(prepared, pending.body, scope.memberId, id(100)),
        201,
      ),
    );
  });
  expect(loadFactScopeRecord(keyScope).pending).toEqual(pending);
  expect(
    screen.queryByText("范围声明记录已读回校验；当前有效性需另行重读。"),
  ).not.toBeInTheDocument();
});
it("范围链头和选项主体矛盾时拒绝当前匹配观察", async () => {
  const head = await scopeReply(prepared, body(), scope.memberId, id(100));
  const observation = scopeObservation(prepared, id(90), head);
  observation.subject_choices[1].id = id(999);
  await expect(
    validateScopeObservation(observation, scope, id(6), prepared, id(90)),
  ).rejects.toThrow();
});
