import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Knowledge } from "./Knowledge";
import { KnowledgeVersionEditor } from "./KnowledgeVersionEditor";
import { clearKnowledgeStorage, knowledgeStorageKey } from "./knowledgeStorage";
import { setAuth } from "./api";
import type { KnowledgeView } from "./contracts";

// Explicit component fixtures; these checks do not attest published knowledge quality.
const source = {
  source_id: "source",
  source_revision: 2,
  document_version_id: "document",
  parse_id: "parse-fixed",
  physical_page: 1,
  evidence_id: "evidence",
  excerpt: "逐字出处",
};
const item: KnowledgeView = {
  id: "knowledge",
  version_id: "version",
  revision: 3,
  title: "排水方法",
  state: "candidate",
  content: "有来源的施工方法",
  categories: ["method"],
  source_ids: ["source"],
  source_impact: false,
  workflow: "candidate",
  version_no: 2,
  knowledge_source_id: "knowledge-source",
  source_revision: 1,
  published_version_id: null,
  published_workflow: null,
  scope: "明确适用范围",
  applicability: {
    bidder_ids: ["company"],
    bid_ids: [],
    regions: ["浙江"],
    engineering_types: ["市政"],
    conditions: [],
    purposes: ["assist"],
    validity_kind: "no_expiry_confirmed",
    valid_from: "2020-01-01T00:00:00Z",
    valid_until: null,
    validity_basis: "经核对无到期限制",
    specificity_note: "仅限明确场景",
  },
  source_refs: [source],
  provenance: [],
  declared_source_version_ids: ["document"],
  created_by: "member",
  created_at: "2026-01-01T00:00:00Z",
  confirmed_by: null,
  confirmed_at: null,
  reference_notice: "选用需重新核验，不自动创建工程事实",
};
function json(value: unknown, status = 200, etag?: string) {
  return new Response(JSON.stringify(value), {
    status,
    headers: etag ? { ETag: etag } : {},
  });
}
beforeEach(() => {
  sessionStorage.clear();
  setAuth({
    member: { id: "member", display_name: "测试", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
function basic(url: string) {
  const path = new URL(url, window.location.href).pathname;
  if (path === "/api/v1/bids")
    return json({ items: [], has_more: false, next_cursor: null });
  if (path === "/api/v1/identity/bidders")
    return json({
      items: [
        {
          id: "company",
          name: "实际登记主体",
          registered: true,
          registration_id: "registration",
        },
      ],
      has_more: false,
    });
  if (path.endsWith("source-positions"))
    return json({
      items: [{ reference: source, excerpt_truncated: false }],
      parse_id: "parse-fixed",
      physical_page: 1,
      page_count: 3,
      next_ordinal: null,
      has_more: false,
      readiness: "readable_text_positions_only",
    });
  if (path === "/api/v1/documents/document")
    return json({ id: "document", filename: "原件.pdf", file_revision: 1 });
  return json({ items: [], has_more: false, next_cursor: null });
}
it("收起、离开后保留成员自己的候选输入，恢复本地输入不发创建请求", async () => {
  const user = userEvent.setup();
  const writes = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") writes();
      if (new URL(url, window.location.href).pathname === "/api/v1/knowledge") {
        expect(new URL(url, window.location.href).searchParams.has("q")).toBe(
          false,
        );
      }
      return basic(url);
    }),
  );
  const props = { memberId: "member", selectedId: null, onSelect: vi.fn() };
  const first = render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "建立知识候选" }));
  await user.type(screen.getByLabelText("候选标题"), "尚未保存的知识");
  await user.type(screen.getByLabelText("知识正文"), "需要保留的中文内容");
  await user.click(screen.getByRole("button", { name: "收起候选表单" }));
  first.unmount();
  render(<Knowledge {...props} />);
  await user.click(screen.getByRole("button", { name: "建立知识候选" }));
  expect(screen.getByLabelText("候选标题")).toHaveValue("尚未保存的知识");
  expect(screen.getByLabelText("知识正文")).toHaveValue("需要保留的中文内容");
  expect(writes).not.toHaveBeenCalled();
  sessionStorage.setItem(
    knowledgeStorageKey("other", "candidate") + "title",
    JSON.stringify("其他成员"),
  );
  clearKnowledgeStorage("member");
  expect(
    sessionStorage.getItem(knowledgeStorageKey("other", "candidate") + "title"),
  ).toBeNull();
  expect(
    sessionStorage.getItem(
      knowledgeStorageKey("member", "candidate") + "title",
    ),
  ).toContain("尚未保存");
});
it("原页与失败重试按钮不会提交版本；412后保留正文及旧令牌，明确比较才用新令牌", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        if (writes.length === 1)
          return json(
            {
              code: "REVISION_CONFLICT",
              message: "服务器已有新版",
              retryable: false,
              details: {},
            },
            412,
          );
        return json({ ...item, revision: 5, version_no: 4 });
      }
      if (url === "/api/v1/knowledge/knowledge")
        return json(
          { ...item, content: "他人新版正文", revision: 4, version_no: 3 },
          200,
          '"real-current-head"',
        );
      if (url === "/api/v1/evidence/evidence")
        return json(
          {
            code: "TEMPORARY",
            message: "原页读取失败",
            retryable: true,
            details: {},
          },
          503,
        );
      return basic(url);
    }),
  );
  const saved = vi.fn();
  render(
    <KnowledgeVersionEditor
      item={item}
      etag={'"original-head"'}
      memberId="member"
      onSaved={saved}
      onCancel={vi.fn()}
    />,
  );
  await user.clear(screen.getByLabelText("特殊条件与范围说明"));
  expect(screen.getByRole("button", { name: "保存候选新版本" })).toBeDisabled();
  expect(
    screen.getByText("保存前还需填写或核对").closest("[role=status]"),
  ).toHaveTextContent("保存前还需填写或核对特殊条件与范围说明");
  await user.type(
    screen.getByLabelText("特殊条件与范围说明"),
    "明确适用范围边界",
  );
  await user.clear(screen.getByLabelText("版本正文"));
  await user.type(screen.getByLabelText("版本正文"), "我保留的修订内容");
  await user.click(screen.getByRole("button", { name: /核对已选原页/ }));
  await user.click(await screen.findByRole("button", { name: "重试" }));
  expect(writes).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "保存候选新版本" }));
  await screen.findByText(/当前版本或来源状态已有变化/);
  expect(screen.getByLabelText("版本正文")).toHaveValue("我保留的修订内容");
  expect(new Headers(writes[0].headers).get("If-Match")).toBe(
    '"original-head"',
  );
  await user.click(screen.getByRole("button", { name: "读取最新知识并比较" }));
  await screen.findByText("他人新版正文");
  await user.click(
    screen.getByRole("button", { name: "保留本地内容，按当前版本继续追加" }),
  );
  await user.click(screen.getByRole("button", { name: "保存候选新版本" }));
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(new Headers(writes[1].headers).get("If-Match")).toBe(
    '"real-current-head"',
  );
  expect(JSON.parse(writes[1].body as string)).toMatchObject({
    content: "我保留的修订内容",
    source_refs: [source],
  });
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).not.toBe(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
});
it("创建请求尚未返回时离开页面，迟到ACK不把用户导航回知识对象", async () => {
  const user = userEvent.setup();
  let resolve: ((response: Response) => void) | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST")
        return new Promise<Response>((done) => {
          resolve = done;
        });
      if (String(url).includes("/bids"))
        return String(url).includes("/materials")
          ? json({
              documents: [
                { id: "document", filename: "原件.pdf", file_revision: 1 },
              ],
            })
          : json({
              items: [{ id: "bid", title: "真实项目" }],
              has_more: false,
              next_cursor: null,
            });
      return basic(url);
    }),
  );
  const select = vi.fn();
  const view = render(
    <Knowledge memberId="member" selectedId={null} onSelect={select} />,
  );
  await user.click(screen.getByRole("button", { name: "建立知识候选" }));
  await user.type(screen.getByLabelText("候选标题"), "候选");
  await user.type(screen.getByLabelText("知识正文"), "正文");
  await user.type(screen.getByLabelText("拟适用范围说明"), "范围");
  await user.selectOptions(screen.getByLabelText("候选来源项目"), "bid");
  await user.click(await screen.findByRole("checkbox", { name: /原件.pdf/ }));
  await user.click(screen.getByRole("button", { name: "保存待完善候选" }));
  await waitFor(() => expect(resolve).toBeDefined());
  view.unmount();
  await act(async () => resolve!(json(item, 201)));
  expect(select).not.toHaveBeenCalled();
  expect(
    sessionStorage.getItem("tender:command:knowledge-candidate:member"),
  ).toContain("knowledge");
});

it("最新候选与旧发布版分别可读，影响清单能跨会话追溯旧引用和当前失效原因", async () => {
  const user = userEvent.setup();
  const writes = vi.fn();
  const candidate = {
    ...item,
    published_version_id: "published-v1",
    published_workflow: "published",
    title: "维护中的新版候选",
  };
  const published = {
    ...item,
    version_id: "published-v1",
    version_no: 1,
    state: "published",
    workflow: "published",
    published_version_id: "published-v1",
    published_workflow: "published",
    title: "已发布旧版本",
    content: "旧版固定正文",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") writes();
      const path = new URL(url, window.location.href).pathname;
      if (path === "/api/v1/knowledge/knowledge")
        return json(candidate, 200, '"knowledge-head"');
      if (path === "/api/v1/knowledge/knowledge/versions/published-v1")
        return json(published);
      if (path.endsWith("/impacts"))
        return json({
          knowledge_id: "knowledge",
          version_id: "published-v1",
          workflow: "published",
          groups: {
            working: ["citation", "citation2", "citation3", "citation4"].map(
              (citation_id) => ({
                citation_id,
                bid_id: "bid",
                target_object_id: "bid",
                purpose: "assist",
                created_at: "2026-01-01T00:00:00Z",
                phase: "working",
                archived_at: null,
                title: "曾使用此知识的项目",
              }),
            ),
            submitted: [],
            archived: [],
            closed: [],
          },
          registered_research_model_derivations: [],
          requires_review: true,
          unknown_ranges: [],
          historical_reports_rewritten: false,
        });
      if (path === "/api/v1/knowledge-references/citation")
        return json({
          reference: {
            knowledge_id: "knowledge",
            version_id: "published-v1",
            bid_id: "bid",
            citation_ids: ["citation"],
            excerpt: "当时固定的摘录",
            purpose: "assist",
            target_kind: "project",
            target_object_id: "bid",
            applicability_reason: "当时实际依据",
            source_manifest: [],
            source_refs: [source],
            reference_only: true,
            project_fact_created: false,
            evaluated_at: "2026-01-01T00:00:00Z",
          },
          version_content: "历史固定正文",
          current_applicability_reasons: ["当前来源已失效，仅保留历史"],
          historical_bytes_preserved: true,
        });
      return basic(url);
    }),
  );
  render(
    <Knowledge memberId="member" selectedId="knowledge" onSelect={vi.fn()} />,
  );
  await screen.findByRole("heading", { name: "维护中的新版候选" });
  await user.click(screen.getByRole("button", { name: "查看当前发布版本" }));
  await screen.findByRole("heading", { name: "已发布旧版本" });
  expect(screen.getByText("旧版固定正文")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "查看当前版本影响" }));
  expect(await screen.findByText(/在办项目.*1个项目.*4处引用/)).toBeVisible();
  await user.click(
    (await screen.findAllByRole("button", { name: "追溯此项目当时引用" }))[0],
  );
  await screen.findByText("当时固定的摘录");
  expect(screen.getByText("当前来源已失效，仅保留历史")).toBeVisible();
  expect(writes).not.toHaveBeenCalled();
});

it("引用上下文409后不普通重试，明确重读主体与原知识版本才以新命令继续，摘录不丢且不创建事实", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  let reads = 0;
  const published = {
    ...item,
    state: "published",
    workflow: "published",
    published_version_id: item.version_id,
    published_workflow: "published",
  };
  const bid = {
    id: "bid",
    title: "目标项目",
    phase: "working",
    archived_at: null,
    identity: {
      bidder_id: "company",
      bidder_name: "原已确认公司",
      region: "浙江",
      engineering_type: "市政",
      binding_status: "confirmed",
      digest: "a".repeat(64),
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      const path = new URL(url, window.location.href).pathname;
      if (options?.method === "POST") {
        writes.push(options);
        if (writes.length === 1)
          return json(
            {
              code: "KNOWLEDGE_PROJECT_CONTEXT_CHANGED",
              message: "身份依据已有变化，请重新核对",
              retryable: false,
              details: {},
            },
            409,
          );
        return json(
          {
            knowledge_id: item.id,
            version_id: item.version_id,
            bid_id: "bid",
            citation_ids: [],
            excerpt: "有来源的施工方法",
            purpose: "assist",
            target_kind: "project",
            target_object_id: "bid",
            applicability_reason: "本工程方法适用",
            source_manifest: [],
            source_refs: [source],
            reference_only: true,
            project_fact_created: false,
            evaluated_at: "2026-01-01T00:00:00Z",
          },
          201,
        );
      }
      if (path === "/api/v1/bids")
        return json({ items: [bid], has_more: false, next_cursor: null });
      if (path === "/api/v1/bids/bid") {
        reads++;
        return json({
          ...bid,
          identity: {
            ...bid.identity,
            bidder_name: reads > 1 ? "刚核对的当前公司" : "原已确认公司",
            digest: reads > 1 ? "b".repeat(64) : "a".repeat(64),
          },
        });
      }
      if (
        path === "/api/v1/knowledge/knowledge" ||
        path === "/api/v1/knowledge/knowledge/versions/version"
      )
        return json(published, 200, '"knowledge-head"');
      return basic(url);
    }),
  );
  render(
    <Knowledge memberId="member" selectedId="knowledge" onSelect={vi.fn()} />,
  );
  await screen.findByRole("option", { name: "目标项目" });
  await user.selectOptions(screen.getByLabelText("知识目标项目"), "bid");
  await screen.findByRole("heading", { name: "明确选作项目参考" });
  await user.type(
    screen.getByLabelText("本次使用的实际摘录"),
    "有来源的施工方法",
  );
  await user.type(
    screen.getByLabelText("为何适用于此项目与用途"),
    "本工程方法适用",
  );
  await user.click(screen.getByRole("button", { name: "登记本次项目参考" }));
  await screen.findByText("身份依据已有变化，请重新核对");
  expect(
    screen.getByRole("button", { name: "登记本次项目参考" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", {
      name: "重新核对项目与知识版本，保留本次摘录",
    }),
  );
  await screen.findByText(/刚核对的当前公司/);
  expect(screen.getByLabelText("本次使用的实际摘录")).toHaveValue(
    "有来源的施工方法",
  );
  await user.click(screen.getByRole("button", { name: "登记本次项目参考" }));
  await screen.findByText("参考已登记，未创建项目事实");
  expect(writes).toHaveLength(2);
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).not.toBe(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
  expect(JSON.parse(writes[1].body as string)).toMatchObject({
    version_id: item.version_id,
    bid_id: "bid",
    excerpt: "有来源的施工方法",
  });
});
