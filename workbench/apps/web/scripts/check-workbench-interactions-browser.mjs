/* global console, document, getComputedStyle, innerWidth, NodeFilter, process */
// Real app on loopback, with synthetic projects and a synthetic session.
import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { createRequire } from "node:module";
import { setTimeout } from "node:timers/promises";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const engine = process.argv[2] ?? "chromium";
assert(["chromium", "webkit"].includes(engine), "Use chromium or webkit");
const suite = process.argv[3] ?? "all";
assert(
  ["all", "mobile", "desktop"].includes(suite),
  "Use all, mobile or desktop",
);
const require = createRequire(import.meta.url);
const browserType = require(process.env.PLAYWRIGHT_MODULE ?? "playwright")[
  engine
];
const empty = { items: [], has_more: false, next_cursor: null };
const titles = [
  "合成项目甲 · 施工组织与现场管理",
  "合成项目乙 · 道路及排水工程",
];
const bids = titles.map((title, index) => {
  const id = `20000000-0000-4000-8000-00000000000${index + 1}`;
  return {
    id,
    title,
    phase: "working",
    material_revision: index + 1,
    current_body_id: null,
    current_review_id: null,
    stream_id: null,
    next_action: {
      action: "upload_materials",
      reason: "核对合成资料",
      target_url: `/bids/${id}/materials`,
      blocked: false,
    },
  };
});
const reason = "核对尚未冻结的解析身份";
const summaries = bids.map((bid) => ({
  bid_id: bid.id,
  phase: bid.phase,
  archived_at: null,
  package_counts: { authority: 2, bid: 1 },
  head_members: { total: 5, parse_not_frozen: 1 },
  next_action: {
    action: "inspect_package_parses",
    reason,
    target_url: `/bids/${bid.id}/packages`,
    blocked: true,
  },
  action_scope: "package_directory",
  risk_status: "not_evaluated",
  critical_risk_count: null,
  other_risk_count: null,
  prediction_status: "not_evaluated",
  predicted_score: null,
  inventory_complete: false,
  formal_scoring_eligible: false,
  submission_eligible: false,
}));
const app = await createServer({
  configFile: false,
  root: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [react()],
  server: { host: "127.0.0.1", hmr: false },
});

function fixture(path, query) {
  if (path === "/auth/session") {
    return {
      member: {
        id: "responsive-test",
        display_name: "合成验收账号",
        active: true,
      },
      csrf_token: "responsive-test-only",
      expires_at: "2099-01-01T00:00:00Z",
    };
  }
  if (path === "/bids") return { ...empty, items: bids };
  if (path === "/history") return empty;
  if (path === "/project-work-summaries")
    return {
      version: "project-work-summary/1",
      observed_at: "2026-11-20T00:00:00Z",
      items: query
        .getAll("bid_id")
        .map((id) => summaries.find((item) => item.bid_id === id)),
    };
  const bid = bids.find((item) => path.startsWith(`/bids/${item.id}`));
  if (!bid) return null;
  const suffix = path.slice(`/bids/${bid.id}`.length);
  if (suffix === "") return bid;
  if (suffix === "/review-state")
    return { bid_id: bid.id, request: null, current_review: null };
  if (suffix === "/settings")
    return { bid_id: bid.id, settings: { pricing: false } };
  if (suffix === "/upload-batches" || suffix === "/upload-batches/batch-qa") {
    const batch = {
      id: "batch-qa",
      bid_id: bid.id,
      revision: 1,
      state: "open",
      uploads: [
        { id: "upload-qa", filename: "合成续传原件.pdf", state: "authorized" },
      ],
    };
    return suffix === "/upload-batches" ? { ...empty, items: [batch] } : batch;
  }
  if (suffix === "/materials")
    return {
      documents: [
        {
          id: "synthetic-version",
          bid_id: bid.id,
          file_id: "synthetic-file",
          file_head_version_id: "synthetic-version",
          file_revision: 1,
          file_head_revision: 1,
          previous_version_id: null,
          source_relation: null,
          role: "tender",
          artifact_kind: "source_original",
          filename: `合成工程管网施工标段-${"DWG20261121REV".repeat(5)}-补充说明.pdf`,
          byte_size: 8192,
          sha256: "a".repeat(64),
          media_type: "application/pdf",
          obtained_at: "2026-11-21T00:00:00Z",
          parse_coverage: "partial",
        },
      ],
      conflicts: [],
    };
  if (suffix === "/package-documents" || suffix === "/packages") return empty;
  return null;
}

function heading(page, name) {
  return page.getByRole("heading", { name, exact: true });
}

async function hitTarget(locator, minimum = 0) {
  await locator.waitFor();
  const rect = await locator.evaluate((el) => {
    const { x, y, width, height } = el.getBoundingClientRect();
    const hit = [x + 2, x + width / 2, x + width - 2].every((point) =>
      el.contains(document.elementFromPoint(point, y + height / 2)),
    );
    return { width, height, hit };
  });
  const label =
    (await locator.getAttribute("aria-label")) ??
    (await locator.textContent()).trim();
  assert(rect.hit, `${label} is clipped or covered`);
  assert(
    rect.width >= minimum && rect.height >= minimum,
    `${label} measures ${Math.round(rect.width)}×${Math.round(rect.height)}px, need ${minimum}px`,
  );
}

async function checkVisibleText(locator) {
  const visible = await locator.evaluate((el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    const boxes = [];
    while (walker.nextNode()) {
      if (!walker.currentNode.textContent.trim()) continue;
      range.selectNodeContents(walker.currentNode);
      boxes.push(...range.getClientRects());
    }
    return (
      boxes.length > 0 &&
      boxes.every(({ left, right, top, height }) =>
        [left + 1, right - 1].every((x) =>
          el.contains(document.elementFromPoint(x, top + height / 2)),
        ),
      )
    );
  });
  assert(
    visible,
    `${(await locator.textContent()).trim()} text is clipped or covered`,
  );
}

async function checkFocus(locator) {
  assert(
    await locator.evaluate(
      (el) =>
        el === document.activeElement &&
        el.matches(":focus-visible") &&
        getComputedStyle(el).outlineStyle !== "none",
    ),
    "Expected visible keyboard focus",
  );
}

async function checkMaterialRow(page) {
  await page.goto(new URL(`/bids/${bids[0].id}/materials`, page.url()).href);
  const row = page.locator(".materials-panel tbody tr");
  const action = row.getByRole("button", { name: "查看原件与依据" });
  await action.scrollIntoViewIfNeeded();
  await hitTarget(action);
  for (const label of [row.locator("td").nth(1), action]) {
    const lines = await label.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el.firstChild);
      return range.getClientRects().length;
    });
    assert.equal(
      lines,
      1,
      `Short material label wraps: ${await label.innerText()}`,
    );
  }
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  );
  await action.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await checkFocus(action);
  await checkVisibleText(action);
}

async function checkFilePickers(page) {
  await page.goto(new URL(`/bids/${bids[0].id}/materials`, page.url()).href);
  await page
    .getByRole("button", { name: "查找本项目已保存的上传批次" })
    .click();
  await page.getByRole("button", { name: "切换到此批次继续核对" }).click();
  const resume = page.getByLabel("重新选择合成续传原件.pdf的原文件以接续上传");
  const mainPicker = page.getByLabel("选择需要上传的资料");
  for (const input of [resume, mainPicker]) {
    await input.scrollIntoViewIfNeeded();
    await hitTarget(input, 38);
    await input.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    for (const forcedColors of engine === "chromium"
      ? ["none", "active"]
      : ["none"]) {
      await page.emulateMedia({ forcedColors });
      assert(
        await input.evaluate((el) => {
          const box = el.getBoundingClientRect();
          const face = el.nextElementSibling;
          const visual = face.getBoundingClientRect();
          return (
            el === document.activeElement &&
            el.matches(":focus-visible") &&
            getComputedStyle(el).opacity === "0" &&
            getComputedStyle(face).outlineStyle === "solid" &&
            parseFloat(getComputedStyle(face).outlineWidth) >= 2 &&
            Math.abs(box.width - visual.width) < 1 &&
            Math.abs(box.height - visual.height) < 1
          );
        }),
        "Native file chooser must cover its styled, visibly focused button",
      );
    }
    await page.emulateMedia({ forcedColors: "none" });
  }
  const resumeFace = page.locator(".resume-file .file-picker-control");
  const status = page.getByRole("button", { name: "查询已收到的传输状态" });
  const [a, b] = await Promise.all([
    resumeFace.boundingBox(),
    status.boundingBox(),
  ]);
  assert(
    Math.abs(a.height - b.height) <= 1,
    "Resume and status buttons have different heights",
  );
  assert(
    Math.abs(a.y - b.y) <= 1,
    "Resume and status buttons should fit on the same row",
  );
  const [resumeChooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.locator(".batch-file label.resume-file").click(),
  ]);
  assert.equal(await resumeChooser.isMultiple(), false);
  const name = `合成附件-${"DWG-REVISION-QA-".repeat(8)}.pdf`;
  const file = {
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nSynthetic fixture"),
  };
  let finishRead;
  const reading = new Promise((resolve) => {
    finishRead = resolve;
  });
  await page.route("**/api/v1/uploads/upload-qa/layout", async (route) => {
    await reading;
    await route.fulfill({
      status: 503,
      json: { code: "QA_RETRY", message: "合成批次暂时无法读取" },
    });
  });
  try {
    await resumeChooser.setFiles(file);
    await page.locator("#project-files:disabled").waitFor();
    assert(await resume.isDisabled());
    assert(
      await resume.evaluate(
        (el) => parseFloat(getComputedStyle(el.nextElementSibling).opacity) < 1,
      ),
    );
    if (engine === "chromium") {
      await page.emulateMedia({ forcedColors: "active" });
      assert(
        await resume.evaluate((el) => {
          const face = getComputedStyle(el.nextElementSibling);
          return face.opacity === "1" && face.color === face.borderTopColor;
        }),
        "Disabled chooser must remain visible in forced colors",
      );
      await page.emulateMedia({ forcedColors: "none" });
    }
  } finally {
    finishRead();
  }
  await page
    .getByRole("alert")
    .filter({ hasText: "合成批次暂时无法读取" })
    .waitFor();
  const selection = page.locator(".resume-file .file-picker-selection");
  assert.equal(await selection.innerText(), `已选择：${name}`);
  assert(
    await selection.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    "Selected resume filename overflows",
  );
  await mainPicker.focus();
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.keyboard.press("Enter"),
  ]);
  assert.equal(await chooser.isMultiple(), true);
  await chooser.setFiles(file);
  await page.getByText("当前列表有 1 项资料").waitFor();
  const filename = page
    .locator(".draft-file .file-summary strong")
    .filter({ hasText: name });
  await filename.scrollIntoViewIfNeeded();
  assert(
    await filename.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    "File name overflows its row",
  );
  const draft = page.locator(".draft-file-actions");
  const add = draft.getByRole("button", { name: `为${name}添加另一用途` });
  const remove = draft.getByRole("button", { name: `移除${name}` });
  const [first, last] = await Promise.all([
    add.boundingBox(),
    remove.boundingBox(),
  ]);
  assert(
    Math.abs(first.y + first.height / 2 - last.y - last.height / 2) <= 1,
    "Draft file actions are misaligned",
  );
  await remove.click();
  await filename.waitFor({ state: "detached" });
  assert.equal(
    await page.locator(".file-drop .file-picker-selection").innerText(),
    "",
  );
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  );
}

async function scrollAcross(page, scroller, forward) {
  const box = await scroller.boundingBox();
  const left = Math.round(box.x + 22);
  const right = Math.round(box.x + box.width - 76);
  const y = Math.round(box.y + 65);
  if (engine === "webkit") {
    // Playwright's mobile WebKit supports taps but offers neither swipe nor wheel input.
    await scroller.evaluate(
      (el, direction) => el.scrollBy(direction * el.clientWidth, 0),
      forward ? 1 : -1,
    );
    return;
  }
  const cdp = await page.context().newCDPSession(page);
  const start = forward ? right : left;
  const end = forward ? left : right;
  async function send(type, x) {
    await cdp.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: x === undefined ? [] : [{ x, y }],
    });
  }
  try {
    await send("touchStart", start);
    for (let step = 1; step <= 8; step++) {
      await send("touchMove", start + ((end - start) * step) / 8);
      await setTimeout(20);
    }
    await send("touchEnd");
  } finally {
    await cdp.detach();
  }
}

async function checkTable(page) {
  const scroller = page.getByRole("region", { name: "全部项目" });
  const table = scroller.getByRole("table");
  const row = table.getByRole("row").nth(1);
  const open = row.getByRole("button", {
    name: `打开${titles[0]}`,
    exact: true,
  });
  await row.getByText(reason, { exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready.then(() => {}));
  assert.deepEqual(await table.getByRole("columnheader").allTextContents(), [
    "项目名称",
    "工作阶段",
    "整包资料",
    "工作下一步",
    "打开",
  ]);
  const width = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  assert.equal(width.page, width.viewport, "table overflow must remain local");
  const initialX = (await open.boundingBox()).x;
  await hitTarget(open);
  const scrollLeft = () => scroller.evaluate((el) => el.scrollLeft);
  await scrollAcross(page, scroller, true);
  await page.waitForFunction(
    () => document.querySelector(".project-list .table-wrap").scrollLeft > 75,
  );
  assert(
    Math.abs((await open.boundingBox()).x - initialX) <= 1,
    "Open action moved on swipe",
  );
  for (const label of [titles[0], "工作中", "依据包 2 · 投标包 1", reason]) {
    const entry = row.getByText(label, { exact: true });
    await entry.evaluate((el) =>
      el.scrollIntoView({ block: "nearest", inline: "center" }),
    );
    await checkVisibleText(entry);
  }
  const far = await scrollLeft();
  await scrollAcross(page, scroller, false);
  await page.waitForFunction(
    (offset) =>
      document.querySelector(".project-list .table-wrap").scrollLeft <
      offset - 60,
    far,
  );
  assert(
    Math.abs((await open.boundingBox()).x - initialX) <= 1,
    "Open action moved on return swipe",
  );
  await hitTarget(open, 44);
  await scroller.evaluate((el) => {
    el.scrollLeft = el.scrollWidth;
  });
  await scroller.focus();
  await page.keyboard.press("Tab");
  const project = row.getByRole("button", { name: titles[0], exact: true });
  await checkFocus(project);
  await checkVisibleText(project);
  await scroller.evaluate((el) => {
    el.scrollLeft = el.scrollWidth;
  });
  await hitTarget(open, 44);
  await open.tap();
  await page.waitForURL(`**/bids/${bids[0].id}/packages`);
}

async function checkMobileNavigation(page) {
  const picker = page.getByLabel("切换工作区");
  await picker.tap();
  // Playwright selects an option without interacting with the operating system's native picker.
  await picker.selectOption("history");
  await heading(page, "项目档案").waitFor();
  await picker.selectOption("projects");
  const open = page.getByRole("button", {
    name: `打开${titles[0]}`,
    exact: true,
  });
  await open.tap();
  await heading(page, "整包核查").waitFor();
  assert.equal(new URL(page.url()).pathname, `/bids/${bids[0].id}/packages`);
  const workspace = page.getByLabel("当前工作区");
  await workspace.selectOption("overview");
  await page.waitForURL(`**/bids/${bids[0].id}/overview`);
  assert.notEqual(
    await picker.inputValue(),
    "projects",
    "A native select cannot return to the list by reselecting its current value",
  );
  await picker.selectOption("projects");
  await heading(page, "投标项目").waitFor();
  await page.getByRole("button", { name: titles[1], exact: true }).tap();
  await page.waitForURL(`**/bids/${bids[1].id}/overview`);
  await picker.selectOption("history");
  await heading(page, "项目档案").waitFor();
}

async function checkMobileTargets(page) {
  const picker = page.getByLabel("切换工作区");
  const logout = page.getByRole("button", { name: "退出登录", exact: true });
  await page
    .getByRole("button", { name: `打开${titles[0]}`, exact: true })
    .tap();
  await heading(page, "整包核查").waitFor();
  const workspace = page.getByLabel("当前工作区");
  const back = page.getByRole("button", { name: "返回项目列表", exact: true });
  const sizes = {};
  for (const [name, control] of Object.entries({
    picker,
    workspace,
    back,
    logout,
  })) {
    const box = await control.boundingBox();
    sizes[name] = [Math.round(box.width), Math.round(box.height)];
  }
  console.log(JSON.stringify(sizes));
  for (const control of [picker, workspace, back, logout])
    await hitTarget(control, 44);
  await page.keyboard.press("Tab");
  for (const control of [picker, workspace, back, logout]) {
    await control.focus();
    await checkFocus(control);
  }
  await back.tap({ position: { x: 20, y: 4 } });
  await heading(page, "投标项目").waitFor();
  await logout.tap({ position: { x: 4, y: 4 } });
  await page.getByRole("button", { name: "登录工作区" }).waitFor();
}

async function checkDesktopSidebar(page) {
  const sidebar = page.locator(".sidebar");
  const nav = sidebar.getByRole("navigation", { name: "主导航" });
  const buttons = await nav.getByRole("button").all();
  assert(buttons.length > 0);
  const final = buttons.at(-1);
  const logout = sidebar.getByRole("button", { name: "退出登录", exact: true });
  const scroll = await sidebar.evaluate((el) => ({
    scrollable: el.scrollHeight - el.clientHeight,
    overflow: getComputedStyle(el).overflowY,
  }));
  assert(
    scroll.scrollable > 0,
    "Short viewport must exercise overflowing sidebar",
  );
  assert.equal(
    scroll.overflow,
    "auto",
    "Sidebar must allow vertical scrolling",
  );
  const initialPageScroll = await page.evaluate(
    () => document.scrollingElement.scrollTop,
  );
  const box = await sidebar.boundingBox();
  await page.mouse.move(
    Math.round(box.x + box.width / 2),
    Math.round(box.y + box.height / 2),
  );
  await page.mouse.wheel(0, 800);
  await page.waitForFunction(
    (distance) => document.querySelector(".sidebar").scrollTop >= distance - 1,
    scroll.scrollable,
  );
  await hitTarget(final, 24);
  await hitTarget(logout, 24);
  assert.equal(
    await page.evaluate(() => document.scrollingElement.scrollTop),
    initialPageScroll,
  );

  await page.mouse.wheel(0, -800);
  await page.waitForFunction(
    () => document.querySelector(".sidebar").scrollTop === 0,
  );
  await page.keyboard.press("Tab");
  await checkFocus(page.getByRole("link", { name: "跳到主要内容" }));
  for (const control of [...buttons, logout]) {
    await page.keyboard.press("Tab");
    await checkFocus(control);
    await hitTarget(control, 24);
  }

  await page.keyboard.press("Shift+Tab");
  await checkFocus(final);
  await page.keyboard.press("Enter");
  await page.waitForURL("**/assistant");
  await page.keyboard.press("Tab");
  await checkFocus(logout);
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "登录工作区" }).waitFor();
  console.log(`Sidebar scrollable distance: ${scroll.scrollable}px`);
}

let browser;
try {
  await app.listen();
  const origin = `http://127.0.0.1:${app.httpServer.address().port}`;
  browser = await browserType.launch({
    headless: true,
    ...(engine === "chromium"
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  const mobileChecks = [
    ["table", checkTable],
    ["navigation", checkMobileNavigation],
    ["targets", checkMobileTargets],
  ];
  const cases = [];
  for (const [width, height] of [
    [1440, 900],
    [390, 844],
    [844, 390],
  ]) {
    const mobile = width !== 1440;
    if (suite === "all" || suite === (mobile ? "mobile" : "desktop")) {
      cases.push({
        width,
        height,
        mobile,
        name: "material-row",
        check: checkMaterialRow,
      });
      cases.push({
        width,
        height,
        mobile,
        name: "file-pickers",
        check: checkFilePickers,
      });
    }
  }
  if (suite !== "desktop") {
    for (const [width, height] of [
      [320, 640],
      [390, 844],
    ]) {
      for (const [name, check] of mobileChecks)
        cases.push({ width, height, mobile: true, name, check });
    }
  }
  if (suite !== "mobile") {
    for (const [width, height] of [
      [761, 360],
      [1024, 400],
      [1440, 420],
    ])
      cases.push({
        width,
        height,
        mobile: false,
        name: "sidebar",
        check: checkDesktopSidebar,
      });
  }
  const failures = [];
  for (const { width, height, mobile, name, check } of cases) {
    const page = await browser.newPage({
      viewport: { width, height },
      isMobile: mobile,
      hasTouch: mobile,
    });
    page.setDefaultTimeout(5_000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/v1/")) return route.continue();
      const path = url.pathname.slice("/api/v1".length);
      const method = route.request().method();
      if (method === "POST" && path === "/auth/logout")
        return route.fulfill({ status: 204 });
      const data = method === "GET" ? fixture(path, url.searchParams) : null;
      return data
        ? route.fulfill({ json: data })
        : route.fulfill({ status: 404 });
    });
    try {
      await page.goto(`${origin}/projects`);
      await heading(page, "投标项目").waitFor();
      await check(page);
      assert.deepEqual(errors, []);
      console.log(
        `${engine} ${browser.version()} ${width}×${height}px ${name} passed`,
      );
    } catch (error) {
      const failure = `${engine} ${width}×${height}px ${name}: ${error.message}`;
      console.error(failure);
      failures.push(failure);
    } finally {
      await page.close();
    }
  }
  assert.deepEqual(failures, []);
} finally {
  await browser?.close();
  await app.close();
}
