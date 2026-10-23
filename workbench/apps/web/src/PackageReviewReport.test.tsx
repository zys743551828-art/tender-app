import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Report from "./PackageReviewReport";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  fixture = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("preserves the partial boundary and unresolved requirements while filtering the matrix", async () => {
  render(<Report run={fixture.completed} />);
  expect(screen.getByText(/整体覆盖仍为部分/)).toBeInTheDocument();
  expect(screen.getAllByRole("article")).toHaveLength(2);
  await userEvent.selectOptions(
    screen.getByLabelText("筛选核查结论"),
    "unable_to_judge",
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(
    screen.getByRole("heading", { name: "按招标文件规定的格式提供技术正文。" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/整体覆盖仍为部分/)).toBeInTheDocument();
});
it("never promotes a complete per-requirement matrix into a full-package pass", () => {
  const run = structuredClone(fixture.completed),
    m = run.result!.manifest;
  m.matrix[1] = { ...m.matrix[0], requirement_id: m.matrix[1].requirement_id };
  m.counts = {
    satisfied: 2,
    violated: 0,
    not_found: 0,
    unable_to_judge: 0,
    not_applicable: 0,
  };
  m.matrix_coverage = "complete";
  render(<Report run={run} />);
  expect(screen.getByText(/逐条判定矩阵已完成/)).toBeInTheDocument();
  expect(
    screen.getByText(/不形成整包通过、正式评分或投递资格/),
  ).toBeInTheDocument();
});
it("renders at most twenty requirement cards and changes pages without dropping the retained matrix", async () => {
  const run = structuredClone(fixture.completed),
    m = run.result!.manifest;
  m.matrix = Array.from({ length: 45 }, (_, n) => ({
    ...m.matrix[0],
    requirement_id: id(400 + n),
    requirement_statement: `合成要求第${n + 1}条`,
  }));
  m.requirement_count = 45;
  m.counts.satisfied = 45;
  render(<Report run={run} />);
  expect(screen.getAllByRole("article")).toHaveLength(20);
  await userEvent.click(screen.getByRole("button", { name: "下一页要求" }));
  expect(screen.getAllByRole("article")).toHaveLength(20);
  expect(
    screen.queryByRole("heading", { name: "合成要求第1条" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "合成要求第21条" }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "下一页要求" }));
  expect(screen.getAllByRole("article")).toHaveLength(5);
});
it("exports the complete retained run, including filtered-out requirements and digests", async () => {
  let exported: Blob | null = null;
  const create = vi.fn((blob: Blob) => {
    exported = blob;
    return "blob:synthetic-review";
  });
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = vi.fn();
    },
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  render(<Report run={fixture.completed} />);
  await userEvent.selectOptions(
    screen.getByLabelText("筛选核查结论"),
    "unable_to_judge",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "导出范围核查 JSON" }),
  );
  expect(create).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(exported!);
  });
  expect(JSON.parse(text)).toEqual(fixture.completed);
});
it("locates an exact original requirement from beyond the first page and keeps all requirements available after clearing search", async () => {
  fixture = await packageReviewFixture(45);
  const target = fixture.completed.result!.manifest.matrix[44];
  render(
    <Report
      run={fixture.completed}
      focusRequirementId={target.requirement_id}
    />,
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(
    screen.getByRole("heading", { name: target.requirement_statement }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "清除要求检索" }));
  expect(screen.getAllByRole("article")).toHaveLength(20);
  await userEvent.click(screen.getByRole("button", { name: "下一页要求" }));
  await userEvent.type(
    screen.getByLabelText("查找要求编号或内容"),
    target.requirement_statement,
  );
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "上一页要求" })).toBeDisabled();
  expect(
    screen.getByText(/导出 JSON 和报告仍包含本轮全部要求/),
  ).toBeInTheDocument();
});
