import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, supportsApi } from "./api";
import { PackageMaterialExecution } from "./PackageMaterialExecution";
import type { PackageTechnicalScopeView } from "./contracts";
import raw from "./test-fixtures/technical-execution-http.json";
import f from "./test-fixtures/material-execution-check.json";
import { materialStorageKey } from "./packageMaterialExecutionProtocol";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: vi.fn(),
}));
// This suite isolates the material application commands; pipeline composition is tested separately.
vi.mock("./PackagePredictionPipeline", () => ({
  PackagePredictionPipeline: () => null,
}));
const mocked = vi.mocked(api),
  saved = raw.scope as unknown as PackageTechnicalScopeView,
  memberId = f.receipt.actor_id;
beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(supportsApi).mockReturnValue(true);
  mocked
    .mockReset()
    .mockImplementation(async (path) =>
      path.endsWith("/material-execution-context")
        ? { data: f.context, etag: f.etag }
        : { data: f.receipt, etag: null },
    );
});
function mount() {
  return render(<PackageMaterialExecution saved={saved} memberId={memberId} />);
}
async function prepare() {
  fireEvent.click(screen.getByText("读取完整材料执行条件"));
  await screen.findByText("保存受阻申请并核对");
}
async function send() {
  fireEvent.click(screen.getByText("保存受阻申请并核对"));
  await screen.findByLabelText("完整材料受阻回执");
}
it("freezes /3 input and persists refusal using an explicit second action", async () => {
  mount();
  expect(mocked).not.toHaveBeenCalled();
  await prepare();
  await send();
  const options = mocked.mock.calls[1][1]!;
  expect(options.body).toEqual(f.request);
  expect(options.etag).toBe(f.etag);
  expect(options.key).toBeTruthy();
  expect(screen.getByLabelText("完整材料受阻回执")).toHaveTextContent(
    "不是当前执行资格",
  );
  expect(
    sessionStorage.getItem(materialStorageKey(saved, memberId)),
  ).not.toBeNull();
});
it("recovers the exact original request after lost ACK and remount", async () => {
  let view = mount();
  await prepare();
  mocked.mockRejectedValueOnce(new Error("lost ACK"));
  fireEvent.click(screen.getByText("保存受阻申请并核对"));
  await screen.findByRole("alert");
  const first = mocked.mock.calls[1];
  view.unmount();
  view = mount();
  await screen.findByText("恢复原申请回执");
  expect(mocked).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByText("恢复原申请回执"));
  await screen.findByLabelText("完整材料受阻回执");
  expect(mocked.mock.calls[2]).toEqual(first);
  view.unmount();
});
it("does not send when recovery storage cannot be written", async () => {
  mount();
  await prepare();
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage full");
  });
  try {
    fireEvent.click(screen.getByText("保存受阻申请并核对"));
    await screen.findByRole("alert");
    expect(mocked).toHaveBeenCalledTimes(1);
  } finally {
    spy.mockRestore();
  }
});
it("does not replace a corrupted pending request", async () => {
  sessionStorage.setItem(materialStorageKey(saved, memberId), "invalid");
  mount();
  await screen.findByRole("alert");
  expect(screen.getByText("读取完整材料执行条件")).toBeDisabled();
  expect(mocked).not.toHaveBeenCalled();
});
it("ignores a late context after member switch", async () => {
  let resolve!: (v: { data: unknown; etag: string }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const view = mount();
  fireEvent.click(screen.getByText("读取完整材料执行条件"));
  view.rerender(
    <PackageMaterialExecution
      saved={saved}
      memberId="00000000-0000-0000-0000-000000009999"
    />,
  );
  await act(async () => resolve({ data: f.context, etag: f.etag }));
  expect(screen.queryByText("保存受阻申请并核对")).not.toBeInTheDocument();
});
it("keeps unknown or forged success pending instead of claiming zero effects", async () => {
  mount();
  await prepare();
  mocked.mockResolvedValueOnce({
    data: { ...f.receipt, jobs_created: 1 },
    etag: null,
  });
  fireEvent.click(screen.getByText("保存受阻申请并核对"));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("完整材料受阻回执")).not.toBeInTheDocument();
  expect(screen.getByText("恢复原申请回执")).toBeEnabled();
});
it("blocks partial reference and unknown fee before posting", async () => {
  mount();
  await prepare();
  fireEvent.change(screen.getByLabelText("材料封印编号"), {
    target: { value: f.receipt.command_id },
  });
  fireEvent.click(screen.getByText("保存受阻申请并核对"));
  await screen.findByRole("alert");
  expect(mocked).toHaveBeenCalledTimes(1);
});
it("does not double send while an original request is in flight", async () => {
  mount();
  await prepare();
  let resolve!: (v: { data: unknown; etag: null }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const button = screen.getByText("保存受阻申请并核对");
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
  await act(async () => resolve({ data: f.receipt, etag: null }));
  await screen.findByLabelText("完整材料受阻回执");
});

it("allows explicit fresh checking after a definitive stale-condition rejection", async () => {
  mount();
  await prepare();
  mocked.mockRejectedValueOnce(new ApiError("stale", 412, "REVISION_CONFLICT"));
  fireEvent.click(screen.getByText("保存受阻申请并核对"));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("完整材料受阻回执")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("开始新的条件核对"));
  expect(screen.getByText("读取完整材料执行条件")).toBeEnabled();
  expect(
    sessionStorage.getItem(materialStorageKey(saved, memberId)),
  ).toBeNull();
});
