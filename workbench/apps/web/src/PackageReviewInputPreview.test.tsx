import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackageReviewInputPreview } from "./PackageReviewInputPreview";
import type {
  BidPackageStoredView,
  PackageRequirementInventoryView,
  PackageReviewInputPreview as Preview,
} from "./contracts";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope = {
  engineering_project_id: id(1),
  lot_id: id(2),
  round_id: id(3),
  bid_id: id(4),
  bidder_id: id(5),
  bidder_status: "confirmed" as const,
};
const target: BidPackageStoredView = {
  digest: "a".repeat(64),
  storage_eligible: true,
  review_ready: false,
  identity: {
    identity_version: "bid-identity/2",
    bidder_id: id(5),
    bidder_name: "Synthetic",
    round_id: id(3),
    engineering_project_id: id(1),
    engineering_title: "Synthetic",
    region: null,
    engineering_type: null,
    lot: "Synthetic",
    lot_id: id(2),
    round_no: 1,
    binding_status: "confirmed",
    authority_id: id(6),
    digest: "b".repeat(64),
  },
  manifest: {
    identity_version: "bid-package/1",
    package_id: id(7),
    revision_id: id(8),
    revision: 1,
    kind: "bid",
    scope,
    predecessor_digest: null,
    members: [
      {
        member_id: "synthetic",
        document_version_id: id(9),
        file_digest: "c".repeat(64),
        source_kind: "own",
        source_ref: "synthetic:original",
        scope,
        purposes: ["technical"],
        page_count: 2,
        parse: {
          status: "frozen",
          parse_run_id: id(10),
          parser_digest: "d".repeat(64),
          config_digest: "e".repeat(64),
          evidence_digest: "f".repeat(64),
          reason: null,
        },
        parts: [
          {
            part_id: "tech",
            category: "technical",
            first_page: 1,
            last_page: 2,
            shared_attachment: false,
            heading_path: [],
          },
        ],
      },
    ],
  },
};
const authority: BidPackageStoredView = {
  ...target,
  digest: "1".repeat(64),
  manifest: {
    ...target.manifest,
    kind: "authority",
    package_id: id(11),
    revision_id: id(12),
  },
};
const inv: PackageRequirementInventoryView = {
  digest: "2".repeat(64),
  manifest: {
    version: "bid-package-requirements/1",
    id: id(13),
    bid_id: id(4),
    package_id: id(7),
    target_revision_id: id(8),
    package_digest: target.digest,
    authority_revision_id: id(12),
    authority_digest: authority.digest,
    rule_set_id: id(14),
    rule_set_digest: "3".repeat(64),
    revision: 1,
    predecessor_digest: null,
    identity_digest: target.identity.digest,
    source_snapshot: [],
    requirements: [],
    inventory_complete: false,
    extraction_binding: "unproven_legacy_rule_set",
    review_ready: false,
    actor_id: id(15),
  },
};
const reply = (): Preview => ({
  digest: "4".repeat(64),
  review_ready: false,
  launch_available: false,
  physical_page_gaps: [],
  blockers: [
    "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN",
    "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
  ],
  manifest: {
    version: "bid-package-review-input/1",
    kind: "preview",
    bid_id: id(4),
    target,
    authority,
    inventory: inv,
    coverage: null,
  },
});
const props = {
  bidId: id(4),
  packageView: target,
  inventory: inv,
  coverage: null,
};
const respond = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

it("显式触发只读预检，StrictMode下仍显示阻断且没有执行入口", async () => {
  fetchMock.mockResolvedValue(respond(reply()));
  render(
    <StrictMode>
      <PackageReviewInputPreview {...props} />
    </StrictMode>,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  );
  expect(await screen.findByText("暂不可正式评审")).toBeInTheDocument();
  expect(screen.getByText("正式整包评审执行器尚未接入。")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [path, options] = fetchMock.mock.calls[0];
  expect(path).toContain(
    `/requirement-inventories/${id(13)}/review-input-preview`,
  );
  expect(JSON.parse(options.body)).toEqual({
    package_digest: target.digest,
    inventory_digest: inv.digest,
    coverage_attempt_id: null,
    coverage_digest: null,
  });
});

it("实际证据无法匹配时显示可理解的阻断而不提供执行入口", async () => {
  const value = reply();
  value.blockers.push("PACKAGE_REVIEW_EVIDENCE_CHANGED");
  fetchMock.mockResolvedValue(respond(value));
  render(<PackageReviewInputPreview {...props} />);
  await userEvent.click(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  );
  expect(
    await screen.findByText(
      "冻结解析对应的文件、页或证据记录无法核对，需检查原件与解析。",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("暂不可正式评审")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("未选择清单或所选范围记录仍在加载时不发送", async () => {
  const { rerender } = render(
    <PackageReviewInputPreview {...props} inventory={null} />,
  );
  expect(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  ).toBeDisabled();
  rerender(<PackageReviewInputPreview {...props} coveragePending />);
  expect(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  ).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
});

it.each(["scope", "authority", "rule-set", "ready"])(
  "拒绝错误的嵌套身份或就绪声明：%s",
  async (kind) => {
    const value = structuredClone(reply());
    if (kind === "scope") value.manifest.target.manifest.scope.bid_id = id(99);
    else if (kind === "authority")
      value.manifest.authority.manifest.revision_id = id(99);
    else if (kind === "rule-set")
      value.manifest.inventory.manifest.rule_set_id = id(99);
    else Object.assign(value, { review_ready: true });
    fetchMock.mockResolvedValue(respond(value));
    render(<PackageReviewInputPreview {...props} />);
    await userEvent.click(
      screen.getByRole("button", { name: "检查所选整包评审输入" }),
    );
    expect(await screen.findByText(/预检响应与所选包/)).toBeInTheDocument();
    expect(screen.queryByText("暂不可正式评审")).not.toBeInTheDocument();
  },
);

it("切换清单后隐藏旧结果并忽略迟到响应", async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((r) => {
        resolve = r;
      }),
  );
  const { rerender } = render(<PackageReviewInputPreview {...props} />);
  await userEvent.click(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  );
  rerender(
    <PackageReviewInputPreview
      {...props}
      inventory={{ ...inv, manifest: { ...inv.manifest, id: id(16) } }}
    />,
  );
  await act(async () => resolve(respond(reply())));
  expect(screen.queryByText("暂不可正式评审")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  ).toBeEnabled();
});

it("切换离开又返回同一清单，也不接受上次未完成的旧观察", async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const { rerender } = render(<PackageReviewInputPreview {...props} />);
  await userEvent.click(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  );
  rerender(<PackageReviewInputPreview {...props} inventory={null} />);
  rerender(<PackageReviewInputPreview {...props} />);
  await act(async () => resolve(respond(reply())));
  expect(screen.queryByText("暂不可正式评审")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "检查所选整包评审输入" }),
  ).toBeEnabled();
});
