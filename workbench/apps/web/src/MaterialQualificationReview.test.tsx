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
import { MaterialQualificationReview } from "./MaterialQualificationReview";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const scopeId = "00000000-0000-4000-8000-000000000001",
  recordId = "00000000-0000-4000-8000-000000000002";
const props = {
  base: "/bids/x/technical-scopes/s",
  scopeId,
  scopeDigest: "a".repeat(64),
  memberId: "member1",
};
const body = { binding: { scope_digest: props.scopeDigest } };
async function response(revision = 0, decision: string | null = null) {
  return {
    data: {
      version: "material-qualification-review-view/1",
      id: recordId,
      scope_id: scopeId,
      document: body,
      digest: await jsonDigest(body),
      revision,
      state: decision ?? "registered",
      decision,
      execution_authorized: false,
      accuracy_verified: false,
    },
    etag: `"material-qualification:${recordId}:${revision}"`,
  };
}
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});
async function load() {
  fireEvent.change(screen.getByLabelText("资格记录编号"), {
    target: { value: recordId },
  });
  fireEvent.click(screen.getByText("读取当前审核状态"));
  await screen.findByText(/状态：registered/);
}
it("registers metadata and requires explicit read before reviewing", async () => {
  mocked.mockResolvedValue(await response());
  render(<MaterialQualificationReview {...props} />);
  fireEvent.change(screen.getByLabelText("资格协议 JSON"), {
    target: { value: JSON.stringify(body) },
  });
  fireEvent.click(screen.getByText("登记不可变证据版本"));
  await waitFor(() =>
    expect(screen.getByLabelText("资格记录编号")).toHaveValue(recordId),
  );
  expect(screen.queryByText("批准所示证据")).not.toBeInTheDocument();
  await load();
  fireEvent.change(screen.getByLabelText("审核理由"), {
    target: { value: "Reviewed evidence" },
  });
  mocked.mockResolvedValue(await response(1, "approved"));
  fireEvent.click(screen.getByText("批准所示证据"));
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(3));
  expect(mocked.mock.calls[2][1]).toMatchObject({
    etag: `"material-qualification:${recordId}:0"`,
    body: { decision: "approved", reason: "Reviewed evidence" },
  });
});
it("recovers exact request after lost ACK across remount", async () => {
  mocked.mockRejectedValue(new Error("lost ACK"));
  const mounted = render(<MaterialQualificationReview {...props} />);
  fireEvent.change(screen.getByLabelText("资格协议 JSON"), {
    target: { value: JSON.stringify(body) },
  });
  fireEvent.click(screen.getByText("登记不可变证据版本"));
  await screen.findByText(/lost ACK/);
  const first = mocked.mock.calls[0];
  mounted.unmount();
  mocked.mockResolvedValue(await response());
  render(<MaterialQualificationReview {...props} />);
  fireEvent.click(await screen.findByText("恢复原审核请求"));
  await waitFor(() =>
    expect(screen.getByLabelText("资格记录编号")).toHaveValue(recordId),
  );
  expect(mocked.mock.calls[1]).toEqual(first);
});
it("ignores late response after member switch", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof response>>) => void;
  mocked.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const mounted = render(<MaterialQualificationReview {...props} />);
  fireEvent.change(screen.getByLabelText("资格记录编号"), {
    target: { value: recordId },
  });
  fireEvent.click(screen.getByText("读取当前审核状态"));
  mounted.rerender(
    <MaterialQualificationReview {...props} memberId="member2" />,
  );
  await act(async () => resolve(await response()));
  expect(screen.queryByText("批准所示证据")).not.toBeInTheDocument();
});
it("rejects mismatched scope and retains pending request", async () => {
  const bad = await response();
  bad.data.scope_id = recordId;
  mocked.mockResolvedValue(bad);
  render(<MaterialQualificationReview {...props} />);
  fireEvent.change(screen.getByLabelText("资格协议 JSON"), {
    target: { value: JSON.stringify(body) },
  });
  fireEvent.click(screen.getByText("登记不可变证据版本"));
  await screen.findByText(/资格回执身份/);
  expect(screen.getByText("恢复原审核请求")).toBeEnabled();
});
