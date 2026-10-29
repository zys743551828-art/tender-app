// Synthetic navigation-only transport. Original-byte and business acceptance remain separate.
import { vi } from "vitest";
import type { Bid, BidPackageDocument, BidPackageHeadPage } from "./contracts";
import {
  submissionFixture,
  submissionId as id,
  submissionScope,
} from "./packageSubmissionFixtures.test-support";
import { jsonDigest } from "./editorSchema";

export const navResponse = (
  data: unknown,
  status = 200,
  headers: Record<string, string> = {},
) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
export async function navigationFixture() {
  const f = await submissionFixture(true),
    inventory = f.selection.inventory!,
    authority = f.selection.authority!;
  const target = {
    packageId: f.target.manifest.package_id,
    revisionId: f.target.manifest.revision_id,
    inventoryId: inventory.manifest.id,
  };
  const base = `/api/v1/bids/${submissionScope.bidId}/packages/${target.packageId}/revisions/${target.revisionId}`;
  const page: BidPackageHeadPage = {
    items: [
      {
        id: target.packageId,
        bid_id: submissionScope.bidId,
        kind: "bid",
        revision_id: target.revisionId,
        revision: f.target.manifest.revision,
        digest: f.target.digest,
      },
    ],
    has_more: false,
    next_cursor: null,
  };
  const doc: BidPackageDocument = {
    id: f.target.manifest.members[0].document_version_id,
    bid_id: submissionScope.bidId,
    file_id: id(720),
    file_revision: 1,
    filename: "合成技术册.pdf",
    role: "body",
    artifact_kind: "bid_body",
    sha256: f.target.manifest.members[0].file_digest,
    verified_upload: true,
  };
  const identity = f.target.identity;
  if (identity.identity_version !== "bid-identity/2")
    throw new Error("Navigation fixture requires an exact v2 bid identity.");
  const bid: Bid = {
    id: submissionScope.bidId,
    title: "合成整包导航项目",
    revision: 1,
    material_revision: 1,
    presentation_revision: 1,
    phase: "working",
    archived_at: null,
    current_body_id: null,
    current_review_id: null,
    stream_id: id(721),
    identity,
    next_action: {
      action: "start_review",
      reason: "旧单稿建议",
      target_url: `/bids/${submissionScope.bidId}/review`,
      blocked: false,
    },
  };
  const server = {
    page,
    bid,
    package: f.target,
    inventory,
    reads: [] as string[],
    writes: [] as { path: string; options: RequestInit }[],
    onRead: null as
      | ((path: string) => Response | Promise<Response> | null)
      | null,
    onWrite: null as
      | ((path: string, options: RequestInit) => Promise<Response>)
      | null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const path = String(input);
      if (options?.method === "POST") {
        server.writes.push({ path, options });
        if (server.onWrite) return server.onWrite(path, options);
        throw new Error(`Unexpected navigation write ${path}`);
      }
      server.reads.push(path);
      const overridden = server.onRead?.(path);
      if (overridden) return overridden;
      if (path === "/api/v1/auth/session")
        return navResponse({
          member: {
            id: submissionScope.memberId,
            display_name: "合成成员",
            active: true,
          },
          csrf_token: "synthetic",
          expires_at: "2099-01-01T00:00:00Z",
        });
      if (path === `/api/v1/bids/${submissionScope.bidId}`)
        return navResponse(server.bid);
      if (path.endsWith("/review-state"))
        return navResponse({
          bid_id: submissionScope.bidId,
          revision: 1,
          current_body_id: null,
          material_revision: 1,
          current_material_snapshot_id: null,
          current_rule_set_id: null,
          request: null,
          current_review: null,
        });
      if (path.endsWith("/settings"))
        return navResponse({
          bid_id: submissionScope.bidId,
          settings: { pricing: false },
        });
      if (path.includes("/packages?kind=bid")) return navResponse(server.page);
      if (path.includes("/packages?kind=authority"))
        return navResponse({
          items: [
            {
              id: authority.manifest.package_id,
              bid_id: submissionScope.bidId,
              kind: "authority",
              revision_id: authority.manifest.revision_id,
              revision: authority.manifest.revision,
              digest: authority.digest,
            },
          ],
          has_more: false,
          next_cursor: null,
        });
      if (path.includes("/package-documents"))
        return navResponse({
          items: [doc],
          has_more: false,
          next_cursor: null,
        });
      if (
        path === base ||
        path ===
          `/api/v1/bids/${submissionScope.bidId}/packages/${target.packageId}`
      )
        return navResponse(server.package, 200, {
          ETag: `"bid-package:${target.packageId}:${server.package.digest}"`,
        });
      if (
        path ===
        `/api/v1/bids/${submissionScope.bidId}/packages/${target.packageId}/revisions?limit=20`
      )
        return navResponse({
          items: [
            {
              id: target.revisionId,
              package_id: target.packageId,
              revision: 1,
              digest: f.target.digest,
              created_at: "2025-01-01T00:00:00Z",
            },
          ],
          has_more: false,
          next_cursor: null,
        });
      if (path === base + "/requirement-inventories?limit=20")
        return navResponse(
          {
            items: [
              {
                id: inventory.manifest.id,
                digest: inventory.digest,
                created_at: "2025-01-01T00:00:00Z",
              },
            ],
            current_inventory_id: inventory.manifest.id,
            has_more: false,
            next_cursor: null,
          },
          200,
          {
            ETag: `"requirement-inventory:${target.revisionId}:${inventory.digest}"`,
          },
        );
      if (path === base + `/requirement-inventories/${inventory.manifest.id}`)
        return navResponse(server.inventory, 200, {
          ETag: `"requirement-inventory:${target.revisionId}:${server.inventory.digest}"`,
        });
      if (path.endsWith("/coverage-attempts?limit=20"))
        return navResponse({ items: [], has_more: false, next_cursor: null });
      if (path.endsWith("/rules"))
        return navResponse({
          id: inventory.manifest.rule_set_id,
          bid_id: submissionScope.bidId,
          rules: [],
        });
      if (path.endsWith("/materials"))
        return navResponse({ documents: [], conflicts: [] });
      if (path.endsWith("/parses?limit=20"))
        return navResponse({ items: [], has_more: false, next_cursor: null });
      return navResponse(
        {
          code: "SYNTHETIC_ROUTE_UNAVAILABLE",
          message: `本导航夹具未配置 ${path}`,
        },
        503,
      );
    }),
  );
  async function acceptedPackage(options: RequestInit) {
    const body = JSON.parse(String(options.body));
    const stored = structuredClone(f.target);
    stored.manifest.members = body.members.map(
      (member: (typeof stored.manifest.members)[number]) => ({
        ...f.target.manifest.members[0],
        ...member,
        parse: {
          ...f.target.manifest.members[0].parse,
          status: "unknown",
          parse_run_id: null,
        },
        page_count: null,
      }),
    );
    stored.digest = await jsonDigest(stored.manifest);
    server.package = stored;
    return navResponse(stored, 201, {
      ETag: `"bid-package:${target.packageId}:${stored.digest}"`,
    });
  }
  return {
    f,
    inventory,
    authority,
    target,
    base,
    page,
    doc,
    bid,
    server,
    acceptedPackage,
    scope: submissionScope,
  };
}
