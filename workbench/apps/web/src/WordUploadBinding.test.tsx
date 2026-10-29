import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi, beforeEach } from "vitest";
import { BindingRecovery } from "./Project";
import type { DocumentView } from "./contracts";
const doc: DocumentView = {
  id: "pdf",
  bid_id: "bid",
  filename: "旧正文.pdf",
  role: "body",
  artifact_kind: "bid_body",
  sha256: "a".repeat(64),
  byte_size: 100,
  media_type: "application/pdf",
  obtained_at: "2026-10-17T00:00:00Z",
  parse_coverage: "partial",
  file_id: "oldfile",
  file_revision: 1,
  previous_version_id: null,
  file_head_revision: 1,
  file_head_version_id: "pdf",
  source_relation: null,
};
beforeEach(() => sessionStorage.clear());
it("旧批次画面不是声明判定依据；fresh GET有Word声明时拒旧PDF版本目标并保留原因", async () => {
  const writes: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") writes.push(init.body);
      return new Response(
        JSON.stringify({
          id: "upload",
          word_pdf_declaration: {
            source_document_version_id: "word",
            role: "body",
            required_target_kind: "new_file",
            relation_kind: "user_declared_same_draft",
            verification_status: "unverified",
          },
        }),
        { headers: { ETag: '"real-upload"' } },
      );
    }),
  );
  render(
    <BindingRecovery uploadId="upload" documents={[doc]} onUpdated={vi.fn()} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "调整入库目标" }));
  await userEvent.selectOptions(screen.getByLabelText("入库目标"), "oldfile");
  await userEvent.type(screen.getByLabelText("调整原因"), "我的原因保留");
  await userEvent.click(
    screen.getByRole("button", { name: "确认新的入库目标" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("只能作为独立文件"),
  );
  expect(writes).toHaveLength(0);
  expect(screen.getByLabelText("调整原因")).toHaveValue("我的原因保留");
  expect(screen.getByLabelText("入库目标")).toHaveValue("");
});
it("旧ACK缺新字段不能解释为无声明；新GET未提供约束就地保留原件", async () => {
  const post = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") post();
      return new Response(JSON.stringify({ id: "upload" }), {
        headers: { ETag: '"real-upload"' },
      });
    }),
  );
  render(
    <BindingRecovery uploadId="upload" documents={[]} onUpdated={vi.fn()} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "调整入库目标" }));
  await userEvent.type(screen.getByLabelText("调整原因"), "核对后沿用独立文件");
  await userEvent.click(
    screen.getByRole("button", { name: "确认新的入库目标" }),
  );
  await screen.findByText(/服务器尚未提供本次上传的对应稿约束/);
  expect(post).not.toHaveBeenCalled();
});
