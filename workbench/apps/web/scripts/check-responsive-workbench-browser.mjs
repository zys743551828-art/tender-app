/* global console, document, getComputedStyle, process */
// Runs the real app in Chromium with synthetic HTTP responses and a loopback-only Vite server.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const widths = [390, 640, 641, 760, 761, 1440];
const evidence = process.env.RESPONSIVE_EVIDENCE_DIR;
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
const summary = {
  bid_id: bid.id,
  phase: bid.phase,
  archived_at: null,
  package_counts: { authority: 2, bid: 1 },
  head_members: { total: 5, parse_not_frozen: 1 },
  next_action: {
    action: "inspect_package_parses",
    reason: "核对尚未冻结的解析身份",
    target_url: `${bidPath}/packages`,
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
};
const fixtures = new Map([
  ["/auth/session", auth],
  ["/bids", { ...empty, items: [bid] }],
  [
    "/project-work-summaries",
    {
      version: "project-work-summary/1",
      observed_at: "2026-11-20T00:00:00Z",
      items: [summary],
    },
  ],
  ["/history", empty],
  [bidPath, bid],
  [`${bidPath}/materials`, { documents: [], conflicts: [] }],
  [`${bidPath}/package-documents`, empty],
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
  configFile: false,
  plugins: [react()],
  root: fileURLToPath(new URL("..", import.meta.url)),
  server: { host: "127.0.0.1", hmr: false },
});
let browser;
try {
  if (evidence) await mkdir(evidence, { recursive: true });
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const { authoringLayoutFixture, layoutScope } = await server.ssrLoadModule(
    "/src/authoringLayoutFixtures.test-support.ts",
  );
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
  });
  const failures = [];
  for (const width of widths) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    page.setDefaultTimeout(10_000);
    const authoring = authoringLayoutFixture(origin);
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      assert.equal(route.request().method(), "GET");
      const path = url.pathname.replace(/^\/api\/v1/, "");
      const data = fixtures.get(path);
      if (data) return route.fulfill({ json: data });
      if (
        path.startsWith("/authoring/") ||
        path.startsWith("/sections/") ||
        path.startsWith(`${bidPath}/draft`)
      ) {
        const response = await authoring.fetcher(url.href);
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

      await page.getByRole("button", { name: "返回项目列表" }).click();
      await heading.waitFor();
      const table = page.getByRole("table");
      const scroller = page.getByRole("region", { name: "全部项目" });
      const open = table.getByRole("button", {
        name: `打开${bid.title}`,
        exact: true,
      });
      const reason = table.getByText(summary.next_action.reason, {
        exact: true,
      });
      const counts = table.getByText("依据包 2 · 投标包 1", { exact: true });
      await reason.waitFor();
      await page.evaluate(() => document.fonts.ready.then(() => {}));
      assert.deepEqual(
        await table.getByRole("columnheader").allTextContents(),
        ["项目名称", "工作阶段", "整包资料", "工作下一步", "打开"],
      );
      const initial = await scroller.evaluate((wrap) => ({
        scrollLeft: wrap.scrollLeft,
        overflow: wrap.scrollWidth - wrap.clientWidth,
        pageWidth: document.documentElement.scrollWidth,
      }));
      assert.equal(initial.scrollLeft, 0);
      assert.equal(initial.pageWidth, width);
      const withinTable = async (locator) => {
        const tableBox = await scroller.boundingBox();
        const controlBox = await locator.boundingBox();
        return (
          controlBox.x >= tableBox.x - 1 &&
          controlBox.x + controlBox.width <= tableBox.x + tableBox.width + 1
        );
      };
      assert(await withinTable(open), "打开项目行动应在表格初始视口内");
      const create = page.getByRole("button", { name: "＋ 新建投标" });
      assert(await create.isVisible());
      const createBox = await create.boundingBox();
      assert(createBox.x >= 0 && createBox.x + createBox.width <= width);
      if (width === 390 && evidence)
        await page.screenshot({ path: join(evidence, "projects-390.png") });
      if (width === 390) {
        assert(initial.overflow > 0, "390px 应覆盖实际横向滚动");
        await scroller.press("ArrowRight");
        await page.waitForFunction(() => document.activeElement.scrollLeft > 0);
      }
      await counts.evaluate((el) => {
        el.scrollIntoView({ block: "nearest", inline: "center" });
      });
      assert(await withinTable(counts), "表内滚动可读到整包数量");
      assert(
        await counts.evaluate((el) => {
          const rects = [...el.getClientRects()];
          return (
            rects.length > 0 &&
            rects.every((rect) => Math.abs(rect.top - rects[0].top) < 3)
          );
        }),
        "整包数量应在同一行",
      );
      if (width === 390 && evidence)
        await page.screenshot({
          path: join(evidence, "projects-packages-390.png"),
        });
      await scroller.evaluate((wrap) => {
        wrap.scrollLeft = wrap.scrollWidth;
      });
      assert.equal(
        await scroller.evaluate((wrap) => wrap.scrollLeft),
        initial.overflow,
      );
      assert(await withinTable(reason), "横向滚动后可以读取完整的工作下一步");
      assert(await withinTable(open), "横向滚动后打开项目行动应保持可见");
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth),
        width,
      );
      if (width === 390 && evidence)
        await page.screenshot({
          path: join(evidence, "projects-scrolled-390.png"),
        });
      await open.click();
      await page
        .getByRole("heading", { name: "整包核查", exact: true })
        .waitFor();
      assert.equal(new URL(page.url()).pathname, `${bidPath}/packages`);
      assert.deepEqual(pageErrors, []);
      console.log(
        `${width}px 项目列表五列、创建与打开项目通过，表内滚动 ${initial.overflow}px`,
      );

      await page.goto(
        `${origin}${bidPath}/authoring?draft=${layoutScope.draftId}`,
      );
      const projectTitle = page.getByRole("heading", {
        name: bid.title,
        exact: true,
      });
      const body = page.locator(
        '[aria-label="章节正文"][contenteditable="true"]',
      );
      const title = page.getByRole("textbox", { name: "章节名称" });
      await body.waitFor();
      await page.evaluate(() => document.fonts.ready.then(() => {}));
      assert.equal(await title.inputValue(), "施工组织与进度");
      assert.equal(
        await page
          .locator(".authoring-draft-management details")
          .getAttribute("open"),
        null,
      );
      const bodyBox = await body.boundingBox();
      const paragraphBox = await body.locator("p").first().boundingBox();
      const titleBox = await title.boundingBox();
      const titleFont = await projectTitle.evaluate(
        (el) => getComputedStyle(el).fontSize,
      );
      const compactEditor = width <= 640;
      console.log(
        `${width}px 编制项目标题 ${titleFont}，章节名称 ${Math.round(titleBox.y)}px，正文 ${Math.round(bodyBox.y)}px，首段 ${Math.round(paragraphBox.y)}px`,
      );
      assert.equal(titleFont, compactEditor ? "18px" : "22px");
      assert(bodyBox.y <= 744, "正文应进入首屏且至少露出 100px");
      assert(paragraphBox.y < 844, "首段文字应进入首屏");
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth),
        width,
      );
      const toolbar = page.getByRole("toolbar", { name: "章节正文格式" });
      assert.equal(await toolbar.isVisible(), !compactEditor);
      if (evidence)
        await page.screenshot({
          path: join(evidence, `authoring-${width}.png`),
        });
      if (compactEditor) {
        await page
          .getByRole("button", { name: "文字格式与编辑工具", exact: true })
          .press("Enter");
        await toolbar.waitFor();
        await page
          .getByRole("button", { name: "收起文字格式与编辑工具", exact: true })
          .press("Enter");
        await toolbar.waitFor({ state: "hidden" });
        assert.equal(await title.inputValue(), "施工组织与进度");
      }
      assert.deepEqual(authoring.state.unexpected, []);
      assert.deepEqual(pageErrors, []);
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
