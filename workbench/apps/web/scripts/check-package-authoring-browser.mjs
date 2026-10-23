/* global process, console, window, document, innerWidth, URL, sessionStorage */
// Real product components and Chromium; captured native API responses with
// synthetic originals, never a production database or a paid model request.
// B3 action proof responses are unchanged captures. The draft guard scenarios
// and ancillary reads are explicitly synthetic UI state, not backend evidence.
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
import {AuthoringPanel} from "./src/AuthoringPanel";
import {AuthoringBuilds} from "./src/AuthoringBuilds";
import {packageAuthoringFixture} from "./src/packageAuthoringFixtures.test-support";
import exact from "./src/test-fixtures/authoring-exact-adoption-http.json";
import built from "./src/test-fixtures/authoring-exact-build-http.json";
import {exactDraftLayoutFixture} from "./src/authoringExactDraftFixtures.test-support";
import {layoutScope} from "./src/authoringLayoutFixtures.test-support";
import {historicalSame} from "./src/historicalImportProtocol";
import "./src/styles.css";
const f = packageAuthoringFixture(), d = f.draft, params = new URLSearchParams(location.search), mode = params.get("mode") || "editor", exactAction = ["exact-action","exact-lost","exact-conflict"].includes(mode), exactBuild = ["exact-build","exact-build-lost","exact-package","exact-package-lost"].includes(mode), exactDraft = mode === "exact-draft" ? await exactDraftLayoutFixture() : null, bid = exactBuild ? built.bid_id : exactDraft ? layoutScope.bidId : exactAction ? exact.bid_id : mode === "draft" ? d.bid.id : f.template.bid_id, member = exactBuild ? built.member_id : exactDraft ? layoutScope.memberId : exactAction ? exact.member_id : mode === "draft" ? d.member_id : f.member_id;
if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
const calls = [], unexpected = [], accepted = [];
window.__authoringQA = {calls, unexpected, accepted, template: f.template, run: f.runs.published, draft: d, exact, exactDraft, built};
let currentDraft = null;
setAuth({member: {id: member, display_name: "合成固定整包编写验收", active: true}, csrf_token: "synthetic-only", expires_at: "2099-01-01T00:00:00Z"});
const json = (value, etag = null, status = 200) => new Response(JSON.stringify(value), {status, headers: {"Content-Type": "application/json", ...(etag ? {ETag: etag} : {})}});
window.fetch = async (input, options = {}) => {
  const url = new URL(input, location.origin), route = url.pathname.replace(/^\\/api\\/v1/, ""), method = options.method || "GET";
  calls.push({route: url.pathname+url.search, method, body: options.body || null, headers: options.headers || {}});
  if (exactDraft) return exactDraft.fetcher(input,options);
  if (exactBuild) {
    if (method === "GET") {
      if (route === "/builds/"+built.build.id) return json(built.build);
      if (route === "/bids/"+bid+"/builds" && !sessionStorage.getItem("qa-exact-built")) return json({items:[],next_cursor:null,has_more:false});
      const read = built.reads[url.pathname+url.search];
      if (read) return json(read.body,read.etag,read.status);
    }
    if (method === "POST" && route === "/bids/"+bid+"/builds") {
      if (!historicalSame(JSON.parse(options.body),built.build_request)) throw new Error("Exact build changed the native frozen request");
      sessionStorage.setItem("qa-exact-built","true");
      if (mode === "exact-build-lost" && !sessionStorage.getItem("qa-exact-build-lost")) {sessionStorage.setItem("qa-exact-build-lost",JSON.stringify(calls.at(-1)));throw new TypeError("Synthetic lost native B4 build ACK");}
      accepted.push("build");
      return json(built.build_ack,null,202);
    }
    if (method === "POST" && route === "/bids/"+bid+"/builds/"+built.build.id+"/package-adoptions") {
      if (!historicalSame(JSON.parse(options.body),built.adoption_request) || new Headers(options.headers).get("If-Match") !== null) throw new Error("Exact output adoption changed the native explicit request");
      if (mode === "exact-package-lost" && !sessionStorage.getItem("qa-exact-package-lost")) {sessionStorage.setItem("qa-exact-package-lost",JSON.stringify(calls.at(-1)));throw new TypeError("Synthetic lost native B4 package ACK");}
      accepted.push("package");
      return json(built.adoption_ack,built.adoption_etag,201);
    }
    unexpected.push({route,method});throw new Error("Unexpected exact build fixture request");
  }
  if (exactAction) {
    if (method === "GET") {
      if (route === "/bids/"+bid) return json(exact.bid,exact.bid_etag);
      if (route === "/authoring/exact-revision-capabilities") return json(exact.capabilities);
      if (route === "/bids/"+bid+"/authoring/package-inputs/"+exact.input.manifest.id) return json(exact.input);
      if (route === "/bids/"+bid+"/authoring/package-inputs/"+exact.input.manifest.id+"/context") return json(exact.context);
      if (route === "/assistant/actions/"+exact.before_action.action_id) return sessionStorage.getItem("qa-exact-consumed") ? json(exact.resolve_ack,exact.resolve_etag) : json(exact.before_action,exact.before_etag);
      if (route === "/bids/"+bid+"/draft-snapshots/"+exact.snapshot.snapshot_id) return json(exact.snapshot);
      if (route === "/bids/"+bid+"/authoring/section-revisions/"+exact.qualification.manifest.section_revision_id+"/exact-qualification") return json(exact.qualification);
    }
    if (method === "POST" && route === "/assistant/actions/"+exact.before_action.action_id+"/resolve") {
      if (!historicalSame(JSON.parse(options.body),exact.resolve_request) || new Headers(options.headers).get("If-Match") !== exact.before_etag) throw new Error("Exact adoption changed original decision or ETag");
      if (mode === "exact-conflict") return json({code:"REVISION_CONFLICT",message:"合成并发冲突，原稿与候选均保留",details:null,request_id:"synthetic-conflict",retryable:false},null,412);
      sessionStorage.setItem("qa-exact-consumed","true");
      if (mode === "exact-lost" && !sessionStorage.getItem("qa-exact-lost")) {sessionStorage.setItem("qa-exact-lost",JSON.stringify(calls.at(-1)));throw new TypeError("Synthetic lost native B3 ACK");}
      return json(exact.resolve_ack,exact.resolve_etag);
    }
    unexpected.push({route,method}); throw new Error("Unexpected exact adoption fixture request");
  }
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
  {exactBuild ? <AuthoringBuilds bidId={bid} memberId={member} draftId={built.saved.draft_id} projectTitle="合成固定整包正文" capabilities={built.reads["/api/v1/authoring/capabilities"].body} richCapabilities={built.reads["/api/v1/authoring/rich-capabilities"].body} fixedRevision={built.saved} disabled={false} setBusy={() => {}} prepare={async()=>{const r=built.reads["/api/v1/bids/"+bid+"/drafts/"+built.saved.draft_id]; return {data:r.body,etag:r.etag};}}/> : exactDraft ? <AuthoringPanel {...layoutScope} projectTitle="合成固定整包正文" onOpenDraft={() => {}}/> : exactAction ? <AssistantActionCard id={exact.before_action.action_id} memberId={member}/> : mode === "draft" ? <TaskDraftPanel bidId={bid} memberId={member} bidEtag={d.bid_etag} onSaved={() => accepted.push(d.template.id)}/> : mode === "editor" || mode === "lost-ack" ? <PackageAuthoringTemplateEditor bidId={bid} memberId={member} template={null} etag={f.bid_etag} onSaved={value => accepted.push(value)} onClose={() => {}}/> : mode === "run" ? <PackageAuthoringRunControl bidId={bid} memberId={member} id={f.template.id} template={f.template} etag={f.template_etag} kinds={f.kinds} disabled={false} onRun={id => accepted.push(id)} onChanged={() => {}}/> : mode === "action" ? <AssistantActionCard id={f.proposal.action_id} memberId={member}/> : <TaskRunCard bidId={bid} memberId={member} id={f.runs.published.id}/>}</main>);
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
    "Unchanged native B2/B3/B4 API proof captures with synthetic originals; exact draft guard, lost ACK/conflict injection and initial empty build history are explicitly synthetic; real product components and Chromium",
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
      for (const mode of process.env.PACKAGE_AUTHORING_MODES?.split(",") ?? [
        "editor",
        "lost-ack",
        "run",
        "result",
        "action",
        "draft",
        "exact-action",
        "exact-lost",
        "exact-conflict",
        "exact-draft",
        "exact-build",
        "exact-build-lost",
        "exact-package",
        "exact-package-lost",
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
        } else if (mode.startsWith("exact-")) {
          if (
            [
              "exact-build",
              "exact-build-lost",
              "exact-package",
              "exact-package-lost",
            ].includes(mode)
          ) {
            await page.getByText("内置正文版式", { exact: true }).waitFor();
            if (await page.getByLabel("章页排版", { exact: true }).count())
              throw new Error("plain exact build invented pagination controls");
            if (
              await page.evaluate(() =>
                window.__authoringQA.calls.some((c) => c.method !== "GET"),
              )
            )
              throw new Error("exact build started automatically");
            await page
              .getByRole("button", { name: "保存确认后生成文件", exact: true })
              .click();
            if (mode === "exact-build-lost") {
              await page
                .getByRole("button", { name: /重试受理草稿修订/ })
                .waitFor();
              await page.reload();
              await page
                .getByRole("button", { name: /重试受理草稿修订/ })
                .click();
              const same = await page.evaluate(
                () =>
                  JSON.stringify(
                    JSON.parse(sessionStorage.getItem("qa-exact-build-lost")),
                  ) ===
                  JSON.stringify(
                    window.__authoringQA.calls.find((c) => c.method === "POST"),
                  ),
              );
              if (!same)
                throw new Error(
                  "exact build recovery changed its original request",
                );
            }
            await page.getByText("此格式生成成功", { exact: true }).waitFor();
            await page.getByText("此格式生成失败", { exact: true }).waitFor();
            await page.getByText(/PDF 转换器尚未配置或不可用/).waitFor();
            if (mode.startsWith("exact-package")) {
              await page
                .getByRole("button", {
                  name: "选择投标包并采用此文件",
                  exact: true,
                })
                .click();
              const request = await page.evaluate(
                () => window.__authoringQA.built.adoption_request,
              );
              await page
                .getByLabel("采用文件用途", { exact: true })
                .fill(request.member.purposes.join("，"));
              await page
                .getByLabel("生成文件采用原因", { exact: true })
                .fill(request.reason);
              await page
                .getByRole("button", {
                  name: "采用文件并新建投标包",
                  exact: true,
                })
                .click();
              if (mode === "exact-package-lost") {
                await page
                  .getByRole("button", {
                    name: "恢复原文件采用请求",
                    exact: true,
                  })
                  .waitFor();
                await page.reload();
                await page
                  .getByRole("button", {
                    name: "恢复原文件采用请求",
                    exact: true,
                  })
                  .click();
                const same = await page.evaluate(
                  () =>
                    JSON.stringify(
                      JSON.parse(
                        sessionStorage.getItem("qa-exact-package-lost"),
                      ),
                    ) ===
                    JSON.stringify(
                      window.__authoringQA.calls.find(
                        (c) => c.method === "POST",
                      ),
                    ),
                );
                if (!same)
                  throw new Error(
                    "exact package recovery changed its original request",
                  );
              }
              await page.getByText(/生成文件已采用到投标包/).waitFor();
              await page
                .getByText("资料包保存结果不代表评审完成或内容通过。", {
                  exact: true,
                })
                .waitFor();
            }
          } else if (mode === "exact-draft") {
            await page
              .getByText(/这份草稿含固定整包候选采纳后的正文修订/)
              .waitFor();
            await page.waitForFunction(
              () => !document.body.textContent.includes("正在核对保存快照"),
            );
            if (
              (await page
                .getByLabel("章节正文", { exact: true })
                .getAttribute("contenteditable")) !== "false"
            )
              throw new Error("exact draft remained editable");
            await page
              .getByRole("button", { name: "章节目录与计划", exact: true })
              .click();
            await page.getByRole("button", { name: /质量保障措施/ }).click();
            const title = page
              .getByRole("region", { name: "正文编写" })
              .getByLabel("章节名称", { exact: true });
            await title.waitFor();
            if (
              (await title.inputValue()) !== "质量保障措施" ||
              (await title.isEnabled())
            )
              throw new Error(
                "exact draft could not navigate read-only chapters",
              );
          } else {
            const apply = page.getByRole("button", {
              name: "采纳这份固定整包候选并保存新修订",
              exact: true,
            });
            await apply.waitFor();
            if (await apply.isEnabled())
              throw new Error(
                "exact adoption missing explicit acknowledgement",
              );
            await page.getByText("查看具体文字增删", { exact: true }).click();
            await page.getByLabel("拟修改后全文", { exact: true }).waitFor();
            await page.getByText("查看完整拟稿与格式", { exact: true }).click();
            await page
              .getByLabel("提议保存的完整拟稿", { exact: true })
              .waitFor();
            await page
              .getByRole("checkbox", {
                name: "我已核对完整原稿与拟稿，确认采用这份修改",
                exact: true,
              })
              .check();
            await apply.click();
            if (mode === "exact-conflict") {
              await page
                .getByRole("button", {
                  name: "读取最新操作卡并重新核对",
                  exact: true,
                })
                .waitFor();
              if (
                await page
                  .getByRole("button", { name: "拒绝此提议", exact: true })
                  .isEnabled()
              )
                throw new Error("conflict allowed a second decision");
              await page
                .getByRole("button", {
                  name: "读取最新操作卡并重新核对",
                  exact: true,
                })
                .click();
              await page.waitForFunction(
                () => !document.body.textContent.includes("原操作遇到修订冲突"),
              );
              if (await apply.isEnabled())
                throw new Error(
                  "conflict reread skipped fresh full-content acknowledgement",
                );
            } else {
              if (mode === "exact-lost") {
                await page
                  .getByRole("button", {
                    name: "恢复原固定整包候选处理结果",
                    exact: true,
                  })
                  .waitFor();
                await page.reload();
                await page
                  .getByRole("button", {
                    name: "恢复原固定整包候选处理结果",
                    exact: true,
                  })
                  .click();
                const same = await page.evaluate(
                  () =>
                    JSON.stringify(
                      JSON.parse(sessionStorage.getItem("qa-exact-lost")),
                    ) ===
                    JSON.stringify(
                      window.__authoringQA.calls.find(
                        (c) => c.method === "POST",
                      ),
                    ),
                );
                if (!same)
                  throw new Error(
                    "exact adoption recovery changed original body, ETag or key",
                  );
              }
              await page
                .getByRole("link", {
                  name: "打开这份正文草稿，核对修订并生成文件",
                  exact: true,
                })
                .waitFor();
            }
          }
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
          unexpected: [
            ...window.__authoringQA.unexpected,
            ...(window.__authoringQA.exactDraft?.state.unexpected ?? []),
          ],
          accepted: window.__authoringQA.accepted.length,
        }));
        if (
          result.overflow ||
          result.unexpected.length ||
          errors.length ||
          external.length ||
          (["result", "action", "exact-draft"].includes(mode) &&
            result.writes.length)
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
