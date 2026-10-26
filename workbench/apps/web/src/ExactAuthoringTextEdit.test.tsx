import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { readExactDraftStatus } from "./authoringExactProtocol";
import { ExactAuthoringTextEdit } from "./ExactAuthoringTextEdit";
import native from "./test-fixtures/authoring-exact-text-edit-http.json";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});
function prepare(available = true) {
  mocked.mockImplementation(async (path, options) => {
    if (options?.method === "POST")
      return { data: native.ack, etag: native.ack_etag };
    if (path === "/authoring/exact-text-edit-capabilities")
      return {
        data: {
          ...native.capabilities,
          available,
          blocking_reasons: available
            ? []
            : ["AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED"],
        },
        etag: null,
      };
    if (path.startsWith("/sections/"))
      return { data: native.parent_section, etag: null };
    if (path.endsWith("/exact-qualification"))
      return { data: native.parent_qualification, etag: null };
    throw new Error(`Unexpected fixture request: ${path}`);
  });
  const onSaved = vi.fn().mockResolvedValue(undefined),
    onEditingChange = vi.fn();
  render(
    <ExactAuthoringTextEdit
      memberId={native.member_id}
      bidId={native.bid_id}
      draftId={native.parent_status.draft_id}
      sectionId={native.parent_section.id}
      status={readExactDraftStatus(
        native.parent_status,
        native.bid_id,
        native.parent_status.draft_id,
      )}
      etag={native.request_etag}
      disabled={false}
      onSaved={onSaved}
      onEditingChange={onEditingChange}
    />,
  );
  return { onSaved, onEditingChange };
}
it("requires explicit text, reason and confirmation; sends one original request and presents the native manual ACK", async () => {
  const user = userEvent.setup(),
    f = prepare();
  const begin = screen.getByRole("button", { name: "修改本章固定来源文字" });
  await waitFor(() => expect(begin).toBeEnabled());
  expect(
    mocked.mock.calls.filter(([, o]) => o?.method === "POST"),
  ).toHaveLength(0);
  await user.click(begin);
  const save = screen.getByRole("button", { name: "确认保存人工修订" });
  expect(save).toBeDisabled();
  await user.clear(screen.getByLabelText("修改后的文字"));
  await user.type(
    screen.getByLabelText("修改后的文字"),
    native.request.replacement_text,
  );
  await user.type(screen.getByLabelText("修订说明"), native.request.reason);
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(save);
  await screen.findByText(/人工文字修订已保存为草稿修订/);
  const writes = mocked.mock.calls.filter(([, o]) => o?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][1]?.body).toEqual(native.request);
  expect(writes[0][1]?.etag).toBe(native.request_etag);
  expect(f.onSaved).toHaveBeenCalledOnce();
  expect(f.onEditingChange).toHaveBeenCalledWith(true);
});
it("leaves editing unavailable when the installed capability is false", async () => {
  prepare(false);
  await screen.findByText("当前服务未开放固定来源文字修订。");
  expect(
    screen.getByRole("button", { name: "修改本章固定来源文字" }),
  ).toBeDisabled();
  expect(
    mocked.mock.calls.filter(([, o]) => o?.method === "POST"),
  ).toHaveLength(0);
});

it("keeps two paragraph changes across selection and sends one atomic request after explicit confirmation", async () => {
  const { syntheticMultiTextEdit } = await import(
    "./authoringMultiTextEdit.test-support"
  );
  const f = await syntheticMultiTextEdit();
  mocked.mockImplementation(async (path, options) => {
    if (options?.method === "POST") return { data: f.ack, etag: f.etag };
    if (path === "/authoring/exact-text-edit-capabilities")
      return { data: f.capabilities, etag: null };
    if (path.startsWith("/sections/"))
      return { data: f.pending.base.section, etag: null };
    return { data: f.pending.base.qualification, etag: null };
  });
  const saved = vi.fn().mockResolvedValue(undefined);
  render(
    <ExactAuthoringTextEdit
      {...f.scope}
      sectionId={f.pending.base.section.id}
      status={f.pending.base.status}
      etag={f.pending.etag}
      disabled={false}
      onSaved={saved}
      onEditingChange={vi.fn()}
    />,
  );
  const begin = screen.getByRole("button", { name: "修改本章固定来源文字" });
  await waitFor(() => expect(begin).toBeEnabled());
  await userEvent.click(begin);
  await userEvent.clear(screen.getByLabelText("修改后的文字"));
  await userEvent.type(
    screen.getByLabelText("修改后的文字"),
    "Synthetic change 0",
  );
  await userEvent.selectOptions(
    screen.getByLabelText("修改段落或标题"),
    "11111111-1111-4111-8111-111111111111",
  );
  await userEvent.clear(screen.getByLabelText("修改后的文字"));
  await userEvent.type(
    screen.getByLabelText("修改后的文字"),
    "Synthetic change 1",
  );
  await userEvent.click(screen.getByText(/^待保存节点 2：/));
  await userEvent.click(
    screen.getByRole("button", { name: "撤销节点 2 的修改" }),
  );
  expect(screen.getByLabelText("修改后的文字")).toHaveValue(
    "Synthetic second paragraph",
  );
  await userEvent.clear(screen.getByLabelText("修改后的文字"));
  await userEvent.type(
    screen.getByLabelText("修改后的文字"),
    "Synthetic change 1",
  );
  await userEvent.type(
    screen.getByLabelText("修订说明"),
    f.pending.body.reason,
  );
  expect(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  ).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  );
  await screen.findByText(/人工文字修订已保存为草稿修订/);
  const posts = mocked.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(posts).toHaveLength(1);
  expect(posts[0][1]?.body).toEqual(f.pending.body);
  expect(saved).toHaveBeenCalledOnce();
});
