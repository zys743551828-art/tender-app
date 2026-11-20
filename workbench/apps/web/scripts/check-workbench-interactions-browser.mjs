/* global console, document, getComputedStyle, innerWidth, NodeFilter, process */
// Real app on loopback, with synthetic projects and a synthetic session.
import assert from "node:assert/strict";
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
  if (suffix === "/materials") return { documents: [], conflicts: [] };
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
