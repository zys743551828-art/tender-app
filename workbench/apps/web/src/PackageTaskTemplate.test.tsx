import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PackageTaskTemplate from "./PackageTaskTemplate";
import type { TaskKindPage, TemplateRequest, TemplateView } from "./contracts";
import {
  packageTaskCapability,
  packageTaskConfiguration,
} from "./packageTaskTemplateSelection";
import type { PackageTaskSelectionProps } from "./packageTaskTemplateSelection";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId } from "../qa-previews/frozen-inputs/factChange";
import { taskPackageFixture } from "./taskPackageFixtures.test-support";

const editor = vi.fn();
vi.mock("./TaskTemplateEditor", () => ({
  TaskTemplateEditor: (props: {
    initialConfiguration: TemplateRequest;
    onClose: () => void;
    onSaved: (item: TemplateView) => void;
  }) => {
    editor(props);
    return (
      <section aria-label="测试任务表单">
        <button onClick={props.onClose}>收起表单</button>
      </section>
    );
  },
}));
const fetchMock = vi.fn();
let selection: PackageTaskSelectionProps;
let kinds: TaskKindPage;
const json = (value: unknown, etag?: string, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  editor.mockClear();
  sessionStorage.clear();
  const fixture = await packageReviewFixture();
  selection = { ...fixture.props, plan: fixture.plan };
  kinds = {
    items: [
      {
        task_kind: "denial_check",
        name: "否决核对",
        purpose: "compliance",
        execution: "existing_review_control_plane",
        exact_package_manual: {
          available: true,
          reason: null,
          input_mode: "exact_package_review",
          method_digest: "a".repeat(64),
          trigger: "manual",
          overall_coverage: "partial",
          formal_scoring_eligible: false,
          submission_eligible: false,
          automatic_input_selection: false,
        },
      },
    ],
    default_trigger: "manual",
    saving_preset_creates_run: false,
  };
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/v1/task-kinds") return json(kinds);
    if (url === `/api/v1/bids/${selection.scope.bidId}`)
      return json(
        { id: selection.scope.bidId },
        `"bid:${selection.scope.bidId}:${"b".repeat(64)}"`,
      );
    throw new Error("Unexpected synthetic request: " + url);
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("does no automatic IO and opens a fixed exact package selection only after the explicit button", async () => {
  // ReviewWorkspace also passes its rerun callback through a props spread.
  render(
    <PackageTaskTemplate {...{ ...selection, onRequestRerun: vi.fn() }} />,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "保存为手动任务" }));
  await screen.findByRole("region", { name: "测试任务表单" });
  expect(fetchMock.mock.calls).toHaveLength(2);
  expect(
    fetchMock.mock.calls.every(([, options]) => options.method === "GET"),
  ).toBe(true);
  expect(editor.mock.lastCall![0].initialConfiguration).toEqual(
    await packageTaskConfiguration(selection, packageTaskCapability(kinds)),
  );
  expect(
    editor.mock.lastCall![0].initialConfiguration.source_selection.input,
  ).toEqual({
    package_id: selection.scope.packageId,
    revision_id: selection.scope.revisionId,
    inventory_id: selection.scope.inventoryId,
    frozen_input_id: selection.frozen.manifest.id,
    frozen_input_digest: selection.frozen.digest,
    execution_input_id: selection.prepared.manifest.id,
    execution_input_digest: selection.prepared.digest,
    dependency_plan_id: selection.plan.manifest.id,
    dependency_plan_digest: selection.plan.digest,
    method_digest: "a".repeat(64),
  });
});

it("keeps the opened plan and mounted editor when another plan is inspected or the form is collapsed", async () => {
  const view = render(<PackageTaskTemplate {...selection} />);
  await userEvent.click(screen.getByRole("button", { name: "保存为手动任务" }));
  await screen.findByRole("region", { name: "测试任务表单" });
  const original = editor.mock.lastCall![0].initialConfiguration;
  const other = structuredClone(selection);
  other.plan.manifest.id = changeId(987);
  other.plan.digest = "e".repeat(64);
  view.rerender(<PackageTaskTemplate {...other} />);
  expect(screen.getByText(/上方的新选择不会替换/)).toBeInTheDocument();
  expect(editor.mock.lastCall![0].initialConfiguration).toEqual(original);
  await userEvent.click(screen.getByRole("button", { name: "收起表单" }));
  expect(
    screen.queryByRole("region", { name: "测试任务表单" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "测试任务表单", hidden: true }),
  ).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "继续填写手动任务模板" }),
  );
  expect(editor.mock.lastCall![0].initialConfiguration).toEqual(original);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("allows saving a manual template while execution is unavailable and does not enqueue any work", async () => {
  kinds.items[0].exact_package_manual!.available = false;
  kinds.items[0].exact_package_manual!.reason =
    "PACKAGE_REVIEW_EXECUTOR_NOT_READY";
  render(<PackageTaskTemplate {...selection} />);
  await userEvent.click(screen.getByRole("button", { name: "保存为手动任务" }));
  await screen.findByRole("region", { name: "测试任务表单" });
  expect(screen.getByText(/仍可保存这份手动模板/)).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.every(([, options]) => options.method === "GET"),
  ).toBe(true);
});

it.each(["wrong-bid", "wrong-etag", "promoted-qualification", "bad-digest"])(
  "does not open a save form on invalid server/selection identity: %s",
  async (failure) => {
    if (failure === "promoted-qualification")
      Object.assign(kinds.items[0].exact_package_manual!, {
        formal_scoring_eligible: true,
      });
    if (failure === "bad-digest") selection.plan.digest = "c".repeat(64);
    if (failure === "wrong-bid" || failure === "wrong-etag")
      fetchMock.mockImplementation(async (url: string) =>
        url.endsWith("task-kinds")
          ? json(kinds)
          : json(
              {
                id:
                  failure === "wrong-bid"
                    ? changeId(999)
                    : selection.scope.bidId,
              },
              `"bid:${changeId(999)}:${"b".repeat(64)}"`,
            ),
      );
    render(<PackageTaskTemplate {...selection} />);
    await userEvent.click(
      screen.getByRole("button", { name: "保存为手动任务" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("正在核对所选输入和当前项目修订…"),
      ).not.toBeInTheDocument(),
    );
    expect(editor).not.toHaveBeenCalled();
    expect(
      fetchMock.mock.calls.every(([, options]) => options.method === "GET"),
    ).toBe(true);
  },
);

it("ignores late initialization after the exact selection workspace unmounts", async () => {
  const finishes: Array<(value: Response) => void> = [];
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finishes.push(resolve);
      }),
  );
  const view = render(<PackageTaskTemplate {...selection} />);
  await userEvent.click(screen.getByRole("button", { name: "保存为手动任务" }));
  view.unmount();
  await act(async () => {
    finishes[0](json(kinds));
    finishes[1](
      json(
        { id: selection.scope.bidId },
        `"bid:${selection.scope.bidId}:${"b".repeat(64)}"`,
      ),
    );
  });
  expect(editor).not.toHaveBeenCalled();
});

it("rejects a changed prepared input even if its external identifiers still match", async () => {
  selection.prepared.manifest.inventory_id = changeId(999);
  await expect(
    packageTaskConfiguration(selection, packageTaskCapability(kinds)),
  ).rejects.toThrow();
});

it("preserves actual PostgreSQL HTTP input digests without re-signing the synthetic fixture", async () => {
  const real = taskPackageFixture();
  const m = real.frozen.data.manifest;
  const configuration = await packageTaskConfiguration(
    {
      scope: {
        memberId: m.actor_id,
        bidId: m.bid_id,
        packageId: m.package_id,
        revisionId: m.revision_id,
        inventoryId: m.inventory_id,
      },
      frozen: real.frozen.data,
      prepared: real.prepared.data,
      plan: real.plan.data,
    },
    packageTaskCapability(real.kinds.data),
  );
  expect(configuration.source_selection).toEqual(
    real.created.data.configuration.source_selection,
  );
  expect(configuration.trigger).toEqual({
    mode: "manual",
    cron: null,
    timezone: "Asia/Shanghai",
  });
  expect(fetchMock).not.toHaveBeenCalled();
});
