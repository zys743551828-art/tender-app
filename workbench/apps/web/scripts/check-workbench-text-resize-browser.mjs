/* global console, document, getComputedStyle, HTMLElement, innerWidth, process */
// Runs the real UI on loopback with a synthetic logged-out session.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const engine = process.argv[2] ?? "chromium";
assert(["chromium", "webkit"].includes(engine), "Use chromium or webkit");
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
  assert(
    await locator.evaluate((el) => {
      const style = getComputedStyle(el);
      const bounds = el.getBoundingClientRect();
      return (
        el === document.activeElement &&
        el.matches(":focus-visible") &&
        style.outlineStyle !== "none" &&
        Number.parseFloat(style.outlineWidth) > 0 &&
        bounds.left >= 0 &&
        bounds.right <= innerWidth + 1
      );
    }),
    "Expected a visible keyboard focus ring",
  );
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
  const failures = [];
  for (const colorScheme of ["light", "dark"]) {
    for (const [width, height, scale] of [
      [1440, 900, 1],
      [640, 450, 1],
      [390, 844, 2],
      [320, 640, 2],
    ]) {
      const page = await browser.newPage({
        viewport: { width, height },
        colorScheme,
      });
      const label = `${engine} ${browser.version()} ${colorScheme} ${width}×${height} ${scale * 100}% login`;
      page.setDefaultTimeout(5000);
      await page.route("**/*", (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== origin) return route.abort();
        if (url.pathname === "/api/v1/auth/session")
          return route.fulfill({
            status: 401,
            json: { code: "UNAUTHENTICATED", message: "请登录" },
          });
        if (url.pathname.startsWith("/api/"))
          return route.fulfill({ status: 404 });
        return route.continue();
      });
      try {
        await page.goto(`${origin}/projects`);
        await checkLogin(page, scale);
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth),
          width,
        );
        console.log(`${label} passed`);
      } catch (error) {
        failures.push(new Error(`${label}: ${error.message}`));
      } finally {
        await page.close();
      }
    }
  }
  if (failures.length)
    throw new AggregateError(failures, "Text resize checks failed");
} finally {
  await browser?.close();
  await app.close();
}
