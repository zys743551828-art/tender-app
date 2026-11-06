import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { DocumentEvidenceView, DocumentView } from "./contracts";
import { PartialPageSelection } from "./PartialPageSelection";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: mocks.api,
  commandKey: () => "stable-key",
}));
const document = {
  id: "document",
  bid_id: "bid",
  sha256: "a".repeat(64),
} as DocumentView;
const evidence = {
  document_version_id: "document",
  parse_run_id: "parse",
  coverage: "partial",
  gaps: ["OCR"],
  items: [
    {
      id: "selected",
      physical_page: 65,
      quote: "所选原文",
      document_version_id: "document",
      parse_run_id: "parse",
    },
    {
      id: "outside",
      physical_page: 1,
      quote: "范围外原文",
      document_version_id: "document",
      parse_run_id: "parse",
    },
  ],
} as DocumentEvidenceView;
const record = {
  id: "selection",
  current_material: true,
  source_effectivity: "not_verified",
  model_execution_allowed: false,
  formal_qualification: false,
  proof: {
    digest: "d".repeat(64),
    manifest: {
      source: {
        document_version_id: "document",
        parse_run_id: "parse",
        file_digest: "a".repeat(64),
      },
      purpose: "technical_reference",
      coverage: "partial",
      selection: { first_page: 65, last_page: 65 },
      selected_pages: [
        { physical_page: 65, quality: "partial", gaps: ["OCR_LOW_CONFIDENCE"] },
      ],
      selected_blocks: [{ id: "selected", physical_page: 65 }],
      omitted_ranges: [
        { first_page: 1, last_page: 64 },
        { first_page: 66, last_page: 123 },
      ],
    },
  },
};

beforeEach(() => {
  mocks.api.mockReset();
});

it("requires explicit confirmation and shows only the selected evidence with its original page", async () => {
  const onPage = vi.fn();
  mocks.api.mockResolvedValue({ data: record });
  render(
    <PartialPageSelection
      document={document}
      evidence={evidence}
      page={65}
      pageCount={123}
      onPage={onPage}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  const submit = screen.getByRole("button", { name: "确认并保存页范围" });
  expect(submit).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(submit);
  expect(await screen.findByText("人工确认记录 · 部分覆盖")).toBeVisible();
  expect(mocks.api).toHaveBeenCalledTimes(2);
  await user.click(screen.getByText("查看所选范围的解析依据"));
  const status = screen.getByRole("status");
  mocks.api.mockResolvedValueOnce({
    data: {
      selection_id: record.id,
      proof_digest: record.proof.digest,
      model_execution_allowed: false,
      formal_qualification: false,
      items: [
        {
          id: "selected",
          physical_page: 65,
          quote: "所选原文",
          source_status: "candidate",
        },
      ],
    },
  });
  await user.click(
    within(status).getByRole("button", { name: "读取所选范围证据" }),
  );
  expect(await within(status).findByText("所选原文")).toBeVisible();
  expect(within(status).queryByText("范围外原文")).not.toBeInTheDocument();
  expect(
    within(status).queryByRole("button", { name: "第 1 物理页" }),
  ).not.toBeInTheDocument();
  await user.click(
    within(status).getByRole("button", { name: "第 65 物理页" }),
  );
  expect(onPage).toHaveBeenCalledWith(65);
});

it("refuses a rechecked record bound to another parse", async () => {
  const foreign = structuredClone(record);
  foreign.proof.manifest.source.parse_run_id = "other";
  mocks.api
    .mockResolvedValueOnce({ data: record })
    .mockResolvedValueOnce({ data: foreign });
  render(
    <PartialPageSelection
      document={document}
      evidence={evidence}
      page={65}
      pageCount={123}
      onPage={vi.fn()}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "确认并保存页范围" }));
  expect(
    await screen.findByText("已保存记录与复核依据不一致，请重新读取。"),
  ).toBeVisible();
  expect(screen.queryByText("人工确认记录 · 部分覆盖")).not.toBeInTheDocument();
});
