import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { jsonDigest } from "./editorSchema";
import { QualifiedMaterialJob } from "./QualifiedMaterialJob";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
}));
const mocked = vi.mocked(api),
  id = "00000000-0000-4000-8000-000000000001";
const props = {
  base: "/bids/example/technical-scopes/test",
  scopeId: id,
  scopeDigest: "a".repeat(64),
  memberId: "member1",
  qualification: { id, digest: "b".repeat(64), revision: 1, state: "approved" },
};
async function result(
  options: NonNullable<Parameters<typeof api>[1]>,
  accepted = true,
) {
  return {
    data: {
      version: "material-qualified-job-receipt/1",
      intent_id: id,
      actor_id: props.memberId,
      scope_id: id,
      request: options.body,
      request_digest: await jsonDigest(options.body),
      request_key_digest: await jsonDigest(options.key),
      state: accepted ? "accepted_preparation" : "pending",
      pending_reason: accepted ? null : "NATIVE_UNCONFIRMED",
      job: accepted
        ? { job_id: id, job_digest: "c".repeat(64), generation: 1 }
        : null,
      send_authorized: false,
      accuracy_verified: false,
      fee_state: "not_observed",
    },
    etag: null,
  };
}
beforeEach(() => {
  sessionStorage.clear();
  mocked
    .mockReset()
    .mockImplementation(async (_path, options) => result(options!));
});
function fill() {
  fireEvent.change(screen.getByLabelText("材料续验编号"), {
    target: { value: id },
  });
  fireEvent.change(screen.getByLabelText("材料续验摘要"), {
    target: { value: "d".repeat(64) },
  });
}
it("binds current reviewed revision and distinguishes preparation from permission", async () => {
  render(<QualifiedMaterialJob {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  await screen.findByText(/原生准备任务已接受/);
  expect(mocked.mock.calls[0][1]).toMatchObject({
    etag: `"material-qualification:${id}:1"`,
    body: {
      qualification_id: id,
      qualification_revision: 1,
      scope_digest: props.scopeDigest,
    },
  });
  expect(screen.getByLabelText("原生材料任务回执")).toHaveTextContent(
    "不授予发送、收费或准确性资格",
  );
});
it("recovers exact pending key after lost ACK and changed review selection", async () => {
  mocked.mockRejectedValueOnce(new Error("lost ACK"));
  const first = render(<QualifiedMaterialJob {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  await screen.findByText(/lost ACK/);
  const request = mocked.mock.calls[0];
  first.unmount();
  render(
    <QualifiedMaterialJob
      {...props}
      qualification={{ ...props.qualification, revision: 2, state: "revoked" }}
    />,
  );
  fireEvent.click(await screen.findByText("恢复原任务申请"));
  await screen.findByText(/原生准备任务已接受/);
  expect(mocked.mock.calls[1]).toEqual(request);
});
it("retains unknown outcome without inventing another request", async () => {
  mocked.mockImplementation(async (_path, options) => result(options!, false));
  render(<QualifiedMaterialJob {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  await screen.findByText(/NATIVE_UNCONFIRMED/);
  expect(screen.getByText("登记固定准备任务")).toBeDisabled();
  fireEvent.click(screen.getByText("恢复原任务申请"));
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
  expect(mocked.mock.calls[1]).toEqual(mocked.mock.calls[0]);
});
it("does not send when durable browser recovery fails", async () => {
  const storage = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("storage unavailable");
    });
  render(<QualifiedMaterialJob {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  await screen.findByText(/storage unavailable/);
  expect(mocked).not.toHaveBeenCalled();
  storage.mockRestore();
});
it("rejects a receipt claiming send authority", async () => {
  mocked.mockImplementation(async (_p, o) => {
    const r = await result(o!);
    r.data.send_authorized = true;
    return r;
  });
  render(<QualifiedMaterialJob {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  await screen.findByText(/任务回执身份/);
  expect(screen.queryByText(/原生准备任务已接受/)).not.toBeInTheDocument();
});
it("does not apply a late receipt to another member", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof result>>) => void;
  mocked.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const view = render(<QualifiedMaterialJob key="member1" {...props} />);
  fill();
  fireEvent.click(screen.getByText("登记固定准备任务"));
  const options = mocked.mock.calls[0][1]!;
  view.rerender(
    <QualifiedMaterialJob key="member2" {...props} memberId="member2" />,
  );
  await act(async () => resolve(await result(options)));
  expect(screen.queryByText(/原生准备任务已接受/)).not.toBeInTheDocument();
  expect(screen.queryByText("恢复原任务申请")).not.toBeInTheDocument();
});
