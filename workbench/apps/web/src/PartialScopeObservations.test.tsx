import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PartialScopeObservations } from "./PartialScopeObservations";
import type { Comparison } from "./PartialPageComparison";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: mocks.api,
  commandKey: () => "synthetic-key",
}));
const comparison = {
  requirement: {
    evidence: {
      items: [{ id: "r", physical_page: 1, quote: "SYNTHETIC requirement" }],
    },
  },
  technical: {
    evidence: {
      items: [{ id: "t", physical_page: 2, quote: "SYNTHETIC technical" }],
    },
  },
} as Comparison;

it("requires explicit evidence and confirmation before saving a scoped human opinion", async () => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue({
    data: { items: [], scope_revalidated: true, has_more: false },
  });
  render(
    <PartialScopeObservations
      path="/bids/b/partial-page-selections"
      requirement="req"
      technical="tech"
      comparison={comparison}
    />,
  );
  const user = userEvent.setup();
  const save = await screen.findByRole("button", { name: "保存人工意见" });
  expect(save).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("要求依据"), "r");
  await user.selectOptions(screen.getByLabelText("技术依据"), "t");
  await user.selectOptions(
    screen.getByLabelText("人工意见"),
    "observed_support",
  );
  await user.type(screen.getByLabelText("核对理由"), "SYNTHETIC review");
  await user.click(screen.getByRole("checkbox"));
  await user.click(save);
  expect(mocks.api).toHaveBeenCalledWith(
    expect.stringContaining("/decisions"),
    expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({
        requirement_evidence_id: "r",
        technical_evidence_id: "t",
        expected_revision: 0,
        outcome: "observed_support",
        confirmed: true,
      }),
    }),
  );
});

it("shows history but prevents edits when the scope requires revalidation", async () => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue({
    data: {
      scope_revalidated: false,
      has_more: false,
      items: [
        {
          id: "v1",
          item_id: "item",
          revision: 1,
          actor_id: "actor-01",
          created_at: "2026-11-06T00:00:00Z",
          requirement_evidence_id: "r",
          technical_evidence_id: "t",
          outcome: "observed_support",
          reason: "SYNTHETIC past",
        },
      ],
    },
  });
  render(
    <PartialScopeObservations
      path="/bids/b/partial-page-selections"
      requirement="req"
      technical="tech"
      comparison={null}
    />,
  );
  expect(await screen.findByText(/SYNTHETIC past/)).toBeVisible();
  expect(screen.getByText(/历史可查看/)).toBeVisible();
  expect(screen.getByRole("button", { name: "修改此项" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "保存人工意见" }),
  ).not.toBeInTheDocument();
});

it("revises the latest item without letting its requirement evidence change", async () => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValue({
    data: {
      scope_revalidated: true,
      has_more: false,
      items: [
        {
          id: "v1",
          item_id: "item",
          revision: 1,
          actor_id: "actor-01",
          created_at: "2026-11-06T00:00:00Z",
          requirement_evidence_id: "r",
          technical_evidence_id: "t",
          outcome: "needs_review",
          reason: "SYNTHETIC initial",
        },
      ],
    },
  });
  render(
    <PartialScopeObservations
      path="/bids/b/partial-page-selections"
      requirement="req"
      technical="tech"
      comparison={comparison}
    />,
  );
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "修改此项" }));
  expect(screen.getByLabelText("要求依据")).toBeDisabled();
  await user.clear(screen.getByLabelText("核对理由"));
  await user.type(screen.getByLabelText("核对理由"), "SYNTHETIC revised");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "保存人工意见" }));
  expect(mocks.api).toHaveBeenCalledWith(
    expect.stringContaining("/decisions"),
    expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({
        item_id: "item",
        expected_revision: 1,
        requirement_evidence_id: "r",
        reason: "SYNTHETIC revised",
      }),
    }),
  );
});
