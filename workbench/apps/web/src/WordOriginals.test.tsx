import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { WordCard } from "./WordOriginals";
import type { WordOriginalView } from "./contracts";
const word: WordOriginalView = {
  id: "word",
  bid_id: "bid",
  file_id: "file",
  original_name: "修改稿.docx",
  role: "body",
  original_saved: true,
  source_sha256: "a".repeat(64),
  byte_size: 100,
  inspection: {
    schema: "word-intake-inspection/1",
    container_validated: true,
    entry_count: 2,
    expanded_bytes: 100,
    xml_part_count: 1,
    active_content_gaps: [],
    unsupported_layout_features: [],
    requested_fonts: [],
    conversion_eligible: true,
    text_digest: "b".repeat(64),
  },
  conversion: {
    state: "succeeded",
    operation_id: "op",
    conversion_attempted: true,
    coverage: "partial",
    error_code: null,
    retryable: true,
    gaps: ["某字体尚未核验"],
    pdf_document_version_id: "pdf",
    controlled_render_verified: false,
  },
  message: "原件保留，转换范围尚未完整",
  delivery_check_message: "Word交付未获对应检查资格",
  review_qualification: "not_established_by_conversion",
  primary_action: {
    action: "upload_modified_pdf",
    label: "上传此修改稿的PDF",
    context: {
      bid_id: "bid",
      role: "body",
      declared_source_document_version_id: "word",
      target: { kind: "new_file" },
    },
  },
  converted_pdf_action: { action: "open_pdf", document_version_id: "pdf" },
};
function json(data: unknown, status = 200, etag?: string) {
  return new Response(JSON.stringify(data), {
    status,
    headers: etag ? { ETag: etag } : {},
  });
}
beforeEach(() => {
  sessionStorage.clear();
});
it("无转换结果显示可恢复说明，技术码留在折叠详情且不授予PDF或资格", async () => {
  const failed: WordOriginalView = {
    ...word,
    conversion: {
      ...word.conversion,
      state: "failed",
      conversion_attempted: false,
      coverage: "failed",
      gaps: ["WORD_CONVERSION_RESULT_MISSING"],
      pdf_document_version_id: null,
    },
    converted_pdf_action: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(failed)),
  );
  render(
    <WordCard initial={failed} bidId="bid" disabled={false} onPdf={vi.fn()} />,
  );
  expect(
    screen.getByText(
      "本次转换未返回可用的PDF。Word原件仍保留，可重试转换或上传对应PDF。",
    ),
  ).toBeVisible();
  expect(screen.getByText("Word交付未获对应检查资格")).toBeVisible();
  expect(screen.getByText("WORD_CONVERSION_RESULT_MISSING")).not.toBeVisible();
  expect(screen.queryByText(/尚未实际运行转换/)).not.toBeInTheDocument();
  expect(
    screen.getByText("请按下列范围提示继续；Word原件仍保留。"),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "下载此Word转换的PDF" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("查看转换状态详情"));
  expect(screen.getByText("WORD_CONVERSION_RESULT_MISSING")).toBeVisible();
});
it("处理成功但转换partial仍保留未完成与Word无资格，迟到历史不称当前采用", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("/word-originals/word")
        ? json(word, 200, '"word-state"')
        : json({
            source_document_version_id: "word",
            bid_id: "bid",
            adoption_state: "needs_selection",
            is_current_converted_pdf: false,
          }),
    ),
  );
  render(
    <WordCard initial={word} bidId="bid" disabled={false} onPdf={vi.fn()} />,
  );
  expect(screen.getByText("Word原件已保存／本次对应检查未完成")).toBeVisible();
  expect(screen.getByText("Word交付未获对应检查资格")).toBeVisible();
  await screen.findByText(
    "当前材料或稿件已变化，此转换仅留历史，未替换当前稿。",
  );
  expect(screen.queryByText("受控转换已完成")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "下载Word资料原件" }),
  ).toBeVisible();
});
it("补PDF固定原Word、项目、用途和独立file，不把关系称已核验", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(word)),
  );
  const pdf = vi.fn();
  render(<WordCard initial={word} bidId="bid" disabled={false} onPdf={pdf} />);
  await userEvent.upload(
    screen.getByLabelText("上传此修改稿的PDF"),
    new File(["%PDF-test"], "对应修改稿.pdf", { type: "application/pdf" }),
  );
  expect(pdf).toHaveBeenCalledOnce();
  expect(pdf.mock.calls[0][1]).toEqual(word.primary_action.context);
});
it("重试用Word GET实tag，202只受理，原件和未完成提示不冒变成功", async () => {
  const calls: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/retry-conversion")) {
        calls.push(init!);
        return json({ operation: { id: "retry", bid_id: "bid" } }, 202);
      }
      if (url.endsWith("/word-originals/word"))
        return json(word, 200, '"real-word-state"');
      return json({
        source_document_version_id: "word",
        bid_id: "bid",
        adoption_state: "pending",
      });
    }),
  );
  render(
    <WordCard initial={word} bidId="bid" disabled={false} onPdf={vi.fn()} />,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "重试此原件的转换" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "重试此原件的转换" }),
  );
  expect(new Headers(calls[0].headers).get("If-Match")).toBe(
    '"real-word-state"',
  );
  expect(screen.getByText("Word原件已保存／本次对应检查未完成")).toBeVisible();
});

it("安全拒绝说明可操作且真实码仅在详情中显示，不给PDF或授予资格", async () => {
  const blocked: WordOriginalView = {
    ...word,
    inspection: {
      ...word.inspection,
      active_content_gaps: ["WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED"],
      conversion_eligible: false,
    },
    conversion: {
      ...word.conversion,
      state: "failed",
      conversion_attempted: false,
      coverage: "failed",
      error_code: null,
      retryable: false,
      gaps: ["WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED"],
      pdf_document_version_id: null,
    },
    converted_pdf_action: null,
  };
  const fetch = vi.fn<typeof window.fetch>(async () => json(blocked));
  const onPdf = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(
    <WordCard initial={blocked} bidId="bid" disabled={false} onPdf={onPdf} />,
  );
  expect(
    screen.getByText(
      "此Word含动态域、宏或外部链接等不支持自动转换的内容。原件已保留；可移除相关内容后重新上传Word，或提供对应PDF。",
    ),
  ).toBeVisible();
  expect(screen.getByText("Word原件已保存／本次对应检查未完成")).toBeVisible();
  expect(screen.getByText(word.delivery_check_message)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "下载Word资料原件" }),
  ).toBeVisible();
  expect(screen.getByLabelText("上传此修改稿的PDF")).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "下载此Word转换的PDF" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "重试此原件的转换" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED"),
  ).not.toBeVisible();
  await userEvent.click(screen.getByText("查看转换状态详情"));
  expect(screen.getByText("WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED")).toBeVisible();
  expect(onPdf).not.toHaveBeenCalled();
  expect(
    fetch.mock.calls.every(
      (call) => !call[1]?.method || call[1].method === "GET",
    ),
  ).toBe(true);
});
