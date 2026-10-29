// Run against the explicitly synthetic fixture; this is not a business API or model test.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";

const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE ?? "playwright"
);
const root = resolve("dist");
const output = resolve(
  process.env.PACKAGE_REVIEW_QA_OUTPUT ?? ".local/package-review-visual",
);
const media = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};
await readFile(resolve(root, "_qa/package-review.html"));
await mkdir(output, { recursive: true });
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(
      new URL(request.url, "http://127.0.0.1").pathname,
    );
    const file = resolve(root, `.${pathname}`);
    if (!file.startsWith(`${root}${sep}`)) {
      response.writeHead(403).end();
      return;
    }
    const bytes = await readFile(file);
    response.writeHead(200, {
      "Content-Type": media[extname(file)] ?? "application/octet-stream",
    });
    response.end(bytes);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const receipts = [];
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {}),
  });
  for (const width of [1200, 768, 390]) {
    const context = await browser.newContext({
      viewport: { width, height: 1000 },
      locale: "zh-CN",
    });
    const externalRequests = [],
      errors = [];
    await context.route("**/*", (route) => {
      if (route.request().url().startsWith(`${origin}/`))
        return route.continue();
      externalRequests.push(route.request().url());
      return route.abort();
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${origin}/_qa/package-review.html`);
    await page
      .getByRole("heading", { name: "整包核查、对比与报告副本 · 合成界面验收" })
      .waitFor();
    await page.getByLabel("内容容器宽度").selectOption(String(width));
    await page.evaluate(() => {
      const syntheticFetch = window.fetch;
      window.syntheticReportRequests = [];
      window.fetch = (input, options) => {
        if (
          String(input).endsWith("/report-exports") &&
          options?.method === "POST"
        )
          window.syntheticReportRequests.push({
            key: new Headers(options.headers).get("Idempotency-Key"),
            body: options.body,
          });
        return syntheticFetch(input, options);
      };
    });
    for (const mode of ["report", "comparison", "exports"]) {
      await page.getByLabel("验收页面").selectOption(mode);
      if (mode === "report") {
        const row = page.getByRole("article").first();
        await row
          .getByRole("button", { name: "记录人工判断", exact: true })
          .click();
        await page
          .getByText("已读取 2 条要求的人工状态；保存时仍须通过版本核对。", {
            exact: true,
          })
          .waitFor();
        await row
          .getByLabel("本次人工理由（必填）")
          .fill("合成浏览器验收：请复核证照有效期。");
        await row
          .getByRole("button", { name: "需要复查", exact: true })
          .click();
        await page.getByText("原请求已核对受理", { exact: true }).waitFor();
        await row.getByText("需要复查 · 第 1 版", { exact: true }).waitFor();
        const quoteChoices = await row
          .locator(".package-review__quote-choice")
          .evaluateAll((choices) =>
            choices.map((choice) => {
              const checkbox = choice
                .querySelector("input")
                .getBoundingClientRect();
              const text = choice.querySelector("span").getBoundingClientRect();
              return {
                checkboxWidth: checkbox.width,
                checkboxHeight: checkbox.height,
                textBesideCheckbox: text.left > checkbox.right,
              };
            }),
          );
        assert.ok(quoteChoices.length > 0);
        for (const choice of quoteChoices) {
          assert.ok(choice.checkboxWidth <= 24 && choice.checkboxHeight <= 24);
          assert.equal(choice.textBesideCheckbox, true);
        }
        await row.scrollIntoViewIfNeeded();
        await page.screenshot({ path: resolve(output, `human-${width}.png`) });
      }
      if (mode === "comparison") {
        const hint = await page.locator("p.muted").first().textContent();
        const ids = hint.match(/[a-f0-9-]{36}/g);
        assert.equal(ids.length, 2);
        await page.getByLabel("左侧核查编号（比较基准）").fill(ids[0]);
        await page.getByLabel("右侧核查编号（待比较轮次）").fill(ids[1]);
        await page
          .getByRole("button", { name: "读取两轮对比", exact: true })
          .click();
        await page.locator(".package-review-comparison__row").first().waitFor();
        await page
          .getByRole("button", {
            name: "查看此项左侧原结果与引用",
            exact: true,
          })
          .first()
          .click();
        const original = page.getByRole("region", {
          name: "左侧此项原结果与引用",
          exact: true,
        });
        await original
          .getByRole("region", { name: "整包范围核查结果", exact: true })
          .waitFor();
        assert.equal(await original.getByRole("article").count(), 1);
        await original
          .getByRole("button", { name: "关闭原核查详情", exact: true })
          .click();
      }
      if (mode === "exports") {
        await page
          .getByRole("button", { name: "读取报告生成依据", exact: true })
          .click();
        await page.getByText("已读取生成依据", { exact: true }).waitFor();
        await page
          .getByRole("button", { name: "下一份报告模拟丢回执", exact: true })
          .click();
        await page
          .getByRole("button", { name: "申请生成 Word 报告", exact: true })
          .click();
        await page.getByText("原报告申请尚未确认", { exact: true }).waitFor();
        await page
          .getByRole("button", { name: "恢复原报告申请", exact: true })
          .click();
        await page.getByText("报告副本已生成", { exact: true }).waitFor();
        const attempts = await page.evaluate(
          () => window.syntheticReportRequests,
        );
        assert.equal(attempts.length, 2);
        assert.deepEqual(attempts[0], attempts[1]);
        assert.ok(attempts[0].key);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: resolve(output, `${mode}-${width}.png`) });
      const bounds = await page.evaluate(() => ({
        viewport: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        controlsOutsideViewport: [
          ...document.querySelectorAll("button,input,select,textarea"),
        ]
          .filter((element) => {
            const box = element.getBoundingClientRect();
            return (
              box.width > 0 && (box.left < -1 || box.right > innerWidth + 1)
            );
          })
          .map((element) => element.tagName),
      }));
      const alerts = await page.getByRole("alert").allTextContents();
      assert.equal(
        bounds.scrollWidth,
        width,
        `${mode} overflows at ${width}px`,
      );
      assert.deepEqual(bounds.controlsOutsideViewport, []);
      assert.deepEqual(alerts, []);
      assert.deepEqual(errors, []);
      assert.deepEqual(externalRequests, []);
      receipts.push({ width, mode, bounds, alerts, errors: [...errors] });
    }
    await context.close();
  }
  const receipt = {
    browser: await browser.version(),
    synthetic_http: true,
    real_model_calls: 0,
    checks: receipts,
  };
  await writeFile(
    resolve(output, "receipt.json"),
    `${JSON.stringify(receipt, null, 2)}\n`,
  );
  console.log(JSON.stringify(receipt, null, 2));
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
