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
import { PackageTechnicalScope } from "./PackageTechnicalScope";
import { PackageScopeGuardProvider } from "./PackageScopeGuardProvider";
import { usePackageScopeState } from "./packageScopeGuard";
import {
  technicalAckFor,
  technicalFixture,
} from "./packageTechnicalScopeFixtures.test-support";
import {
  readTechnicalRecovery,
  writeTechnicalRecovery,
} from "./packageTechnicalScopeRecovery";
import type { TechnicalPending } from "./packageTechnicalScopeProtocol";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));
const mocked = vi.mocked(api);
let f = technicalFixture();
beforeEach(() => {
  sessionStorage.clear();
  f = technicalFixture();
  mocked.mockReset();
  mocked.mockImplementation(async (path, options) => {
    if (path.includes("technical-scope-context"))
      return { data: f.context, etag: f.context.etag };
    if (path.endsWith("technical-scope-previews")) {
      expect(options?.body).toEqual(f.request);
      return { data: f.preview, etag: f.context.etag };
    }
    if (path.endsWith("/technical-scopes") && options?.method === "POST")
      return technicalAckFor({
        ...f.pending,
        key: options.key!,
        body: options.body as TechnicalPending["body"],
        etag: options.etag!,
      });
    throw new Error(`Unexpected synthetic API path: ${path}`);
  });
});
function GuardProbe() {
  const state = usePackageScopeState();
  return <output aria-label="navigation state">{JSON.stringify(state)}</output>;
}
function mount() {
  return render(
    <PackageScopeGuardProvider>
      <GuardProbe />
      <PackageTechnicalScope
        bidId={f.scope.bidId}
        memberId={f.scope.memberId}
        packageView={f.context.target}
        inventory={f.context.inventory}
      />
    </PackageScopeGuardProvider>,
  );
}
async function fill() {
  fireEvent.click(screen.getByRole("button", { name: "读取技术范围依据" }));
  const parts = await screen.findByRole("group", {
    name: "1. 选择要纳入的完整页段",
  });
  expect(
    screen.getByRole("button", { name: "预览技术范围与缺口" }),
  ).toBeDisabled();
  for (const checkbox of within(parts).getAllByRole("checkbox"))
    fireEvent.click(checkbox);
  for (let index = 0; index < f.request.rule_scopes.length; index++) {
    const rule = f.request.rule_scopes[index],
      n = index + 1;
    fireEvent.change(screen.getByLabelText(`条款 ${n} 的范围判断`), {
      target: { value: rule.selection },
    });
    if (rule.selection === "include") {
      const group = screen.getByRole("group", {
        name: `条款 ${n} 关联的已选页段`,
      });
      for (const checkbox of within(group).getAllByRole("checkbox"))
        fireEvent.click(checkbox);
    }
    fireEvent.change(screen.getByLabelText(`条款 ${n} 的选择理由`), {
      target: { value: rule.reason },
    });
  }
  fireEvent.change(screen.getByLabelText("本次范围说明"), {
    target: { value: f.request.reason },
  });
}

it("requires explicit choices, complete preview and confirmation before saving the verified input", async () => {
  mount();
  expect(mocked).not.toHaveBeenCalled();
  await fill();
  expect(screen.getByLabelText("navigation state")).toHaveTextContent(
    '"dirty":true',
  );
  fireEvent.click(screen.getByRole("button", { name: "预览技术范围与缺口" }));
  await screen.findByRole("heading", { name: "待保存的技术范围" });
  expect(
    screen.getByRole("button", { name: "确认保存技术范围" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText("我已核对本次选择与缺口，确认保存为范围记录。"),
  );
  fireEvent.click(screen.getByRole("button", { name: "确认保存技术范围" }));
  await screen.findByText("技术范围已保存，原件字节已在登记时核验。");
  expect(readTechnicalRecovery(f.scope)).toBeNull();
  await waitFor(() =>
    expect(screen.getByLabelText("navigation state")).toHaveTextContent(
      '{"busy":false,"pending":false,"dirty":false}',
    ),
  );
  expect(
    mocked.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(2);
});

it("editing after a preview invalidates confirmation and removing a part removes its rule associations", async () => {
  mount();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "预览技术范围与缺口" }));
  await screen.findByRole("heading", { name: "待保存的技术范围" });
  fireEvent.click(
    screen.getByLabelText("我已核对本次选择与缺口，确认保存为范围记录。"),
  );
  fireEvent.change(screen.getByLabelText("本次范围说明"), {
    target: { value: "重新说明范围" },
  });
  expect(
    screen.queryByRole("button", { name: "确认保存技术范围" }),
  ).not.toBeInTheDocument();
  const parts = screen.getByRole("group", { name: "1. 选择要纳入的完整页段" });
  for (const checkbox of within(parts).getAllByRole("checkbox"))
    fireEvent.click(checkbox);
  expect(
    screen.getByRole("button", { name: "预览技术范围与缺口" }),
  ).toBeDisabled();
  expect(
    mocked.mock.calls.filter(([path]) => path.endsWith("/technical-scopes")),
  ).toHaveLength(0);
});

it("can replay an uncertain original save before fetching new context", async () => {
  writeTechnicalRecovery(f.scope, f.pending);
  mount();
  expect(
    screen.getByRole("button", { name: "读取技术范围依据" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("navigation state")).toHaveTextContent(
    '"pending":true',
  );
  fireEvent.click(screen.getByRole("button", { name: "恢复原技术范围请求" }));
  await screen.findByText("技术范围已保存，原件字节已在登记时核验。");
  // The recovered ACK mounts the status reader; it must not refetch input context
  // or replace the original write identity before recovering the saved scope.
  expect(mocked).toHaveBeenCalledTimes(2);
  expect(mocked.mock.calls[1][0]).toMatch(
    /\/technical-scopes\/[^/]+\/prediction-pipeline$/,
  );
  expect(mocked.mock.calls[1][1]?.method).toBeUndefined();
  expect(
    mocked.mock.calls.some(([path]) =>
      path.includes("technical-scope-context"),
    ),
  ).toBe(false);
  expect(mocked.mock.calls[0][1]).toEqual({
    method: "POST",
    body: f.pending.body,
    etag: f.pending.etag,
    key: f.pending.key,
  });
});

it("a wrong context tag never unlocks an editor and a late context cannot reach a different mounted scope", async () => {
  mocked.mockResolvedValueOnce({ data: f.context, etag: '"wrong-context"' });
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "读取技术范围依据" }));
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  expect(screen.queryByLabelText("本次范围说明")).not.toBeInTheDocument();
  let resolve!: (value: { data: typeof f.context; etag: string }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "读取技术范围依据" }));
  view.unmount();
  await act(async () => {
    resolve({ data: f.context, etag: f.context.etag });
  });
  mount();
  expect(screen.queryByLabelText("本次范围说明")).not.toBeInTheDocument();
});
