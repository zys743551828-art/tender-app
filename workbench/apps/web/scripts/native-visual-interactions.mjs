/* global process, console, URL, document, window */
// Limited real App/native API interaction acceptance. No intercepted or mocked API.
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

let input = "";
for await (const piece of process.stdin) input += piece;
const config = JSON.parse(input);
const backend = new URL(config.backend);
assert.equal(backend.hostname, "127.0.0.1");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "native-visual-"));
const evidence = config.journeys.evidence ?? "/evidence";
const cases = [];
const errors = [];
let browser, server, page;
async function screenshot(name) {
  await page.screenshot({ path: path.join(evidence, name + ".png") });
}
async function noPageOverflow() {
  const layout = await page.evaluate(() => ({
    width: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  assert.ok(layout.scrollWidth <= layout.width + 1, JSON.stringify(layout));
}
async function desktopAccountLayout() {
  const layout = await page
    .getByRole("button", { name: "退出登录", exact: true })
    .evaluate((button) => {
      const bounds = button.getBoundingClientRect();
      const footer = button.closest(".account").getBoundingClientRect();
      const avatar = button
        .closest(".account")
        .querySelector(".avatar")
        .getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(button);
      const textRects = [...range.getClientRects()].filter(
        (rect) => rect.width && rect.height,
      );
      return {
        text: button.textContent.trim(),
        textLines: textRects.length,
        button: {
          x: bounds.x,
          y: bounds.y,
          width: bounds.width,
          height: bounds.height,
        },
        insideFooter:
          bounds.left >= footer.left && bounds.right <= footer.right + 1,
        insideViewport:
          bounds.left >= 0 &&
          bounds.top >= 0 &&
          bounds.right <= window.innerWidth &&
          bounds.bottom <= window.innerHeight,
        avatarWidth: avatar.width,
      };
    });
  assert.equal(layout.text, "退出");
  assert.equal(layout.textLines, 1);
  assert.ok(
    layout.insideFooter && layout.insideViewport,
    JSON.stringify(layout),
  );
  assert.ok(layout.avatarWidth >= 29.5, JSON.stringify(layout));
  return layout;
}
try {
  await build({
    stdin: {
      contents: `import React from 'react';import{createRoot}from'react-dom/client';import{App}from'./src/App';import'./src/styles.css';createRoot(document.getElementById('root')).render(<App/>);`,
      resolveDir: root,
      loader: "tsx",
    },
    outfile: path.join(temporary, "app.js"),
    bundle: true,
    format: "esm",
    jsx: "automatic",
    loader: { ".woff2": "file" },
    external: ["/fonts/*"],
    plugins: [
      {
        name: "native-assets",
        setup(builder) {
          builder.onResolve({ filter: /\?url$/ }, (args) => ({
            path: require.resolve(args.path.slice(0, -4)),
            namespace: "asset-url",
          }));
          builder.onLoad(
            { filter: /.*/, namespace: "asset-url" },
            async (args) => {
              const name = path.basename(args.path);
              await fs.copyFile(args.path, path.join(temporary, name));
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
  server = http.createServer(async (request, response) => {
    if (request.url.startsWith("/api/v1/")) {
      const forwarded = http.request(
        new URL(request.url, backend),
        {
          method: request.method,
          headers: { ...request.headers, host: backend.host },
        },
        (upstream) => {
          response.writeHead(upstream.statusCode, upstream.headers);
          upstream.pipe(response);
        },
      );
      forwarded.on("error", () => {
        if (!response.headersSent) response.writeHead(502);
        response.end();
      });
      request.pipe(forwarded);
      return;
    }
    const pathname = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname,
    );
    if (!path.extname(pathname)) {
      response.setHeader("Content-Type", "text/html;charset=utf-8");
      response.end(
        '<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>',
      );
      return;
    }
    const base = pathname.startsWith("/fonts/")
      ? path.join(root, "public")
      : temporary;
    const filename = path.resolve(base, "." + pathname);
    if (!filename.startsWith(path.resolve(base) + path.sep)) {
      response.writeHead(400);
      response.end();
      return;
    }
    try {
      const raw = await fs.readFile(filename);
      response.setHeader(
        "Content-Type",
        filename.endsWith(".js")
          ? "text/javascript"
          : filename.endsWith(".css")
            ? "text/css"
            : filename.endsWith(".woff2")
              ? "font/woff2"
              : "application/octet-stream",
      );
      response.end(raw);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((resolve) =>
    server.listen(config.port, "127.0.0.1", resolve),
  );
  const origin = `http://127.0.0.1:${config.port}`;
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
  });
  page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(origin + "/projects");
  await page.getByRole("heading", { name: "登录投标工作台" }).waitFor();
  await page.getByRole("button", { name: "登录工作区", exact: true }).click();
  assert.equal(
    await page
      .getByLabel("账号", { exact: true })
      .evaluate((el) => el === document.activeElement),
    true,
  );
  await page.getByLabel("账号", { exact: true }).fill(config.journeys.login);
  await page
    .getByLabel("密码", { exact: true })
    .fill("synthetic-wrong-password");
  const denied = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "登录工作区", exact: true }).click();
  assert.equal((await denied).status(), 401);
  await page.getByRole("alert").waitFor();
  await screenshot("visual-login-1280");
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow();
  await screenshot("visual-login-390");
  await page.getByLabel("密码", { exact: true }).fill(config.journeys.password);
  const loggedIn = page.waitForResponse(
    (r) => r.url().endsWith("/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "登录工作区", exact: true }).click();
  assert.equal((await loggedIn).status(), 200);
  await page.getByRole("button", { name: "退出登录", exact: true }).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "退出登录", exact: true }).waitFor();
  cases.push({
    name: "login_validation_failure_retry_and_session_refresh",
    real_http: true,
  });

  const emptyBid = config.journeys.empty_bid;
  await page.goto(`${origin}/bids/${emptyBid}/materials`);
  await page.getByText("已核验文件经确认入库后，会在这里显示。").waitFor();
  await noPageOverflow();
  await page.locator("#project-files").setInputFiles({
    name: "synthetic-empty.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.alloc(0),
  });
  await page.locator(".draft-file").getByText(/0 B/).waitFor();
  await page
    .getByRole("button", { name: "上传并核验原件", exact: true })
    .click();
  await page.getByText(/单文件需大于0且不超过100 MiB/).waitFor();
  await page
    .getByRole("button", { name: "重试未完成的文件", exact: true })
    .click();
  await page.getByText(/单文件需大于0且不超过100 MiB/).waitFor();
  await screenshot("visual-upload-validation-390");
  await page
    .getByRole("button", { name: "移除synthetic-empty.pdf", exact: true })
    .click();
  assert.equal(await page.locator(".draft-file").count(), 0);
  await page.reload();
  await page.getByText("已核验文件经确认入库后，会在这里显示。").waitFor();
  cases.push({
    name: "empty_materials_zero_byte_validation_retry_remove_refresh",
    boundary: "Client validation; no upload or parse worker success claimed",
  });

  await page.goto(`${origin}/bids/${config.bid}/materials`);
  await page.getByText("解析失败", { exact: true }).first().waitFor();
  await page
    .getByText("解析失败", { exact: true })
    .first()
    .scrollIntoViewIfNeeded();
  await screenshot("visual-parse-failure-390");
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto(`${origin}/bids/${emptyBid}/rules`);
  await page.getByRole("heading", { name: "规则核对", exact: true }).waitFor();
  await page.goto(`${origin}/bids/${emptyBid}/review`);
  await page
    .getByRole("heading", { name: "尚未形成评审结果", exact: true })
    .waitFor();
  await screenshot("visual-review-unavailable-1280");
  await page.goto(`${origin}/bids/${config.bid}/review`);
  await page.getByLabel(/^本次评审正文/).selectOption({ index: 1 });
  const unconfigured = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/bids/${config.bid}/reviews`) &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "开始评审所选正文", exact: true })
    .click();
  const refused = await unconfigured;
  assert.equal(refused.status(), 503);
  assert.equal((await refused.json()).code, "MODEL_NOT_CONFIGURED");
  await page.getByText("尚未配置DeepSeek凭据", { exact: true }).waitFor();
  await screenshot("visual-model-unconfigured-1280");
  cases.push({
    name: "seeded_failed_parse_and_empty_review_remain_unqualified",
    boundary:
      "Failed parse is a persisted synthetic fixture, not a parser execution",
  });

  await page.goto(`${origin}/bids/${emptyBid}/settings`);
  const otherSettingsBefore = await (
    await context.request.get(`${origin}/api/v1/bids/${config.bid}/settings`)
  ).json();
  const pricing = page.getByRole("switch", { name: /报价辅助/ });
  await pricing.waitFor();
  const before = await pricing.isChecked();
  await pricing.setChecked(!before);
  const saved = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/bids/${emptyBid}/settings`) &&
      r.request().method() === "PATCH",
  );
  let writes = 0;
  const countWrite = (request) => {
    if (
      request.method() === "PATCH" &&
      request.url().endsWith(`/bids/${emptyBid}/settings`)
    )
      writes++;
  };
  page.on("request", countWrite);
  await page.locator(".settings-panel form").evaluate((form) => {
    form.requestSubmit();
    form.requestSubmit();
  });
  assert.equal((await saved).status(), 200);
  await page.getByText("设置已保存；已有关键风险和历史报告保留。").waitFor();
  assert.equal(writes, 1);
  const otherSettingsAfter = await (
    await context.request.get(`${origin}/api/v1/bids/${config.bid}/settings`)
  ).json();
  assert.deepEqual(otherSettingsAfter, otherSettingsBefore);
  page.off("request", countWrite);
  await page.reload();
  await pricing.waitFor();
  assert.equal(await pricing.isChecked(), !before);
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow();
  await page.locator(".settings-panel").scrollIntoViewIfNeeded();
  await screenshot("visual-settings-390");
  await page.getByLabel(/^当前工作区/).selectOption("materials");
  await page.waitForURL(/\/materials$/);
  await page.goBack();
  await pricing.waitFor();
  await page.goForward();
  await page.waitForURL(/\/materials$/);
  await context.setOffline(true);
  await page.getByLabel(/^当前工作区/).selectOption("settings");
  await page.locator(".settings-panel").getByRole("alert").waitFor();
  await page.locator(".settings-panel").scrollIntoViewIfNeeded();
  await screenshot("visual-offline-retry-390");
  await context.setOffline(false);
  await page
    .locator(".settings-panel")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await pricing.waitFor();
  assert.equal(await pricing.isChecked(), !before);
  cases.push({
    name: "settings_single_write_other_project_unchanged_refresh_history_offline_retry",
    writes,
  });

  await page.goto(`${origin}/bids/${emptyBid}/authoring`);
  const management = page.locator(".authoring-draft-management details");
  await management.waitFor();
  if (!(await management.evaluate((el) => el.open)))
    await management.locator("summary").click();
  await page.getByLabel("新正文草稿名称", { exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole("button", { name: "创建正文草稿", exact: true })
      .isDisabled(),
    true,
  );
  await page
    .getByLabel("新正文草稿名称", { exact: true })
    .fill("合成视觉验收正文");
  const draftResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/bids/${emptyBid}/drafts`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "创建正文草稿", exact: true }).click();
  assert.equal((await draftResponse).status(), 201);
  await page.waitForURL(/draft=/);
  const draftId = new URL(page.url()).searchParams.get("draft");
  const editor = page.getByRole("textbox", { name: "章节正文", exact: true });
  await editor.waitFor();
  // The real snapshot qualification check deliberately mounts a read-only
  // editor first. Wait for its current admission; do not bypass that guard.
  await page.waitForFunction(
    () =>
      document
        .querySelector('[aria-label="章节正文"]')
        ?.getAttribute("contenteditable") === "true",
  );
  const saveSection = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/drafts/${draftId}`) &&
      r.request().method() === "PATCH",
  );
  saveSection.catch(() => {});
  await editor.fill("合成验收章节正文：仅验证人工编辑与保存，不代表投标依据。");
  await page.getByRole("button", { name: "立即保存", exact: true }).click();
  assert.equal((await saveSection).status(), 200);
  const buildPanel = page.getByRole("region", {
    name: "生成文件版本",
    exact: true,
  });
  await buildPanel.waitFor();
  for (const checkbox of await buildPanel.getByRole("checkbox").all())
    await checkbox.uncheck();
  assert.equal(
    await buildPanel
      .getByRole("button", { name: "保存确认后生成文件", exact: true })
      .isDisabled(),
    true,
  );
  await buildPanel.getByRole("checkbox", { name: "Word", exact: true }).check();
  await page.waitForFunction(
    () =>
      document.querySelector(".authoring-builds button.button.primary")
        ?.disabled === false,
  );
  assert.equal(
    await buildPanel
      .getByRole("button", { name: "保存确认后生成文件", exact: true })
      .isDisabled(),
    false,
  );
  assert.equal(await buildPanel.getByRole("link", { name: /下载/ }).count(), 0);
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page
    .getByRole("button", { name: "章节目录与计划", exact: true })
    .waitFor();
  await page
    .getByRole("button", { name: "章节目录与计划", exact: true })
    .click();
  await page.getByRole("button", { name: "收起目录", exact: true }).waitFor();
  await page.keyboard.press("Escape");
  assert.equal(
    await page
      .getByRole("button", { name: "章节目录与计划", exact: true })
      .getAttribute("aria-expanded"),
    "false",
  );
  assert.equal(
    await page
      .getByRole("button", { name: "章节目录与计划", exact: true })
      .evaluate((el) => el === document.activeElement),
    true,
  );
  const accountLayout = await desktopAccountLayout();
  await screenshot("visual-authoring-1280");
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "章节目录与计划", exact: true })
    .click();
  const directoryDialog = page.getByRole("dialog", {
    name: "章节目录与编写计划",
    exact: true,
  });
  await directoryDialog.waitFor();
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await directoryDialog.evaluate((el) => el.contains(document.activeElement)),
    true,
  );
  await noPageOverflow();
  await screenshot("visual-directory-dialog-390");
  await page.keyboard.press("Escape");
  assert.equal(
    await page
      .getByRole("button", { name: "章节目录与计划", exact: true })
      .evaluate((el) => el === document.activeElement),
    true,
  );
  const draftUrl = page.url();
  await page.reload();
  await page
    .getByRole("button", { name: "章节目录与计划", exact: true })
    .waitFor();
  assert.equal(page.url(), draftUrl);
  assert.ok((await editor.innerText()).includes("合成验收章节正文"));
  cases.push({
    name: "draft_validation_real_edit_save_export_guard_directory_escape_and_refresh",
    desktop_account_layout: accountLayout,
    boundary:
      "No build worker/export success claimed; only current export controls inspected",
  });

  const anonymous = await browser.newContext();
  const deniedApi = await anonymous.request.get(
    `${origin}/api/v1/bids/${emptyBid}/settings`,
  );
  assert.equal(deniedApi.status(), 401);
  await anonymous.close();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.getByRole("heading", { name: "登录投标工作台" }).waitFor();
  await page.reload();
  await page.getByRole("heading", { name: "登录投标工作台" }).waitFor();
  cases.push({
    name: "unauthenticated_isolation_and_logout_refresh",
    status: deniedApi.status(),
  });
  assert.deepEqual(errors, []);
  const report = {
    cases: [{ name: "limited_visual_interactions", checks: cases }],
    page_errors: errors,
    api_mocking: false,
    real_app: true,
  };
  await fs.writeFile(
    path.join(evidence, "visual-interactions.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} catch (error) {
  if (page) {
    await screenshot("visual-failure").catch(() => {});
    await fs
      .writeFile(
        path.join(evidence, "visual-failure-body.txt"),
        await page.locator("body").innerText(),
      )
      .catch(() => {});
  }
  await fs.writeFile(
    path.join(evidence, "visual-interactions-failure.json"),
    JSON.stringify(
      { completed: cases, error: error.message, page_errors: errors },
      null,
      2,
    ),
  );
  throw error;
} finally {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
  await fs.rm(temporary, { recursive: true, force: true });
}
