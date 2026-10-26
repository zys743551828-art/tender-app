import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthoringRichTools } from "./AuthoringRichTools";
import {
  readAuthoringContent,
  serializeAuthoringContent,
} from "./richEditorSchema";
import { SectionEditor } from "./SectionEditor";
import type {
  AuthoringCapabilities,
  AuthoringRichCapabilities,
  SectionView,
} from "./contracts";

const capabilities: AuthoringCapabilities = {
  schema_digest: "a".repeat(64),
  schema: { version: 1, nodes: [], marks: [], metadata: [] },
  default_template_version_id: "template",
  formats: ["docx", "pdf"],
  supports_external_docx_import: false,
  supported_nodes: [],
  unsupported: [],
};
const rich: AuthoringRichCapabilities = {
  schema_digest: "b".repeat(64),
  schema: {},
  build_schema_digest: "c".repeat(64),
  image_upload_max_bytes: 8388608,
  renderer_configured: false,
  runtime_verified_by_this_read: false,
  table_pdf_geometry: "unverified",
  pagination_modes: [
    { mode: "chapter_start_new_page", page_count_impact: "每章另起一页" },
  ],
};
const content = {
  type: "doc",
  attrs: { title: "人工章节", ordinal: 0, rule_ids: [], source_refs: [] },
  content: [
    {
      type: "table",
      attrs: {
        id: "table-1",
        column_widths_twips: [2500, 2500],
        caption: "工序安排",
      },
      content: [
        {
          type: "tableRow",
          attrs: { id: "row-1" },
          content: [
            {
              type: "tableCell",
              attrs: { id: "cell-1", colspan: 2, rowspan: 1, header: true },
              content: [
                {
                  type: "paragraph",
                  attrs: { id: "paragraph-1" },
                  content: [{ type: "text", text: "保持合并表格内容" }],
                },
              ],
            },
          ],
        },
      ],
    },
  ],
};
function response(value: unknown, etag?: string) {
  return new Response(JSON.stringify(value), {
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

it.each([false, true])(
  "既有RICH章节可编辑保存，保留合并单元格、稳定节点和明确RICH摘要（旧版=%s）",
  async (legacy) => {
    const richVersion = legacy
      ? {
          ...rich,
          schema: { version: 3, previous_schema_digest: "e".repeat(64) },
        }
      : rich;
    let section = {
      id: "section",
      draft_id: "draft",
      revision: 1,
      schema_digest: legacy ? "e".repeat(64) : rich.schema_digest,
      writing_plan_id: null,
      content: structuredClone(content),
    } as SectionView;
    const writes: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options?: RequestInit) => {
        if (url === "/api/v1/sections/section") return response(section);
        if (
          url === "/api/v1/bids/bid/drafts/draft" &&
          options?.method === "PATCH"
        ) {
          writes.push(options);
          const body = JSON.parse(options.body as string);
          section = {
            ...section,
            revision: 2,
            content: body.changes[0].content,
          };
          return response(
            {
              draft_id: "draft",
              draft_revision: 2,
              snapshot_id: "snapshot-2",
              snapshot_digest: "d".repeat(64),
            },
            '"draft-2"',
          );
        }
        throw new Error(`Unexpected ${url}`);
      }),
    );
    render(
      <SectionEditor
        bidId="bid"
        memberId="member"
        draft={{
          id: "draft",
          bid_id: "bid",
          revision: 1,
          snapshot_id: "snapshot-1",
          sections: [],
        }}
        etag={'"draft-1"'}
        sectionId="section"
        capabilities={capabilities}
        richCapabilities={richVersion}
        disabled={false}
        onSaved={vi.fn()}
      />,
    );
    await screen.findByText("保持合并表格内容");
    const title = screen.getByRole("textbox", { name: "章节名称" });
    await userEvent.clear(title);
    await userEvent.type(title, "更新的人工章节");
    await userEvent.click(screen.getByRole("button", { name: "立即保存" }));
    await screen.findByText(/已保存 · 章节修订 2/);
    const request = JSON.parse(writes[0].body as string);
    expect(request.changes[0].schema_digest).toBe(rich.schema_digest);
    expect(request.changes[0].content.content).toEqual(content.content);
    expect(request.changes[0].content.attrs.title).toBe("更新的人工章节");
    expect(new Headers(writes[0].headers).get("If-Match")).toBe('"draft-1"');
  },
);

it("未知章节格式保留原件，不用文字schema把表格降为可编辑空稿", async () => {
  const fetcher = vi.fn(async () =>
    response({
      id: "section",
      draft_id: "draft",
      revision: 1,
      schema_digest: "f".repeat(64),
      writing_plan_id: null,
      content,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <SectionEditor
      bidId="bid"
      memberId="member"
      draft={{
        id: "draft",
        bid_id: "bid",
        revision: 1,
        snapshot_id: "snapshot-1",
        sections: [],
      }}
      etag={'"draft-1"'}
      sectionId="section"
      capabilities={capabilities}
      richCapabilities={rich}
      disabled={false}
      onSaved={vi.fn()}
    />,
  );
  await screen.findByText(/章节格式无法核对/);
  expect(
    screen.queryByRole("textbox", { name: "章节正文" }),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
});

it("界面显式选择重复表头后才写入冻结声明", async () => {
  const changed = vi.fn();
  const value = readAuthoringContent({ ...content, content: [] });
  render(
    <AuthoringRichTools
      bidId="bid"
      memberId="member"
      value={value}
      capabilities={rich}
      disabled={false}
      onChange={changed}
    />,
  );
  await userEvent.click(
    screen.getByText("编制表格与图片 · 保留结构及固定图片版本"),
  );
  const repeat = await screen.findByRole("checkbox", {
    name: /跨页重复首行表头/,
  });
  expect(repeat).not.toBeChecked();
  await userEvent.click(repeat);
  await userEvent.click(screen.getByRole("button", { name: "插入表格到章末" }));
  expect(changed).toHaveBeenCalledTimes(1);
  const document = serializeAuthoringContent(changed.mock.calls[0][0]);
  expect(document.content[0].attrs).toHaveProperty("pagination", {
    protocol: "authoring-table-pagination/1",
    repeat_header_rows: 1,
  });
});
