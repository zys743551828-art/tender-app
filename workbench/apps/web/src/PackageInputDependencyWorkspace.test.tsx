import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageInputDependencyWorkspace";
import {
  inputDependencyFixture,
  dependencyReply,
} from "../qa-previews/frozen-inputs/inputDependencies";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  validateDependencyAssessment,
  validateDependencyInventory,
} from "./inputDependencyProtocol";
import type { CheckPackageInputDependencies } from "./contracts";
let fixture: Awaited<ReturnType<typeof inputDependencyFixture>>;
const fetchMock = vi.fn();
const json = (v: unknown) =>
  new Response(JSON.stringify(v), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  fixture = await inputDependencyFixture();
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/dependency-check"))
      return json(
        await dependencyReply(fixture, JSON.parse(String(options?.body))),
      );
    if (url.includes("/facts?limit=")) return json(fixture.directory);
    if (url.endsWith(`/requirement-inventories/${id(5)}`))
      return json(fixture.inventory);
    throw new Error("unexpected synthetic route");
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function show() {
  return render(
    <StrictMode>
      <Workspace {...fixture.props} />
    </StrictMode>,
  );
}
async function load() {
  await userEvent.click(
    screen.getByText("逐条核对事实需求", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取原要求清单" }));
  await screen.findByRole("button", { name: "核对第 1 条要求" });
}
async function edit() {
  await userEvent.click(
    screen.getByRole("button", { name: "核对第 1 条要求" }),
  );
}
async function apply() {
  await userEvent.type(
    screen.getByLabelText("依赖核对理由"),
    "逐条核对原规则后明确本轮依赖",
  );
  await userEvent.click(
    screen.getByLabelText("我已核对以上要求原页，并确认本次事实依赖标注"),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "应用到本轮核对（不保存）" }),
  );
}
async function calculate() {
  await userEvent.click(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  );
  await screen.findByText(/本次只核对依赖标注与原事实选择/);
}
it("does not issue automatic requests, writes or recovery records on mount", async () => {
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  await load();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(sessionStorage.length).toBe(0);
});
it("empty selection and no annotations remain unknown", async () => {
  show();
  await load();
  await calculate();
  const [, options] = fetchMock.mock.calls.find(([url]) =>
    url.endsWith("/dependency-check"),
  )!;
  expect(JSON.parse(options.body)).toEqual({
    execution_input_digest: fixture.props.prepared.digest,
    purpose: "prebid_compliance",
    fact_ids: [],
    dependencies: [],
  });
  expect(new Headers(options.headers).get("Idempotency-Key")).toEqual(
    expect.any(String),
  );
  expect(sessionStorage.length).toBe(0);
});
it("required facts without a value produce a known gap, not automatic pool selection", async () => {
  show();
  await load();
  await edit();
  await userEvent.selectOptions(
    screen.getByLabelText("本次事实需求"),
    "required",
  );
  await apply();
  await calculate();
  expect(screen.getAllByText("缺少所需事实或尚未选用").length).toBeGreaterThan(
    0,
  );
  const body = JSON.parse(
    fetchMock.mock.calls.find(([url]) => url.endsWith("/dependency-check"))![1]
      .body,
  );
  expect(body.fact_ids).toEqual([]);
  expect(body.dependencies[0].fact_ids).toEqual([]);
});
it("a requirement dependency does not silently select that fact for actual consumption", async () => {
  show();
  await load();
  await edit();
  await userEvent.selectOptions(
    screen.getByLabelText("本次事实需求"),
    "required",
  );
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  await userEvent.click(
    await screen.findByRole("button", {
      name: "合同工期 · 180 天 原主体：本工程；原范围：标段一",
    }),
  );
  await apply();
  await calculate();
  const body = JSON.parse(
    fetchMock.mock.calls.find(([url]) => url.endsWith("/dependency-check"))![1]
      .body,
  );
  expect(body.dependencies[0].fact_ids).toEqual([id(51)]);
  expect(body.fact_ids).toEqual([]);
  expect(screen.getAllByText("缺少所需事实或尚未选用").length).toBeGreaterThan(
    0,
  );
});
it("explicit consumption remains unvalidated and omitted requirements stay unknown", async () => {
  show();
  await load();
  await edit();
  await userEvent.selectOptions(
    screen.getByLabelText("本次事实需求"),
    "required",
  );
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  await userEvent.click(
    await screen.findByRole("button", {
      name: "合同工期 · 180 天 原主体：本工程；原范围：标段一",
    }),
  );
  await userEvent.click(screen.getByLabelText("本轮实际选用：合同工期 · 180"));
  await apply();
  await calculate();
  expect(screen.getByText("已选事实，当前资格仍须核验")).toBeInTheDocument();
  expect(screen.getAllByText("事实需求尚未核定").length).toBeGreaterThan(0);
});
it("editing invalidates old assessment and cannot calculate an unapplied draft", async () => {
  show();
  await load();
  await calculate();
  await edit();
  expect(screen.queryByText(/本次只核对依赖标注与原事实选择/)).toBeNull();
  expect(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  ).toBeDisabled();
});
it("does not show a late assessment after switching prepared input", async () => {
  const view = show();
  await load();
  let done!: (r: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        done = resolve;
      }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  );
  view.rerender(
    <StrictMode>
      <Workspace
        {...fixture.props}
        prepared={{ ...fixture.props.prepared, digest: "f".repeat(64) }}
      />
    </StrictMode>,
  );
  const body: CheckPackageInputDependencies = {
    execution_input_digest: fixture.props.prepared.digest,
    purpose: "prebid_compliance",
    fact_ids: [],
    dependencies: [],
  };
  await act(async () => done(json(await dependencyReply(fixture, body))));
  expect(screen.queryByText(/本次只核对依赖标注与原事实选择/)).toBeNull();
  expect(
    screen.getByRole("button", { name: "读取原要求清单" }),
  ).toBeInTheDocument();
});
it("a corrupt inventory digest never enables assessment or silently changes revision", async () => {
  fixture.inventory.digest = "a".repeat(64);
  show();
  await userEvent.click(
    screen.getByText("逐条核对事实需求", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取原要求清单" }));
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  ).toBeDisabled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it.each(["qualification", "binding", "result"])(
  "rejects a resealed %s mismatch",
  async (kind) => {
    const body: CheckPackageInputDependencies = {
      execution_input_digest: fixture.props.prepared.digest,
      purpose: "prebid_compliance",
      fact_ids: [],
      dependencies: [],
    };
    const value = await dependencyReply(fixture, body);
    if (kind === "qualification")
      Object.assign(value.manifest, { facts_qualified: true });
    if (kind === "binding")
      value.manifest.prepared.execution_input_id = id(999);
    if (kind === "result")
      value.manifest.required_facts_assessment = "not_used";
    value.digest = await frozenManifestDigest(value.manifest);
    await expect(
      validateDependencyAssessment(
        value,
        fixture.props,
        fixture.inventory,
        body,
      ),
    ).rejects.toThrow();
  },
);
it("a changed original rule identity fails even when inventory digest is recomputed", async () => {
  fixture.inventory.manifest.requirements[0].rule_snapshot.id = id(999);
  fixture.inventory.digest = await frozenManifestDigest(
    fixture.inventory.manifest,
  );
  await expect(
    validateDependencyInventory(fixture.inventory, fixture.props),
  ).rejects.toThrow();
});
it("a malformed assessment is rejected in the real component", async () => {
  show();
  await load();
  fetchMock.mockImplementationOnce(async () => {
    const body: CheckPackageInputDependencies = {
      execution_input_digest: fixture.props.prepared.digest,
      purpose: "prebid_compliance",
      fact_ids: [],
      dependencies: [],
    };
    const value = await dependencyReply(fixture, body);
    value.digest = "a".repeat(64);
    return json(value);
  });
  await userEvent.click(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("依赖评估的输入身份"),
  );
  expect(screen.queryByText(/本次只核对依赖标注与原事实选择/)).toBeNull();
});
