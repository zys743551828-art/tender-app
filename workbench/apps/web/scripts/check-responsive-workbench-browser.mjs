/* global console, process */
// Runs the real app in Chromium with synthetic HTTP responses and a loopback-only Vite server.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, URL } from "node:url";
import { createServer } from "vite";

const widths = [390, 640, 641, 760, 761, 1440];
const auth = {
  member: { id: "responsive-test", display_name: "合成验收账号", active: true },
  csrf_token: "responsive-test-only",
  expires_at: "2099-01-01T00:00:00Z",
};
const empty = { items: [], has_more: false, next_cursor: null };
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  server: { host: "127.0.0.1", port: 0 },
});
let browser;
try {
  await server.listen(0);
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
  });
  const failures = [];
  for (const width of widths) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      assert.equal(route.request().method(), "GET");
      const data = url.pathname === "/api/v1/auth/session" ? auth : empty;
      return route.fulfill({ json: data });
    });
    try {
      await page.goto(`${origin}/projects`);
      const heading = page.getByRole("heading", {
        name: "投标项目",
        exact: true,
      });
      await heading.waitFor();
      const nav = page.getByRole("navigation", { name: "主导航" });
      const picker = page.getByLabel("切换工作区");
      const compact = width <= 760;
      assert.equal(await nav.isVisible(), !compact, "桌面侧栏导航可见性");
      assert.equal(await picker.isVisible(), compact, "窄屏工作区下拉框可见性");
      if (compact) await picker.selectOption("history");
      else await nav.getByRole("button", { name: "项目档案" }).click();
      await page
        .getByRole("heading", { name: "项目档案", exact: true })
        .waitFor();
      assert.equal(new URL(page.url()).pathname, "/history");
      if (compact) await picker.selectOption("projects");
      else await nav.getByRole("button", { name: "投标项目" }).click();
      await heading.waitFor();
      assert.equal(new URL(page.url()).pathname, "/projects");
      assert.deepEqual(pageErrors, []);
      console.log(`${width}px 导航往返通过`);
    } catch (error) {
      failures.push(new Error(`${width}px ${error.message}`, { cause: error }));
    } finally {
      await page.close();
    }
  }
  if (failures.length)
    throw new AggregateError(failures, "响应式浏览器检查失败");
} finally {
  await browser?.close();
  await server.close();
}
