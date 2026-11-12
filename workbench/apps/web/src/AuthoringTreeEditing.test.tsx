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
import type { AuthoringStructurePreview, AuthoringTreeView } from "./contracts";
import { setAuth } from "./api";
import { authoringStorageKey } from "./editorStorage";
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
  mode:
    | "confirm"
    | "reject"
    | "conflict"
    | "head-failure"
    | "recovery" = "confirm",
) {
  const fixture = authoringLayoutFixture();
  const [a, b] = fixture.state.sections.map((section) => section.id);
  let inside = false;
  let resolveCount = 0;
  let previewCount = 0;
  let failHead = false;
  let failedHeads = 0;
  const storageKey = authoringStorageKey(
    layoutScope.memberId,
    layoutScope.bidId,
    `${layoutScope.draftId}:${a}`,
  );
  const stored = JSON.stringify({
    sectionId: a,
    value: {
      ...fixture.state.sections[0].content,
      attrs: {
        ...fixture.state.sections[0].content.attrs,
        title: "SYNTHETIC recovery",
      },
    },
    draftRevision: 1,
    sectionRevision: 1,
    schemaDigest: fixture.state.sections[0].schema_digest,
    etag: '"draft:1"',
    pending: null,
  });
  if (mode === "recovery") sessionStorage.setItem(storageKey, stored);
  let held: AuthoringStructurePreview | null = null;
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
      if ((init?.method ?? "GET") === "GET" && path.endsWith("/structure")) {
        const original = await fixture.fetcher(input, init);
        const tree = (await original.json()) as AuthoringTreeView;
        if (inside)
          tree.nodes.find((node) => node.section_id === b)!.parent_id = a;
        return response(tree, tag);
      }
      if (init?.method === "POST" && path.endsWith("/structure/preview")) {
        previewCount++;
        expect(new Headers(init.headers).get("If-Match")).toBe(tag);
        expect(JSON.parse(String(init.body)).base_draft_revision).toBe(
          fixture.state.draft.revision,
        );
        const original = await fixture.fetcher(
          `/api/v1/bids/${layoutScope.bidId}/drafts/${layoutScope.draftId}/structure`,
        );
        const tree = (await original.json()) as AuthoringTreeView;
        const after = structuredClone(tree.nodes);
        after.find((node) => node.section_id === b)!.parent_id = a;
        after.find((node) => node.section_id === b)!.ordinal = 0;
        held = {
          action_id: "synthetic-move",
          base_draft_revision: fixture.state.draft.revision,
          created_ids: {},
          plan_suggestions: {},
          before: tree.nodes,
          after,
          before_sections: Object.fromEntries(
            fixture.state.sections.map((section) => [
              section.id,
              section.content,
            ]),
          ),
          after_sections: Object.fromEntries(
            fixture.state.sections.map((section) => [
              section.id,
              section.content,
            ]),
          ),
          directory_template_version_id: tree.directory_template_version_id,
          style_template_version_id: tree.style_template_version_id,
          deletion_impact: [],
          format_report: null,
          expires_in_seconds: 300,
        };
        return response(held, tag, 201);
      }
      if (init?.method === "POST" && path.endsWith("/resolve")) {
        resolveCount++;
        const decision = JSON.parse(String(init.body)).decision;
        if (decision === "reject")
          return response(
            { action_id: "synthetic-move", state: "rejected" },
            tag,
          );
        if (mode === "conflict")
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC resolve conflict",
              retryable: false,
            },
            tag,
            412,
          );
        expect(decision).toBe("confirm");
        expect(new Headers(init.headers).get("If-Match")).toBe(tag);
        expect(held).not.toBeNull();
        inside = true;
        failHead = mode === "head-failure";
        fixture.state.draft.revision++;
        fixture.state.draft.snapshot_id =
          "20000000-0000-4000-8000-000000000092";
        return response(
          {
            action_id: "synthetic-move",
            state: "applied",
            draft_id: layoutScope.draftId,
            draft_revision: fixture.state.draft.revision,
            snapshot_id: fixture.state.draft.snapshot_id,
            snapshot_digest: "b".repeat(64),
          },
          `"draft:${fixture.state.draft.revision}"`,
        );
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
              message: "合成草稿基准冲突",
              retryable: false,
              details: null,
              request_id: "synthetic",
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
      projectTitle="合成目录编制"
      onOpenDraft={vi.fn()}
    />,
  );
  if (mode === "recovery")
    await screen.findByRole("button", { name: "恢复本地内容并继续保存" });
  else await editable();
  return {
    fixture,
    a,
    b,
    saves,
    storageKey,
    stored,
    counts: () => ({ resolveCount, previewCount, failedHeads }),
  };
}
const pasteText = "SYNTHETIC pending body preserved";
function pasteBody() {
  const body = screen.getByLabelText("章节正文");
  body.focus();
  fireEvent.paste(body, {
    clipboardData: {
      getData: (type: string) => (type === "text/plain" ? pasteText : ""),
      files: [],
      items: [],
      types: ["text/plain"],
    },
  });
  expect(body.textContent).toContain(pasteText);
  return body;
}
async function preview(a: string) {
  await userEvent.click(screen.getByRole("button", { name: "章节目录与计划" }));
  const directory = within(
    screen.getByRole("complementary", { name: "章节目录与编写计划" }),
  );
  await userEvent.click(
    directory.getByRole("button", { name: "选择移动章节：质量保障措施" }),
  );
  await userEvent.selectOptions(directory.getByLabelText("目标章节"), a);
  await userEvent.selectOptions(directory.getByLabelText("移动位置"), "inside");
  await userEvent.click(
    directory.getByRole("button", { name: "预览所选章节移动" }),
  );
  return directory;
}
async function saveTitle() {
  const writing = within(screen.getByRole("region", { name: "正文编写" }));
  fireEvent.change(writing.getByLabelText("章节名称"), {
    target: { value: "目录移动后继续编写" },
  });
  await userEvent.click(writing.getByRole("button", { name: "立即保存" }));
}
it.each(["confirm", "reject", "conflict", "head-failure"] as const)(
  "preserves actual pending editor body across structure %s and saves against the correct head",
  async (mode) => {
    const f = await setup(mode);
    const body = pasteBody();
    const directory = await preview(f.a);
    const confirm = await directory.findByRole("button", {
      name: "应用这次变更",
    });
    expect(f.saves).toEqual([{ etag: '"draft:1"', revision: 1 }]);
    expect(f.fixture.state.draft.revision).toBe(2);
    expect(JSON.stringify(f.fixture.state.sections[0].content)).toContain(
      pasteText,
    );
    expect(f.counts().previewCount).toBe(1);
    await userEvent.click(
      mode === "reject"
        ? directory.getByRole("button", { name: "放弃这次变更" })
        : confirm,
    );
    await waitFor(() => expect(f.counts().resolveCount).toBe(1));
    if (mode === "head-failure") {
      const retry = await screen.findByRole("button", {
        name: "核对并重新读取已保存正文",
      });
      expect(f.counts().failedHeads).toBe(1);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body).toHaveAttribute("contenteditable", "false");
      expect(body.textContent).toContain(pasteText);
      const savesBefore = f.saves.length;
      await userEvent.click(retry);
      await editable();
      expect(f.saves).toHaveLength(savesBefore);
      expect(f.counts().resolveCount).toBe(1);
    } else if (mode === "conflict") {
      await directory.findByText(/SYNTHETIC resolve conflict/);
      expect(directory.getByText("变更尚未应用")).toBeInTheDocument();
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toContain(pasteText);
      expect(f.saves).toHaveLength(1);
      return;
    } else {
      await waitFor(() =>
        expect(directory.queryByText("变更尚未应用")).not.toBeInTheDocument(),
      );
      await editable();
      if (mode === "reject")
        expect(screen.getByLabelText("章节正文")).toBe(body);
    }
    expect(screen.getByLabelText("章节正文").textContent).toContain(pasteText);
    await saveTitle();
    await waitFor(() => expect(f.fixture.state.appliedSaves).toBe(2));
    const base = mode === "reject" ? 2 : 3;
    expect(f.saves).toEqual([
      { etag: '"draft:1"', revision: 1 },
      { etag: `"draft:${base}"`, revision: base },
    ]);
    expect(JSON.stringify(f.fixture.state.sections[0].content)).toContain(
      pasteText,
    );
    expect(f.counts().resolveCount).toBe(1);
  },
);
it("blocks directory preview while local recovery remains undecided without altering stored bytes", async () => {
  const f = await setup("recovery");
  await preview(f.a);
  await screen.findByText(
    "发现尚未处理的本地内容。请先选择恢复，或明确使用服务器稿，再生成版本。",
  );
  await screen.findByRole("button", { name: "恢复本地内容并继续保存" });
  expect(f.counts().previewCount).toBe(0);
  expect(f.counts().resolveCount).toBe(0);
  expect(f.saves).toHaveLength(0);
  expect(sessionStorage.getItem(f.storageKey)).toBe(f.stored);
});
