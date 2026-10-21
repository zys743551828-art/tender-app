import { expect, it } from "vitest";
import { textDifference } from "./textDifference";

it.each([
  ["", "新增"],
  ["删除", ""],
  ["相同\n文本", "相同\n文本"],
  ["第1段\n工期30天\n末段", "第1段\n工期45天\n末段"],
  ["👨‍👩‍👧‍👦 e\u0301 原文", "👨‍👩‍👧‍👦 e\u0301 新文"],
  ["甲乙甲乙甲", "乙甲乙甲乙"],
  ["\t首行\r\n尾行\n", "\t首行\r\n新增\n尾行\n"],
])("preserves both complete inputs: %j / %j", (before, after) => {
  const { changes } = textDifference(before, after);
  expect(
    changes
      .filter((part) => part.kind !== "added")
      .map((part) => part.text)
      .join(""),
  ).toBe(before);
  expect(
    changes
      .filter((part) => part.kind !== "removed")
      .map((part) => part.text)
      .join(""),
  ).toBe(after);
  if (before === after)
    expect(changes.every((part) => part.kind === "equal")).toBe(true);
});

it("marks the changed words and preserves common Unicode graphemes", () => {
  const { changes, blockComparison } = textDifference(
    "e\u0301 👩🏽‍🔧 旧方案结束",
    "e\u0301 👩🏽‍🔧 新方案结束",
  );
  expect(blockComparison).toBe(false);
  expect(changes).toEqual([
    { kind: "equal", text: "e\u0301 👩🏽‍🔧 " },
    { kind: "removed", text: "旧" },
    { kind: "added", text: "新" },
    { kind: "equal", text: "方案结束" },
  ]);
});

it("bounds large replacements without truncating either side", () => {
  const before = `共同开头\n${"甲".repeat(120_000)}\n共同结尾`;
  const after = `共同开头\n${"乙".repeat(120_000)}\n共同结尾`;
  const result = textDifference(before, after);
  expect(result.blockComparison).toBe(true);
  expect(
    result.changes
      .filter((part) => part.kind !== "added")
      .map((part) => part.text)
      .join(""),
  ).toBe(before);
  expect(
    result.changes
      .filter((part) => part.kind !== "removed")
      .map((part) => part.text)
      .join(""),
  ).toBe(after);
  expect(result.changes[0]).toEqual({ kind: "equal", text: "共同开头\n" });
  expect(result.changes.at(-1)).toEqual({ kind: "equal", text: "\n共同结尾" });
});
