/* global document, innerWidth, getComputedStyle, console, process */
// CSS layout regression only; no API fixtures or business acceptance claims.
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { values } = parseArgs({
  options: {
    out: { type: "string" },
    "css-file": { type: "string" },
    "fixture-json": { type: "string" },
    "browser-executable": { type: "string" },
  },
});
assert(values.out, "Explicit evidence directory required");
const out = path.resolve(values.out);
await fs.mkdir(out, { recursive: true });
const css = await fs.readFile(
  values["css-file"] ?? path.join(root, "src/styles.css"),
  "utf8",
);
const sample = `<section class="panel project-list"><div class="list-toolbar"><h2>SYNTHETIC projects</h2></div>
<div class="table-wrap"><table><thead><tr><th>Project name</th><th>Stage</th><th>Packages</th><th>Next step</th><th><span class="sr-only">Open</span></th></tr></thead>
<tbody><tr><td><button class="project-link">SYNTHETIC technical project with a long title</button></td><td><span class="badge">Preparation</span></td><td>Authority 1 / Bid 1</td><td class="next-action-cell">Keep unknown navigation and extraction states explicit.</td><td><button class="icon-button" aria-label="Open SYNTHETIC project">→</button></td></tr></tbody></table></div></section>`;
const section = values["fixture-json"]
  ? JSON.parse(await fs.readFile(values["fixture-json"], "utf8")).project_html
  : sample;
assert(typeof section === "string" && section.includes("project-list"));
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const browser = await chromium.launch({
  headless: true,
  ...(values["browser-executable"]
    ? { executablePath: values["browser-executable"] }
    : {}),
});
const records = [],
  failures = [];
try {
  const page = await browser.newPage();
  await page.route("**/*", (route) => route.abort());
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body><div class="app-shell"><div class="workspace"><main><div class="page-content">${section}</div></main></div></div></body></html>`,
    );
    const before = await page.evaluate(() => {
      const wrap = document.querySelector(".project-list .table-wrap");
      const label = wrap.querySelector("th .sr-only");
      return {
        viewport: innerWidth,
        document_width: document.documentElement.scrollWidth,
        wrap_client_width: wrap.clientWidth,
        wrap_scroll_width: wrap.scrollWidth,
        horizontal_scrolling: getComputedStyle(wrap).overflowX,
        accessible_column_label: label.textContent.trim(),
        label_containing_block_is_scroller: label.offsetParent === wrap,
      };
    });
    const originalLabel = before.accessible_column_label;
    await page.screenshot({ path: path.join(out, `projects-${width}.png`) });
    await page.locator(".project-list .table-wrap").evaluate((wrap) => {
      wrap.scrollLeft = wrap.scrollWidth;
    });
    const after = await page.evaluate(() => {
      const wrap = document.querySelector(".project-list .table-wrap"),
        b = wrap.getBoundingClientRect();
      const button = wrap.querySelector(
          "tbody tr:last-child td:last-child button",
        ),
        c = button.getBoundingClientRect();
      return {
        scroll_left: wrap.scrollLeft,
        rightmost_action_inside_scroller:
          c.left >= b.left && c.right <= b.right,
        accessible_column_label: wrap
          .querySelector("th .sr-only")
          .textContent.trim(),
        document_width: document.documentElement.scrollWidth,
      };
    });
    await page.screenshot({
      path: path.join(out, `projects-scrolled-${width}.png`),
    });
    records.push({ width, before, after });
    try {
      assert(
        before.document_width <= width + 1,
        "Page must not acquire the table's horizontal overflow",
      );
      assert(
        after.document_width <= width + 1,
        "Local scrolling must not move the page boundary",
      );
      assert.equal(before.horizontal_scrolling, "auto");
      assert(
        originalLabel && originalLabel === after.accessible_column_label,
        "Accessible column label must remain intact",
      );
      assert(
        after.rightmost_action_inside_scroller,
        "The last action must remain reachable by local scrolling",
      );
      if (width === 390) {
        assert(
          before.wrap_scroll_width > before.wrap_client_width,
          "Narrow regression must exercise a genuinely wide table",
        );
        assert(
          after.scroll_left > 0,
          "Wide table must remain scrollable rather than hidden",
        );
      }
    } catch (error) {
      failures.push({ width, message: error.message });
    }
  }
} finally {
  await browser.close();
}
await fs.writeFile(
  path.join(out, "result.json"),
  JSON.stringify(
    {
      scope: "offline CSS layout regression only",
      records,
      failures,
      browser_closed: true,
    },
    null,
    2,
  ),
);
console.log(
  JSON.stringify({
    status: failures.length ? "failed" : "passed",
    evidence_dir: out,
    failures: failures.length,
  }),
);
process.exitCode = failures.length ? 1 : 0;
