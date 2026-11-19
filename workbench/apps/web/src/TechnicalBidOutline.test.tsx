import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringStructure } from "./AuthoringStructure";
import type {
  AuthoringTreeView,
  PackageRequirementInventoryView,
  PackageRequirementInventoryPage,
} from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { jsonDigest } from "./editorSchema";

const f = captureFixture();
const draftId = f.request.target_section.draft_id;
const etag = '"synthetic-draft-head"';
const actionId = "d43187a0-d0da-4490-ab27-1ce0898df2e7";
const chapterId = "d43187a0-d0da-4490-ab27-1ce0898df2e9";
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
  let hasPreview = false;
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
        if (url.pathname.endsWith("/structure/preview")) {
          hasPreview = true;
          return reply(
            {
              action_id: actionId,
              base_draft_revision: tree.draft_revision,
              created_ids: { [body.changes[0].client_key]: chapterId },
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
        if (url.pathname.endsWith("/resolve"))
          return reply({
            state: body.decision === "confirm" ? "applied" : "rejected",
            action_id: actionId,
            draft_id: draftId,
            draft_revision: 5,
            snapshot_id: tree.snapshot_id,
            snapshot_digest: "a".repeat(64),
          });
        return reply({ message: "Unexpected write" }, 404);
      }
      if (url.pathname.endsWith("/structure")) return reply(tree);
      if (url.pathname.includes("/authoring/template-versions/"))
        return reply({
          config: { schema_version: 1, nodes: [] },
          name: "合成目录",
        });
      if (url.pathname.endsWith("/rules"))
        return reply({
          bid_id: f.bidId,
          id: inventory.manifest.rule_set_id,
          rules: [
            {
              id: reference.rule_id,
              statement,
              evidence_ids: reference.rule_snapshot.evidence_ids,
              confirmation:
                hasPreview && mode === "stale" ? "rejected" : "confirmed",
              provenance_status: "effective",
            },
          ],
        });
      for (const name of ["target", "authority"]) {
        const row = f.responses.get(name)!;
        if (
          row.path === url.pathname ||
          row.path.split("/revisions/")[0] === url.pathname
        ) {
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
      if (row?.name === "inventory") return reply(inventory);
      if (row?.name === "inventories") return reply(directory);
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
  return { user, writes, onChanged, digest: inventory.digest };
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

it("previews only additive chapters, then uses the same underlying revision to explicitly apply", async () => {
  const { user, writes, onChanged, digest } = await setup("ok");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  expect(
    await screen.findByRole("checkbox", { name: "施工进度与资源配置" }),
  ).toBeChecked();
  expect(writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "预览追加大纲" }));
  const apply = await screen.findByRole("button", { name: "应用这次变更" });
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    etag,
    body: {
      base_draft_revision: 4,
      changes: [
        {
          op: "add",
          client_key: "technical-bid-" + digest + "-schedule",
          title: "施工进度与资源配置",
          node_type: "chapter",
          ordinal: 0,
          parent: null,
        },
      ],
    },
  });
  await user.click(apply);
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
  expect(writes).toHaveLength(2);
  expect(writes[1]).toMatchObject({ etag, body: { decision: "confirm" } });
});

it("blocks a once-valid outline if a recorded rule is rejected between preview and apply", async () => {
  const { user, writes, onChanged } = await setup("stale");
  await user.click(await screen.findByRole("button", { name: /核对当前清单/ }));
  await user.click(await screen.findByRole("button", { name: "预览追加大纲" }));
  await user.click(await screen.findByRole("button", { name: "应用这次变更" }));
  await screen.findByText(/当前要求清单、来源或确认决定已变更/);
  expect(writes).toHaveLength(1);
  expect(onChanged).not.toHaveBeenCalled();
});

it("does not offer directory changes from a mismatched basis receipt", async () => {
  const { writes } = await setup("foreign");
  await screen.findByText(/包修订的身份或摘要不一致|采集.*核验/);
  expect(
    screen.queryByRole("button", { name: "预览追加大纲" }),
  ).not.toBeInTheDocument();
  expect(writes).toHaveLength(0);
});
