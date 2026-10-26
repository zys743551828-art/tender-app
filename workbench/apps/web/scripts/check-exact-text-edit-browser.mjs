/* global process, window, document, console, URL */
// Browser acceptance replays an actual PG/S3 HTTP fixture, with synthetic business data.
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
  process.argv[2] ?? "/tmp/tender-exact-text-edit-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {ExactAuthoringTextEdit} from "./src/ExactAuthoringTextEdit";
import {NavigationGuardContext} from "./src/navigationGuard";
import {readExactDraftStatus} from "./src/authoringExactProtocol";
import native from "./src/test-fixtures/authoring-exact-text-edit-http.json";
import "./src/styles.css";
const params = new URLSearchParams(location.search), calls = [], unexpected = [];
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
window.__editQA = {calls, unexpected, saved: 0, guard: null, request: native.request, requestEtag: native.request_etag};
setAuth({member: {id: native.member_id, display_name: "合成人工修订验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (value, etag) => new Response(JSON.stringify(value), {headers: {"Content-Type": "application/json", ...(etag ? {ETag: etag} : {})}});
window.fetch = async (input, options = {}) => {
 const url = new URL(input, location.origin), route = url.pathname.replace(/^\\/api\\/v1/, ""), method = options.method || "GET";
 const headers = Object.fromEntries(new Headers(options.headers).entries());
 const body = options.body ? JSON.parse(options.body) : null;
 calls.push({route, method, headers, body});
 if (method === "GET") {
  if (route === "/authoring/exact-text-edit-capabilities") return json(native.capabilities);
  if (route.startsWith("/sections/")) return json(native.parent_section);
  if (route.endsWith("/exact-qualification")) return json(native.parent_qualification);
 }
 if (method === "POST" && route.endsWith("/exact-text-edits")) {
  if (params.get("lost") === "1" && !sessionStorage.getItem("synthetic-text-edit-ack-dropped")) {
   sessionStorage.setItem("synthetic-text-edit-ack-dropped", "1");
   throw new Error("Synthetic response lost after save");
  }
  return json(native.ack, native.ack_etag);
 }
 unexpected.push({route, method}); throw new Error("Unexpected synthetic endpoint");
};
const register = guard => {window.__editQA.guard = guard; return () => {window.__editQA.guard = null;};};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth: 1120, margin: "0 auto", padding: 16}}>
 <h1>固定来源正文修订</h1><p className="small-note">真实接口回执的合成浏览器重放，不发送业务写入。</p>
 <div className="authoring-workspace"><NavigationGuardContext.Provider value={register}>
  <ExactAuthoringTextEdit memberId={native.member_id} bidId={native.bid_id} draftId={native.parent_status.draft_id}
   sectionId={native.parent_section.id} status={readExactDraftStatus(native.parent_status, native.bid_id, native.parent_status.draft_id)}
   etag={native.request_etag} disabled={false} onEditingChange={() => {}} onSaved={async () => {window.__editQA.saved++;}}/>
 </NavigationGuardContext.Provider></div></main>);
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
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>固定来源文字修订验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const sources = Object.keys(built.metafile.inputs).filter(
  (value) => value !== "<stdin>" && !value.includes("node_modules"),
);
sources.push("scripts/check-exact-text-edit-browser.mjs");
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
  protocol: "exact-text-edit-browser/1",
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
    const bytes = await fs.readFile(file);
    const types = {
      ".html": "text/html",
      ".js": "text/javascript",
      ".css": "text/css",
      ".woff2": "font/woff2",
    };
    response.writeHead(200, {
      "Content-Type": types[path.extname(file)] ?? "application/octet-stream",
    });
    response.end(bytes);
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
    { width: 1280, height: 1000 },
    { width: 390, height: 844 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("dialog", (dialog) => void dialog.accept());
      await page.goto(
        `http://127.0.0.1:${server.address().port}/?theme=${theme}&lost=1`,
      );
      const begin = page.getByRole("button", { name: "修改本章固定来源文字" });
      await page.waitForFunction(() => {
        const button = [...document.querySelectorAll("button")].find(
          (item) => item.textContent === "修改本章固定来源文字",
        );
        return button && !button.disabled;
      });
      assert(await page.evaluate(() => window.__editQA.guard()));
      assert.equal(
        await page.evaluate(
          () =>
            window.__editQA.calls.filter((call) => call.method === "POST")
              .length,
        ),
        0,
      );
      const fixture = await page.evaluate(() => ({
        body: window.__editQA.request,
        etag: window.__editQA.requestEtag,
      }));
      await begin.click();
      assert.equal(await page.evaluate(() => window.__editQA.guard()), false);
      const save = page.getByRole("button", { name: "确认保存人工修订" });
      assert(await save.isDisabled());
      await page
        .getByRole("textbox", { name: "修改后的文字", exact: true })
        .fill(fixture.body.replacement_text);
      await page
        .getByRole("textbox", { name: "修订说明", exact: true })
        .fill(fixture.body.reason);
      assert(await save.isDisabled());
      await page.getByRole("checkbox").check();
      await page.screenshot({
        path: path.join(out, `edit-${viewport.width}-${theme}.png`),
        fullPage: true,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 1,
        ),
        false,
      );
      await save.click();
      await page
        .getByRole("button", { name: "查询并重试原文字修订" })
        .waitFor();
      // The durable pending UI is rendered before send() finishes its async
      // original-request verification. Visibility alone does not prove a POST
      // has happened; wait for the lost-response attempt to settle as well.
      await page.waitForFunction(() => {
        const recovery = [...document.querySelectorAll("button")].find(
          (button) => button.textContent === "查询并重试原文字修订",
        );
        return (
          window.__editQA.calls.some((call) => call.method === "POST") &&
          recovery &&
          !recovery.disabled
        );
      });
      const first = await page.evaluate(() =>
        window.__editQA.calls.filter((call) => call.method === "POST"),
      );
      assert.equal(first.length, 1);
      assert.deepEqual(first[0].body, fixture.body);
      assert.equal(first[0].headers["if-match"], fixture.etag);
      assert(first[0].headers["idempotency-key"]);
      await page.reload();
      const retry = page.getByRole("button", { name: "查询并重试原文字修订" });
      await retry.waitFor();
      assert.equal(
        await page.evaluate(
          () =>
            window.__editQA.calls.filter((call) => call.method === "POST")
              .length,
        ),
        0,
      );
      assert.equal(await page.evaluate(() => window.__editQA.guard()), false);
      await page.screenshot({
        path: path.join(out, `recovery-${viewport.width}-${theme}.png`),
        fullPage: true,
      });
      await retry.click();
      await page.getByText(/人工文字修订已保存为草稿修订/).waitFor();
      const replay = await page.evaluate(() =>
        window.__editQA.calls.filter((call) => call.method === "POST"),
      );
      assert.deepEqual(replay, first);
      await page.waitForFunction(() => window.__editQA.saved === 1);
      assert(await page.evaluate(() => window.__editQA.guard()));
      assert.deepEqual(
        await page.evaluate(() => window.__editQA.unexpected),
        [],
      );
      assert.deepEqual(errors, []);
      receipt.checks.push({
        viewport,
        theme,
        passed: true,
        original_request_preserved: true,
        automatic_posts_after_reload: 0,
      });
      await page.close();
    }
  }
  assert.deepEqual(await identities(), receipt.source_sha256);
  receipt.passed = true;
} catch (error) {
  receipt.failure = { name: error.name, message: error.message };
  const pages = browser?.contexts().flatMap((context) => context.pages()) ?? [];
  if (pages.length) {
    const page = pages.at(-1);
    await page.screenshot({
      path: path.join(out, "failure.png"),
      fullPage: true,
    });
    await fs.writeFile(
      path.join(out, "failure-dom.txt"),
      await page.locator("body").innerText(),
    );
  }
  throw error;
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
