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
import type { SectionView, AuthoringGenerationBatchReceipt } from "./contracts";
import { setAuth } from "./api";
afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAuth({
    member: {
      id: generationScope.memberId,
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
  generationFixture,
  generationHead,
  generationScope,
  generationCapabilities,
  generationReceipt,
  generationId,
} from "./authoringGenerationFixtures.test-support";
import { storeGenerationRecovery } from "./authoringGenerationRecovery";
import type { PendingGeneration } from "./authoringGenerationRecovery";
type Mode =
  | "success"
  | "head-failure"
  | "unknown"
  | "invalid"
  | "reject"
  | "conflict";
async function setup(current: number, mode: Mode = "success") {
  const f = authoringLayoutFixture(),
    g = await generationFixture();
  Object.assign(f.state.draft, structuredClone(generationHead.data));
  f.state.sections.splice(
    0,
    f.state.sections.length,
    ...g.candidates.map(
      (c, i) =>
        ({
          id: c.section_id,
          draft_id: generationScope.draftId,
          revision: generationHead.data.sections[i].revision,
          schema_digest: "b".repeat(64),
          writing_plan_id: null,
          content: structuredClone(c.before),
        }) as SectionView,
    ),
  );
  const c = structuredClone(f.state.sections[1]);
  c.id = generationId(12);
  c.revision = 1;
  c.content.attrs.title = "未选商务章节";
  c.content.attrs.ordinal = 2;
  f.state.sections.push(c);
  storeGenerationRecovery({
    version: 1,
    scope: generationScope,
    pending: null,
    lastBatchId: g.batch.batch_id,
  });
  let cached: AuthoringGenerationBatchReceipt | null = null;
  let failHead = false,
    failedHeads = 0;
  const commands: RequestInit[] = [];
  const writes: {
    path: string;
    etag: string | null;
    body: Record<string, unknown>;
  }[] = [];
  const base = `/api/v1/bids/${generationScope.bidId}/drafts/${generationScope.draftId}/generation-batches`;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.href).pathname,
        tag = `"draft-${f.state.draft.revision}"`;
      if (
        (init?.method ?? "GET") === "GET" &&
        path.endsWith(`/drafts/${generationScope.draftId}`) &&
        failHead
      ) {
        failHead = false;
        failedHeads++;
        throw new TypeError("SYNTHETIC head read failed");
      }
      if (path.endsWith("/authoring/generation-batch-capabilities"))
        return response(generationCapabilities, tag);
      if (path === base)
        return response(
          {
            bid_id: generationScope.bidId,
            draft_id: generationScope.draftId,
            items: [g.batch],
            has_more: false,
            next_cursor: null,
          },
          tag,
        );
      if (path === `${base}/${g.batch.batch_id}`)
        return response(g.batch, g.batch.etag);
      const candidate = g.candidates.find(
        (c) => path === `${base}/${g.batch.batch_id}/candidates/${c.action_id}`,
      );
      if (candidate) return response(candidate, candidate.etag);
      if (init?.method === "POST") {
        expect(path).toBe(`${base}/${g.batch.batch_id}/resolve`);
        const headers = new Headers(init.headers),
          body = JSON.parse(String(init.body));
        writes.push({ path, etag: headers.get("If-Match"), body });
        commands.push(init);
        if (cached) return response(cached, tag);
        if (mode === "conflict")
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC generation conflict",
              retryable: false,
            },
            tag,
            412,
          );
        const pending: PendingGeneration = {
          kind: "resolve",
          batchId: g.batch.batch_id,
          baseDraftRevision: 7,
          key: headers.get("Idempotency-Key")!,
          etag: headers.get("If-Match")!,
          body,
        };
        const receipt = await generationReceipt(g.batch, pending);
        g.batch.state = receipt.batch_state;
        g.batch.resolution = receipt;
        if (receipt.kind === "applied") {
          f.state.draft.revision = receipt.draft_revision!;
          f.state.draft.snapshot_id = receipt.snapshot_id!;
          for (const id of receipt.applied_section_ids) {
            const s = f.state.sections.find((s) => s.id === id)!,
              candidate = g.candidates.find((c) => c.section_id === id)!;
            s.content = structuredClone(
              candidate.after,
            ) as SectionView["content"];
            s.revision++;
            const summary = f.state.draft.sections.find((s) => s.id === id)!;
            summary.revision = s.revision;
            candidate.state = "executed";
          }
        }
        cached = receipt;
        failHead = mode === "head-failure";
        if (mode === "unknown") throw new TypeError("SYNTHETIC lost apply ACK");
        if (mode === "invalid")
          return response({ ...receipt, snapshot_id: null }, tag);
        return response(receipt, `"draft-${f.state.draft.revision}"`);
      }
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)),
          etag = new Headers(init.headers).get("If-Match");
        writes.push({ path, etag, body });
        if (etag !== tag || body.base_draft_revision !== f.state.draft.revision)
          return response(
            {
              code: "PRECONDITION_FAILED",
              message: "SYNTHETIC stale generation editor",
              retryable: false,
            },
            tag,
            412,
          );
      }
      const translated = path
        .replace(generationScope.bidId, layoutScope.bidId)
        .replace(generationScope.draftId, layoutScope.draftId);
      const r = await f.fetcher(translated, init);
      const value = await r.json();
      return response(value, tag, r.status);
    }),
  );
  sessionStorage.setItem(
    `tender:authoring:${generationScope.memberId}:${generationScope.bidId}:${generationScope.draftId}:selected-section`,
    generationId(current),
  );
  render(
    <AuthoringPanel
      {...generationScope}
      projectTitle="SYNTHETIC existing ready batch"
      onOpenDraft={vi.fn()}
    />,
  );
  await editable();
  return { f, g, writes, commands, failedHeads: () => failedHeads };
}
async function reviewA() {
  await userEvent.click(
    await screen.findByRole("button", { name: "核对施工组织的完整前后稿" }),
  );
  const checkbox = await screen.findByRole("checkbox", {
    name: "已核对完整前后稿，选择应用施工组织",
  });
  await waitFor(() => expect(checkbox).toBeEnabled());
  await userEvent.click(checkbox);
  fireEvent.change(screen.getByLabelText("本次应用或关闭理由"), {
    target: { value: "已核对合成候选和未选章节" },
  });
}
it.each([10, 11])(
  "adopts only A while refreshing selected chapter %s",
  async (current) => {
    const { f, writes } = await setup(current);
    const writing = within(screen.getByRole("region", { name: "正文编写" })),
      original = screen.getByLabelText("章节正文").textContent;
    expect(writing.getByLabelText("章节名称")).toHaveValue(
      current === 10 ? "施工组织" : "质量保障",
    );
    expect(screen.getByLabelText("章节正文")).toHaveTextContent(
      current === 10 ? "施工组织原有目标" : "质量保障原有目标",
    );
    if (current === 10)
      expect(
        writing.getByRole("columnheader", { name: "合并表头" }),
      ).toHaveAttribute("colspan", "2");
    await reviewA();
    await userEvent.click(
      screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
    );
    await waitFor(() => expect(f.state.draft.revision).toBe(8));
    await editable();
    if (current === 10)
      await waitFor(() =>
        expect(screen.getByLabelText("章节正文")).toHaveTextContent(
          "施工组织候选目标",
        ),
      );
    else expect(screen.getByLabelText("章节正文").textContent).toBe(original);
    expect(writing.getByLabelText("章节名称")).toHaveValue(
      current === 10 ? "施工组织" : "质量保障",
    );
    await continueSaving(writes, current, 8, 3);
    if (current === 10)
      expect(
        writing.getByRole("columnheader", { name: "合并表头" }),
      ).toHaveAttribute("colspan", "2");
  },
);
async function continueSaving(
  writes: {
    path: string;
    etag: string | null;
    body: Record<string, unknown>;
  }[],
  current: number,
  revision: number,
  sectionRevision: number,
) {
  const writing = within(screen.getByRole("region", { name: "正文编写" }));
  fireEvent.change(writing.getByLabelText("章节名称"), {
    target: { value: "SYNTHETIC continued chapter" },
  });
  await userEvent.click(writing.getByRole("button", { name: "立即保存" }));
  await waitFor(() =>
    expect(
      writes.filter((w) =>
        w.path.endsWith(`/drafts/${generationScope.draftId}`),
      ),
    ).toHaveLength(1),
  );
  const save = writes.at(-1)!;
  expect(save.etag).toBe(`"draft-${revision}"`);
  expect(save.body.base_draft_revision).toBe(revision);
  const change = (
    save.body.changes as { section_id: string; base_section_revision: number }[]
  )[0];
  expect(change.section_id).toBe(generationId(current));
  expect(change.base_section_revision).toBe(sectionRevision);
}
it.each(["head-failure", "unknown", "invalid", "reject", "conflict"] as const)(
  "protects the actual current editor during generation %s",
  async (mode) => {
    const { f, writes, commands, failedHeads } = await setup(10, mode),
      body = screen.getByLabelText("章节正文"),
      original = body.textContent;
    await reviewA();
    await userEvent.click(
      screen.getByRole("button", {
        name:
          mode === "reject"
            ? "关闭本批并请求取消未完成任务"
            : "一次应用已核对的 1 章并结束本批",
      }),
    );
    if (mode === "unknown" || mode === "invalid") {
      const retry = await screen.findByRole("button", {
        name: "恢复原批次请求结果",
      });
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(commands).toHaveLength(1);
      await userEvent.click(retry);
      await waitFor(() => expect(commands).toHaveLength(2));
      expect(commands[1].body).toBe(commands[0].body);
      for (const h of ["If-Match", "Idempotency-Key"])
        expect(new Headers(commands[1].headers).get(h)).toBe(
          new Headers(commands[0].headers).get(h),
        );
    } else if (mode === "head-failure") {
      const retry = await screen.findByRole("button", {
        name: "核对并重新读取已保存正文",
      });
      expect(failedHeads()).toBe(1);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body).toHaveAttribute("contenteditable", "false");
      expect(body.textContent).toBe(original);
      await userEvent.click(retry);
      await editable();
      expect(commands).toHaveLength(1);
      expect(writes).toHaveLength(1);
    } else if (mode === "conflict")
      await screen.findByText("SYNTHETIC generation conflict");
    else await screen.findByText(/批次已关闭；运行中的任务已请求取消/);
    await editable();
    if (mode === "reject" || mode === "conflict") {
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(f.state.draft.revision).toBe(7);
      await continueSaving(writes, 10, 7, 2);
    } else {
      await waitFor(() =>
        expect(screen.getByLabelText("章节正文")).toHaveTextContent(
          "施工组织候选目标",
        ),
      );
      await continueSaving(writes, 10, 8, 3);
    }
  },
);
