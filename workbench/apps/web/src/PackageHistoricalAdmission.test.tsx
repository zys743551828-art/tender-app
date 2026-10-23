import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import { PackageHistoricalAdmission } from "./PackageHistoricalAdmission";
import { historyAdmissionFixture } from "./packageHistoricalAdmissionFixtures.test-support";
import { historyEtag } from "./packageHistoricalResearchProtocol";
import {
  historyRecoveryKey,
  readHistoryRecovery,
} from "./packageHistoricalResearchRecovery";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));
const mocked = vi.mocked(api);
let f: Awaited<ReturnType<typeof historyAdmissionFixture>>;
beforeEach(async () => {
  sessionStorage.clear();
  mocked.mockReset();
  f = await historyAdmissionFixture();
  mocked.mockImplementation(async (_path, options) =>
    options?.method === "POST"
      ? { data: f.admission, etag: f.admissionEtag }
      : { data: f.context, etag: f.contextEtag },
  );
});

async function read() {
  fireEvent.click(
    screen.getByRole("button", { name: "读取所选记录的严格准入依据" }),
  );
  return await screen.findByLabelText("严格历史准入依据");
}
async function ready() {
  await read();
  fireEvent.change(screen.getByLabelText("严格历史准入核验回执"), {
    target: { value: f.proofId },
  });
  fireEvent.change(screen.getByLabelText("严格历史准入原因"), {
    target: { value: "核对明确的合成实交、成绩和独立回执" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "已核对所选实交、成绩和回执，仅保存回溯研究准入",
    }),
  );
}
const save = () =>
  screen.getByRole("button", { name: "明确保存这份历史研究准入" });

it("requires the actual selected pair and never reads or writes on mount", async () => {
  render(
    <PackageHistoricalAdmission {...f} submission={null} outcome={null} />,
  );
  expect(mocked).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "读取所选记录的严格准入依据" }),
  ).toBeDisabled();
});

it("keeps real-source configuration gaps visible while explicitly admitting only a selected synthetic proof", async () => {
  render(<PackageHistoricalAdmission {...f} />);
  const details = await read();
  expect(details).toHaveTextContent("官方技术分0");
  expect(screen.getByLabelText("严格历史准入核验回执")).toHaveValue("");
  expect(save()).toBeDisabled();
  fireEvent.change(screen.getByLabelText("严格历史准入核验回执"), {
    target: { value: f.proofId },
  });
  fireEvent.change(screen.getByLabelText("严格历史准入原因"), {
    target: { value: "明确合成机制核验" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(
    screen.getByText("真实证明接入来源尚未配置；签名本身不证明事实真实。"),
  ).toBeVisible();
  expect(save()).toBeEnabled();
  fireEvent.click(save());
  expect(
    await screen.findByLabelText("严格历史准入保存回执"),
  ).toHaveTextContent("合成机制候选");
  expect(
    mocked.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(1);
  expect(readHistoryRecovery(f.memberId, f.workspace)).toBeNull();
});

it("never bypasses a missing range proof or enables external-evidence admission without its prerequisites", async () => {
  f.context.blockers.push({
    code: "PACKAGE_HISTORY_COMPLETE_VISUAL_RANGE_PROOF_MISSING",
    message: "缺少完整图文范围证据",
  });
  f.contextEtag = await historyEtag("context", f.saved.manifest.id, f.context);
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  expect(save()).toBeDisabled();
  expect(
    mocked.mock.calls.every(([, options]) => options?.method !== "POST"),
  ).toBe(true);
});

it("does not treat external evidence as a synthetic configuration exception", async () => {
  f.context.proofs[0].origin = "external_evidence";
  f.contextEtag = await historyEtag("context", f.saved.manifest.id, f.context);
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  expect(save()).toBeDisabled();
});

it("restores the exact original body, condition and key after reload even when the current pair is unselected", async () => {
  mocked.mockImplementationOnce(async () => ({
    data: f.context,
    etag: f.contextEtag,
  }));
  mocked.mockImplementationOnce(async () => {
    throw new ApiError("回执未确认", 0, "NETWORK_ERROR", undefined, true);
  });
  const mounted = render(<PackageHistoricalAdmission {...f} />);
  await ready();
  fireEvent.click(save());
  await screen.findByRole("button", { name: "恢复原准入请求结果" });
  const pending = readHistoryRecovery(f.memberId, f.workspace);
  expect(pending?.body).toMatchObject({
    submission_id: f.submission.id,
    outcome_id: f.outcome.id,
  });
  mounted.unmount();
  render(
    <PackageHistoricalAdmission {...f} submission={null} outcome={null} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "恢复原准入请求结果" }));
  await screen.findByLabelText("严格历史准入保存回执");
  const writes = mocked.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
});

it("retains a wrong-success acknowledgement for recovery rather than accepting another outcome", async () => {
  const changed = {
    ...f.admission,
    outcome_id: "50000000-0000-4000-8000-000000000001",
  };
  const document = Object.fromEntries(
    Object.entries(changed).filter(([key]) => key !== "digest"),
  );
  changed.digest = await jsonDigest(document);
  const wrongTag = await historyEtag("admission", changed.id, changed);
  mocked.mockImplementation(async (_path, options) =>
    options?.method === "POST"
      ? { data: changed, etag: wrongTag }
      : { data: f.context, etag: f.contextEtag },
  );
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  fireEvent.click(save());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原准入请求结果" }),
    ).toBeEnabled(),
  );
  expect(
    screen.queryByLabelText("严格历史准入保存回执"),
  ).not.toBeInTheDocument();
  expect(readHistoryRecovery(f.memberId, f.workspace)).not.toBeNull();
});

it("preserves an original request after permission loss", async () => {
  mocked.mockImplementation(async (_path, options) => {
    if (options?.method === "POST")
      throw new ApiError("当前权限不足", 403, "FORBIDDEN");
    return { data: f.context, etag: f.contextEtag };
  });
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  fireEvent.click(save());
  await screen.findByText("当前权限不足");
  expect(readHistoryRecovery(f.memberId, f.workspace)).not.toBeNull();
});

it("invalidates the reviewed context after a definitive condition conflict and does not resend automatically", async () => {
  mocked.mockImplementation(async (_path, options) => {
    if (options?.method === "POST")
      throw new ApiError("原条件已变化", 412, "PRECONDITION_FAILED");
    return { data: f.context, etag: f.contextEtag };
  });
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  fireEvent.click(save());
  await screen.findByText("原条件已变化");
  expect(readHistoryRecovery(f.memberId, f.workspace)).toBeNull();
  expect(screen.queryByLabelText("严格历史准入依据")).not.toBeInTheDocument();
  expect(
    mocked.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(1);
});

it("ignores a delayed context after the explicitly selected outcome changes", async () => {
  let complete!: (value: { data: unknown; etag: string }) => void;
  mocked.mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const mounted = render(<PackageHistoricalAdmission {...f} />);
  fireEvent.click(
    screen.getByRole("button", { name: "读取所选记录的严格准入依据" }),
  );
  mounted.rerender(
    <PackageHistoricalAdmission
      {...f}
      outcome={{ ...f.outcome, id: "60000000-0000-4000-8000-000000000001" }}
    />,
  );
  await act(async () => {
    complete({ data: f.context, etag: f.contextEtag });
  });
  expect(screen.queryByLabelText("严格历史准入依据")).not.toBeInTheDocument();
});

it("refuses a locally corrupt recovery record and performs no new write", async () => {
  sessionStorage.setItem(
    historyRecoveryKey(f.memberId, f.workspace),
    '{"pending":"corrupt"}',
  );
  render(<PackageHistoricalAdmission {...f} />);
  expect(
    screen.getByText("本地恢复记录无法核对，新准入保持锁定，请保留记录。"),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "读取所选记录的严格准入依据" }),
  ).toBeDisabled();
  expect(mocked).not.toHaveBeenCalled();
});

it("does not send when the browser cannot persist its original request", async () => {
  render(<PackageHistoricalAdmission {...f} />);
  await ready();
  const storage = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("Synthetic storage unavailable");
    });
  fireEvent.click(save());
  await screen.findByText(/浏览器未能保存历史研究原请求/);
  expect(
    mocked.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
  storage.mockRestore();
});

it("does not reuse another member's pending request", async () => {
  mocked.mockImplementation(async (_path, options) => {
    if (options?.method === "POST")
      throw new ApiError("回执未确认", 0, "NETWORK_ERROR", undefined, true);
    return { data: f.context, etag: f.contextEtag };
  });
  const mounted = render(<PackageHistoricalAdmission {...f} />);
  await ready();
  fireEvent.click(save());
  await screen.findByRole("button", { name: "恢复原准入请求结果" });
  mounted.rerender(
    <PackageHistoricalAdmission
      {...f}
      memberId="70000000-0000-4000-8000-000000000001"
    />,
  );
  expect(
    screen.queryByRole("button", { name: "恢复原准入请求结果" }),
  ).not.toBeInTheDocument();
  expect(readHistoryRecovery(f.memberId, f.workspace)).not.toBeNull();
});
