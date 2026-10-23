import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import type { PackageCoverageWorkspace } from "./PackageCoverageWorkspace";
import type { PackageRuleCorrections } from "./PackageRuleCorrections";
import type { PackageReviewInputPreview } from "./PackageReviewInputPreview";
import { PackageRequirements } from "./PackageRequirements";
import {
  correctionApplied,
  correctionFixture,
  correctionId,
  correctionPackage,
  correctionPreview,
  correctionScope,
} from "./packageRuleCorrectionFixtures.test-support";
import { correctionInventoryPath } from "./packageRuleCorrectionRecovery";

const controls = vi.hoisted(() => ({
  beforeApplied: () => {},
  nextInventoryId: "",
}));
vi.mock("./PackageRuleCorrections", () => ({
  PackageRuleCorrections: (
    props: ComponentProps<typeof PackageRuleCorrections>,
  ) => (
    <section>
      <button onClick={() => props.onPendingChange(true)}>
        模拟修订已发送未决
      </button>
      <button
        onClick={() => {
          controls.beforeApplied();
          props.onPendingChange(false);
          props.onApplied(controls.nextInventoryId);
        }}
      >
        模拟取得原修订回执
      </button>
    </section>
  ),
}));
vi.mock("./PackageCoverageWorkspace", () => ({
  PackageCoverageWorkspace: (
    props: ComponentProps<typeof PackageCoverageWorkspace>,
  ) => (
    <section>
      <p data-testid="coverage-inventory">
        {props.inventory?.manifest.id ?? "none"}
      </p>
      <button
        disabled={props.disabled}
        onClick={() =>
          props.onSaved(props.inventory!.manifest.id, correctionId(800))
        }
      >
        模拟已保存范围声明
      </button>
    </section>
  ),
}));
vi.mock("./PackageReviewInputPreview", () => ({
  PackageReviewInputPreview: (
    props: ComponentProps<typeof PackageReviewInputPreview>,
  ) => (
    <section>
      <p data-testid="selected-coverage">
        {props.coverage?.manifest.id ?? "none"}
      </p>
      <button disabled={props.disabled}>准备核查</button>
    </section>
  ),
}));

beforeEach(() => sessionStorage.clear());
it("locks sibling coverage/review writes for an unresolved correction, then selects the exact new inventory and clears old coverage", async () => {
  const f = await correctionFixture(),
    preview = await correctionPreview(f.inventory, f.request, f.evidence),
    saved = await correctionApplied(f.inventory, preview);
  let current = f.inventory;
  controls.nextInventoryId = saved.inventory.manifest.id;
  controls.beforeApplied = () => {
    current = saved.inventory;
  };
  const base = `/api/v1${correctionInventoryPath(correctionScope)}`;
  const page = (items: unknown[]) => ({
    items,
    has_more: false,
    next_cursor: null,
  });
  const json = (value: unknown, etag?: string) =>
    new Response(JSON.stringify(value), {
      headers: etag ? { ETag: etag } : {},
    });
  const fetcher = vi.fn(async (input: string) => {
    const url = String(input);
    if (url === `${base}?limit=20`)
      return json(
        {
          ...page([
            {
              id: current.manifest.id,
              digest: current.digest,
              created_at: "2026-10-21T00:00:00Z",
            },
          ]),
          current_inventory_id: current.manifest.id,
        },
        `"requirement-inventory:${correctionScope.revisionId}:${current.digest}"`,
      );
    if (url === `${base}/${f.inventory.manifest.id}`)
      return json(f.inventory, f.etag);
    if (url === `${base}/${saved.inventory.manifest.id}`)
      return json(
        saved.inventory,
        `"requirement-inventory:${correctionScope.revisionId}:${saved.inventory.digest}"`,
      );
    if (url.endsWith("coverage-attempts?limit=20")) return json(page([]));
    if (url.endsWith(`/coverage-attempts/${correctionId(800)}`))
      return json({
        digest: "8".repeat(64),
        manifest: {
          version: "bid-package-coverage/1",
          id: correctionId(800),
          bid_id: correctionScope.bidId,
          inventory_id: f.inventory.manifest.id,
          inventory_digest: f.inventory.digest,
          package_digest: correctionScope.packageDigest,
          actor_id: correctionScope.memberId,
          results: [],
          review_ready: false,
          assessment: {
            package_digest: correctionScope.packageDigest,
            complete: false,
            requirement_inventory_complete: false,
            requirement_states: {},
            requirement_digests: {},
            inspected_ranges: [],
            member_gaps: [],
          },
        },
      });
    if (url.includes("packages?kind=authority")) return json(page([]));
    if (url.endsWith("/rules"))
      return json({
        id: f.inventory.manifest.rule_set_id,
        bid_id: correctionScope.bidId,
        material_revision: 1,
        revision: 1,
        coverage: "partial",
        rules: [],
      });
    throw new Error(`Unexpected read ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <PackageRequirements
      bidId={correctionScope.bidId}
      memberId={correctionScope.memberId}
      packageView={correctionPackage}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "要求清单与覆盖" }));
  await user.click(await screen.findByRole("button", { name: /读取清单 1/ }));
  await waitFor(() =>
    expect(screen.getByTestId("coverage-inventory")).toHaveTextContent(
      f.inventory.manifest.id,
    ),
  );
  await user.click(screen.getByRole("button", { name: "模拟已保存范围声明" }));
  await waitFor(() =>
    expect(screen.getByTestId("selected-coverage")).toHaveTextContent(
      correctionId(800),
    ),
  );
  await user.click(screen.getByRole("button", { name: "模拟修订已发送未决" }));
  expect(
    screen.getByRole("button", { name: "模拟已保存范围声明" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "准备核查" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "模拟取得原修订回执" }));
  await waitFor(() =>
    expect(screen.getByTestId("coverage-inventory")).toHaveTextContent(
      saved.inventory.manifest.id,
    ),
  );
  expect(screen.getByTestId("selected-coverage")).toHaveTextContent("none");
  expect(
    screen.getByRole("button", { name: "模拟已保存范围声明" }),
  ).toBeEnabled();
  expect(
    fetcher.mock.calls.some(
      ([url]) => url === `${base}/${saved.inventory.manifest.id}`,
    ),
  ).toBe(true);
});
