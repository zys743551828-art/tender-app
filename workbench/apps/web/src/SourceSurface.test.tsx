import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Evidence } from "./Evidence";
import { RetrievalDrawer } from "./RetrievalDrawer";
import {
  sourceDocument,
  sourceEvidence,
  sourceGrant,
  sourceSurfaceFixture,
} from "./sourceSurfaceFixtures.test-support";

vi.mock("./PdfPreview", () => ({
  PdfPreview: ({ page }: { page: number }) => (
    <canvas role="img" aria-label={`原页${page}`} />
  ),
}));
let available = 1160;
const originalWidth = window.innerWidth;
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  available = 1160;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  });
  const original = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const width =
        this.id === "main-content"
          ? available
          : this.hasAttribute("data-workspace-auxiliary-surface")
            ? Number.parseFloat(this.style.width) || 400
            : null;
      return width === null
        ? original.call(this)
        : {
            width,
            height: 900,
            left: innerWidth - width,
            right: innerWidth,
            top: 60,
            bottom: 960,
            x: innerWidth - width,
            y: 60,
            toJSON: () => ({}),
          };
    },
  );
  vi.stubGlobal("fetch", vi.fn(sourceSurfaceFixture().fetcher));
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: originalWidth,
  });
});
function Fixture() {
  const [retrieval, showRetrieval] = useState(false),
    [original, showOriginal] = useState(false);
  const closeRetrieval = useCallback(() => showRetrieval(false), []);
  const closeOriginal = useCallback(() => showOriginal(false), []);
  return (
    <main id="main-content">
      <label>
        正文草稿
        <textarea defaultValue="保持正文" />
      </label>
      <button onClick={() => showRetrieval(true)}>打开查证</button>
      <button onClick={() => showOriginal(true)}>直接打开原件</button>
      {retrieval && (
        <RetrievalDrawer
          bidId={sourceDocument.bid_id}
          title="合成项目"
          onClose={closeRetrieval}
        />
      )}
      {original && (
        <Evidence document={sourceDocument} onClose={closeOriginal} />
      )}
    </main>
  );
}
function setWidth(width: number) {
  available = width;
  act(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: width,
    });
    window.dispatchEvent(new Event("resize"));
  });
}
it("reserves desktop source space, keeps the body editable and releases only its own reservation", async () => {
  render(<Fixture />);
  const user = userEvent.setup();
  const body = screen.getByRole("textbox", { name: "正文草稿" });
  const trigger = screen.getByRole("button", { name: "打开查证" });
  await user.click(trigger);
  expect(
    screen.getByRole("complementary", { name: "查找原页依据" }),
  ).not.toHaveAttribute("aria-modal");
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(document.getElementById("main-content")).toHaveAttribute(
    "data-assistant-docked",
    "true",
  );
  await user.type(body, "继续编辑");
  expect(body).toHaveValue("保持正文继续编辑");
  await user.click(screen.getByRole("button", { name: "直接打开原件" }));
  await screen.findByRole("complementary", { name: sourceDocument.filename });
  expect(
    screen.queryByRole("complementary", { name: "查找原页依据" }),
  ).not.toBeInTheDocument();
  expect(document.getElementById("main-content")).toHaveAttribute(
    "data-assistant-docked",
    "true",
  );
  expect(
    document
      .getElementById("main-content")
      ?.style.getPropertyValue("--assistant-dock-space"),
  ).toBe("532px");
  await user.click(screen.getByRole("button", { name: "关闭原件" }));
  expect(document.getElementById("main-content")).not.toHaveAttribute(
    "data-assistant-docked",
  );
  expect(body).toHaveValue("保持正文继续编辑");
  expect(screen.getByRole("button", { name: "直接打开原件" })).toHaveFocus();
});

it("replaces only the parent source surface and preserves the exact query and nested focus", async () => {
  render(<Fixture />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "打开查证" }));
  const question = screen.getByRole("textbox", { name: "想查证什么？" });
  await user.type(question, "工期原问题");
  await user.click(screen.getByRole("button", { name: "查证当前项目资料" }));
  const opener = await screen.findByRole("button", {
    name: "核对来源并打开引用原页",
  });
  await user.click(opener);
  await screen.findByRole("complementary", { name: sourceDocument.filename });
  expect(question.closest("[data-workspace-auxiliary-panel]")).toHaveAttribute(
    "inert",
  );
  expect(question).toHaveValue("工期原问题");
  expect(document.body.style.overflow).not.toBe("hidden");
  await user.keyboard("{Escape}");
  expect(
    question.closest("[data-workspace-auxiliary-panel]"),
  ).not.toHaveAttribute("inert");
  expect(screen.getByRole("textbox", { name: "想查证什么？" })).toBe(question);
  expect(question).toHaveValue("工期原问题");
  expect(opener).toHaveFocus();
});

it("returns to the source trigger after an asynchronous check has lost browser focus", async () => {
  const fetcher = sourceSurfaceFixture().fetcher;
  let requests = 0;
  let resume!: () => void;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/retrievals") && ++requests === 2)
      await new Promise<void>((resolve) => {
        resume = resolve;
      });
    return fetcher(input, init);
  });
  render(<Fixture />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "打开查证" }));
  await user.type(
    screen.getByRole("textbox", { name: "想查证什么？" }),
    "工期",
  );
  await user.click(screen.getByRole("button", { name: "查证当前项目资料" }));
  const opener = await screen.findByRole("button", {
    name: "核对来源并打开引用原页",
  });
  await user.click(opener);
  expect(opener).toBeDisabled();
  // jsdom keeps disabled controls focused; reproduce Chromium's body fallback.
  document.body.tabIndex = -1;
  document.body.focus();
  document.body.removeAttribute("tabindex");
  expect(document.body).toHaveFocus();
  await act(async () => resume());
  await screen.findByRole("complementary", { name: sourceDocument.filename });
  await user.keyboard("{Escape}");
  await waitFor(() => expect(opener).toHaveFocus());
  expect(screen.getByRole("textbox", { name: "想查证什么？" })).toHaveValue(
    "工期",
  );
});

it("switches one compact source task at a time while keeping the original canvas, page and draft", async () => {
  setWidth(390);
  render(<Fixture />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "直接打开原件" }));
  await screen.findByText(sourceEvidence.gaps[0]);
  const canvas = screen.getByRole("img", { name: "原页1" });
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(document.body.style.overflow).toBe("hidden");
  expect(screen.getByRole("region", { name: "原文件预览" })).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "解析文本依据" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "解析文本" }));
  fireEvent.change(screen.getByRole("combobox", { name: "物理页" }), {
    target: { value: "3" },
  });
  expect(screen.getByText(sourceEvidence.items[2].quote)).toBeVisible();
  expect(canvas).not.toBeVisible();
  await user.click(screen.getByRole("button", { name: "原页" }));
  expect(screen.getByRole("img", { name: "原页3" })).toBe(canvas);
  setWidth(1280);
  await waitFor(() =>
    expect(
      screen.getByRole("complementary", { name: sourceDocument.filename }),
    ).toBeVisible(),
  );
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(screen.getByRole("img", { name: "原页3" })).toBe(canvas);
  expect(screen.getByRole("textbox", { name: "正文草稿" })).toHaveValue(
    "保持正文",
  );
});

it("ignores the previous document's late evidence and grant after changing the exact source", async () => {
  let resolve!: (value: Response) => void;
  const newer = {
    ...sourceDocument,
    id: "source-v2",
    filename: "第二份原件.pdf",
    file_revision: 2,
  };
  const json = (value: unknown) =>
    new Response(JSON.stringify(value), {
      headers: { "Content-Type": "application/json" },
    });
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("source-v1/evidence"))
      return new Promise<Response>((done) => {
        resolve = done;
      });
    if (url.endsWith("source-v2/evidence"))
      return json({
        ...sourceEvidence,
        document_version_id: newer.id,
        items: [
          {
            ...sourceEvidence.items[0],
            document_version_id: newer.id,
            quote: "确切第二份资料",
          },
        ],
      });
    return json({
      ...sourceGrant,
      artifact_id: url.includes("source-v2") ? newer.id : sourceDocument.id,
    });
  });
  const view = render(<Evidence document={sourceDocument} onClose={vi.fn()} />);
  view.rerender(<Evidence document={newer} onClose={vi.fn()} />);
  await screen.findByText("确切第二份资料");
  await act(async () => resolve(json(sourceEvidence)));
  expect(
    screen.queryByText(sourceEvidence.items[0].quote),
  ).not.toBeInTheDocument();
  expect(screen.getByText("确切第二份资料")).toBeVisible();
});

it("rejects a mismatched evidence identity and does not fetch a mismatched original grant", async () => {
  vi.mocked(fetch).mockImplementation(
    async (input) =>
      new Response(
        JSON.stringify(
          String(input).includes("/evidence")
            ? { ...sourceEvidence, document_version_id: "other-source" }
            : { ...sourceGrant, artifact_id: "other-source" },
        ),
        { headers: { "Content-Type": "application/json" } },
      ),
  );
  render(<Evidence document={sourceDocument} onClose={vi.fn()} />);
  await screen.findByRole("alert");
  expect(
    screen.queryByText(sourceEvidence.items[0].quote),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "下载资料原件" }),
  ).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
});
