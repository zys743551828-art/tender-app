import { expect, it } from "vitest";
import type { PackageTechnicalScopeView } from "./contracts";
import {
  materialContext,
  materialReceipt,
  validMaterialRequest,
  type PendingMaterialCheck,
} from "./packageMaterialExecutionProtocol";
import raw from "./test-fixtures/technical-execution-http.json";
import f from "./test-fixtures/material-execution-check.json";
const saved = raw.scope as unknown as PackageTechnicalScopeView;
const pending = {
  key: f.receipt.command_id,
  etag: f.etag,
  body: f.request,
} as PendingMaterialCheck;
it("validates the actual backend context and receipt fixture", async () => {
  await expect(materialContext(f.context, f.etag, saved)).resolves.toEqual(
    f.context,
  );
  await expect(
    materialReceipt(f.receipt, pending, saved, f.receipt.actor_id),
  ).resolves.toEqual(f.receipt);
});
it.each(["actor_id", "scope_id", "scope_digest", "request_digest", "version"])(
  "rejects changed receipt %s",
  async (field) => {
    await expect(
      materialReceipt(
        { ...f.receipt, [field]: "changed" },
        pending,
        saved,
        f.receipt.actor_id,
      ),
    ).rejects.toThrow();
  },
);
it.each([
  "execution_authorized",
  "fee_reserved",
  "jobs_created",
  "model_requests",
])("rejects promoted receipt %s", async (field) => {
  await expect(
    materialReceipt(
      { ...f.receipt, [field]: 1 },
      pending,
      saved,
      f.receipt.actor_id,
    ),
  ).rejects.toThrow();
});
it("rejects context method, model and condition drift", async () => {
  await expect(materialContext(f.context, '"stale"', saved)).rejects.toThrow();
  await expect(
    materialContext(
      {
        ...f.context,
        target: {
          ...f.context.target,
          profile: { ...f.context.target.profile, model_alias: "another" },
        },
      },
      f.etag,
      saved,
    ),
  ).rejects.toThrow();
});
it("rejects missing or reworded authority blockers", async () => {
  await expect(
    materialReceipt(
      { ...f.receipt, blockers: [] },
      pending,
      saved,
      f.receipt.actor_id,
    ),
  ).rejects.toThrow();
  await expect(
    materialReceipt(
      {
        ...f.receipt,
        blockers: f.receipt.blockers.map((g) => ({
          ...g,
          message: "approved",
        })),
      },
      pending,
      saved,
      f.receipt.actor_id,
    ),
  ).rejects.toThrow();
});
it.each(["unknown", "-1", "NaN", "1e9", "0.0000001"])(
  "rejects unknown or ambiguous budget %s",
  (budget) => {
    expect(
      validMaterialRequest({ ...f.request, budget_usd: budget }, saved.digest),
    ).toBe(false);
  },
);
