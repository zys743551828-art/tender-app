import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageRequirements } from "./PackageRequirements";
import type {
  BidPackageStoredView,
  PackageRequirementInventoryView,
  RuleSetView,
} from "./contracts";

// UI protocol fixtures only; real nonowner ASGI is tested in requirements-api.
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const bid = id(1),
  member = id(2),
  authorityId = id(3),
  authorityRevision = id(4),
  packageId = id(5),
  target = id(6),
  inventoryId = id(7),
  ruleSet = id(8),
  ruleId = id(9),
  evidence = id(10),
  attemptId = id(11);
const scope = {
  engineering_project_id: id(12),
  lot_id: id(13),
  round_id: id(14),
  bid_id: bid,
  bidder_id: id(15),
  bidder_status: "confirmed" as const,
};
const view: BidPackageStoredView = {
  manifest: {
    package_id: packageId,
    revision_id: target,
    revision: 1,
    kind: "bid",
    identity_version: "bid-package/1",
    scope,
    predecessor_digest: null,
    members: [
      {
        member_id: "技术册",
        document_version_id: id(16),
        file_digest: "a".repeat(64),
        source_kind: "own",
        source_ref: "file:1",
        scope,
        purposes: ["技术"],
        page_count: 2,
        parse: {
          status: "frozen",
          parse_run_id: id(17),
          parser_digest: "b".repeat(64),
          config_digest: "c".repeat(64),
          evidence_digest: "d".repeat(64),
          reason: null,
        },
        parts: [
          {
            part_id: "技术",
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
    bidder_id: scope.bidder_id,
    bidder_name: "企业",
    round_id: scope.round_id,
    engineering_project_id: scope.engineering_project_id,
    engineering_title: "项目",
    region: null,
    engineering_type: null,
    lot: "一标",
    lot_id: scope.lot_id,
    round_no: 1,
    binding_status: "confirmed",
    authority_id: id(18),
    digest: "f".repeat(64),
  },
  storage_eligible: true,
  review_ready: false,
};
const authority: BidPackageStoredView = {
  ...view,
  manifest: {
    ...view.manifest,
    kind: "authority",
    package_id: authorityId,
    revision_id: authorityRevision,
  },
};
const rules: RuleSetView = {
  id: ruleSet,
  bid_id: bid,
  material_revision: 1,
  revision: 1,
  coverage: "partial",
  rules: [],
};
const frozen: PackageRequirementInventoryView = {
  digest: "1".repeat(64),
  manifest: {
    version: "bid-package-requirements/1",
    id: inventoryId,
    bid_id: bid,
    package_id: packageId,
    target_revision_id: target,
    package_digest: view.digest,
    authority_revision_id: authorityRevision,
    authority_digest: authority.digest,
    rule_set_id: ruleSet,
    rule_set_digest: "2".repeat(64),
    revision: 1,
    predecessor_digest: null,
    identity_digest: view.identity.digest,
    source_snapshot: [],
    inventory_complete: false,
    extraction_binding: "unproven_legacy_rule_set",
    review_ready: false,
    actor_id: member,
    requirements: [
      {
        rule_id: ruleId,
        rule_digest: "3".repeat(64),
        rule_snapshot: {
          statement: "原规则全文必须保留，不能改成施组摘要",
          conditions: ["仅在指定条件适用"],
          exceptions: ["除非有正式补遗"],
          evidence_ids: [evidence],
        },
        decision_id: null,
        decision_snapshot: null,
        requirement: {
          requirement_id: ruleId,
          scope,
          origin: "authority",
          source_refs: ["rule:original"],
          categories: ["未分类"],
          target_part_ids: [],
          minimum_count: null,
          applicability: "unknown",
          applicability_evidence: [],
          valid_at: null,
          conditions: ["conditions:0:original"],
          checks: [],
          identity_version: "bid-requirement/1",
        },
        requirement_digest: "4".repeat(64),
        source_bound: false,
        annotation: {
          kind: "human_check_plan_declaration",
          mapped: false,
          reason: null,
          basis_evidence_ids: [],
        },
      },
    ],
  },
};
const base = `/api/v1/bids/${bid}/packages/${packageId}/revisions/${target}/requirement-inventories`;
const json = (data: unknown, etag?: string, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: etag ? { ETag: etag } : {},
  });
const page = (items: unknown[]) => ({
  items,
  has_more: false,
  next_cursor: null,
});
type Handler = (
  url: string,
  options?: RequestInit,
) => Response | undefined | Promise<Response | undefined>;
function install(handler?: Handler, existing = true) {
  const writes: { body: unknown; headers: Headers; url: string }[] = [];
  const fetcher = vi.fn(async (input: string, options?: RequestInit) => {
    const url = String(input);
    if (options?.method === "POST")
      writes.push({
        url,
        body: JSON.parse(String(options.body)),
        headers: new Headers(options.headers),
      });
    const custom = await handler?.(url, options);
    if (custom) return custom;
    if (options?.method === "POST") return json(frozen, '"saved"', 201);
    if (url === `/api/v1/bids/${bid}/packages?kind=authority&limit=20`)
      return json(
        page([
          {
            id: authorityId,
            bid_id: bid,
            kind: "authority",
            revision: 1,
            revision_id: authorityRevision,
            digest: authority.digest,
          },
        ]),
      );
    if (
      url === `/api/v1/bids/${bid}/packages/${authorityId}/revisions?limit=20`
    )
      return json(
        page([
          {
            id: authorityRevision,
            package_id: authorityId,
            revision: 1,
            digest: authority.digest,
            created_at: "2026-10-19T00:00:00Z",
          },
        ]),
      );
    if (
      url ===
      `/api/v1/bids/${bid}/packages/${authorityId}/revisions/${authorityRevision}`
    )
      return json(authority);
    if (url === `/api/v1/bids/${bid}/rules`) return json(rules);
    if (url === base + "?limit=20")
      return json(
        {
          ...page(
            existing
              ? [
                  {
                    id: inventoryId,
                    digest: frozen.digest,
                    created_at: "2026-10-19T00:00:00Z",
                  },
                ]
              : [],
          ),
          current_inventory_id: existing ? inventoryId : null,
        },
        existing ? '"current"' : undefined,
      );
    if (url === base + "/" + inventoryId) return json(frozen);
    if (url === base + "/" + inventoryId + "/coverage-attempts?limit=20")
      return json(page([]));
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { writes, fetcher };
}
beforeEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
async function expand() {
  await userEvent.click(screen.getByRole("button", { name: "要求清单与覆盖" }));
  await screen.findByRole("option", { name: /依据包 1/ });
}
async function selectAuthority() {
  await userEvent.selectOptions(
    screen.getByLabelText("权威依据包"),
    authorityId,
  );
  await screen.findByRole("option", { name: /修订 1 ·/ });
  await userEvent.selectOptions(
    screen.getByLabelText("依据包明确修订"),
    authorityRevision,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "创建未映射清单" }),
    ).toBeEnabled(),
  );
}
const mount = () =>
  render(
    <PackageRequirements bidId={bid} memberId={member} packageView={view} />,
  );

it("loads only after opening and reads exact frozen rule, unknown flags and historical scope", async () => {
  const { fetcher } = install();
  mount();
  expect(fetcher).not.toHaveBeenCalled();
  await expand();
  await userEvent.click(
    await screen.findByRole("button", { name: /读取清单 1/ }),
  );
  expect(
    await screen.findByText("原规则全文必须保留，不能改成施组摘要"),
  ).toBeInTheDocument();
  expect(screen.getByText(/清单完整性未知/)).toBeInTheDocument();
  expect(screen.getByText(/来源绑定：未知／未绑定/)).toBeInTheDocument();
  expect(screen.getByText(/数量：未知/)).toBeInTheDocument();
  expect(screen.getByText(/原始条件：仅在指定条件适用/)).toBeInTheDocument();
  expect(
    await screen.findByText(/尚无人工范围声明，所有条款核验状态为未知/),
  ).toBeInTheDocument();
});

it("creates an explicit empty mapping from top-level exact rule set with first-version condition", async () => {
  const { writes } = install(undefined, false);
  mount();
  await expand();
  expect(screen.getByRole("button", { name: "创建未映射清单" })).toBeDisabled();
  await selectAuthority();
  await userEvent.click(screen.getByRole("button", { name: "创建未映射清单" }));
  await screen.findByText(/已保存要求清单修订 1/);
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toEqual({
    authority_revision_id: authorityRevision,
    rule_set_id: ruleSet,
    mappings: [],
  });
  expect(writes[0].headers.get("If-None-Match")).toBe("*");
  expect(writes[0].headers.get("If-Match")).toBeNull();
});

it.each(["other-bid", "mixed-set", "missing-id"])(
  "blocks creation for inconsistent exact rules identity: %s",
  async (mode) => {
    const invalid = structuredClone(rules);
    if (mode === "other-bid") invalid.bid_id = id(99);
    if (mode === "missing-id") invalid.id = "";
    if (mode === "mixed-set")
      invalid.rules = [
        {
          rule_set_id: id(99),
          scope: { bid_id: bid },
        } as RuleSetView["rules"][number],
      ];
    install(
      (url) => (url.endsWith("/rules") ? json(invalid) : undefined),
      false,
    );
    mount();
    await expand();
    expect(
      await screen.findByText(/规则集精确身份或项目范围不一致/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创建未映射清单" }),
    ).toBeDisabled();
  },
);

it("keeps RULE_SET_NOT_READY unavailable and never guesses rules from an array", async () => {
  install(
    (url) =>
      url.endsWith("/rules")
        ? json(
            {
              code: "RULE_SET_NOT_READY",
              message: "本轮要求尚未准备完成",
              retryable: false,
            },
            undefined,
            409,
          )
        : undefined,
    false,
  );
  mount();
  await expand();
  expect(await screen.findByText("本轮要求尚未准备完成")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建未映射清单" })).toBeDisabled();
});

it("unknown ACK freezes full scope/body/key/condition and restores identical request after refresh", async () => {
  let fail = true;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST" && fail) throw new TypeError("lost ACK");
    return undefined;
  }, false);
  const ui = mount();
  await expand();
  await selectAuthority();
  await userEvent.click(screen.getByRole("button", { name: "创建未映射清单" }));
  await screen.findByText(/保存结果未知/);
  expect(screen.getByLabelText("权威依据包")).toBeDisabled();
  ui.unmount();
  mount();
  await expand();
  expect(
    await screen.findByRole("button", { name: "重试原清单操作" }),
  ).toBeEnabled();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "重试原清单操作" }));
  await screen.findByText(/已保存要求清单修订 1/);
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
  expect(writes[1].headers.get("If-None-Match")).toBe("*");
});

it("subsequent creation uses current head ETag and a known stale rejection releases only this operation", async () => {
  const { writes } = install((_url, options) =>
    options?.method === "POST"
      ? json(
          { code: "REVISION_CONFLICT", message: "清单变化", retryable: false },
          undefined,
          412,
        )
      : undefined,
  );
  mount();
  await expand();
  await selectAuthority();
  await userEvent.click(screen.getByRole("button", { name: "创建未映射清单" }));
  await screen.findByText("清单变化");
  expect(writes[0].headers.get("If-Match")).toBe('"current"');
  expect(writes[0].headers.get("If-None-Match")).toBeNull();
  await waitFor(() =>
    expect(screen.getByLabelText("权威依据包")).toBeEnabled(),
  );
  expect(
    screen.queryByRole("button", { name: "重试原清单操作" }),
  ).not.toBeInTheDocument();
});

it.each([401, 503])(
  "retains pending operation on unknown/temporary server result %s",
  async (status) => {
    install(
      (_url, options) =>
        options?.method === "POST"
          ? json(
              {
                code: "TEMPORARY",
                message: "需核对",
                retryable: status === 503,
              },
              undefined,
              status,
            )
          : undefined,
      false,
    );
    mount();
    await expand();
    await selectAuthority();
    await userEvent.click(
      screen.getByRole("button", { name: "创建未映射清单" }),
    );
    await screen.findByText(/保存结果未知/);
    expect(screen.getByLabelText("权威依据包")).toBeDisabled();
  },
);

it("does not send when complete pending record cannot be persisted", async () => {
  const { writes } = install(undefined, false);
  mount();
  await expand();
  await selectAuthority();
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  await userEvent.click(screen.getByRole("button", { name: "创建未映射清单" }));
  expect(await screen.findByText(/请求尚未发送/)).toBeInTheDocument();
  expect(writes).toHaveLength(0);
  spy.mockRestore();
});

it("guards foreign inventory manifest rather than showing another bid's statement", async () => {
  install((url) =>
    url === base + "/" + inventoryId
      ? json({ ...frozen, manifest: { ...frozen.manifest, bid_id: id(99) } })
      : undefined,
  );
  mount();
  await expand();
  await userEvent.click(
    await screen.findByRole("button", { name: /读取清单 1/ }),
  );
  expect(await screen.findByText(/清单冻结范围不一致/)).toBeInTheDocument();
  expect(
    screen.queryByText("原规则全文必须保留，不能改成施组摘要"),
  ).not.toBeInTheDocument();
});

it("reads coverage attempt history by explicit ID with missing requirement states left unknown", async () => {
  install((url) => {
    if (url === base + "/" + inventoryId + "/coverage-attempts?limit=20")
      return json(
        page([
          {
            id: attemptId,
            digest: "5".repeat(64),
            created_at: "2026-10-19T00:00:00Z",
          },
        ]),
      );
    if (url === base + "/" + inventoryId + "/coverage-attempts/" + attemptId)
      return json({
        digest: "5".repeat(64),
        manifest: {
          version: "bid-package-coverage/1",
          id: attemptId,
          bid_id: bid,
          inventory_id: inventoryId,
          inventory_digest: frozen.digest,
          package_digest: view.digest,
          actor_id: member,
          results: [],
          assessment: {
            package_digest: view.digest,
            complete: false,
            requirement_inventory_complete: false,
            requirement_states: {},
            requirement_digests: {},
            inspected_ranges: [],
            member_gaps: [],
          },
          review_ready: false,
        },
      });
    return undefined;
  });
  mount();
  await expand();
  await userEvent.click(
    await screen.findByRole("button", { name: /读取清单 1/ }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: /读取范围声明 1/ }),
  );
  expect(await screen.findByText("要求 1：未知")).toBeInTheDocument();
  expect(screen.getByText(/完整核验：否/)).toBeInTheDocument();
});

it("can recover the original lost ACK while the project is now closed", async () => {
  let fail = true;
  const { writes } = install((_url, options) => {
    if (options?.method === "POST" && fail) throw new TypeError("lost ACK");
    return undefined;
  }, false);
  const ui = mount();
  await expand();
  await selectAuthority();
  await userEvent.click(screen.getByRole("button", { name: "创建未映射清单" }));
  await screen.findByText(/保存结果未知/);
  ui.rerender(
    <PackageRequirements
      bidId={bid}
      memberId={member}
      packageView={view}
      disabled
    />,
  );
  fail = false;
  const retry = screen.getByRole("button", { name: "重试原清单操作" });
  expect(retry).toBeEnabled();
  await userEvent.click(retry);
  await screen.findByText(/已保存要求清单修订 1/);
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
});

it.each([422, 428])(
  "does not erase an already unknown command on pre-command rejection %s",
  async (status) => {
    let first = true;
    const { writes } = install((_url, options) => {
      if (options?.method !== "POST") return undefined;
      if (first) {
        first = false;
        throw new TypeError("lost ACK");
      }
      return json(
        {
          code: status === 422 ? "INVALID_REQUEST" : "PRECONDITION_REQUIRED",
          message: "前置请求拒绝",
          retryable: false,
        },
        undefined,
        status,
      );
    }, false);
    mount();
    await expand();
    await selectAuthority();
    await userEvent.click(
      screen.getByRole("button", { name: "创建未映射清单" }),
    );
    await screen.findByText(/保存结果未知/);
    await userEvent.click(
      screen.getByRole("button", { name: "重试原清单操作" }),
    );
    await screen.findByText("前置请求拒绝");
    expect(
      screen.getByRole("button", { name: "重试原清单操作" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("权威依据包")).toBeDisabled();
    expect(writes[1].headers.get("Idempotency-Key")).toBe(
      writes[0].headers.get("Idempotency-Key"),
    );
  },
);

it("does not silently erase a structured original condition or exception", async () => {
  const changed = structuredClone(frozen);
  changed.manifest.requirements[0].rule_snapshot.conditions = [
    { only_when: "报名完成" },
  ];
  install((url) =>
    url === base + "/" + inventoryId ? json(changed) : undefined,
  );
  mount();
  await expand();
  await userEvent.click(
    await screen.findByRole("button", { name: /读取清单 1/ }),
  );
  expect(await screen.findByText("原始条件：记录格式待核")).toBeInTheDocument();
  expect(screen.getByText(/only_when/)).toBeInTheDocument();
  expect(screen.queryByText("原规则未列条件")).not.toBeInTheDocument();
});

it("keeps corruption and another embedded scope locked rather than replacing the pending key", async () => {
  install(undefined, false);
  sessionStorage.setItem(
    `tender:requirements-pending:${member}:${bid}:${packageId}:${target}`,
    JSON.stringify({
      version: 1,
      scope: {
        bidId: id(99),
        memberId: member,
        packageId,
        revisionId: target,
        digest: view.digest,
      },
    }),
  );
  mount();
  await expand();
  expect(
    await screen.findByText(/本地未决操作记录损坏或范围不符/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建未映射清单" })).toBeDisabled();
});

it("appends history pages with the signed cursor and keeps old entries accessible", async () => {
  install((url) => {
    if (url === base + "?limit=20")
      return json(
        {
          items: [
            {
              id: inventoryId,
              digest: frozen.digest,
              created_at: "2026-10-19T00:00:00Z",
            },
          ],
          has_more: true,
          next_cursor: "signed+/cursor",
          current_inventory_id: inventoryId,
        },
        '"current"',
      );
    if (url === base + "?limit=20&cursor=signed%2B%2Fcursor")
      return json({
        ...page([
          {
            id: id(30),
            digest: "6".repeat(64),
            created_at: "2026-10-18T00:00:00Z",
          },
        ]),
        current_inventory_id: inventoryId,
      });
    return undefined;
  });
  mount();
  await expand();
  await userEvent.click(
    await screen.findByRole("button", { name: "更多清单" }),
  );
  expect(
    await screen.findByRole("button", { name: /读取清单 2/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /读取清单 1/ }),
  ).toBeInTheDocument();
});
