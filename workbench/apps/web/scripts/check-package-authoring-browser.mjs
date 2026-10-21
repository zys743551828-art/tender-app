/* global process, console, window, document, innerWidth, URL, sessionStorage */
// Real product components and Chromium; captured native API responses with
// synthetic originals, never a production database or a paid model request.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-package-authoring-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {PackageAuthoringTemplateEditor} from "./src/PackageAuthoringTemplateEditor";
import {PackageAuthoringRunControl} from "./src/PackageAuthoringRunControl";
import {TaskRunCard} from "./src/TaskRunCard";
import {AssistantActionCard} from "./src/AssistantActionCard";
import {TaskDraftPanel} from "./src/TaskDraftPanel";
import {packageAuthoringFixture} from "./src/packageAuthoringFixtures.test-support";
import {historicalSame} from "./src/historicalImportProtocol";
import "./src/styles.css";
const f = packageAuthoringFixture(), d = f.draft, params = new URLSearchParams(location.search), mode = params.get("mode") || "editor", bid = mode === "draft" ? d.bid.id : f.template.bid_id, member = mode === "draft" ? d.member_id : f.member_id;
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
const calls = [], unexpected = [], accepted = [];
window.__authoringQA = {calls, unexpected, accepted, template: f.template, run: f.runs.published, draft: d};
let currentDraft = null;
setAuth({member: {id: member, display_name: "合成固定整包编写验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (value, etag = null, status = 200) => new Response(JSON.stringify(value), {status, headers: {"Content-Type": "application/json", ...(etag ? {ETag: etag} : {})}});
window.fetch = async (input, options = {}) => {
  const url = new URL(input, location.origin), route = url.pathname.replace(/^\\/api\\/v1/, ""), method = options.method || "GET";
  calls.push({route: url.pathname+url.search, method, body: options.body || null, headers: options.headers || {}});
  if (mode === "draft") {
    const prefix = "/bids/"+bid, flow = d.task_draft_flow, draftPath = prefix+"/task-definition-drafts/"+flow.created.body.id;
    if (method === "GET") {
      if (route === "/task-kinds") return json(d.kinds);
      if (route === "/assistant/sources") return json({items:[],has_more:false,next_cursor:null});
      if (route === prefix+"/task-definition-drafts") return json({items:currentDraft ? [currentDraft.body] : [],has_more:false,next_cursor:null});
      if (route === draftPath && currentDraft) return json(currentDraft.body,currentDraft.etag);
      if (route === prefix+"/authoring/package-inputs") return json(d.input_page);
      if (route === prefix+"/authoring/package-inputs/"+d.input.manifest.id) return json(d.input);
      if (route === prefix+"/task-definitions/"+d.template.id) return json(d.template,d.template_etag);
      if ([prefix+"/task-definitions/"+d.template.id+"/runs",prefix+"/task-definitions/"+d.template.id+"/schedules"].includes(route)) return json({items:[],has_more:false,next_cursor:null});
    } else {
      const step = route === prefix+"/task-definition-drafts" && method === "POST" ? "created" : route === draftPath && method === "PUT" ? "revised" : route === draftPath+"/save" && method === "POST" ? "saved" : null;
      if (step) {
        const expected = flow[step];
        if (!historicalSame(JSON.parse(options.body),expected.request) || new Headers(options.headers).get("If-Match") !== expected.if_match) throw new Error("Private draft changed exact native request or basis");
        currentDraft = step === "saved" ? flow.final : expected;
        return json(expected.body,expected.etag,expected.status);
      }
    }
    unexpected.push({route,method}); throw new Error("Unexpected private authoring draft request");
  }
  if (method === "GET") {
    if (route === "/bids/"+bid) return json(f.bid, f.bid_etag);
    if (route === "/task-kinds") return json(f.kinds);
    if (route === "/bids/"+bid+"/authoring/package-inputs") return json(f.input_page);
    if (route === "/bids/"+bid+"/authoring/package-inputs/"+f.input.manifest.id) return json(f.input);
    if (route === "/bids/"+bid+"/authoring/package-inputs/"+f.input.manifest.id+"/context") return json(f.context);
    if (route === "/bids/"+bid+"/task-definitions/"+f.template.id) return json(f.template, f.template_etag);
    if (route === "/bids/"+bid+"/task-definitions/"+f.template.id+"/versions/"+f.template.version_id) return json(f.template_version);
    if (route === "/bids/"+bid+"/task-runs/"+f.runs.published.id) return json(f.runs.published);
    if (route === "/operations/"+f.runs.published.root_operation_id) return json(f.operations.published.data, f.operations.published.etag);
    if (route === "/assistant/actions/"+f.proposal.action_id) return json(f.proposal, f.proposal_etag);
  }
  if (method === "POST" && route === "/bids/"+bid+"/task-definitions") {
    if (!historicalSame(JSON.parse(options.body), f.template.configuration)) throw new Error("template input did not equal explicit original choice");
    if (mode === "lost-ack" && !sessionStorage.getItem("qa-authoring-lost-ack")) {sessionStorage.setItem("qa-authoring-lost-ack", JSON.stringify(calls[calls.length-1])); throw new TypeError("Synthetic lost native ACK");}
    return json(f.template, f.template_etag, 201);
  }
  if (method === "POST" && route === "/bids/"+bid+"/task-definitions/"+f.template.id+"/runs") {
    if (JSON.stringify(JSON.parse(options.body)) !== JSON.stringify({rerun:false})) throw new Error("rerun was not explicit false");
    return json(f.accepted_run, null, 202);
  }
  unexpected.push({route, method}); throw new Error("Unexpected authoring fixture request");
};
createRoot(document.getElementById("root")).render(<main id="main-content" style={{maxWidth:1120, margin:"0 auto", padding:16}}><h1>固定整包章节编写</h1><p className="small-note">合成原件与原生响应浏览器验收。</p>
  {mode === "draft" ? <TaskDraftPanel bidId={bid} memberId={member} bidEtag={d.bid_etag} onSaved={() => accepted.push(d.template.id)}/> : mode === "editor" || mode === "lost-ack" ? <PackageAuthoringTemplateEditor bidId={bid} memberId={member} template={null} etag={f.bid_etag} onSaved={value => accepted.push(value)} onClose={() => {}}/> : mode === "run" ? <PackageAuthoringRunControl bidId={bid} memberId={member} id={f.template.id} template={f.template} etag={f.template_etag} kinds={f.kinds} disabled={false} onRun={id => accepted.push(id)} onChanged={() => {}}/> : mode === "action" ? <AssistantActionCard id={f.proposal.action_id} memberId={member}/> : <TaskRunCard bidId={bid} memberId={member} id={f.runs.published.id}/>}</main>);
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
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>固定整包编写浏览器验收</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
        new URL(req.url, "http://localhost").pathname,
      ),
      dir = name.startsWith("/fonts/") ? path.join(root, "public") : out,
      target = path.resolve(dir, `.${name === "/" ? "/index.html" : name}`);
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
  (v) =>
    !v.includes("node_modules") &&
    !v.startsWith("asset-url:") &&
    v !== "<stdin>",
);
sources.push("scripts/check-package-authoring-browser.mjs");
const identities = async () =>
  Object.fromEntries(
    await Promise.all(
      sources
        .sort()
        .map(async (p) => [p, sha(await fs.readFile(path.resolve(root, p)))]),
    ),
  );
const receipt = {
  schema: "package-authoring-browser/1",
  passed: false,
  real_model_calls: 0,
  real_database_in_browser: false,
  transport:
    "Captured native API responses with synthetic originals; real product components and Chromium",
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
  for (const width of [390, 1280])
    for (const theme of ["light", "dark"])
      for (const mode of [
        "editor",
        "lost-ack",
        "run",
        "result",
        "action",
        "draft",
      ]) {
        const context = await browser.newContext({
            viewport: { width, height: 960 },
            colorScheme: theme,
          }),
          page = await context.newPage(),
          errors = [],
          external = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        const origin = `http://127.0.0.1:${server.address().port}`;
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
        if (mode === "editor" || mode === "lost-ack") {
          const save = page.getByRole("button", {
            name: "保存固定整包编写模板，不运行",
            exact: true,
          });
          await save.waitFor();
          if (await save.isEnabled())
            throw new Error("automatic authoring selection");
          await page
            .getByRole("button", { name: "读取固定输入目录", exact: true })
            .click();
          await page.getByRole("button", { name: /选择这份编写输入/ }).click();
          const config = await page.evaluate(
            () => window.__authoringQA.template.configuration,
          );
          await page
            .getByLabel("固定整包编写模板名称", { exact: true })
            .fill(config.name);
          await page
            .getByLabel("固定整包编写要求", { exact: true })
            .fill(config.instructions);
          await save.click();
          if (mode === "lost-ack") {
            await page
              .getByRole("button", {
                name: "恢复原固定整包模板保存结果",
                exact: true,
              })
              .waitFor();
            await page.reload();
            await page
              .getByRole("button", {
                name: "恢复原固定整包模板保存结果",
                exact: true,
              })
              .click();
            await page.waitForFunction(
              () => window.__authoringQA.accepted.length === 1,
            );
            const same = await page.evaluate(() => {
              const first = JSON.parse(
                  sessionStorage.getItem("qa-authoring-lost-ack"),
                ),
                sent = window.__authoringQA.calls.find(
                  (c) => c.method === "POST",
                );
              return JSON.stringify(first) === JSON.stringify(sent);
            });
            if (!same)
              throw new Error("lost ACK recovery changed original command");
          } else
            await page.waitForFunction(
              () => window.__authoringQA.accepted.length === 1,
            );
        } else if (mode === "run") {
          await page
            .getByRole("button", {
              name: "手动生成固定整包章节候选",
              exact: true,
            })
            .click();
          await page.waitForFunction(
            () => window.__authoringQA.accepted.length === 1,
          );
        } else if (mode === "draft") {
          const flow = await page.evaluate(
            () => window.__authoringQA.draft.task_draft_flow,
          );
          await page
            .getByRole("button", {
              name: "用自然语言拟定任务草案／恢复已有草案",
              exact: true,
            })
            .click();
          await page
            .getByLabel("任务草案来源", { exact: true })
            .selectOption("package-authoring");
          await page
            .getByRole("button", { name: "读取固定输入目录", exact: true })
            .click();
          await page.getByRole("button", { name: /选择这份编写输入/ }).click();
          await page
            .getByLabel("想反复完成什么工作", { exact: true })
            .fill(flow.created.request.request);
          await page
            .getByRole("button", {
              name: "生成可编辑草案，不保存模板",
              exact: true,
            })
            .click();
          await page
            .getByLabel("固定整包编写模板名称", { exact: true })
            .fill(flow.revised.request.name);
          await page
            .getByLabel("固定整包编写要求", { exact: true })
            .fill(flow.revised.request.instructions);
          await page
            .getByRole("button", {
              name: "保存为固定整包编写模板，不运行",
              exact: true,
            })
            .click();
          await page.getByText(/此草案已一次保存为以下模板/).waitFor();
          await page.waitForFunction(
            () => window.__authoringQA.accepted.length === 1,
          );
        } else {
          if (mode === "result")
            await page
              .getByRole("button", {
                name: "核对固定整包章节候选的原稿与拟稿",
                exact: true,
              })
              .click();
          else {
            const apply = page.getByRole("button", {
              name: "此固定整包候选暂不可采纳",
              exact: true,
            });
            await apply.waitFor();
            if (await apply.isEnabled())
              throw new Error("unavailable adoption enabled");
          }
          await page.getByText("查看具体文字增删", { exact: true }).click();
          await page.getByLabel("拟修改后全文", { exact: true }).waitFor();
          await page.getByText("查看完整拟稿与格式", { exact: true }).click();
          await page
            .getByLabel("提议保存的完整拟稿", { exact: true })
            .waitFor();
        }
        await page.evaluate(() => {
          for (const d of document.querySelectorAll("details.identity-details"))
            d.open = true;
          return document.fonts.ready;
        });
        const result = await page.evaluate(() => ({
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
          overflow_elements: Array.from(document.querySelectorAll("main *"))
            .filter((el) => el.getBoundingClientRect().right > innerWidth + 1)
            .slice(0, 12)
            .map((el) => ({
              tag: el.tagName,
              class: el.className,
              right: el.getBoundingClientRect().right,
              text: el.textContent?.slice(0, 180),
            })),
          writes: window.__authoringQA.calls.filter((c) => c.method !== "GET"),
          unexpected: window.__authoringQA.unexpected,
          accepted: window.__authoringQA.accepted.length,
        }));
        if (
          result.overflow ||
          result.unexpected.length ||
          errors.length ||
          external.length ||
          (["result", "action"].includes(mode) && result.writes.length)
        ) {
          await page.screenshot({
            path: path.join(out, `failure-${mode}-${theme}-${width}.png`),
            fullPage: true,
          });
          throw new Error(
            JSON.stringify({ width, theme, mode, result, errors, external }),
          );
        }
        await page.evaluate(() => window.scrollTo(0, 0));
        const filename = `${mode}-${theme}-${width}.png`;
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
          mode,
          horizontal_overflow: false,
          writes: result.writes.length,
          accepted: result.accepted,
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
