/* global process, URL, console, window, document, innerWidth */
// Actual source/retrieval/PDF/feedback components with explicit synthetic HTTP.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-source-feedback-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const hash = (data) => createHash("sha256").update(data).digest("hex");
const assert = (value, message) => {
  if (!value) throw Error(message);
};
await fs.mkdir(out, { recursive: true });

// Generated pages carry no business information.
const pageCount = 36;
const objects = [
  "<< /Type /Catalog /Pages 2 0 R >>",
  `<< /Type /Pages /Kids [${Array.from({ length: pageCount }, (_, i) => `${4 + i * 2} 0 R`).join(" ")}] /Count ${pageCount} >>`,
  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
];
for (let number = 1; number <= pageCount; number++) {
  const contentId = objects.length + 2;
  objects.push(
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${contentId} 0 R >>`,
  );
  const stream = `BT /F1 23 Tf 60 710 Td (Synthetic original / physical page ${number}) Tj 0 -48 Td /F1 14 Tf (Schedule: 240 days. See appendix for rain conditions.) Tj 0 -30 Td (This fixture does not establish review completeness.) Tj ET\n0.2 0.35 0.7 RG 60 570 492 80 re S\n`;
  objects.push(
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}endstream`,
  );
}
let pdf = "%PDF-1.4\n";
const offsets = [0];
objects.forEach((object, index) => {
  offsets.push(Buffer.byteLength(pdf));
  pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
});
const xref = Buffer.byteLength(pdf);
pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
  .slice(1)
  .map((offset) => String(offset).padStart(10, "0") + " 00000 n \n")
  .join(
    "",
  )}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
await fs.writeFile(path.join(out, "synthetic.pdf"), pdf);

async function sourceFiles(directory) {
  const result = {};
  for (const item of await fs.readdir(directory, { withFileTypes: true })) {
    const name = path.join(directory, item.name);
    if (item.isDirectory()) Object.assign(result, await sourceFiles(name));
    else if (item.isFile()) result[name] = hash(await fs.readFile(name));
  }
  return result;
}
const before = await sourceFiles(path.join(root, "src"));
const entry = `
import React, { useCallback, useState } from "react";
import { createRoot } from "react-dom/client";
import { RetrievalDrawer } from "./src/RetrievalDrawer";
import { Evidence } from "./src/Evidence";
import { ErrorNotice, LoadingSkeleton } from "./src/components";
import { ResourceState } from "./src/ResourceState";
import { ApiError } from "./src/api";
import { ThemePicker } from "./src/ThemePicker";
import { useTheme } from "./src/theme";
import { sourceDocument, sourceEvidence, sourceSurfaceFixture } from "./src/sourceSurfaceFixtures.test-support";
import "./src/styles.css";
sourceDocument.sha256 = ${JSON.stringify(hash(pdf))}; sourceDocument.byte_size = ${Buffer.byteLength(pdf)};
sourceEvidence.gaps = ["合成资料含未核对的文字。"];
for (let page = 4; page <= ${pageCount}; page++) {
  sourceEvidence.items.push({...sourceEvidence.items[0], id:"long-page-"+page, physical_page:page,
    quote:"合成第"+page+"页："+"施工方案与工期，仅供本地滚动测试。".repeat(5)});
}
const fixture = sourceSurfaceFixture(); window.__sourceQA = fixture;
const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => new URL(String(input), location.href).pathname.startsWith("/api/v1/") ? fixture.fetcher(input, init) : nativeFetch(input, init);
function Harness() {
 const theme = useTheme(); const [retrieval, openRetrieval] = useState(false), [original, openOriginal] = useState(false), [retried, retry] = useState(0), [reads, read] = useState(0);
 const closeRetrieval = useCallback(() => openRetrieval(false), []), closeOriginal = useCallback(() => openOriginal(false), []);
 return <div className="app-shell"><aside className="sidebar"><strong>投标工作台</strong><p>合成原件与界面验收</p></aside><div className="workspace"><header className="topbar"><span>查证与原页 · 合成验收</span><ThemePicker {...theme}/></header><main id="main-content"><div className="page-content"><h1>正文与资料对照</h1><section className="panel" style={{padding:20}}><label>正文草稿<textarea style={{width:"100%",minHeight:160}} defaultValue="已编辑的正文仍保持。" /></label><div className="button-row"><button className="button secondary" onClick={()=>openRetrieval(true)}>打开查证</button><button className="button secondary" onClick={()=>openOriginal(true)}>直接打开原件</button></div><p className="small-note">当前为不完整解析范围，请逐页核对原件；不构成通过结论。</p></section><section className="panel" style={{padding:20}}><h2>反馈状态样例</h2><LoadingSkeleton text="正在读取合成列表…"/><ErrorNotice error={new ApiError("来源已经变化，请重新核对。",409,"SYNTHETIC_SOURCE_CHANGED","synthetic-request-original",false,{expected_revision:7})} onRetry={()=>retry(v=>v+1)}/><span>显式重试次数：{retried}</span><ResourceState hasData={false} onRetry={()=>read(v=>v+1)} emptyLabel="尚未保存模板"/><span>显式读取次数：{reads}</span></section>{retrieval&&<RetrievalDrawer bidId={sourceDocument.bid_id} title="合成项目" onClose={closeRetrieval}/>} {original&&<Evidence document={sourceDocument} onClose={closeOriginal}/>}</div></main></div></div>;
}
createRoot(document.getElementById("root")).render(<Harness/>);
`;
const built = await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  format: "esm",
  jsx: "automatic",
  outdir: out,
  entryNames: "app",
  metafile: true,
  external: ["/fonts/*"],
  logLimit: 5,
  plugins: [
    {
      name: "asset-urls",
      setup(builder) {
        builder.onResolve({ filter: /\?url$/ }, (args) => ({
          path: require.resolve(args.path.slice(0, -4)),
          namespace: "asset-url",
        }));
        builder.onLoad(
          { filter: /.*/, namespace: "asset-url" },
          async (args) => {
            const name = path.basename(args.path);
            await fs.copyFile(args.path, path.join(out, name));
            return {
              contents: `export default ${JSON.stringify("/" + name)}`,
              loader: "js",
            };
          },
        );
      },
    },
  ],
});
const source = {};
for (const input of Object.keys(built.metafile.inputs)) {
  const absolute = path.resolve(root, input);
  if (!before[absolute]) continue;
  const after = hash(await fs.readFile(absolute));
  assert(after === before[absolute], `Source changed while bundling: ${input}`);
  source[path.relative(root, absolute)] = after;
}
await fs.copyFile(
  path.join(root, "public/theme.js"),
  path.join(out, "theme.js"),
);
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>查证与原页合成验收</title><script src="/theme.js"></script><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
  ".pdf": "application/pdf",
  ".wasm": "application/wasm",
};
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const directory =
      name.startsWith("/fonts/") || name.startsWith("/pdfjs/")
        ? path.join(root, "public")
        : out;
    const target = path.resolve(
      directory,
      `.${name === "/" ? "/index.html" : name}`,
    );
    assert(target.startsWith(directory + path.sep), "outside fixture");
    const content = await fs.readFile(target);
    res.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const receipt = {
  scope:
    "Actual RetrievalDrawer/Evidence/SourceSurface/PdfPreview and shared feedback; synthetic HTTP and a real synthetic PDF. No backend service, private originals or paid calls.",
  source_sha256: source,
  bundle_sha256: hash(await fs.readFile(path.join(out, "app.js"))),
  pdf: { sha256: hash(pdf), bytes: Buffer.byteLength(pdf), pages: pageCount },
  cases: [],
  screenshots: [],
  page_errors: [],
  external_requests: [],
};
let browser, lastPage;
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(out, name + ".png") });
  receipt.screenshots.push(name + ".png");
}
async function layout(page, label) {
  const value = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    outside: [...document.querySelectorAll("input,select,textarea,button")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        return (
          el.getClientRects().length &&
          rect.width > 0 &&
          (rect.left < -1 || rect.right > innerWidth + 1)
        );
      })
      .map((el) => el.textContent || el.getAttribute("aria-label")),
    unexpected: window.__sourceQA.state.unexpected,
  }));
  assert(
    value.scroll <= value.width + 1 &&
      !value.outside.length &&
      !value.unexpected.length,
    JSON.stringify({ label, value }),
  );
}
async function visiblePortion(target) {
  return target.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    let top = Math.max(0, rect.top);
    let bottom = Math.min(window.innerHeight, rect.bottom);
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      if (window.getComputedStyle(parent).overflowY === "visible") continue;
      const start = parent.getBoundingClientRect().top + parent.clientTop;
      top = Math.max(top, start);
      bottom = Math.min(bottom, start + parent.clientHeight);
    }
    const x = rect.x + rect.width / 2;
    const y = (top + bottom) / 2;
    const height =
      bottom > top && el.contains(document.elementFromPoint(x, y))
        ? Math.floor(bottom - top)
        : 0;
    return { x, y, height };
  });
}

async function wheelToReading(page, target, height) {
  // Start in the dialog gutter, outside the expanded forms.
  await page.mouse.move(4, height / 2);
  let visible = (await visiblePortion(target)).height;
  for (let i = 0; i < 12; i++) {
    await page.mouse.wheel(0, 100);
    await page.evaluate(
      () =>
        new Promise((done) =>
          window.requestAnimationFrame(() =>
            window.requestAnimationFrame(done),
          ),
        ),
    );
    visible = Math.max(visible, (await visiblePortion(target)).height);
  }
  return visible;
}

async function expandedReading(page, width, height) {
  await page.setViewportSize({ width, height });
  await page.goto(origin);
  const opener = page.getByRole("button", { name: "直接打开原件" });
  await opener.scrollIntoViewIfNeeded();
  const openerY = (await opener.boundingBox()).y;
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "合成工期要求.pdf" });
  const pages = dialog.getByRole("combobox", { name: "物理页", exact: true });
  await pages.selectOption(String(pageCount));
  const canvas = dialog.getByRole("img", {
    name: `合成工期要求.pdf，物理页${pageCount}原页`,
  });
  await canvas.waitFor();
  await dialog.getByLabel("查找本文件解析文本").fill("施工方案");
  await dialog.getByText(`查看 ${pageCount - 3} 个可能相关页`).click();
  await dialog.getByText("人工确认部分页范围").click();
  await dialog.getByLabel("起始物理页").fill(String(pageCount - 1));
  const confirm = dialog.getByRole("checkbox");
  await confirm.check();
  await layout(page, `${width}x${height}-expanded`);
  const canvasHeight = await wheelToReading(page, canvas, height);
  const paper = await visiblePortion(canvas);
  let scrolledPdf = false;
  if (paper.height > 0) {
    const container = dialog.locator(".pdf-canvas-container");
    const before = await container.evaluate((el) => el.scrollTop);
    await page.mouse.move(paper.x, paper.y);
    await page.mouse.wheel(0, before > 5 ? -140 : 140);
    await page.waitForFunction(
      (previous) =>
        Math.abs(
          document.querySelector(".pdf-canvas-container").scrollTop - previous,
        ) > 1,
      before,
    );
    scrolledPdf = true;
  }
  await screenshot(page, `expanded-original-${width}x${height}`);
  await dialog.getByRole("button", { name: "解析文本", exact: true }).click();
  const textHeight = await wheelToReading(
    page,
    dialog.locator(".evidence-quote p").first(),
    height,
  );
  const confirmed =
    (await confirm.isChecked()) &&
    (await dialog.getByLabel("起始物理页").inputValue()) ===
      String(pageCount - 1);
  await screenshot(page, `expanded-text-${width}x${height}`);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  const restored = await opener.evaluate(
    (el, y) =>
      document.activeElement === el &&
      document.body.style.overflow !== "hidden" &&
      Math.abs(el.getBoundingClientRect().y - y) <= 1,
    openerY,
  );
  return {
    width,
    height,
    canvasHeight,
    textHeight,
    scrolledPdf,
    confirmed,
    restored,
  };
}
async function localRequests(page) {
  page.on("pageerror", (error) => receipt.page_errors.push(error.message));
  await page.route("**/*", (route) => {
    if (
      route
        .request()
        .url()
        .startsWith(origin + "/")
    )
      return route.continue();
    receipt.external_requests.push(route.request().url());
    return route.abort();
  });
}
try {
  browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  receipt.expanded = [];
  for (const [width, height] of [
    [390, 640],
    [760, 360],
  ]) {
    const page = await browser.newPage();
    lastPage = page;
    await localRequests(page);
    receipt.expanded.push(await expandedReading(page, width, height));
    await page.close();
  }
  assert(
    receipt.expanded.every(
      (item) =>
        item.canvasHeight >= 80 &&
        item.textHeight >= 16 &&
        item.scrolledPdf &&
        item.confirmed &&
        item.restored,
    ),
    "Expanded source reading: " + JSON.stringify(receipt.expanded),
  );
  for (const width of [1440, 1280, 768, 390])
    for (const theme of ["light", "dark"]) {
      const context = await browser.newContext({
        viewport: { width, height: width === 390 ? 844 : 900 },
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      lastPage = page;
      await localRequests(page);
      await page.goto(origin);
      if (width === 1440 && theme === "light") {
        const syntheticUrl = origin + "/synthetic.pdf";
        const changed = pdf.replace("240 days", "241 days");
        assert(
          changed !== pdf &&
            Buffer.byteLength(changed) === Buffer.byteLength(pdf),
          "same-size PDF fixture",
        );
        let reads = 0;
        await page.route(syntheticUrl, (route) => {
          reads++;
          return route.fulfill({
            contentType: "application/pdf",
            body: reads % 2 ? changed : pdf,
          });
        });
        await page.getByRole("button", { name: "直接打开原件" }).click();
        const failure = page.locator(".original-view").getByRole("alert");
        await failure
          .getByText(/与固定版本摘要不一致/)
          .waitFor({ timeout: 5000 });
        assert(
          !(await page.locator(".original-view canvas").isVisible()),
          "Mismatch must not display a page",
        );
        await failure.getByRole("button", { name: "重试" }).click();
        await page.locator(".original-view canvas:visible").waitFor();
        assert(
          reads === 2,
          "One original request per preview attempt, including retry with the same URL",
        );
        let saved = 0;
        page.on("download", () => saved++);
        await page.getByRole("button", { name: "下载资料原件" }).click();
        const downloadError = page
          .locator(".evidence-error")
          .getByRole("alert");
        await downloadError.getByText(/本版本的原件摘要或大小不一致/).waitFor();
        assert(saved === 0, "Mismatched bytes must not be saved");
        const [download] = await Promise.all([
          page.waitForEvent("download"),
          downloadError.getByRole("button", { name: "重试" }).click(),
        ]);
        assert(
          hash(await fs.readFile(await download.path())) === hash(pdf) &&
            reads === 4,
          "Retry must save the exact original with a single read",
        );
        receipt.original_byte_verification = {
          rejected_same_size_change: true,
          recovered_with_same_url: true,
          download_matches_registered_sha256: true,
          object_reads: reads,
        };
        await page.getByRole("button", { name: "关闭原件" }).click();
        await page.unroute(syntheticUrl);
      }
      await page.getByLabel("外观主题").selectOption(theme);
      const body = page.getByRole("textbox", { name: "正文草稿" });
      await body.fill("保持正文与光标上下文。");
      const errorDetail = page.locator(".error-details");
      assert(
        !(await errorDetail.getAttribute("open")),
        "error diagnostics start collapsed",
      );
      assert(
        await page
          .getByText("来源已经变化，请重新核对。", { exact: true })
          .isVisible(),
        "actionable error remains visible",
      );
      await page.getByText("查看错误详情", { exact: true }).click();
      assert(
        await page
          .getByText("synthetic-request-original", { exact: true })
          .isVisible(),
        "request reference remains available",
      );
      assert(
        await page.getByText("显式重试次数：0").isVisible(),
        "details never retries",
      );
      await page.getByRole("button", { name: "重试", exact: true }).click();
      assert(
        await page.getByText("显式重试次数：1").isVisible(),
        "explicit retry works",
      );
      await layout(page, `${width}-${theme}-feedback`);
      await screenshot(page, `feedback-${theme}-${width}`);
      await page.getByRole("button", { name: "打开查证", exact: true }).click();
      const desktop = width >= 1280;
      const retrieval = page.getByRole(desktop ? "complementary" : "dialog", {
        name: "查找原页依据",
      });
      await retrieval.waitFor();
      assert(
        (await page.evaluate(
          () => document.body.style.overflow === "hidden",
        )) !== desktop,
        "only compact source locks page",
      );
      if (desktop) {
        const boundary = page.getByRole("separator", {
          name: "调整来源面板宽度",
          exact: true,
        });
        const before = Number(await boundary.getAttribute("aria-valuenow"));
        await boundary.focus();
        await page.keyboard.press("ArrowRight");
        assert(
          Number(await boundary.getAttribute("aria-valuenow")) === before - 24,
          "source keyboard resize",
        );
        const handle = await boundary.boundingBox();
        await page.mouse.move(
          handle.x + handle.width / 2,
          handle.y + handle.height / 2,
        );
        await page.mouse.down();
        await page.mouse.move(
          handle.x + handle.width / 2 - 24,
          handle.y + handle.height / 2,
          { steps: 4 },
        );
        await page.mouse.up();
        assert(
          Number(await boundary.getAttribute("aria-valuenow")) === before,
          "source pointer resize",
        );
        await body.fill("查证期间继续编辑正文。");
        const bodyRect = await body.boundingBox(),
          pane = await retrieval.boundingBox();
        assert(
          bodyRect.x + bodyRect.width <= pane.x,
          "desktop source must not cover body",
        );
      }
      await page
        .getByRole("textbox", { name: "想查证什么？" })
        .fill("工期原问题");
      await page
        .getByRole("button", { name: "查证当前项目资料", exact: true })
        .click();
      const opener = page.getByRole("button", {
        name: "核对来源并打开引用原页",
        exact: true,
      });
      await opener.click();
      const original = page.getByRole(desktop ? "complementary" : "dialog", {
        name: "合成工期要求.pdf",
        exact: true,
      });
      await original.waitFor();
      if (desktop) {
        const nestedBoundary = page.getByRole("separator", {
          name: "调整来源面板宽度",
          exact: true,
        });
        assert(
          (await nestedBoundary.count()) === 1,
          "only the nested resize boundary is interactive",
        );
        const before = Number(
          await nestedBoundary.getAttribute("aria-valuenow"),
        );
        await nestedBoundary.focus();
        await page.keyboard.press("ArrowRight");
        await page.waitForFunction((expected) => {
          const boundary = document.querySelector(
            '.source-surface--nested [role="separator"]',
          );
          return Number(boundary?.getAttribute("aria-valuenow")) === expected;
        }, before - 24);
      }
      const canvas = page.getByRole("img", {
        name: "合成工期要求.pdf，物理页3原页",
        exact: true,
      });
      await canvas.waitFor();
      await page.waitForFunction(() => {
        const paper = document.querySelector(".pdf-canvas-container canvas");
        const container = paper?.parentElement;
        if (!container || !paper.style.width) return false;
        const style = window.getComputedStyle(container);
        const available =
          container.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight);
        // The fixture is 612 points wide and the renderer caps its scale at 2.
        return Math.abs(paper.clientWidth - Math.min(available, 1224)) <= 1;
      });
      await page.evaluate(() => {
        window.__sourceCanvas = document.querySelector("canvas");
      });
      assert(
        (await page.locator(".retrieval-drawer").getAttribute("inert")) !==
          null,
        "nested original leaves parent inert and mounted",
      );
      await layout(page, `${width}-${theme}-original`);
      await screenshot(page, `original-${theme}-${width}`);
      await page.getByRole("button", { name: "解析文本", exact: true }).click();
      assert(
        await original
          .getByText("合成第3页：总工期240日历天，雨季条件另见附件。", {
            exact: true,
          })
          .isVisible(),
        "exact page text visible",
      );
      assert(!(await canvas.isVisible()), "one compact source task at a time");
      await page
        .getByRole("combobox", { name: "物理页", exact: true })
        .selectOption("2");
      await layout(page, `${width}-${theme}-text`);
      await screenshot(page, `text-${theme}-${width}`);
      await page.getByRole("button", { name: "原页", exact: true }).click();
      await page
        .getByRole("img", {
          name: "合成工期要求.pdf，物理页2原页",
          exact: true,
        })
        .waitFor();
      assert(
        await page.evaluate(
          () => window.__sourceCanvas === document.querySelector("canvas"),
        ),
        "source canvas preserved",
      );
      await page.keyboard.press("Escape");
      await retrieval.waitFor();
      assert(
        await opener.evaluate((el) => el === document.activeElement),
        "nested source restores source trigger",
      );
      assert(
        (await page
          .getByRole("textbox", { name: "想查证什么？" })
          .inputValue()) === "工期原问题",
        "query preserved",
      );
      await page.getByRole("button", { name: "关闭查证", exact: true }).click();
      assert(
        await page.evaluate(() => document.body.style.overflow !== "hidden"),
        "scroll lock released",
      );
      assert(
        (await body.inputValue()) ===
          (desktop ? "查证期间继续编辑正文。" : "保持正文与光标上下文。"),
        "body preserved",
      );
      await layout(page, `${width}-${theme}-closed`);
      receipt.cases.push({
        width,
        theme,
        source: desktop ? "nonmodal beside editable body" : "single modal task",
        real_pdf_pages: 3,
        exact_page_retained: 2,
        nested_focus_restored: true,
        source_resize: desktop
          ? "pointer and keyboard, shared with nested source"
          : "compact single pane",
        body_and_query_preserved: true,
        error_details_explicit: true,
      });
      await context.close();
    }
  assert(
    !receipt.page_errors.length && !receipt.external_requests.length,
    "no page errors or external calls",
  );
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      passed: receipt.cases.length + receipt.expanded.length,
      screenshots: receipt.screenshots.length,
      source_files: Object.keys(source).length,
      page_errors: receipt.page_errors.length,
      external_requests: receipt.external_requests.length,
    }),
  );
} catch (error) {
  receipt.failure = String(error);
  if (lastPage && !lastPage.isClosed()) {
    receipt.focus_at_failure = await lastPage.evaluate(() => ({
      tag: document.activeElement?.tagName,
      text: document.activeElement?.textContent?.slice(0, 200),
      className: document.activeElement?.className,
    }));
    await lastPage.screenshot({ path: path.join(out, "failure.png") });
  }
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  throw error;
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
