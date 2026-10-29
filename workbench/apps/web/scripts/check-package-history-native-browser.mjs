/* global console, process, window, document, innerWidth, sessionStorage */
// Chromium exercises the real product components using unmodified HTTP captures
// from one native PG run. Browser transport is a replay, not a database run.
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath, URL } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-history-native-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const mainFixture = "src/test-fixtures/package-history-ui-complete-http.json";
const unavailableFixture =
  "src/test-fixtures/package-history-ui-unavailable-http.json";
const capture = JSON.parse(
  await fs.readFile(path.join(root, mainFixture), "utf8"),
);
const native = Object.fromEntries(capture.responses.map((r) => [r.name, r]));
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import { createRoot } from "react-dom/client";
import { setAuth } from "./src/api";
import { PackageHistoricalAdmission } from "./src/PackageHistoricalAdmission";
import { PackageHistoricalResearch } from "./src/PackageHistoricalResearch";
import native from "./${mainFixture}";
import unavailable from "./${unavailableFixture}";
import "./src/styles.css";
const records=Object.fromEntries(native.responses.map(r=>[r.name,r]));
const absent=Object.fromEntries(unavailable.responses.map(r=>[r.name,r]));
const params=new URLSearchParams(location.search),mode=params.get("mode"),theme=params.get("theme");
document.documentElement.dataset.theme=theme;
setAuth({member:{id:native.actor_id,active:true,display_name:"合成研究验收"},csrf_token:"synthetic-only",expires_at:"2099-01-01T00:00:00Z"});
const canonical=value=>JSON.stringify(value&&typeof value==="object"?Array.isArray(value)?value.map(v=>JSON.parse(canonical(v))):Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,JSON.parse(canonical(v))])):value);
const calls=[],unexpected=[],used=[];let train="queued",empty=false;
window.__historyNative={calls,unexpected,used,showEmpty:()=>{empty=true},showTrainResult:()=>{train="succeeded"}};
const response=record=>{used.push(record.name);return new Response(JSON.stringify(record.body),{status:record.status,headers:{"Content-Type":"application/json",...(record.etag?{ETag:record.etag}:{})}})};
window.fetch=async(input,options={})=>{
 const url=new URL(input,location.origin),method=options.method||"GET",headers=new Headers(options.headers);
 const request={path:url.pathname,query:Object.fromEntries(url.searchParams),method,body:options.body?JSON.parse(options.body):null,etag:headers.get("If-Match"),key:headers.get("Idempotency-Key")};calls.push(request);
 if(method==="GET"){
  if(mode==="unavailable"){
   const kind=url.pathname.split("/").at(-1),record=absent[kind+(empty?"_empty":"_unavailable")];
   if(record)return response(record);
  }
  if(url.pathname===records.admission_context.path){
   if(canonical(request.query)!==canonical(records.admission_context.query))throw new Error("Different admission pair");
   return response(records.admission_context);
  }
  if(url.pathname===records.cohort_current.path)return response(records[mode==="stale"?"cohort_stale":"cohort_current"]);
  if(url.pathname===records.train_queued.path)return response(records["train_"+train]);
  if(url.pathname===records.evaluate_succeeded.path)return response(records[mode==="stale"?"evaluation_stale":"evaluate_succeeded"]);
  for(const name of ["admissions_directory","protocols_directory","cohorts_directory","jobs_directory","protocol_template"]){
   if(url.pathname===records[name].path)return response(records[name]);
  }
  const admission=native.responses.find(r=>r.method==="GET"&&r.path===url.pathname&&r.name.endsWith("_current")&&r.body.admission);
  if(admission)return response(admission);
 }
 if(method==="POST"){
  let name;
  if(url.pathname===records.admission_created.path)name="admission_created";
  else if(url.pathname===records.protocol_created.path)name="protocol_created";
  else if(url.pathname===records.cohort_created.path)name="cohort_created";
  else if(url.pathname===records.train_created.path)name=request.body.kind==="train"?"train_created":"evaluate_created";
  else if(url.pathname===records.pause_ack.path)name=request.body.action==="pause"?"pause_ack":"resume_ack";
  if(name){
   const record=records[name];
   if(canonical(record.request_body)!==canonical(request.body)||request.etag!==(record.request_headers["if-match"]||null)||!request.key){unexpected.push({request,expected:name});throw new Error("Browser request differs from captured native command: "+name)}
   if(mode==="recovery"&&name==="protocol_created"&&!sessionStorage.getItem("native-first-request")){sessionStorage.setItem("native-first-request",JSON.stringify(request));throw new TypeError("Explicit browser-only ACK loss; native command itself was successful")}
   if(name==="pause_ack")train="paused";
   if(name==="resume_ack")train="resumed";
   return response(record);
  }
 }
 unexpected.push(request);return new Response(JSON.stringify({code:"UNEXPECTED_REPLAY_ROUTE",message:"未配置的原生响应重放路由"}),{status:500,headers:{"Content-Type":"application/json"}});
};
const admission=records.admission_created.body;
const props={memberId:native.actor_id,saved:records.saved_scope.body,submission:records.scope_submissions.body.items.find(v=>v.id===admission.submission_id),outcome:records.scope_outcomes.body.items.find(v=>v.id===admission.outcome_id)};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth:1160,margin:"0 auto",padding:16}}><h1>整包历史研究验收</h1><p>真实组件 · 同次原生响应重放 · 合成业务资料</p>{mode==="admission"?<PackageHistoricalAdmission {...props}/>:<PackageHistoricalResearch memberId={native.actor_id}/>}</main>);
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
});
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>整包历史研究原生响应重放</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const base = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const file = path.resolve(base, `.${name === "/" ? "/index.html" : name}`);
    if (!file.startsWith(base + path.sep)) throw new Error("Outside replay");
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
const sha = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const sourcePaths = [
  ...Object.keys(built.metafile.inputs).filter(
    (p) => !p.includes("node_modules") && p !== "<stdin>",
  ),
  "scripts/check-package-history-native-browser.mjs",
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
  schema: "package-history-native-browser/1",
  passed: false,
  paid_calls: 0,
  real_database_in_browser: false,
  transport:
    "Actual Chromium and product UI. Unmodified successful/failed HTTP bodies and ETags from native PG captures are replayed locally. The recovery scenario alone injects browser-only transport loss. No model or database is contacted by the browser.",
  fixtures: {
    [mainFixture]: sha(await fs.readFile(path.join(root, mainFixture))),
    [unavailableFixture]: sha(
      await fs.readFile(path.join(root, unavailableFixture)),
    ),
  },
  source_before: await identities(),
  checks: [],
  screenshots: [],
};
let browser, currentPage;
try {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
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
      for (const mode of [
        "admission",
        "study",
        "evaluation",
        "stale",
        "recovery",
        "unavailable",
      ]) {
        const context = await browser.newContext({
          viewport: { width, height: 960 },
          colorScheme: theme,
        });
        const page = await context.newPage();
        currentPage = page;
        const errors = [],
          external = [];
        page.on("pageerror", (e) => errors.push(String(e)));
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
        const button = (name) =>
          page.getByRole("button", { name, exact: true });
        const screenshot = async (stage) => {
          await page.evaluate(() => document.fonts.ready);
          const file = `native-${mode}-${stage}-${width}-${theme}.png`;
          await page.screenshot({ path: path.join(out, file), fullPage: true });
          receipt.screenshots.push({
            file,
            sha256: sha(await fs.readFile(path.join(out, file))),
          });
        };
        if (mode === "admission") {
          await button("读取所选记录的严格准入依据").click();
          await page
            .getByLabel("严格历史准入核验回执")
            .selectOption(native.admission_created.request_body.proof_id);
          await page
            .getByLabel("严格历史准入原因")
            .fill(native.admission_created.request_body.reason);
          await page.getByRole("checkbox").check();
          await button("明确保存这份历史研究准入").click();
          await page.getByLabel("严格历史准入保存回执").waitFor();
        } else if (mode === "unavailable") {
          await button("读取准入资料目录").click();
          await page.getByText(/准入资料目录尚未配置/).waitFor();
          await screenshot("unknown");
          await page.evaluate(() => window.__historyNative.showEmpty());
          await button("读取准入资料目录").click();
          await page.getByText("本次已观察到的准入资料目录为空。").waitFor();
          if (await page.getByText(/目录尚未配置/).count())
            throw new Error("Unknown conflated with empty");
        } else if (mode === "recovery") {
          await button("2. 冻结研究方案").click();
          await page.getByText("冻结新 CPU 研究协议", { exact: true }).click();
          await button("读取当前 CPU 方法").click();
          await page
            .getByLabel("随机种子", { exact: true })
            .fill(String(native.protocol_created.request_body.seed));
          await page
            .getByLabel("组级重采样次数")
            .fill(
              String(native.protocol_created.request_body.bootstrap_iterations),
            );
          await page
            .getByLabel("冻结协议的原因")
            .fill(native.protocol_created.request_body.reason);
          await page
            .getByRole("checkbox", { name: /我已核对 CPU 方法/ })
            .check();
          await button("明确冻结 CPU 协议").click();
          await button("恢复原研究请求结果").waitFor();
          await screenshot("pending");
          await page.reload();
          await button("恢复原研究请求结果").click();
          await page.getByText(/已确认协议冻结回执/).waitFor();
          const pair = await page.evaluate(() => ({
            first: JSON.parse(sessionStorage.getItem("native-first-request")),
            replay: window.__historyNative.calls.find(
              (c) => c.method === "POST",
            ),
          }));
          if (JSON.stringify(pair.first) !== JSON.stringify(pair.replay))
            throw new Error("Original protocol request changed on recovery");
        } else {
          if (mode === "study") {
            await button("读取准入资料目录").click();
            const choices = native.cohort_created.request_body.selections;
            for (let i = 0; i < choices.length; i++) {
              const index =
                native.admissions_directory.body.items.findIndex(
                  (v) => v.id === choices[i].admission_id,
                ) + 1;
              await button(`核对资料 ${index} 的准入详情`).click();
              await button("明确选入研究方案").click();
              await page
                .getByRole("combobox", { name: `资料 ${i + 1} 的请求用途` })
                .selectOption(choices[i].purpose);
            }
            await button("2. 冻结研究方案").click();
            await button("读取CPU协议目录").click();
            await button("选择协议 1").click();
            // The precise input mode preserves the recorded RFC3339 microseconds.
            await page.getByLabel("使用含时区的精确时间（可保留微秒）").check();
            await page
              .getByLabel("精确实交分界（必须含时区）", { exact: true })
              .fill(native.cohort_created.request_body.submission_split_at);
            await page
              .getByLabel("精确标签可用截止（必须含时区）", { exact: true })
              .fill(native.cohort_created.request_body.label_available_as_of);
            await page
              .getByLabel("冻结研究组的原因")
              .fill(native.cohort_created.request_body.reason);
            await button("1. 选择已准入资料").click();
            await button("2. 冻结研究方案").click();
            if (
              (await page.getByLabel("冻结研究组的原因").inputValue()) !==
              native.cohort_created.request_body.reason
            )
              throw new Error("Step switch discarded proposal");
            await page
              .getByRole("checkbox", { name: /我已核对所选协议/ })
              .check();
            await screenshot("proposal");
            await button("明确冻结研究组").click();
            await page.getByText(/已确认研究组冻结回执/).waitFor();
          } else {
            await button("3. 任务与结果").click();
            await button("读取研究组目录").click();
            await button("打开研究组 1").click();
          }
          await page.getByLabel("当前研究组详情", { exact: true }).waitFor();
          if (mode === "study") {
            await page
              .getByRole("combobox", { name: "本次任务" })
              .selectOption("train");
            await page
              .getByLabel("创建任务的原因")
              .fill(native.train_created.request_body.reason);
            await page
              .getByRole("checkbox", { name: /我已核对本研究组/ })
              .check();
            await button("明确创建研究任务").click();
            await page
              .getByText(
                "任务已登记，等待独立研究服务领取；尚未证明训练或评估完成。",
              )
              .waitFor();
            for (const [action, name] of [
              ["pause", "pause_ack"],
              ["resume", "resume_ack"],
            ]) {
              await page
                .getByRole("combobox", { name: "任务控制动作" })
                .selectOption(action);
              await page
                .getByLabel("控制任务的原因")
                .fill(native[name].request_body.reason);
              await page
                .getByRole("checkbox", { name: /我已核对当前任务/ })
                .check();
              await button("明确执行任务控制").click();
              await page
                .getByRole("status")
                .filter({
                  hasText:
                    action === "pause"
                      ? /已确认原任务回执：已暂停/
                      : /已确认原任务回执：等待独立执行/,
                })
                .waitFor();
            }
            await page.evaluate(() => window.__historyNative.showTrainResult());
            await button("读取所选任务当前状态").click();
            await page
              .getByRole("heading", { name: "CPU 基线训练结果", exact: true })
              .waitFor();
          } else {
            if (
              mode === "stale" &&
              (await button("明确创建研究任务").isEnabled())
            )
              throw new Error("Stale cohort enabled new command");
            await button("读取组内任务目录").click();
            const index =
              native.jobs_directory.body.items.findIndex(
                (v) => v.id === native.evaluate_succeeded.body.job_id,
              ) + 1;
            await button(`打开任务 ${index}`).click();
            await page
              .getByRole("heading", { name: "独立最终评估记录", exact: true })
              .waitFor();
            const report = page.getByLabel("全部最终评估记录", { exact: true });
            const text = await report.innerText();
            if (
              !text.includes("未取得") ||
              !text.includes("拒绝") ||
              !text.includes("未标注")
            )
              throw new Error(
                "Result omitted unavailable/full denominator fields",
              );
            if (mode === "stale")
              await page
                .getByText(
                  "当前依据已变化。历史结果仍按原版本读取；不恢复执行或授予新用途资格。",
                )
                .waitFor();
          }
        }
        await screenshot("complete");
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth + 1,
        );
        const evidence = await page.evaluate(() => ({
          calls: window.__historyNative.calls,
          unexpected: window.__historyNative.unexpected,
          used: window.__historyNative.used,
        }));
        const passed =
          !overflow &&
          !errors.length &&
          !external.length &&
          !evidence.unexpected.length;
        receipt.checks.push({
          mode,
          width,
          theme,
          passed,
          overflow,
          errors,
          external,
          ...evidence,
        });
        if (!passed)
          throw new Error(`Browser checks failed ${mode}/${width}/${theme}`);
        await context.close();
        currentPage = null;
      }
  receipt.source_after = await identities();
  receipt.source_unchanged =
    JSON.stringify(receipt.source_before) ===
    JSON.stringify(receipt.source_after);
  receipt.passed =
    receipt.source_unchanged && receipt.checks.every((c) => c.passed);
  if (!receipt.passed) throw new Error("Source changed during browser run");
} catch (error) {
  receipt.error = String(error);
  if (currentPage) {
    await currentPage
      .screenshot({ path: path.join(out, "failure.png"), fullPage: true })
      .catch(() => {});
    receipt.failure_text = await currentPage
      .locator("body")
      .innerText()
      .catch(() => "");
  }
  process.exitCode = 1;
} finally {
  await browser?.close();
  if (server.listening) await new Promise((resolve) => server.close(resolve));
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      passed: receipt.passed,
      checks: receipt.checks.length,
      screenshots: receipt.screenshots.length,
      error: receipt.error ?? null,
      receipt: path.join(out, "receipt.json"),
    }),
  );
}
