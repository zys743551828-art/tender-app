/* global process, console, window, document, innerWidth, URL, sessionStorage */
// Real UI and Chromium. Discovery uses raw native PG/S3 responses with synthetic
// originals; POST acknowledgements explicitly simulate this UI's exact selection.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-authoring-capture-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {AuthoringPackageCapture} from "./src/AuthoringPackageCapture";
import {captureFixture} from "./src/authoringCaptureFixtures.test-support";
import {captureIdentityLabels, captureIdentityNames} from "./src/authoringInputCatalogProtocol";
import {captureCommandKey} from "./src/authoringCaptureCommandProtocol";
import {knowledgeStorageKey} from "./src/knowledgeStorage";
import {jsonDigest} from "./src/editorSchema";
import "./src/styles.css";
const f=captureFixture(), params=new URLSearchParams(location.search), mode=params.get("mode")||"explicit";
if(params.get("theme")==="dark") document.documentElement.dataset.theme="dark";
setAuth({member:{id:f.memberId,active:true,display_name:"合成固定输入采集验收"},csrf_token:"synthetic-only",expires_at:"2099-01-01T00:00:00Z"});
if(mode!=="explicit"&&!sessionStorage.getItem("qa-capture-opened")) {
  sessionStorage.setItem(knowledgeStorageKey(f.memberId,f.bidId)+"authoring-package-capture:draft",JSON.stringify(f.draft));
  sessionStorage.setItem("qa-capture-opened","1");
}
const calls=[],unexpected=[],accepted=[];
window.__captureQA={calls,unexpected,accepted,request:f.request,draft:f.draft,facts:f.facts,identityNames:captureIdentityNames,identityLabels:captureIdentityLabels,recoveryKey:captureCommandKey({memberId:f.memberId,bidId:f.bidId})};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
window.fetch=async(input,options={})=>{
  const url=new URL(input,location.origin),method=options.method||"GET",record={path:url.pathname+url.search,method,key:new Headers(options.headers).get("Idempotency-Key"),body:options.body?JSON.parse(options.body):null};
  calls.push(record);
  if(method==="POST"&&url.pathname==="/api/v1/bids/"+f.bidId+"/authoring/package-inputs") {
    if(mode==="lost"&&!sessionStorage.getItem("qa-capture-first")){sessionStorage.setItem("qa-capture-first",JSON.stringify(record));throw new TypeError("Synthetic lost ACK");}
    const value=structuredClone(f.saved);
    value.manifest.selection=record.body;
    if(mode==="wrong") value.manifest.actor_id=crypto.randomUUID();
    value.digest=await jsonDigest(value.manifest);
    return json(value,201);
  }
  const row=method==="GET"&&f.bundle.responses.find(row=>row.name!=="saved"&&row.path===url.pathname&&Object.entries(row.query).every(([k,v])=>url.searchParams.get(k)===String(v)));
  if(row)return json(row.body,row.status);
  unexpected.push(record);return json({code:"UNEXPECTED_READ",message:"Synthetic unexpected route"},404);
};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth:1120,margin:"0 auto",padding:16}}><h1>固定编写输入</h1><p className="small-note">合成原件；真实界面与明确的保存响应模拟。</p><AuthoringPackageCapture memberId={f.memberId} bidId={f.bidId} onSaved={value=>accepted.push(value)}/></main>);
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
});
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>固定输入采集浏览器验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    const dir = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const target = path.resolve(dir, `.${name === "/" ? "/index.html" : name}`);
    if (!target.startsWith(dir + path.sep)) throw new Error("outside fixture");
    const bytes = await fs.readFile(target);
    res.writeHead(200, {
      "Content-Type":
        {
          ".html": "text/html",
          ".js": "text/javascript",
          ".css": "text/css",
          ".woff2": "font/woff2",
        }[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(bytes);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const sha = (value) => crypto.createHash("sha256").update(value).digest("hex");
const sources = Object.keys(built.metafile.inputs).filter(
  (v) => !v.includes("node_modules") && v !== "<stdin>",
);
sources.push("scripts/check-authoring-capture-browser.mjs");
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sources
        .sort()
        .map(async (p) => [p, sha(await fs.readFile(path.resolve(root, p)))]),
    ),
  );
const receipt = {
  schema: "authoring-input-capture-browser/1",
  passed: false,
  real_model_calls: 0,
  real_database_in_browser: false,
  transport:
    "Unmodified native PG17/S3 discovery with synthetic originals; simulated exact POST acknowledgement; actual UI and Chromium",
  source_sha256: await identities(),
  checks: [],
  screenshots: [],
};
let browser;
let lastPage;
async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready);
  const overflow = await page.evaluate(() => ({
    horizontal: document.documentElement.scrollWidth > innerWidth + 1,
    elements: Array.from(document.querySelectorAll("main *"))
      .filter((el) => el.getBoundingClientRect().right > innerWidth + 1)
      .slice(0, 10)
      .map((el) => ({
        tag: el.tagName,
        class: el.className,
        right: el.getBoundingClientRect().right,
        text: el.textContent?.slice(0, 100),
      })),
  }));
  await page.screenshot({ path: path.join(out, name), fullPage: true });
  receipt.screenshots.push({
    file: name,
    sha256: sha(await fs.readFile(path.join(out, name))),
  });
  if (overflow.horizontal) throw new Error(JSON.stringify({ name, overflow }));
}
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
      for (const mode of ["explicit", "lost", "wrong"]) {
        const context = await browser.newContext({
          viewport: { width, height: 960 },
          colorScheme: theme,
        });
        const page = await context.newPage(),
          errors = [],
          external = [];
        lastPage = page;
        page.on("pageerror", (e) => errors.push(String(e)));
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
        const save = page.getByRole("button", {
          name: "保存这份固定编写输入",
          exact: true,
        });
        await save.waitFor();
        if (mode === "explicit") {
          if (await save.isEnabled())
            throw new Error("automatic input selection");
          const f = await page.evaluate(() => window.__captureQA);
          for (const [label, ref] of [
            ["目标投标包", f.request.package_context.target],
            ["招标与补遗依据包", f.request.package_context.authority],
          ]) {
            await page
              .getByLabel(label + "目录", { exact: false })
              .selectOption(ref.package_id);
            await page
              .getByRole("group", { name: label, exact: true })
              .getByRole("button", { name: /选择第 1 版/ })
              .click();
          }
          await page
            .getByLabel("需求清单", { exact: false })
            .selectOption(f.request.package_context.inventory.id);
          await page
            .getByLabel("正文快照", { exact: false })
            .selectOption(f.request.target_section.snapshot_id);
          await page
            .getByLabel("快照中的章节", { exact: false })
            .selectOption(f.request.target_section.section_id);
          await page
            .getByLabel("稳定文字节点", { exact: false })
            .selectOption(f.request.target_section.node_id);
          await page
            .getByLabel("事实集", { exact: false })
            .selectOption(f.request.facts.fact_set_id);
          for (const name of f.identityNames)
            await page
              .getByRole("combobox", {
                name: new RegExp("^" + f.identityLabels[name]),
              })
              .selectOption(f.draft.identities[name]);
          const fact = f.facts.items.find(
            (x) => x.fact_id === f.request.facts.uses[0].fact_id,
          );
          await page
            .getByRole("checkbox", {
              name: new RegExp(
                "将“" +
                  (fact.identity_name
                    ? f.identityLabels[fact.identity_name]
                    : fact.name) +
                  "”用于本次编写",
              ),
            })
            .check();
          await page
            .getByLabel("作用对象", { exact: false })
            .selectOption(f.request.facts.uses[0].subject.kind);
          await page
            .getByLabel("本次用途与理由", { exact: false })
            .fill(f.request.facts.uses[0].reason);
        }
        await page.waitForFunction(() => {
          const button = Array.from(document.querySelectorAll("button")).find(
            (x) => x.textContent === "保存这份固定编写输入",
          );
          return button && !button.disabled;
        });
        const early = await page.evaluate(
          () =>
            window.__captureQA.calls.filter((x) => x.method !== "GET").length,
        );
        if (early) throw new Error("write before explicit save");
        await capture(page, `selected-${mode}-${theme}-${width}.png`);
        await save.click();
        if (mode === "lost") {
          await page
            .getByRole("button", { name: "恢复原保存请求", exact: true })
            .waitFor();
          await page.reload();
          await page
            .getByRole("button", { name: "恢复原保存请求", exact: true })
            .click();
          await page.waitForFunction(
            () => window.__captureQA.accepted.length === 1,
          );
          const same = await page.evaluate(
            () =>
              JSON.stringify(
                window.__captureQA.calls.find((x) => x.method === "POST"),
              ) === sessionStorage.getItem("qa-capture-first"),
          );
          if (!same) throw new Error("lost ACK changed original body or key");
        } else if (mode === "wrong") {
          await page
            .getByRole("button", { name: "恢复原保存请求", exact: true })
            .waitFor();
          const retained = await page.evaluate(
            () =>
              window.__captureQA.accepted.length === 0 &&
              !!sessionStorage.getItem(window.__captureQA.recoveryKey),
          );
          if (!retained) throw new Error("wrong actor ACK lost recovery");
        } else
          await page.waitForFunction(
            () => window.__captureQA.accepted.length === 1,
          );
        await capture(page, `result-${mode}-${theme}-${width}.png`);
        const result = await page.evaluate(() => ({
          unexpected: window.__captureQA.unexpected,
          writes: window.__captureQA.calls.filter((x) => x.method !== "GET")
            .length,
          accepted: window.__captureQA.accepted.length,
          recovery_present: !!sessionStorage.getItem(
            window.__captureQA.recoveryKey,
          ),
        }));
        if (
          errors.length ||
          external.length ||
          result.unexpected.length ||
          result.writes !== 1 ||
          (mode !== "wrong" && result.recovery_present)
        )
          throw new Error(
            JSON.stringify({ width, theme, mode, result, errors, external }),
          );
        receipt.checks.push({
          width,
          theme,
          mode,
          horizontal_overflow: false,
          ...result,
          javascript_errors: errors,
          external_requests: external,
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
  if (lastPage && !lastPage.isClosed()) {
    await lastPage.screenshot({
      path: path.join(out, "failure.png"),
      fullPage: true,
    });
    receipt.failure_state = await lastPage.evaluate(() => ({
      text: document.body.innerText,
      calls: window.__captureQA?.calls,
      labels: Array.from(document.querySelectorAll("label")).map(
        (el) => el.textContent,
      ),
    }));
  }
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
