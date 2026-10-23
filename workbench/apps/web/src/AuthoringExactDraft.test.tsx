import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthoringPanel } from "./AuthoringPanel";
import { layoutScope } from "./authoringLayoutFixtures.test-support";
import { exactDraftLayoutFixture } from "./authoringExactDraftFixtures.test-support";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
it("reads the exact snapshot and qualification, protects edits, and leaves chapter navigation available", async () => {
  const fixture = await exactDraftLayoutFixture(),
    user = userEvent.setup();
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  render(
    <AuthoringPanel
      {...layoutScope}
      projectTitle="合成固定整包正文"
      onOpenDraft={vi.fn()}
    />,
  );
  await screen.findByText(/这份草稿含固定整包候选采纳后的正文修订/);
  await waitFor(() =>
    expect(screen.queryByText(/正在核对保存快照/)).not.toBeInTheDocument(),
  );
  const body = screen.getByLabelText("章节正文");
  expect(body).toHaveAttribute("contenteditable", "false");
  const writing = within(screen.getByRole("region", { name: "正文编写" }));
  expect(writing.getByLabelText("章节名称")).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "章节目录与计划" }));
  const next = screen.getByRole("button", { name: /质量保障措施/ });
  expect(next).toBeEnabled();
  await user.click(next);
  await waitFor(() =>
    expect(writing.getByLabelText("章节名称")).toHaveValue("质量保障措施"),
  );
  expect(writing.getByLabelText("章节名称")).toBeDisabled();
  expect(fixture.reads).toContain(
    `/bids/${layoutScope.bidId}/authoring/drafts/${layoutScope.draftId}/exact-qualification`,
  );
  expect(fixture.state.writes).toHaveLength(0);
  expect(fixture.state.unexpected).toEqual([]);
});
