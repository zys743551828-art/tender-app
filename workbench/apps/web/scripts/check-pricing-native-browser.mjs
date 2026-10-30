/* global process, console, URL */
// Real PricingPanel + native HTTP. No fetch interception or model calls.
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { journeys } from "./native-workspace-journeys.mjs";

let input = "";
for await (const piece of process.stdin) input += piece;
const config = JSON.parse(input);
const backend = new URL(config.backend);
assert.equal(backend.hostname, "127.0.0.1");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temporary = await fs.mkdtemp(
  path.join(os.tmpdir(), "pricing-native-ui-"),
);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const entry = config.journeys
  ? `
import React from "react";
import {createRoot} from "react-dom/client";
import {App} from "./src/App";
import "./src/styles.css";
createRoot(document.getElementById("root")).render(<App/>);
`
  : `
import React from "react";
import {createRoot} from "react-dom/client";
import {setAuth} from "./src/api";
import {PricingPanel} from "./src/PricingPanel";
import "./src/styles.css";
const response=await fetch('/api/v1/auth/session');
if (!response.ok) throw new Error('Native session unavailable');
const auth=await response.json();setAuth(auth);
createRoot(document.getElementById('root')).render(<PricingPanel bidId=${JSON.stringify(config.bid)} memberId={auth.member.id} onSettings={()=>{}}/>);
`;
let server, browser;
const errors = [];
const cases = [];
try {
  await build({
    stdin: { contents: entry, resolveDir: root, loader: "tsx" },
    outfile: path.join(temporary, "app.js"),
    bundle: true,
    format: "esm",
    jsx: "automatic",
    loader: { ".woff2": "file" },
    external: ["/fonts/*"],
    plugins: [
      {
        name: "native-asset-urls",
        setup(builder) {
          builder.onResolve({ filter: /\?url$/ }, (args) => ({
            path: require.resolve(args.path.slice(0, -4)),
            namespace: "asset-url",
          }));
          builder.onLoad(
            { filter: /.*/, namespace: "asset-url" },
            async (args) => {
              const name = path.basename(args.path);
              await fs.copyFile(args.path, path.join(temporary, name));
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
  server = http.createServer(async (request, response) => {
    if (request.url.startsWith("/api/v1/")) {
      const forwarded = http.request(
        new URL(request.url, backend),
        {
          method: request.method,
          headers: { ...request.headers, host: backend.host },
        },
        (upstream) => {
          response.writeHead(upstream.statusCode, upstream.headers);
          upstream.pipe(response);
        },
      );
      response.on("close", () => forwarded.destroy());
      forwarded.on("error", () => {
        if (response.destroyed) return;
        if (!response.headersSent) response.writeHead(502);
        response.end("native API unavailable");
      });
      request.pipe(forwarded);
      return;
    }
    if (!path.extname(new URL(request.url, "http://localhost").pathname)) {
      response.setHeader("Content-Type", "text/html;charset=utf-8");
      response.end(
        '<!doctype html><html lang="zh-CN"><head><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>',
      );
      return;
    }
    const name = path.basename(
      new URL(request.url, "http://localhost").pathname,
    );
    try {
      const raw = await fs.readFile(path.join(temporary, name));
      response.setHeader(
        "Content-Type",
        name.endsWith(".js")
          ? "text/javascript"
          : name.endsWith(".css")
            ? "text/css"
            : "application/octet-stream",
      );
      response.end(raw);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((resolve) =>
    server.listen(config.port, "127.0.0.1", resolve),
  );
  const origin = `http://127.0.0.1:${config.port}`;
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  if (config.journeys) {
    cases.push(await journeys({ browser, origin, config }));
  } else
    for (const width of [1280, 390]) {
      const context = await browser.newContext({
        viewport: { width, height: 1000 },
      });
      await context.addCookies([
        {
          name: "session",
          value: config.cookie,
          url: origin,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("response", (response) => {
        if (
          new URL(response.url()).pathname.startsWith("/api/v1/") &&
          response.status() >= 400
        )
          errors.push(`native HTTP ${response.status()}`);
      });
      await page.goto(origin);
      try {
        await page.getByLabel(/^本次投标包/).waitFor({ timeout: 10000 });
      } catch (failure) {
        throw new Error(
          `Native pricing UI unavailable: ${JSON.stringify({ errors, body: (await page.locator("body").innerText()).slice(0, 1200) })}`,
          { cause: failure },
        );
      }
      await page
        .getByLabel(/^本次投标包/)
        .selectOption(
          `${config.binding.package_id}:${config.binding.revision_id}`,
        );
      await page
        .getByLabel(/^本次招标与补遗包/)
        .selectOption(
          `${config.binding.authority_package_id}:${config.binding.authority_revision_id}`,
        );
      await page
        .getByRole("button", { name: "使用这两份修订继续报价" })
        .click();
      await page
        .locator(".pricing-plan-summary")
        .nth(config.expected.length - 1)
        .waitFor();
      const rows = await page
        .locator(".pricing-plan-summary")
        .allTextContents();
      assert.equal(rows.length, config.expected.length);
      rows.forEach((text, index) => {
        assert.ok(
          text.includes(config.expected[index].slice(0, 8)),
          "native UI chronological order",
        );
        assert.ok(
          text.includes("25.00"),
          "native persisted hand-calculated score",
        );
      });
      await page.reload();
      await page
        .locator(".pricing-plan-summary")
        .nth(config.expected.length - 1)
        .waitFor();
      const after = await page
        .locator(".pricing-plan-summary")
        .allTextContents();
      assert.deepEqual(
        after,
        rows,
        "reload preserves package choice and persisted order",
      );
      cases.push({
        width,
        plans: rows.length,
        real_http: true,
        reload_consistent: true,
      });
      await context.close();
    }
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      kind: "synthetic-pricing-native-browser",
      real_database: true,
      real_private_s3: true,
      model_calls: 0,
      cases,
    }),
  );
} finally {
  if (browser) await browser.close();
  if (server) {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
  await fs.rm(temporary, { recursive: true, force: true });
}
