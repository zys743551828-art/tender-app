/* global process, URL, console, window, document, innerWidth, Event */
// Real authoring/assistant/workspace components, explicit synthetic HTTP only.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-authoring-layout-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
await fs.mkdir(out, { recursive: true });
const entry = `
import React, { useCallback, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ProjectWorkspace } from "./src/ProjectWorkspace";
import { NavigationGuardContext } from "./src/navigationGuard";
import { ThemePicker } from "./src/ThemePicker";
import { useTheme } from "./src/theme";
import { setAuth } from "./src/api";
import { authoringLayoutFixture, layoutScope } from "./src/authoringLayoutFixtures.test-support";
import "./src/styles.css";
const fixture = authoringLayoutFixture();
window.__layoutQA = fixture;
window.fetch = fixture.fetcher;
setAuth({ member: { id: layoutScope.memberId, display_name: "合成验收账号", active: true }, csrf_token: "synthetic-not-a-credential", expires_at: "2099-01-01T00:00:00Z" });
function Harness() {
  const theme = useTheme();
  const [route, setRoute] = useState("/bids/" + layoutScope.bidId + "/authoring?draft=" + layoutScope.draftId);
  const guards = useRef(new Set());
  const register = useCallback((guard) => { guards.current.add(guard); return () => guards.current.delete(guard); }, []);
  const navigate = async (page, draft) => { for (const guard of guards.current) if (!(await guard())) return; setRoute("/bids/" + layoutScope.bidId + "/" + page + (draft ? "?draft=" + draft : "")); };
  return <NavigationGuardContext.Provider value={register}><div className="app-shell">
    <aside className="sidebar"><strong>投标工作台</strong><p>合成布局验收</p><p>真实界面组件，资料与HTTP均为测试夹具。</p></aside>
    <div className="workspace"><header className="topbar"><span>正文与助手 · 合成交互核对</span><ThemePicker {...theme}/></header>
      <main id="main-content"><ProjectWorkspace id={layoutScope.bidId} memberId={layoutScope.memberId} route={route}
        onBack={() => navigate("authoring", layoutScope.draftId)} onNavigate={(page) => navigate(page, page === "authoring" ? layoutScope.draftId : undefined)}
        onOpenDraft={(id) => navigate("authoring", id)} /></main>
    </div></div></NavigationGuardContext.Provider>;
}
createRoot(document.getElementById("root")).render(<Harness/>);
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
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>正文与助手合成布局验收</title><script src="/theme.js"></script><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
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
    const directory = name.startsWith("/fonts/")
      ? path.join(root, "public")
      : out;
    const target = path.resolve(
      directory,
      `.${name === "/" ? "/index.html" : name}`,
    );
    if (!target.startsWith(directory + path.sep))
      throw Error("outside fixture");
    const content = await fs.readFile(target);
    res.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const receipt = {
  scope:
    "Actual ProjectWorkspace, AuthoringPanel, SectionEditor, AssistantDrawer, AssistantWorkspace; explicit synthetic HTTP. No model, original conversion, or business acceptance.",
  cases: [],
  screenshots: [],
  page_errors: [],
};
let browser;
let lastPage;
function assert(value, message) {
  if (!value) throw Error(message);
}
async function screenshot(page, name) {
  const file = name + ".png";
  await page.screenshot({ path: path.join(out, file) });
  receipt.screenshots.push(file);
}
async function checkLayout(page, state) {
  const layout = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    outside: [...document.querySelectorAll("input,select,textarea,button")]
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return (
          el.getClientRects().length > 0 &&
          r.width > 0 &&
          (r.left < -1 || r.right > innerWidth + 1)
        );
      })
      .map((el) =>
        (el.getAttribute("aria-label") ?? el.textContent ?? el.tagName).slice(
          0,
          120,
        ),
      ),
    unexpected: window.__layoutQA.state.unexpected,
  }));
  assert(
    layout.scroll <= layout.width + 1 &&
      !layout.outside.length &&
      !layout.unexpected.length,
    JSON.stringify({ state, layout }),
  );
  return layout;
}
try {
  browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  for (const width of [1440, 1280, 820, 390]) {
    const context = await browser.newContext({
      viewport: { width, height: width === 390 ? 844 : 900 },
      colorScheme: "light",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    lastPage = page;
    page.on("pageerror", (error) => receipt.page_errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.getByLabel("章节正文", { exact: true }).waitFor();
    const initialUnexpected = await page.evaluate(
      () => window.__layoutQA.state.unexpected,
    );
    assert(!initialUnexpected.length, JSON.stringify({ initialUnexpected }));
    assert(
      !(await page
        .locator(".authoring-draft-management details")
        .getAttribute("open")),
      "draft management must start collapsed",
    );
    const bodyTop = await page
      .getByLabel("章节正文", { exact: true })
      .evaluate((el) => el.getBoundingClientRect().top);
    assert(
      bodyTop < (width === 390 ? 744 : 800),
      `body below initial viewport: ${width}/${bodyTop}`,
    );
    for (const theme of ["light", "dark", "system"]) {
      await page.getByLabel("外观主题").selectOption(theme);
      await checkLayout(page, `${width}-${theme}-body`);
      await screenshot(page, `body-${theme}-${width}`);
      const beforeScroll = await page.evaluate(() => window.scrollY);
      await page.getByRole("button", { name: "项目助手", exact: true }).click();
      await page.getByLabel("本次提问", { exact: true }).waitFor();
      const desktop = width >= 1280;
      const assistant = page.getByRole(desktop ? "complementary" : "dialog", {
        name: "项目主会话助手",
      });
      await assistant.waitFor();
      if (desktop) {
        const boxes = await page.evaluate(() => {
          const body = document
            .querySelector('[aria-label="章节正文"]')
            .getBoundingClientRect();
          const panel = document
            .querySelector(".assistant-surface")
            .getBoundingClientRect();
          return {
            bodyRight: body.right,
            panelLeft: panel.left,
            bodyWidth: body.width,
            overflow: document.body.style.overflow,
          };
        });
        assert(
          boxes.bodyRight < boxes.panelLeft &&
            boxes.bodyWidth >= 400 &&
            boxes.overflow !== "hidden",
          JSON.stringify(boxes),
        );
        const divider = page.getByRole("separator", {
          name: "调整助手面板宽度",
        });
        await divider.focus();
        await page.keyboard.press("End");
        const widest = Number(await divider.getAttribute("aria-valuenow"));
        await page.keyboard.press("Home");
        assert(
          Number(await divider.getAttribute("aria-valuenow")) === 340,
          "minimum not applied",
        );
        const handle = await divider.boundingBox();
        await page.mouse.move(handle.x + handle.width / 2, handle.y + 100);
        await page.mouse.down();
        await page.mouse.move(handle.x - 70, handle.y + 100);
        await page.mouse.up();
        const afterDrag = Number(await divider.getAttribute("aria-valuenow"));
        assert(
          afterDrag > 340 && afterDrag <= widest,
          "pointer resize not bounded",
        );
        await page.locator(".chapter-writing input").first().focus();
        assert(
          await page
            .locator(".chapter-writing input")
            .first()
            .evaluate((el) => document.activeElement === el),
          "desktop trapped body focus",
        );
      }
      const closeVisible = await page
        .getByRole("button", { name: "收起助手" })
        .evaluate((el) => {
          const box = el.getBoundingClientRect();
          return box.top >= 0 && box.bottom <= window.innerHeight;
        });
      assert(
        closeVisible,
        "touch close must remain visible while continuing a long conversation",
      );
      await checkLayout(page, `${width}-${theme}-assistant`);
      await screenshot(page, `assistant-${theme}-${width}`);
      await page
        .getByLabel("本次提问", { exact: true })
        .fill("保留未发送的合成提问");
      await page.getByLabel("本次提问", { exact: true }).press("Escape");
      await assistant.waitFor({ state: "detached" });
      assert(
        Math.abs((await page.evaluate(() => window.scrollY)) - beforeScroll) <=
          2,
        "assistant changed task reading position",
      );
      assert(
        await page
          .getByRole("button", { name: "项目助手", exact: true })
          .evaluate((el) => document.activeElement === el),
        "assistant opener focus not restored",
      );
      await page.getByRole("button", { name: "章节目录与计划" }).click();
      const directory = page.getByRole(
        width >= 1280 ? "complementary" : "dialog",
        { name: "章节目录与编写计划" },
      );
      await directory.waitFor();
      await checkLayout(page, `${width}-${theme}-directory`);
      await screenshot(page, `directory-${theme}-${width}`);
      await directory.getByRole("button", { name: "收起目录" }).press("Escape");
      await directory.waitFor({ state: "hidden" });
      assert(
        await page
          .getByRole("button", { name: "章节目录与计划" })
          .evaluate((el) => document.activeElement === el),
        "directory opener focus not restored",
      );
      receipt.cases.push({
        width,
        theme,
        body_top: bodyTop,
        layout: "no whole-page overflow",
        assistant: desktop
          ? "nonmodal bounded side panel"
          : "modal single task",
        focus_restored: true,
      });
    }
    if (width === 1280) {
      await page.getByRole("button", { name: "项目助手", exact: true }).click();
      const question = page.getByLabel("本次提问", { exact: true });
      await question.waitFor();
      assert(
        (await question.inputValue()) === "保留未发送的合成提问",
        "reopening lost unsent question",
      );
      await question.evaluate((el) => {
        window.__layoutQuestion = el;
        window.__layoutBody = document.querySelector('[aria-label="章节正文"]');
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("dialog", { name: "项目主会话助手" }).waitFor();
      assert(
        await question.evaluate(
          (el) =>
            el === window.__layoutQuestion &&
            window.__layoutBody ===
              document.querySelector('[aria-label="章节正文"]'),
        ),
        "resize remounted drafts",
      );
      await page.getByRole("button", { name: "＋ / @ 选择可信来源" }).click();
      const sources = page.getByRole("dialog", { name: "选择本次消息来源" });
      await sources.waitFor();
      await sources.getByLabel("查找来源名称").fill("合成来源查询");
      await checkLayout(page, "compact-source-task");
      await screenshot(page, "sources-compact");
      await sources.getByLabel("查找来源名称").press("Escape");
      await sources.waitFor({ state: "detached" });
      assert(
        (await question.inputValue()) === "保留未发送的合成提问",
        "sources discarded question",
      );
      assert(
        await page
          .getByRole("button", { name: "＋ / @ 选择可信来源" })
          .evaluate((el) => document.activeElement === el),
        "source focus not restored",
      );
      await page.setViewportSize({ width: 1280, height: 900 });
      await page
        .getByRole("complementary", { name: "项目主会话助手" })
        .waitFor();
      assert(
        await question.evaluate((el) => el === window.__layoutQuestion),
        "returning desktop remounted question",
      );
      await page.getByRole("button", { name: "查证资料", exact: true }).click();
      await page.getByRole("dialog", { name: "查找原页依据" }).waitFor();
      assert(
        !(await page
          .getByRole("complementary", { name: "项目主会话助手" })
          .count()),
        "source and assistant both open",
      );
      await page.getByRole("button", { name: "关闭查证" }).press("Escape");
      await page
        .getByRole("dialog", { name: "查找原页依据" })
        .waitFor({ state: "detached" });
      assert(
        await page
          .getByRole("button", { name: "查证资料", exact: true })
          .evaluate((el) => document.activeElement === el),
        "retrieval focus not restored",
      );
      receipt.cases.push({
        workflow:
          "resize desktop/390/desktop, source task, retrieval exclusion",
        same_draft_nodes: true,
        unsent_text_preserved: true,
      });
    }
    if (width === 390) {
      await page.evaluate(() => {
        window.__layoutQA.state.saveMode = "offline";
      });
      const title = page.locator(".chapter-writing input").first();
      await title.fill("合成待保存内容：不得因目录切换丢失");
      await page.getByRole("button", { name: "章节目录与计划" }).click();
      const directory = page.getByRole("dialog", {
        name: "章节目录与编写计划",
      });
      await directory.getByRole("button", { name: /质量保障措施/ }).click();
      await directory.getByText(/本章保存尚未确认，未切换章节/).waitFor();
      await screenshot(page, "directory-save-failure-390");
      assert(
        (await title.inputValue()) === "合成待保存内容：不得因目录切换丢失",
        "failed save lost local draft",
      );
      const blocked = await page.evaluate(() => {
        const event = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(event);
        return event.defaultPrevented;
      });
      assert(blocked, "pending draft no longer protects navigation");
      await directory.getByRole("button", { name: "收起目录" }).press("Escape");
      await page.evaluate(() => {
        window.__layoutQA.state.saveMode = "ok";
      });
      await page.getByRole("button", { name: "重试保存" }).click();
      await page.getByText(/已保存 · 章节修订 2/).waitFor();
      const save = await page.evaluate(() => ({
        writes: window.__layoutQA.state.writes,
        applied: window.__layoutQA.state.appliedSaves,
      }));
      assert(
        save.applied === 1 &&
          JSON.stringify(save.writes[0]) === JSON.stringify(save.writes[1]),
        "save did not retry original key/body/tag",
      );
      await page.getByRole("button", { name: "章节目录与计划" }).click();
      await directory.getByRole("button", { name: /质量保障措施/ }).click();
      await directory.waitFor({ state: "hidden" });
      await page.waitForFunction(
        () =>
          document.querySelector(".chapter-writing input")?.value ===
          "质量保障措施",
      );
      await checkLayout(page, "after-recovered-chapter-switch");
      receipt.cases.push({
        workflow:
          "failed save -> denied chapter switch -> explicit original-key recovery -> chapter switch",
        pending_navigation_protected: true,
        applied_saves: save.applied,
      });
    }
    await context.close();
  }
  assert(!receipt.page_errors.length, JSON.stringify(receipt.page_errors));
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      passed: receipt.cases.length,
      screenshots: receipt.screenshots.length,
      receipt: path.join(out, "receipt.json"),
    }),
  );
} catch (error) {
  if (lastPage && !lastPage.isClosed()) {
    await lastPage.screenshot({ path: path.join(out, "failure.png") });
    receipt.last_state = await lastPage.evaluate(() => ({
      unexpected: window.__layoutQA?.state.unexpected,
      text: document.body.innerText.slice(0, 1800),
    }));
  }
  await fs.writeFile(
    path.join(out, "failure.json"),
    JSON.stringify({ message: error.message, ...receipt }, null, 2) + "\n",
  );
  throw error;
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
