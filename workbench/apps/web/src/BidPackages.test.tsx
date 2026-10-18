import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { BidPackages } from "./BidPackages";
import type { BidPackageDocument, BidPackageStoredView } from "./contracts";

// Contract fixtures only; real nonowner HTTP/DB evidence lives in test_bid_package_api.py.
const document: BidPackageDocument = {
  id: "doc",
  bid_id: "bid",
  file_id: "file",
  file_revision: 1,
  filename: "技术册.pdf",
  role: "body",
  artifact_kind: "bid_body",
  sha256: "a".repeat(64),
  verified_upload: true,
};
const scope = {
  engineering_project_id: "engineering",
  lot_id: "lot",
  round_id: "round",
  bid_id: "bid",
  bidder_id: "bidder",
  bidder_status: "confirmed" as const,
};
const frozen: BidPackageStoredView = {
  manifest: {
    package_id: "package",
    revision_id: "revision-1",
    revision: 1,
    kind: "bid",
    identity_version: "bid-package/1",
    scope,
    predecessor_digest: null,
    members: [
      {
        member_id: "member",
        document_version_id: "doc",
        file_digest: "a".repeat(64),
        source_kind: "own",
        source_ref: "file:1",
        scope,
        purposes: ["技术"],
        page_count: 2,
        parse: {
          status: "frozen",
          parse_run_id: "run-explicit",
          parser_digest: "b".repeat(64),
          config_digest: "c".repeat(64),
          evidence_digest: "d".repeat(64),
          reason: null,
        },
        parts: [
          {
            part_id: "technical",
            category: "技术",
            first_page: 1,
            last_page: 2,
            shared_attachment: false,
            heading_path: [],
          },
        ],
      },
    ],
  },
  digest: "e".repeat(64),
  identity: {
    identity_version: "bid-identity/2",
    bidder_id: "bidder",
    bidder_name: "本方企业",
    round_id: "round",
    engineering_project_id: "engineering",
    engineering_title: "项目",
    lot_id: "lot",
    lot: "一标段",
    round_no: 1,
    binding_status: "confirmed",
    authority_id: "audit",
    digest: "f".repeat(64),
    region: null,
    engineering_type: null,
  },
  storage_eligible: true,
  review_ready: false,
};
const parses = [
  {
    id: "run-explicit",
    document_version_id: "doc",
    coverage: "complete",
    page_count: 2,
    gaps: [],
    parser_digest: "b".repeat(64),
    config_digest: "c".repeat(64),
    created_at: "2026-10-01T00:00:00Z",
  },
  {
    id: "run-failed",
    document_version_id: "doc",
    coverage: "failed",
    page_count: 0,
    gaps: ["无法解析"],
    parser_digest: "b".repeat(64),
    config_digest: "c".repeat(64),
    created_at: "2026-10-02T00:00:00Z",
  },
];
const page = (items: unknown[]) => ({
  items,
  has_more: false,
  next_cursor: null,
});
const json = (value: unknown, etag?: string, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: etag ? { ETag: etag } : {},
  });
type Handler = (
  url: string,
  options?: RequestInit,
) => Response | undefined | Promise<Response | undefined>;
function install(handler?: Handler, existing = false) {
  const writes: { url: string; body: unknown; headers: Headers }[] = [];
  const requests: string[] = [];
  const fetcher = vi.fn(async (input: string, options?: RequestInit) => {
    const url = String(input);
    requests.push(url);
    if (options?.method === "POST")
      writes.push({
        url,
        body: JSON.parse(String(options.body)),
        headers: new Headers(options.headers),
      });
    const handled = await handler?.(url, options);
    if (handled) return handled;
    if (url.includes("/package-documents/doc/parses"))
      return json(page(parses));
    if (url.includes("/package-documents")) return json(page([document]));
    if (url.endsWith("/revisions?limit=20"))
      return json(
        page([
          {
            id: "revision-1",
            package_id: "package",
            revision: 1,
            digest: frozen.digest,
            created_at: "2026-10-01T00:00:00Z",
          },
        ]),
      );
    if (
      url.endsWith("/packages/package") ||
      url.endsWith("/revisions/revision-1")
    )
      return json(frozen, '"head:1"');
    if (options?.method === "POST") return json(frozen, '"head:1"', 201);
    if (url.includes("/packages?"))
      return json(
        page(
          existing
            ? [
                {
                  id: "package",
                  bid_id: "bid",
                  kind: "bid",
                  revision_id: "revision-1",
                  revision: 1,
                  digest: frozen.digest,
                },
              ]
            : [],
        ),
      );
    return json(page([]));
  });
  vi.stubGlobal("fetch", fetcher);
  return { writes, requests, fetcher };
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

it("未明确选解析时保存未知原件，多用途逗号输入保留，未接正式评审", async () => {
  const user = userEvent.setup();
  const { writes } = install();
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  const purposes = screen.getByRole("combobox", { name: "用途 doc" });
  await user.clear(purposes);
  await user.type(purposes, "资格,商务,自定义");
  expect(purposes).toHaveValue("资格,商务,自定义");
  expect(screen.getByRole("combobox", { name: "解析记录 doc" })).toHaveValue(
    "",
  );
  expect(
    screen.getByRole("button", { name: "添加明确逻辑范围" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body).toEqual({
    kind: "bid",
    members: [
      {
        member_id: "document-doc",
        document_version_id: "doc",
        purposes: ["资格", "商务", "自定义"],
        parts: [],
      },
    ],
  });
  expect(screen.getByText("尚未接入正式评审")).toBeInTheDocument();
});

it("用户明确选精确解析后添加物理页范围，失败解析不能选且不推断摘要", async () => {
  const user = userEvent.setup();
  const { writes } = install();
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: /失败，不可冻结/ }),
    ).toBeDisabled(),
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "解析记录 doc" }),
    "run-explicit",
  );
  await user.click(screen.getByRole("button", { name: "添加明确逻辑范围" }));
  await user.clear(screen.getByRole("spinbutton", { name: "结束页 doc 0" }));
  await user.type(
    screen.getByRole("spinbutton", { name: "结束页 doc 0" }),
    "2",
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body).toMatchObject({
    kind: "bid",
    members: [
      {
        parse_run_id: "run-explicit",
        parts: [{ category: "技术", first_page: 1, last_page: 2 }],
      },
    ],
  });
  expect(JSON.stringify(writes[0].body)).not.toContain("file_digest");
  expect(JSON.stringify(writes[0].body)).not.toContain("scope");
});

it("分页查找包、文件和解析记录，不把当前资料当作全部版本", async () => {
  const user = userEvent.setup();
  const { requests } = install((url) => {
    if (url.includes("cursor=")) return json(page([]));
    if (url.includes("/packages?"))
      return json({
        ...page([]),
        has_more: true,
        next_cursor: "package:cursor",
      });
    if (url.includes("/package-documents/doc/parses"))
      return json({
        ...page(parses),
        has_more: true,
        next_cursor: "parse:cursor",
      });
    if (url.includes("/package-documents?"))
      return json({
        ...page([document]),
        has_more: true,
        next_cursor: "document:cursor",
      });
  });
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("button", { name: "加载更多资料包" }),
  );
  await user.click(screen.getByRole("button", { name: "加载更多文件版本" }));
  await user.click(
    screen.getByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "加载更多解析记录" }),
  );
  expect(requests).toContain(
    "/api/v1/bids/bid/packages?kind=bid&limit=20&cursor=package%3Acursor",
  );
  expect(requests).toContain(
    "/api/v1/bids/bid/package-documents?kind=bid&limit=20&cursor=document%3Acursor",
  );
  expect(requests).toContain(
    "/api/v1/bids/bid/package-documents/doc/parses?limit=20&cursor=parse%3Acursor",
  );
});

it("历史查看不写入，编辑明确重读当前head并带If-Match", async () => {
  const user = userEvent.setup();
  const { writes, requests } = install(undefined, true);
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("button", { name: "查看资料包 package" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "查看历史修订 1" }),
  );
  expect(
    await screen.findByRole("heading", { name: "历史冻结记录 · 修订 1" }),
  ).toBeInTheDocument();
  expect(writes).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "基于当前修订编辑" }));
  expect(
    await screen.findByRole("button", { name: "保存新修订" }),
  ).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "保存新修订" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(
    requests.filter((r) => r.endsWith("/packages/package")).length,
  ).toBeGreaterThanOrEqual(2);
  expect(writes[0].url).toBe("/api/v1/bids/bid/packages/package/revisions");
  expect(writes[0].headers.get("If-Match")).toBe('"head:1"');
});

it("CAS冲突保留本地选择，读取核对最新记录后才允许继续，绝不自动重试", async () => {
  const user = userEvent.setup();
  let current = frozen;
  const { writes } = install((url, options) => {
    if (options?.method === "POST") {
      current = {
        ...frozen,
        digest: "newdigest",
        manifest: {
          ...frozen.manifest,
          revision: 2,
          revision_id: "revision-2",
        },
      };
      return json(
        {
          code: "REVISION_CONFLICT",
          message: "其他人已更新",
          retryable: false,
        },
        undefined,
        412,
      );
    }
    if (url.endsWith("/packages/package"))
      return json(current, current === frozen ? '"head:1"' : '"head:2"');
  }, true);
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("button", { name: "查看资料包 package" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "基于当前修订编辑" }),
  );
  const purposes = await screen.findByRole("combobox", { name: "用途 doc" });
  await user.clear(purposes);
  await user.type(purposes, "商务,资格");
  await user.click(screen.getByRole("button", { name: "保存新修订" }));
  await screen.findByText("资料包已有更新。本地选择保留，未自动覆盖或重试。");
  expect(purposes).toHaveValue("商务,资格");
  expect(writes).toHaveLength(1);
  expect(screen.getByRole("button", { name: "保存新修订" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "读取最新修订，保留本地选择" }),
  );
  const confirm = await screen.findByRole("button", {
    name: "已核对最新修订 2，以此版本继续",
  });
  await waitFor(() => expect(confirm).toBeEnabled());
  expect(writes).toHaveLength(1);
  await user.click(confirm);
  expect(screen.getByRole("button", { name: "保存新修订" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "保存新修订" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].headers.get("If-Match")).toBe('"head:2"');
});

it("切换类型使用独立目录，跨项目文档不显示，项目切换清空本地草稿", async () => {
  const user = userEvent.setup();
  const { requests } = install((url) => {
    if (url.includes("/other/"))
      return json(page([{ ...document, bid_id: "bid" }]));
    if (url.includes("package-documents?kind=authority"))
      return json(
        page([
          {
            ...document,
            role: "tender",
            artifact_kind: "source_original",
            filename: "招标文件.pdf",
          },
        ]),
      );
  });
  const { rerender } = render(<BidPackages bidId="bid" />);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "资料包类型" }),
    "authority",
  );
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 招标文件.pdf 版本 1" }),
  );
  expect(screen.getByRole("combobox", { name: "用途 doc" })).toHaveValue(
    "要求依据",
  );
  expect(requests).toContain(
    "/api/v1/bids/bid/package-documents?kind=authority&limit=20",
  );
  rerender(<BidPackages bidId="other" />);
  await waitFor(() =>
    expect(
      screen.queryByRole("combobox", { name: "用途 doc" }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("checkbox", { name: /选择 技术册/ }),
  ).not.toBeInTheDocument();
});

it("网络结果不明时保留选择，用户重试沿用原幂等键", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST" && attempts++ === 0)
      throw new TypeError("synthetic uncertain response");
    return undefined;
  });
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await screen.findByText(/暂时无法连接服务/);
  expect(
    screen.getByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  ).toBeChecked();
  expect(writes).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "核对并重试原保存" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[0].headers.get("Idempotency-Key")).toBe(
    writes[1].headers.get("Idempotency-Key"),
  );
  expect(writes[0].body).toEqual(writes[1].body);
});

it("切项目后旧保存响应不写进新项目工作区，旧资料仍由服务端目录可发现", async () => {
  const user = userEvent.setup();
  let resolve: ((value: Response) => void) | undefined;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST")
      return new Promise<Response>((done) => {
        resolve = done;
      });
  });
  const { rerender } = render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  rerender(<BidPackages bidId="other" />);
  resolve?.(json(frozen, '"head:1"', 201));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存新资料包" })).toBeDisabled(),
  );
  expect(screen.queryByText(/已保存修订/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: /历史冻结记录/ }),
  ).not.toBeInTheDocument();
});

it("未决A操作冻结body和key，无法编辑B覆盖；刷新恢复A原操作再核对", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST" && attempts++ === 0)
      throw new TypeError("synthetic lost ACK");
    return undefined;
  });
  const { unmount } = render(<BidPackages bidId="bid" memberId="actor" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await screen.findByText(/暂时无法连接服务/);
  const purposes = screen.getByRole("combobox", { name: "用途 doc" });
  expect(purposes).toBeDisabled();
  await user.type(purposes, "报价");
  expect(purposes).toHaveValue("技术");
  expect(screen.getByRole("button", { name: "清空选择并新建" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "资料包类型" })).toBeDisabled();
  expect(writes).toHaveLength(1);
  const original = JSON.parse(
    sessionStorage.getItem("tender:package-pending:actor:bid")!,
  );
  expect(original.body).toEqual(writes[0].body);
  unmount();
  render(<BidPackages bidId="bid" memberId="actor" />);
  expect(screen.getByRole("combobox", { name: "用途 doc" })).toHaveValue(
    "技术",
  );
  await user.click(screen.getByRole("button", { name: "核对并重试原保存" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
  await waitFor(() =>
    expect(
      sessionStorage.getItem("tender:package-pending:actor:bid"),
    ).toBeNull(),
  );
});

it("追加修订丢ACK后刷新保留原If-Match，新head不自动覆盖未决基线", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST" && attempts++ === 0)
      throw new TypeError("synthetic lost ACK");
    return undefined;
  }, true);
  const { unmount } = render(<BidPackages bidId="bid" memberId="actor" />);
  await user.click(
    await screen.findByRole("button", { name: "查看资料包 package" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "基于当前修订编辑" }),
  );
  await user.click(await screen.findByRole("button", { name: "保存新修订" }));
  await screen.findByText(/暂时无法连接服务/);
  unmount();
  render(<BidPackages bidId="bid" memberId="actor" />);
  await user.click(screen.getByRole("button", { name: "核对并重试原保存" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].url).toBe(writes[0].url);
  expect(writes[1].headers.get("If-Match")).toBe('"head:1"');
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
});

it("未决操作按成员隔离，503不能假装原操作未提交", async () => {
  const user = userEvent.setup();
  const { writes } = install((_url, options) =>
    options?.method === "POST"
      ? json(
          {
            code: "DATABASE_TRANSACTION_FAILED",
            message: "暂不可用",
            retryable: true,
          },
          undefined,
          503,
        )
      : undefined,
  );
  const { rerender } = render(<BidPackages bidId="bid" memberId="actor-A" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await screen.findByText("暂不可用");
  expect(screen.getByRole("button", { name: "清空选择并新建" })).toBeDisabled();
  rerender(<BidPackages bidId="bid" memberId="actor-B" />);
  expect(
    screen.queryByRole("button", { name: "核对并重试原保存" }),
  ).not.toBeInTheDocument();
  rerender(<BidPackages bidId="bid" memberId="actor-A" />);
  expect(
    screen.getByRole("button", { name: "核对并重试原保存" }),
  ).toBeEnabled();
  expect(writes).toHaveLength(1);
});

it("未知结果重试遇登录失效仍保留原命令，不解除编辑锁", async () => {
  const user = userEvent.setup();
  let attempts = 0;
  const { writes } = install((_url, options) => {
    if (options?.method !== "POST") return undefined;
    if (attempts++ === 0) throw new TypeError("synthetic lost ACK");
    return json(
      { code: "SESSION_EXPIRED", message: "请重新登录", retryable: false },
      undefined,
      401,
    );
  });
  render(<BidPackages bidId="bid" memberId="actor" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  await user.click(screen.getByRole("button", { name: "保存新资料包" }));
  await screen.findByText(/暂时无法连接服务/);
  await user.click(screen.getByRole("button", { name: "核对并重试原保存" }));
  await screen.findByText("请重新登录");
  expect(screen.getByRole("combobox", { name: "用途 doc" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "清空选择并新建" })).toBeDisabled();
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
  expect(
    sessionStorage.getItem("tender:package-pending:actor:bid"),
  ).not.toBeNull();
});

it("不能持久化原命令时不发送请求，避免刷新丢失未决身份", async () => {
  const user = userEvent.setup();
  const { writes } = install();
  render(<BidPackages bidId="bid" />);
  await user.click(
    await screen.findByRole("checkbox", { name: "选择 技术册.pdf 版本 1" }),
  );
  const storage = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementationOnce(() => {
      throw new Error("synthetic quota failure");
    });
  try {
    await user.click(screen.getByRole("button", { name: "保存新资料包" }));
    await screen.findByText(/无法保存本地待核操作，请求尚未发送/);
    expect(writes).toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存新资料包" })).toBeEnabled();
  } finally {
    storage.mockRestore();
  }
});
