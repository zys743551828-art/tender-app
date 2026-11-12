import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringPanel } from "./AuthoringPanel";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
import type { AuthoringPlanVersion, AuthoringTreeView } from "./contracts";
import { setAuth } from "./api";
afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAuth({
    member: {
      id: layoutScope.memberId,
      display_name: "合成目录编制验收",
      active: true,
    },
    csrf_token: "synthetic-not-a-credential",
    expires_at: "2099-01-01T00:00:00Z",
  });
  vi.spyOn(window, "scrollBy").mockImplementation(() => {});
  const createRange = document.createRange.bind(document);
  vi.spyOn(document, "createRange").mockImplementation(() => {
    const range = createRange();
    range.getClientRects = () => [] as unknown as DOMRectList;
    range.getBoundingClientRect = () => new DOMRect(0, 0, 1, 1);
    return range;
  });
  const previous = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("authoring-columns")
        ? {
            width: 1100,
            height: 800,
            left: 0,
            right: 1100,
            top: 200,
            bottom: 1000,
            x: 0,
            y: 200,
            toJSON: () => ({}),
          }
        : previous.call(this);
    },
  );
});
function response(data: unknown, etag: string, status = 200) {
  const result = new Response(JSON.stringify(data), {
    status,
    headers: { ETag: etag },
  });
  result.json = async () => structuredClone(data);
  return result;
}
async function editable() {
  await waitFor(
    () => {
      expect(
        screen.queryByText("正在核对保存快照及本稿的来源资格…"),
      ).not.toBeInTheDocument();
      expect(screen.getByLabelText("章节正文")).toHaveAttribute(
        "contenteditable",
        "true",
      );
    },
    { timeout: 5000 },
  );
}
async function setup(
  mode: "success" | "unknown" | "failure" | "head-failure" = "success",
  corrupt?:
    | "outer-draft"
    | "bid_id"
    | "draft_id"
    | "section_id"
    | "unsafe-revision"
    | "draft-revision"
    | "plan-revision"
    | "snapshot",
) {
  const fixture = authoringLayoutFixture();
  let plan: AuthoringPlanVersion | null = null;
  let planWrites = 0;
  let failHead = false;
  let failedHeads = 0;
  let receipt: unknown;
  const puts: { key: string | null; etag: string | null; body: unknown }[] = [];
  const saves: { etag: string | null; revision: number }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.href).pathname;
      const tag = `"draft:${fixture.state.draft.revision}"`;
      if (
        (init?.method ?? "GET") === "GET" &&
        path.endsWith(`/drafts/${layoutScope.draftId}`) &&
        failHead
      ) {
        failHead = false;
        failedHeads++;
        throw new TypeError("SYNTHETIC head unavailable");
      }
      if (init?.method === "PUT" && path.endsWith("/plan")) {
        planWrites++;
        puts.push({
          key: new Headers(init.headers).get("Idempotency-Key"),
          etag: new Headers(init.headers).get("If-Match"),
          body: JSON.parse(String(init.body)),
        });
        if (receipt) return response(receipt, '"draft:2"');
        if (mode === "failure")
          return response(
            {
              code: "INVALID_PLAN",
              message: "SYNTHETIC rejected plan",
              retryable: false,
            },
            tag,
            422,
          );
        const request = JSON.parse(String(init.body));
        expect(request.base_draft_revision).toBe(1);
        expect(new Headers(init.headers).get("If-Match")).toBe(tag);
        plan = {
          id: "20000000-0000-4000-8000-000000000091",
          bid_id: layoutScope.bidId,
          draft_id: layoutScope.draftId,
          section_id: layoutScope.sectionId,
          revision: 1,
          base_section_revision: 1,
          state: request.state,
          planned_pages: request.planned_pages,
          payload: request,
          digest: "c".repeat(64),
          created_by: layoutScope.memberId,
          created_at: "2026-01-01T00:00:00Z",
        };
        fixture.state.draft.revision = 2;
        fixture.state.draft.snapshot_id =
          "20000000-0000-4000-8000-000000000092";
        receipt = {
          draft_id: layoutScope.draftId,
          draft_revision: 2,
          snapshot_id: fixture.state.draft.snapshot_id,
          snapshot_digest: "b".repeat(64),
          plan,
        };
        failHead = mode === "head-failure";
        if (mode === "unknown")
          throw new TypeError("SYNTHETIC lost plan acknowledgement");
        if (corrupt) {
          const bad = structuredClone(receipt) as {
            draft_id: string;
            draft_revision: number;
            snapshot_id: string;
            plan: AuthoringPlanVersion;
          };
          if (corrupt === "outer-draft") bad.draft_id = "another-draft";
          else if (corrupt === "unsafe-revision")
            bad.draft_revision = Number.MAX_SAFE_INTEGER + 1;
          else if (corrupt === "draft-revision") bad.draft_revision = 0;
          else if (corrupt === "plan-revision") bad.plan.revision = 1.5;
          else if (corrupt === "snapshot") bad.snapshot_id = "";
          else bad.plan[corrupt] = "another-scope";
          return response(bad, '"draft:2"');
        }
        return response(receipt, '"draft:2"');
      }
      if ((init?.method ?? "GET") === "GET" && path.endsWith("/structure")) {
        const original = await fixture.fetcher(input, init);
        const tree = (await original.json()) as AuthoringTreeView;
        if (plan) {
          tree.nodes[0].plan = plan;
          tree.nodes[0].plan_version_id = plan.id;
        }
        return response(tree, tag);
      }
      if (
        init?.method === "PATCH" &&
        path.endsWith(`/drafts/${layoutScope.draftId}`)
      ) {
        const request = JSON.parse(String(init.body));
        const etag = new Headers(init.headers).get("If-Match");
        saves.push({ etag, revision: request.base_draft_revision });
        if (
          etag !== tag ||
          request.base_draft_revision !== fixture.state.draft.revision
        )
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC stale plan editor",
              retryable: false,
            },
            tag,
            412,
          );
      }
      return fixture.fetcher(input, init);
    }),
  );
  render(
    <AuthoringPanel
      {...layoutScope}
      projectTitle="SYNTHETIC plan editing"
      onOpenDraft={vi.fn()}
    />,
  );
  await editable();
  return {
    fixture,
    saves,
    puts,
    failedHeads: () => failedHeads,
    planWrites: () => planWrites,
  };
}
async function savePlan() {
  await userEvent.click(screen.getByRole("button", { name: "章节目录与计划" }));
  const directory = within(
    screen.getByRole("complementary", { name: "章节目录与编写计划" }),
  );
  await userEvent.click(directory.getByText("本章编写计划 · 施工组织与进度"));
  fireEvent.change(directory.getByLabelText("本章目标"), {
    target: { value: "SYNTHETIC manual plan" },
  });
  await userEvent.click(
    directory.getByRole("button", { name: "保存编写计划" }),
  );
  return directory;
}
async function saveTitle() {
  const writing = within(screen.getByRole("region", { name: "正文编写" }));
  fireEvent.change(writing.getByLabelText("章节名称"), {
    target: { value: "SYNTHETIC after plan" },
  });
  await userEvent.click(writing.getByRole("button", { name: "立即保存" }));
}
it.each(["success", "unknown", "failure", "head-failure"] as const)(
  "preserves the actual editor across plan %s and uses only acknowledged revisions",
  async (mode) => {
    const f = await setup(mode);
    const body = screen.getByLabelText("章节正文"),
      original = body.textContent;
    const directory = await savePlan();
    await waitFor(() => expect(f.planWrites()).toBe(1));
    if (mode === "unknown") {
      const retry = await directory.findByRole("button", {
        name: "恢复原计划保存结果",
      });
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(
        directory.getByRole("button", { name: "保存编写计划" }),
      ).toBeDisabled();
      expect(f.saves).toHaveLength(0);
      await userEvent.click(retry);
      await waitFor(() => expect(f.planWrites()).toBe(2));
      expect(f.puts[1]).toEqual(f.puts[0]);
      expect(f.puts[0].key).toBeTruthy();
    } else if (mode === "failure") {
      await directory.findByText("SYNTHETIC rejected plan");
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(
        directory.queryByText("计划已保存；页数仍为预算。"),
      ).not.toBeInTheDocument();
      expect(f.fixture.state.draft.revision).toBe(1);
    } else if (mode === "head-failure") {
      const retry = await screen.findByRole("button", {
        name: "核对并重新读取已保存正文",
      });
      expect(f.failedHeads()).toBe(1);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body).toHaveAttribute("contenteditable", "false");
      expect(body.textContent).toBe(original);
      await userEvent.click(retry);
      await editable();
      expect(f.planWrites()).toBe(1);
      expect(f.saves).toHaveLength(0);
    }
    await editable();
    expect(screen.getByLabelText("章节正文").textContent).toBe(original);
    await saveTitle();
    await waitFor(() => expect(f.saves).toHaveLength(1));
    const revision = mode === "failure" ? 1 : 2;
    expect(f.saves).toEqual([{ etag: `"draft:${revision}"`, revision }]);
    await waitFor(() => expect(f.fixture.state.appliedSaves).toBe(1));
    expect(f.planWrites()).toBe(mode === "unknown" ? 2 : 1);
  },
);

it.each([
  "outer-draft",
  "bid_id",
  "draft_id",
  "section_id",
  "unsafe-revision",
  "draft-revision",
  "plan-revision",
  "snapshot",
] as const)(
  "retains the exact request and editor for malformed plan acknowledgement %s",
  async (field) => {
    const f = await setup("success", field);
    const body = screen.getByLabelText("章节正文"),
      original = body.textContent;
    const directory = await savePlan();
    const retry = await directory.findByRole("button", {
      name: "恢复原计划保存结果",
    });
    expect(screen.getByLabelText("章节正文")).toBe(body);
    expect(body.textContent).toBe(original);
    expect(
      directory.queryByText("计划已保存；页数仍为预算。"),
    ).not.toBeInTheDocument();
    expect(f.saves).toHaveLength(0);
    const key = `tender:command-record:authoring-plan:${layoutScope.memberId}:${layoutScope.draftId}:${layoutScope.sectionId}`;
    const record = JSON.parse(sessionStorage.getItem(key)!);
    expect(record.key).toBe(f.puts[0].key);
    expect(record.body).toEqual(f.puts[0].body);
    expect(record.etag).toBe(f.puts[0].etag);
    await userEvent.click(retry);
    await editable();
    expect(f.puts).toHaveLength(2);
    expect(f.puts[1]).toEqual(f.puts[0]);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(screen.getByLabelText("章节正文").textContent).toBe(original);
    await saveTitle();
    await waitFor(() => expect(f.saves).toHaveLength(1));
    expect(f.saves).toEqual([{ etag: '"draft:2"', revision: 2 }]);
  },
);
