import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PackageFactChangeView } from "./contracts";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  validEditableFact,
  validFactHead,
  validPendingFactChange,
  validateFactChange,
} from "./factChangeProtocol";
import type { FactChangeScope, PendingFactChange } from "./factChangeProtocol";
import {
  factChangeStorageKey,
  loadFactChangeRecord,
  storeFactChangeRecord,
} from "./factChangeRecovery";
import { clearRecordedCommands } from "./useRecordedCommand";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: FactChangeScope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
  frozenId: id(6),
  frozenDigest: "a".repeat(64),
};
function pending(): PendingFactChange & { kind: "confirm" } {
  return {
    kind: "confirm",
    key: id(7),
    body: {
      frozen_digest: scope.frozenDigest,
      expected_head: { id: id(8), revision: 1 },
      replaces_fact_id: id(9),
      confirmation: "confirmed",
      fact: {
        subject: "工程",
        scope: "标段一",
        name: "工期",
        value: "180",
        unit: "天",
        evidence_ids: [id(10)],
        reason: "已核对原页",
      },
    },
  };
}
async function reply(p = pending()): Promise<PackageFactChangeView> {
  const manifest: PackageFactChangeView["manifest"] = {
    version: "package-fact-change/2",
    kind: "package_fact_change",
    command_id: id(11),
    actor_id: scope.memberId,
    action: "confirmed",
    recorded_at: "2026-10-20T08:00:00.000001Z",
    reason: p.body.fact.reason,
    binding: {
      bid_id: scope.bidId,
      package_id: scope.packageId,
      revision_id: scope.revisionId,
      inventory_id: scope.inventoryId,
      frozen_input_id: scope.frozenId,
      frozen_digest: scope.frozenDigest,
    },
    previous_head: p.body.expected_head,
    head: { id: id(12), revision: 2 },
    fact_id: id(13),
    replaces_fact_id: p.body.replaces_fact_id,
    decision_id: id(14),
    evidence_selection_digest: "b".repeat(64),
    evidence_basis_digest: "c".repeat(64),
    request_digest: await frozenManifestDigest({
      body: p.body,
      if_match: null,
    }),
    original_bytes_verified: false,
    facts_qualified: false,
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("fact request and exact acknowledgement", () => {
  it("accepts a complete v2 receipt bound to the original request", async () => {
    const p = pending();
    expect(validPendingFactChange(p, scope)).toBe(true);
    await expect(
      validateFactChange(await reply(p), scope, p),
    ).resolves.toBeUndefined();
  });
  it.each(["value", "subject", "scope", "unit"] as const)(
    "rejects a same-head receipt for a different %s",
    async (field) => {
      const p = pending();
      const receipt = await reply(p);
      p.body.fact[field] = "其他内容";
      await expect(validateFactChange(receipt, scope, p)).rejects.toThrow(
        "请求摘要",
      );
    },
  );
  it("rejects different evidence even when reason and value match", async () => {
    const p = pending();
    const receipt = await reply(p);
    p.body.fact.evidence_ids = [id(20)];
    await expect(validateFactChange(receipt, scope, p)).rejects.toThrow();
  });
  it("reads authentic legacy history but never uses it as a precise new acknowledgement", async () => {
    const p = pending();
    const current = await reply(p);
    const { request_digest: omitted, ...legacy } = current.manifest as Extract<
      PackageFactChangeView["manifest"],
      { version: "package-fact-change/2" }
    >;
    expect(omitted).toHaveLength(64);
    const manifest = { ...legacy, version: "package-fact-change/1" as const };
    const receipt = { manifest, digest: await frozenManifestDigest(manifest) };
    await expect(validateFactChange(receipt, scope)).resolves.toBeUndefined();
    await expect(validateFactChange(receipt, scope, p)).rejects.toThrow();
  });
  it.each([
    "facts_qualified",
    "review_ready",
    "launch_available",
    "publication_authorized",
    "original_bytes_verified",
  ] as const)(
    "rejects forged %s even with a matching manifest hash",
    async (field) => {
      const receipt = await reply();
      Object.assign(receipt.manifest, { [field]: true });
      receipt.digest = await frozenManifestDigest(receipt.manifest);
      await expect(validateFactChange(receipt, scope)).rejects.toThrow();
    },
  );
  it("rejects a different actor for an outstanding operation", async () => {
    const p = pending();
    const receipt = await reply(p);
    receipt.manifest.actor_id = id(21);
    receipt.digest = await frozenManifestDigest(receipt.manifest);
    await expect(validateFactChange(receipt, scope, p)).rejects.toThrow();
  });
  it.each([false, null, "180"])(
    "preserves supported scalar %s without coercion",
    (value) => {
      const p = pending();
      p.body.fact.value = value;
      expect(validPendingFactChange(p, scope)).toBe(true);
    },
  );
  it("rejects objects, numbers, repeated evidence and ambiguous heads", () => {
    const { reason: omitted, ...fact } = pending().body.fact;
    expect(omitted).toBeTruthy();
    for (const value of [{ text: "180" }, 180, ["180"]])
      expect(validEditableFact({ ...fact, value })).toBe(false);
    expect(validEditableFact({ ...fact, evidence_ids: [id(10), id(10)] })).toBe(
      false,
    );
    expect(validFactHead({ id: null, revision: 1 })).toBe(false);
    expect(validFactHead({ id: id(1), revision: 0 })).toBe(false);
    expect(validFactHead({ id: null, revision: 0 })).toBe(true);
  });
});

describe("fact operation recovery isolation", () => {
  it("restores the exact key and body without sending a request", () => {
    const send = vi.fn();
    vi.stubGlobal("fetch", send);
    const record = {
      version: 1 as const,
      scope,
      pending: pending(),
      lastId: null,
    };
    storeFactChangeRecord(record);
    expect(loadFactChangeRecord(scope)).toEqual(record);
    expect(send).not.toHaveBeenCalled();
  });
  it.each([
    "{broken",
    JSON.stringify({ version: 1, scope, pending: null, lastId: "invalid" }),
  ])("retains damaged recovery bytes for inspection", (raw) => {
    sessionStorage.setItem(factChangeStorageKey(scope), raw);
    expect(() => loadFactChangeRecord(scope)).toThrow("未发送请求");
    expect(sessionStorage.getItem(factChangeStorageKey(scope))).toBe(raw);
  });
  it("does not replay an operation for a different frozen digest", () => {
    storeFactChangeRecord({
      version: 1,
      scope,
      pending: pending(),
      lastId: null,
    });
    expect(() =>
      loadFactChangeRecord({ ...scope, frozenDigest: "b".repeat(64) }),
    ).toThrow();
  });
  it("clears another member's private pending command on account change and all on logout", () => {
    const other = { ...scope, memberId: id(30) };
    storeFactChangeRecord({
      version: 1,
      scope,
      pending: pending(),
      lastId: null,
    });
    storeFactChangeRecord({
      version: 1,
      scope: other,
      pending: null,
      lastId: id(31),
    });
    clearRecordedCommands(scope.memberId);
    expect(sessionStorage.getItem(factChangeStorageKey(scope))).not.toBeNull();
    expect(sessionStorage.getItem(factChangeStorageKey(other))).toBeNull();
    clearRecordedCommands();
    expect(sessionStorage.getItem(factChangeStorageKey(scope))).toBeNull();
  });
});
