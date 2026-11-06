import { describe, expect, it } from "vitest";
import { contentClues } from "./contentClues";
import type { EvidenceView } from "./contracts";

const item = (
  quote: string,
  physical_page: number,
  overrides = {},
): EvidenceView => ({
  id: String(physical_page),
  document_version_id: "doc",
  parse_run_id: "run",
  physical_page,
  printed_label: null,
  kind: "text",
  quote,
  bbox: [1, 1, 2, 2],
  page_width: 100,
  page_height: 100,
  rotation: 0,
  source_status: "published",
  ...overrides,
});

describe("content navigation clues", () => {
  it("shows several possible categories from text, including spaced OCR, without changing quotations", () => {
    const input = [
      item("投 标 文 件（商 务 文 件）", 1),
      item("项目投入使用后的维护和服务", 65),
      item("维 保 方 案", 65),
    ];
    expect(contentClues(input)).toEqual([
      { label: "施工或维护方案", pages: [65] },
      { label: "商务或资格材料", pages: [1] },
    ]);
    expect(input[2].quote).toBe("维 保 方 案");
  });

  it("does not infer missing content or use withdrawn or non-text evidence", () => {
    expect(
      contentClues([
        item("施 工 组 织 设 计", 2, { source_status: "withdrawn" }),
        item("施工方案", 3, { kind: "visual_observation" }),
        item("深基模", 4),
      ]),
    ).toEqual([]);
  });
});
