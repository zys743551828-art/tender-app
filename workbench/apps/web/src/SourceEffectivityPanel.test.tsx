import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { Bid, RuleView } from "./contracts";
import { setAuth } from "./api";
import { SourceEffectivityPanel } from "./SourceEffectivityPanel";

const ambiguityIds = ["a".repeat(64), "b".repeat(64)];
const defaultQuotation = "总工期改为90天；投标截止时间改为22日，其余条款不变。";
let quotation = defaultQuotation;
const bid = (id = "bid-a") => ({ id, material_revision: 3 }) as Bid;
const rule = (
  id: string,
  statement: string,
  evidence: string[],
  bidId: string,
): RuleView => ({
  id,
  statement,
  evidence_ids: evidence,
  scope: { bid_id: bidId, description: "本标段" },
  rule_set_id: "rules-1",
  kind: "mandatory",
  conditions: [],
  exceptions: [],
  maximum: null,
  confirmation: "pending",
  decision_revision: 1,
  carryover: null,
  bands: [],
  origin_kind: "model_extracted",
  manual_origin_rule_id: null,
  provenance_status: "effective",
});
function world(bidId = "bid-a", newRules = true) {
  const rules = [
    rule("old-rule", "工期120天", ["old-evidence"], bidId),
    rule("keep-rule", "质量C30保持", ["old-evidence"], bidId),
    rule("other-rule", "其他文件条款", ["other-evidence"], bidId),
  ];
  if (mixedNewRule) rules[0].evidence_ids.push("new-evidence");
  if (newRules)
    rules.push(rule("new-rule", "补遗工期90天", ["new-evidence"], bidId));
  return {
    rules: {
      id: "rules-1",
      bid_id: bidId,
      material_revision: 3,
      coverage: "conflict",
      revision: 1,
      rules,
    },
    view: {
      bid_id: bidId,
      rule_set_id: "rules-1",
      rules,
      sources: [
        {
          document_version_id: "old",
          original_name: "原招标.pdf",
          current: true,
          roles: ["tender"],
          evidence_ids: ["old-evidence"],
        },
        {
          document_version_id: "new",
          original_name: "补遗一.pdf",
          current: true,
          roles: ["supplement"],
          evidence_ids: ["new-evidence"],
        },
      ],
      ambiguities: [
        { id: ambiguityIds[0], text: "工期范围需确认" },
        { id: ambiguityIds[1], text: "截止时间范围需确认" },
      ],
      ambiguity_resolution_available: true,
      ambiguity_resolution_error: null as string | null,
    },
  };
}
function result(bidId = "bid-a") {
  const value = world(bidId).rules;
  return {
    ...value,
    id: "rules-2",
    coverage: "partial",
    rules: value.rules.filter((r) => r.id !== "old-rule"),
  };
}
const json = (data: unknown, status = 200, etag = '"source-1"') =>
  new Response(JSON.stringify(data), { status, headers: { ETag: etag } });
let writes: RequestInit[];
let tag: string;
let available: boolean;
let hasNewRules: boolean;
let mixedNewRule: boolean;
let post: () => Promise<Response>;
beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  writes = [];
  tag = '"source-1"';
  available = true;
  hasNewRules = true;
  mixedNewRule = false;
  quotation = defaultQuotation;
  post = async () => json(result());
  setAuth({
    member: { id: "member-a", display_name: "合成", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const path = String(input);
      if (options?.method === "POST") {
        writes.push(options);
        return post();
      }
      const bidId = path.match(/\/bids\/([^/]+)/)?.[1] ?? "bid-a";
      const value = world(bidId, hasNewRules);
      if (path.endsWith("/source-effectivity"))
        return json(
          {
            ...value.view,
            ambiguity_resolution_available: available,
            ambiguity_resolution_error: available
              ? null
              : "INTERNAL_NOT_PUBLIC",
          },
          200,
          tag,
        );
      if (path.endsWith("/rules")) return json(value.rules);
      if (path.endsWith("/documents/new/evidence"))
        return json({
          document_version_id: "new",
          parse_run_id: "parse-new",
          coverage: "complete",
          gaps: [],
          items: [
            {
              id: "new-evidence",
              document_version_id: "new",
              physical_page: 1,
              quote: quotation,
              source_status: "published",
            },
          ],
        });
      throw new Error("Unexpected test request: " + path);
    }),
  );
});
async function fill(user: ReturnType<typeof userEvent.setup>, ackAll = true) {
  const begin = await screen.findByRole("button", { name: "开始逐项核对" });
  await waitFor(() => expect(begin).toBeEnabled());
  await user.click(begin);
  await user.selectOptions(screen.getByLabelText("旧招标文件"), "old");
  await user.selectOptions(screen.getByLabelText("新补遗文件"), "new");
  await user.click(screen.getByRole("checkbox", { name: "工期120天" }));
  await user.click(
    screen.getByRole("checkbox", { name: /我已核对补遗新要求/ }),
  );
  await user.click(screen.getByRole("checkbox", { name: "工期范围需确认" }));
  if (ackAll)
    await user.click(
      screen.getByRole("checkbox", { name: "截止时间范围需确认" }),
    );
  await user.click(await screen.findByRole("checkbox", { name: /物理页 1/ }));
  await user.type(
    screen.getByLabelText("局部替代的核对理由"),
    "已核对原页，仅替代工期和截止时间范围。",
  );
}
async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "核对本次局部变更" }));
  await user.click(screen.getByRole("button", { name: "确认保存局部变更" }));
}
it("submits only selected old-source rules, all explicit ambiguity ACKs and literal new-source quote", async () => {
  const user = userEvent.setup();
  const onChanged = vi.fn();
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={onChanged}
    />,
  );
  await fill(user);
  expect(
    screen.queryByRole("checkbox", { name: "其他文件条款" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "质量C30保持" }),
  ).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: /查看补遗原页/ }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "核对本次局部变更" }));
  const confirm = screen.getByRole("button", { name: "确认保存局部变更" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await screen.findByText(/已记录局部来源核对/);
  expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0].body as string)).toEqual({
    base_rule_set_id: "rules-1",
    action: "partial_replace",
    old_document_version_id: "old",
    new_document_version_id: "new",
    rule_ids: ["old-rule"],
    scope_basis: [{ evidence_id: "new-evidence", quote: quotation }],
    additions: [],
    reason: "已核对原页，仅替代工期和截止时间范围。",
    acknowledged_ambiguity_ids: ambiguityIds,
  });
  expect(new Headers(writes[0].headers).get("If-Match")).toBe('"source-1"');
  expect(onChanged).toHaveBeenCalledTimes(1);
});
it("requires every ambiguity and an exact source quote; cancel never sends", async () => {
  const user = userEvent.setup();
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user, false);
  const review = screen.getByRole("button", { name: "核对本次局部变更" });
  expect(review).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", { name: "截止时间范围需确认" }),
  );
  await user.clear(screen.getByLabelText("引用原文（须与该证据逐字对应）"));
  await user.type(
    screen.getByLabelText("引用原文（须与该证据逐字对应）"),
    "凭空改写的引用",
  );
  expect(review).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "取消本次核对" }));
  expect(writes).toHaveLength(0);
});
it.each([
  ["CRLF", "\r\n"],
  ["LF", "\n"],
  ["CR", "\r"],
])(
  "submits the original %s bytes after editing a multiline excerpt in a textarea",
  async (_, newline) => {
    const user = userEvent.setup();
    const lines = ["总工期改为90天；", "投标截止时间改为22日，其余条款不变。"];
    const exactExcerpt = lines.join(newline);
    quotation = ["原页标题", exactExcerpt, "原页末尾"].join(newline);
    render(
      <SourceEffectivityPanel
        bid={bid()}
        memberId="member-a"
        onChanged={vi.fn()}
      />,
    );
    await fill(user);
    const input = screen.getByLabelText("引用原文（须与该证据逐字对应）");
    fireEvent.change(input, { target: { value: lines.join("\n") } });
    expect(input).toHaveValue(lines.join("\n"));
    expect(
      screen.getByRole("button", { name: "核对本次局部变更" }),
    ).toBeEnabled();
    await submit(user);
    await screen.findByText(/已记录局部来源核对/);
    expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0].body as string).scope_basis).toEqual([
      { evidence_id: "new-evidence", quote: exactExcerpt },
    ]);
  },
);
it.each([
  ["edited character", "总工期改为91天；\n投标截止时间改为22日。"],
  ["edited punctuation", "总工期改为90天,\n投标截止时间改为22日。"],
  ["inserted space", "总工期 改为90天；\n投标截止时间改为22日。"],
])(
  "does not repair %s while adapting CRLF evidence input",
  async (_, candidate) => {
    quotation = "总工期改为90天；\r\n投标截止时间改为22日。";
    const user = userEvent.setup();
    render(
      <SourceEffectivityPanel
        bid={bid()}
        memberId="member-a"
        onChanged={vi.fn()}
      />,
    );
    await fill(user);
    fireEvent.change(screen.getByLabelText("引用原文（须与该证据逐字对应）"), {
      target: { value: candidate },
    });
    expect(
      screen.getByRole("button", { name: "核对本次局部变更" }),
    ).toBeDisabled();
    expect(writes).toHaveLength(0);
  },
);
it("keeps an unresolvable mixed-line-ending edit invalid instead of inventing source text", async () => {
  quotation =
    "原页标题\r\n总工期改为90天；\r\n投标截止时间改为22日。\n其余条款不变。";
  const user = userEvent.setup();
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  fireEvent.change(screen.getByLabelText("引用原文（须与该证据逐字对应）"), {
    target: {
      value: "总工期改为90天；\n投标截止时间改为22日。\n其余条款不变。",
    },
  });
  expect(
    screen.getByRole("button", { name: "核对本次局部变更" }),
  ).toBeDisabled();
  expect(writes).toHaveLength(0);
});
it("unavailable resolution fails closed without exposing internal codes", async () => {
  available = false;
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "开始逐项核对" }),
  ).toBeDisabled();
  expect(screen.queryByText("INTERNAL_NOT_PUBLIC")).not.toBeInTheDocument();
});
it("missing new requirements blocks replacement and directs users to the existing addition entry", async () => {
  hasNewRules = false;
  const user = userEvent.setup();
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  expect(screen.getByText(/补遗的新要求尚未列入/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "核对本次局部变更" }),
  ).toBeDisabled();
  expect(writes).toHaveLength(0);
});
it("412 preserves edits and requires explicit reread/reselection, without rebasing or resend", async () => {
  const user = userEvent.setup();
  post = async () => {
    tag = '"source-2"';
    return json({ message: "来源已变化", code: "REVISION_CONFLICT" }, 412);
  };
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  await submit(user);
  await screen.findByText(/保存时来源已变化/);
  expect(screen.getByLabelText("局部替代的核对理由")).toHaveValue(
    "已核对原页，仅替代工期和截止时间范围。",
  );
  await user.click(screen.getByRole("button", { name: "重新读取来源" }));
  await screen.findByText(/来源或条款已变化/);
  expect(
    screen.getByRole("button", { name: "核对本次局部变更" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "确认保存局部变更" }),
  ).not.toBeInTheDocument();
  expect(writes).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "重新核对当前来源" }));
  expect(
    screen.getByRole("checkbox", { name: "工期范围需确认" }),
  ).not.toBeChecked();
  expect(screen.getByLabelText("旧招标文件")).toHaveValue("");
});
it("lost ACK retries the same original request after remount, isolated from another member", async () => {
  const user = userEvent.setup();
  post = async () => {
    throw new Error("Lost acknowledgement");
  };
  let mounted = render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  await submit(user);
  await screen.findByRole("button", { name: "恢复原来源核对回执" });
  mounted.unmount();
  mounted = render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-b"
      onChanged={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: "恢复原来源核对回执" }),
  ).not.toBeInTheDocument();
  mounted.unmount();
  post = async () => json(result());
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "恢复原来源核对回执" }),
  );
  await screen.findByText(/已记录局部来源核对/);
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toBe(writes[0].body);
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).toBe(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
  expect(new Headers(writes[1].headers).get("If-Match")).toBe('"source-1"');
});
it("project switch ignores a late acknowledgement and clears the visible edit scope", async () => {
  const user = userEvent.setup();
  let resolve!: (value: Response) => void;
  post = () =>
    new Promise((done) => {
      resolve = done;
    });
  const onChanged = vi.fn();
  const mounted = render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={onChanged}
    />,
  );
  await fill(user);
  await submit(user);
  mounted.rerender(
    <SourceEffectivityPanel
      bid={bid("bid-b")}
      memberId="member-a"
      onChanged={onChanged}
    />,
  );
  await act(async () => resolve(json(result())));
  expect(onChanged).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("局部替代的核对理由")).not.toBeInTheDocument();
  expect(writes).toHaveLength(1);
});
it("requires a surviving new-source rule after mixed-source rules are retired", async () => {
  hasNewRules = false;
  mixedNewRule = true;
  const user = userEvent.setup();
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  expect(screen.getByText(/补遗的新要求尚未列入/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "核对本次局部变更" }),
  ).toBeDisabled();
  expect(writes).toHaveLength(0);
});
it("tampered pending targets cannot be replayed", async () => {
  const user = userEvent.setup();
  post = async () => {
    throw new Error("Lost acknowledgement");
  };
  const mounted = render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  await fill(user);
  await submit(user);
  await screen.findByRole("button", { name: "恢复原来源核对回执" });
  mounted.unmount();
  const key = "tender:command-record:source-effectivity:member-a:bid-a";
  const record = JSON.parse(sessionStorage.getItem(key)!);
  record.path = "/bids/other/source-effectivity-decisions";
  sessionStorage.setItem(key, JSON.stringify(record));
  render(
    <SourceEffectivityPanel
      bid={bid()}
      memberId="member-a"
      onChanged={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "恢复原来源核对回执" }),
  ).toBeDisabled();
  expect(writes).toHaveLength(1);
});
