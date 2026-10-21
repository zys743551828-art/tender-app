/* global process, URL, console, document, innerWidth, getComputedStyle */
// Actual app shell/editor; synthetic data and a visual component gallery only.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/tmp/tender-theme-browser");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./src/App";
import { ThemePicker } from "./src/ThemePicker";
import { useTheme } from "./src/theme";
import { SourceEditor } from "./src/SourceEditor";
import { editorSchema } from "./src/editorSchema";
import { TextChangePreview } from "./src/TextChangePreview";
import "./src/styles.css";
const auth = {member:{id:"00000000-0000-4000-8000-000000000001",display_name:"合成验收账号",active:true},csrf_token:"synthetic-not-a-credential",expires_at:"2030-01-01T00:00:00Z"};
window.fetch = async (url) => {
  const route = new URL(url, location.origin).pathname;
  if(route === "/api/v1/auth/session") return new Response(JSON.stringify(location.search.includes("login")?{code:"UNAUTHENTICATED",message:"合成登录页面"}:auth),{status:location.search.includes("login")?401:200,headers:{"Content-Type":"application/json"}});
  if(route === "/api/v1/bids") return new Response(JSON.stringify({items:[],next_cursor:null,has_more:false}),{headers:{"Content-Type":"application/json"}});
  throw new Error("Unconfigured synthetic route: "+route);
};
function Gallery(){
 const theme=useTheme();
 const [value,setValue]=useState(()=>editorSchema.nodeFromJSON({type:"doc",attrs:{title:"合成章节",ordinal:1,rule_ids:[],source_refs:[]},content:[{type:"heading",attrs:{id:"00000000-0000-4000-8000-000000000002",level:2},content:[{type:"text",text:"施工安排"}]},{type:"paragraph",attrs:{id:"00000000-0000-4000-8000-000000000003"},content:[{type:"text",text:"合成界面验收：工期90日，混凝土C30。主题切换不更改正文。"}]}]}));
 return <main className="page-content" style={{maxWidth:1100}}><header className="section-heading"><div><h1>工作界面外观核对</h1><p>合成页面：真实编辑组件，状态卡与表格为视觉样例。</p></div><ThemePicker {...theme}/></header>
 <section className="panel" style={{padding:20,marginBottom:16}}><h2>可读状态与操作</h2><div style={{display:"flex",flexWrap:"wrap",gap:12,marginTop:16}}><button className="button primary">主要操作</button><button className="button secondary">次要操作</button><button className="button danger">危险操作</button></div><p className="notice error">原件未取得：请恢复连接后重试。</p><p className="notice warning">仍有条款待核对；本次输入保持原样。</p><p className="notice neutral">技术满分未知；数值结果保持空白。</p><div className="assistant-message role-assistant"><div className="assistant-message-heading">AI建议 · 尚未采用</div><p>建议核对工期和进度表；正式决定需明确确认。</p></div></section>
 <section className="panel" style={{padding:20,marginBottom:16}}><h2>章节正文</h2><SourceEditor value={value} onChange={setValue} onTarget={()=>{}}/><details><summary>核对差异与表格</summary><TextChangePreview before="工期90日。原文保留。👩🏽‍🔧" after="工期90日，分三阶段。原文保留。👩🏽‍🔧"/><table className="data-table"><thead><tr><th>项目</th><th>原值</th><th>来源</th></tr></thead><tbody><tr><td>工期</td><td>90</td><td>物理页1</td></tr><tr><td>技术满分</td><td>未知</td><td>尚未取得</td></tr></tbody></table></details></section>
 <section className="panel" style={{padding:20}}><h2>原件阅读区域</h2><p>此处只核对界面背景；不是PDF解析或版式验收。</p><div className="pdf-canvas-container"><canvas aria-label="合成纸张色样" width="260" height="100"/></div></section></main>
}
createRoot(document.getElementById("root")).render(location.pathname==="/gallery"?<Gallery/>:<App/>);
`;
await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  format: "esm",
  jsx: "automatic",
  outdir: out,
  entryNames: "app",
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
await fs.copyFile(
  path.join(root, "public/theme.js"),
  path.join(out, "theme.js"),
);
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>主题合成验收</title><script src="/theme.js"></script><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
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
    const dir = name.startsWith("/fonts/") ? path.join(root, "public") : out;
    const requested = path.extname(name) ? name : "/index.html";
    const target = path.resolve(dir, "." + requested);
    if (!target.startsWith(dir + path.sep)) throw Error("outside");
    res.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(await fs.readFile(target));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
const receipt = {
  kind: "synthetic-theme-browser",
  real_database: false,
  provider_calls: 0,
  cases: [],
  contrast: [],
  text_comparisons: [],
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
      colorScheme: "light",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    for (const surface of ["login", "projects", "gallery"]) {
      await page.goto(
        `http://127.0.0.1:${server.address().port}/${surface === "gallery" ? "gallery" : surface === "login" ? "?login=1" : "projects"}`,
      );
      const selector = page.getByLabel("外观主题", { exact: true });
      await selector.waitFor();
      for (const theme of ["light", "dark"]) {
        await selector.selectOption(theme);
        await page.locator(`html[data-theme="${theme}"]`).waitFor();
        if (surface === "gallery")
          await page.getByText("核对差异与表格", { exact: true }).click();
        const layout = await page.evaluate(() => ({
          width: innerWidth,
          scroll: document.documentElement.scrollWidth,
          outside: [
            ...document.querySelectorAll("input,select,textarea,button"),
          ].filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && (r.left < -1 || r.right > innerWidth + 1);
          }).length,
          theme: document.documentElement.dataset.theme,
        }));
        if (layout.scroll > width + 1 || layout.outside || errors.length)
          throw Error(
            JSON.stringify({ surface, theme, width, layout, errors }),
          );
        await page.screenshot({
          path: path.join(out, `${surface}-${theme}-${width}.png`),
        });
        if (surface === "gallery") {
          const before = page.locator(".text-change-preview__before pre"),
            after = page.locator(".text-change-preview__after pre");
          if (
            (await before.textContent()) !== "工期90日。原文保留。👩🏽‍🔧" ||
            (await after.textContent()) !== "工期90日，分三阶段。原文保留。👩🏽‍🔧"
          )
            throw Error("comparison text changed or truncated");
          if (width <= 760) {
            if ((await before.isVisible()) || !(await after.isVisible()))
              throw Error("mobile comparison must open one proposal pane");
            await page
              .getByRole("button", { name: "修改前", exact: true })
              .focus();
            await page.keyboard.press("Enter");
            if (!(await before.isVisible()) || (await after.isVisible()))
              throw Error("keyboard did not switch to full original");
            await page
              .getByRole("button", { name: "拟修改后", exact: true })
              .click();
          } else if (
            !(await before.isVisible()) ||
            !(await after.isVisible())
          ) {
            throw Error("desktop must show both comparison panes");
          }
          receipt.text_comparisons.push({
            width,
            theme,
            full_text_preserved: true,
            mobile_single_pane: width <= 760,
            keyboard_switch: width <= 760,
          });
          const contrast = await page.evaluate(() => {
            const root = document.documentElement,
              css = getComputedStyle(root);
            function rgb(value) {
              const el = document.createElement("span");
              el.style.color = value;
              document.body.append(el);
              const result = getComputedStyle(el)
                .color.match(/[\d.]+/g)
                .slice(0, 3)
                .map(Number);
              el.remove();
              return result;
            }
            function lum(color) {
              return rgb(color)
                .map((x) => {
                  x /= 255;
                  return x <= 0.04045
                    ? x / 12.92
                    : ((x + 0.055) / 1.055) ** 2.4;
                })
                .reduce((a, x, i) => a + x * [0.2126, 0.7152, 0.0722][i], 0);
            }
            const pairs = [
              ["foreground", "background"],
              ["foreground", "card"],
              ["muted-foreground", "card"],
              ["muted-foreground", "background"],
              ["primary-foreground", "primary"],
              ["danger-foreground", "danger-soft"],
              ["warning-foreground", "warning-soft"],
              ["success-foreground", "success-soft"],
              ["ai-foreground", "ai-soft"],
            ];
            return {
              pairs: pairs.map(([front, back]) => {
                const a = lum(css.getPropertyValue("--" + front)),
                  b = lum(css.getPropertyValue("--" + back));
                return {
                  front,
                  back,
                  ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
                };
              }),
              paper: getComputedStyle(document.querySelector("canvas"))
                .backgroundColor,
              filter: getComputedStyle(document.querySelector("canvas")).filter,
            };
          });
          if (
            contrast.pairs.some((x) => x.ratio < 4.5) ||
            contrast.paper !== "rgb(255, 255, 255)" ||
            contrast.filter !== "none"
          )
            throw Error(JSON.stringify({ theme, contrast }));
          if (width === 1280) receipt.contrast.push({ theme, ...contrast });
          await page.getByText("核对差异与表格", { exact: true }).click();
        }
        receipt.cases.push({
          width,
          surface,
          theme,
          horizontal_overflow: false,
          page_errors: errors.slice(),
        });
      }
      await page.reload();
      await page.locator('html[data-theme="dark"]').waitFor();
      await page.getByLabel("外观主题").waitFor();
      if ((await page.getByLabel("外观主题").inputValue()) !== "dark")
        throw Error("saved theme lost");
      await page.getByLabel("外观主题").selectOption("system");
      await page.locator('html[data-theme="light"]').waitFor();
      await page.emulateMedia({ colorScheme: "dark" });
      await page.locator('html[data-theme="dark"]').waitFor();
      await page.emulateMedia({ colorScheme: "light" });
      await page.locator('html[data-theme="light"]').waitFor();
    }
    await context.close();
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
