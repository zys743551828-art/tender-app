import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  RequirementCheckPlan,
  type CheckPlanValue,
} from "./RequirementCheckPlan";
import type {
  BidPackageStoredView,
  EvidenceView,
  RuleSetView,
} from "./contracts";

const scope = {
  bid_id: "bid",
  engineering_project_id: "project",
  lot_id: "lot",
  round_id: "round",
  bidder_id: "bidder",
  bidder_status: "confirmed" as const,
};
const own: BidPackageStoredView = {
  manifest: {
    package_id: "own",
    revision_id: "own-1",
    revision: 1,
    kind: "bid",
    scope,
    predecessor_digest: null,
    identity_version: "bid-package/1",
    members: [
      {
        member_id: "original",
        document_version_id: "own-doc",
        file_digest: "a".repeat(64),
        source_kind: "own",
        source_ref: "upload",
        scope,
        purposes: ["technical"],
        page_count: 2,
        parse: {
          status: "frozen",
          parse_run_id: "own-run",
          parser_digest: "b".repeat(64),
          config_digest: "c".repeat(64),
          evidence_digest: "d".repeat(64),
          reason: null,
        },
        parts: [
          {
            part_id: "技术正文",
            category: "technical",
            first_page: 1,
            last_page: 2,
            heading_path: [],
            shared_attachment: true,
          },
          {
            part_id: "商务共享附件",
            category: "business",
            first_page: 1,
            last_page: 2,
            heading_path: [],
            shared_attachment: true,
          },
        ],
      },
    ],
  },
  digest: "e".repeat(64),
  storage_eligible: true,
  review_ready: false,
  identity: {
    identity_version: "bid-identity/2",
    bidder_id: "bidder",
    bidder_name: "企业",
    round_id: "round",
    engineering_project_id: "project",
    engineering_title: "项目",
    region: null,
    engineering_type: null,
    lot: "一标段",
    lot_id: "lot",
    round_no: 1,
    binding_status: "confirmed",
    authority_id: "audit",
    digest: "f".repeat(64),
  },
};
const authority: BidPackageStoredView = {
  ...own,
  manifest: {
    ...own.manifest,
    package_id: "authority",
    revision_id: "authority-1",
    kind: "authority",
    members: own.manifest.members.map((m) => ({
      ...m,
      source_kind: "authority",
      document_version_id: "authority-doc",
      parse: { ...m.parse, parse_run_id: "authority-run" },
    })),
  },
};
const rules: RuleSetView = {
  id: "rule-set",
  bid_id: "bid",
  material_revision: 1,
  revision: 1,
  coverage: "partial",
  rules: [
    {
      id: "rule",
      rule_set_id: "rule-set",
      kind: "mandatory",
      statement: "原规则全文保持不变",
      conditions: ["合同时点要求"],
      exceptions: ["正式补遗另行约定"],
      maximum: null,
      evidence_ids: ["evidence"],
      confirmation: "pending",
      decision_revision: 0,
      carryover: null,
      scope: { bid_id: "bid", description: "本标段" },
      bands: [],
      origin_kind: "model_extracted",
      manual_origin_rule_id: null,
      provenance_status: "effective",
    },
  ],
};
const evidence: EvidenceView = {
  id: "evidence",
  document_version_id: "authority-doc",
  parse_run_id: "authority-run",
  physical_page: 1,
  printed_label: "3",
  kind: "text",
  quote: "权威原页完整原句",
  bbox: null,
  page_width: 400,
  page_height: 500,
  rotation: 0,
  source_status: "published",
};
const response = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
beforeEach(() => {
  vi.unstubAllGlobals();
});
function setup(evidenceValue: EvidenceView = evidence) {
  const fetcher = vi.fn(async (url: string) => {
    expect(url).toBe("/api/v1/evidence/evidence");
    return response(evidenceValue);
  });
  vi.stubGlobal("fetch", fetcher);
  const onChange = vi.fn<(value: CheckPlanValue) => void>();
  const props = {
    bidId: "bid",
    packageView: own,
    authorityView: authority,
    rules,
    disabled: false,
    onChange,
  };
  const ui = render(<RequirementCheckPlan {...props} />);
  return {
    fetcher,
    onChange,
    props,
    ui,
    last: () => onChange.mock.calls.at(-1)?.[0],
  };
}
async function enable() {
  await userEvent.click(screen.getByRole("checkbox", { name: "映射要求 1" }));
  await screen.findByText("权威原页完整原句");
}
async function fill() {
  await enable();
  await userEvent.click(
    screen.getByRole("checkbox", { name: /文件 1 · 分册 1/ }),
  );
  // These are whole form-value checks, not per-key behavior. Avoid leaving a
  // timed-out typing loop able to send its remaining keys to the next test.
  const reason = screen.getByLabelText("要求 1 人工映射理由（最多200字）");
  fireEvent.change(reason, { target: { value: "明确人工检查范围" } });
  expect(reason).toHaveValue("明确人工检查范围");
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: "要求 1 采用依据 1" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 采用依据 1" }),
  );
}

it("starts with no mappings and never fetches or silently selects evidence for unchecked rules", async () => {
  const w = setup();
  await waitFor(() =>
    expect(w.last()).toEqual({ mappings: [], valid: true, dirty: false }),
  );
  expect(w.fetcher).not.toHaveBeenCalled();
  expect(
    screen.getByRole("checkbox", { name: "映射要求 1" }),
  ).not.toBeChecked();
});
it("requires explicit target, reason and evidence even after a rule is enabled", async () => {
  const w = setup();
  await enable();
  await userEvent.click(
    screen.getByRole("checkbox", { name: /文件 1 · 分册 1/ }),
  );
  fireEvent.change(screen.getByLabelText("要求 1 人工映射理由（最多200字）"), {
    target: { value: "仅人工理由还不够" },
  });
  expect(
    screen.getByRole("checkbox", { name: "要求 1 采用依据 1" }),
  ).not.toBeChecked();
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(w.last()?.mappings).toEqual([]);
});
it("derives multiple categories from frozen shared parts and permits the same exact evidence once", async () => {
  const w = setup();
  const original = structuredClone(rules);
  await fill();
  await userEvent.click(
    screen.getByRole("checkbox", { name: /文件 1 · 分册 2/ }),
  );
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.mappings[0]).toMatchObject({
    categories: ["technical", "business"],
    target_part_ids: ["技术正文", "商务共享附件"],
    basis_evidence_ids: ["evidence"],
    minimum_count: null,
    applicability: "unknown",
  });
  expect(w.fetcher).toHaveBeenCalledTimes(1);
  expect(rules).toEqual(original);
  expect(w.last()).not.toHaveProperty("coverage");
});
it("preserves unknown as null and explicit zero as zero with quantity check", async () => {
  const w = setup();
  await fill();
  await waitFor(() => expect(w.last()?.mappings[0].minimum_count).toBeNull());
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 数量未知" }),
  );
  fireEvent.change(screen.getByLabelText("要求 1 最小数量"), {
    target: { value: "0" },
  });
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.mappings[0]).toMatchObject({
    minimum_count: 0,
    checks: ["quantity"],
  });
  expect(screen.getByRole("checkbox", { name: "数量逐项核对" })).toBeChecked();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 数量未知" }),
  );
  await waitFor(() => expect(w.last()?.mappings[0].minimum_count).toBeNull());
});
it.each(["-1", "9007199254740992"])(
  "rejects an unsafe or negative explicit quantity %s",
  async (value) => {
    const w = setup();
    await fill();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "要求 1 数量未知" }),
    );
    fireEvent.change(screen.getByLabelText("要求 1 最小数量"), {
      target: { value },
    });
    await waitFor(() => expect(w.last()?.valid).toBe(false));
  },
);
it("requires a separately chosen not-applicable basis even if the same evidence is already the plan basis", async () => {
  const w = setup();
  await fill();
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 适用性"),
    "not_applicable",
  );
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(
    screen.getByRole("checkbox", { name: "要求 1 不适用依据 1" }),
  ).not.toBeChecked();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 不适用依据 1" }),
  );
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.mappings[0].applicability_evidence_ids).toEqual([
    "evidence",
  ]);
});
it("does not truncate an overlong reason into an apparently valid declaration", async () => {
  const w = setup();
  await fill();
  const input = screen.getByLabelText("要求 1 人工映射理由（最多200字）");
  await userEvent.clear(input);
  await userEvent.paste("理".repeat(201));
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(input).toHaveValue("理".repeat(201));
});
it("rejects old parse, wrong document or out-of-range evidence without selecting a newer parse", async () => {
  for (const invalid of [
    { ...evidence, parse_run_id: "a-later-run" },
    { ...evidence, document_version_id: "wrong-doc" },
    { ...evidence, physical_page: 3 },
    { ...evidence, id: "wrong-evidence" },
  ]) {
    const w = setup(invalid);
    await userEvent.click(screen.getByRole("checkbox", { name: "映射要求 1" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "要求 1 采用依据 1" }),
    ).toBeDisabled();
    expect(w.last()?.valid).toBe(false);
    expect(w.fetcher).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("权威原页完整原句")).not.toBeInTheDocument();
    w.ui.unmount();
  }
});
it.each(["withdrawn", "candidate"] as const)(
  "blocks %s evidence instead of presenting it as currently usable",
  async (source_status) => {
    const w = setup({ ...evidence, source_status });
    await userEvent.click(screen.getByRole("checkbox", { name: "映射要求 1" }));
    await screen.findByText(
      source_status === "withdrawn"
        ? "引用已撤回，不可选用"
        : "引用尚未发布，不可选用",
    );
    expect(
      screen.getByRole("checkbox", { name: "要求 1 采用依据 1" }),
    ).toBeDisabled();
    expect(w.last()?.valid).toBe(false);
  },
);
it("disables editing without dropping an already entered mapping", async () => {
  const w = setup();
  await fill();
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  const saved = structuredClone(w.last());
  w.ui.rerender(<RequirementCheckPlan {...w.props} disabled />);
  expect(screen.getByRole("checkbox", { name: "映射要求 1" })).toBeDisabled();
  expect(
    screen.getByLabelText("要求 1 人工映射理由（最多200字）"),
  ).toBeDisabled();
  expect(w.last()).toEqual(saved);
});
it("discards late evidence response after the authority context changes and locks the original draft", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  const onChange = vi.fn<(value: CheckPlanValue) => void>();
  const props = {
    bidId: "bid",
    packageView: own,
    authorityView: authority,
    rules,
    disabled: false,
    onChange,
  };
  const ui = render(<RequirementCheckPlan {...props} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "映射要求 1" }));
  ui.rerender(
    <RequirementCheckPlan
      {...props}
      authorityView={{
        ...authority,
        manifest: { ...authority.manifest, revision_id: "authority-2" },
      }}
    />,
  );
  resolve(response(evidence));
  await waitFor(() =>
    expect(onChange.mock.calls.at(-1)?.[0]).toMatchObject({
      valid: false,
      dirty: true,
      mappings: [],
    }),
  );
  expect(screen.getByRole("checkbox", { name: "映射要求 1" })).toBeDisabled();
  expect(screen.queryByText("权威原页完整原句")).not.toBeInTheDocument();
});
it("invalidates rather than reusing a draft after original rule conditions change", async () => {
  const w = setup();
  await fill();
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  w.ui.rerender(
    <RequirementCheckPlan
      {...w.props}
      rules={{
        ...rules,
        rules: rules.rules.map((r) => ({ ...r, conditions: ["新版条件"] })),
      }}
    />,
  );
  await waitFor(() =>
    expect(w.last()).toEqual({ mappings: [], valid: false, dirty: true }),
  );
  expect(screen.getByLabelText("要求 1 人工映射理由（最多200字）")).toHaveValue(
    "明确人工检查范围",
  );
});
it("requires a real explicit-offset timestamp and retains blank as unknown", async () => {
  const w = setup();
  await fill();
  const at = screen.getByLabelText("要求 1 有效时点（可留空，填写须有时区）");
  fireEvent.change(at, { target: { value: "2026-10-19T08:00:00" } });
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  fireEvent.change(at, { target: { value: "2026-02-30T08:00:00+08:00" } });
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  fireEvent.change(at, { target: { value: "2026-10-19T08:00:00+08:00" } });
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.mappings[0].valid_at).toBe("2026-10-19T08:00:00+08:00");
});

it("restores an explicitly saved plan including zero, both evidence declarations and its original reason", async () => {
  const w = setup();
  w.ui.unmount();
  const saved: CheckPlanValue["mappings"] = [
    {
      rule_id: "rule",
      categories: ["technical"],
      target_part_ids: ["技术正文"],
      minimum_count: 0,
      applicability: "not_applicable",
      applicability_evidence_ids: ["evidence"],
      basis_evidence_ids: ["evidence"],
      reason: "原填写理由",
      valid_at: "2026-10-19T08:00:00+08:00",
      checks: ["quantity", "signature"],
    },
  ];
  render(<RequirementCheckPlan {...w.props} initialMappings={saved} />);
  expect(screen.getByRole("checkbox", { name: "映射要求 1" })).toBeChecked();
  expect(screen.getByLabelText("要求 1 最小数量")).toHaveValue("0");
  expect(screen.getByLabelText("要求 1 人工映射理由（最多200字）")).toHaveValue(
    "原填写理由",
  );
  expect(
    screen.getByRole("checkbox", { name: "要求 1 不适用依据 1" }),
  ).toBeChecked();
  await waitFor(() =>
    expect(w.last()).toEqual({ mappings: saved, valid: true, dirty: true }),
  );
});

it("keeps an invalid restored category/part binding locked instead of silently assigning a new target", async () => {
  const w = setup();
  w.ui.unmount();
  const saved: CheckPlanValue["mappings"] = [
    {
      rule_id: "rule",
      categories: ["business"],
      target_part_ids: ["技术正文"],
      minimum_count: null,
      applicability: "unknown",
      applicability_evidence_ids: [],
      basis_evidence_ids: ["evidence"],
      reason: "保留原计划待核",
      valid_at: null,
      checks: [],
    },
  ];
  render(<RequirementCheckPlan {...w.props} initialMappings={saved} />);
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(screen.getByRole("checkbox", { name: "映射要求 1" })).toBeDisabled();
  expect(screen.getByLabelText("要求 1 人工映射理由（最多200字）")).toHaveValue(
    "保留原计划待核",
  );
});
