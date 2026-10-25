import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { contextChoicePage } from "../qa-previews/frozen-inputs/workContextAuthoring";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { api } from "./api";
import { reviewSummaryActions } from "./projectReviewSummaryFixtures.test-support";
import { ProjectSelectedReviewSummary } from "./ProjectSelectedReviewSummary";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
let fixture: Awaited<ReturnType<typeof workContextFixture>>;
const openRecord = vi.fn(),
  openPackage = vi.fn(),
  openRules = vi.fn();
const answer = (data: unknown) => ({ data, etag: null, replay: false });

beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.mocked(api).mockReset();
  openRecord.mockReset();
  openPackage.mockReset();
  openRules.mockReset();
  fixture = await workContextFixture();
  const page = await contextChoicePage(
    [fixture.context.selection],
    "package_review_run",
    fixture.props.scope.bidId,
  );
  vi.mocked(api).mockImplementation(async (path) =>
    answer(
      path.includes("/choices?")
        ? page
        : path.includes("/package-next-actions/")
          ? reviewSummaryActions(fixture)
          : fixture.context,
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());
function view(
  memberId = fixture.props.scope.memberId,
  bidId = fixture.props.scope.bidId,
) {
  return (
    <ProjectSelectedReviewSummary
      bidId={bidId}
      memberId={memberId}
      onOpenRecord={openRecord}
      onOpenPackage={openPackage}
      onOpenRules={openRules}
    />
  );
}
async function choose() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "选择一轮核查" }));
  await user.click(await screen.findByRole("button", { name: "选择此记录" }));
  return user;
}

it("waits for an explicit choice and opens the exact verified record without a write", async () => {
  render(view());
  expect(api).not.toHaveBeenCalled();
  expect(screen.getByText(/风险数量与预测分数保持未知/)).toBeInTheDocument();
  const user = await choose();
  await user.click(
    await screen.findByRole("button", {
      name: "核对所选范围的关键问题（1项）",
    }),
  );
  expect(openRecord).toHaveBeenCalledWith({
    stage: "package_review_run",
    selected: {
      kind: "package_review_run",
      id: fixture.completed.id,
      selectionDigest: fixture.context.selection_digest,
    },
  });
  expect(
    vi
      .mocked(api)
      .mock.calls.every(
        ([, options]) => !options?.method || options.method === "GET",
      ),
  ).toBe(true);
});

it.each(["member", "project"])(
  "clears the selection across %s boundaries",
  async (kind) => {
    const rendered = render(view());
    await choose();
    await screen.findByRole("button", {
      name: "核对所选范围的关键问题（1项）",
    });
    rendered.rerender(
      kind === "member"
        ? view("another-member")
        : view(
            fixture.props.scope.memberId,
            "00000000-0000-0000-0000-000000009999",
          ),
    );
    expect(
      screen.queryByRole("button", { name: "核对所选范围的关键问题（1项）" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/尚未选择核查/)).toBeInTheDocument();
  },
);

it("rejects a mismatched context before fetching risk actions", async () => {
  const existing = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, options) =>
    path.includes("/work-contexts/package_review_run/")
      ? answer({ ...fixture.context, selection_digest: "0".repeat(64) })
      : existing(path, options),
  );
  render(view());
  await choose();
  await screen.findByRole("alert");
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path.includes("/package-next-actions/")),
  ).toBe(false);
  expect(
    screen.queryByRole("button", { name: "查看所选核查与原报告" }),
  ).not.toBeInTheDocument();
});

it("does not restore a late response after clearing the selection", async () => {
  const existing = vi.mocked(api).getMockImplementation()!;
  let resolve: (value: ReturnType<typeof answer>) => void = () => {};
  vi.mocked(api).mockImplementation((path, options) =>
    path.includes("/work-contexts/package_review_run/")
      ? new Promise((done) => {
          resolve = done;
        })
      : existing(path, options),
  );
  render(view());
  const user = await choose();
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.some(([path]) =>
          path.includes("/work-contexts/package_review_run/"),
        ),
    ).toBe(true),
  );
  await user.click(screen.getByRole("button", { name: "取消选择" }));
  await act(async () => resolve(answer(fixture.context)));
  expect(screen.getByText(/尚未选择核查/)).toBeInTheDocument();
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path.includes("/package-next-actions/")),
  ).toBe(false);
});

it("hides stale risk counts if rechecking the selected context fails", async () => {
  render(view());
  await choose();
  await screen.findByRole("button", { name: "核对所选范围的关键问题（1项）" });
  vi.mocked(api).mockRejectedValue(new Error("当前连接失败"));
  await act(async () =>
    window.dispatchEvent(new Event("server-snapshot-change")),
  );
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("button", { name: "核对所选范围的关键问题（1项）" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "查看所选核查与原报告" }),
  ).not.toBeInTheDocument();
});
