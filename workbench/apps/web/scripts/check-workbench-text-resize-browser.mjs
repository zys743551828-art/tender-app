/* global console, document, getComputedStyle, HTMLElement, innerHeight, innerWidth, process, scrollTo */
// Runs the real UI on loopback with synthetic HTTP responses.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const engine = process.argv[2] ?? "chromium";
assert(["chromium", "webkit"].includes(engine), "Use chromium or webkit");
const suite = process.argv[3] ?? "all";
assert(
  ["all", "login", "project"].includes(suite),
  "Use all, login or project",
);
const projectTitle =
  "海州市城市更新重点片区市政基础设施改造及配套管网提升工程施工总承包第一标段技术标编制与审核（合成项目）";
const require = createRequire(import.meta.url);
const browserType = require(process.env.PLAYWRIGHT_MODULE ?? "playwright")[
  engine
];
const app = await createServer({
  configFile: false,
  root: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [react()],
  server: { host: "127.0.0.1", hmr: false },
});

// Double the actual computed text sizes, keeping the viewport and the authored layout dimensions.
async function resizeText(page, scale) {
  await page.evaluate(async (factor) => {
    if (factor !== 1) {
      const entries = [...document.querySelectorAll("body *")]
        .filter((el) => el instanceof HTMLElement && el.getClientRects().length)
        .map((el) => [el, Number.parseFloat(getComputedStyle(el).fontSize)]);
      for (const [el, size] of entries)
        el.style.fontSize = `${size * factor}px`;
    }
    await document.fonts.ready;
  }, scale);
}

async function fitsNativeSelect(locator) {
  const [actual, intrinsic] = await locator.evaluate((select) => {
    const clone = select.cloneNode(true);
    Object.assign(clone.style, {
      width: "max-content",
      minWidth: "0",
      maxWidth: "none",
      position: "absolute",
      visibility: "hidden",
    });
    select.after(clone);
    const widths = [
      select.getBoundingClientRect().width,
      clone.getBoundingClientRect().width,
    ];
    clone.remove();
    return widths;
  });
  assert(
    actual >= intrinsic - 1,
    `Select clips its options: ${Math.round(actual)}px available, ${Math.round(intrinsic)}px needed`,
  );
}

async function checkVisibleFocus(locator) {
  const target = await locator.elementHandle();
  try {
    await locator.page().waitForFunction(
      (el) => {
        const style = getComputedStyle(el);
        const bounds = el.getBoundingClientRect();
        const visibleHeight =
          Math.min(bounds.bottom, innerHeight) - Math.max(bounds.top, 0);
        return (
          el === document.activeElement &&
          el.matches(":focus-visible") &&
          style.outlineStyle !== "none" &&
          Number.parseFloat(style.outlineWidth) > 0 &&
          visibleHeight >= bounds.height / 2 &&
          bounds.left >= 0 &&
          bounds.right <= innerWidth + 1
        );
      },
      target,
      { timeout: 3000 },
    );
  } finally {
    await target.dispose();
  }
}

async function checkLogin(page, scale) {
  await page.getByRole("heading", { name: "登录标事台" }).waitFor();
  const account = page.getByLabel("账号", { exact: true });
  const password = page.getByLabel("密码", { exact: true });
  await account.fill("建设工程测试账号");
  await resizeText(page, scale);
  const help = page.locator(".login-help");
  await help.waitFor();
  assert(
    await help.evaluate((el) => el.getBoundingClientRect().right <= innerWidth),
  );
  const dimensions = await account.evaluate((el) => {
    const style = getComputedStyle(el);
    const content =
      el.clientHeight -
      Number.parseFloat(style.paddingBlockStart) -
      Number.parseFloat(style.paddingBlockEnd);
    const sample = document.createElement("span");
    sample.textContent = "建A";
    Object.assign(sample.style, {
      font: style.font,
      lineHeight: style.lineHeight,
      position: "absolute",
      visibility: "hidden",
    });
    document.body.append(sample);
    const line = sample.getBoundingClientRect().height;
    sample.remove();
    return { content, line };
  });
  console.log(
    `Login input content ${dimensions.content}px, one text line ${dimensions.line}px`,
  );
  await page.keyboard.press("Tab");
  await checkVisibleFocus(password);
  await fitsNativeSelect(page.getByLabel("外观主题"));
  assert(
    dimensions.content >= dimensions.line - 1,
    "Login field is shorter than the scaled text line",
  );
}

async function checkProject(page, scale, section) {
  const title = page.getByRole("heading", { name: projectTitle, exact: true });
  await title.waitFor();
  if (section === "authoring")
    await page
      .locator('[aria-label="章节正文"][contenteditable="true"]')
      .waitFor();
  await resizeText(page, scale);
  await page.evaluate(() => scrollTo(0, 0));
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth === innerWidth,
    ),
  );

  const back = page.getByRole("button", { name: "返回项目列表", exact: true });
  const topbar = page.locator(".topbar");
  assert(
    await back.evaluate((el) => {
      const box = el.getBoundingClientRect();
      return (
        box.top >= 0 && box.bottom <= innerHeight && box.right <= innerWidth
      );
    }),
    "Back action must be visible when entering the project",
  );
  const upload = page.getByRole("button", {
    name: section === "materials" ? "上传资料" : "上传新版资料",
    exact: true,
  });
  const picker = page.getByLabel("切换工作区");
  const theme = page.getByLabel("外观主题");
  const breadcrumb = topbar.locator(":scope > span");
  const topbarBox = await topbar.boundingBox();
  const items = [];
  for (const el of [breadcrumb, picker, theme]) {
    if (!(await el.isVisible())) continue;
    const box = await el.boundingBox();
    assert(
      box.x >= topbarBox.x &&
        box.x + box.width <= topbarBox.x + topbarBox.width + 1 &&
        box.y >= topbarBox.y &&
        box.y + box.height <= topbarBox.y + topbarBox.height + 1,
      "Topbar control or breadcrumb crosses its row boundary",
    );
    assert(
      items.every(
        (other) =>
          box.x + box.width <= other.x + 1 ||
          other.x + other.width <= box.x + 1 ||
          box.y + box.height <= other.y + 1 ||
          other.y + other.height <= box.y + 1,
      ),
      "Topbar items overlap",
    );
    items.push(box);
  }
  if (page.viewportSize().width <= 480) {
    const titleBox = await title.boundingBox();
    const headerBox = await page
      .locator(".project-page > .page-heading")
      .boundingBox();
    const toolbox = await page.locator(".workspace-nav-tools").boundingBox();
    console.log(
      `Project title ${Math.round(titleBox.width)}/${Math.round(headerBox.width)}px, toolbox y=${Math.round(toolbox.y)}px`,
    );
    assert(
      titleBox.width >= headerBox.width - 1 &&
        (await upload.boundingBox()).y >= titleBox.y + titleBox.height - 1,
      "The upload button crowds the project title on a phone",
    );
    const assistant = await page
      .getByRole("button", { name: "项目助手", exact: true })
      .boundingBox();
    const sources = await page
      .getByRole("button", { name: "查证资料", exact: true })
      .boundingBox();
    assert(
      sources.x >= assistant.x + assistant.width + 7 ||
        sources.y >= assistant.y + assistant.height + 7,
      "Adjacent project actions need a visible gap",
    );
  }
  if (scale === 2) {
    await fitsNativeSelect(picker);
    await fitsNativeSelect(theme);
  }

  const projectPicker = page.getByLabel("当前工作区");
  const navigation = (await projectPicker.isVisible())
    ? projectPicker
    : page
        .getByRole("navigation", { name: "项目工作区" })
        .getByRole("link")
        .first();
  await page.keyboard.press("Tab");
  for (const control of [
    back,
    upload,
    navigation,
    page.getByRole("button", { name: "项目助手", exact: true }),
    page.getByRole("button", { name: "查证资料", exact: true }),
  ]) {
    await control.focus();
    await checkVisibleFocus(control);
  }
  await back.press("Enter");
  await page.waitForURL("**/projects");
}

function projectFixture(path, bidPath, bid) {
  if (path === bidPath) return bid;
  if (path === `${bidPath}/materials`)
    return { documents: [], conflicts: [], material_revision: 12 };
  if (path === `${bidPath}/review-state`)
    return { bid_id: bid.id, request: null, current_review: null };
  if (path === `${bidPath}/settings`)
    return { bid_id: bid.id, settings: { pricing: false } };
  if (path === "/bids" || path === `${bidPath}/upload-batches`)
    return { items: [], has_more: false, next_cursor: null };
  return undefined;
}

let browser;
try {
  await app.listen();
  const origin = `http://127.0.0.1:${app.httpServer.address().port}`;
  const { authoringLayoutFixture, layoutScope } = await app.ssrLoadModule(
    "/src/authoringLayoutFixtures.test-support.ts",
  );
  const bidPath = `/bids/${layoutScope.bidId}`;
  const auth = {
    member: {
      id: layoutScope.memberId,
      display_name: "合成验收账号",
      active: true,
    },
    csrf_token: "synthetic-only",
    expires_at: "2099-01-01T00:00:00Z",
  };
  const bid = {
    id: layoutScope.bidId,
    title: projectTitle,
    phase: "working",
    material_revision: 12,
    current_body_id: null,
    current_review_id: null,
    stream_id: null,
    next_action: {
      action: "upload_materials",
      reason: "核对合成资料",
      target_url: `${bidPath}/materials`,
      blocked: false,
    },
  };
  browser = await browserType.launch({
    headless: true,
    ...(engine === "chromium"
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  const failures = [];
  const screens = [
    ...(suite === "project" ? [] : ["login"]),
    ...(suite === "login" ? [] : ["materials", "authoring"]),
  ];
  for (const colorScheme of ["light", "dark"]) {
    for (const [width, height, scale] of [
      [1440, 900, 1],
      [640, 450, 1],
      [390, 844, 1],
      [390, 844, 2],
      [320, 640, 2],
    ]) {
      for (const screen of screens) {
        const page = await browser.newPage({
          viewport: { width, height },
          colorScheme,
        });
        const label = `${engine} ${browser.version()} ${colorScheme} ${width}×${height} ${scale * 100}% ${screen}`;
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        const draft = authoringLayoutFixture(origin);
        page.setDefaultTimeout(5000);
        await page.route("**/*", async (route) => {
          const url = new URL(route.request().url());
          if (url.origin !== origin) return route.abort();
          if (!url.pathname.startsWith("/api/v1/")) return route.continue();
          const path = url.pathname.slice("/api/v1".length);
          if (path === "/auth/session")
            return screen === "login"
              ? route.fulfill({
                  status: 401,
                  json: { code: "UNAUTHENTICATED", message: "请登录" },
                })
              : route.fulfill({ json: auth });
          const data = projectFixture(path, bidPath, bid);
          if (data) return route.fulfill({ json: data });
          if (
            path.startsWith("/authoring/") ||
            path.startsWith("/sections/") ||
            path.startsWith(`${bidPath}/draft`)
          ) {
            const response = await draft.fetcher(url.href);
            return route.fulfill({
              status: response.status,
              headers: Object.fromEntries(response.headers),
              body: await response.text(),
            });
          }
          return route.fulfill({
            status: 404,
            json: { code: "SYNTHETIC_UNAVAILABLE" },
          });
        });
        try {
          const route =
            screen === "login"
              ? "/projects"
              : `${bidPath}/${screen}${screen === "authoring" ? `?draft=${layoutScope.draftId}` : ""}`;
          await page.goto(origin + route);
          if (screen === "login") await checkLogin(page, scale);
          else await checkProject(page, scale, screen);
          assert.equal(
            await page.evaluate(() => document.documentElement.dataset.theme),
            colorScheme,
          );
          assert.equal(
            await page.evaluate(() => document.documentElement.scrollWidth),
            width,
          );
          assert.deepEqual(errors, []);
          assert.deepEqual(draft.state.unexpected, []);
          console.log(`${label} passed`);
        } catch (error) {
          failures.push(new Error(`${label}: ${error.message}`));
        } finally {
          await page.close();
        }
      }
    }
  }
  if (failures.length)
    throw new AggregateError(failures, "Text resize checks failed");
} finally {
  await browser?.close();
  await app.close();
}
