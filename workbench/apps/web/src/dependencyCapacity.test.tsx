import { StrictMode } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import InputWorkspace from "./PackageInputDependencyWorkspace";
import PlanWorkspace from "./PackageDependencyPlanWorkspace";
import type { DependencyPlanCandidate } from "./PackageDependencyPlanWorkspace";
import type {
  CheckPackageInputDependencies,
  PackageDependencyPlanView,
  SavePackageDependencyPlan,
} from "./contracts";
import { inputDependencyFixture } from "../qa-previews/frozen-inputs/inputDependencies";
import {
  dependencyPlanAssessment,
  dependencyPlanReply,
} from "../qa-previews/frozen-inputs/dependencyPlan";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  validDependencyRequest,
  validateDependencyAssessment,
} from "./inputDependencyProtocol";
import { dependencyPlanScope } from "./dependencyPlanProtocol";
import {
  dependencyPlanStorageKey,
  loadDependencyPlanRecord,
  storeDependencyPlanRecord,
} from "./dependencyPlanRecovery";

type Fixture = Awaited<ReturnType<typeof inputDependencyFixture>>;
const MAX_BYTES = 4 * 1024 * 1024;
const fetchMock = vi.fn(),
  recheck = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const bytes = (body: unknown) =>
  new TextEncoder().encode(JSON.stringify(body)).byteLength;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  recheck.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function fixture(count: number, evidenceCount = 1): Promise<Fixture> {
  const f = await inputDependencyFixture();
  const template = f.inventory.manifest.requirements[0];
  f.inventory.manifest.requirements = await Promise.all(
    Array.from({ length: count }, async (_, n) => {
      const row = structuredClone(template);
      row.rule_id =
        row.rule_snapshot.id =
        row.requirement.requirement_id =
          id(1000 + n);
      row.rule_snapshot.evidence_ids = Array.from(
        { length: evidenceCount },
        (_, i) => id(50000 + i),
      );
      row.rule_digest = await frozenManifestDigest(row.rule_snapshot);
      row.requirement_digest = await frozenManifestDigest(row.requirement);
      return row;
    }),
  );
  f.inventory.digest = await frozenManifestDigest(f.inventory.manifest);
  return f;
}
function request(f: Fixture): CheckPackageInputDependencies {
  return {
    execution_input_digest: f.props.prepared.digest,
    purpose: "prebid_compliance",
    fact_ids: [],
    dependencies: f.inventory.manifest.requirements.map((row) => ({
      requirement_id: row.rule_id,
      requirement_digest: row.requirement_digest,
      state: "not_needed",
      fact_ids: [],
      evidence_ids: row.rule_snapshot.evidence_ids as string[],
      reason: "逐条核对原页后明确本次不依赖额外事实",
    })),
  };
}
const savedRecord = (f: Fixture) =>
  JSON.parse(
    sessionStorage.getItem(
      dependencyPlanStorageKey(dependencyPlanScope(f.props)),
    )!,
  );
async function prepareSave() {
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  fireEvent.change(screen.getByLabelText("计划保存理由"), {
    target: { value: "明确保存本次跨页核对" },
  });
  await userEvent.click(
    screen.getByLabelText(
      "我确认保存以上核对结果与本轮明确选择，缺口仍按原状态保留",
    ),
  );
}
function showPlan(f: Fixture, candidate: DependencyPlanCandidate | null) {
  return render(
    <StrictMode>
      <PlanWorkspace {...f.props} candidate={candidate} onRecheck={recheck} />
    </StrictMode>,
  );
}

it("accepts one 10,000-declaration snapshot while preserving duplicate and 500-fact guards", async () => {
  const f = await fixture(1),
    body = request(f);
  body.dependencies = Array.from({ length: 10000 }, (_, n) => ({
    ...body.dependencies[0],
    requirement_id: id(n + 1000),
  }));
  expect(validDependencyRequest(body, f.props)).toBe(true);
  body.dependencies.push({
    ...body.dependencies[0],
    requirement_id: id(50000),
  });
  expect(validDependencyRequest(body, f.props)).toBe(false);
  body.dependencies = body.dependencies.slice(0, 2);
  body.dependencies[1] = body.dependencies[0];
  expect(validDependencyRequest(body, f.props)).toBe(false);
  body.dependencies = body.dependencies.slice(0, 1);
  body.fact_ids = Array.from({ length: 501 }, (_, n) => id(n));
  expect(validDependencyRequest(body, f.props)).toBe(false);
});

it("checks, saves and recovers all 501 declarations as the same plan and pages its original receipt", async () => {
  const f = await fixture(501),
    body = request(f);
  const assessment = await dependencyPlanAssessment(f, body);
  await expect(
    validateDependencyAssessment(assessment, f.props, f.inventory, body),
  ).resolves.toBeUndefined();
  let committed!: PackageDependencyPlanView;
  fetchMock.mockImplementationOnce(async (_url, options: RequestInit) => {
    committed = await dependencyPlanReply(f, JSON.parse(String(options.body)));
    throw new TypeError("synthetic lost ACK");
  });
  const first = showPlan(f, { request: body, assessment });
  await prepareSave();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByRole("button", { name: "恢复原计划保存回执" });
  await screen.findByText("NETWORK_ERROR");
  expect(savedRecord(f).pending.body.dependencies).toHaveLength(501);
  const original = fetchMock.mock.calls[0][1] as RequestInit;
  first.unmount();
  showPlan(f, null);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fetchMock.mockResolvedValueOnce(json(committed, 201));
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原计划保存回执" }),
  );
  const history = await screen.findByRole("region", { name: "原计划保存回执" });
  const restored = fetchMock.mock.calls[1][1] as RequestInit;
  expect(restored.body).toBe(original.body);
  expect(new Headers(restored.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(savedRecord(f).pending).toBeNull();
  await userEvent.click(
    within(history).getByText("查看原计划的标注与身份", {
      selector: "summary",
    }),
  );
  expect(within(history).getAllByRole("listitem")).toHaveLength(20);
  await userEvent.selectOptions(
    within(history).getByLabelText("原计划标注页码"),
    "25",
  );
  expect(within(history).getByText("原要求 501")).toBeInTheDocument();
  expect(within(history).queryByText("原要求 1")).not.toBeInTheDocument();
  expect(within(history).getAllByRole("listitem")).toHaveLength(1);
  expect(committed.manifest.inventory_complete).toBe(false);
});

it("retains edits from distant pages and saves/replays one assessment without treating omitted rows as declared", async () => {
  const f = await fixture(501);
  let committed!: PackageDependencyPlanView;
  let checkCount = 0;
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (url.endsWith(`/requirement-inventories/${f.props.scope.inventoryId}`))
      return json(f.inventory);
    if (url.endsWith("/dependency-check")) {
      if (checkCount++ === 0)
        return json(
          {
            code: "PACKAGE_DEPENDENCY_BODY_TOO_LARGE",
            message: "合成核对超限拒绝",
            retryable: false,
            details: {},
          },
          413,
        );
      return json(
        await dependencyPlanAssessment(f, JSON.parse(String(options?.body))),
      );
    }
    if (url.endsWith("/dependency-plans")) {
      committed = await dependencyPlanReply(
        f,
        JSON.parse(String(options?.body)),
      );
      throw new TypeError("synthetic lost ACK");
    }
    throw new Error("unexpected synthetic route");
  });
  const first = render(
    <StrictMode>
      <InputWorkspace {...f.props} />
    </StrictMode>,
  );
  await userEvent.click(
    screen.getByText("逐条核对事实需求", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取原要求清单" }));
  await screen.findByRole("button", { name: "核对第 1 条要求" });
  for (const [page, number] of [
    [0, 1],
    [1, 21],
    [25, 501],
  ]) {
    await userEvent.selectOptions(
      screen.getByLabelText("原要求页码"),
      String(page),
    );
    expect(
      screen.getAllByRole("button", { name: /^核对第 \d+ 条要求$/ }),
    ).toHaveLength(page === 25 ? 1 : 20);
    await userEvent.click(
      screen.getByRole("button", { name: `核对第 ${number} 条要求` }),
    );
    expect(screen.getByLabelText("原要求页码")).toBeDisabled();
    await userEvent.selectOptions(
      screen.getByLabelText("本次事实需求"),
      "not_needed",
    );
    fireEvent.change(screen.getByLabelText("依赖核对理由"), {
      target: { value: `已核对第 ${number} 条原页` },
    });
    await userEvent.click(
      screen.getByLabelText("我已核对以上要求原页，并确认本次事实依赖标注"),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "应用到本轮核对（不保存）" }),
    );
  }
  await userEvent.selectOptions(screen.getByLabelText("原要求页码"), "0");
  await userEvent.click(
    screen.getByRole("button", { name: "核对第 1 条要求" }),
  );
  expect(screen.getByLabelText("依赖核对理由")).toHaveValue(
    "已核对第 1 条原页",
  );
  await userEvent.click(screen.getByRole("button", { name: "放弃此条编辑" }));
  await userEvent.click(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  );
  await screen.findByText("合成核对超限拒绝");
  await userEvent.selectOptions(screen.getByLabelText("原要求页码"), "25");
  expect(screen.getByText("本轮已标注：本次不依赖事实")).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "计算本轮依赖缺口（不保存）" }),
  );
  await screen.findByText(/本次只核对依赖标注与原事实选择/);
  const checkedBody = JSON.parse(
    fetchMock.mock.calls.find(([url]) => url.endsWith("/dependency-check"))![1]
      .body,
  );
  expect(
    checkedBody.dependencies.map(
      (row: { requirement_id: string }) => row.requirement_id,
    ),
  ).toEqual([id(1000), id(1020), id(1500)]);
  await prepareSave();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByRole("button", { name: "恢复原计划保存回执" });
  await screen.findByText("NETWORK_ERROR");
  const original = fetchMock.mock.calls.at(-1)![1] as RequestInit;
  first.unmount();
  showPlan(f, null);
  fetchMock.mockResolvedValueOnce(json(committed, 201));
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原计划保存回执" }),
  );
  await screen.findByRole("region", { name: "原计划保存回执" });
  expect((fetchMock.mock.calls.at(-1)![1] as RequestInit).body).toBe(
    original.body,
  );
  expect(committed.manifest.assessment.manifest.dependency_review_status).toBe(
    "incomplete",
  );
  expect(committed.manifest.assessment.manifest.requirements).toHaveLength(501);
});

it("preserves a 501-row candidate when browser recovery storage is full and does not POST without recoverability", async () => {
  const f = await fixture(501),
    body = request(f),
    assessment = await dependencyPlanAssessment(f, body);
  showPlan(f, { request: body, assessment });
  await prepareSave();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("合成恢复存储容量不足", "QuotaExceededError");
  });
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByText(/本机恢复存储空间不足，本次请求尚未发送/);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.length).toBe(0);
  expect(screen.getByLabelText("计划保存理由")).toHaveValue(
    "明确保存本次跨页核对",
  );
  expect(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  ).toBeEnabled();
  expect(recheck).not.toHaveBeenCalled();
});

async function nearLimit(count = 501) {
  const f = await fixture(count, 80),
    body = request(f);
  for (const row of body.dependencies) row.reason = "据";
  let remaining = MAX_BYTES - 80 - bytes(body);
  for (const row of body.dependencies) {
    const add = Math.min(1899, Math.floor(remaining / 3));
    row.reason += "据".repeat(add);
    remaining -= add * 3;
  }
  body.dependencies.at(-1)!.reason += "x".repeat(remaining);
  expect(body.dependencies.every((row) => row.reason.length <= 2000)).toBe(
    true,
  );
  expect(bytes(body)).toBe(MAX_BYTES - 80);
  return { f, body, assessment: await dependencyPlanAssessment(f, body) };
}

it("budgets the final UTF-8 Save body, keeps the candidate, and never writes a pending request or POST when too large", async () => {
  const { f, body, assessment } = await nearLimit();
  expect(validDependencyRequest(body, f.props)).toBe(true);
  expect(JSON.stringify(body).length).toBeLessThan(MAX_BYTES);
  showPlan(f, { request: body, assessment });
  await prepareSave();
  expect(
    bytes({
      ...body,
      assessment_digest: assessment.digest,
      reason: "明确保存本次跨页核对",
    }),
  ).toBeGreaterThan(MAX_BYTES);
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByText(/超过 4 MiB/);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.length).toBe(0);
  expect(screen.getByLabelText("计划保存理由")).toHaveValue(
    "明确保存本次跨页核对",
  );
  expect(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  ).toBeEnabled();
  expect(recheck).not.toHaveBeenCalled();
});

it("recovers an accepted historical 4–5 MiB request without applying the new-write budget or changing its key", async () => {
  const { f, body, assessment } = await nearLimit(500);
  const pending = {
    key: id(900),
    body: {
      ...body,
      assessment_digest: assessment.digest,
      reason: "原请求保存理由",
    } satisfies SavePackageDependencyPlan,
  };
  expect(bytes(pending.body)).toBeGreaterThan(MAX_BYTES);
  expect(bytes(pending.body)).toBeLessThan(5 * 1024 * 1024);
  storeDependencyPlanRecord({
    version: 1,
    scope: dependencyPlanScope(f.props),
    pending,
    lastId: null,
  });
  expect(loadDependencyPlanRecord(f.props).pending).toEqual(pending);
  const committed = await dependencyPlanReply(f, pending.body);
  fetchMock.mockResolvedValueOnce(json(committed, 201));
  showPlan(f, null);
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原计划保存回执" }),
  );
  await screen.findByRole("region", { name: "原计划保存回执" });
  const posted = fetchMock.mock.calls[0][1] as RequestInit;
  expect(posted.body).toBe(JSON.stringify(pending.body));
  expect(new Headers(posted.headers).get("Idempotency-Key")).toBe(pending.key);
  expect(savedRecord(f).pending).toBeNull();
  expect(screen.queryByText(/本机恢复记录无法核验/)).not.toBeInTheDocument();
});

it("retains an original request above the transport limit without transmitting or calling it corrupt", async () => {
  const f = await fixture(500, 140),
    body = request(f);
  for (const row of body.dependencies) row.reason = "据".repeat(2000);
  const pending = {
    key: id(900),
    body: {
      ...body,
      assessment_digest: "a".repeat(64),
      reason: "原请求保存理由",
    } satisfies SavePackageDependencyPlan,
  };
  expect(bytes(pending.body)).toBeGreaterThan(5 * 1024 * 1024);
  storeDependencyPlanRecord({
    version: 1,
    scope: dependencyPlanScope(f.props),
    pending,
    lastId: null,
  });
  showPlan(f, null);
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原计划保存回执" }),
  );
  await screen.findByText(/原保存请求超过 5 MiB/);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(savedRecord(f).pending).toEqual(pending);
  expect(screen.queryByText(/本机恢复记录无法核验/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看已保存计划" })).toBeEnabled();
});

it("honors a server 413 for a new save without claiming a receipt, losing the candidate or leaving a false uncertain POST", async () => {
  const f = await fixture(1),
    body = request(f),
    assessment = await dependencyPlanAssessment(f, body);
  fetchMock.mockResolvedValueOnce(
    json(
      {
        code: "PACKAGE_DEPENDENCY_BODY_TOO_LARGE",
        message: "服务器拒绝本次过大请求",
        retryable: false,
        details: {},
      },
      413,
    ),
  );
  showPlan(f, { request: body, assessment });
  await prepareSave();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByText("服务器拒绝本次过大请求");
  await waitFor(() => expect(savedRecord(f).pending).toBeNull());
  expect(
    screen.queryByRole("region", { name: "原计划保存回执" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("计划保存理由")).toHaveValue(
    "明确保存本次跨页核对",
  );
  expect(recheck).not.toHaveBeenCalled();
});
