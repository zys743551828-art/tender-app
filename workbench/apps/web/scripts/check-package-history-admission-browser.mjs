/* global console, process, window, document, innerWidth, sessionStorage */
// Real Chromium and product components, with explicitly simulated historical
// admission responses. Native PG proof is captured by a separate acceptance run.
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath, URL } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-history-admission-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import { createRoot } from "react-dom/client";
import { setAuth } from "./src/api";
import { PackageHistoricalAdmission } from "./src/PackageHistoricalAdmission";
import { historyAdmissionFixture } from "./src/packageHistoricalAdmissionFixtures.test-support";
import { historyEtag } from "./src/packageHistoricalResearchProtocol";
import { historyRecoveryKey } from "./src/packageHistoricalResearchRecovery";
import { jsonDigest } from "./src/editorSchema";
import "./src/styles.css";
import "./src/PackageTechnicalScope.css";
const f=await historyAdmissionFixture(),params=new URLSearchParams(location.search),mode=params.get("mode")||"explicit";
if(params.get("theme")==="dark")document.documentElement.dataset.theme="dark";
setAuth({member:{id:f.memberId,active:true,display_name:"合成历史研究验收"},csrf_token:"synthetic-only",expires_at:"2099-01-01T00:00:00Z"});
const calls=[],unexpected=[];
window.__historyAdmission={calls,unexpected,proofId:f.proofId,recoveryKey:historyRecoveryKey(f.memberId,f.workspace)};
const json=(body,status,etag)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json",...(etag?{ETag:etag}:{})}});
window.fetch=async(input,options={})=>{
 const url=new URL(input,location.origin),method=options.method||"GET",record={path:url.pathname+url.search,method,key:new Headers(options.headers).get("Idempotency-Key"),etag:new Headers(options.headers).get("If-Match"),body:options.body?JSON.parse(options.body):null};
 calls.push(record);
 if(method==="GET"&&url.pathname==="/api/v1"+f.base+"/historical-admission-context"){
  if(url.searchParams.get("submission_id")!==f.submission.id||url.searchParams.get("outcome_id")!==f.outcome.id)throw new Error("Different selected pair");
  const value=structuredClone(f.context);
  if(mode==="gap")value.blockers.push({code:"PACKAGE_HISTORY_COMPLETE_VISUAL_RANGE_PROOF_MISSING",message:"缺少完整图文范围证据"});
  return json(value,200,await historyEtag("context",f.saved.manifest.id,value));
 }
 if(method==="POST"&&url.pathname==="/api/v1"+f.base+"/historical-admissions"){
  if(mode==="lost"&&!sessionStorage.getItem("qa-first-admission")){sessionStorage.setItem("qa-first-admission",JSON.stringify(record));throw new TypeError("Explicit synthetic lost ACK");}
  const value=structuredClone(f.admission);
  if(mode==="wrong"){
   value.outcome_id="50000000-0000-4000-8000-000000000001";
   value.digest=await jsonDigest(Object.fromEntries(Object.entries(value).filter(([k])=>k!=="digest")));
  }
  return json(value,201,await historyEtag("admission",value.id,value));
 }
 unexpected.push(record);return json({code:"UNEXPECTED_ROUTE",message:"未配置的合成路由"},404);
};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth:1040,margin:"0 auto",padding:16}}><h1>整包历史研究准入</h1><p>合成机制资料 · 实际组件与明确响应模拟</p><PackageHistoricalAdmission {...f}/></main>);
`;
const built = await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  format: "esm",
  target: "es2022",
  jsx: "automatic",
  outdir: out,
  entryNames: "app",
  metafile: true,
  external: ["/fonts/*"],
  logLimit: 5,
});
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>历史准入浏览器验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const base = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const file = path.resolve(base, `.${name === "/" ? "/index.html" : name}`);
    if (!file.startsWith(base + path.sep)) throw new Error("Outside fixture");
    const bytes = await fs.readFile(file);
    res.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".woff2": "font/woff2",
        }[path.extname(file)] ?? "application/octet-stream",
    });
    res.end(bytes);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const sha = (value) => crypto.createHash("sha256").update(value).digest("hex");
const sourcePaths = [
  ...Object.keys(built.metafile.inputs).filter(
    (name) => !name.includes("node_modules") && name !== "<stdin>",
  ),
  "scripts/check-package-history-admission-browser.mjs",
];
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sourcePaths
        .sort()
        .map(async (name) => [
          name,
          sha(await fs.readFile(path.resolve(root, name))),
        ]),
    ),
  );
const receipt = {
  schema: "package-history-admission-browser/1",
  passed: false,
  real_database_in_browser: false,
  paid_calls: 0,
  transport:
    "Actual Chromium and component; explicitly simulated admission context, writes and fault responses. Source metadata is from an earlier synthetic fixture, not one joined native run.",
  source_before: await identities(),
  checks: [],
  screenshots: [],
};
let browser;
let currentPage;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  receipt.chromium = browser.version();
  const origin = `http://127.0.0.1:${server.address().port}`;
  for (const width of [390, 1280])
    for (const theme of ["light", "dark"])
      for (const mode of ["explicit", "lost", "wrong", "gap"]) {
        const context = await browser.newContext({
          viewport: { width, height: 960 },
          colorScheme: theme,
        });
        const page = await context.newPage();
        currentPage = page;
        const errors = [],
          external = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        page.on("dialog", (dialog) => dialog.accept());
        await page.route("**/*", async (route) => {
          const url = route.request().url();
          if (url.startsWith(origin) || url.startsWith("blob:"))
            await route.continue();
          else {
            external.push(url);
            await route.abort();
          }
        });
        await page.goto(`${origin}/?mode=${mode}&theme=${theme}`);
        await page
          .getByRole("button", { name: "读取所选记录的严格准入依据" })
          .click();
        await page.getByLabel("严格历史准入依据", { exact: true }).waitFor();
        if (await page.getByLabel("严格历史准入核验回执").inputValue())
          throw new Error("Automatically chose a proof");
        const proofId = await page.evaluate(
          () => window.__historyAdmission.proofId,
        );
        await page.getByLabel("严格历史准入核验回执").selectOption(proofId);
        await page
          .getByLabel("严格历史准入原因")
          .fill("核对同一实交、官方零分与独立回执，仅用于合成机制验收");
        await page.getByRole("checkbox").check();
        const save = page.getByRole("button", {
          name: "明确保存这份历史研究准入",
        });
        if (mode === "gap") {
          if (await save.isEnabled())
            throw new Error("Missing range proof allowed");
        } else {
          await save.click();
          if (mode === "explicit")
            await page.getByLabel("严格历史准入保存回执").waitFor();
          if (mode === "wrong") {
            const recover = page.getByRole("button", {
              name: "恢复原准入请求结果",
            });
            await recover.waitFor();
            await page.waitForFunction(
              () =>
                !Array.from(document.querySelectorAll("button")).find((b) =>
                  b.textContent.includes("恢复原准入请求结果"),
                )?.disabled,
            );
            if (await page.getByLabel("严格历史准入保存回执").count())
              throw new Error("Accepted different outcome ACK");
          }
          if (mode === "lost") {
            await page
              .getByRole("button", { name: "恢复原准入请求结果" })
              .waitFor();
            await page.reload();
            await page
              .getByRole("button", { name: "恢复原准入请求结果" })
              .click();
            await page.getByLabel("严格历史准入保存回执").waitFor();
            const pair = await page.evaluate(() => ({
              first: JSON.parse(sessionStorage.getItem("qa-first-admission")),
              replay: window.__historyAdmission.calls.find(
                (c) => c.method === "POST",
              ),
            }));
            if (JSON.stringify(pair.first) !== JSON.stringify(pair.replay))
              throw new Error("Changed original request on reload");
          }
        }
        await page.evaluate(() => document.fonts.ready);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth + 1,
        );
        const calls = await page.evaluate(() => ({
          calls: window.__historyAdmission.calls,
          unexpected: window.__historyAdmission.unexpected,
        }));
        const file = `admission-${mode}-${width}-${theme}.png`;
        await page.screenshot({ path: path.join(out, file), fullPage: true });
        receipt.screenshots.push({
          file,
          sha256: sha(await fs.readFile(path.join(out, file))),
        });
        const passed =
          !errors.length &&
          !external.length &&
          !overflow &&
          !calls.unexpected.length;
        receipt.checks.push({
          mode,
          width,
          theme,
          passed,
          javascript_errors: errors,
          external_requests: external,
          horizontal_overflow: overflow,
          writes: calls.calls.filter((call) => call.method === "POST").length,
        });
        if (!passed) throw new Error(JSON.stringify(receipt.checks.at(-1)));
        await context.close();
      }
  receipt.source_after = await identities();
  receipt.source_unchanged =
    JSON.stringify(receipt.source_before) ===
    JSON.stringify(receipt.source_after);
  if (!receipt.source_unchanged)
    throw new Error("Sources changed during browser acceptance");
  receipt.passed = true;
} catch (error) {
  receipt.error = String(error?.stack ?? error);
  if (currentPage)
    await currentPage
      .screenshot({ path: path.join(out, "failure.png"), fullPage: true })
      .catch(() => {});
  throw error;
} finally {
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
  console.log(
    JSON.stringify({
      passed: receipt.passed,
      checks: receipt.checks.length,
      screenshots: receipt.screenshots.length,
      receipt: path.join(out, "receipt.json"),
    }),
  );
}
