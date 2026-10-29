/* global process, URL, console, window, document, innerWidth, Event */
// Actual assistant components and original command hook; synthetic HTTP only.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(
  process.argv[2] ?? "/tmp/tender-assistant-review-browser",
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const sha = (data) => createHash("sha256").update(data).digest("hex");
await fs.mkdir(out, { recursive: true });
async function sourceHashes(directory = path.join(root, "src")) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const result = {};
  for (const entry of entries) {
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
import { AssistantActionCard } from "./src/AssistantActionCard";
import { AssistantSourcePicker } from "./src/AssistantSourcePicker";
import { ThemePicker } from "./src/ThemePicker";
import { useTheme } from "./src/theme";
import { setAuth } from "./src/api";
import { assistantReviewFixture, assistantReviewReference, assistantReviewOldVersion, assistantReviewScope } from "./src/assistantReviewFixtures.test-support";
import "./src/styles.css";
const params = new URLSearchParams(window.location.search);
const fixture = assistantReviewFixture({ long: params.has("long") });
window.__assistantReviewQA = fixture;
window.fetch = fixture.fetcher;
window.__assistantSelectionQA = { changes: 0, selected: [] };
setAuth({ member: { id: assistantReviewScope.memberId, display_name: "合成验收账号", active: true }, csrf_token: "synthetic-not-a-credential", expires_at: "2099-01-01T00:00:00Z" });
function Harness() {
  const theme = useTheme();
  const [generation, setGeneration] = useState(0);
  const [selected, setSelected] = useState([{ title: "进度条款原件", bidId: assistantReviewScope.bidId, reference: { ...assistantReviewReference, version: assistantReviewOldVersion } }]);
  window.__remountAssistantCard = () => setGeneration((value) => value + 1);
  window.__assistantSelectionQA.selected = selected;
  return <main className={"qa-assistant-review" + (params.has("narrow") ? " qa-assistant-review--narrow" : "")}>
    <header><h1>助手提议与来源核对</h1><p>合成验收：真实组件、本地测试资料与 HTTP；不表示真实项目采纳或模型质量通过。</p><ThemePicker {...theme}/></header>
    <AssistantActionCard key={generation} id={assistantReviewScope.actionId} memberId={assistantReviewScope.memberId}/>
    <section className="panel qa-assistant-review__sources"><AssistantSourcePicker bidId={assistantReviewScope.bidId} selected={selected} disabled={false} onChange={(next) => { window.__assistantSelectionQA.changes += 1; setSelected(next); }}/></section>
  </main>;
}
createRoot(document.getElementById("root")).render(<Harness/>);
`;
const built = await build({
  stdin: { contents: entry, loader: "tsx", resolveDir: root },
  bundle: true,
  metafile: true,
  format: "esm",
  jsx: "automatic",
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
const sourceInputs = {};
for (const name of Object.keys(built.metafile.inputs).sort()) {
  if (!name.startsWith("src/")) continue;
  const digest = sha(await fs.readFile(path.join(root, name)));
  if (before[name] !== digest)
    throw Error(`Source changed while bundling: ${name}; rebuild the fixture.`);
  sourceInputs[name] = digest;
}
await fs.copyFile(
  path.join(root, "public/theme.js"),
  path.join(out, "theme.js"),
);
await fs.writeFile(
  path.join(out, "fixture.css"),
  ".qa-assistant-review{max-width:1100px;margin:0 auto;padding:24px;min-width:0}.qa-assistant-review--narrow{max-width:468px}.qa-assistant-review>header{margin-bottom:24px}.qa-assistant-review h1{font-size:24px}.qa-assistant-review__sources{margin-top:24px;padding:20px;min-width:0}@media(max-width:600px){.qa-assistant-review{padding:12px}.qa-assistant-review__sources{padding:12px}}",
);
await fs.writeFile(
  path.join(out, "index.html"),
  '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>助手核对合成验收</title><script src="/theme.js"></script><link rel="stylesheet" href="/app.css"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script type="module" src="/app.js"></script></html>',
);
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
};
const server = http.createServer(async (req, res) => {
  try {
    const name = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
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
    const content = await fs.readFile(target);
    res.writeHead(200, {
      "Content-Type": types[path.extname(target)] ?? "application/octet-stream",
    });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const receipt = {
  recorded_at: new Date().toISOString(),
  scope:
    "Actual AssistantActionCard, AssistantSourcePicker, AssistantPatchComparison, AssistantSourceDetails, TextChangePreview, AuthoringRichSnapshot and useRecordedCommand. Immutable local bundle with explicit synthetic HTTP. No live backend, model, business result or mobile soft-keyboard acceptance.",
  source_inputs: sourceInputs,
  bundle_sha256: {
    "app.js": sha(await fs.readFile(path.join(out, "app.js"))),
    "app.css": sha(await fs.readFile(path.join(out, "app.css"))),
    "theme.js": sha(await fs.readFile(path.join(out, "theme.js"))),
    "fixture.css": sha(await fs.readFile(path.join(out, "fixture.css"))),
  },
  cases: [],
  screenshots: [],
  page_errors: [],
  external_requests: [],
};
let browser;
let lastPage;
function assert(value, message) {
  if (!value) throw Error(message);
}
async function screenshot(page, name) {
  const file = `${name}.png`;
  await page.screenshot({ path: path.join(out, file) });
  receipt.screenshots.push({
    file,
    sha256: sha(await fs.readFile(path.join(out, file))),
  });
}
async function checkLayout(page, state) {
  const result = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
    outside: [
      ...document.querySelectorAll("input,select,textarea,button,summary"),
    ]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return (
          el.getClientRects().length > 0 &&
          box.width > 0 &&
          (box.left < -1 || box.right > innerWidth + 1)
        );
      })
      .map((el) =>
        (el.getAttribute("aria-label") ?? el.textContent ?? el.tagName).slice(
          0,
          120,
        ),
      ),
    unexpected: window.__assistantReviewQA.state.unexpected,
  }));
  assert(
    result.scroll <= result.width + 1 &&
      !result.outside.length &&
      !result.unexpected.length,
    JSON.stringify({ state, result }),
  );
  return result;
}
async function open({ width = 390, theme = "light", query = "" } = {}) {
  const context = await browser.newContext({
    viewport: { width, height: width === 390 ? 844 : 900 },
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  lastPage = page;
  page.on("pageerror", (error) => receipt.page_errors.push(error.message));
  page.on("request", (request) => {
    if (!request.url().startsWith(`http://127.0.0.1:${server.address().port}/`))
      receipt.external_requests.push(request.url());
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/${query}`);
  await page
    .getByRole("button", { name: "应用这份正文修改", exact: true })
    .waitFor();
  await page.getByRole("checkbox", { name: /进度条款原件/ }).waitFor();
  await page.getByLabel("外观主题").selectOption(theme);
  await page.locator(`html[data-theme="${theme}"]`).waitFor();
  return { context, page };
}
async function openText(page, narrow) {
  const summary = page.getByText("查看具体文字增删", { exact: true });
  await summary.focus();
  await page.keyboard.press("Enter");
  await page.getByLabel("拟修改后全文", { exact: true }).waitFor();
  const full = await page.evaluate(() => ({
    before:
      document.querySelector('[aria-label="修改前全文"]').textContent ===
      window.__assistantReviewQA.expectedBefore,
    after:
      document.querySelector('[aria-label="拟修改后全文"]').textContent ===
      window.__assistantReviewQA.expectedAfter,
    removed: document.querySelectorAll("mark.text-change-preview__removed")
      .length,
    added: document.querySelectorAll("mark.text-change-preview__added").length,
    writes: window.__assistantReviewQA.state.writes.length,
  }));
  assert(
    full.before && full.after && full.removed > 0 && full.added > 0,
    JSON.stringify(full),
  );
  const switcher = page.getByRole("group", { name: "选择对照稿件" });
  assert(
    (await switcher.isVisible()) === narrow,
    "comparison width mode mismatch",
  );
  if (narrow) {
    assert(
      !(await page.getByLabel("修改前全文", { exact: true }).isVisible()),
      "both texts visible in narrow mode",
    );
    await switcher.getByRole("button", { name: "修改前", exact: true }).focus();
    await page.keyboard.press("Space");
    assert(
      await page.getByLabel("修改前全文", { exact: true }).isVisible(),
      "keyboard comparison switch failed",
    );
    assert(
      !(await page.getByLabel("拟修改后全文", { exact: true }).isVisible()),
      "proposal not hidden after switch",
    );
    await switcher
      .getByRole("button", { name: "拟修改后", exact: true })
      .click();
  } else {
    assert(
      await page.getByLabel("修改前全文", { exact: true }).isVisible(),
      "wide original pane missing",
    );
  }
  return full;
}
async function inspectFormat(page) {
  await page.getByText("查看完整原稿与格式", { exact: true }).click();
  const original = page.getByRole("region", {
    name: "完整原稿滚动区域",
    exact: true,
  });
  await original.waitFor();
  assert(
    (await original.locator("strong").textContent()) === "进度",
    "original emphasis missing",
  );
  assert((await original.locator("br").count()) > 0, "hard break missing");
  assert(
    (await original.locator("ol li").textContent()) === "保留清单第一项。",
    "list content missing",
  );
  assert(
    (await original.textContent()).includes("原稿尾段：保留现场核验。"),
    "original tail missing",
  );
  await page.getByText("查看完整原稿与格式", { exact: true }).click();
  await page.getByText("查看完整拟稿与格式", { exact: true }).click();
  const proposal = page.getByRole("region", {
    name: "完整拟稿滚动区域",
    exact: true,
  });
  await proposal.waitFor();
  assert(
    (await proposal.textContent()).includes("拟稿尾段：明确增派人员。"),
    "proposal tail missing",
  );
  await page.getByText("查看完整拟稿与格式", { exact: true }).click();
}
async function inspectSources(page) {
  const selected = page.getByRole("region", {
    name: "已选来源版本核对",
    exact: true,
  });
  await selected.locator("summary").click();
  assert(
    await selected.getByText("a".repeat(64), { exact: true }).isVisible(),
    "original selected version lost",
  );
  assert(
    await selected.getByText("b".repeat(64), { exact: true }).isVisible(),
    "current different version missing",
  );
  assert(
    await selected.getByText(/当前目录提供了不同版本/).isVisible(),
    "version change silently accepted",
  );
  const option = page
    .locator(".assistant-source-option")
    .filter({ has: page.getByRole("checkbox", { name: /进度条款原件/ }) });
  await option.getByText("核对来源版本与用途", { exact: true }).click();
  assert(
    await option
      .getByText(
        "助手讨论参考，不作为正式评分输入；来源文字不能授权执行操作。",
        { exact: true },
      )
      .isVisible(),
    "actual source scope missing",
  );
  const withdrawn = page
    .locator(".assistant-source-option")
    .filter({ has: page.getByRole("checkbox", { name: /已撤回的补充原件/ }) });
  assert(
    await withdrawn.getByRole("checkbox").isDisabled(),
    "withdrawn source selectable",
  );
  await withdrawn.locator("summary").click();
  assert(
    await withdrawn
      .getByText("服务器未提供可用版本凭据", { exact: true })
      .isVisible(),
    "withdrawn source invented a version",
  );
  assert(
    await withdrawn.getByText("来源已撤回。", { exact: true }).isVisible(),
    "withdrawal missing",
  );
  const unchanged = await page.evaluate(() => ({
    writes: window.__assistantReviewQA.state.writes.length,
    changes: window.__assistantSelectionQA.changes,
    version: window.__assistantSelectionQA.selected[0].reference.version,
  }));
  assert(
    unchanged.writes === 0 &&
      unchanged.changes === 0 &&
      unchanged.version === "a".repeat(64),
    JSON.stringify(unchanged),
  );
  await selected.evaluate((el) => el.scrollIntoView({ block: "start" }));
  return { selected, option, unchanged };
}
try {
  browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  receipt.browser = await browser.version();
  for (const width of [1280, 768, 390]) {
    for (const theme of ["light", "dark"]) {
      const { page, context } = await open({ width, theme });
      const name = `${theme}-${width}`;
      const full = await openText(page, width < 1000);
      assert(full.writes === 0, "opening text applied action");
      await inspectFormat(page);
      await page
        .locator(".assistant-card-preview")
        .evaluate((el) => el.scrollIntoView({ block: "start" }));
      await checkLayout(page, `${name}-comparison`);
      await screenshot(page, `comparison-${name}`);
      const sources = await inspectSources(page);
      await checkLayout(page, `${name}-sources`);
      await screenshot(page, `sources-${name}`);
      await sources.option.getByRole("checkbox").check();
      const selection = await page.evaluate(() => ({
        changes: window.__assistantSelectionQA.changes,
        version: window.__assistantSelectionQA.selected[0].reference.version,
      }));
      assert(
        selection.changes === 1 && selection.version === "b".repeat(64),
        "explicit source replacement failed",
      );
      await page
        .getByRole("button", { name: "应用这份正文修改", exact: true })
        .click();
      await page.getByText("已执行并留存结果", { exact: true }).waitFor();
      const effect = await page.evaluate(() => ({
        writes: window.__assistantReviewQA.state.writes,
        applied: window.__assistantReviewQA.state.applied,
      }));
      assert(
        effect.applied === 1 &&
          effect.writes.length === 1 &&
          effect.writes[0].body.decision === "confirm" &&
          !!effect.writes[0].key &&
          effect.writes[0].etag === '"action:1"',
        "explicit apply did not preserve original command semantics",
      );
      assert(
        (await page
          .getByRole("button", { name: "应用这份正文修改", exact: true })
          .count()) === 0,
        "executed card still offered apply",
      );
      await checkLayout(page, `${name}-executed`);
      receipt.cases.push({
        name,
        assertions: [
          "complete_text",
          "marks_breaks_list",
          "keyboard_expansion",
          "responsive_diff",
          "original_source_version",
          "no_apply_on_inspection",
          "withdrawn_source_disabled",
          "explicit_selection_only",
          "explicit_confirm_once",
          "layout",
        ],
        expected_text_length: await page.evaluate(
          () => window.__assistantReviewQA.expectedAfter.length,
        ),
      });
      await context.close();
    }
  }
  {
    const { page, context } = await open({
      width: 1280,
      theme: "dark",
      query: "?narrow=1",
    });
    const full = await openText(page, true);
    assert(full.writes === 0, "narrow inspection applied action");
    await page
      .locator(".assistant-card-preview")
      .evaluate((el) => el.scrollIntoView({ block: "start" }));
    await checkLayout(page, "desktop-narrow-card");
    await screenshot(page, "comparison-dark-1280-narrow");
    receipt.cases.push({
      name: "desktop-narrow-card",
      assertions: [
        "container_query_single_pane",
        "keyboard_switch",
        "complete_text",
        "no_apply",
        "layout",
      ],
    });
    await context.close();
  }
  {
    const { page, context } = await open({
      width: 390,
      theme: "dark",
      query: "?long=1",
    });
    const full = await openText(page, true);
    assert(full.writes === 0, "long inspection applied action");
    const length = await page.evaluate(
      () => window.__assistantReviewQA.expectedAfter.length,
    );
    assert(length > 100000, "long fixture too short");
    await page.getByLabel("拟修改后全文", { exact: true }).evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    await page.getByText("查看完整拟稿与格式", { exact: true }).click();
    const proposal = page.getByRole("region", {
      name: "完整拟稿滚动区域",
      exact: true,
    });
    await proposal.waitFor();
    const complete = await proposal.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
      const tail = [...el.querySelectorAll(".rich-snapshot p")].at(-1);
      const tailBox = tail?.getBoundingClientRect();
      const regionBox = el.getBoundingClientRect();
      return {
        scrollable: el.scrollHeight > el.clientHeight,
        atEnd: el.scrollHeight - el.clientHeight - el.scrollTop < 2,
        tail: tail?.textContent === "拟稿尾段：明确增派人员。",
        tailInRegion:
          !!tailBox &&
          tailBox.top >= regionBox.top &&
          tailBox.bottom <= regionBox.bottom,
      };
    });
    assert(
      complete.scrollable &&
        complete.atEnd &&
        complete.tail &&
        complete.tailInRegion,
      JSON.stringify(complete),
    );
    await proposal.evaluate((el) => el.scrollIntoView({ block: "center" }));
    await checkLayout(page, "long-390");
    await screenshot(page, "long-tail-dark-390");
    receipt.cases.push({
      name: "long-390",
      expected_text_length: length,
      assertions: [
        "full_exact_original_and_proposal",
        "bounded_display_not_truncation",
        "formatted_tail_reachable",
        "no_apply",
        "layout",
      ],
    });
    await context.close();
  }
  {
    const { page, context } = await open({ width: 390, theme: "light" });
    await openText(page, true);
    await page.evaluate(() => {
      window.__assistantReviewQA.state.resolveMode = "withdrawn";
    });
    await page
      .getByRole("button", { name: "应用这份正文修改", exact: true })
      .click();
    await page.getByText("依据已变化，未执行", { exact: true }).waitFor();
    const state = await page.evaluate(() => ({
      applied: window.__assistantReviewQA.state.applied,
      writes: window.__assistantReviewQA.state.writes.length,
    }));
    assert(state.applied === 0 && state.writes === 1, JSON.stringify(state));
    assert(
      (await page
        .getByRole("button", { name: "应用这份正文修改", exact: true })
        .count()) === 0,
      "stale action can be confirmed",
    );
    await page
      .locator(".assistant-action-card")
      .evaluate((el) => el.scrollIntoView({ block: "start" }));
    await checkLayout(page, "withdrawn-at-confirm");
    await screenshot(page, "withdrawn-at-confirm-light-390");
    receipt.cases.push({
      name: "withdrawn-at-confirm",
      assertions: [
        "read_only_preview",
        "server_revalidation",
        "stale_no_business_effect",
        "no_second_confirm",
        "layout",
      ],
    });
    await context.close();
  }
  {
    const { page, context } = await open({ width: 390, theme: "dark" });
    await page.evaluate(() => {
      window.__assistantReviewQA.state.resolveMode = "lost_ack";
    });
    await page
      .getByRole("button", { name: "应用这份正文修改", exact: true })
      .click();
    await page
      .getByRole("button", { name: "恢复原操作结果", exact: true })
      .waitFor();
    const first = await page.evaluate(
      () => window.__assistantReviewQA.state.writes[0],
    );
    await openText(page, true);
    await page.evaluate(() => window.__remountAssistantCard());
    await page.getByText("已执行并留存结果", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "恢复原操作结果", exact: true })
      .waitFor();
    assert(
      (await page
        .getByRole("button", { name: "应用这份正文修改", exact: true })
        .count()) === 0,
      "pending recovery offered new confirm",
    );
    const pending = await page.evaluate(
      () => window.__assistantReviewQA.state.writes.length,
    );
    assert(pending === 1, "inspection or remount resubmitted action");
    await page
      .getByRole("button", { name: "恢复原操作结果", exact: true })
      .click();
    await page
      .getByRole("button", { name: "恢复原操作结果", exact: true })
      .waitFor({ state: "detached" });
    const recovered = await page.evaluate(() => ({
      applied: window.__assistantReviewQA.state.applied,
      writes: window.__assistantReviewQA.state.writes,
    }));
    assert(
      recovered.applied === 1 &&
        recovered.writes.length === 2 &&
        JSON.stringify(recovered.writes[1]) === JSON.stringify(first),
      "original command changed or effect duplicated",
    );
    await page
      .locator(".assistant-action-card")
      .evaluate((el) => el.scrollIntoView({ block: "start" }));
    await checkLayout(page, "lost-ack-remount-recovery");
    await screenshot(page, "recovered-dark-390");
    receipt.cases.push({
      name: "lost-ack-remount-recovery",
      assertions: [
        "no_replay_on_preview_or_remount",
        "original_key_body_if_match",
        "pending_survives_remount",
        "one_effect",
        "layout",
      ],
    });
    await context.close();
  }
  {
    const { page, context } = await open({ width: 390, theme: "light" });
    const { selected } = await inspectSources(page);
    await page.evaluate(() => {
      window.__assistantReviewQA.state.sourceReadFailure = true;
      window.dispatchEvent(new Event("server-snapshot-change"));
    });
    await page.getByText("合成目录暂时无法读取。", { exact: true }).waitFor();
    assert(
      await selected.getByText(/当前目录尚未核对到这个精确来源/).isVisible(),
      "stale directory claimed current status",
    );
    assert(
      await selected.getByText("a".repeat(64), { exact: true }).isVisible(),
      "read failure lost original version",
    );
    assert(
      await page.getByRole("checkbox", { name: /进度条款原件/ }).isDisabled(),
      "stale directory selectable",
    );
    assert(
      await page.evaluate(
        () =>
          window.__assistantSelectionQA.changes === 0 &&
          window.__assistantReviewQA.state.writes.length === 0,
      ),
      "read failure mutated selection or action",
    );
    await selected.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await checkLayout(page, "source-directory-error");
    await screenshot(page, "source-unverified-light-390");
    receipt.cases.push({
      name: "source-directory-error",
      assertions: [
        "original_selection_kept",
        "availability_unverified",
        "stale_choices_disabled",
        "no_write",
        "layout",
      ],
    });
    await context.close();
  }
  assert(
    !receipt.page_errors.length && !receipt.external_requests.length,
    JSON.stringify({
      errors: receipt.page_errors,
      external: receipt.external_requests,
    }),
  );
  receipt.status = "passed";
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      status: receipt.status,
      cases: receipt.cases.length,
      screenshots: receipt.screenshots.length,
      source_inputs: Object.keys(sourceInputs).length,
      page_errors: receipt.page_errors,
      external_requests: receipt.external_requests,
      receipt: path.join(out, "receipt.json"),
    }),
  );
} catch (error) {
  receipt.status = "failed";
  receipt.error = error instanceof Error ? error.message : String(error);
  if (lastPage && !lastPage.isClosed()) {
    await lastPage.screenshot({ path: path.join(out, "failure.png") });
    await fs.writeFile(
      path.join(out, "failure.html"),
      await lastPage.content(),
    );
  }
  await fs.writeFile(
    path.join(out, "receipt.json"),
    JSON.stringify(receipt, null, 2) + "\n",
  );
  throw error;
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
