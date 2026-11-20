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
const bidPath = "/bids/20000000-0000-4000-8000-000000000002";
const bid = {
  id: bidPath.split("/").at(-1),
  title: "标事台响应式验收合成项目 · 施工组织与现场管理",
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
const historyId = "20000000-0000-4000-8000-000000000012";
const layer = { state: "not_run", planned: null, completed: null, gaps: [] };
const fixtures = new Map([
  ["/auth/session", auth],
  ["/bids", empty],
  ["/history", empty],
  [bidPath, bid],
  [`${bidPath}/materials`, { documents: [], conflicts: [] }],
  [
    `${bidPath}/review-state`,
    { bid_id: bid.id, request: null, current_review: null },
  ],
  [`${bidPath}/settings`, { bid_id: bid.id, settings: { pricing: false } }],
  [`/reviews/${historyId}/findings`, empty],
  [
    `/reviews/${historyId}`,
    {
      id: historyId,
      bid_id: bid.id,
      current: false,
      core_coverage: "partial",
      risk_count: null,
      next_action: bid.next_action,
      prediction: { mode: "hidden", reasons: [] },
      coverage_layers: {
        source_scope: layer,
        core_extraction: layer,
        judgment: layer,
        scoring: layer,
      },
    },
  ],
]);
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
    page.setDefaultTimeout(10_000);
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      assert.equal(route.request().method(), "GET");
      const data = fixtures.get(url.pathname.replace(/^\/api\/v1/, ""));
      return data
        ? route.fulfill({ json: data })
        : route.fulfill({
            status: 404,
            json: { code: "SYNTHETIC_UNAVAILABLE" },
          });
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
      console.log(`${width}px 导航往返通过`);

      const meta = page.locator(".project-meta");
      const revision = meta.getByText("资料修订 12", { exact: true });
      const historical = meta.getByText("正在查看指定历史轮次", {
        exact: true,
      });
      await page.goto(`${origin}${bidPath}/review`);
      await meta.waitFor();
      const currentRevisionVisible = await revision.isVisible();
      assert.equal(await historical.count(), 0);
      await page.goto(`${origin}${bidPath}/review?review=${historyId}`);
      await page.getByText("历史评审 · 输入已固定", { exact: true }).waitFor();
      assert.deepEqual(
        [
          currentRevisionVisible,
          await revision.isVisible(),
          await historical.isVisible(),
        ],
        [true, true, true],
        "当前页资料修订、历史页资料修订、历史页轮次提示应均可见",
      );
      assert.deepEqual(pageErrors, []);
      console.log(`${width}px 项目资料修订与历史轮次提示通过`);
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
