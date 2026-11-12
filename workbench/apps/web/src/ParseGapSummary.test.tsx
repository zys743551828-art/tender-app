import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ParseGapSummary } from "./ParseGapSummary";

it("explains the observed case01 gaps without treating read pages as absent or qualified", async () => {
  const pages = Array.from({ length: 29 }, (_, i) => ({
    physical_page: i + 65,
    gaps: [
      "TEXT_VISUAL_COMPOSITION_UNVERIFIED",
      "SCAN_LAYOUT_TABLES_AND_VISUALS_UNVERIFIED",
      ...(i === 1 || i === 2 ? [] : ["OCR_LOW_CONFIDENCE"]),
    ],
  }));
  render(<ParseGapSummary pages={pages} />);
  await userEvent.click(screen.getByText("查看缺口原因与核查建议"));
  expect(screen.getByText(/缺口不等于整页未读/)).toBeVisible();
  expect(screen.getByText(/OCR 已尝试识别文字/)).toBeVisible();
  expect(screen.getByText(/颜色、描边或叠放关系/)).toBeVisible();
  expect(screen.getByText(/置信度偏低/)).toBeVisible();
  expect(screen.getAllByRole("term")).toHaveLength(3);
  expect(
    screen.getByText("OCR_LOW_CONFIDENCE").parentElement,
  ).not.toHaveTextContent("66、67");
  expect(
    screen.getByText("TEXT_VISUAL_COMPOSITION_UNVERIFIED").parentElement,
  ).toHaveTextContent("65、66、67");
});

it("distinguishes unread pages and retains unknown codes without inventing a diagnosis", async () => {
  render(
    <ParseGapSummary
      pages={[
        { physical_page: 94, gaps: ["DOCUMENT_PARSE_TIME_LIMIT"] },
        {
          physical_page: 95,
          gaps: ["PAGE_PARSE_FAILED", "FUTURE_GAP", "FUTURE_GAP"],
        },
      ]}
    />,
  );
  await userEvent.click(screen.getByText("查看缺口原因与核查建议"));
  expect(screen.getByText(/此页尚未读取/)).toBeVisible();
  expect(screen.getByText(/此页解析失败/)).toBeVisible();
  expect(screen.getByText("FUTURE_GAP")).toBeVisible();
  expect(screen.getAllByRole("term")).toHaveLength(3);
});

it("does not invent gaps for a page with none", () => {
  const { container } = render(
    <ParseGapSummary pages={[{ physical_page: 1, gaps: [] }]} />,
  );
  expect(container).toBeEmptyDOMElement();
});
