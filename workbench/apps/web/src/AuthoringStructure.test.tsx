import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { AuthoringStructure } from "./AuthoringStructure";
import type { AuthoringTreeView, AuthoringStructurePreview } from "./contracts";
import { treeOrder, initialPlan } from "./authoringStructureState";
const tree: AuthoringTreeView = {
  draft_id: "draft",
  draft_revision: 4,
  snapshot_id: "snap",
  structure_version_id: "tree",
  nodes: [
    {
      section_id: "a",
      parent_id: null,
      ordinal: 0,
      node_type: "chapter",
      deleted: false,
      section_revision: 2,
      plan_version_id: null,
      template_family_id: null,
      template_key: null,
      title: "人工章节",
      rule_ids: [],
      source_refs: [],
      plan: null,
      plan_content_basis_state: "none",
      actual_page_range: null,
    },
  ],
  directory_template_version_id: "directory",
  style_template_version_id: "style",
  metadata: {},
  page_budget: {
    planned_total: 0,
    unknown_section_ids: ["a"],
    actual_total: null,
    actual_ranges_state: "unknown",
  },
};
const preview: AuthoringStructurePreview = {
  action_id: "action",
  base_draft_revision: 4,
  created_ids: {},
  plan_suggestions: {},
  before: tree.nodes,
  after: [],
  before_sections: {
    a: { type: "doc", attrs: { title: "人工章节" }, content: [] },
  },
  after_sections: {},
  directory_template_version_id: "directory",
  style_template_version_id: "style",
  deletion_impact: [
    {
      section_id: "a",
      title: "人工章节",
      text_characters: 321,
      rule_ids: ["rule"],
      source_count: 2,
      plan_version_id: "plan",
    },
  ],
  format_report: null,
  expires_in_seconds: 300,
};
const props = {
  bidId: "bid",
  memberId: "member",
  draftId: "draft",
  draftRevision: 4,
  sectionId: "a",
  disabled: false,
  onChoose: vi.fn().mockResolvedValue(undefined),
  prepare: vi.fn().mockResolvedValue({
    data: {
      id: "draft",
      bid_id: "bid",
      revision: 4,
      snapshot_id: "snap",
      sections: [],
    },
    etag: '"actual-draft-4"',
  }),
  onChanged: vi.fn().mockResolvedValue(undefined),
  onBusy: vi.fn(),
};
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ETag: '"actual-draft-4"' },
  });
}
function reads(url: string) {
  if (url.endsWith("/materials")) return json({ documents: [], conflicts: [] });
  if (url.endsWith("/structure")) return json(tree);
  if (url.includes("/authoring/templates?"))
    return json({
      items: [],
      next_cursor: null,
      coverage: "partial",
      notice: "",
    });
  if (url.includes("/template-versions/"))
    return json({
      id: url.endsWith("style") ? "style" : "directory",
      name: "内置模板",
      kind: url.endsWith("style") ? "layout" : "outline",
      revision: 1,
      config: url.endsWith("style")
        ? {
            schema_version: 1,
            page: "A4",
            font: "Noto Sans CJK SC",
            font_size_halfpoints: 22,
            margin_top_twips: 1440,
            margin_right_twips: 1440,
            margin_bottom_twips: 1440,
            margin_left_twips: 1440,
            paragraph_after_twips: 0,
            cover_enabled: false,
            cover_title: "正文",
            header_text: "",
            footer_text: "",
            page_number: true,
            chapter_numbering: "decimal",
            toc_enabled: true,
          }
        : { schema_version: 1, nodes: [] },
      previous_version_id: null,
    });
  if (url.endsWith("/rules")) return json({ rules: [] });
  return json({ items: [], next_cursor: null });
}
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});
it("删除先显示完整影响，不直接写稿；一次明确应用使用原draft tag", async () => {
  const writes: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({ url, init });
        return url.endsWith("/resolve")
          ? json({
              state: "applied",
              action_id: "action",
              draft_id: "draft",
              draft_revision: 5,
              snapshot_id: "new",
              snapshot_digest: "a".repeat(64),
            })
          : json(preview, 201);
      }
      return reads(url);
    }),
  );
  render(<AuthoringStructure {...props} />);
  await userEvent.click(await screen.findByText("新增或调整章节目录"));
  await screen.findByRole("button", { name: "预览删除本章及子章" });
  await userEvent.click(
    screen.getByRole("button", { name: "预览删除本章及子章" }),
  );
  await screen.findByText(/321字/);
  expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0].init.body as string).changes).toEqual([
    { op: "delete", section_id: "a" },
  ]);
  await userEvent.click(screen.getByRole("button", { name: "应用这次变更" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(new Headers(writes[1].init.headers).get("If-Match")).toBe(
    '"actual-draft-4"',
  );
  expect(JSON.parse(writes[1].init.body as string)).toEqual({
    decision: "confirm",
  });
});
it("预览失响应后刷新只恢复相同body/key/tag，不按新head重建身份", async () => {
  const requests: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        requests.push(init);
        if (requests.length === 1) throw new TypeError("network lost");
        return json(preview, 201);
      }
      return reads(url);
    }),
  );
  const first = render(<AuthoringStructure {...props} />);
  await userEvent.click(await screen.findByText("新增或调整章节目录"));
  await userEvent.click(
    await screen.findByRole("button", { name: "预览删除本章及子章" }),
  );
  await screen.findByRole("button", { name: "恢复原目录预览结果" });
  first.unmount();
  render(<AuthoringStructure {...props} draftRevision={99} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原目录预览结果" }),
  );
  await screen.findByText(/321字/);
  expect(requests[0].body).toBe(requests[1].body);
  expect(new Headers(requests[0].headers).get("Idempotency-Key")).toBe(
    new Headers(requests[1].headers).get("Idempotency-Key"),
  );
  expect(new Headers(requests[1].headers).get("If-Match")).toBe(
    '"actual-draft-4"',
  );
});
it("412保留差异和删除影响，不能显示应用成功", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST")
        return url.endsWith("/resolve")
          ? json(
              {
                code: "PRECONDITION_FAILED",
                message: "原草稿已变化",
                retryable: false,
                details: null,
                request_id: "test",
              },
              412,
            )
          : json(preview, 201);
      return reads(url);
    }),
  );
  render(<AuthoringStructure {...props} />);
  await userEvent.click(await screen.findByText("新增或调整章节目录"));
  await userEvent.click(
    await screen.findByRole("button", { name: "预览删除本章及子章" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "应用这次变更" }),
  );
  await screen.findByText(/原预览不能覆盖当前稿/);
  expect(screen.getByText(/321字/)).toBeVisible();
  expect(props.onChanged).not.toHaveBeenCalled();
});
it("稳定ID按父级及ordinal排列；计划取plan revision，实际范围仍unknown", () => {
  const child = {
    ...tree.nodes[0],
    section_id: "child",
    parent_id: "a",
    ordinal: 0,
  };
  expect(
    treeOrder([child, ...tree.nodes]).map((x) => [x.node.section_id, x.depth]),
  ).toEqual([
    ["a", 0],
    ["child", 1],
  ]);
  expect(initialPlan(tree.nodes[0], 4)).toMatchObject({
    base_plan_revision: 0,
    base_draft_revision: 4,
    planned_pages: null,
    budget_basis: "manual",
  });
  expect(tree.nodes[0].actual_page_range).toBeNull();
});

it("版式未判明范围需服务器digest原样ACK，核对前不能显示可应用Action", async () => {
  const bodies: unknown[] = [];
  let previews = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/style-template/preview")) {
        bodies.push(JSON.parse(init!.body as string));
        previews++;
        return json(
          previews === 1
            ? {
                action_id: null,
                state: "requires_format_review",
                format_report: {
                  review_digest: "real-report-digest",
                  notice: "格式语义未自动核完",
                },
              }
            : preview,
          201,
        );
      }
      return reads(url);
    }),
  );
  render(<AuthoringStructure {...props} />);
  await userEvent.click(
    await screen.findByText("目录模板与版式模板 · 分别固定版本"),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "预览应用版式模板" }),
  );
  await screen.findByText("格式语义未自动核完");
  expect(
    screen.queryByRole("button", { name: "应用这次变更" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "已核对未判明范围，继续预览" }),
  );
  await screen.findByRole("button", { name: "应用这次变更" });
  expect(bodies[1]).toMatchObject({
    base_draft_revision: 4,
    style_template_version_id: "style",
    format_review_ack: "real-report-digest",
  });
});
