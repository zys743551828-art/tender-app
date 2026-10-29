import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthoringBuilds } from "./AuthoringBuilds";
import type {
  AuthoringCapabilities,
  BuildView,
  DraftView,
  Operation,
} from "./contracts";
import type { ApiResult } from "./api";

const capabilities: AuthoringCapabilities = {
  schema_digest: "a".repeat(64),
  schema: { version: 1, nodes: [], marks: [], metadata: [] },
  default_template_version_id: "template",
  formats: ["docx", "pdf"],
  supports_external_docx_import: false,
  supported_nodes: [],
  unsupported: [],
};
const head: ApiResult<DraftView> = {
  data: {
    id: "draft",
    bid_id: "bid",
    revision: 8,
    snapshot_id: "snapshot-8",
    sections: [],
  },
  etag: '"draft-8"',
};
const operation: Operation = {
  id: "operation",
  bid_id: "bid",
  kind: "build",
  state: "succeeded",
  input_digest: "a".repeat(64),
  handler_version: "test",
  result_ref: null,
};
const result: BuildView = {
  id: "build",
  draft_snapshot_id: "snapshot-8",
  operation_id: operation.id,
  outputs: [
    {
      format: "docx",
      state: "succeeded",
      document_version_id: "word",
      gaps: [],
    },
    {
      format: "pdf",
      state: "failed",
      document_version_id: null,
      gaps: ["转换器未就绪，Word仍可取件"],
    },
  ],
};
function response(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

it("构建等待保存ACK，使用确认修订；PDF失败不会把Word成功改写为整体就绪", async () => {
  let ack: ((value: ApiResult<DraftView>) => void) | undefined;
  const prepare = vi.fn(
    () =>
      new Promise<ApiResult<DraftView>>((resolve) => {
        ack = resolve;
      }),
  );
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/bids/bid/builds" && options?.method !== "POST")
        return response({ items: [], next_cursor: null, has_more: false });
      if (url === "/api/v1/bids/bid/builds") {
        writes.push(options!);
        return response({
          resource_kind: "build",
          resource_id: "build",
          operation,
        });
      }
      if (url === "/api/v1/builds/build") return response(result);
      if (url === "/api/v1/operations/operation") return response(operation);
      throw new Error(`Unexpected ${url}`);
    }),
  );
  render(
    <AuthoringBuilds
      bidId="bid"
      memberId="member"
      draftId="draft"
      capabilities={capabilities}
      disabled={false}
      prepare={prepare}
      setBusy={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存确认后生成文件" }),
  );
  expect(writes).toHaveLength(0);
  await act(async () => {
    ack!(head);
  });
  await screen.findByText("转换器未就绪，Word仍可取件");
  expect(JSON.parse(writes[0].body as string)).toMatchObject({
    draft_id: "draft",
    draft_revision: 8,
    follow_up: "none",
  });
  expect(screen.getByText("此格式生成成功")).toBeInTheDocument();
  expect(screen.getByText("此格式生成失败")).toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: "下载投标正文（Word）" }),
  ).toHaveLength(1);
});
it("失响应恢复重试原修订和幂等键，刷新后也不悄悄改用新稿", async () => {
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/bids/bid/builds" && options?.method !== "POST")
        return response({ items: [], next_cursor: null, has_more: false });
      if (url === "/api/v1/bids/bid/builds") {
        writes.push(options!);
        throw new TypeError("network lost");
      }
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const prepare = vi.fn().mockResolvedValue(head);
  const first = render(
    <AuthoringBuilds
      bidId="bid"
      memberId="member"
      draftId="draft"
      capabilities={capabilities}
      disabled={false}
      prepare={prepare}
      setBusy={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存确认后生成文件" }),
  );
  await screen.findByRole("button", { name: "重试受理草稿修订 8" });
  first.unmount();
  const latest = vi
    .fn()
    .mockResolvedValue({ ...head, data: { ...head.data, revision: 99 } });
  render(
    <AuthoringBuilds
      bidId="bid"
      memberId="member"
      draftId="draft"
      capabilities={capabilities}
      disabled={false}
      prepare={latest}
      setBusy={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "重试受理草稿修订 8" }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(latest).not.toHaveBeenCalled();
  expect(writes[1].body).toEqual(writes[0].body);
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).toEqual(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
});
it("保存没有确认时不发送构建请求", async () => {
  const fetcher = vi.fn(async () =>
    response({ items: [], next_cursor: null, has_more: false }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <AuthoringBuilds
      bidId="bid"
      memberId="member"
      draftId="draft"
      capabilities={capabilities}
      disabled={false}
      prepare={async () => null}
      setBusy={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存确认后生成文件" }),
  );
  expect(
    fetcher.mock.calls.every(
      (call) =>
        !((call as unknown[])[1] as RequestInit | undefined)?.method ||
        ((call as unknown[])[1] as RequestInit).method === "GET",
    ),
  ).toBe(true);
});
