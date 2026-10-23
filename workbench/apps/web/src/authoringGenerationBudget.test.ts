import { expect, it } from "vitest";
import {
  generationAmountText,
  parseGenerationAmount,
  sumGenerationLimits,
} from "./authoringGenerationBudget";

it("金额转换精确保留九位小数，不经浮点四舍五入", () => {
  for (const [input, minor] of [
    ["0.1", 100000000],
    ["0.000000001", 1],
    ["1.999999999", 1999999999],
    ["9007199.254740991", Number.MAX_SAFE_INTEGER],
  ] as const) {
    expect(parseGenerationAmount(input)).toBe(minor);
    expect(generationAmountText(minor)).toBe(input);
  }
  expect(generationAmountText(0)).toBe("0");
  expect(parseGenerationAmount("0.100000000")).toBe(100000000);
});
it("拒绝过高精度、超出安全整数、指数、负数和非金额文本", () => {
  for (const value of [
    "0.0000000001",
    "9007199.254740992",
    "1e3",
    "-1",
    "+1",
    "1,000",
    "",
    "NaN",
    "Infinity",
    "1.",
  ]) {
    expect(parseGenerationAmount(value)).toBeNull();
  }
});
it("分章份额加总保持整数，上限溢出不能成为可确认预算", () => {
  expect(
    sumGenerationLimits([
      parseGenerationAmount("0.1")!,
      parseGenerationAmount("0.2")!,
    ]),
  ).toBe(parseGenerationAmount("0.3"));
  expect(sumGenerationLimits([Number.MAX_SAFE_INTEGER, 1])).toBeNull();
  expect(sumGenerationLimits([1, 0.1])).toBeNull();
  expect(() => generationAmountText(0.1)).toThrow();
});
