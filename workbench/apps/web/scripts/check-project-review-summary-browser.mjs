/* global process, window, document, Event, console, URL */
// Real components and Chromium; all business records below are synthetic.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-project-review-summary",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {ProjectSelectedReviewSummary} from "./src/ProjectSelectedReviewSummary";
import {workContextFixture} from "./qa-previews/frozen-inputs/workContext";
import {contextChoicePage} from "./qa-previews/frozen-inputs/workContextAuthoring";
import {reviewSummaryActions} from "./src/projectReviewSummaryFixtures.test-support";
import "./src/styles.css";
const fixture = await workContextFixture(), scope = fixture.props.scope;
const choices = await contextChoicePage([fixture.context.selection], "package_review_run", scope.bidId);
const calls = [], navigation = [], unexpected = [];
window.__reviewQA = {calls, navigation, unexpected, failCurrent: false,
 expected: {stage: "package_review_run", selected: {kind: "package_review_run", id: fixture.completed.id, selectionDigest: fixture.context.selection_digest}}};
if (new URLSearchParams(location.search).get("theme") === "dark") document.documentElement.dataset.theme = "dark";
setAuth({member: {id: scope.memberId, display_name: "合成概览验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (value, status = 200) => new Response(JSON.stringify(value), {status, headers: {"Content-Type": "application/json"}});
window.fetch = async (input, options = {}) => {
 const url = new URL(input, location.origin), method = options.method || "GET";
 calls.push({route: url.pathname + url.search, method});
 if (method === "GET") {
  if (url.pathname.endsWith("/work-contexts/choices")) return json(choices);
  if (url.pathname.includes("/work-contexts/package_review_run/")) return window.__reviewQA.failCurrent
   ? json({error: {code: "SYNTHETIC_UNAVAILABLE", message: "合成连接失败"}}, 503) : json(fixture.context);
  if (url.pathname.includes("/package-next-actions/")) return json(reviewSummaryActions(fixture));
 }
 unexpected.push({route: url.pathname, method}); throw new Error("Unexpected synthetic endpoint");
};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth: 1120, margin: "0 auto", padding: 16}}>
 <h1>项目概览</h1><p className="small-note">合成浏览器验收，非真实业务核查。</p>
 <ProjectSelectedReviewSummary bidId={scope.bidId} memberId={scope.memberId}
  onOpenRecord={value => navigation.push(value)} onOpenPackage={value => navigation.push({package: value})}
  onOpenRules={() => navigation.push({rules: true})}/></main>);
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
});
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>所选核查概览验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const sources = Object.keys(built.metafile.inputs).filter(
  (value) => value !== "<stdin>" && !value.includes("node_modules"),
);
sources.push("scripts/check-project-review-summary-browser.mjs");
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sources.sort().map(async (name) => [
        name,
        crypto
          .createHash("sha256")
          .update(await fs.readFile(path.resolve(root, name)))
          .digest("hex"),
      ]),
    ),
  );
const receipt = {
  protocol: "project-selected-review-browser/1",
  passed: false,
  real_model_calls: 0,
  real_database_in_browser: false,
  source_sha256: await identities(),
  checks: [],
};
const server = http.createServer(async (request, response) => {
  try {
    const name = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname,
    );
    const dir = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const file = path.resolve(dir, `.${name === "/" ? "/index.html" : name}`);
    if (!file.startsWith(dir + path.sep)) throw new Error("outside fixture");
    const types = {
      ".html": "text/html",
      ".js": "text/javascript",
      ".css": "text/css",
      ".woff2": "font/woff2",
    };
    response.writeHead(200, {
      "Content-Type": types[path.extname(file)] ?? "application/octet-stream",
    });
    response.end(await fs.readFile(file));
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true });
  for (const viewport of [
    { width: 1280, height: 900 },
    { width: 390, height: 844 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(
        `http://127.0.0.1:${server.address().port}/?theme=${theme}`,
      );
      await page.getByRole("button", { name: "选择一轮核查" }).waitFor();
      assert.equal(
        await page.evaluate(() => window.__reviewQA.calls.length),
        0,
      );
      await page.getByRole("button", { name: "选择一轮核查" }).click();
      await page.getByRole("button", { name: "选择此记录" }).click();
      const action = page.getByRole("button", {
        name: "核对所选范围的关键问题（1项）",
      });
      await action.waitFor();
      await page.screenshot({
        path: path.join(out, `selected-${viewport.width}-${theme}.png`),
        fullPage: true,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 1,
        ),
        false,
        "The selected summary must not overflow horizontally",
      );
      await action.click();
      const navigation = await page.evaluate(() => window.__reviewQA);
      assert.deepEqual(navigation.navigation, [navigation.expected]);
      await page.evaluate(() => {
        window.__reviewQA.failCurrent = true;
        window.dispatchEvent(new Event("server-snapshot-change"));
      });
      await page.getByRole("alert").waitFor();
      assert.equal(await action.count(), 0);
      assert.equal(
        await page
          .getByRole("button", { name: "查看所选核查与原报告" })
          .count(),
        0,
      );
      await page.getByRole("button", { name: "取消选择" }).click();
      await page.getByRole("button", { name: "选择一轮核查" }).waitFor();
      const final = await page.evaluate(() => window.__reviewQA);
      assert(final.calls.every((call) => call.method === "GET"));
      assert.deepEqual(final.unexpected, []);
      assert.deepEqual(errors, []);
      receipt.checks.push({
        viewport,
        theme,
        passed: true,
        calls: final.calls,
      });
      await page.close();
    }
  }
  assert.deepEqual(await identities(), receipt.source_sha256);
  receipt.passed = true;
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
  await fs.writeFile(
    path.join(out, "result.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
}
console.log(
  JSON.stringify({
    passed: receipt.passed,
    checks: receipt.checks.length,
    output: out,
  }),
);
