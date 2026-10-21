/* global process, URL, console, window, document, innerWidth */
// Actual React components with an explicit synthetic HTTP server; no business/provider calls.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-technical-scope-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import { createRoot } from "react-dom/client";
import { PackageTechnicalScope } from "./src/PackageTechnicalScope";
import { PackageTechnicalEligibility } from "./src/PackageTechnicalEligibility";
import eligibility from "./src/test-fixtures/technical-eligibility-catalog-http.json";
import scaled from "./src/test-fixtures/technical-scale-http.json";
import { PackageScopeGuardProvider } from "./src/PackageScopeGuardProvider";
import { technicalFixture, technicalAckFor } from "./src/packageTechnicalScopeFixtures.test-support";
import "./src/styles.css";
const f = technicalFixture(), calls = [], acks = new Map();
const params = new URLSearchParams(location.search), mode = params.get("eligibility");
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
window.__technicalQA = { fixture: f, calls, loseFirstAck: true, lost: false };
window.fetch = async (url, options = {}) => {
  const route = new URL(url, location.origin).pathname;
  const headers = new Headers(options.headers), method = options.method || "GET";
  const body = options.body ? JSON.parse(options.body) : null;
  calls.push({ route, method, body, key: headers.get("Idempotency-Key"), etag: headers.get("If-Match") });
  const response = (data, etag) => new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json", ...(etag ? { ETag: etag } : {}) } });
  if (mode) {
    if (route.endsWith("technical-scale-capabilities")) return response({ ...eligibility.capabilities, schema_configured: true, sourced_denominator_registration: true });
    if (route.endsWith("technical-scales")) return response({ items: [scaled.scale], limit: 200, formal_eligibility: "unavailable" });
    if (route.endsWith("submissions")) return response(eligibility.submissions);
    if (route.endsWith("outcomes")) return response(eligibility.outcomes);
    if (route.endsWith("sample-context")) return response(eligibility.sampleContext, eligibility.sampleEtag);
    if (route.endsWith("scoring-context")) return response(scaled.scoringContext, scaled.scoringEtag);
  }
  if (route.endsWith("technical-scope-context")) return response(f.context, f.context.etag);
  if (route.endsWith("technical-scope-previews")) {
    if (JSON.stringify(body) !== JSON.stringify(f.request)) throw new Error("Synthetic preview input differs");
    return response(f.preview, f.context.etag);
  }
  if (route.endsWith("technical-scopes") && method === "POST") {
    const key = headers.get("Idempotency-Key");
    if (!acks.has(key)) acks.set(key, await technicalAckFor({ ...f.pending, body, key, etag: headers.get("If-Match") }));
    if (window.__technicalQA.loseFirstAck && !window.__technicalQA.lost) { window.__technicalQA.lost = true; throw new Error("Synthetic lost acknowledgement after commit"); }
    const result = acks.get(key); return response(result.data, result.etag);
  }
  throw new Error("Unconfigured synthetic endpoint: " + route);
};
createRoot(document.getElementById("root")).render(<main style={{maxWidth:1000,margin:"0 auto",padding:16}}><h1>施组评分范围</h1><p>合成资料交互验收：使用实际组件；HTTP由测试夹具提供。</p>{mode ? <div className="technical-scope panel"><PackageTechnicalEligibility saved={mode === "historical" ? eligibility.scope : scaled.scope}/></div> : <PackageScopeGuardProvider><PackageTechnicalScope bidId={f.scope.bidId} memberId={f.scope.memberId} packageView={f.context.target} inventory={f.context.inventory} /></PackageScopeGuardProvider>}</main>);
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
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>技术范围合成交互验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
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
let browser;
const receipt = {
  kind: "synthetic-browser-interaction",
  real_model_calls: 0,
  real_database: false,
  viewports: [],
  eligibility: [],
};
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  for (const width of [1280, 768, 390]) {
    const context = await browser.newContext({
      viewport: { width, height: 1000 },
      locale: "zh-CN",
    });
    const page = await context.newPage(),
      errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page
      .getByRole("button", { name: "读取技术范围依据", exact: true })
      .click();
    const parts = page.getByRole("group", {
      name: "1. 选择要纳入的完整页段",
      exact: true,
    });
    await parts.waitFor();
    const fixture = await page.evaluate(() => window.__technicalQA.fixture);
    for (const checkbox of await parts.getByRole("checkbox").all())
      await checkbox.check();
    for (let index = 0; index < fixture.request.rule_scopes.length; index++) {
      const rule = fixture.request.rule_scopes[index],
        n = index + 1;
      await page
        .getByLabel(`条款 ${n} 的范围判断`, { exact: true })
        .selectOption(rule.selection);
      if (rule.selection === "include")
        for (const checkbox of await page
          .getByRole("group", { name: `条款 ${n} 关联的已选页段`, exact: true })
          .getByRole("checkbox")
          .all())
          await checkbox.check();
      await page
        .getByLabel(`条款 ${n} 的选择理由`, { exact: true })
        .fill(rule.reason);
    }
    await page
      .getByLabel("本次范围说明", { exact: true })
      .fill(fixture.request.reason);
    await page
      .getByRole("button", { name: "预览技术范围与缺口", exact: true })
      .click();
    const preview = page.getByRole("region", {
      name: "待保存的技术范围",
      exact: true,
    });
    await preview.waitFor();
    await preview.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `preview-${width}.png`) });
    if (
      await page
        .getByRole("button", { name: "确认保存技术范围", exact: true })
        .isEnabled()
    )
      throw new Error("Confirmation missing");
    await page
      .getByLabel("我已核对本次选择与缺口，确认保存为范围记录。", {
        exact: true,
      })
      .check();
    await page
      .getByRole("button", { name: "确认保存技术范围", exact: true })
      .click();
    await page
      .getByRole("button", { name: "恢复原技术范围请求", exact: true })
      .waitFor();
    const originalCommand = await page.evaluate(() =>
      window.__technicalQA.calls.at(-1),
    );
    await page.reload();
    await page
      .getByRole("button", { name: "恢复原技术范围请求", exact: true })
      .waitFor();
    await page.evaluate(() => {
      window.__technicalQA.loseFirstAck = false;
    });
    await page
      .getByRole("button", { name: "恢复原技术范围请求", exact: true })
      .click();
    await page
      .getByText("技术范围已保存，原件字节已在登记时核验。", { exact: true })
      .waitFor();
    const saved = page.getByRole("region", {
      name: "本次已保存范围",
      exact: true,
    });
    await saved.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `saved-${width}.png`) });
    const layout = await page.evaluate(() => ({
      viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      controlsOutside: [
        ...document.querySelectorAll("button,input,textarea,select"),
      ].filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width && (box.left < -1 || box.right > innerWidth + 1);
      }).length,
      commands: window.__technicalQA.calls.filter(
        (call) => call.method === "POST",
      ),
    }));
    if (
      layout.scrollWidth > width + 1 ||
      layout.controlsOutside ||
      errors.length
    )
      throw new Error(JSON.stringify({ width, layout, errors }));
    const originals = layout.commands.filter((call) =>
      call.route.endsWith("technical-scopes"),
    );
    if (
      originals.length !== 1 ||
      JSON.stringify(originals[0]) !== JSON.stringify(originalCommand)
    )
      throw new Error("Replay did not preserve the exact original request");
    receipt.viewports.push({
      width,
      horizontal_overflow: false,
      console_errors: errors,
      recovered_original_request: true,
      model_calls: 0,
    });
    await context.close();
  }
  const historical = JSON.parse(
    await fs.readFile(
      path.join(
        root,
        "src/test-fixtures/technical-eligibility-catalog-http.json",
      ),
      "utf8",
    ),
  );
  const scale = JSON.parse(
    await fs.readFile(
      path.join(root, "src/test-fixtures/technical-scale-http.json"),
      "utf8",
    ),
  );
  for (const width of [1280, 768, 390]) {
    for (const theme of ["light", "dark"]) {
      for (const mode of ["current", "historical"]) {
        const context = await browser.newContext({
          viewport: { width, height: 1000 },
          locale: "zh-CN",
        });
        const page = await context.newPage(),
          errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(
          `http://127.0.0.1:${server.address().port}/?eligibility=${mode}&theme=${theme}`,
        );
        if (mode === "historical") {
          await page
            .getByLabel("技术范围检查用途", { exact: true })
            .selectOption("historical_backtest");
          await page
            .getByRole("button", { name: "读取实交记录", exact: true })
            .click();
          await page
            .getByLabel("检查所用实交记录", { exact: true })
            .selectOption(historical.sampleRequest.submission_id);
          await page
            .getByRole("button", { name: "读取该实交的成绩记录", exact: true })
            .click();
          await page
            .getByLabel("检查所用成绩记录", { exact: true })
            .selectOption(historical.sampleRequest.outcome_id);
          await page
            .getByRole("button", { name: "检查历史样本条件", exact: true })
            .click();
          await page.getByText("0 分（关联已核验）", { exact: true }).waitFor();
        } else {
          await page
            .getByRole("button", { name: "读取可选量尺", exact: true })
            .click();
          await page
            .getByLabel("检查所用技术量尺", { exact: true })
            .selectOption(scale.scale.id);
          await page
            .getByRole("button", { name: "检查当前评分条件", exact: true })
            .click();
          await page
            .getByText("60.00 分 · 未加权原始分", { exact: true })
            .waitFor();
        }
        const result = page.getByLabel("技术条件检查结果", { exact: true });
        await result.scrollIntoViewIfNeeded();
        await page.screenshot({
          path: path.join(out, `eligibility-${mode}-${theme}-${width}.png`),
        });
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth + 1,
        );
        if (overflow || errors.length)
          throw new Error(
            JSON.stringify({ width, theme, mode, overflow, errors }),
          );
        receipt.eligibility.push({
          width,
          theme,
          mode,
          horizontal_overflow: false,
          page_errors: errors,
          real_pg_fixture_replayed: true,
        });
        await context.close();
      }
    }
  }
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(JSON.stringify(receipt, null, 2));
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
