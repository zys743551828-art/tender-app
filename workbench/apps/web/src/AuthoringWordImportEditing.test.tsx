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
import type {
  AuthoringTreeView,
  AuthoringWordImportResult,
  SectionView,
} from "./contracts";
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
import {
  importCandidate,
  importCapabilities,
  importOriginal,
  importResolution,
} from "./authoringWordImportFixtures.test-support";
type Mode =
  | "success"
  | "reject"
  | "conflict"
  | "invalid"
  | "unknown"
  | "head-failure"
  | "already"
  | "candidate-failure";
async function setup(mode: Mode = "success") {
  const fixture = authoringLayoutFixture();
  let candidate = importCandidate();
  candidate.bid_id = layoutScope.bidId;
  candidate.draft_id = layoutScope.draftId;
  candidate.created_by = layoutScope.memberId;
  candidate.base_draft_revision = 1;
  candidate.base_draft_etag = '"draft:1"';
  candidate.base_snapshot_id = fixture.state.draft.snapshot_id;
  candidate.existing_sections = fixture.state.draft.sections.map((s) => ({
    section_id: s.id,
    parent_id: null,
    ordinal: s.ordinal,
    title: s.title,
  }));
  candidate.sections[0].ordinal = 2;
  candidate.preparation.actor_id = layoutScope.memberId;
  let receipt: AuthoringWordImportResult | null = null;
  const saves: { etag: string | null; revision: number }[] = [];
  const resolves: RequestInit[] = [];
  let failHead = false,
    failedHeads = 0,
    failedCandidates = 0;
  const base = `/api/v1/bids/${layoutScope.bidId}/drafts/${layoutScope.draftId}/word-imports`;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.href).pathname,
        tag = `"draft:${fixture.state.draft.revision}"`;
      if (
        (init?.method ?? "GET") === "GET" &&
        path.endsWith(`/drafts/${layoutScope.draftId}`) &&
        failHead
      ) {
        failHead = false;
        failedHeads++;
        throw new TypeError("SYNTHETIC head failed");
      }
      if (path.endsWith("/authoring/word-import-capabilities"))
        return response(importCapabilities, tag);
      if (path.endsWith("/word-originals"))
        return response(
          {
            items: [{ ...importOriginal, bid_id: layoutScope.bidId }],
            has_more: false,
            next_after: null,
          },
          tag,
        );
      if (path === base && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        candidate.reason = body.reason;
        candidate.preparation = {
          ...candidate.preparation,
          request: body,
          actor_id: layoutScope.memberId,
          idempotency_key: new Headers(init.headers).get("Idempotency-Key")!,
          if_match: new Headers(init.headers).get("If-Match"),
        };
        return response(candidate, tag, 201);
      }
      if (path === `${base}/${candidate.candidate_id}/resolve`) {
        resolves.push(init!);
        if (receipt) return response(receipt, tag);
        if (mode === "conflict")
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC append conflict",
              retryable: false,
            },
            tag,
            412,
          );
        receipt = importResolution(candidate, init!);
        receipt.bid_id = layoutScope.bidId;
        receipt.draft_id = layoutScope.draftId;
        receipt.command.actor_id = layoutScope.memberId;
        if (receipt.decision === "append") {
          receipt.draft_revision = 2;
          fixture.state.draft.revision = 2;
          fixture.state.draft.snapshot_id = receipt.snapshot_id!;
          for (const c of candidate.sections) {
            const section = {
              ...structuredClone(fixture.state.sections[0]),
              id: c.section_id,
              revision: 1,
              content: structuredClone(c.content),
            } as SectionView;
            fixture.state.sections.push(section);
            fixture.state.draft.sections.push({
              id: c.section_id,
              title: c.title,
              ordinal: c.ordinal,
              revision: 1,
              rule_ids: [],
              save_state: "saved",
            });
          }
        }
        candidate = {
          ...candidate,
          state: receipt.state,
          can_apply: false,
          resolution: receipt,
        };
        failHead = mode === "head-failure";
        if (mode === "unknown")
          throw new TypeError("SYNTHETIC lost append ACK");
        if (mode === "already" || mode === "candidate-failure")
          return response(
            {
              code: "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED",
              message: "SYNTHETIC already resolved",
              retryable: false,
            },
            tag,
            409,
          );
        if (mode === "invalid")
          return response(
            { ...receipt, candidate_digest: "0".repeat(64) },
            tag,
          );
        return response(receipt, `"draft:${fixture.state.draft.revision}"`);
      }
      if (path === `${base}/${candidate.candidate_id}`) {
        if (mode === "candidate-failure") {
          failedCandidates++;
          throw new TypeError("SYNTHETIC candidate read failed");
        }
        return response(candidate, tag);
      }
      if (path.endsWith("/structure")) {
        const r = await fixture.fetcher(input, init);
        const tree = (await r.json()) as AuthoringTreeView;
        if (receipt?.decision === "append")
          for (const c of candidate.sections)
            tree.nodes.find((n) => n.section_id === c.section_id)!.parent_id =
              c.parent_id;
        return response(tree, tag);
      }
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)),
          etag = new Headers(init.headers).get("If-Match");
        saves.push({ etag, revision: body.base_draft_revision });
        if (
          etag !== tag ||
          body.base_draft_revision !== fixture.state.draft.revision
        )
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC stale Word import editor",
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
      projectTitle="SYNTHETIC Word append editing"
      onOpenDraft={vi.fn()}
    />,
  );
  await editable();
  return {
    fixture,
    saves,
    resolves,
    counts: () => ({ failedHeads, failedCandidates }),
  };
}
async function candidateUI() {
  await userEvent.click(
    screen.getByRole("button", { name: "选择已保存的Word原件" }),
  );
  await userEvent.selectOptions(
    await screen.findByRole("combobox", { name: "选择本项目的确切Word版本" }),
    importOriginal.id,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "创建候选的理由" }), {
    target: { value: "核对本次合成原件后追加" },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  await screen.findByRole("heading", { name: importOriginal.original_name });
  await userEvent.click(screen.getByRole("checkbox", { name: /^确认损失：/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "本次处理理由" }), {
    target: { value: "已核对合成内容及损失，明确追加" },
  });
}
it.each([
  "success",
  "reject",
  "conflict",
  "invalid",
  "unknown",
  "head-failure",
  "already",
  "candidate-failure",
] as const)(
  "preserves the current editor across Word append %s",
  async (mode) => {
    const f = await setup(mode),
      body = screen.getByLabelText("章节正文"),
      original = body.textContent;
    await candidateUI();
    await userEvent.click(
      screen.getByRole("button", {
        name: mode === "reject" ? "拒绝此候选并保留历史" : "明确追加这些新章节",
      }),
    );
    await waitFor(() => expect(f.resolves).toHaveLength(1));
    if (mode === "unknown" || mode === "invalid") {
      const retry = await screen.findByRole("button", {
        name: "恢复原导入请求结果",
      });
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(screen.queryByText(/已追加 2 个章节/)).not.toBeInTheDocument();
      expect(f.saves).toHaveLength(0);
      await userEvent.click(retry);
      await waitFor(() => expect(f.resolves).toHaveLength(2));
      expect(f.resolves[1].body).toBe(f.resolves[0].body);
      for (const header of ["Idempotency-Key", "If-Match"])
        expect(new Headers(f.resolves[1].headers).get(header)).toBe(
          new Headers(f.resolves[0].headers).get(header),
        );
    } else if (mode === "head-failure") {
      const retry = await screen.findByRole("button", {
        name: "核对并重新读取已保存正文",
      });
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body).toHaveAttribute("contenteditable", "false");
      expect(body.textContent).toBe(original);
      expect(f.counts().failedHeads).toBe(1);
      await userEvent.click(retry);
      await editable();
      expect(f.resolves).toHaveLength(1);
      expect(f.saves).toHaveLength(0);
    } else if (mode === "conflict") {
      await screen.findByText("SYNTHETIC append conflict");
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(f.fixture.state.draft.revision).toBe(1);
    } else if (mode === "candidate-failure") {
      await waitFor(() => expect(f.counts().failedCandidates).toBe(1));
      await screen.findByText(/暂时无法连接服务/);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(f.saves).toHaveLength(0);
      expect(screen.queryByText(/已追加 2 个章节/)).not.toBeInTheDocument();
      return;
    } else if (mode === "reject") {
      await screen.findByText(/此候选已明确拒绝，草稿未改变/);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(f.fixture.state.draft.revision).toBe(1);
    }
    if (!["reject", "conflict"].includes(mode))
      await screen.findByText(/已追加 2 个章节，生成草稿修订 2/);
    await editable();
    expect(screen.getByLabelText("章节正文").textContent).toBe(original);
    if (!["reject", "conflict"].includes(mode)) {
      await userEvent.click(
        screen.getByRole("button", { name: "章节目录与计划" }),
      );
      const directory = within(
        screen.getByRole("complementary", { name: "章节目录与编写计划" }),
      );
      expect(
        await directory.findByRole("button", { name: /^章\s+施工组织\s/ }),
      ).toBeInTheDocument();
    }
    const writing = within(screen.getByRole("region", { name: "正文编写" }));
    expect(writing.getByLabelText("章节名称")).toHaveValue("施工组织与进度");
    fireEvent.change(writing.getByLabelText("章节名称"), {
      target: { value: "SYNTHETIC continued original chapter" },
    });
    await userEvent.click(writing.getByRole("button", { name: "立即保存" }));
    await waitFor(() => expect(f.saves).toHaveLength(1));
    const revision = ["reject", "conflict"].includes(mode) ? 1 : 2;
    expect(f.saves).toEqual([{ etag: `"draft:${revision}"`, revision }]);
    await waitFor(() => expect(f.fixture.state.appliedSaves).toBe(1));
  },
);
