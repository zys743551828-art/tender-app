import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { AuthoringReferences } from "./AuthoringReferences";

const notReady = () =>
  Response.json(
    { code: "RULE_SET_NOT_READY", message: "要求提取尚未准备完成" },
    { status: 409 },
  );
const available = (ids: string[]) =>
  Response.json({
    id: "set",
    bid_id: "project",
    rules: ids.map((id) => ({
      id,
      statement: id,
      provenance_status: "effective",
    })),
  });
function Chapter() {
  const [attrs, setAttrs] = useState({
    title: "施工组织",
    ordinal: 1,
    rule_ids: ["已关联要求"],
    source_refs: [
      {
        source_id: "source",
        source_revision: 1,
        document_version_id: "doc",
        evidence_id: "quote",
      },
    ],
  });
  return (
    <AuthoringReferences
      bidId="project"
      content={{ attrs }}
      disabled={false}
      changeAttrs={setAttrs}
    />
  );
}
async function openChapter(readRules: () => Response) {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", async (path: string) => {
    switch (path) {
      case "/api/v1/bids/project/rules":
        return readRules();
      case "/api/v1/bids/project/materials":
        return Response.json({
          documents: [
            {
              id: "doc",
              filename: "合成招标文件.pdf",
              file_revision: 1,
              role: "tender",
            },
          ],
        });
      case "/api/v1/documents/doc/evidence":
        return Response.json({
          gaps: [],
          items: [
            {
              id: "evidence",
              physical_page: 2,
              quote: "合成工期依据",
              source_status: "published",
            },
          ],
        });
      default:
        throw new Error(`意外请求 ${path}`);
    }
  });
  render(<Chapter />);
  await user.click(screen.getByText(/本章要求与来源/));
  const picker = within(
    await screen.findByRole("group", { name: "关联当前项目要求" }),
  );
  return { user, picker };
}
afterEach(() => vi.unstubAllGlobals());

it("明确未就绪时可继续人工编写、读取来源，并可稍后重新关联当前要求", async () => {
  let readRules = notReady;
  const { user, picker } = await openChapter(() => readRules());
  expect(await picker.findByText(/要求清单尚未就绪.*人工编写/)).toBeVisible();
  expect(picker.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText(/本章要求与来源 · 1 条要求／1 处来源/)).toBeVisible();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "已入库来源文件" }),
    "doc",
  );
  expect(await screen.findByText("合成工期依据")).toBeVisible();
  readRules = () => available(["已关联要求", "新要求"]);
  await user.click(picker.getByRole("button", { name: "重新读取" }));
  expect(
    await picker.findByRole("checkbox", { name: "已关联要求" }),
  ).toBeChecked();
  await user.click(picker.getByRole("checkbox", { name: "新要求" }));
  expect(screen.getByText(/本章要求与来源 · 2 条要求／1 处来源/)).toBeVisible();
});

it("已有清单刷新成未就绪后，旧记录不再可选且章节原关联保留", async () => {
  let readRules = () => available(["已关联要求", "旧清单独有要求"]);
  const { picker } = await openChapter(() => readRules());
  expect(
    await picker.findByRole("checkbox", { name: "旧清单独有要求" }),
  ).toBeEnabled();
  readRules = notReady;
  act(() => {
    window.dispatchEvent(new Event("server-snapshot-change"));
  });
  expect(await picker.findByText(/要求清单尚未就绪.*人工编写/)).toBeVisible();
  expect(picker.queryAllByRole("checkbox")).toHaveLength(0);
  expect(screen.getByText(/本章要求与来源 · 1 条要求／1 处来源/)).toBeVisible();
});

it.each([
  [403, "RULE_SET_NOT_READY"],
  [409, "REVISION_CONFLICT"],
  [0, "NETWORK_ERROR"],
])("读取已展示的清单遇到 %s/%s 时保留真实错误与重试", async (status, code) => {
  let readRules = () => available(["旧清单独有要求"]);
  const { picker } = await openChapter(() => readRules());
  expect(
    await picker.findByRole("checkbox", { name: "旧清单独有要求" }),
  ).toBeEnabled();
  readRules = () => {
    if (status === 0) throw new TypeError("offline");
    return Response.json(
      { code, message: "清单读取失败" },
      { status: Number(status) },
    );
  };
  act(() => {
    window.dispatchEvent(new Event("server-snapshot-change"));
  });
  expect(await picker.findByRole("alert")).toHaveTextContent(String(code));
  expect(picker.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(picker.getByRole("button", { name: "重试" })).toBeEnabled();
});
