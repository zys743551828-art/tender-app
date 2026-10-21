/* global process, console, window, document, innerWidth, URL */
// Actual React components; HTTP replays the sanitized PG/ASGI fixture. No real business/model calls.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-task-triggers-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import { createRoot } from "react-dom/client";
import { setAuth } from "./src/api";
import { TaskTemplateEditor } from "./src/TaskTemplateEditor";
import { TaskPanel } from "./src/TaskPanel";
import { TaskPackageTriggerDetail } from "./src/TaskPackageTriggerPanel";
import { ExactPackageTaskDraftStart } from "./src/ExactPackageTaskDraftStart";
import { ExactPackageTaskScope } from "./src/ExactPackageTaskScope";
import { PackageScopeGuardProvider } from "./src/PackageScopeGuardProvider";
import { taskTriggerFixtures } from "./src/taskTriggerFixtures.test-support";
import { historicalSame } from "./src/historicalImportProtocol";
import { jsonDigest } from "./src/editorSchema";
import "./src/styles.css";
const f = taskTriggerFixtures();
const params = new URLSearchParams(location.search), mode = params.get("mode") || "event";
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
const record = f[mode === "schedule" || mode === "missed" ? "schedule-template" : "event-template"];
const template = record.data, memberId = f["event-succeeded-run"].data.frozen_manifest.actor_id;
const cancel = f["cancel-pending"], bidId = mode === "cancel" ? cancel.data.bid_id : template.bid_id;
const calls = [], unexpected = [];
window.__taskQA = { calls, unexpected, saved: false, expected: template.configuration,
  savedMatches: () => historicalSame(calls.find((call) => call.method === "POST")?.body, template.configuration) };
setAuth({ member: { id: memberId, display_name: "合成触发验收", active: true }, csrf_token: "synthetic", expires_at: "2099-01-01T00:00:00Z" });
const json = (data, headers = {}) => new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json", ...headers } });
const reply = (item) => json(item.data, item.headers);
window.fetch = async (url, options = {}) => {
  const route = new URL(url, location.origin).pathname, method = options.method || "GET";
  const headers = new Headers(options.headers), body = options.body ? JSON.parse(options.body) : null;
  calls.push({ route, method, body, key: headers.get("Idempotency-Key"), etag: headers.get("If-Match") });
  if (method === "POST") {
    if ((mode === "event" || mode === "schedule") && route === "/api/v1/bids/" + bidId + "/task-definitions") return reply(record);
    if (mode === "draft" && route === "/api/v1/bids/" + bidId + "/task-definition-drafts") {
      const interpretation = { interpreter: "bounded-zh-task-draft/1", raw_request: body.request, name: "整包否决核对",
        task_kind: "denial_check", instructions: body.request, section_id: null, source_selection: body.source_selection,
        trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" }, target_description: "所选精确投标包、冻结输入、执行准备与依赖计划",
        output_description: "否决及强制项核对结果与证据", unresolved: [], ready_for_template_form: true,
        template_saved: false, run_created: false, formal_decisions_allowed: false };
      const id = "a5000000-0000-4000-8000-000000000001";
      return json({ id, bid_id: bidId, created_by: memberId, revision: 1, created_at: "2026-10-21T00:00:00Z", updated_at: "2026-10-21T00:00:00Z",
        interpretation, configuration_digest: await jsonDigest(interpretation), explicitly_edited: false, saved_template_id: null }, { ETag: '"task-draft:' + id + ':1"' });
    }
    if (mode === "cancel" && route.endsWith("/task-package-trigger-intents/" + cancel.data.id + "/cancel")) {
      if (!sessionStorage.getItem("synthetic-server-cancelled")) {
        sessionStorage.setItem("synthetic-server-cancelled", "true");
        throw new Error("Synthetic cancel ACK lost after commit");
      }
      return reply(f.cancelled);
    }
  }
  if (method === "GET") {
    if (route.endsWith("/task-kinds")) return reply(f["task-kinds"]);
    if (mode === "cancel" && route.endsWith("/task-package-trigger-intents/" + cancel.data.id))
      return json((sessionStorage.getItem("synthetic-server-cancelled") ? f.cancelled : cancel).data, cancel.headers);
    if (route === "/api/v1/bids/" + bidId) return json({ id: bidId }, { ETag: record.request.headers["if-match"] });
    if (route.endsWith("/task-definitions/" + template.id)) return reply(record);
    if (route.endsWith("/task-definitions")) return json({ items: [template], has_more: false, next_cursor: null });
    if (route.endsWith("/task-definition-drafts")) return json({ items: [], has_more: false, next_cursor: null });
    if (route.endsWith("/task-runs")) return json({ items: [], next_after: null });
    if (route.endsWith("/task-notifications")) return mode === "history" ? reply(f["event-notifications"]) : json({ items: [], next_after: null });
    if (route.endsWith("/task-schedule-recoveries")) return mode === "missed" ? reply(f["schedule-missed"]) : json({ items: [], next_after: null, run_current_once_supported: true });
    if (route.endsWith("/task-package-trigger-intents")) return mode === "history" ? reply(f["event-intents"]) : json({ items: [], next_after: null });
    if (mode === "history" && route.endsWith("/task-package-trigger-intents/" + f["event-accepted"].data.id)) return reply(f["event-accepted"]);
  }
  unexpected.push({ route, method });
  throw new Error("Unconfigured fixture endpoint: " + method + " " + route);
};
const selection = template.configuration.source_selection.input;
const initial = { ...template.configuration, source_selection: { mode: "exact_package_review", input: selection }, trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" } };
createRoot(document.getElementById("root")).render(
 <main style={{ maxWidth: 1040, margin: "0 auto", padding: 16 }}>
  <h1>精确整包任务</h1><p>合成原件验收：真实组件与 PG/ASGI 响应回放。</p>
  <PackageScopeGuardProvider>{mode === "event" || mode === "schedule" ?
    <TaskTemplateEditor bidId={bidId} memberId={memberId} template={null} etag={record.request.headers["if-match"]}
      initialConfiguration={initial} formIdentity={"package:" + selection.execution_input_id + ":" + selection.dependency_plan_id}
      onSaved={() => { window.__taskQA.saved = true; }} onClose={() => {}} /> :
    mode === "cancel" ? <TaskPackageTriggerDetail bidId={bidId} memberId={memberId} id={cancel.data.id} onRun={() => {}} onChanged={() => {}} /> :
    mode === "draft" ? <><ExactPackageTaskScope bidId={bidId} selection={selection} />
      <ExactPackageTaskDraftStart bidId={bidId} memberId={memberId} identity={"package:" + selection.execution_input_id + ":" + selection.dependency_plan_id}
        configuration={initial} etag={record.request.headers["if-match"]} /></> :
    <TaskPanel bidId={bidId} memberId={memberId} />}
  </PackageScopeGuardProvider>
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
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>任务触发交互验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
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
      throw new Error("outside fixture");
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
const receipt = {
  kind: "actual-react-pg-http-fixture-browser",
  real_model_calls: 0,
  real_database_in_browser: false,
  private_draft_http:
    "constructed synthetic response; other task responses replay isolated PG/ASGI fixtures",
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
  for (const width of [1280, 768, 390]) {
    for (const mode of [
      "event",
      "schedule",
      "cancel",
      "history",
      "missed",
      "draft",
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
      if (mode === "event" || mode === "schedule") {
        const trigger = page.getByLabel("触发方式", { exact: true });
        await trigger.waitFor();
        if ((await trigger.inputValue()) !== "manual")
          throw new Error("Default trigger changed");
        await page.waitForFunction(
          () => !document.querySelector('option[value="schedule"]').disabled,
        );
        await trigger.selectOption(
          mode === "event" ? "material_updated" : "schedule",
        );
        await page.getByText("核对完整来源身份与摘要", { exact: true }).click();
        await page.screenshot({
          path: path.join(out, `${mode}-${width}.png`),
          fullPage: true,
        });
        await page
          .getByRole("button", { name: "保存任务模板，不运行", exact: true })
          .click();
        await page.waitForFunction(() => window.__taskQA.saved);
        const exact = await page.evaluate(() => window.__taskQA.savedMatches());
        if (!exact)
          throw new Error(
            "Saved configuration differs from selected exact fixture",
          );
      } else if (mode === "cancel") {
        await page
          .getByLabel("取消本次触发的原因", { exact: true })
          .fill("明确取消这次原输入触发");
        await page
          .getByRole("button", { name: "取消这次尚未运行的触发", exact: true })
          .click();
        await page
          .getByRole("button", { name: "恢复原取消请求结果", exact: true })
          .waitFor();
        const original = await page.evaluate(() =>
          window.__taskQA.calls.find((call) => call.method === "POST"),
        );
        await page.reload();
        await page
          .getByRole("button", { name: "恢复原取消请求结果", exact: true })
          .click();
        await page.getByText(/原取消请求回执：已取消本次触发/).waitFor();
        const retry = await page.evaluate(() =>
          window.__taskQA.calls.find((call) => call.method === "POST"),
        );
        if (JSON.stringify(original) !== JSON.stringify(retry))
          throw new Error("Cancellation changed original request identity");
        await page.getByText("核对完整来源身份与摘要", { exact: true }).click();
        await page.screenshot({
          path: path.join(out, `${mode}-${width}.png`),
          fullPage: true,
        });
      } else if (mode === "history") {
        await page
          .getByRole("button", { name: "整包事件与定时触发记录", exact: true })
          .click();
        await page
          .getByRole("button", { name: /资料事件 · 已关联原生运行/ })
          .first()
          .click();
        await page.getByText("这次固定输入的触发", { exact: true }).waitFor();
        await page
          .getByRole("button", { name: "运行通知", exact: true })
          .click();
        await page.getByText(/以下是已持久保存的站内通知/).waitFor();
        if (await page.getByRole("button", { name: /手动运行/ }).count())
          throw new Error("Automatic template exposed manual runs");
        await page.screenshot({
          path: path.join(out, `${mode}-${width}.png`),
          fullPage: true,
        });
      } else if (mode === "draft") {
        await page
          .getByRole("button", { name: "先用文字拟定私有草案", exact: true })
          .click();
        await page
          .getByLabel("这份整包想反复核对什么", { exact: true })
          .fill("核查这份整包的否决项");
        await page
          .getByRole("button", { name: "生成这份输入的私有草案", exact: true })
          .click();
        await page
          .getByRole("link", { name: "打开草案并明确触发方式", exact: true })
          .waitFor();
        const writes = await page.evaluate(() =>
          window.__taskQA.calls.filter((call) => call.method === "POST"),
        );
        if (
          writes.length !== 1 ||
          !writes[0].route.endsWith("/task-definition-drafts") ||
          writes[0].body.source_selection.mode !== "exact_package_review"
        )
          throw new Error(
            "Private draft promoted automatic execution or replaced the explicit source",
          );
        await page.screenshot({
          path: path.join(out, `${mode}-${width}.png`),
          fullPage: true,
        });
      } else {
        await page
          .getByRole("button", { name: "漏时与计划恢复记录", exact: true })
          .click();
        await page
          .getByText(/请核对原模板的确切输入，明确保存为手动模式后再运行一次/)
          .waitFor();
        if (await page.getByRole("button", { name: /手动运行/ }).count())
          throw new Error("Missed period exposed automatic catchup");
        await page.screenshot({
          path: path.join(out, `${mode}-${width}.png`),
          fullPage: true,
        });
      }
      const result = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        width: innerWidth,
        controlsOutside: [
          ...document.querySelectorAll("button,input,textarea,select"),
        ].filter((element) => {
          const box = element.getBoundingClientRect();
          return box.width && (box.left < -1 || box.right > innerWidth + 1);
        }).length,
        unexpected: window.__taskQA.unexpected,
        writes: window.__taskQA.calls
          .filter((call) => call.method !== "GET")
          .map((call) => call.route),
      }));
      if (
        errors.length ||
        result.unexpected.length ||
        result.scrollWidth > width + 1 ||
        result.controlsOutside ||
        result.writes.some((route) => route.endsWith("/runs"))
      )
        throw new Error(JSON.stringify({ mode, width, errors, ...result }));
      receipt.checks.push({
        mode,
        width,
        theme: width === 390 ? "dark" : "light",
        errors,
        ...result,
      });
      await context.close();
    }
  }
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      passed: receipt.checks.length,
      receipt: path.join(out, "receipt.json"),
    }),
  );
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
