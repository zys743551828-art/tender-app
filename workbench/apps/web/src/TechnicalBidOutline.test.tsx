import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringStructure } from "./AuthoringStructure";
import { technicalOutlineWireContract } from "./contracts";
import type {
  AuthoringTreeView,
  PackageRequirementInventoryView,
  PackageRequirementInventoryPage,
} from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { jsonDigest } from "./editorSchema";
import { outlineSelectionKey } from "./technicalOutlineSelection";

const f = captureFixture();
const draftId = f.request.target_section.draft_id;
const etag = '"synthetic-draft-head"';
const actionId = "d43187a0-d0da-4490-ab27-1ce0898df2e7";
const chapterId = "d43187a0-d0da-4490-ab27-1ce0898df2e9";
const newInventoryId = "33334444-e67a-458c-8751-c5b6947eeb9d";
const newActionId = "d43187a0-d0da-4490-ab27-1ce0898df2e8";
type Schema = {
  $ref?: string;
  type?: string;
  format?: string;
  enum?: string[];
  pattern?: string;
  required?: string[];
  additionalProperties?: boolean;
  properties?: Record<string, Schema>;
  items?: Schema;
  minItems?: number;
  maxItems?: number;
  minimum?: number;
  maximum?: number;
};
const apiRequest = technicalOutlineWireContract.request as Schema;
const outlineSchemas = technicalOutlineWireContract.schemas as Record<
  string,
  Schema
>;
// Validate this small closed schema from the generated, implemented API snapshot,
// not a separate mock of the request property names.
function wireMatches(schema: Schema, value: unknown): boolean {
  if (schema.$ref)
    return wireMatches(outlineSchemas[schema.$ref.split("/").at(-1)!], value);
  if (schema.type === "object") {
    if (!value || typeof value !== "object" || Array.isArray(value))
      return false;
    const row = value as Record<string, unknown>;
    const props = schema.properties!;
    return (
      schema.required?.every((name) => Object.hasOwn(row, name)) === true &&
      Object.keys(row).every((key) =>
        Object.hasOwn(props, key)
          ? wireMatches(props[key], row[key])
          : schema.additionalProperties !== false,
      )
    );
  }
  if (schema.type === "array")
    return (
      Array.isArray(value) &&
      value.length >= (schema.minItems ?? 0) &&
      value.length <= (schema.maxItems ?? Infinity) &&
      value.every((el) => wireMatches(schema.items!, el))
    );
  if (schema.type === "integer")
    return (
      typeof value === "number" &&
      Number.isSafeInteger(value) &&
      value >= (schema.minimum ?? -Infinity) &&
      value <= (schema.maximum ?? Infinity)
    );
  if (schema.type === "string")
    return (
      typeof value === "string" &&
      (!schema.enum || schema.enum.includes(value)) &&
      (!schema.pattern || new RegExp(schema.pattern).test(value)) &&
      (schema.format !== "uuid" ||
        /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value))
    );
  return false;
}
const statement = "工期不超过150天";
const tree: AuthoringTreeView = {
  draft_id: draftId,
  draft_revision: 4,
  snapshot_id: f.request.target_section.snapshot_id,
  structure_version_id: null,
  nodes: [],
  directory_template_version_id: f.request.target_section.section_id,
  style_template_version_id: f.request.target_section.section_id,
  metadata: {},
  page_budget: {
    planned_total: 0,
    unknown_section_ids: [],
    actual_total: null,
    actual_ranges_state: "unknown",
  },
};
function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ETag: etag },
  });
}

async function setup(mode: "ok" | "stale" | "foreign") {
  const inventory = structuredClone(
    f.body<PackageRequirementInventoryView>("inventory"),
  );
  const directory = structuredClone(
    f.body<PackageRequirementInventoryPage>("inventories"),
  );
  const reference = inventory.manifest.requirements[0];
  reference.rule_snapshot.statement = statement;
  inventory.digest = await jsonDigest(inventory.manifest);
  directory.items[0].digest = inventory.digest;
  const nextInventory = structuredClone(inventory);
  nextInventory.manifest.id = newInventoryId;
  nextInventory.manifest.revision += 1;
  nextInventory.manifest.predecessor_digest = inventory.digest;
  nextInventory.digest = await jsonDigest(nextInventory.manifest);
  const nextDirectory = structuredClone(directory);
  nextDirectory.current_inventory_id = newInventoryId;
  nextDirectory.items[0] = {
    ...directory.items[0],
    id: newInventoryId,
    digest: nextInventory.digest,
  };
  let superseded = false;
  let supersedeAuthority = false;
  let pageCurrentInventoryLater = false;

  const reads: string[] = [];
  const writes: { path: string; etag: string | null; body: unknown }[] = [];
  const onChanged = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, window.location.href);
      if (init.method === "POST") {
        const body = JSON.parse(init.body as string);
        writes.push({
          path: url.pathname,
          etag: new Headers(init.headers).get("If-Match"),
          body,
        });
        if (url.pathname.endsWith("/technical-outline/preview")) {
          if (!wireMatches(apiRequest, body))
            return reply(
              { code: "INVALID_REQUEST", message: "真实大纲接口结构不匹配" },
              422,
            );
          const chosen = superseded ? nextInventory : inventory;
          if (
            body.basis.inventory.id !== chosen.manifest.id ||
            body.basis.inventory.digest !== chosen.digest
          )
            return reply(
              {
                code: "TECHNICAL_OUTLINE_BASIS_STALE",
                message: "请重新选择清单",
              },
              409,
            );

          return reply(
            {
              action_id: superseded ? newActionId : actionId,
              base_draft_revision: tree.draft_revision,
              created_ids: {
                ["technical-bid-" + chosen.digest + "-schedule"]: chapterId,
              },
              plan_suggestions: {},
              before: [],
              after: [
                {
                  section_id: chapterId,
                  parent_id: null,
                  ordinal: 0,
                  deleted: false,
                  node_type: "chapter",
                },
              ],
              before_sections: {},
              after_sections: {
                [chapterId]: {
                  type: "doc",
                  attrs: { title: "施工进度与资源配置" },
                  content: [],
                },
              },
              directory_template_version_id: tree.directory_template_version_id,
              style_template_version_id: tree.style_template_version_id,
              deletion_impact: [],
              format_report: null,
              expires_in_seconds: 300,
            },
            201,
          );
        }
        if (url.pathname.endsWith("/resolve")) {
          if (mode === "stale" && body.decision === "confirm" && !superseded) {
            superseded = true;
            return reply(
              {
                code: "TECHNICAL_OUTLINE_BASIS_STALE",
                message:
                  "大纲的投标包、依据包、要求清单或确认已变化，请重新选择当前依据并预览。",
              },
              409,
            );
          }
          return reply({
            state: body.decision === "confirm" ? "applied" : "rejected",
            action_id: actionId,
            draft_id: draftId,
            draft_revision: 5,
            snapshot_id: tree.snapshot_id,
            snapshot_digest: "a".repeat(64),
          });
        }
        return reply({ message: "Unexpected write" }, 404);
      }
      reads.push(url.pathname);
      if (url.pathname.endsWith("/structure")) return reply(tree);
      if (url.pathname.includes("/authoring/template-versions/"))
        return reply({
          config: { schema_version: 1, nodes: [] },
          name: "合成目录",
        });
      if (url.pathname.endsWith("/rules")) return reply({ rules: [] });
      for (const name of ["target", "authority"]) {
        const row = f.responses.get(name)!;
        if (
          row.path === url.pathname ||
          row.path.split("/revisions/")[0] === url.pathname
        ) {
          if (
            supersedeAuthority &&
            name === "authority" &&
            row.path !== url.pathname
          ) {
            const changed = structuredClone(
              f.body<{
                manifest: { revision_id: string };
                digest: string;
              }>(name),
            );
            changed.manifest.revision_id = chapterId;
            changed.digest = await jsonDigest(changed.manifest);
            return reply(changed);
          }
          if (mode === "foreign" && name === "authority") {
            const foreign = structuredClone(
              f.body<{
                manifest: { scope: { lot_id: string } };
                digest: string;
              }>(name),
            );
            const head = structuredClone(
              f.body<{ items: { digest: string }[] }>("authority_heads"),
            );
            foreign.manifest.scope.lot_id = chapterId;
            foreign.digest = await jsonDigest(foreign.manifest);
            // A receipt with mismatched confirmed digest must not reach outline generation.
            expect(foreign.digest).not.toBe(head.items[0].digest);
            return reply(foreign);
          }
          return reply(row.body);
        }
      }
      const row = f.bundle.responses.find(
        (r) =>
          r.path === url.pathname &&
          Object.entries(r.query).every(
            ([key, value]) => url.searchParams.get(key) === String(value),
          ),
      );
      if (
        superseded &&
        url.pathname.endsWith("/requirement-inventories/" + newInventoryId)
      )
        return reply(nextInventory);
      if (row?.name === "inventory") return reply(inventory);
      if (row?.name === "inventories") {
        if (pageCurrentInventoryLater && !url.searchParams.has("cursor")) {
          return reply({
            ...directory,
            items: [
              {
                ...directory.items[0],
                id: newInventoryId,
                digest: nextInventory.digest,
              },
            ],
            has_more: true,
            next_cursor: "synthetic-next",
          });
        }
        return reply(superseded ? nextDirectory : directory);
      }
      if (row) return reply(row.body, row.status);
      return reply({ items: [], next_cursor: null });
    }),
  );

  const user = userEvent.setup();
  render(
    <AuthoringStructure
      bidId={f.bidId}
      memberId={f.memberId}
      draftId={draftId}
      draftRevision={tree.draft_revision}
      sectionId={undefined}
      disabled={false}
      onChoose={vi.fn().mockResolvedValue(undefined)}
      prepare={vi.fn().mockResolvedValue({
        etag,
        data: {
          id: draftId,
          bid_id: f.bidId,
          revision: tree.draft_revision,
          snapshot_id: tree.snapshot_id,
        },
      })}
      onChanged={onChanged}
      onBusy={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "生成技术标大纲" }),
  );
  for (const [name, ref] of [
    ["目标投标包", f.request.package_context.target],
    ["招标与补遗依据包", f.request.package_context.authority],
  ] as const) {
    const group = within(screen.getByRole("group", { name }));
    await waitFor(() => expect(group.getAllByRole("option")).toHaveLength(2));
    await user.selectOptions(group.getByRole("combobox"), ref.package_id);
    await user.click(await group.findByRole("button", { name: /选择第 1 版/ }));
  }
  return {
    user,
    writes,
    reads,
    onChanged,
    digest: inventory.digest,
    nextDigest: nextInventory.digest,
    pageInventoryLater: () => {
      pageCurrentInventoryLater = true;
    },
    moveAuthorityHead: () => {
      supersedeAuthority = true;
    },
  };
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

it("previews only additive chapters, then uses the same underlying revision to explicitly apply", async () => {
  const { user, writes, onChanged, digest } = await setup("ok");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  expect(
    await screen.findByRole("checkbox", { name: "施工进度与资源配置" }),
  ).toBeChecked();
  expect(
    screen.getByText(/需要核对本章计划版本、所选原页和要求/),
  ).toBeVisible();
  expect(
    screen.queryByText(/请在“章节计划”补写条款与引用/),
  ).not.toBeInTheDocument();
  await user.click(screen.getByText(/技术要求与已存章节对照/));
  expect(screen.getByText("尚无保存的章节关联")).toBeInTheDocument();
  expect(screen.getByText(/不能当作覆盖率或审批/)).toBeInTheDocument();
  expect(writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "预览追加大纲" }));
  const apply = await screen.findByRole("button", { name: "应用这次变更" });
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    path: `/api/v1/bids/${f.bidId}/drafts/${draftId}/technical-outline/preview`,
    etag,
    body: {
      base_draft_revision: 4,
      basis: {
        target: {
          package_id: f.request.package_context.target.package_id,
          revision_id: f.request.package_context.target.revision_id,
          digest: f.request.package_context.target.manifest_digest,
        },
        authority: {
          package_id: f.request.package_context.authority.package_id,
          revision_id: f.request.package_context.authority.revision_id,
          digest: f.request.package_context.authority.manifest_digest,
        },
        inventory: { id: f.request.package_context.inventory.id, digest },
      },
      chapter_keys: ["schedule"],
    },
  });
  await user.click(apply);
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
  expect(writes).toHaveLength(2);
  expect(writes[1]).toMatchObject({ etag, body: { decision: "confirm" } });
});

it("blocks a once-valid outline if a recorded rule is rejected between preview and apply", async () => {
  const { user, writes, onChanged, nextDigest } = await setup("stale");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  await user.click(await screen.findByRole("button", { name: "预览追加大纲" }));
  await user.click(await screen.findByRole("button", { name: "应用这次变更" }));
  await screen.findByText(/大纲的投标包、依据包、要求清单或确认已变化/);
  expect(writes).toHaveLength(2);
  expect(onChanged).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "放弃这次变更" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
  expect(writes[2].body).toEqual({ decision: "reject" });
  await user.click(screen.getByRole("button", { name: "收起技术标大纲" }));
  await user.click(screen.getByRole("button", { name: "生成技术标大纲" }));
  await screen.findByText(/先前清单不是目前核到的版本/);
  expect(screen.queryByText(/技术要求与已存章节对照/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "预览追加大纲" }),
  ).not.toBeInTheDocument();
  expect(writes).toHaveLength(3);
  await user.click(screen.getByRole("button", { name: "刷新要求清单" }));
  await user.click(
    await screen.findByRole("button", { name: /核对当前清单 · 33334444/ }),
  );
  await user.click(await screen.findByRole("button", { name: "预览追加大纲" }));
  await screen.findByRole("button", { name: "应用这次变更" });
  expect(writes[3].body).toMatchObject({
    basis: { inventory: { id: newInventoryId, digest: nextDigest } },
  });
  expect(writes).toHaveLength(4);
});

it("does not offer directory changes from a mismatched basis receipt", async () => {
  const { writes } = await setup("foreign");
  await screen.findByText(/包修订的身份或摘要不一致|采集.*核验/);
  expect(
    screen.queryByRole("button", { name: "预览追加大纲" }),
  ).not.toBeInTheDocument();
  expect(writes).toHaveLength(0);
});

it("restores only checked references, rereads them and permits forgetting without a write", async () => {
  const { user, writes, reads, digest } = await setup("ok");
  const key = outlineSelectionKey({
    memberId: f.memberId,
    bidId: f.bidId,
    draftId,
  });
  expect(sessionStorage.getItem(key)).toBeNull();
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  await screen.findByRole("checkbox", { name: "施工进度与资源配置" });
  expect(JSON.parse(sessionStorage.getItem(key) ?? "null")?.basis).toEqual({
    target: f.request.package_context.target,
    authority: f.request.package_context.authority,
    inventory: { id: f.request.package_context.inventory.id, digest },
  });
  await user.click(screen.getByRole("button", { name: "收起技术标大纲" }));
  reads.length = 0;
  await user.click(screen.getByRole("button", { name: "生成技术标大纲" }));
  await screen.findByText(/已按原身份重新核对本次会话记住的包和清单/);
  for (const ref of [
    f.request.package_context.target,
    f.request.package_context.authority,
  ])
    expect(reads).toContain(
      `/api/v1/bids/${f.bidId}/packages/${ref.package_id}`,
    );
  expect(reads.some((path) => path.endsWith("/requirement-inventories"))).toBe(
    true,
  );
  expect(
    reads.some((path) =>
      path.endsWith(
        "/requirement-inventories/" + f.request.package_context.inventory.id,
      ),
    ),
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "清除已记住的选择" }));
  expect(sessionStorage.getItem(key)).toBeNull();
  await user.click(screen.getByRole("button", { name: "收起技术标大纲" }));
  await user.click(screen.getByRole("button", { name: "生成技术标大纲" }));
  expect(screen.queryByText(/本次会话/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "预览追加大纲" }),
  ).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});

it("retains a historical authority selection but blocks its use when the current head has advanced", async () => {
  const { user, writes, reads, moveAuthorityHead } = await setup("ok");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  await screen.findByRole("checkbox", { name: "施工进度与资源配置" });
  moveAuthorityHead();
  await user.click(screen.getByRole("button", { name: "收起技术标大纲" }));
  reads.length = 0;
  await user.click(screen.getByRole("button", { name: "生成技术标大纲" }));
  await screen.findByText(/原包修订可能不再是当前版本/);
  expect(reads.some((path) => path.includes("/requirement-inventories"))).toBe(
    false,
  );
  expect(
    screen.queryByRole("button", { name: "预览追加大纲" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/已按原身份重新核对/)).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});

it("rereads the exact current inventory even when its directory row is not on the first page", async () => {
  const { user, writes, reads, pageInventoryLater } = await setup("ok");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  await screen.findByRole("checkbox", { name: "施工进度与资源配置" });
  pageInventoryLater();
  await user.click(screen.getByRole("button", { name: "收起技术标大纲" }));
  reads.length = 0;
  await user.click(screen.getByRole("button", { name: "生成技术标大纲" }));
  await screen.findByText(/已按原身份重新核对/);
  expect(
    reads.some((path) =>
      path.endsWith(
        "/requirement-inventories/" + f.request.package_context.inventory.id,
      ),
    ),
  ).toBe(true);
  expect(
    screen.queryByText(/先前清单不是目前核到的版本/),
  ).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});
