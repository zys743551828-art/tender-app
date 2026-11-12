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
      { label: "维护服务方案", pages: [65] },
      { label: "商务或资格材料", pages: [1] },
    ]);
    expect(input[2].quote).toBe("维 保 方 案");
  });

  it("keeps construction and maintenance clues distinct without inferring one from the other", () => {
    expect(contentClues([item("施 工 组 织 设 计", 8)])).toEqual([
      { label: "施工组织或施工方案", pages: [8] },
    ]);
    expect(contentClues([item("维 保 方 案", 65)])).toEqual([
      { label: "维护服务方案", pages: [65] },
    ]);
  });

  it("can show both clues on the same page and deduplicates sorted pages independently", () => {
    const input = [
      item("施工方案及维护和服务", 9),
      item("维保方案", 3),
      item("施工组织设计", 2),
      item("维保方案", 9),
      item("施工方案", 9),
    ];
    const original = structuredClone(input);
    expect(contentClues(input)).toEqual([
      { label: "施工组织或施工方案", pages: [2, 9] },
      { label: "维护服务方案", pages: [3, 9] },
    ]);
    expect(input).toEqual(original);
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
