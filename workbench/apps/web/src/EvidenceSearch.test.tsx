import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Evidence } from "./Evidence";
import {
  sourceDocument,
  sourceEvidence,
  sourceGrant,
} from "./sourceSurfaceFixtures.test-support";
vi.mock("./PdfPreview", () => ({
  PdfPreview: ({ page }: { page: number }) => (
    <div aria-label={`原页${page}`} />
  ),
}));
beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input) => {
      const path = String(input);
      const newer = path.includes("source-v2");
      const id = newer ? "source-v2" : sourceDocument.id;
      const data = path.endsWith("/download")
        ? { ...sourceGrant, artifact_id: id }
        : {
            ...sourceEvidence,
            document_version_id: id,
            items: sourceEvidence.items.map((item) => ({
              ...item,
              document_version_id: id,
            })),
          };
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("navigates search matches to the text page on a narrow screen and clears", async () => {
  const old = window.innerWidth;
  Object.defineProperty(window, "innerWidth", {
    value: 390,
    configurable: true,
  });
  const user = userEvent.setup();
  const view = render(<Evidence document={sourceDocument} onClose={vi.fn()} />);
  const input = await screen.findByRole("searchbox", {
    name: "查找本文件解析文本",
  });
  await user.type(input, "第3页");
  expect(screen.getByRole("status")).toHaveTextContent("找到 1 个文本块");
  await user.click(
    screen.getByRole("button", { name: "查看匹配文本 · 第 3 页" }),
  );
  const text = screen.getByRole("region", { name: "解析文本依据" });
  expect(within(text).getByText(sourceEvidence.items[2].quote)).toBeVisible();
  expect(screen.getByRole("button", { name: "解析文本" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "清空查找" }));
  expect(input).toHaveValue("");
  expect(screen.queryByText("找到 1 个文本块。")).not.toBeInTheDocument();
  view.unmount();
  Object.defineProperty(window, "innerWidth", {
    value: old,
    configurable: true,
  });
});
it("does not retain a previous document query or results after version change", async () => {
  const user = userEvent.setup();
  const view = render(<Evidence document={sourceDocument} onClose={vi.fn()} />);
  await user.type(await screen.findByRole("searchbox"), "工期");
  expect(screen.getByRole("status")).toHaveTextContent("找到 3 个文本块");
  view.rerender(
    <Evidence
      document={{ ...sourceDocument, id: "source-v2" }}
      onClose={vi.fn()}
    />,
  );
  expect(await screen.findByRole("searchbox")).toHaveValue("");
  expect(screen.queryByText("找到 3 个文本块。")).not.toBeInTheDocument();
});
