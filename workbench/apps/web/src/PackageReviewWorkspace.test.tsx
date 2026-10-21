import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageReviewWorkspace";
import { dependencyPlanPage } from "../qa-previews/frozen-inputs/dependencyPlan";
import {
  packageReviewFixture,
  packageReviewPage,
} from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import {
  dependencyPlanPath,
  dependencyPlanScope,
} from "./dependencyPlanProtocol";
import { packageReviewPath } from "./packageReviewProtocol";
import { packageReviewStorageKey } from "./packageReviewRecovery";
import {
  packageReviewAlternateFixture,
  packageReviewOriginalFetch,
} from "../qa-previews/frozen-inputs/packageReviewComparison";

let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
const fetchMock = vi.fn();
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
let post: (options: RequestInit) => Promise<Response>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  fixture = await packageReviewFixture();
  post = async () => json(fixture.run, 202);
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    const path = url.replace(/^\/api\/v1/, "");
    if (path === packageReviewPath(fixture.props) && options.method === "POST")
      return post(options);
    if (path === `${packageReviewPath(fixture.props)}/${fixture.run.id}`)
      return json(fixture.completed);
    if (path === `${packageReviewPath(fixture.props)}?limit=10`)
      return json(packageReviewPage(fixture, [fixture.completed]));
    if (path === `${dependencyPlanPath(fixture.props)}?limit=10`)
      return json(dependencyPlanPage(fixture, [fixture.plan]));
    if (
      path ===
      `${dependencyPlanPath(fixture.props)}/${fixture.plan.manifest.id}`
    )
      return json(fixture.plan);
    throw new Error(`unexpected synthetic request ${path}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const writes = () =>
  fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
const saved = () =>
  JSON.parse(
    sessionStorage.getItem(
      packageReviewStorageKey(dependencyPlanScope(fixture.props)),
    )!,
  );
async function readPlan() {
  await userEvent.click(
    screen.getByText("逐条核对事实需求", { selector: "summary" }),
  );
  await userEvent.click(
    await screen.findByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "查看已保存计划" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看这份原计划" }),
  );
  return screen.findByRole("button", { name: "选择这份计划继续核查" });
}
async function chooseAndLaunch() {
  await userEvent.click(await readPlan());
  await userEvent.click(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  );
}
it("does not launch on mount or history read and explicitly launches the chosen original plan", async () => {
  render(<Workspace {...fixture.props} />);
  expect(fetchMock).not.toHaveBeenCalled();
  const adopt = await readPlan();
  expect(writes()).toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
  await userEvent.click(adopt);
  expect(writes()).toHaveLength(0);
  post = async (options) => {
    expect(saved().pending.body).toEqual(fixture.body);
    expect(saved().pending.key).toBe(
      new Headers(options.headers).get("Idempotency-Key"),
    );
    return json(fixture.run, 202);
  };
  await userEvent.click(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  );
  await screen.findByRole("region", { name: "整包范围核查结果" });
  expect(writes()).toHaveLength(1);
  expect(JSON.parse(String(writes()[0][1].body))).toEqual(fixture.body);
  expect(saved().pending).toBeNull();
  expect(saved().lastId).toBe(fixture.run.id);
  expect(screen.getByText(/整体覆盖仍为部分/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
});
it("recovers a lost acknowledgement with the original plan, body and key after refresh without auto POST", async () => {
  post = async () => {
    throw new TypeError("synthetic lost acknowledgement");
  };
  const view = render(<Workspace {...fixture.props} />);
  await chooseAndLaunch();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原核查请求" }),
    ).toBeEnabled(),
  );
  const original = writes()[0][1] as RequestInit;
  view.unmount();
  render(<Workspace {...fixture.props} />);
  expect(writes()).toHaveLength(1);
  expect(saved().pending.body).toEqual(fixture.body);
  post = async () => json(fixture.run, 202);
  await userEvent.click(screen.getByRole("button", { name: "恢复原核查请求" }));
  await screen.findByRole("region", { name: "整包范围核查结果" });
  expect(writes()).toHaveLength(2);
  expect(writes()[1][1].body).toBe(original.body);
  expect(new Headers(writes()[1][1].headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(saved().pending).toBeNull();
});
it.each(["mismatched-plan", "idempotency-conflict", "malformed-error"])(
  "retains the original request when recovery cannot be proved: %s",
  async (kind) => {
    post = async () =>
      kind === "malformed-error"
        ? json({ message: "unknown proxy rejection" }, 409)
        : kind === "mismatched-plan"
          ? json(
              { ...fixture.run, dependency_plan_digest: "0".repeat(64) },
              202,
            )
          : json(
              {
                code: "IDEMPOTENCY_CONFLICT",
                message: "合成原请求冲突",
              },
              409,
            );
    render(<Workspace {...fixture.props} />);
    await chooseAndLaunch();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "恢复原核查请求" }),
      ).toBeEnabled(),
    );
    expect(saved().pending.body).toEqual(fixture.body);
    expect(
      screen.queryByRole("region", { name: "本次整包范围核查" }),
    ).not.toBeInTheDocument();
  },
);
it("retains a complete large plan but explicitly blocks an execution above the method's 400-requirement bound", async () => {
  fixture = await packageReviewFixture(401);
  render(<Workspace {...fixture.props} />);
  await userEvent.click(await readPlan());
  expect(
    screen.getByText(/本轮核查最多 400 条要求；当前 401 条，尚未启动/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "已选用这份计划" }),
  ).toBeInTheDocument();
  expect(writes()).toHaveLength(0);
});
it("releases a definitely rejected recovery and requires explicit plan selection again", async () => {
  const storage = packageReviewStorageKey(dependencyPlanScope(fixture.props));
  sessionStorage.setItem(
    storage,
    JSON.stringify({
      version: 1,
      scope: dependencyPlanScope(fixture.props),
      pending: { key: id(151), body: fixture.body },
      lastId: null,
    }),
  );
  post = async () =>
    json(
      {
        code: "PROJECT_WORK_CLOSED",
        message: "当前项目已关闭，未受理这次核查",
      },
      409,
    );
  render(<Workspace {...fixture.props} />);
  await userEvent.click(screen.getByRole("button", { name: "恢复原核查请求" }));
  await screen.findByText("当前项目已关闭，未受理这次核查");
  expect(saved().pending).toBeNull();
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
  expect(writes()).toHaveLength(1);
});
it("treats semantic duplication as a rejected new request and opens the existing run under its original preparation", async () => {
  const original = fixture;
  fixture = await packageReviewAlternateFixture();
  const currentFetch = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    const historical = packageReviewOriginalFetch(
      original,
      url.replace(/^\/api\/v1/, ""),
    );
    return historical ? json(historical) : currentFetch(url, options);
  });
  post = async () =>
    json(
      {
        code: "PACKAGE_REVIEW_ALREADY_EXISTS",
        message: "合成相同内容已有核查",
        details: {
          existing_run: packageReviewPage(original, [original.completed])
            .items[0],
        },
      },
      409,
    );
  render(<Workspace {...fixture.props} />);
  await chooseAndLaunch();
  await screen.findByRole("button", { name: "查看已存在的原核查" });
  expect(saved().pending).toBeNull();
  expect(saved().lastId).toBeNull();
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "查看已存在的原核查" }),
  );
  await screen.findByRole("region", { name: "整包范围核查结果" });
  expect(saved().lastId).toBeNull();
  expect(writes()).toHaveLength(1);
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) =>
        options.method === "GET" &&
        String(url).endsWith(
          `${packageReviewPath(original.props)}/${original.run.id}`,
        ),
    ),
  ).toBe(true);
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
});
it("does not create an original-run navigation link from a cross-bid duplicate summary", async () => {
  const summary = packageReviewPage(fixture, [fixture.completed]).items[0];
  summary.scope = { ...summary.scope, bid_id: id(991) };
  post = async () =>
    json(
      {
        code: "PACKAGE_REVIEW_ALREADY_EXISTS",
        message: "合成重复但导航不符",
        details: { existing_run: summary },
      },
      409,
    );
  render(<Workspace {...fixture.props} />);
  await chooseAndLaunch();
  await screen.findByText("合成重复但导航不符");
  expect(saved().pending).toBeNull();
  expect(
    screen.queryByRole("button", { name: "查看已存在的原核查" }),
  ).not.toBeInTheDocument();
});
it("keeps an unmounted original request recoverable and ignores its late acknowledgement in a new prepared scope", async () => {
  let resolve!: (response: Response) => void;
  post = () =>
    new Promise<Response>((done) => {
      resolve = done;
    });
  const view = render(<Workspace {...fixture.props} />);
  await chooseAndLaunch();
  expect(saved().pending).toBeTruthy();
  const changed = {
    ...fixture.props,
    prepared: {
      ...fixture.props.prepared,
      digest: "9".repeat(64),
      manifest: { ...fixture.props.prepared.manifest, id: id(707) },
    },
  };
  view.rerender(<Workspace {...changed} />);
  await act(async () => {
    resolve(json(fixture.run, 202));
  });
  expect(
    screen.queryByRole("region", { name: "本次整包范围核查" }),
  ).not.toBeInTheDocument();
  expect(saved().pending.body).toEqual(fixture.body);
  expect(
    sessionStorage.getItem(
      packageReviewStorageKey(dependencyPlanScope(changed)),
    ),
  ).toBeNull();
});
it("reads history without adopting or launching its plan and exposes explicit rerun preparation", async () => {
  const onRequestRerun = vi.fn();
  render(<Workspace {...fixture.props} onRequestRerun={onRequestRerun} />);
  await userEvent.click(
    screen.getByText("此准备输入的核查历史与恢复", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取核查历史" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看这次核查" }),
  );
  await screen.findByRole("region", { name: "整包范围核查结果" });
  expect(writes()).toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "开始整包范围核查" }),
  ).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "准备复检" }));
  expect(onRequestRerun).toHaveBeenCalledTimes(1);
  expect(writes()).toHaveLength(0);
});
