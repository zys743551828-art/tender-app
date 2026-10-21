// Explicit local HTTP fixtures for read-only previews and existing action controls.
// No model/provider, business database, or real document acceptance is represented.
import type {
  AssistantAction,
  AssistantSourcePage,
  AssistantSourceRef,
  AuthoringDocument,
} from "./contracts";

const id = (n: number) =>
  `30000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const assistantReviewScope = {
  memberId: id(1),
  bidId: id(2),
  actionId: id(3),
  sectionId: id(4),
};
export const assistantReviewReference: AssistantSourceRef = {
  kind: "document",
  id: id(20),
  version: "b".repeat(64),
  physical_page: 1,
  trace_id: null,
};
export const assistantReviewOldVersion = "a".repeat(64);

export function assistantReviewFixture({
  long = false,
}: { long?: boolean } = {}) {
  const scope = assistantReviewScope;
  const title = "合成章节：施工进度";
  const middle = "保留完整核对内容，不以局部预览替代原稿。".repeat(
    long ? 6000 : 12,
  );
  function content(proposal: boolean): AuthoringDocument {
    return {
      type: "doc",
      attrs: { title, ordinal: 1, rule_ids: [], source_refs: [] },
      content: [
        {
          type: "heading",
          attrs: { id: id(30), level: 2 },
          content: [{ type: "text", text: title }],
        },
        {
          type: "paragraph",
          attrs: { id: id(31) },
          content: [
            { type: "text", text: "施工" },
            { type: "text", text: "进度", marks: [{ type: "bold" }] },
            { type: "text", text: `安排：工期${proposal ? 45 : 30}日。` },
            { type: "hardBreak" },
            { type: "text", text: "软换行不丢失👩🏽‍🔧。" },
          ],
        },
        {
          type: "paragraph",
          attrs: { id: id(32) },
          content: [{ type: "text", text: middle }],
        },
        {
          type: "orderedList",
          attrs: { id: id(33) },
          content: [
            {
              type: "listItem",
              attrs: { id: id(34) },
              content: [
                {
                  type: "paragraph",
                  attrs: { id: id(35) },
                  content: [{ type: "text", text: "保留清单第一项。" }],
                },
              ],
            },
          ],
        },
        {
          type: "paragraph",
          attrs: { id: id(36) },
          content: [
            {
              type: "text",
              text: proposal
                ? "拟稿尾段：明确增派人员。"
                : "原稿尾段：保留现场核验。",
            },
          ],
        },
      ],
    };
  }
  const expected = (proposal: boolean) =>
    `${title}\n施工进度安排：工期${proposal ? 45 : 30}日。\n软换行不丢失👩🏽‍🔧。\n${middle}\n保留清单第一项。\n${proposal ? "拟稿尾段：明确增派人员。" : "原稿尾段：保留现场核验。"}`;
  const initial: AssistantAction = {
    action_id: scope.actionId,
    job_id: id(10),
    target_bid_id: scope.bidId,
    tool: "authoring.apply_patch",
    state: "pending",
    revision: 1,
    request_digest: "c".repeat(64),
    base_revision: 4,
    expires_at: "2099-01-01T00:00:00Z",
    preview: {
      kind: "authoring_patch",
      section_id: scope.sectionId,
      base_section_revision: 2,
      before: content(false),
      after: content(true),
      effect: "拟调整工期说明；尚未应用到正文。",
    },
    result: null,
    resolved_by: null,
    error_code: null,
    formal_scoring_input: false,
  };
  const sources: AssistantSourcePage = {
    coverage: "partial",
    notice: "合成来源目录，只表示本次可发现范围。",
    items: [
      {
        title: "进度条款原件",
        reference: assistantReviewReference,
        available: true,
        reasons: [],
        bid_id: scope.bidId,
        formal_scoring_input: false,
      },
      {
        title: "已撤回的补充原件",
        reference: null,
        available: false,
        reasons: ["SOURCE_WITHDRAWN"],
        bid_id: scope.bidId,
        formal_scoring_input: false,
      },
    ],
  };
  const state = {
    action: initial,
    sources,
    sourceReadFailure: false,
    resolveMode: "ok" as "ok" | "lost_ack" | "withdrawn",
    reads: [] as string[],
    writes: [] as {
      path: string;
      body: unknown;
      key: string | null;
      etag: string | null;
    }[],
    unexpected: [] as string[],
    applied: 0,
  };
  const receipts = new Map<string, AssistantAction>();
  let lost = false;
  function response(
    value: unknown,
    status = 200,
    etag = `"action:${state.action.revision}"`,
  ) {
    return new Response(JSON.stringify(value), {
      status,
      headers: { "Content-Type": "application/json", ETag: etag },
    });
  }
  const fetcher: typeof fetch = async (input, options = {}) => {
    const raw =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(raw, "http://synthetic.local");
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = options.method ?? "GET";
    if (method === "GET") {
      state.reads.push(path);
      if (path === `/assistant/actions/${scope.actionId}`)
        return response(state.action);
      if (path === `/bids/${scope.bidId}`)
        return response({ id: scope.bidId, title: "合成助手核对项目" });
      if (path === "/bids")
        return response({
          items: [{ id: scope.bidId, title: "合成助手核对项目" }],
          has_more: false,
          next_cursor: null,
        });
      if (path === "/assistant/sources") {
        if (state.sourceReadFailure)
          return response(
            {
              code: "SYNTHETIC_DIRECTORY_UNAVAILABLE",
              message: "合成目录暂时无法读取。",
            },
            503,
          );
        const kind = url.searchParams.get("kind");
        const query = url.searchParams.get("q") ?? "";
        return response({
          ...state.sources,
          items: state.sources.items.filter(
            (item) =>
              (item.reference?.kind ?? "document") === kind &&
              item.title.includes(query),
          ),
        });
      }
    }
    if (
      method === "POST" &&
      path === `/assistant/actions/${scope.actionId}/resolve`
    ) {
      const headers = new Headers(options.headers);
      const body = JSON.parse(String(options.body));
      const key = headers.get("Idempotency-Key");
      state.writes.push({ path, body, key, etag: headers.get("If-Match") });
      if (key && receipts.has(key)) return response(receipts.get(key));
      const withdrawn = state.resolveMode === "withdrawn";
      const applied = !withdrawn && body.decision === "confirm";
      const nextState = withdrawn ? "stale" : applied ? "executed" : "rejected";
      const error = withdrawn ? "ASSISTANT_SOURCE_CHANGED" : null;
      state.applied += applied ? 1 : 0;
      state.action = {
        ...state.action,
        state: nextState,
        revision: state.action.revision + 1,
        resolved_by: scope.memberId,
        error_code: error,
        result: {
          assistant_resolution: {
            action_id: scope.actionId,
            state: nextState,
            tool: "authoring.apply_patch",
            target_bid_id: scope.bidId,
            domain_result: applied
              ? {
                  draft_id: id(40),
                  draft_revision: 5,
                  snapshot_id: id(41),
                  snapshot_digest: "e".repeat(64),
                }
              : null,
            error_code: error,
            http_status: withdrawn ? 409 : 200,
            business_effect_executed: applied,
          },
        },
      };
      if (key) receipts.set(key, structuredClone(state.action));
      if (state.resolveMode === "lost_ack" && !lost) {
        lost = true;
        throw new TypeError("Synthetic response lost after one explicit apply");
      }
      return response(state.action);
    }
    state.unexpected.push(`${method} ${path}`);
    return response(
      {
        code: "SYNTHETIC_ROUTE_NOT_CONFIGURED",
        message: "此合成夹具没有该操作。",
      },
      501,
    );
  };
  return {
    state,
    fetcher,
    expectedBefore: expected(false),
    expectedAfter: expected(true),
  };
}
