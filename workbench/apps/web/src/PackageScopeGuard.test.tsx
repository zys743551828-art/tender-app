import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackageScopeGuardProvider } from "./PackageScopeGuardProvider";
import {
  usePackageScopeGuard,
  usePackageScopeState,
} from "./packageScopeGuard";
import Cancel from "./PackageReviewReportCancel";
import {
  packageReportOperation,
  packageReviewReportFixture,
} from "../qa-previews/frozen-inputs/packageReviewReport";
import { loadPackageReviewReportCancel } from "./packageReviewReportRecovery";
import { navResponse } from "./packageNavigationFixtures.test-support";

function ScopeBoundary({ children }: { children: React.ReactNode }) {
  const state = usePackageScopeState();
  const [left, setLeft] = useState(false),
    [blocked, setBlocked] = useState(false);
  return (
    <>
      <output aria-label="作用域状态">{JSON.stringify(state)}</output>
      <button
        onClick={() => {
          if (state.busy || state.dirty || state.pending) setBlocked(true);
          else setLeft(true);
        }}
      >
        离开当前包
      </button>
      {blocked && !left && <p>原操作未核对，保留当前工作面</p>}
      {left ? <p>已离开工作面</p> : children}
    </>
  );
}
function Reporter({
  scope,
  pending = false,
  dirty = false,
}: {
  scope: string;
  pending?: boolean;
  dirty?: boolean;
}) {
  usePackageScopeGuard(scope, { pending, dirty });
  return null;
}
beforeEach(() => {
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("keeps independently registered guards when another scope is changed or unmounted", async () => {
  const ui = render(
    <PackageScopeGuardProvider>
      <ScopeBoundary>
        <Reporter scope="first" pending />
        <Reporter scope="second" dirty />
      </ScopeBoundary>
    </PackageScopeGuardProvider>,
  );
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent(
    '"pending":true',
  );
  ui.rerender(
    <PackageScopeGuardProvider>
      <ScopeBoundary>
        <Reporter scope="changed-first" />
        <Reporter scope="second" dirty />
      </ScopeBoundary>
    </PackageScopeGuardProvider>,
  );
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent('"dirty":true');
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent(
    '"pending":false',
  );
  await userEvent.click(screen.getByRole("button", { name: "离开当前包" }));
  expect(screen.getByText("原操作未核对，保留当前工作面")).toBeVisible();
  ui.rerender(
    <PackageScopeGuardProvider>
      <ScopeBoundary>
        <Reporter scope="changed-first" />
      </ScopeBoundary>
    </PackageScopeGuardProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "离开当前包" }));
  expect(screen.getByText("已离开工作面")).toBeVisible();
});

it("blocks departure for a real deep report-cancel command, restores it on reopen, and accepts only its original receipt", async () => {
  const f = await packageReviewReportFixture(),
    user = userEvent.setup(),
    reload = vi.fn().mockResolvedValue(undefined);
  let mode: "lost" | "wrong" | "accepted" = "lost";
  const calls: { path: string; options: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options: RequestInit) => {
      calls.push({ path, options });
      if (options.method !== "POST")
        return navResponse(
          { ...packageReportOperation(f.report), state: "queued" },
          200,
          { ETag: '"exact-report-status"' },
        );
      if (mode === "lost") throw new TypeError("synthetic lost deep ACK");
      return navResponse({
        ...packageReportOperation(f.report),
        state: "cancel_requested",
        ...(mode === "wrong"
          ? { input_digest: f.f.completed.input_digest }
          : {}),
      });
    }),
  );
  const show = () =>
    render(
      <PackageScopeGuardProvider>
        <ScopeBoundary>
          <Cancel
            memberId={f.f.props.scope.memberId}
            run={f.f.completed}
            report={f.report}
            onReload={reload}
          />
        </ScopeBoundary>
      </PackageScopeGuardProvider>,
    );
  const first = show();
  await user.click(screen.getByRole("button", { name: "取消此份报告生成" }));
  await user.type(
    screen.getByLabelText("取消报告生成的理由"),
    "合成报告取消理由",
  );
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent('"dirty":true');
  await user.click(screen.getByRole("button", { name: "确认取消此份报告" }));
  await screen.findByText("NETWORK_ERROR");
  const original = calls[1].options;
  await user.click(screen.getByRole("button", { name: "离开当前包" }));
  expect(screen.getByText("原操作未核对，保留当前工作面")).toBeVisible();
  expect(
    loadPackageReviewReportCancel(
      f.f.props.scope.memberId,
      f.f.completed,
      f.report,
    ),
  ).not.toBeNull();
  first.unmount();
  mode = "wrong";
  show();
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent(
    '"pending":true',
  );
  await user.click(screen.getByRole("button", { name: "恢复原报告取消请求" }));
  expect(await screen.findByText(/取消回执与此份报告任务不符/)).toBeVisible();
  expect(screen.getByLabelText("作用域状态")).toHaveTextContent(
    '"pending":true',
  );
  mode = "accepted";
  await user.click(screen.getByRole("button", { name: "恢复原报告取消请求" }));
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(calls).toHaveLength(4);
  for (const { options } of calls.slice(2)) {
    expect(options.body).toBe(original.body);
    expect(new Headers(options.headers).get("Idempotency-Key")).toBe(
      new Headers(original.headers).get("Idempotency-Key"),
    );
    expect(new Headers(options.headers).get("If-Match")).toBe(
      new Headers(original.headers).get("If-Match"),
    );
  }
  await user.click(screen.getByRole("button", { name: "离开当前包" }));
  expect(screen.getByText("已离开工作面")).toBeVisible();
});
