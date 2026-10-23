/* global process, URL, console, window, document, innerWidth, localStorage */
// Real chapter history/preview/command components, immutable bundle, synthetic HTTP.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-authoring-history-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const sha = (data) => createHash("sha256").update(data).digest("hex");
const assert = (value, message) => {
  if (!value) throw Error(message);
};
await fs.mkdir(out, { recursive: true });
try {
  await fs.access(path.join(out, "receipt.json"));
  throw Error("Use a new output directory; preserve prior evidence.");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
async function sourceHashes(directory = path.join(root, "src")) {
  const result = {};
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) Object.assign(result, await sourceHashes(file));
    else result[path.relative(root, file)] = sha(await fs.readFile(file));
  }
  return result;
}
const before = await sourceHashes();
const entry = `
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { AuthoringHistory } from "./src/AuthoringHistory";
import { ThemePicker } from "./src/ThemePicker";
import { useTheme } from "./src/theme";
import { setAuth } from "./src/api";
import { historyFixture, historyScope, historyLongText } from "./src/authoringHistoryFixtures.test-support";
import "./src/styles.css";
const params = new URLSearchParams(window.location.search);
const fixture = await historyFixture({ image: true, long: true });
if (params.has("bad_image")) fixture.state.image.digest = "f".repeat(64);
if (params.has("source_stale")) fixture.state.restoreMode = "source_stale";
window.__historyQA = fixture;
window.__historyLongText = historyLongText;
window.fetch = fixture.fetcher;
setAuth({ member: { id: historyScope.memberId, display_name: "合成验收成员", active: true }, csrf_token: "synthetic-not-a-credential", expires_at: "2099-01-01T00:00:00Z" });
function Harness() {
  const theme = useTheme();
  const [busy, setBusy] = useState(false);
  const [, refreshView] = useState(0);
  return <main className="qa-history"><header><h1>章节历史与显式恢复</h1><p>合成验收资料：实际组件与本地测试响应；不代表真实项目内容或模型质量验收。</p><ThemePicker {...theme}/></header>
  <section className="panel qa-history__surface"><AuthoringHistory bidId={historyScope.bidId} sectionId={historyScope.sectionId} disabled={busy} getHead={() => fixture.state.head} flush={async () => { fixture.state.flushes++; return fixture.state.flushAllowed; }} setBusy={setBusy} refresh={async () => { fixture.state.refreshes++; refreshView(value => value + 1); }}/></section></main>;
}
createRoot(document.getElementById("root")).render(<Harness/>);
`;
const built = await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  metafile: true,
  format: "esm",
  jsx: "automatic",
  target: "es2022",
  outdir: out,
  entryNames: "app",
  external: ["/fonts/*"],
  logLimit: 5,
  plugins: [
    {
      name: "asset-urls",
      setup(builder) {
        builder.onResolve({ filter: /\?url$/ }, (args) => ({
          path: require.resolve(args.path.slice(0, -4)),
          namespace: "asset-url",
        }));
        builder.onLoad(
          { filter: /.*/, namespace: "asset-url" },
          async (args) => {
            const name = path.basename(args.path);
            await fs.copyFile(args.path, path.join(out, name));
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
const inputs = {};
for (const name of Object.keys(built.metafile.inputs).sort()) {
  if (!name.startsWith("src/")) continue;
  const digest = sha(await fs.readFile(path.join(root, name)));
  assert(before[name] === digest, `Source changed while bundling: ${name}`);
  inputs[name] = digest;
}
await fs.copyFile(
  path.join(root, "public/theme.js"),
  path.join(out, "theme.js"),
);
await fs.writeFile(
  path.join(out, "fixture.css"),
  ".qa-history{max-width:1100px;margin:0 auto;padding:24px;min-width:0}.qa-history>header{margin-bottom:24px}.qa-history h1{font-size:24px}.qa-history__surface{padding:20px;min-width:0}@media(max-width:600px){.qa-history{padding:12px}.qa-history__surface{padding:12px}}",
);
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>章节历史合成验收</title><script src="/theme.js"></script><link rel="stylesheet" href="/app.css"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
};
const server = http.createServer(async (request, response) => {
  try {
    const name = decodeURIComponent(
      new URL(request.url, "http://localhost").pathname,
    );
    const directory = name.startsWith("/fonts/")
      ? path.join(root, "public")
      : out;
    const target = path.resolve(
      directory,
      `.${name === "/" ? "/index.html" : name}`,
    );
    if (!target.startsWith(directory + path.sep))
      throw Error("outside fixture");
    const bytes = await fs.readFile(target);
    response.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    response.end(bytes);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const receipt = {
  recorded_at: new Date().toISOString(),
  scope:
    "Actual AuthoringHistory, authoringHistoryProtocol, AuthoringRichSnapshot, TextChangePreview, useResource and unchanged useCommand, compiled once with recorded source hashes; synthetic local HTTP responses only. Native nonowner main HTTP/restore is separately tested. No real project or mobile soft-keyboard acceptance.",
  source_inputs: inputs,
  bundle_sha256: Object.fromEntries(
    await Promise.all(
      ["app.js", "app.css", "theme.js", "fixture.css"].map(async (name) => [
        name,
        sha(await fs.readFile(path.join(out, name))),
      ]),
    ),
  ),
  cases: [],
  screenshots: [],
  page_errors: [],
  external_requests: [],
};
let browser;
async function shot(page, name) {
  const file = `${name}.png`;
  await page.screenshot({ path: path.join(out, file) });
  receipt.screenshots.push({
    file,
    sha256: sha(await fs.readFile(path.join(out, file))),
  });
}
async function layout(page, state) {
  const value = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    outside: [
      ...document.querySelectorAll("input,select,textarea,button,summary"),
    ]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return (
          element.getClientRects().length &&
          box.width &&
          (box.left < -1 || box.right > innerWidth + 1)
        );
      })
      .map((element) => (element.textContent ?? "").slice(0, 100)),
    unexpected: window.__historyQA.state.unexpected,
  }));
  assert(
    value.scroll <= value.width + 1 &&
      !value.outside.length &&
      !value.unexpected.length,
    JSON.stringify({ state, value }),
  );
  return value;
}
async function open(width, theme, query = "") {
  const context = await browser.newContext({
    viewport: { width, height: width === 390 ? 844 : 900 },
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  await context.addInitScript((chosen) => {
    localStorage.setItem("bid-workbench:theme", chosen);
  }, theme);
  const page = await context.newPage();
  page.on("pageerror", (error) => receipt.page_errors.push(error.message));
  await page.route("**/*", async (route) => {
    const address = new URL(route.request().url());
    if (
      !["127.0.0.1", "localhost"].includes(address.hostname) &&
      !["data:", "blob:"].includes(address.protocol)
    ) {
      receipt.external_requests.push(address.origin);
      await route.abort();
    } else await route.continue();
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/${query}`, {
    waitUntil: "networkidle",
  });
  await page.getByText("查看章节历史修订", { exact: true }).click();
  await page.getByRole("button", { name: /^章节修订 2\b/ }).waitFor();
  assert(
    await page.evaluate(
      () =>
        window.__historyQA.state.calls.length === 1 &&
        window.__historyQA.state.writes.length === 0,
    ),
    "opening directory auto-selected or wrote history",
  );
  await page.getByRole("button", { name: /^章节修订 2\b/ }).click();
  return { context, page };
}
try {
  browser = await chromium.launch({
    executablePath:
      process.env.CHROME_BIN ??
      "/tmp/tender-completion-runtime/chrome-156/chrome-headless-shell-linux64/chrome-headless-shell",
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  receipt.browser = browser.version();
  for (const width of [390, 1280])
    for (const theme of ["light", "dark"]) {
      const { context, page } = await open(width, theme);
      const name = `${theme}-${width}`;
      const restore = page.getByRole("button", {
        name: "恢复此历史正文为新修订",
        exact: true,
      });
      await page.waitForFunction(() => {
        const button = [...document.querySelectorAll("button")].find(
          (item) => item.textContent === "恢复此历史正文为新修订",
        );
        return button && !button.disabled;
      });
      const body = page.getByRole("region", { name: "拟恢复的完整历史正文" });
      const completeness = await page.evaluate(() => ({
        full: document
          .querySelector('[aria-label="拟恢复的完整历史正文"]')
          .textContent.includes(window.__historyLongText),
        writes: window.__historyQA.state.writes.length,
        decoded:
          document.querySelector('[aria-label="拟恢复的完整历史正文"] img')
            .naturalWidth === 2,
        theme: document.documentElement.dataset.theme,
      }));
      assert(
        completeness.full &&
          completeness.decoded &&
          completeness.writes === 0 &&
          completeness.theme === theme,
        `incomplete or mismatched preview ${name}`,
      );
      assert(
        (await body
          .getByRole("columnheader", { name: "合并表头" })
          .getAttribute("colspan")) === "2",
        "merged table lost",
      );
      await body
        .getByRole("img", { name: "合成示意图" })
        .scrollIntoViewIfNeeded();
      const initialLayout = await layout(page, `body-${name}`);
      await shot(page, `body-${name}`);
      await page.getByText("与当前已保存正文比较", { exact: true }).click();
      await page.getByRole("region", { name: "完整当前已保存正文" }).waitFor();
      assert(
        await page.evaluate(
          () =>
            window.__historyQA.state.writes.length === 0 &&
            window.__historyQA.state.flushes === 0,
        ),
        "comparison applied or saved automatically",
      );
      const comparisonLayout = await layout(page, `comparison-${name}`);
      await shot(page, `comparison-${name}`);
      if (width === 1280 && theme === "dark") {
        await page.setViewportSize({ width: 390, height: 844 });
        await layout(page, "resized-mobile");
        assert((await body.count()) === 1, "resize lost exact history");
        await page.setViewportSize({ width: 1280, height: 900 });
      }
      if (width === 390 && theme === "light") {
        await page.evaluate(() => {
          window.__historyQA.state.flushAllowed = false;
        });
        await restore.click();
        await page.waitForFunction(
          () => window.__historyQA.state.flushes === 1,
        );
        assert(
          await page.evaluate(
            () => window.__historyQA.state.writes.length === 0,
          ),
          "blocked draft flush still sent restore",
        );
        await page.evaluate(() => {
          window.__historyQA.state.flushAllowed = true;
        });
      }
      await restore.click();
      await page
        .getByText("已追加草稿修订 4，其他历史仍保留。", { exact: true })
        .waitFor();
      const outcome = await page.evaluate(() => ({
        writes: window.__historyQA.state.writes.length,
        refreshes: window.__historyQA.state.refreshes,
        revision: window.__historyQA.state.writes[0].body.revision,
        baseDraft: window.__historyQA.state.writes[0].body.base_draft_revision,
        baseSection:
          window.__historyQA.state.writes[0].body.base_section_revision,
      }));
      assert(
        outcome.writes === 1 &&
          outcome.refreshes === 1 &&
          outcome.revision === 2 &&
          outcome.baseDraft === 3 &&
          outcome.baseSection === 3,
        "explicit restore identity changed",
      );
      assert(
        (await page.getByRole("button", { name: /^章节修订 2\b/ }).count()) ===
          1,
        "original revision disappeared",
      );
      assert(
        (await body.count()) === 0,
        "restored selection left misleading pending preview",
      );
      await shot(page, `restored-${name}`);
      receipt.cases.push({
        name,
        completeness,
        initialLayout,
        comparisonLayout,
        outcome,
        result: "passed",
      });
      console.log(`Chapter history browser: ${name} passed`);
      await context.close();
    }
  for (const condition of ["bad_image", "source_stale"]) {
    const { context, page } = await open(390, "dark", `?${condition}`);
    if (condition === "bad_image") {
      await page
        .getByText(/图片的项目、历史版本或规范字节证明不一致/)
        .waitFor();
      assert(
        await page
          .getByRole("button", { name: "恢复此历史正文为新修订" })
          .isDisabled(),
        "bad image enabled restore",
      );
      assert(
        await page.evaluate(
          () =>
            !window.__historyQA.state.calls.some((call) =>
              call.path.endsWith("/bytes/normalized"),
            ) && window.__historyQA.state.writes.length === 0,
        ),
        "bad binding read bytes or restored",
      );
    } else {
      await page.waitForFunction(() => {
        const button = [...document.querySelectorAll("button")].find(
          (item) => item.textContent === "恢复此历史正文为新修订",
        );
        return button && !button.disabled;
      });
      await page
        .getByRole("button", { name: "恢复此历史正文为新修订" })
        .click();
      await page
        .getByText("历史来源已撤回，不能恢复为当前正文。", { exact: true })
        .waitFor();
      assert(
        (await page
          .getByRole("region", { name: "拟恢复的完整历史正文" })
          .count()) === 1,
        "source rejection discarded old preview",
      );
      assert(
        (await page.getByText(/已追加草稿修订/).count()) === 0,
        "source rejection pretended success",
      );
    }
    const checkedLayout = await layout(page, condition);
    await shot(page, condition);
    receipt.cases.push({
      name: condition,
      layout: checkedLayout,
      result: "passed",
    });
    console.log(`Chapter history browser: ${condition} passed`);
    await context.close();
  }
  assert(
    !receipt.page_errors.length && !receipt.external_requests.length,
    "unexpected browser errors or external requests",
  );
  receipt.result = "passed";
} catch (error) {
  receipt.result = "failed";
  receipt.failure = error instanceof Error ? error.message : String(error);
  process.exitCode = 1;
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
  receipt.source_changes = [];
  for (const [name, digest] of Object.entries(inputs))
    if (sha(await fs.readFile(path.join(root, name))) !== digest)
      receipt.source_changes.push(name);
  if (receipt.source_changes.length) {
    receipt.result = "failed";
    receipt.failure = `Bundled source changed during run: ${receipt.source_changes.join(", ")}`;
    process.exitCode = 1;
  }
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
    { flag: "wx" },
  );
  console.log(
    JSON.stringify({
      result: receipt.result,
      cases: receipt.cases.length,
      screenshots: receipt.screenshots.length,
      receipt: path.join(out, "receipt.json"),
      failure: receipt.failure,
    }),
  );
}
