import { useEffect } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageCoverageWorkspace } from "./PackageCoverageWorkspace";
import type {
  BidPackageStoredView,
  CreatePackageCoverageAttempt,
  PackageRequirementInventoryView,
} from "./contracts";

// The editor has separate range/evidence tests. This boundary uses the real HTTP client.
vi.mock("./CoverageEditor", () => ({
  CoverageEditor: ({
    disabled,
    initialResults,
    onChange,
  }: {
    disabled: boolean;
    initialResults: CreatePackageCoverageAttempt["results"];
    onChange: (v: unknown) => void;
  }) => {
    useEffect(() => {
      if (initialResults.length)
        onChange({ results: initialResults, valid: true, dirty: true });
    }, [initialResults, onChange]);
    return (
      <button
        disabled={disabled}
        onClick={() =>
          onChange({ results: [observation], valid: true, dirty: true })
        }
      >
        填写合成人工观察
      </button>
    );
  },
}));
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const bid = id(1),
  member = id(2),
  ownId = id(3),
  ownRev = id(4),
  invId = id(5),
  rule = id(6),
  authorityRev = id(7);
const scope = {
  bid_id: bid,
  engineering_project_id: id(8),
  lot_id: id(9),
  round_id: id(10),
  bidder_id: id(11),
  bidder_status: "confirmed",
};
const own = {
  manifest: {
    kind: "bid",
    package_id: ownId,
    revision_id: ownRev,
    scope,
    members: [
      {
        parts: [
          {
            part_id: "技术正文",
            category: "技术",
            first_page: 1,
            last_page: 3,
          },
        ],
      },
    ],
  },
  digest: "a".repeat(64),
} as unknown as BidPackageStoredView;
const authority = {
  manifest: {
    kind: "authority",
    package_id: id(12),
    revision_id: authorityRev,
    scope,
    members: [],
  },
  digest: "b".repeat(64),
} as unknown as BidPackageStoredView;
const inventory = {
  manifest: {
    id: invId,
    bid_id: bid,
    package_id: ownId,
    target_revision_id: ownRev,
    package_digest: own.digest,
    authority_revision_id: authorityRev,
    authority_digest: authority.digest,
    revision: 3,
    requirements: [
      {
        rule_id: rule,
        requirement_digest: "d".repeat(64),
        requirement: {
          requirement_id: rule,
          scope,
          categories: ["技术"],
          target_part_ids: ["技术正文"],
        },
      },
    ],
  },
  digest: "c".repeat(64),
} as unknown as PackageRequirementInventoryView;
const observation: CreatePackageCoverageAttempt["results"][number] = {
  rule_id: rule,
  requirement_digest: "d".repeat(64),
  state: "missing",
  inspected: [{ part_id: "技术正文", first_page: 1, last_page: 2 }],
  evidence_ids: [],
  reason: "合成缺项观察",
  basis_type: "human_observation",
};
const storage = `tender:coverage-pending:${member}:${bid}:${ownId}:${ownRev}`;
const endpoint = `/api/v1/bids/${bid}/packages/${ownId}/revisions/${ownRev}/requirement-inventories/${invId}/coverage-attempts`;
const props = {
  bidId: bid,
  memberId: member,
  packageView: own,
  authorityView: authority,
  inventory,
  currentInventoryId: invId,
  currentKnown: true,
  disabled: false,
  onSaved: vi.fn(),
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function saved(body: CreatePackageCoverageAttempt) {
  return {
    digest: "e".repeat(64),
    manifest: {
      id: id(20),
      bid_id: bid,
      actor_id: member,
      inventory_id: invId,
      inventory_digest: body.inventory_digest,
      package_digest: body.package_digest,
      review_ready: false,
      assessment: {
        complete: false,
        requirement_inventory_complete: false,
        package_digest: body.package_digest,
        requirement_states: Object.fromEntries(
          inventory.manifest.requirements.map((binding) => [
            binding.rule_id,
            body.results.find((row) => row.rule_id === binding.rule_id)
              ?.state ?? "unknown",
          ]),
        ),
        requirement_digests: Object.fromEntries(
          inventory.manifest.requirements.map((binding) => [
            binding.rule_id,
            binding.requirement_digest,
          ]),
        ),
      },
      results: body.results.map((r) => ({
        basis_type: r.basis_type,
        evidence_ids: r.evidence_ids,
        coverage: {
          requirement_id: r.rule_id,
          package_digest: body.package_digest,
          evidence_refs: r.evidence_ids.map((id) => `evidence:${id}`),
          requirement_digest: r.requirement_digest,
          state: r.state,
          reason: r.reason,
          // JSONB replay may reorder object keys without changing the request.
          inspected: r.inspected.map((p) => ({
            last_page: p.last_page,
            part_id: p.part_id,
            first_page: p.first_page,
          })),
        },
      })),
    },
  };
}
function install(
  handler?: (
    body: CreatePackageCoverageAttempt,
    index: number,
  ) => Promise<Response> | Response,
) {
  const writes: {
    url: string;
    body: CreatePackageCoverageAttempt;
    headers: Headers;
  }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit) => {
      const body = JSON.parse(
        String(init.body),
      ) as CreatePackageCoverageAttempt;
      writes.push({
        url: String(input),
        body,
        headers: new Headers(init.headers),
      });
      return handler
        ? handler(body, writes.length)
        : response(saved(body), 201);
    }),
  );
  return writes;
}
async function fill() {
  await userEvent.click(
    screen.getByRole("button", { name: "开始填写本次人工范围记录" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "填写合成人工观察" }),
  );
}
beforeEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
  props.onSaved.mockClear();
});

it("reports actual unsent edits and clears only the draft guard on explicit cancel or a verified save", async () => {
  const writes = install(),
    dirty = vi.fn(),
    pending = vi.fn();
  render(
    <PackageCoverageWorkspace
      {...props}
      onDirtyChange={dirty}
      onPendingChange={pending}
    />,
  );
  expect(dirty).toHaveBeenLastCalledWith(false);
  await fill();
  expect(dirty).toHaveBeenLastCalledWith(true);
  await userEvent.click(
    screen.getByRole("button", { name: "放弃未发送或已明确失败的填写" }),
  );
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(writes).toHaveLength(0);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/已保存本次人工范围记录/);
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  expect(pending).toHaveBeenLastCalledWith(false);
});

it("does not release an unknown original command when its selected inventory changes", async () => {
  install(async () => {
    throw new TypeError("synthetic lost ACK");
  });
  const pending = vi.fn(),
    dirty = vi.fn();
  const view = render(
    <PackageCoverageWorkspace
      {...props}
      onDirtyChange={dirty}
      onPendingChange={pending}
    />,
  );
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/保存结果未知/);
  const original = sessionStorage.getItem(storage);
  view.rerender(
    <PackageCoverageWorkspace
      {...props}
      inventory={null}
      onDirtyChange={dirty}
      onPendingChange={pending}
    />,
  );
  expect(pending).toHaveBeenLastCalledWith(true);
  expect(sessionStorage.getItem(storage)).toBe(original);
  expect(
    screen.getByRole("button", { name: "放弃未发送或已明确失败的填写" }),
  ).toBeDisabled();
});

it("requires explicit start and saves exact digest-bound observations without inventing an ETag", async () => {
  const writes = install();
  render(<PackageCoverageWorkspace {...props} />);
  expect(writes).toHaveLength(0);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/已保存本次人工范围记录/);
  expect(writes).toHaveLength(1);
  expect(writes[0].url).toBe(endpoint);
  expect(writes[0].body).toEqual({
    inventory_digest: inventory.digest,
    package_digest: own.digest,
    results: [observation],
  });
  expect(writes[0].headers.has("If-Match")).toBe(false);
  expect(writes[0].headers.has("If-None-Match")).toBe(false);
  expect(props.onSaved).toHaveBeenCalledWith(invId, id(20));
  expect(sessionStorage.getItem(storage)).toBeNull();
});
it("restores a lost ACK with the original path/body/key even after selection and project state change", async () => {
  const writes = install(async (body, n) => {
    if (n === 1) throw new TypeError("lost ACK");
    return response(saved(body), 201);
  });
  const ui = render(<PackageCoverageWorkspace {...props} />);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/保存结果未知/);
  expect(
    screen.getByRole("button", { name: "放弃未发送或已明确失败的填写" }),
  ).toBeDisabled();
  ui.unmount();
  const other = structuredClone(inventory);
  other.manifest.id = id(30);
  other.digest = "f".repeat(64);
  render(
    <PackageCoverageWorkspace
      {...props}
      inventory={other}
      authorityView={null}
      currentInventoryId={other.manifest.id}
      disabled
    />,
  );
  const retry = await screen.findByRole("button", {
    name: "重试原人工范围操作",
  });
  expect(retry).toBeEnabled();
  await userEvent.click(retry);
  await screen.findByText(/已保存本次人工范围记录/);
  expect(writes[1].url).toBe(endpoint);
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].headers.get("Idempotency-Key")).toBe(
    writes[0].headers.get("Idempotency-Key"),
  );
});
it.each([401, 503, 422, 428, 409])(
  "keeps an already unknown operation locked on generic rejection %s",
  async (status) => {
    const writes = install(async (_body, n) => {
      if (n === 1) throw new TypeError("lost ACK");
      return response(
        {
          code: status === 422 ? "INVALID_REQUEST" : "REQUEST_FAILED",
          message: "前置拒绝",
          retryable: false,
        },
        status,
      );
    });
    render(<PackageCoverageWorkspace {...props} />);
    await fill();
    await userEvent.click(
      screen.getByRole("button", { name: "保存本次人工范围记录" }),
    );
    await screen.findByText(/保存结果未知/);
    await userEvent.click(
      screen.getByRole("button", { name: "重试原人工范围操作" }),
    );
    await screen.findByText("前置拒绝");
    expect(sessionStorage.getItem(storage)).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "放弃未发送或已明确失败的填写" }),
    ).toBeDisabled();
    expect(writes[1].headers.get("Idempotency-Key")).toBe(
      writes[0].headers.get("Idempotency-Key"),
    );
  },
);
it("does not send when persistence fails", async () => {
  const writes = install();
  render(<PackageCoverageWorkspace {...props} />);
  await fill();
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/请求尚未发送/);
  expect(writes).toHaveLength(0);
  spy.mockRestore();
});
it("preserves input after an explicit stale inventory rejection and never silently targets the new head", async () => {
  const writes = install(() =>
    response(
      {
        code: "PACKAGE_REQUIREMENT_INVENTORY_STALE",
        message: "清单已变化",
        retryable: false,
      },
      409,
    ),
  );
  const ui = render(<PackageCoverageWorkspace {...props} />);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText("清单已变化");
  expect(sessionStorage.getItem(storage)).toBeNull();
  ui.rerender(
    <PackageCoverageWorkspace {...props} currentInventoryId={id(30)} />,
  );
  expect(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  ).toBeDisabled();
  expect(writes).toHaveLength(1);
  await userEvent.click(
    screen.getByRole("button", { name: "放弃未发送或已明确失败的填写" }),
  );
  expect(
    screen.getByRole("button", { name: "开始填写本次人工范围记录" }),
  ).toBeDisabled();
});
it("retains an identity-inconsistent success as unknown instead of accepting another inventory's ACK", async () => {
  install((body) => {
    const wrong = saved(body);
    wrong.manifest.inventory_id = id(31);
    return response(wrong, 201);
  });
  render(<PackageCoverageWorkspace {...props} />);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/响应身份或内容不一致/);
  expect(sessionStorage.getItem(storage)).not.toBeNull();
  expect(props.onSaved).not.toHaveBeenCalled();
});
it.each(["lot", "body", "key", "json"])(
  "locks malformed recovery %s without writing a new request",
  async (kind) => {
    const record = {
      version: 1,
      scope: {
        bidId: bid,
        memberId: member,
        packageId: ownId,
        revisionId: ownRev,
        digest: own.digest,
      },
      context: {
        inventory: structuredClone(inventory),
        authority: structuredClone(authority),
      },
      key: id(40),
      body: {
        inventory_digest: inventory.digest,
        package_digest: own.digest,
        results: [observation],
      },
    };
    if (kind === "lot") record.context.authority.manifest.scope.lot_id = id(41);
    if (kind === "body") record.body.package_digest = "9".repeat(64);
    if (kind === "key") record.key = "bad";
    sessionStorage.setItem(
      storage,
      kind === "json" ? "{" : JSON.stringify(record),
    );
    const writes = install();
    render(<PackageCoverageWorkspace {...props} />);
    expect(
      await screen.findByText(/本地未决范围记录损坏或范围不符/),
    ).toBeInTheDocument();
    expect(writes).toHaveLength(0);
    expect(
      screen.getByRole("button", { name: "开始填写本次人工范围记录" }),
    ).toBeDisabled();
  },
);
it("never starts from a historical inventory or a mismatching authority digest", () => {
  install();
  const ui = render(
    <PackageCoverageWorkspace {...props} currentInventoryId={id(33)} />,
  );
  expect(
    screen.getByRole("button", { name: "开始填写本次人工范围记录" }),
  ).toBeDisabled();
  const wrong = structuredClone(authority);
  wrong.digest = "8".repeat(64);
  ui.rerender(<PackageCoverageWorkspace {...props} authorityView={wrong} />);
  expect(
    screen.getByRole("button", { name: "开始填写本次人工范围记录" }),
  ).toBeDisabled();
});
it.each([
  "actor",
  "coverage-package",
  "evidence-refs",
  "completeness",
  "assessment-package",
  "assessment-digest",
  "assessment-state",
])("does not accept a mismatched success field %s", async (kind) => {
  install((body) => {
    const wrong = saved(body);
    if (kind === "actor") wrong.manifest.actor_id = id(55);
    if (kind === "coverage-package")
      wrong.manifest.results[0].coverage.package_digest = "9".repeat(64);
    if (kind === "evidence-refs")
      wrong.manifest.results[0].coverage.evidence_refs = [`evidence:${id(55)}`];
    if (kind === "completeness")
      wrong.manifest.assessment.requirement_inventory_complete = true;
    if (kind === "assessment-package")
      wrong.manifest.assessment.package_digest = "8".repeat(64);
    if (kind === "assessment-digest")
      wrong.manifest.assessment.requirement_digests[rule] = "8".repeat(64);
    if (kind === "assessment-state")
      wrong.manifest.assessment.requirement_states[rule] = "verified";
    return response(wrong, 201);
  });
  render(<PackageCoverageWorkspace {...props} />);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/响应身份或内容不一致/);
  expect(sessionStorage.getItem(storage)).not.toBeNull();
  expect(props.onSaved).not.toHaveBeenCalled();
});
it("rejects a response that merges a previous conclusion for a requirement omitted from this attempt", async () => {
  const expanded = structuredClone(inventory);
  const other = structuredClone(expanded.manifest.requirements[0]);
  other.rule_id = id(60);
  other.requirement.requirement_id = id(60);
  other.requirement_digest = "6".repeat(64);
  expanded.manifest.requirements.push(other);
  install((body) => {
    const wrong = saved(body);
    wrong.manifest.assessment.requirement_digests[id(60)] =
      other.requirement_digest;
    wrong.manifest.assessment.requirement_states[id(60)] = "verified";
    return response(wrong, 201);
  });
  render(<PackageCoverageWorkspace {...props} inventory={expanded} />);
  await fill();
  await userEvent.click(
    screen.getByRole("button", { name: "保存本次人工范围记录" }),
  );
  await screen.findByText(/响应身份或内容不一致/);
  expect(sessionStorage.getItem(storage)).not.toBeNull();
  expect(props.onSaved).not.toHaveBeenCalled();
});
