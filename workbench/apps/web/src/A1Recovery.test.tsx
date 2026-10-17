import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { NextActionControl } from "./NextActionControl";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { ReviewHistory } from "./ReviewHistory";
import { ReviewIdentity } from "./ReviewIdentity";
import { ReviewProgress } from "./ReviewProgress";
import { ReviewStart } from "./ReviewPanel";
import type {
  Accepted,
  Bid,
  DocumentView,
  Operation,
  ReviewManifest,
  ReviewStateView,
  ReviewView,
} from "./contracts";

// Contract-shaped component fixtures, not paid model or live business acceptance.
vi.mock("./Evidence", () => ({
  Evidence: ({
    document,
    onClose,
  }: {
    document: DocumentView;
    onClose: () => void;
  }) => (
    <div role="dialog" aria-label="测试受检原页">
      <p>
        {document.filename} · {document.id}
      </p>
      <button onClick={onClose}>关闭测试原页</button>
    </div>
  ),
}));
const bid: Bid = {
  identity: {
    bidder_id: "bidder",
    bidder_name: "待确认主体",
    round_id: "round",
    engineering_project_id: "engineering",
    engineering_title: "合成工程",
    region: null,
    engineering_type: null,
    lot: null,
    round_no: 1,
    binding_status: "pending",
    authority_id: null,
    digest: "a".repeat(64),
  },
  id: "bid-1",
  title: "恢复机制测试",
  revision: 2,
  material_revision: 2,
  presentation_revision: 1,
  phase: "working",
  archived_at: null,
  current_body_id: "body-v2",
  current_review_id: null,
  stream_id: "stream-1",
  next_action: {
    action: "start_review",
    reason: "使用当前稿开始评审",
    target_url: "/bids/bid-1/review",
    blocked: false,
  },
};
const body: DocumentView = {
  id: "body-v2",
  bid_id: bid.id,
  filename: "正文V2.pdf",
  role: "body",
  artifact_kind: "bid_body",
  sha256: "a".repeat(64),
  byte_size: 500,
  media_type: "application/pdf",
  obtained_at: "2026-10-16T00:00:00Z",
  parse_coverage: "partial",
  file_id: "file-body",
  file_revision: 2,
  previous_version_id: "body-v1",
  file_head_revision: 2,
  file_head_version_id: "body-v2",
  source_relation: null,
};
const operation: Operation = {
  id: "op-prepare",
  bid_id: bid.id,
  kind: "prepare-requirements",
  state: "running",
  input_digest: "b".repeat(64),
  handler_version: "test",
  result_ref: null,
};
const initial: ReviewStateView = {
  bid_id: bid.id,
  revision: 1,
  current_body_id: body.id,
  material_revision: 2,
  current_material_snapshot_id: "material-v2",
  current_rule_set_id: null,
  current_review: null,
  request: {
    request_id: "request-1",
    trigger: "manual",
    body_version_id: body.id,
    material_snapshot_id: "material-v2",
    material_revision: 2,
    state: "preparing",
    prepare_operation_id: operation.id,
    review_id: null,
    error_code: null,
    gaps: [],
    updated_at: "2026-10-16T00:00:00Z",
  },
};
const layer = {
  state: "partial" as const,
  planned: 2,
  completed: 1,
  denominator_basis: "本轮已识别范围",
  gaps: ["表图范围缺口"],
};
function review(id: string): ReviewView {
  return {
    id,
    bid_id: bid.id,
    operation_id: "op-review",
    input_digest: "a".repeat(64),
    core_coverage: "partial",
    risk_count: 1,
    current: false,
    prediction: {
      review_id: id,
      mode: "unavailable",
      maximum: null,
      reasons: ["本测试没有正式评分"],
      method_digest: "b".repeat(64),
    },
    next_action: bid.next_action,
    source_impact_revision: 1,
    manifest_digest: "c".repeat(64),
    coverage_layers: {
      source_scope: layer,
      core_extraction: layer,
      judgment: layer,
      scoring: { ...layer, state: "not_run" },
      extraction_quality: "not_measured",
      quality_report_id: null,
      human_confirmation_pending: 0,
    },
  };
}
function json(data: unknown, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), { status, headers });
}
let transport: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  transport = vi.fn<typeof fetch>().mockImplementation(async (url) => {
    if (url === "/api/v1/bids/bid-1")
      return json(bid, 200, { ETag: '"actual-bid-etag"' });
    if (url === "/api/v1/bids/bid-1/review-state") return json(initial);
    if (url === "/api/v1/bids/bid-1/reviews")
      return json({ items: [], next_cursor: null, has_more: false });
    if (String(url).includes("/materials"))
      return json({ documents: [body], conflicts: [] });
    if (String(url).includes("/documents/")) return json(body);
    return json(operation);
  });
  vi.stubGlobal("fetch", transport);
});
function workspace() {
  render(
    <ProjectWorkspace
      id={bid.id}
      route="/bids/bid-1/review"
      onBack={vi.fn()}
      onNavigate={vi.fn()}
    />,
  );
}
it("刷新后从服务端恢复准备请求与固定稿件，运行中不再次开始", async () => {
  workspace();
  expect(
    await screen.findByRole("heading", {
      name: "正在准备本轮要求，完成后自动开始评审，可离开",
    }),
  ).toBeVisible();
  expect(
    await within(
      screen.getByRole("region", { name: "本次评审进度" }),
    ).findByText("正文V2.pdf · 文件版本 2"),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "本次处理已受理，请查看真实进度" }),
  ).toBeDisabled();
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
  expect(screen.queryByText("尚未形成评审结果")).not.toBeInTheDocument();
});
it("取消未冻结准备使用服务器ReviewState强令牌，412时保留原因而不声称已取消", async () => {
  const refresh = vi.fn();
  transport.mockImplementation(async (url) => {
    if (String(url).endsWith("/cancel"))
      return json(
        { code: "REVISION_CONFLICT", message: "请求已经变化，请核对" },
        412,
      );
    if (String(url).includes("/documents/")) return json(body);
    if (String(url).includes("/operations/")) return json(operation);
    return json(initial);
  });
  render(
    <ReviewProgress
      state={initial}
      etag={'"actual-state-etag"'}
      loading={false}
      unavailable={false}
      onRetry={refresh}
      onNavigate={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "取消本次准备请求" }),
  );
  await userEvent.type(screen.getByLabelText("取消原因"), "先核对新补遗再继续");
  await userEvent.click(screen.getByRole("button", { name: "取消本次准备" }));
  expect(await screen.findByText("请求已经变化，请核对")).toBeInTheDocument();
  expect(screen.getByLabelText("取消原因")).toHaveValue("先核对新补遗再继续");
  expect(refresh).not.toHaveBeenCalled();
  const write = transport.mock.calls.find(([url]) =>
    String(url).endsWith("/cancel"),
  );
  expect(new Headers(write?.[1]?.headers).get("If-Match")).toBe(
    '"actual-state-etag"',
  );
  expect(JSON.parse(write?.[1]?.body as string)).toMatchObject({
    reason: "先核对新补遗再继续",
    cancel_pending_same_input: false,
  });
  expect(screen.queryByText("本次要求准备请求已取消")).not.toBeInTheDocument();
});
it("取消表单打开后服务器换了请求，不将旧取消原因配新请求令牌自动提交", async () => {
  const props = {
    loading: false,
    unavailable: false,
    onRetry: vi.fn(),
    onNavigate: vi.fn(),
  };
  const view = render(
    <ReviewProgress {...props} state={initial} etag={'"request-1"'} />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "取消本次准备请求" }),
  );
  await userEvent.type(
    screen.getByLabelText("取消原因"),
    "取消先前这份正文的准备",
  );
  view.rerender(
    <ReviewProgress
      {...props}
      state={{
        ...initial,
        request: {
          ...initial.request!,
          request_id: "new-request",
          body_version_id: "body-v3",
        },
      }}
      etag={'"new-request-etag"'}
    />,
  );
  expect(screen.getByRole("button", { name: "取消本次准备" })).toBeDisabled();
  expect(screen.getByLabelText("取消原因")).toHaveValue(
    "取消先前这份正文的准备",
  );
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});
it("未冻结旧请求已过期时保留V1身份，当前稿V2需要明确开始且不自动收费", async () => {
  transport.mockImplementation(async (url) => {
    if (url === "/api/v1/bids/bid-1")
      return json(bid, 200, { ETag: '"actual-bid-etag"' });
    if (String(url).endsWith("/review-state"))
      return json({
        ...initial,
        request: {
          ...initial.request,
          body_version_id: "body-v1",
          material_revision: 1,
          state: "superseded",
        },
      });
    if (String(url).endsWith("/materials"))
      return json({ documents: [body], conflicts: [] });
    if (String(url).endsWith("/reviews"))
      return json({ items: [], next_cursor: null, has_more: false });
    if (String(url).endsWith("/documents/body-v1"))
      return json({
        ...body,
        id: "body-v1",
        filename: "正文V1.pdf",
        file_revision: 1,
      });
    return json(operation);
  });
  workspace();
  expect(await screen.findByText("资料已更新，原请求已过期")).toBeVisible();
  expect(await screen.findByText("正文V1.pdf · 文件版本 1")).toBeVisible();
  expect(screen.getByLabelText("本次评审正文")).toHaveValue("body-v2");
  expect(
    screen.getByRole("button", { name: "使用当前稿开始评审" }),
  ).toBeDefined();
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});
it("准备失败保留范围，明确重试只发一次当前输入和真实bid ETag", async () => {
  transport.mockImplementation(async (url, init) => {
    if (url === "/api/v1/bids/bid-1")
      return json(bid, 200, { ETag: '"actual-bid-etag"' });
    if (String(url).endsWith("/review-state"))
      return json({
        ...initial,
        request: {
          ...initial.request,
          state: "blocked",
          error_code: "SOURCE_SCOPE_PARTIAL",
          gaps: ["必要表页读取尚未完成"],
        },
      });
    if (String(url).endsWith("/reviews"))
      return init?.method === "POST"
        ? json(
            {
              resource_id: "request-new",
              operation_url: "/api/v1/operations/op-prepare",
              operation: { ...operation, state: "queued" },
              resource_kind: "pending_intent",
              disposition: "created",
            } satisfies Accepted,
            202,
          )
        : json({ items: [], next_cursor: null, has_more: false });
    if (String(url).endsWith("/materials"))
      return json({ documents: [body], conflicts: [] });
    if (String(url).includes("/documents/")) return json(body);
    return json(operation);
  });
  workspace();
  expect(await screen.findByText("必要表页读取尚未完成")).toBeVisible();
  const retry = await screen.findByRole("button", { name: "重试并继续评审" });
  await waitFor(() => expect(retry).toBeEnabled());
  await userEvent.click(retry);
  const writes = transport.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({
    body_version_id: "body-v2",
    material_revision: 2,
    trigger: "manual",
  });
  expect(new Headers(writes[0][1]?.headers).get("If-Match")).toBe(
    '"actual-bid-etag"',
  );
  expect(
    screen.getByRole("button", { name: "本次处理已受理，请查看真实进度" }),
  ).toBeDisabled();
});
it("actual接口已声明但旧live未提供时明确服务版本未就绪并禁用新请求", async () => {
  transport.mockImplementation(async (url) => {
    if (String(url).endsWith("/review-state"))
      return json({ detail: "Not Found" }, 404);
    if (url === "/api/v1/bids/bid-1")
      return json(bid, 200, { ETag: '"actual-bid-etag"' });
    if (String(url).endsWith("/materials"))
      return json({ documents: [body], conflicts: [] });
    return json({ items: [], next_cursor: null, has_more: false });
  });
  workspace();
  expect(await screen.findByText(/服务器当前版本尚未提供此接口/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "正在核对服务器处理状态…" }),
  ).toBeDisabled();
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});
it("服务器历史分页发现旧轮，分页失败保留已读列表并可重试", async () => {
  let page2 = 0;
  transport.mockImplementation(async (url) => {
    if (String(url).includes("?cursor="))
      return ++page2 === 1
        ? json({ message: "历史读取暂不可用", code: "TEMPORARY" }, 503)
        : json({
            items: [review("review-old")],
            next_cursor: null,
            has_more: false,
          });
    return json({
      items: [review("review-new")],
      next_cursor: "cursor:1",
      has_more: true,
    });
  });
  const open = vi.fn();
  render(<ReviewHistory bidId={bid.id} selectedId={null} onOpen={open} />);
  await userEvent.click(screen.getByText("查看项目评审历史", { exact: false }));
  await userEvent.click(
    await screen.findByRole("button", { name: "加载更早的评审轮次" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "历史读取暂不可用",
  );
  expect(screen.getByText("评审轮次 review-n")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "重试" }));
  const old = await screen.findByText("评审轮次 review-o");
  await userEvent.click(
    within(old.closest("article")!).getByRole("button", {
      name: "查看此轮评审",
    }),
  );
  expect(open).toHaveBeenCalledWith("review-old");
});
it("历史manifest只读取固定V1受检稿，不以项目当前V2替换", async () => {
  const manifest: ReviewManifest = {
    bid_id: bid.id,
    body_version_id: "body-v1",
    material_snapshot_id: "material-v1",
    material_revision: 1,
    rule_set_id: "rules-v1",
    fact_set_id: null,
    parse_run_ids: ["parse-v1"],
    method_digest: "m",
    policy_digest: "p",
    purpose: "compliance_and_scoring",
    source_refs: [],
    content_checks: { consistency: false, scope_residue: false },
    frozen_at: "2026-10-15T01:00:00Z",
    as_of: "2026-10-15T00:00:00Z",
    evaluation_context_digest: "e",
    evidence_manifest_digest: "d",
  };
  transport.mockImplementation(async (url) =>
    String(url).endsWith("/manifest")
      ? json(manifest)
      : json({
          ...body,
          id: "body-v1",
          filename: "正文V1.pdf",
          file_revision: 1,
        }),
  );
  render(<ReviewIdentity reviewId="review-old" bidId={bid.id} />);
  expect(await screen.findByText("正文V1.pdf · 版本 1")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "查看本轮受检原件" }),
  );
  expect(
    await screen.findByRole("dialog", { name: "测试受检原页" }),
  ).toHaveTextContent("正文V1.pdf · body-v1");
  expect(
    transport.mock.calls.some(([url]) => url === "/api/v1/documents/body-v2"),
  ).toBe(false);
});
it("关键阻断可打开定位，导航不会执行评审或提交命令", async () => {
  const navigate = vi.fn();
  render(
    <NextActionControl
      bidId={bid.id}
      action={{ ...bid.next_action, blocked: true }}
      onNavigate={navigate}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "查看风险与本轮处理" }),
  );
  expect(navigate).toHaveBeenCalledWith("review", undefined);
  expect(screen.getByText(/不表示已经符合继续执行或提交条件/)).toBeVisible();
  expect(transport).not.toHaveBeenCalled();
});
it("已受理新请求后，上一条服务器终态尚未刷新不能造成双击重复启动", async () => {
  const completed = {
    ...initial,
    request: { ...initial.request!, state: "completed" as const },
  };
  transport.mockImplementation(async (url, init) => {
    if (init?.method === "POST")
      return json(
        {
          resource_id: "request-new",
          operation_url: "/api/v1/operations/op-prepare",
          resource_kind: "pending_intent",
          disposition: "created",
          operation: { ...operation, state: "queued" },
        } satisfies Accepted,
        202,
      );
    if (String(url).endsWith("/materials"))
      return json({ documents: [body], conflicts: [] });
    if (url === "/api/v1/bids/bid-1")
      return json(bid, 200, { ETag: '"actual-bid-etag"' });
    return json(operation);
  });
  render(
    <ReviewStart bid={bid} onAccepted={vi.fn()} reviewState={completed} />,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "开始评审所选正文" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "开始评审所选正文" }),
  );
  expect(
    screen.getByRole("button", { name: "本次处理已受理，请查看真实进度" }),
  ).toBeDisabled();
  expect(
    transport.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
});

it("新浏览器没有本地任务缓存仍能从服务器准备请求找到操作与失败详情入口", async () => {
  render(
    <ProjectWorkspace
      id={bid.id}
      route="/bids/bid-1/operations"
      onBack={vi.fn()}
      onNavigate={vi.fn()}
    />,
  );
  expect(await screen.findByText("评审要求准备")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "查看字段与范围详情" }),
  ).toBeEnabled();
  expect(
    screen.queryByText(/尚未收到可恢复的任务记录/),
  ).not.toBeInTheDocument();
  expect(localStorage.getItem("tender:operations:bid-1")).toBeNull();
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});

it("服务器进度已切到新版而项目卡仍旧时禁用旧输入，刷新核对后才继续", async () => {
  render(
    <ReviewStart
      bid={{ ...bid, material_revision: 1, current_body_id: "body-v1" }}
      onAccepted={vi.fn()}
      reviewState={initial}
    />,
  );
  expect(
    await screen.findByText(
      "当前资料或正文已变化，请刷新并核对本次实际评审对象。",
    ),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "开始评审所选正文" }),
  ).toBeDisabled();
  expect(transport.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});
