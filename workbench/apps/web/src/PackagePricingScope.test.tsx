import { PackagePricingScope } from "./PackagePricingScope";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { pricingScopeKey, samePricingBinding } from "./packagePricing";
import { PricingPanel } from "./PricingPanel";
import { PricingFormulaEditor } from "./PricingFormulaEditor";
import type {
  PricingPackageContext,
  PricingPackagePricingBinding,
} from "./contracts";

vi.mock("./contracts", async (original) => ({
  ...(await original<typeof import("./contracts")>()),
  implementedOperations: [
    "GET /api/v1/bids/{bid_id}/settings",
    "GET /api/v1/bids/{bid_id}/packages",
    "GET /api/v1/bids/{bid_id}/pricing-context",
    "GET /api/v1/bids/{bid_id}/package-pricing-context",
    "GET /api/v1/bids/{bid_id}/package-pricing-formula-sources",
    "POST /api/v1/bids/{bid_id}/package-pricing-formulas",
    "GET /api/v1/bids/{bid_id}/pricing-formulas",
    "GET /api/v1/bids/{bid_id}/pricing-plans",
  ],
}));

const binding: PricingPackagePricingBinding = {
  package_id: "package",
  revision_id: "revision-1",
  authority_package_id: "rules",
  authority_revision_id: "rules-2",
};
const context: PricingPackageContext = {
  bid_id: "bid",
  material_snapshot_id: null,
  material_revision: 1,
  scope: { bid_id: "bid", round_id: "round", effective_documents: [] },
  parses: [],
  source_heads: [],
  package_binding: binding,
  package_snapshot: {
    version: "package-pricing-authority/1",
    binding,
    package_digest: "a".repeat(64),
    authority_digest: "b".repeat(64),
    identity_digest: "c".repeat(64),
    source_heads_digest: "d".repeat(64),
    rule_set_id: null,
    inventory_id: null,
    inventory_digest: null,
  },
};
const json = (value: unknown) =>
  new Response(JSON.stringify(value), { headers: { ETag: '"exact-context"' } });
const packageList = (kind: string) => ({
  items: [
    {
      id: kind === "bid" ? "package" : "rules",
      revision_id: kind === "bid" ? "revision-1" : "rules-2",
      revision: kind === "bid" ? 1 : 2,
      kind,
    },
  ],
  next_cursor: null,
});

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it("requires explicit selections and freezes both exact revisions without auto-selecting heads", async () => {
  const user = userEvent.setup();
  const selected = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      json(packageList(new URL(url, "http://test").searchParams.get("kind")!)),
    ),
  );
  render(<PackagePricingScope bidId="bid" onSelect={selected} />);
  await screen.findByRole("option", { name: /投标包 · 第 1 版/ });
  expect(
    screen.getByRole("button", { name: "使用这两份修订继续报价" }),
  ).toBeDisabled();
  expect(selected).not.toHaveBeenCalled();
  await user.selectOptions(
    screen.getByLabelText("本次投标包"),
    "package:revision-1",
  );
  expect(
    screen.getByRole("button", { name: "使用这两份修订继续报价" }),
  ).toBeDisabled();
  await user.selectOptions(
    screen.getByLabelText("本次招标与补遗包"),
    "rules:rules-2",
  );
  await user.click(
    screen.getByRole("button", { name: "使用这两份修订继续报价" }),
  );
  expect(selected).toHaveBeenCalledExactlyOnceWith(binding);
});

it("confirms the displayed exact revisions when a background refresh starts during the click", async () => {
  const user = userEvent.setup();
  const selected = vi.fn();
  const pending: (() => void)[] = [];
  let refreshing = false;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const kind = new URL(url, "http://test").searchParams.get("kind")!;
      if (!refreshing) return Promise.resolve(json(packageList(kind)));
      return new Promise<Response>((resolve) => {
        pending.push(() => resolve(json(packageList(kind))));
      });
    }),
  );
  render(<PackagePricingScope bidId="bid" onSelect={selected} />);
  await screen.findByRole("option", { name: /投标包 · 第 1 版/ });
  await user.selectOptions(
    screen.getByLabelText("本次投标包"),
    "package:revision-1",
  );
  await user.selectOptions(
    screen.getByLabelText("本次招标与补遗包"),
    "rules:rules-2",
  );
  const confirm = screen.getByRole("button", {
    name: "使用这两份修订继续报价",
  });
  await user.pointer({ target: confirm, keys: "[MouseLeft>]" });
  refreshing = true;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await waitFor(() => expect(pending).toHaveLength(2));
  try {
    await user.pointer({ target: confirm, keys: "[/MouseLeft]" });
    expect(selected).toHaveBeenCalledExactlyOnceWith(binding);
  } finally {
    await act(async () => pending.forEach((resolve) => resolve()));
  }
});

it.each(["removed", "error"])(
  "rejects a selection when refreshed directory evidence is %s",
  async (outcome) => {
    const user = userEvent.setup();
    const selected = vi.fn();
    let refreshing = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const kind = new URL(url, "http://test").searchParams.get("kind")!;
        if (refreshing && kind === "bid") {
          if (outcome === "error")
            throw new Error("synthetic directory unavailable");
          const changed = packageList(kind);
          changed.items[0].revision_id = "new-revision";
          return json(changed);
        }
        return json(packageList(kind));
      }),
    );
    render(<PackagePricingScope bidId="bid" onSelect={selected} />);
    await screen.findByRole("option", { name: /投标包 · 第 1 版/ });
    await user.selectOptions(
      screen.getByLabelText("本次投标包"),
      "package:revision-1",
    );
    await user.selectOptions(
      screen.getByLabelText("本次招标与补遗包"),
      "rules:rules-2",
    );
    const confirm = screen.getByRole("button", {
      name: "使用这两份修订继续报价",
    });
    expect(confirm).toBeEnabled();
    refreshing = true;
    act(() => window.dispatchEvent(new Event("server-snapshot-change")));
    await waitFor(() => expect(confirm).toBeDisabled());
    await user.click(confirm);
    expect(selected).not.toHaveBeenCalled();
  },
);

it("uses exact context, filters another package and restores its editor draft after mode changes and reselection", async () => {
  const user = userEvent.setup();
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = new URL(url, "http://test");
      paths.push(url);
      if (path.pathname.endsWith("/settings"))
        return json({ bid_id: "bid", settings: { pricing: true } });
      if (path.pathname.endsWith("/packages"))
        return json(packageList(path.searchParams.get("kind")!));
      if (path.pathname.endsWith("/pricing-formulas"))
        return json({
          items: [
            {
              formula_version_id: "other",
              title: "别的投标包公式",
              package_binding: { ...binding, revision_id: "older" },
              current_applicability: { applicable: true, reasons: [] },
            },
            {
              formula_version_id: "chosen",
              title: "本次精确包公式",
              package_binding: binding,
              current_applicability: { applicable: true, reasons: [] },
            },
          ],
          next_cursor: null,
        });
      if (path.pathname.endsWith("/package-pricing-context"))
        return json(context);
      return json({ items: [], next_cursor: null });
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={vi.fn()} />);
  await screen.findByRole("option", { name: /投标包 · 第 1 版/ });
  await user.selectOptions(
    screen.getByLabelText("本次投标包"),
    "package:revision-1",
  );
  await user.selectOptions(
    screen.getByLabelText("本次招标与补遗包"),
    "rules:rules-2",
  );
  await user.click(
    screen.getByRole("button", { name: "使用这两份修订继续报价" }),
  );
  await screen.findByRole("option", { name: /本次精确包公式/ });
  expect(screen.queryByRole("option", { name: /别的投标包公式/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "登记新的有据公式" }));
  await screen.findByText("确认并登记有据公式");
  await user.type(screen.getByLabelText("公式标题"), "原包待核草稿");
  await user.selectOptions(screen.getByLabelText("报价范围"), "legacy");
  await screen.findByRole("option", { name: /别的投标包公式/ });
  expect(screen.queryByLabelText("公式标题")).toBeNull();
  await user.selectOptions(screen.getByLabelText("报价范围"), "package");
  await user.click(screen.getByRole("button", { name: "登记新的有据公式" }));
  await waitFor(() =>
    expect(screen.getByLabelText("公式标题")).toHaveValue("原包待核草稿"),
  );
  await user.click(screen.getByRole("button", { name: "重新选择报价包修订" }));
  await screen.findByRole("option", { name: /投标包 · 第 1 版/ });
  await user.selectOptions(
    screen.getByLabelText("本次投标包"),
    "package:revision-1",
  );
  await user.selectOptions(
    screen.getByLabelText("本次招标与补遗包"),
    "rules:rules-2",
  );
  await user.click(
    screen.getByRole("button", { name: "使用这两份修订继续报价" }),
  );
  await user.click(screen.getByRole("button", { name: "登记新的有据公式" }));
  await waitFor(() =>
    expect(screen.getByLabelText("公式标题")).toHaveValue("原包待核草稿"),
  );
  const exact = paths.find((path) =>
    path.includes("/package-pricing-context?"),
  );
  expect(new URL(exact!, "http://test").searchParams.get("revision_id")).toBe(
    "revision-1",
  );
  expect(paths.some((path) => /\/pricing-context$/.test(path))).toBe(false);
});

function validInput() {
  return {
    title: "Synthetic exact formula",
    method: "lowest_valid_ratio",
    maximum: "30",
    minimum: "",
    maximumPrice: "",
    noMinimum: true,
    noMaximum: true,
    minimumCount: "1",
    above: "",
    below: "",
    unit: "元",
    currency: "CNY",
    rounding: "half_up_2dp",
    reason: "Synthetic explicit confirmation",
    terms: true,
    matches: true,
    quotes: [
      {
        source_id: "source",
        source_revision: 2,
        document_version_id: "doc",
        parse_id: "parse",
        physical_page: 1,
        evidence_id: "evidence",
        quote: "Synthetic complete pricing clause",
        supported_fields: [
          "method",
          "maximum",
          "minimum_price",
          "maximum_price",
          "minimum_valid_bids",
          "amount_unit",
          "currency",
          "rounding_policy",
          "baseline_set",
          "exclusions",
          "intermediate_rounding",
          "clamping",
        ],
      },
    ],
  };
}

it("preserves the exact editor draft and original request after a mismatched acknowledgement, then recovers its valid reply", async () => {
  const user = userEvent.setup();
  const saved = vi.fn();
  const writes: Record<string, unknown>[] = [];
  const requests: { key: string | null; etag: string | null }[] = [];
  const input = validInput();
  const key =
    "tender:knowledge:member:bid:pricing-formula" + pricingScopeKey(binding);
  sessionStorage.setItem(key, JSON.stringify(input));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        const headers = new Headers(init.headers);
        requests.push({
          key: headers.get("Idempotency-Key"),
          etag: headers.get("If-Match"),
        });
        const correct = writes.length > 1;
        return json({
          formula_version_id: correct ? "correct" : "wrong",
          formula: {
            bid_id: "bid",
            formula_version_id: correct ? "correct" : "wrong",
            package_binding: correct
              ? binding
              : { ...binding, revision_id: "other" },
          },
        });
      }
      return json({ items: [], next_cursor: null });
    }),
  );
  render(
    <PricingFormulaEditor
      bidId="bid"
      memberId="member"
      initialContext={{ data: context, etag: '"exact-context"' }}
      packageBinding={binding}
      onSaved={saved}
      onClose={vi.fn()}
    />,
  );
  await user.click(screen.getByRole("button", { name: "确认并登记公式" }));
  await screen.findByText(/公式返回身份无法核对/);
  expect(writes[0].package_binding).toEqual(binding);
  expect(saved).not.toHaveBeenCalled();
  expect(screen.getByLabelText("公式标题")).toHaveValue(input.title);
  await waitFor(() =>
    expect(JSON.parse(sessionStorage.getItem(key)!).title).toBe(input.title),
  );
  await user.click(screen.getByRole("button", { name: "恢复原公式登记结果" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
  expect(requests[1]).toEqual(requests[0]);
});

it("compares binding values independently of key order and isolates both package revisions", () => {
  expect(
    samePricingBinding(binding, {
      authority_revision_id: "rules-2",
      authority_package_id: "rules",
      revision_id: "revision-1",
      package_id: "package",
    }),
  ).toBe(true);
  expect(
    samePricingBinding(binding, {
      ...binding,
      authority_revision_id: "rules-3",
    }),
  ).toBe(false);
  expect(samePricingBinding(binding, undefined)).toBe(false);
  expect(pricingScopeKey(binding)).not.toEqual(
    pricingScopeKey({ ...binding, revision_id: "revision-2" }),
  );
});

it("keeps an uncertain original registration across leaving and returning to its package without applying a late reply elsewhere", async () => {
  const user = userEvent.setup();
  const saved = vi.fn();
  const other = { ...binding, revision_id: "revision-2" };
  const writes: { body: string; key: string | null; etag: string | null }[] =
    [];
  let resolveOriginal!: (response: Response) => void;
  const acknowledgement = {
    formula_version_id: "original-formula",
    formula: {
      bid_id: "bid",
      formula_version_id: "original-formula",
      package_binding: binding,
    },
  };
  sessionStorage.setItem(
    "tender:knowledge:member:bid:pricing-formula" + pricingScopeKey(binding),
    JSON.stringify(validInput()),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const headers = new Headers(init.headers);
        writes.push({
          body: String(init.body),
          key: headers.get("Idempotency-Key"),
          etag: headers.get("If-Match"),
        });
        if (writes.length === 1)
          return new Promise<Response>((resolve) => {
            resolveOriginal = resolve;
          });
        return json(acknowledgement);
      }
      return json({ items: [], next_cursor: null });
    }),
  );
  const editor = (scope: PricingPackagePricingBinding) => (
    <PricingFormulaEditor
      bidId="bid"
      memberId="member"
      initialContext={{
        data: {
          ...context,
          package_binding: scope,
          package_snapshot: { ...context.package_snapshot, binding: scope },
        },
        etag: '"exact-context"',
      }}
      packageBinding={scope}
      onSaved={saved}
      onClose={vi.fn()}
    />
  );
  let surface = render(editor(binding));
  await user.click(screen.getByRole("button", { name: "确认并登记公式" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  surface.unmount();
  surface = render(editor(other));
  expect(screen.getByLabelText("公式标题")).toHaveValue("");
  resolveOriginal(json(acknowledgement));
  await waitFor(() =>
    expect(screen.getByLabelText("公式标题")).toHaveValue(""),
  );
  expect(saved).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "恢复原公式登记结果" }),
  ).toBeNull();
  surface.unmount();
  render(editor(binding));
  expect(screen.getByLabelText("公式标题")).toHaveValue(
    "Synthetic exact formula",
  );
  await user.click(
    await screen.findByRole("button", { name: "恢复原公式登记结果" }),
  );
  await waitFor(() =>
    expect(saved).toHaveBeenCalledExactlyOnceWith(acknowledgement),
  );
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
});
