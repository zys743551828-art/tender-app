import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { AuthoringPlan } from "./AuthoringPlan";
import type { TreeNode } from "./authoringStructureState";
const node: TreeNode = {
  section_id: "section",
  parent_id: null,
  ordinal: 0,
  node_type: "chapter",
  deleted: false,
  section_revision: 10,
  plan_version_id: null,
  template_family_id: null,
  template_key: null,
  title: "施工",
  rule_ids: [],
  source_refs: [],
  plan: null,
  plan_content_basis_state: "none",
  actual_page_range: null,
};
const prepare = vi.fn().mockResolvedValue({
  data: {
    id: "draft",
    bid_id: "bid",
    revision: 11,
    snapshot_id: "snapshot",
    sections: [],
  },
  etag: '"draft-11"',
});
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status });
}
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});
it("人工预算保存走plan revision 0与draft11，不借section10冒充plan基准；空行不作事实", async () => {
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        writes.push(init);
        return json({
          draft_id: "draft",
          draft_revision: 12,
          plan: { section_id: "section", revision: 1 },
        });
      }
      if (url.endsWith("/rules")) return json({ rules: [] });
      if (url.endsWith("/materials")) return json({ documents: [] });
      return json({});
    }),
  );
  render(
    <AuthoringPlan
      bidId="bid"
      memberId="member"
      draftId="draft"
      node={node}
      draftRevision={10}
      disabled={false}
      prepare={prepare}
      onSaved={vi.fn().mockResolvedValue(undefined)}
    />,
  );
  await userEvent.click(screen.getByText("本章编写计划 · 施工"));
  await userEvent.type(screen.getByLabelText("人工计划页数"), "8");
  await userEvent.type(screen.getByLabelText("本章目标"), "人工目标");
  await userEvent.click(screen.getByRole("button", { name: "保存编写计划" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(JSON.parse(writes[0].body as string)).toMatchObject({
    base_draft_revision: 11,
    base_plan_revision: 0,
    planned_pages: 8,
    budget_basis: "manual",
    pending_facts: [],
  });
  expect(new Headers(writes[0].headers).get("If-Match")).toBe('"draft-11"');
  expect(screen.getByText("计划已保存；页数仍为预算。")).toBeVisible();
});
it("412不清人工目标；异步最新计划不会静默重写用户输入", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT")
        return json(
          {
            code: "AUTHORING_PLAN_CONFLICT",
            message: "计划已变化",
            details: null,
            request_id: "test",
            retryable: false,
          },
          412,
        );
      return json(url.endsWith("/rules") ? { rules: [] } : { documents: [] });
    }),
  );
  const props = {
    bidId: "bid",
    memberId: "member",
    draftId: "draft",
    node,
    draftRevision: 10,
    disabled: false,
    prepare,
    onSaved: vi.fn().mockResolvedValue(undefined),
  };
  const view = render(<AuthoringPlan {...props} />);
  await userEvent.click(screen.getByText("本章编写计划 · 施工"));
  await userEvent.type(screen.getByLabelText("本章目标"), "必须保留我的目标");
  await userEvent.click(screen.getByRole("button", { name: "保存编写计划" }));
  await screen.findByText(/计划或正文已有新版本/);
  view.rerender(<AuthoringPlan {...props} draftRevision={99} />);
  expect(screen.getByLabelText("本章目标")).toHaveValue("必须保留我的目标");
  expect(
    screen.queryByText("计划已保存；页数仍为预算。"),
  ).not.toBeInTheDocument();
});
