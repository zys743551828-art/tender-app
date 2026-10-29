import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { PackageAuthoringActionControls } from "./PackageAuthoringActionControls";
import {
  exactAuthoringFixture,
  exactId,
} from "./authoringExactFixtures.test-support";
import { exactActionStorageKey } from "./useExactAuthoringAction";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});
async function setup({ brokenProof = false, lost = false } = {}) {
  const f = await exactAuthoringFixture(),
    onChanged = vi.fn();
  const writes: unknown[] = [];
  mocked.mockImplementation(async (path, options) => {
    if (options?.method === "POST") {
      writes.push({ path, options });
      if (lost) throw new TypeError("lost ACK");
      return { data: f.executed, etag: f.executedEtag };
    }
    if (path === "/authoring/exact-revision-capabilities")
      return { data: f.capabilities, etag: null };
    if (path === `/bids/${f.f.bid.id}/draft-snapshots/${f.saved.snapshot_id}`)
      return { data: f.snapshot, etag: null };
    if (
      path ===
      `/bids/${f.f.bid.id}/authoring/section-revisions/${f.binding.section_revision_id}/exact-qualification`
    )
      return {
        data: brokenProof
          ? { ...f.qualification, digest: "a".repeat(64) }
          : f.qualification,
        etag: null,
      };
    throw new Error(`unexpected read ${path}`);
  });
  const props = {
    action: f.action,
    etag: f.etag,
    memberId: f.f.member_id,
    input: f.input,
    fresh: true,
    projectWritable: true,
    onChanged,
  };
  return { ...f, props, writes, onChanged };
}
it("requires explicit full-content acknowledgement, then verifies the saved revision before showing the exact draft link", async () => {
  const f = await setup(),
    user = userEvent.setup();
  render(<PackageAuthoringActionControls {...f.props} />);
  const confirm = await screen.findByRole("button", {
    name: "采纳这份固定整包候选并保存新修订",
  });
  expect(confirm).toBeDisabled();
  expect(f.writes).toEqual([]);
  const check = screen.getByRole("checkbox", {
    name: "我已核对完整原稿与拟稿，确认采用这份修改",
  });
  await waitFor(() => expect(check).toBeEnabled());
  await user.click(check);
  await user.click(confirm);
  const link = await screen.findByRole("link", {
    name: "打开这份正文草稿，核对修订并生成文件",
  });
  expect(link).toHaveAttribute(
    "href",
    `/bids/${f.f.bid.id}/authoring?draft=${f.saved.draft_id}`,
  );
  expect(f.writes).toHaveLength(1);
  expect(f.onChanged).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("固定整包正文采纳结果")).toHaveTextContent(
    `草稿修订 ${f.saved.draft_revision}`,
  );
  expect(mocked.mock.calls.some(([path]) => path.includes("/builds"))).toBe(
    false,
  );
});
it("keeps an accepted save receipt but refuses a mismatched qualification link", async () => {
  const f = await setup({ brokenProof: true }),
    user = userEvent.setup();
  render(<PackageAuthoringActionControls {...f.props} />);
  const check = await screen.findByRole("checkbox");
  await waitFor(() => expect(check).toBeEnabled());
  await user.click(check);
  await user.click(
    screen.getByRole("button", { name: "采纳这份固定整包候选并保存新修订" }),
  );
  await screen.findByText(/固定整包采纳的身份、正文修订或原回执不一致/);
  expect(
    screen.queryByRole("link", {
      name: "打开这份正文草稿，核对修订并生成文件",
    }),
  ).toBeNull();
  expect(screen.getByText(/服务端已记录采纳/)).toBeVisible();
});
it("keeps uncertain original commands and blocks a second decision", async () => {
  const f = await setup({ lost: true }),
    user = userEvent.setup();
  render(<PackageAuthoringActionControls {...f.props} />);
  const check = await screen.findByRole("checkbox");
  await waitFor(() => expect(check).toBeEnabled());
  await user.click(check);
  await user.click(
    screen.getByRole("button", { name: "采纳这份固定整包候选并保存新修订" }),
  );
  await screen.findByRole("button", { name: "恢复原固定整包候选处理结果" });
  expect(screen.getByRole("button", { name: "拒绝此提议" })).toBeDisabled();
  expect(
    sessionStorage.getItem(
      exactActionStorageKey({
        memberId: f.f.member_id,
        actionId: f.action.action_id,
      }),
    ),
  ).not.toBeNull();
  expect(f.writes).toHaveLength(1);
});
it("does not expose adoption for a changed immutable candidate or a stale project read", async () => {
  const f = await setup();
  const view = render(
    <PackageAuthoringActionControls {...f.props} fresh={false} />,
  );
  const confirm = await screen.findByRole("button", {
    name: "采纳这份固定整包候选并保存新修订",
  });
  expect(confirm).toBeDisabled();
  const changed = structuredClone(f.action);
  changed.job_id = exactId(99);
  view.rerender(
    <PackageAuthoringActionControls {...f.props} action={changed} />,
  );
  await screen.findByText(/候选卡全文与保存令牌不一致/);
  expect(confirm).toBeDisabled();
  expect(f.writes).toHaveLength(0);
});

it("blocks new adoption if the fixed input cannot be read while preserving rejection", async () => {
  const f = await setup();
  render(<PackageAuthoringActionControls {...f.props} input={null} />);
  const confirm = await screen.findByRole("button", {
    name: "采纳这份固定整包候选并保存新修订",
  });
  expect(confirm).toBeDisabled();
  expect(screen.getByRole("checkbox")).toBeDisabled();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "拒绝此提议" })).toBeEnabled(),
  );
  expect(f.writes).toHaveLength(0);
});
it("blocks a verified input from another target basis without changing the displayed candidate", async () => {
  const f = await setup(),
    input = structuredClone(f.input);
  input.manifest.selection.target_section.base_section_revision++;
  render(<PackageAuthoringActionControls {...f.props} input={input} />);
  await screen.findByText(/固定编写输入与本候选的原稿、章节或基准不一致/);
  expect(
    screen.getByRole("button", { name: "采纳这份固定整包候选并保存新修订" }),
  ).toBeDisabled();
  expect(f.writes).toHaveLength(0);
});
