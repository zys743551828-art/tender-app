import { beforeEach, expect, it } from "vitest";
import { ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import { clearRecordedCommands } from "./recordedCommandStorage";
import { technicalFixture } from "./packageTechnicalScopeFixtures.test-support";
import httpFixture from "./test-fixtures/technical-scope-http.json";
import type {
  BidPackageStoredView,
  FreezePackageTechnicalScope,
  PackageRequirementInventoryView,
  PackageTechnicalScopeContext,
  PackageTechnicalScopePage,
  PackageTechnicalScopeRequest,
} from "./contracts";
import {
  definitiveTechnicalFailure,
  technicalDefaultRequest,
  technicalSelection,
  validateTechnicalACK,
  validateTechnicalContext,
  validateTechnicalPreview,
  validateTechnicalView,
  validTechnicalHistory,
  validTechnicalRequest,
} from "./packageTechnicalScopeProtocol";
import {
  readTechnicalRecovery,
  technicalRecoveryKey,
  writeTechnicalRecovery,
} from "./packageTechnicalScopeRecovery";

beforeEach(() => sessionStorage.clear());

it("accepts the unmodified ASGI/PostgreSQL receipt with exact Python/SQL digests and original command", async () => {
  // Actual nonowner PostgreSQL + ASGI responses; original bytes are synthetic.
  const f = httpFixture,
    scope = technicalSelection(
      f.bidId,
      f.memberId,
      f.target as unknown as BidPackageStoredView,
      f.inventory as unknown as PackageRequirementInventoryView,
    ),
    context = await validateTechnicalContext(f.context, f.contextEtag, scope),
    pending = {
      key: f.applied.command.idempotency_key,
      body: f.freezeRequest as unknown as FreezePackageTechnicalScope,
      etag: f.contextEtag,
      expected: {
        context_digest: f.context.context_digest,
        method_digest: f.context.method.digest,
      },
    };
  expect(context).toEqual(f.context);
  expect(
    await validateTechnicalPreview(f.preview, scope, {
      context: context as PackageTechnicalScopeContext,
      request: f.request as unknown as PackageTechnicalScopeRequest,
      etag: f.previewEtag,
    }),
  ).toEqual(f.preview);
  expect(
    await validateTechnicalACK(f.applied, f.appliedEtag, pending, scope),
  ).toEqual(f.applied);
  expect(validTechnicalHistory(f.history)).toBe(true);
  const history = f.history as unknown as PackageTechnicalScopePage;
  expect(
    await validateTechnicalView(
      f.detail,
      f.detailEtag,
      scope,
      history.items[0],
    ),
  ).toEqual(f.detail);
});

it("verifies Python-produced exact scope, all original pages, text and table structure without assigning scoring eligibility", async () => {
  const f = technicalFixture();
  expect(
    await validateTechnicalContext(f.context, f.context.etag, f.scope),
  ).toEqual(f.context);
  expect(
    await validateTechnicalPreview(f.preview, f.scope, {
      context: f.context,
      request: f.request,
      etag: f.context.etag,
    }),
  ).toEqual(f.preview);
  expect(await validateTechnicalACK(f.ack, f.etag, f.pending, f.scope)).toEqual(
    f.ack,
  );
  expect(
    f.preview.manifest.documents.some((d) =>
      d.blocks.some((b) => b.kind === "table" && b.structure_json),
    ),
  ).toBe(true);
  expect(f.ack.scope.manifest.formal_scoring_eligible).toBe(false);
});

it("does not silently choose technical pages, rules or an explanation", () => {
  const f = technicalFixture(),
    draft = technicalDefaultRequest(f.context);
  expect(draft.technical_part_ids).toEqual([]);
  expect(
    draft.rule_scopes.every(
      (rule) =>
        rule.selection === "unclassified" &&
        rule.part_ids.length === 0 &&
        rule.reason === "",
    ),
  ).toBe(true);
  expect(validTechnicalRequest(draft, f.scope)).toBe(false);
  expect(validTechnicalRequest(f.request, f.scope)).toBe(true);
});

it.each(["package_digest", "authority_digest", "inventory_digest"] as const)(
  "rejects a changed %s even if the outer preview hash was recomputed",
  async (field) => {
    const f = technicalFixture();
    f.preview.manifest.basis[field] = "f".repeat(64);
    f.preview.digest = await jsonDigest(f.preview.manifest);
    await expect(
      validateTechnicalPreview(f.preview, f.scope),
    ).rejects.toThrow();
  },
);

it("rejects text changes, dropped original pages and a silently omitted unselected part", async () => {
  for (const mutate of [
    (f: ReturnType<typeof technicalFixture>) => {
      f.preview.manifest.documents[0].blocks[0].text_content += "unverified";
    },
    (f: ReturnType<typeof technicalFixture>) => {
      f.preview.manifest.documents[0].pages.pop();
    },
    (f: ReturnType<typeof technicalFixture>) => {
      f.preview.manifest.parts.pop();
    },
  ]) {
    const f = technicalFixture();
    mutate(f);
    f.preview.digest = await jsonDigest(f.preview.manifest);
    await expect(
      validateTechnicalPreview(f.preview, f.scope, {
        context: f.context,
        request: f.request,
        etag: f.context.etag,
      }),
    ).rejects.toThrow();
  }
});

it("rejects a mismatched context tag and an acknowledgement belonging to another original request", async () => {
  const f = technicalFixture();
  await expect(
    validateTechnicalContext(f.context, '"different"', f.scope),
  ).rejects.toThrow();
  f.ack.command.idempotency_key = "00000000-0000-4000-8000-000000000099";
  await expect(
    validateTechnicalACK(f.ack, f.etag, f.pending, f.scope),
  ).rejects.toThrow();
});

it("keeps current inputs separate from history and compares timestamp microseconds", async () => {
  const f = technicalFixture(),
    saved = f.ack.scope,
    coverage = saved.manifest.preview.manifest.coverage;
  const row = {
    id: saved.manifest.id,
    digest: saved.digest,
    inventory_id: f.scope.inventoryId,
    created_at: saved.manifest.frozen_at,
    coverage_state: coverage.state,
    selected_part_count: coverage.selected_part_count,
    included_rule_count: coverage.included_rule_count,
    scoring_ready: false as const,
  };
  expect(
    validTechnicalHistory({ items: [row], has_more: false, next_cursor: null }),
  ).toBe(true);
  expect(await validateTechnicalView(saved, f.etag, f.scope, row)).toEqual(
    saved,
  );
  await expect(
    validateTechnicalView(saved, f.etag, f.scope, {
      ...row,
      created_at: "2026-10-21T09:00:00.000001Z",
    }),
  ).rejects.toThrow();
  expect(
    validTechnicalHistory({ items: [row], has_more: true, next_cursor: null }),
  ).toBe(false);
});

it("persists original request and clears it on account switch or signout", () => {
  const f = technicalFixture();
  writeTechnicalRecovery(f.scope, f.pending);
  expect(readTechnicalRecovery(f.scope)).toEqual(f.pending);
  clearRecordedCommands(f.scope.memberId);
  expect(readTechnicalRecovery(f.scope)).toEqual(f.pending);
  clearRecordedCommands("different-member");
  expect(readTechnicalRecovery(f.scope)).toBeNull();
  writeTechnicalRecovery(f.scope, f.pending);
  clearRecordedCommands();
  expect(readTechnicalRecovery(f.scope)).toBeNull();
});

it("corrupt or cross-inventory records block replacement requests instead of disappearing", () => {
  const f = technicalFixture();
  sessionStorage.setItem(technicalRecoveryKey(f.scope), "{");
  expect(() => readTechnicalRecovery(f.scope)).toThrow();
  writeTechnicalRecovery(f.scope, f.pending);
  const value = JSON.parse(
    sessionStorage.getItem(technicalRecoveryKey(f.scope))!,
  );
  value.scope.inventoryDigest = "f".repeat(64);
  sessionStorage.setItem(technicalRecoveryKey(f.scope), JSON.stringify(value));
  expect(() => readTechnicalRecovery(f.scope)).toThrow();
});

it("only releases proven precommit failures; throttling, authentication and retryable business responses remain uncertain", () => {
  expect(
    definitiveTechnicalFailure(
      new ApiError("changed", 412, "REVISION_CONFLICT"),
    ),
  ).toBe(true);
  expect(
    definitiveTechnicalFailure(
      new ApiError("changed", 412, "REVISION_CONFLICT", undefined, true),
    ),
  ).toBe(false);
  expect(
    definitiveTechnicalFailure(new ApiError("expired", 401, "SESSION_EXPIRED")),
  ).toBe(false);
  expect(
    definitiveTechnicalFailure(new ApiError("busy", 429, "RATE_LIMITED")),
  ).toBe(false);
});
