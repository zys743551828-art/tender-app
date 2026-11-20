import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type {
  AuthoringTreeView,
  BidPackageStoredView,
  PackageRequirementInventoryView,
} from "./contracts";
import { TechnicalDraftTrace } from "./TechnicalDraftTrace";
import {
  frozenOutlineAuthority,
  technicalDraftTrace,
} from "./technicalDraftTraceModel";

const id = (i: number) =>
  "12345678-4321-4432-8234-" + String(i).padStart(12, "0");
const authority = {
  manifest: {
    members: [
      {
        document_version_id: id(4),
        parse: { status: "frozen", parse_run_id: id(5) },
      },
      {
        document_version_id: id(6),
        parse: { status: "not_frozen", parse_run_id: null },
      },
      {
        document_version_id: id(7),
        parse: { status: "frozen", parse_run_id: id(8) },
      },
    ],
  },
} as BidPackageStoredView;
const inventory = {
  manifest: { revision: 5 },
} as PackageRequirementInventoryView;
const dates = {
  ruleId: id(30),
  statement: "补遗将计划施工日期改为 12 月 10 日至次年 7 月 7 日（合成样例）",
  evidenceIds: [id(31)],
  suggested: ["schedule" as const],
};
const duration = {
  ruleId: id(40),
  statement: "工期仍为 210 个日历天（合成）",
  evidenceIds: [id(41)],
  suggested: ["schedule" as const],
};
const safety = {
  ruleId: id(50),
  statement: "补充安全资料（合成）",
  evidenceIds: [id(51)],
  suggested: [],
};
const scope = frozenOutlineAuthority(authority);
const outline = {
  rows: [dates, duration, safety],
  chapters: [
    { key: "schedule" as const, title: "施工进度与资源配置" as const },
  ],
  pending: 1,
};
const ref = (evidence: number, doc = 4) => ({
  source_id: id(90),
  source_revision: 2,
  evidence_id: id(evidence),
  document_version_id: id(doc),
});
const chapter = (
  identity: number,
  options: Partial<AuthoringTreeView["nodes"][number]> = {},
) =>
  ({
    section_id: id(identity),
    parent_id: null,
    ordinal: identity,
    node_type: "chapter",
    title: "施工进度安排（含未更新的计划日期及不变的 210 天）",
    deleted: false,
    section_revision: 3,
    plan_version_id: null,
    template_family_id: null,
    template_key: null,
    rule_ids: [],
    source_refs: [],
    plan: null,
    plan_content_basis_state: "none",
    actual_page_range: null,
    ...options,
  }) satisfies AuthoringTreeView["nodes"][number];
const tree = (nodes: AuthoringTreeView["nodes"]) =>
  ({
    draft_id: id(2),
    draft_revision: 9,
    snapshot_id: id(3),
    nodes,
  }) as AuthoringTreeView;
const oldPlan = {
  id: id(60),
  bid_id: id(1),
  draft_id: id(2),
  section_id: id(20),
  revision: 1,
  base_section_revision: 2,
  state: "ready" as const,
  planned_pages: null,
  digest: "e".repeat(64),
  created_by: id(1),
  created_at: "2026-10-21T00:00:00Z",
  payload: { rule_ids: [dates.ruleId], source_refs: [ref(31)] },
};

it("keeps old construction dates unresolved even when 210-day duration and bid deadline have evidence", () => {
  const savedTree = tree([
    chapter(10, {
      rule_ids: [dates.ruleId, duration.ruleId, id(42)],
      // 32: superseded construction dates; 41: unchanged duration; 43: submission deadline.
      source_refs: [ref(32, 7), ref(41), ref(43), ref(31, 99)],
    }),
    chapter(20, {
      plan: oldPlan,
      plan_version_id: oldPlan.id,
      plan_content_basis_state: "section_changed",
    }),
    chapter(21, {
      deleted: true,
      rule_ids: [safety.ruleId],
      source_refs: [ref(51)],
    }),
  ]);
  const [changed, same, none] = technicalDraftTrace(
    id(1),
    savedTree,
    outline.rows,
    scope,
  );
  expect(changed.state).toBe("check_reference");
  expect(
    changed.chapters.map((entry) => [entry.origins, entry.evidenceIds]),
  ).toEqual([
    [["body"], []],
    [["old_plan"], []],
  ]);
  expect(same.state).toBe("matched_reference");
  expect(same.chapters[0].evidenceIds).toEqual([id(41)]);
  expect(none).toMatchObject({ state: "unlinked", chapters: [] });
});

it("does not borrow references from an unrelated plan, or treat an older revision as current", () => {
  const savedTree = tree([
    chapter(18, {
      rule_ids: [dates.ruleId],
      plan_version_id: oldPlan.id,
      plan_content_basis_state: "current",
      plan: {
        ...oldPlan,
        section_id: id(18),
        base_section_revision: 3,
        payload: {
          rule_ids: [duration.ruleId],
          source_refs: [ref(31)],
        },
      },
    }),
    chapter(20, {
      plan: oldPlan,
      plan_version_id: oldPlan.id,
      plan_content_basis_state: "current",
    }),
    chapter(22, {
      plan: { ...oldPlan, bid_id: id(99) },
      plan_version_id: oldPlan.id,
      plan_content_basis_state: "current",
    }),
  ]);
  const rows = technicalDraftTrace(id(1), savedTree, outline.rows, scope);
  expect(rows[0].state).toBe("check_reference");
  expect(
    rows[0].chapters.map(({ sectionId, origins, evidenceIds }) => [
      sectionId,
      origins,
      evidenceIds,
    ]),
  ).toEqual([
    [id(18), ["body"], []],
    [id(20), ["old_plan"], []],
  ]);
  expect(rows[1].state).toBe("check_reference");
  expect(
    technicalDraftTrace(id(1), tree([savedTree.nodes[1]]), [dates], scope)[0]
      .state,
  ).toBe("old_plan");
});

it("uses an exact chapter and denies a same-document evidence response from a foreign parse", async () => {
  const onOpenSection = vi.fn().mockResolvedValue(undefined);
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        id: id(31),
        document_version_id: id(4),
        parse_run_id: id(900),
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  try {
    const props = {
      inventory,
      authority,
      outline: { ...outline, rows: [dates] },
      bidId: id(1),
      navigationDisabled: false,
      onOpenSection,
    };
    const { rerender } = render(
      <TechnicalDraftTrace
        {...props}
        tree={tree([
          chapter(10, { rule_ids: [dates.ruleId], source_refs: [ref(31)] }),
        ])}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByText(/技术要求与已存章节对照/));
    expect(screen.getByText(/保存引用与要求原页身份相符/)).toBeInTheDocument();
    expect(screen.getByText(/不能当作覆盖率或审批/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /定位章节/ }));
    expect(onOpenSection).toHaveBeenCalledWith(id(10));
    expect(fetch).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /查看引用原页/ }));
    expect(
      await screen.findByText(/不属于所选依据包的固定文件和解析/),
    ).toBeInTheDocument();
    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/evidence/" + id(31),
    ]);
    rerender(<TechnicalDraftTrace {...props} tree={null} />);
    expect(screen.getByText(/暂不展示章节关联或引用结论/)).toBeInTheDocument();
    expect(
      screen.queryByText(/保存引用与要求原页身份相符/),
    ).not.toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
  }
});
