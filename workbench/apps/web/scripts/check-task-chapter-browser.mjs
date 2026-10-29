/* global process, console, window, document, innerWidth, URL */
// Actual React and original PG/ASGI response bundles. Two named identity faults are deliberate.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/tmp/tender-task-chapter-browser");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import { createRoot } from "react-dom/client";
import { setAuth } from "./src/api";
import { TaskRunCard } from "./src/TaskRunCard";
import { taskChapterFixtures } from "./src/taskChapterFixtures.test-support";
import "./src/styles.css";
const f = taskChapterFixtures(), params = new URLSearchParams(location.search);
const mode = params.get("mode") || "published", fault = mode.startsWith("bad-");
const record = f[fault ? "published" : mode], run = record.run;
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
if (mode === "bad-binding") run.result.job_id = "10000000-0000-4000-8000-000000000000";
if (mode === "bad-proposal") record.proposal.job_id = "20000000-0000-4000-8000-000000000000";
const calls = [], unexpected = [];
window.__chapterQA = { calls, unexpected, actionId: record.proposal?.action_id, run };
setAuth({ member: { id: run.frozen_manifest.actor_id, display_name: "合成章节原生验收", active: true }, csrf_token: "synthetic", expires_at: "2099-01-01T00:00:00Z" });
const json = (value, etag) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json", ...(etag ? { ETag: etag } : {}) } });
window.fetch = async (input, options = {}) => {
  const route = new URL(input, location.origin).pathname, method = options.method || "GET";
  calls.push({ route, method });
  if (method === "GET") {
    if (route === "/api/v1/bids/" + run.bid_id + "/task-runs/" + run.id) return json(run);
    if (route === "/api/v1/bids/" + run.bid_id + "/task-definitions/" + run.frozen_manifest.definition_id + "/versions/" + run.definition_version_id) return json(record.template_version);
    if (route === "/api/v1/operations/" + run.root_operation_id) return json(record.operation, record.operation_etag);
    if (record.proposal && route === "/api/v1/assistant/actions/" + record.proposal.action_id) return json(record.proposal);
  }
  unexpected.push({ route, method });
  throw new Error("Unconfigured chapter fixture endpoint");
};
createRoot(document.getElementById("root")).render(<main style={{ maxWidth: 1040, margin: "0 auto", padding: 16 }}>
  <h1>章节任务结果</h1><p>合成原件验收：真实组件与 PG/ASGI 响应回放。</p>
  <TaskRunCard bidId={run.bid_id} id={run.id} memberId={run.frozen_manifest.actor_id} />
</main>);
`;
await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  format: "esm",
  jsx: "automatic",
  outdir: out,
  entryNames: "app",
  sourcemap: false,
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
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>章节任务发布验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
};
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const directory = name.startsWith("/fonts/")
      ? path.join(root, "public")
      : out;
    const target = path.resolve(
      directory,
      `.${name === "/" ? "/index.html" : name}`,
    );
    if (!target.startsWith(directory + path.sep))
      throw new Error("Outside fixture");
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
const sha = (data) => crypto.createHash("sha256").update(data).digest("hex");
const sources = [
  "src/TaskRunCard.tsx",
  "src/taskState.ts",
  "src/TaskAuthoringResultPanel.tsx",
  "src/taskAuthoringProtocol.ts",
  "src/AssistantPatchComparison.tsx",
  "src/AssistantReviewDetails.css",
  "src/AuthoringRichSnapshot.tsx",
  "src/taskChapterFixtures.test-support.ts",
  "src/test-fixtures/task-chapter-http.json",
  "src/contracts.ts",
  "scripts/check-task-chapter-browser.mjs",
];
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sources.map(async (name) => [
        name,
        sha(await fs.readFile(path.join(root, name))),
      ]),
    ),
  );
const receipt = {
  schema: "task-chapter-browser/1",
  passed: false,
  real_model_calls: 0,
  real_database_in_browser: false,
  transport:
    "Unmodified isolated PG/ASGI response bundles; bad-binding and bad-proposal are explicit identity fault injections",
  source_sha256: await identities(),
  checks: [],
};
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  receipt.chromium = browser.version();
  for (const width of [1280, 768, 390])
    for (const mode of [
      "awaiting-publication",
      "published",
      "stale-section",
      "unknown-fee",
      "cancelled",
      "bad-binding",
      "bad-proposal",
    ]) {
      const context = await browser.newContext({
        viewport: { width, height: 1000 },
        locale: "zh-CN",
      });
      const page = await context.newPage(),
        errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(
        `http://127.0.0.1:${server.address().port}/?mode=${mode}${width === 390 ? "&theme=dark" : ""}`,
      );
      if (mode === "bad-binding")
        await page.getByText("章节结果关联待核对", { exact: true }).waitFor();
      else await page.getByText(/尚未绑定固定整包/).waitFor();
      if (mode === "published" || mode === "bad-proposal") {
        await page
          .getByRole("button", {
            name: "核对本任务绑定的章节提案",
            exact: true,
          })
          .click();
        if (mode === "published") {
          const link = page.getByRole("link", {
            name: "打开这份提案的持久操作卡",
            exact: true,
          });
          await link.waitFor();
          const id = await page.evaluate(() => window.__chapterQA.actionId);
          if ((await link.getAttribute("href")) !== "/assistant?action=" + id)
            throw new Error("Wrong proposal link");
          await page.getByText("查看具体文字增删", { exact: true }).click();
          const after = page.getByLabel("拟修改后全文", { exact: true });
          await after.waitFor();
          if (
            !(await after.textContent()).includes(
              "合成原页支持的修改建议，尚未采纳",
            )
          )
            throw new Error("Actual proposal text absent");
          if (width === 390) {
            await page
              .getByRole("button", { name: "修改前", exact: true })
              .click();
            if (
              !(
                await page
                  .getByLabel("修改前全文", { exact: true })
                  .textContent()
              ).includes("原正文一")
            )
              throw new Error("Original text absent");
            await page
              .getByRole("button", { name: "拟修改后", exact: true })
              .click();
          }
        } else {
          await page
            .getByText(/原生提案与本任务的项目、章节或原始 job 不一致/)
            .waitFor();
          if (
            await page
              .getByRole("link", { name: "打开这份提案的持久操作卡" })
              .count()
          )
            throw new Error("Wrong proposal remained actionable");
        }
      } else if (
        await page
          .getByRole("button", { name: "核对本任务绑定的章节提案" })
          .count()
      )
        throw new Error("Unpublished or unbound task exposes proposal");
      if (mode === "awaiting-publication")
        await page.getByText("等待提案发布", { exact: true }).waitFor();
      if (mode === "unknown-fee")
        await page.getByText("需核对调用账本", { exact: true }).waitFor();
      if (mode === "stale-section")
        await page.getByText("原输入已过期", { exact: true }).waitFor();
      if (mode === "cancelled")
        await page.getByText("已取消", { exact: true }).waitFor();
      const observed = await page.evaluate(() => ({
        writes: window.__chapterQA.calls.filter(
          (call) => call.method !== "GET",
        ),
        unexpected: window.__chapterQA.unexpected,
        width: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      if (
        observed.writes.length ||
        observed.unexpected.length ||
        errors.length ||
        observed.width > observed.viewport + 1
      )
        throw new Error(JSON.stringify({ mode, width, observed, errors }));
      const name = `${mode}-${width}.png`;
      await page.screenshot({ path: path.join(out, name), fullPage: true });
      receipt.checks.push({
        mode,
        width,
        theme: width === 390 ? "dark" : "light",
        passed: true,
        screenshot: name,
        screenshot_sha256: sha(await fs.readFile(path.join(out, name))),
        requests_are_read_only: true,
        no_page_overflow: true,
        javascript_errors: errors,
      });
      await context.close();
    }
  receipt.source_unchanged_during_execution =
    JSON.stringify(receipt.source_sha256) ===
    JSON.stringify(await identities());
  receipt.passed =
    receipt.source_unchanged_during_execution && receipt.checks.length === 21;
} catch (error) {
  receipt.error = String(error);
  throw error;
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
}
console.log(
  JSON.stringify({
    passed: receipt.passed,
    checks: receipt.checks.length,
    receipt: path.join(out, "receipt.json"),
  }),
);
if (!receipt.passed) process.exitCode = 1;
