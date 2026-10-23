/* global process, console, window, document, innerWidth, URL */
// Real browser/components with explicitly synthetic read-only API records.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/tmp/tender-work-context-browser");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React, {useState} from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {WorkContextWorkspace} from "./src/WorkContextWorkspace";
import {workContextLocation} from "./src/workContextNavigation";
import {workContextFixture, sealContext} from "./qa-previews/frozen-inputs/workContext";
import {authoringContextFixture, contextChoicePage, contextTarget} from "./qa-previews/frozen-inputs/workContextAuthoring";
import {packageReviewOriginalFetch} from "./qa-previews/frozen-inputs/packageReviewComparison";
import {submissionFixture, submissionReceipt, submissionId, submissionEtag} from "./src/packageSubmissionFixtures.test-support";
import "./src/styles.css";
const params = new URLSearchParams(location.search), stage = params.get("stage") || "draft_snapshot";
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
const authoring = await authoringContextFixture(), review = await workContextFixture();
const sub = await submissionFixture(), receipt = await submissionReceipt(sub, {key: submissionId(20), body: sub.body, etag: submissionEtag(), supersedesId: null});
const originalSubmission = receipt.submission, subject = originalSubmission.package_binding.manifest.subject;
const submission = structuredClone(review.context);
submission.selection = {kind: "package_submission", bid_id: originalSubmission.bid_id, package_id: subject.package_id, revision_id: subject.revision_id, package_digest: subject.package_digest,
  submission_id: originalSubmission.id, package_binding_digest: originalSubmission.package_binding.digest, inventory: null, review_run: null};
submission.identity = originalSubmission.identity;
submission.state = {kind: "package_submission", registration_kind: originalSubmission.kind, submitted_at: originalSubmission.submitted_at, recorded_at: originalSubmission.recorded_at,
  supersedes_id: null, gate_checked_at_registration: false, platform_submission_verified: false, pre_submission_system_check_verified: false};
submission.summary = {...submission.summary, perspective: "submission_history", review_status: "not_selected", review: null, primary_action: "open_selected_submission"};
submission.native_targets = {package_revision: {kind: "package_revision", bid_id: originalSubmission.bid_id, package_id: subject.package_id, revision_id: subject.revision_id, package_digest: subject.package_digest},
  authority_revision: null, package_review_run: null, package_submission: {kind: "package_submission", bid_id: originalSubmission.bid_id, submission_id: originalSubmission.id, package_binding_digest: originalSubmission.package_binding.digest}};
await sealContext(submission);
const records = {draft_snapshot: authoring.saved, build: authoring.built, package_review_run: review.context, package_submission: submission};
const record = records[stage], bid = record.selection.bid_id, member = authoring.member;
const target = {kind: stage, id: stage === "draft_snapshot" ? record.selection.snapshot_id : stage === "build" ? record.selection.build_id : stage === "package_review_run" ? record.selection.run_id : record.selection.submission_id, selectionDigest: record.selection_digest};
const calls = [], unexpected = [], navigation = [];
window.__contextQA = {calls, unexpected, navigation, bid, stage};
setAuth({member: {id: member, display_name: "合成阶段验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (v) => new Response(JSON.stringify(v), {headers: {"Content-Type": "application/json"}});
window.fetch = async (input, options = {}) => {
  const url = new URL(input, location.origin), route = url.pathname.replace(/^\\/api\\/v1/, ""), method = options.method || "GET";
  calls.push({route: url.pathname+url.search, method});
  if (method === "GET") {
    if (route.endsWith("/choices")) {const kind = url.searchParams.get("kind"); return json(await contextChoicePage(records[kind].selection.bid_id === bid ? [records[kind].selection] : [], kind, bid));}
    if (route.endsWith("/relations")) return json(authoring.relations);
    if (route.includes("/work-contexts/")) {const kind = route.split("/work-contexts/")[1].split("/")[0]; return json(records[kind]);}
    if (route === "/submissions/"+originalSubmission.id) return json(originalSubmission);
    const native = packageReviewOriginalFetch(review, route); if (native !== null && native !== undefined) return json(native);
  }
  unexpected.push({route, method}); throw new Error("Unexpected context fixture endpoint");
};
function Screen() {
  const [position, setPosition] = useState({stage, selected: params.get("selected") === "1" ? target : null});
  return <main id="main-content" style={{maxWidth: 1120, margin: "0 auto", padding: 16}}><h1>稿件与阶段</h1><p className="small-note">合成浏览器验收，非真实业务效果证明。</p>
    <WorkContextWorkspace bidId={bid} memberId={member} route={workContextLocation(bid, position)}
      onLocation={(next) => {navigation.push(next); setPosition(next);}}
      onOpenDraft={(id) => navigation.push({draft: id})} onOpenPackage={(target) => navigation.push({package: target})}/>
  </main>;
}
createRoot(document.getElementById("root")).render(<Screen/>);
`;
const built = await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  format: "esm",
  jsx: "automatic",
  outdir: out,
  entryNames: "app",
  sourcemap: false,
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
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>稿件阶段真实浏览器验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
        new URL(req.url, "http://localhost").pathname,
      ),
      dir = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const target = path.resolve(dir, `.${name === "/" ? "/index.html" : name}`);
    if (!target.startsWith(dir + path.sep)) throw new Error("outside fixture");
    const contents = await fs.readFile(target),
      types = {
        ".html": "text/html",
        ".js": "text/javascript",
        ".css": "text/css",
        ".woff2": "font/woff2",
      };
    res.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(contents);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const sha = (v) => crypto.createHash("sha256").update(v).digest("hex");
const sources = Object.keys(built.metafile.inputs).filter(
  (v) =>
    !v.includes("node_modules") &&
    !v.startsWith("asset-url:") &&
    v !== "<stdin>",
);
sources.push("scripts/check-work-context-browser.mjs");
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sources
        .sort()
        .map(async (p) => [p, sha(await fs.readFile(path.resolve(root, p)))]),
    ),
  );
const receipt = {
  schema: "work-context-browser/1",
  passed: false,
  real_model_calls: 0,
  real_database_in_browser: false,
  transport:
    "Synthetic immutable API records; real React components, rich text and Chromium",
  source_sha256: await identities(),
  checks: [],
  screenshots: [],
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
    for (const theme of ["light", "dark"])
      for (const stage of [
        "draft_snapshot",
        "build",
        "package_review_run",
        "package_submission",
      ]) {
        const context = await browser.newContext({
          viewport: { width, height: 960 },
          colorScheme: theme,
        });
        const page = await context.newPage(),
          errors = [],
          external = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        const origin = `http://127.0.0.1:${server.address().port}`;
        await page.route("**/*", async (route) => {
          const u = route.request().url();
          if (u.startsWith(origin) || u.startsWith("blob:"))
            await route.continue();
          else {
            external.push(u);
            await route.abort();
          }
        });
        await page.goto(`${origin}/?stage=${stage}&theme=${theme}`);
        await page
          .getByRole("button", { name: "选择此记录", exact: true })
          .waitFor();
        if (
          await page
            .getByRole("region", { name: "当前明确选择的阶段记录" })
            .count()
        )
          throw new Error("automatic selection");
        await page
          .getByRole("button", { name: "选择此记录", exact: true })
          .click();
        const action = {
          draft_snapshot: "阅读全文与目录",
          build: "查看此次生成文件",
          package_review_run: "读取所选核查原记录",
          package_submission: "读取所选实交原记录",
        }[stage];
        await page.getByRole("button", { name: action, exact: true }).click();
        if (stage === "draft_snapshot") {
          const cell = page.getByRole("columnheader", { name: "合并表头" });
          await cell.waitFor();
          if ((await cell.getAttribute("colspan")) !== "2")
            throw new Error("merged table lost");
          await page.getByText("120天", { exact: true }).waitFor();
        } else if (stage === "build") {
          await page
            .getByRole("button", { name: "下载此次 DOCX", exact: true })
            .waitFor();
          if (
            await page
              .getByRole("button", { name: "下载此次 PDF", exact: true })
              .count()
          )
            throw new Error("failed PDF advertised");
          await page
            .getByRole("button", { name: "核对这次生成文件的入包关系" })
            .click();
          await page.getByRole("button", { name: "打开这版包" }).waitFor();
        } else if (stage === "package_review_run")
          await page
            .getByRole("region", { name: "整包范围核查结果" })
            .waitFor();
        else
          await page
            .getByRole("button", { name: "重读同一实交原记录" })
            .waitFor();
        await page.evaluate(() => document.fonts.ready);
        const result = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          writes: window.__contextQA.calls.filter((r) => r.method !== "GET"),
          unexpected: window.__contextQA.unexpected,
          requests: window.__contextQA.calls.length,
        }));
        if (
          result.overflow ||
          result.writes.length ||
          result.unexpected.length ||
          errors.length ||
          external.length
        )
          throw new Error(
            JSON.stringify({ width, theme, stage, result, errors, external }),
          );
        await page.evaluate(() => window.scrollTo(0, 0));
        const filename = `${stage}-${theme}-${width}.png`;
        await page.screenshot({
          path: path.join(out, filename),
          fullPage: true,
        });
        receipt.screenshots.push({
          file: filename,
          sha256: sha(await fs.readFile(path.join(out, filename))),
        });
        receipt.checks.push({
          width,
          theme,
          stage,
          explicit_selection: true,
          exact_original: true,
          horizontal_overflow: false,
          writes: 0,
          javascript_errors: errors,
          external_requests: external,
          requests: result.requests,
        });
        await context.close();
      }
  if (
    JSON.stringify(await identities()) !== JSON.stringify(receipt.source_sha256)
  )
    throw new Error("source changed during acceptance");
  receipt.passed = true;
} catch (error) {
  receipt.error = String(error);
  process.exitCode = 1;
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
    screenshots: receipt.screenshots.length,
    error: receipt.error,
    receipt: path.join(out, "receipt.json"),
  }),
);
