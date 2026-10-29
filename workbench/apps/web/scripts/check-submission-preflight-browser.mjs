/* global process, window, document, Event, console, URL */
// Real React and Chromium. All inputs are synthetic, including optional PG receipts.
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
  process.argv[2] ?? "/tmp/tender-submission-preflight-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const nativeDir = process.env.SUBMISSION_PREFLIGHT_NATIVE_FIXTURE;
const native = nativeDir
  ? {
      preview: JSON.parse(
        await fs.readFile(path.join(nativeDir, "preview.json"), "utf8"),
      ),
      result: JSON.parse(
        await fs.readFile(path.join(nativeDir, "preflight.json"), "utf8"),
      ),
    }
  : null;
await fs.mkdir(out, { recursive: true });
const entry = `
import React, {useState} from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {PackageSubmissionPreflight} from "./src/PackageSubmissionPreflight";
import {submissionPreflightFixture} from "./src/packageSubmissionPreflightFixtures.test-support";
import "./src/styles.css";
import "./src/PackageSubmission.css";
const nativeInput = ${JSON.stringify(native)};
const fixture = nativeInput ?? await submissionPreflightFixture();
const scope = {bidId: fixture.result.manifest.subject.bid_id, memberId: fixture.result.manifest.actor_id};
window.__preflightQA = {calls: [], unexpected: [], fail: false, delay: false, release: null};
if (new URLSearchParams(location.search).get("theme") === "dark") document.documentElement.dataset.theme = "dark";
setAuth({member: {id: scope.memberId, display_name: "合成提交验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (value, status = 200) => new Response(JSON.stringify(value), {status, headers: {"Content-Type": "application/json"}});
window.fetch = async (input, options = {}) => {
 const url = new URL(input, location.origin), method = options.method || "GET";
 const body = options.body ? JSON.parse(options.body) : null, headers = new Headers(options.headers);
 const expected = "/api/v1/bids/" + scope.bidId + "/packages/" + fixture.preview.selection_request.package_id + "/revisions/" + fixture.preview.selection_request.revision_id + "/submission-preflight";
 const call = {path: url.pathname, method, expected_body: JSON.stringify(body) === JSON.stringify({selection: fixture.preview.selection_request, input_digest: fixture.preview.input_digest}), exact_etag: headers.get("If-Match") === fixture.preview.bid_etag};
 window.__preflightQA.calls.push(call);
 if (method !== "POST" || url.pathname !== expected || !call.expected_body || !call.exact_etag) {
   window.__preflightQA.unexpected.push(call); throw new Error("Unexpected synthetic request");
 }
 if (window.__preflightQA.delay) return await new Promise(resolve => {window.__preflightQA.release = () => resolve(json(fixture.result));});
 if (window.__preflightQA.fail) return json({code: "PACKAGE_SUBMISSION_PREFLIGHT_CONTEXT_CHANGED", message: "合成验收：原件读取期间来源已撤回"}, 409);
 return json(fixture.result);
};
function Harness() {
 const [generation, setGeneration] = useState(0);
 return <main id="main-content" style={{maxWidth: 1000, margin: "0 auto", padding: 16}}>
  <h1>整包提交前复核</h1><p className="small-note">合成浏览器验收，真实业务质量另行验收。</p>
  <button className="button secondary" onClick={() => setGeneration(n => n + 1)}>重新读取所选检查</button>
  <PackageSubmissionPreflight key={generation} preview={fixture.preview} scope={scope}/>
 </main>;
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
});
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>提交前原件复核验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const sources = Object.keys(built.metafile.inputs).filter(
  (value) => value !== "<stdin>" && !value.includes("node_modules"),
);
sources.push("scripts/check-submission-preflight-browser.mjs");
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
  protocol: "package-submission-preflight-browser/1",
  passed: false,
  fixture: native
    ? "native-nonowner-pg-synthetic-receipt"
    : "synthetic-client-mechanism",
  native_receipt_digest: native?.result.digest ?? null,
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
      const button = page.getByRole("button", { name: "核验所选整包原件" });
      await button.waitFor();
      assert.equal(
        await page.evaluate(() => window.__preflightQA.calls.length),
        0,
      );
      await button.focus();
      await page.keyboard.press("Enter");
      await page.getByText("本次原件核验已完成", { exact: true }).waitFor();
      await page
        .getByText("运行依据：已与原核查逐项匹配。", { exact: true })
        .waitFor();
      assert.equal(
        await page
          .getByText("标准登记仍未获准。清单语义完整性与核查质量仍需证明。", {
            exact: true,
          })
          .isVisible(),
        true,
        "Original-byte verification must not be presented as submission approval",
      );
      await page.screenshot({
        path: path.join(out, `verified-${viewport.width}-${theme}.png`),
        fullPage: true,
      });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 1,
        ),
        false,
        "No horizontal overflow at the tested width",
      );
      await page.getByRole("button", { name: "重新读取所选检查" }).click();
      assert.equal(
        await page.getByText("本次原件核验已完成", { exact: true }).count(),
        0,
      );
      assert.equal(
        await page.evaluate(() => window.__preflightQA.calls.length),
        1,
      );
      await page.evaluate(() => {
        window.__preflightQA.fail = true;
      });
      await button.click();
      await page
        .getByText("合成验收：原件读取期间来源已撤回", { exact: true })
        .waitFor();
      assert.equal(
        await page.getByText("本次原件核验已完成", { exact: true }).count(),
        0,
      );
      await page.evaluate(() => {
        window.__preflightQA.fail = false;
        window.__preflightQA.delay = true;
      });
      await button.click();
      await page
        .getByRole("button", { name: "正在核验原件与运行依据…" })
        .waitFor();
      await page.getByRole("button", { name: "重新读取所选检查" }).click();
      await page.evaluate(() => window.__preflightQA.release());
      await button.waitFor();
      // Observe the resolved response through real WebCrypto and React work,
      // before beginning a new request that could hide a late-response defect.
      for (let poll = 0; poll < 10; poll += 1) {
        await page.waitForTimeout(25);
        assert.equal(
          await page.getByText("本次原件核验已完成", { exact: true }).count(),
          0,
        );
      }
      assert.equal(
        await page.getByText("本次原件核验已完成", { exact: true }).count(),
        0,
      );
      await page.evaluate(() => {
        window.__preflightQA.delay = false;
      });
      await button.click();
      await page.getByText("本次原件核验已完成", { exact: true }).waitFor();
      await page.evaluate(() =>
        window.dispatchEvent(new Event("session-expired")),
      );
      await page
        .getByText("登录状态已变化，请重新登录后读取提交检查。", {
          exact: true,
        })
        .waitFor();
      assert.equal(
        await page.getByText("本次原件核验已完成", { exact: true }).count(),
        0,
      );
      const final = await page.evaluate(() => ({
        calls: window.__preflightQA.calls,
        unexpected: window.__preflightQA.unexpected,
      }));
      assert.equal(final.calls.length, 4);
      assert(
        final.calls.every(
          (call) =>
            call.method === "POST" &&
            call.path.endsWith("/submission-preflight") &&
            call.expected_body &&
            call.exact_etag,
        ),
      );
      assert.deepEqual(final.unexpected, []);
      assert.deepEqual(errors, []);
      receipt.checks.push({
        viewport,
        theme,
        passed: true,
        calls: final.calls.length,
        empty_initial: true,
        keyboard_activation: true,
        submission_permission_not_claimed: true,
        refreshed_result_cleared: true,
        failure_cleared: true,
        late_reply_discarded: true,
        session_expiry_cleared: true,
        horizontal_overflow: false,
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
    fixture: receipt.fixture,
    output: out,
  }),
);
