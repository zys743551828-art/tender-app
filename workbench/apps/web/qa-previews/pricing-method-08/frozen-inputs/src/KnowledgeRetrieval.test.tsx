import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { KnowledgeRetrieval } from "./KnowledgeRetrieval";
import { clearRecordedCommands } from "./useRecordedCommand";
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const hit = {
  unit_id: "unit",
  unit_source_id: "source",
  unit_kind: "knowledge_text",
  knowledge_id: "knowledge",
  knowledge_version_id: "version",
  knowledge_source_id: "ks",
  index_id: "idx",
  text: "整理后的施工参考，不是原文逐字引用。",
  span_start: 0,
  span_end: 20,
  offset_basis: "knowledge_content",
  rank: 1,
  reference_only: true,
  project_fact_created: false,
  provenance: {
    kind: "derived_knowledge",
    offset_basis: "knowledge_content",
    verbatim_original: false,
    approved_references: [
      {
        source_id: "s",
        source_revision: 1,
        document_version_id: "d",
        parse_id: "p",
        physical_page: 2,
        evidence_id: "e",
        excerpt: "原文批准片段",
      },
    ],
  },
};
const retrieval = {
  trace_id: "trace",
  profile_id: "profile",
  policy_digest: "d".repeat(64),
  coverage: "partial",
  hits: [hit],
  gaps: ["仅提供当前可用知识参考"],
  route: ["vector", "lexical"],
};
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/knowledge");
  vi.restoreAllMocks();
});
it("只在明确查证后执行，实际unit登记参考且固定链接恢复，不创建事实", async () => {
  const u = userEvent.setup();
  const writes: {
    path: string;
    body: Record<string, unknown>;
    headers: Headers;
  }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        writes.push({ path: url, body, headers: new Headers(init.headers) });
        if (url.endsWith("/references"))
          return json({
            citation_id: "citation",
            trace_id: "trace",
            bid_id: "bid",
            unit_id: "unit",
          });
        return json(retrieval);
      }
      if (url.endsWith("/knowledge-retrievals/trace"))
        return json({
          retrieval,
          evaluated_at: "2026-01-01T00:00:00Z",
          current_reasons: [],
          historical_bytes_preserved: true,
        });
      return json({}, 404);
    }),
  );
  render(
    <KnowledgeRetrieval
      memberId="member"
      bidId="bid"
      purpose="assist"
      knowledgeId="knowledge"
    />,
  );
  await u.type(screen.getByLabelText("查证问题"), "排水施工方法");
  expect(writes).toHaveLength(0);
  await u.click(
    screen.getByRole("checkbox", {
      name: "仅查证当前打开的知识条目（先从目录选择）",
    }),
  );
  await u.click(screen.getByRole("button", { name: "查证企业知识" }));
  await screen.findByText("知识整理内容 · 派生参考");
  expect(screen.getByText(/原文批准片段/)).toBeVisible();
  await u.click(screen.getByRole("button", { name: "登记为本项目参考" }));
  await u.type(
    screen.getByLabelText("本次用途与适用理由"),
    "适用于本项目排水方案参考",
  );
  await u.click(screen.getByRole("button", { name: "保存项目参考" }));
  await waitFor(() =>
    expect(window.location.search).toContain("citation=citation"),
  );
  expect(writes).toHaveLength(2);
  expect(writes[0].body.knowledge_ids).toEqual(["knowledge"]);
  expect(writes[1].body).toMatchObject({
    unit_id: "unit",
    target_kind: "project",
    target_object_id: "bid",
    quote: hit.text,
  });
  expect(writes.every((w) => !w.path.includes("/facts"))).toBe(true);
});
it("历史资格改变保留原内容和原页入口，但不能新增引用", async () => {
  window.history.replaceState({}, "", "/knowledge?bid=bid&trace=trace");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        retrieval,
        evaluated_at: "2026-01-01T00:00:00Z",
        current_reasons: ["PROJECT_IDENTITY_UNCONFIRMED"],
        historical_bytes_preserved: true,
      }),
    ),
  );
  render(<KnowledgeRetrieval memberId="member" bidId="bid" purpose="assist" />);
  await screen.findByText(hit.text);
  expect(
    screen.getByRole("button", { name: "登记为本项目参考" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: /查看批准来源原页/ }),
  ).toBeEnabled();
  expect(screen.getByText(/项目投标主体或工程身份尚未有据确认/)).toBeVisible();
});
it("未知响应恢复严格复用query与幂等键，跨成员清理恢复记录", async () => {
  const u = userEvent.setup();
  const attempts: { body: string; key: string | null }[] = [];
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        attempts.push({
          body: String(init.body),
          key: new Headers(init.headers).get("Idempotency-Key"),
        });
        if (fail) {
          fail = false;
          throw new TypeError("lost");
        }
        return json(retrieval);
      }
      return json({
        retrieval,
        evaluated_at: "2026-01-01T00:00:00Z",
        current_reasons: [],
        historical_bytes_preserved: true,
      });
    }),
  );
  const view = render(
    <KnowledgeRetrieval memberId="member" bidId="bid" purpose="assist" />,
  );
  await u.type(screen.getByLabelText("查证问题"), "失响应");
  await u.click(screen.getByRole("button", { name: "查证企业知识" }));
  await screen.findByRole("button", { name: "恢复原查证结果" });
  view.unmount();
  render(<KnowledgeRetrieval memberId="member" bidId="bid" purpose="assist" />);
  expect(screen.getByLabelText("查证问题")).toBeDisabled();
  await u.click(screen.getByRole("button", { name: "恢复原查证结果" }));
  await screen.findByText(hit.text);
  expect(attempts).toHaveLength(2);
  expect(attempts[0]).toEqual(attempts[1]);
  sessionStorage.setItem(
    "tender:command-record:knowledge-unit:other:trace:unit",
    "{}",
  );
  clearRecordedCommands("member");
  expect(
    sessionStorage.getItem(
      "tender:command-record:knowledge-unit:other:trace:unit",
    ),
  ).toBeNull();
});
