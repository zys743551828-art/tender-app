import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CoverageEditor, type CoverageEditorValue } from "./CoverageEditor";
import type {
  BidPackageStoredView,
  EvidenceView,
  PackageRequirementInventoryView,
} from "./contracts";
import type { ComponentProps } from "react";

// UI protocol fixtures; nonowner SQL and ASGI are independently verified.
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
        member_id: "body",
        document_version_id: "own-doc",
        file_digest: "a".repeat(64),
        source_kind: "own",
        source_ref: "file:1",
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
            part_id: "tech",
            category: "technical",
            first_page: 1,
            last_page: 2,
            heading_path: [],
            shared_attachment: false,
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
    lot: "一标",
    lot_id: "lot",
    round_no: 1,
    binding_status: "confirmed",
    authority_id: "audit",
    digest: "f".repeat(64),
  },
};
const authority: BidPackageStoredView = {
  ...own,
  digest: "1".repeat(64),
  manifest: {
    ...own.manifest,
    kind: "authority",
    package_id: "authority",
    revision_id: "authority-1",
    members: own.manifest.members.map((m) => ({
      ...m,
      source_kind: "authority",
      document_version_id: "authority-doc",
      parse: { ...m.parse, parse_run_id: "authority-run" },
      parts: m.parts.map((p) => ({ ...p, part_id: "authority-part" })),
    })),
  },
};
const inventory: PackageRequirementInventoryView = {
  digest: "2".repeat(64),
  manifest: {
    version: "bid-package-requirements/1",
    id: "inventory",
    bid_id: "bid",
    package_id: "own",
    target_revision_id: "own-1",
    package_digest: own.digest,
    authority_revision_id: "authority-1",
    authority_digest: authority.digest,
    rule_set_id: "rule-set",
    rule_set_digest: "3".repeat(64),
    revision: 1,
    predecessor_digest: null,
    identity_digest: own.identity.digest,
    source_snapshot: [],
    inventory_complete: false,
    extraction_binding: "unproven_legacy_rule_set",
    review_ready: false,
    actor_id: "actor",
    requirements: [
      {
        rule_id: "rule",
        rule_digest: "4".repeat(64),
        rule_snapshot: {
          statement: "原规则需要明确检查本方范围",
          provenance_status: "effective",
        },
        decision_id: "decision",
        decision_snapshot: { decision: "confirmed" },
        requirement: {
          requirement_id: "rule",
          scope,
          origin: "authority",
          source_refs: ["rule:original"],
          categories: ["technical"],
          target_part_ids: ["tech"],
          minimum_count: null,
          applicability: "applicable",
          applicability_evidence: [],
          valid_at: null,
          conditions: [],
          checks: [],
          identity_version: "bid-requirement/1",
        },
        requirement_digest: "5".repeat(64),
        source_bound: true,
        annotation: {
          kind: "human_check_plan_declaration",
          mapped: true,
          reason: "检查计划",
          basis_evidence_ids: ["authority-e"],
        },
      },
    ],
  },
};
const ownEvidence: EvidenceView = {
  id: "own-e",
  document_version_id: "own-doc",
  parse_run_id: "own-run",
  physical_page: 1,
  printed_label: null,
  kind: "text",
  quote: "本方冻结原句",
  bbox: null,
  page_width: 400,
  page_height: 500,
  rotation: 0,
  source_status: "published",
};
const authorityEvidence: EvidenceView = {
  ...ownEvidence,
  id: "authority-e",
  document_version_id: "authority-doc",
  parse_run_id: "authority-run",
  quote: "权威依据冻结原句",
};
const ownPath =
  "/api/v1/bids/bid/packages/own/revisions/own-1/evidence?limit=20";
const authorityPath =
  "/api/v1/bids/bid/packages/authority/revisions/authority-1/evidence?limit=20";
const entry = (value: EvidenceView, part = "tech") => ({
  id: value.id,
  document_version_id: value.document_version_id,
  parse_run_id: value.parse_run_id,
  physical_page: value.physical_page,
  part_ids: [part],
});
const page = (view: BidPackageStoredView, items: unknown[]) => ({
  revision_id: view.manifest.revision_id,
  package_digest: view.digest,
  items,
  has_more: false,
  next_cursor: null,
});
const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
type Handler = (
  url: string,
) => Response | undefined | Promise<Response | undefined>;
beforeEach(() => vi.unstubAllGlobals());
function setup(
  overrides: Partial<ComponentProps<typeof CoverageEditor>> = {},
  handler?: Handler,
) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.method ?? "GET").toBe("GET");
    const custom = await handler?.(url);
    if (custom) return custom;
    if (url === ownPath) return json(page(own, [entry(ownEvidence)]));
    if (url === authorityPath)
      return json(
        page(authority, [entry(authorityEvidence, "authority-part")]),
      );
    if (url === "/api/v1/evidence/own-e") return json(ownEvidence);
    if (url === "/api/v1/evidence/authority-e") return json(authorityEvidence);
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const onChange = vi.fn<(value: CoverageEditorValue) => void>();
  const props = {
    bidId: "bid",
    packageView: own,
    authorityView: authority,
    inventory,
    disabled: false,
    onChange,
    ...overrides,
  };
  const ui = render(<CoverageEditor {...props} />);
  return {
    props,
    ui,
    fetcher,
    onChange,
    last: () => onChange.mock.calls.at(-1)?.[0],
  };
}
async function enable(n = 1) {
  await userEvent.click(
    screen.getByRole("checkbox", { name: `纳入本次要求 ${n}` }),
  );
}
async function reason(n = 1) {
  await userEvent.type(
    screen.getByLabelText(`要求 ${n} 理由（最多200字）`),
    "明确人工观察与检查理由",
  );
}
async function range(first = "1", last = "2") {
  await userEvent.click(
    screen.getByRole("checkbox", { name: /要求 1 文件 1 · 分册 1/ }),
  );
  await userEvent.type(
    screen.getByLabelText("要求 1 文件 1 分册 1 起始物理页"),
    first,
  );
  await userEvent.type(
    screen.getByLabelText("要求 1 文件 1 分册 1 结束物理页"),
    last,
  );
}
async function chooseOwn() {
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取证据 1 原句" }),
  );
  await screen.findByText("本方冻结原句");
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  );
}
async function confirmed() {
  await userEvent.click(
    screen.getByRole("checkbox", { name: /我明确声明已人工检查本次全部目标/ }),
  );
}
function initialVerified(): CoverageEditorValue["results"] {
  return [
    {
      rule_id: "rule",
      requirement_digest: "5".repeat(64),
      state: "verified",
      reason: "原人工记录",
      basis_type: "human_scope_declaration",
      inspected: [{ part_id: "tech", first_page: 1, last_page: 2 }],
      evidence_ids: ["own-e"],
    },
  ];
}

it("starts omitted and unknown without requesting all quotes or producing coverage automatically", async () => {
  const w = setup();
  await waitFor(() =>
    expect(w.last()).toEqual({ results: [], valid: true, dirty: false }),
  );
  expect(w.fetcher).not.toHaveBeenCalled();
  await enable();
  expect(screen.getByLabelText("要求 1 本次状态")).toHaveValue("unknown");
  expect(w.last()?.valid).toBe(false);
  expect(w.fetcher).not.toHaveBeenCalled();
});
it("permits an unmapped missing observation with a reason and no fabricated evidence or range", async () => {
  const inv = structuredClone(inventory);
  inv.manifest.requirements[0].source_bound = false;
  inv.manifest.requirements[0].annotation.mapped = false;
  const w = setup({ inventory: inv });
  await enable();
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "missing",
  );
  await reason();
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.results[0]).toMatchObject({
    state: "missing",
    basis_type: "human_observation",
    inspected: [],
    evidence_ids: [],
  });
  expect(w.fetcher).not.toHaveBeenCalled();
});
it("requires the complete own range, exact material evidence and an explicit human declaration", async () => {
  const w = setup();
  await enable();
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "verified",
  );
  await reason();
  await range();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  await screen.findByRole("button", { name: "读取证据 1 原句" });
  expect(w.fetcher).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  ).toBeDisabled();
  await userEvent.click(
    screen.getByRole("button", { name: "读取证据 1 原句" }),
  );
  await screen.findByText("本方冻结原句");
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  );
  expect(w.last()?.valid).toBe(false);
  await confirmed();
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.results[0]).toMatchObject({
    state: "verified",
    basis_type: "human_scope_declaration",
    inspected: [{ part_id: "tech", first_page: 1, last_page: 2 }],
    evidence_ids: ["own-e"],
  });
});
it("does not turn a partial inspection into verified but preserves it as a negative observation", async () => {
  const w = setup();
  await enable();
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "verified",
  );
  await reason();
  await range("1", "1");
  await chooseOwn();
  await confirmed();
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "unknown",
  );
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.results[0].inspected[0].last_page).toBe(1);
  expect(w.last()?.results[0].basis_type).toBe("human_observation");
});
it("rejects zero, negative, fractional and outside-part physical pages rather than dropping the range", async () => {
  const w = setup();
  await enable();
  await reason();
  await range();
  const first = screen.getByLabelText("要求 1 文件 1 分册 1 起始物理页");
  for (const bad of ["0", "-1", "1.5", "3"]) {
    await userEvent.clear(first);
    await userEvent.type(first, bad);
    await waitFor(() => expect(w.last()?.valid).toBe(false));
    expect(w.last()?.results).toEqual([]);
  }
});
it("permits already grounded NA with separately explicit confirmation and authority evidence, without a range", async () => {
  const inv = structuredClone(inventory);
  inv.manifest.requirements[0].requirement.applicability = "not_applicable";
  inv.manifest.requirements[0].requirement.applicability_evidence = [
    "evidence:authority-e",
  ];
  const w = setup({ inventory: inv });
  await enable();
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "not_applicable",
  );
  await reason();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 权威依据证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取证据 1 原句" }),
  );
  await screen.findByText("权威依据冻结原句");
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  );
  expect(w.last()?.valid).toBe(false);
  await userEvent.click(
    screen.getByRole("checkbox", {
      name: /我明确声明已人工核对本条不适用依据/,
    }),
  );
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.results[0]).toMatchObject({
    state: "not_applicable",
    inspected: [],
    evidence_ids: ["authority-e"],
    basis_type: "human_scope_declaration",
  });
});
it("does not offer positive state when frozen confirmation, source, applicability, parsing or quantity gates are missing", async () => {
  for (const kind of [
    "source",
    "decision",
    "provenance",
    "applicability",
    "parse",
    "quantity",
  ]) {
    const inv = structuredClone(inventory),
      view = structuredClone(own);
    const b = inv.manifest.requirements[0];
    if (kind === "source") b.source_bound = false;
    if (kind === "decision") b.decision_snapshot = { decision: "rejected" };
    if (kind === "provenance")
      b.rule_snapshot.provenance_status = "needs_revalidation";
    if (kind === "applicability") b.requirement.applicability = "unknown";
    if (kind === "parse") view.manifest.members[0].parse.status = "not_frozen";
    if (kind === "quantity") b.requirement.minimum_count = 0;
    const w = setup({ inventory: inv, packageView: view });
    await enable();
    expect(
      screen.getByRole("option", { name: "人工声明已检查完整范围" }),
    ).toBeDisabled();
    w.ui.unmount();
  }
});
it("does not let a client state invent NA without frozen applicability evidence", async () => {
  setup();
  await enable();
  expect(
    screen.getByRole("option", { name: "人工声明有据不适用" }),
  ).toBeDisabled();
});
it("rejects a quote from another parse even if the exact directory entry was valid", async () => {
  const w = setup({}, (url) =>
    url === "/api/v1/evidence/own-e"
      ? json({ ...ownEvidence, parse_run_id: "latest-other-run" })
      : undefined,
  );
  await enable();
  await reason();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取证据 1 原句" }),
  );
  expect(
    await screen.findByText("引用不属于所冻文件、解析及物理范围"),
  ).toBeInTheDocument();
  expect(screen.queryByText("本方冻结原句")).not.toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  ).toBeDisabled();
  expect(w.last()?.results[0].evidence_ids).toEqual([]);
});
it("rejects an outside-part directory without resolving it against a latest parse", async () => {
  const w = setup({}, (url) =>
    url === ownPath
      ? json(page(own, [{ ...entry(ownEvidence), physical_page: 9 }]))
      : undefined,
  );
  await enable();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  expect(
    await screen.findByText(/证据目录的文件、解析或逻辑页范围不一致/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "读取证据 1 原句" }),
  ).not.toBeInTheDocument();
  expect(w.fetcher).toHaveBeenCalledTimes(1);
});
it("does not promote authority evidence into verified own-material proof", async () => {
  const w = setup();
  await enable();
  await reason();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 权威依据证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取证据 1 原句" }),
  );
  await screen.findByText("权威依据冻结原句");
  await userEvent.click(
    screen.getByRole("checkbox", { name: "要求 1 采用证据 1" }),
  );
  await userEvent.selectOptions(
    screen.getByLabelText("要求 1 本次状态"),
    "verified",
  );
  await range();
  await confirmed();
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(
    await screen.findByText(/所选引用当前不可用于本条状态或范围/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "选择要求 1 权威依据证据" }),
  ).not.toBeInTheDocument();
});
it("checks the revision and digest on every directory page rather than only the first page", async () => {
  setup({}, (url) => {
    if (url === ownPath)
      return json({
        ...page(own, [entry(ownEvidence)]),
        has_more: true,
        next_cursor: "signed+/cursor",
      });
    if (url === ownPath + "&cursor=signed%2B%2Fcursor")
      return json({
        ...page(own, [{ ...entry(ownEvidence), id: "foreign-e" }]),
        revision_id: "foreign-revision",
      });
    return undefined;
  });
  await enable();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "更多冻结证据" }),
  );
  expect(
    await screen.findByText(/证据目录的包修订或摘要不一致/),
  ).toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: /读取证据 .* 原句/ }),
  ).toHaveLength(1);
});
it("restores the original result but waits for a fresh exact-ID evidence check before calling it valid", async () => {
  let resolve!: (value: Response) => void;
  const saved = initialVerified();
  const w = setup({ initialResults: saved }, (url) =>
    url === "/api/v1/evidence/own-e"
      ? new Promise<Response>((done) => {
          resolve = done;
        })
      : undefined,
  );
  await waitFor(() => expect(w.fetcher).toHaveBeenCalledTimes(1));
  expect(w.last()?.valid).toBe(false);
  expect(screen.getByLabelText("要求 1 理由（最多200字）")).toHaveValue(
    "原人工记录",
  );
  expect(screen.getByLabelText("要求 1 文件 1 分册 1 结束物理页")).toHaveValue(
    "2",
  );
  resolve(json(ownEvidence));
  await waitFor(() =>
    expect(w.last()).toEqual({ results: saved, valid: true, dirty: true }),
  );
});
it("keeps disabled restored inputs and emitted observation intact", async () => {
  const result = {
    rule_id: "rule",
    requirement_digest: "5".repeat(64),
    state: "missing" as const,
    reason: "原观察",
    basis_type: "human_observation" as const,
    inspected: [],
    evidence_ids: [],
  };
  const w = setup({ initialResults: [result], disabled: true });
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(
    screen.getByRole("checkbox", { name: "纳入本次要求 1" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("要求 1 理由（最多200字）")).toBeDisabled();
  expect(w.last()?.results).toEqual([result]);
  expect(w.fetcher).not.toHaveBeenCalled();
});
it("ignores a late quote after inventory context changes and locks the original input", async () => {
  let resolve!: (value: Response) => void;
  const w = setup({}, (url) =>
    url === "/api/v1/evidence/own-e"
      ? new Promise<Response>((done) => {
          resolve = done;
        })
      : undefined,
  );
  await enable();
  await reason();
  await userEvent.click(
    screen.getByRole("button", { name: "选择要求 1 本方证据" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取证据 1 原句" }),
  );
  w.ui.rerender(
    <CoverageEditor
      {...w.props}
      inventory={{ ...inventory, digest: "6".repeat(64) }}
    />,
  );
  resolve(json(ownEvidence));
  await waitFor(() =>
    expect(w.last()).toEqual({ results: [], valid: false, dirty: true }),
  );
  expect(screen.queryByText("本方冻结原句")).not.toBeInTheDocument();
  expect(screen.getByLabelText("要求 1 理由（最多200字）")).toHaveValue(
    "明确人工观察与检查理由",
  );
});
it.each(["candidate", "withdrawn"] as const)(
  "retains but rejects restored %s evidence without calling it published",
  async (source_status) => {
    const w = setup({ initialResults: initialVerified() }, (url) =>
      url === "/api/v1/evidence/own-e"
        ? json({ ...ownEvidence, source_status })
        : undefined,
    );
    await screen.findByText(
      source_status === "withdrawn"
        ? "引用已撤回，不可选用"
        : "引用尚未发布，不可选用",
    );
    expect(w.last()?.valid).toBe(false);
    expect(screen.getByLabelText("要求 1 理由（最多200字）")).toHaveValue(
      "原人工记录",
    );
    expect(screen.queryByText("本方冻结原句")).not.toBeInTheDocument();
  },
);
it("emits only newly selected B and leaves omitted A for server-derived unknown", async () => {
  const inv = structuredClone(inventory);
  const b = structuredClone(inv.manifest.requirements[0]);
  b.rule_id = "rule-b";
  b.requirement.requirement_id = "rule-b";
  b.requirement_digest = "7".repeat(64);
  inv.manifest.requirements.push(b);
  const w = setup({ inventory: inv });
  await enable(2);
  await reason(2);
  await waitFor(() => expect(w.last()?.valid).toBe(true));
  expect(w.last()?.results.map((r) => r.rule_id)).toEqual(["rule-b"]);
  expect(w.last()).not.toHaveProperty("assessment");
});
it("shows member parsing gaps without guessing a requirement missing verdict", async () => {
  const view = structuredClone(own);
  view.manifest.members[0].page_count = null;
  view.manifest.members[0].parts = [];
  view.manifest.members[0].parse.status = "not_frozen";
  const w = setup({ packageView: view });
  expect(
    screen.getByText(/文件 1：页数未知、逻辑范围未分配、解析身份尚未冻结/),
  ).toBeInTheDocument();
  await waitFor(() => expect(w.last()?.results).toEqual([]));
});
it("does not silently collapse multiple restored ranges for one part into a new result", async () => {
  const saved = initialVerified();
  saved[0].inspected = [
    { part_id: "tech", first_page: 1, last_page: 1 },
    { part_id: "tech", first_page: 2, last_page: 2 },
  ];
  const w = setup({ initialResults: saved });
  await waitFor(() => expect(w.last()?.valid).toBe(false));
  expect(
    screen.getByRole("checkbox", { name: "纳入本次要求 1" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/同一分册的多个独立页段尚不在本编辑器/),
  ).toBeInTheDocument();
});
