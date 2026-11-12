import { expect, it } from "vitest";
import { searchEvidence } from "./evidenceTextSearch";
import { sourceEvidence } from "./sourceSurfaceFixtures.test-support";
const item = sourceEvidence.items[0];
it("matches Han OCR spacing without changing evidence", () => {
  const record = { ...item, quote: "第 一 章 施 工 方 案 ABC-12" };
  expect(searchEvidence([record], "施工方案").items[0]).toBe(record);
  expect(searchEvidence([record], "abc-12").total).toBe(1);
  expect(record.quote).toBe("第 一 章 施 工 方 案 ABC-12");
});
it("preserves numbers, punctuation, and non-Chinese word boundaries", () => {
  const record = { ...item, quote: "10.5 ABC 12" };
  for (const query of ["105", "10,5", "ABC12"])
    expect(searchEvidence([record], query).total).toBe(0);
});
it("ignores withdrawn sources and empty queries, does not join blocks", () => {
  const records = [
    { ...item, quote: "施工" },
    { ...item, id: "2", quote: "方案" },
    {
      ...item,
      id: "3",
      quote: "施工方案",
      source_status: "withdrawn" as const,
    },
  ];
  expect(searchEvidence(records, "施工方案").total).toBe(0);
  expect(searchEvidence(records, "  ").total).toBe(0);
});
it("counts all matches but caps rendered results", () => {
  const records = Array.from({ length: 45 }, (_, index) => ({
    ...item,
    id: String(index),
  }));
  const result = searchEvidence(records, "工期");
  expect(result.total).toBe(45);
  expect(result.items).toHaveLength(30);
});
it("treats search input literally rather than as regex", () => {
  expect(searchEvidence([{ ...item, quote: "型号[A+1]" }], "[A+1]").total).toBe(
    1,
  );
  expect(searchEvidence([item], ".*").total).toBe(0);
});
