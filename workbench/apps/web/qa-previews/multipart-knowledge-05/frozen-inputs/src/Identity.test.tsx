import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CreateIdentityForm, IdentityPanel } from "./Identity";
import { setAuth } from "./api";
import type { BidIdentityView, BiddingCompanyPage } from "./contracts";

// Synthetic identities test selection and conditional commands, not company qualification.
const companies: BiddingCompanyPage = {
  items: [
    {
      id: "company-a",
      name: "杭州甲工程有限公司",
      registered: true,
      registration_id: "reg-a",
    },
    {
      id: "company-b",
      name: "杭州甲工程建设有限公司",
      registered: true,
      registration_id: "reg-b",
    },
  ],
  has_more: false,
  next_cursor: null,
};
const identity: BidIdentityView = {
  identity: {
    bidder_id: "placeholder",
    bidder_name: "本公司（部署主体待核验）",
    round_id: "round-original",
    engineering_project_id: "engineering",
    engineering_title: "原工程",
    region: "浙江",
    engineering_type: "市政",
    lot: "一标段",
    round_no: 1,
    binding_status: "pending",
    authority_id: null,
    digest: "a".repeat(64),
  },
  affected: {
    reviews: 1,
    submissions: 1,
    outcomes: 0,
    samples: 1,
    drafts: 1,
    documents: 2,
    facts: 3,
    knowledge_citations: 1,
  },
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
it("真实默认主体在表单可见，创建一次即绑定所选ID，无第二次确认且不按近似名合并", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  const created = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        return json({ id: "new-bid" }, 201);
      }
      if (url.includes("default-bidder"))
        return json(
          { bidder: companies.items[0], authority_id: "default-authority" },
          200,
          '"default-etag"',
        );
      return json(companies);
    }),
  );
  render(<CreateIdentityForm onCreated={created} />);
  await screen.findByRole("option", { name: "杭州甲工程有限公司" });
  expect(screen.getByLabelText("本次选择的投标主体")).toHaveValue("company-a");
  await user.selectOptions(
    screen.getByLabelText("本次选择的投标主体"),
    "company-b",
  );
  await user.type(screen.getByLabelText("项目名称"), "同轮独立工作单元");
  await user.click(screen.getByRole("button", { name: "创建并上传资料" }));
  await waitFor(() => expect(created).toHaveBeenCalledWith("new-bid"));
  expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0].body as string)).toEqual({
    title: "同轮独立工作单元",
    bidder_id: "company-b",
  });
  expect(screen.getByLabelText("本次选择的投标主体")).toHaveValue("company-b");
});
it("没有真实默认公司时可保存独立待确认项目，不将占位名称转换为确认主体ID", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        return json({ id: "pending-bid" }, 201);
      }
      return url.includes("default-bidder")
        ? json({ bidder: null, authority_id: null }, 200, '"no-default"')
        : json(companies);
    }),
  );
  render(<CreateIdentityForm onCreated={vi.fn()} />);
  await screen.findByText(/当前主体待确认/);
  await user.type(screen.getByLabelText("项目名称"), "先整理资料");
  await user.click(screen.getByRole("button", { name: "创建并上传资料" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(JSON.parse(writes[0].body as string)).toEqual({ title: "先整理资料" });
});
it("有据纠正412保留选择和理由，读取影响并明确新基准后才重试；不重写旧记录", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  let head = 1;
  const saved = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        writes.push(options);
        if (writes.length === 1) {
          head = 2;
          return json(
            {
              code: "REVISION_CONFLICT",
              message: "项目已有更新",
              retryable: false,
              details: {},
            },
            412,
          );
        }
        return json({
          ...identity,
          historical_records_rewritten: false,
          qualification_recheck_required: true,
        });
      }
      if (url.includes("/identity/bidders")) return json(companies);
      if (url.includes("/identity/engineering-projects"))
        return json({ items: [], has_more: false });
      return json(identity, 200, `"bid-head-${head}"`);
    }),
  );
  render(<IdentityPanel bidId="bid" onSaved={saved} />);
  await user.click(
    await screen.findByRole("button", { name: "确认本项目投标主体" }),
  );
  await user.selectOptions(
    screen.getByLabelText("本次选择的投标主体"),
    "company-b",
  );
  await user.type(
    screen.getByLabelText("本次选择与纠正依据"),
    "已根据营业执照和本轮委托信息核对",
  );
  await user.click(screen.getByRole("button", { name: "确认本项目身份" }));
  await screen.findByText(/项目已更新，选择和理由保留/);
  expect(screen.getByLabelText("本次选择与纠正依据")).toHaveValue(
    "已根据营业执照和本轮委托信息核对",
  );
  expect(screen.getByRole("button", { name: "确认本项目身份" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "读取当前身份与影响" }));
  await user.click(
    await screen.findByRole("button", { name: "已核对当前身份，保留选择继续" }),
  );
  await user.click(screen.getByRole("button", { name: "确认本项目身份" }));
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(new Headers(writes[0].headers).get("If-Match")).toBe('"bid-head-1"');
  expect(new Headers(writes[1].headers).get("If-Match")).toBe('"bid-head-2"');
  expect(JSON.parse(writes[1].body as string)).toEqual({
    bidder_id: "company-b",
    reason: "已根据营业执照和本轮委托信息核对",
  });
  expect(screen.getByRole("status")).toHaveTextContent("受影响资格须重新核验");
});

it("目录加载后续轮次时保留工程绑定，已有轮次创建不误建新轮或要求手填编号", async () => {
  const user = userEvent.setup();
  const urls: string[] = [];
  const writes: RequestInit[] = [];
  const engineering = {
    id: "engineering",
    title: "完整工程名",
    region: "浙江",
    engineering_type: "市政",
  };
  const round = {
    id: "round-one",
    engineering_project_id: "engineering",
    lot: "一标段",
    round_no: 1,
    engineering_title: "完整工程名",
    region: "浙江",
    engineering_type: "市政",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      urls.push(url);
      if (options?.method === "POST") {
        writes.push(options);
        return json({ id: "new-round-workunit" }, 201);
      }
      if (url.includes("default-bidder"))
        return json(
          { bidder: companies.items[0], authority_id: "default" },
          200,
          '"default"',
        );
      if (url.includes("engineering-projects"))
        return json({
          items: [engineering],
          has_more: false,
          next_cursor: null,
        });
      if (url.includes("/identity/rounds"))
        return url.includes("cursor=")
          ? json({
              items: [{ ...round, id: "round-two", round_no: 2 }],
              has_more: false,
              next_cursor: null,
            })
          : json({
              items: [round],
              has_more: true,
              next_cursor: "round-signed-cursor",
            });
      return json(companies);
    }),
  );
  render(<CreateIdentityForm onCreated={vi.fn()} />);
  await user.type(screen.getByLabelText("项目名称"), "同轮另一主体资料");
  await user.click(
    screen.getByRole("checkbox", { name: "关联工程、标段或轮次（可选）" }),
  );
  await screen.findByRole("option", { name: /完整工程名 · 浙江 · 市政/ });
  await user.selectOptions(screen.getByLabelText("关联工程"), "engineering");
  await user.click(
    await screen.findByRole("button", { name: "加载更多标段与轮次" }),
  );
  await screen.findByRole("option", { name: /第2轮/ });
  await user.selectOptions(screen.getByLabelText("标段与轮次"), "round-two");
  await user.click(screen.getByRole("button", { name: "创建并上传资料" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(JSON.parse(writes[0].body as string)).toMatchObject({
    engineering_project_id: "engineering",
    round_id: "round-two",
    bidder_id: "company-a",
  });
  expect(urls).toContain(
    "/api/v1/identity/rounds?engineering_project_id=engineering&limit=100&cursor=round-signed-cursor",
  );
});

it("旧筛选的后续页迟到不混入新主体查询，也不覆盖当前加载状态", async () => {
  const user = userEvent.setup();
  let resolve: ((response: Response) => void) | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("default-bidder"))
        return json({ bidder: null, authority_id: null }, 200, '"default"');
      if (url.includes("cursor="))
        return new Promise<Response>((done) => {
          resolve = done;
        });
      if (new URL(url, window.location.href).searchParams.get("query"))
        return json({
          items: [companies.items[1]],
          has_more: false,
          next_cursor: null,
        });
      return json({
        items: [companies.items[0]],
        has_more: true,
        next_cursor: "old-filter-cursor",
      });
    }),
  );
  render(<CreateIdentityForm onCreated={vi.fn()} />);
  await user.click(
    await screen.findByRole("button", { name: "加载更多投标主体" }),
  );
  await waitFor(() => expect(resolve).toBeDefined());
  await user.type(screen.getByLabelText("查找完整公司名称"), "建设");
  await screen.findByRole("option", { name: "杭州甲工程建设有限公司" });
  await act(async () =>
    resolve!(
      json({
        items: [
          { ...companies.items[0], id: "old-late", name: "旧查询迟到公司" },
        ],
        has_more: false,
        next_cursor: null,
      }),
    ),
  );
  expect(
    screen.queryByRole("option", { name: "旧查询迟到公司" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "杭州甲工程有限公司" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "杭州甲工程建设有限公司" }),
  ).toBeInTheDocument();
});
