// Run from apps/web after the normal Vite build. The next production build removes _qa.
import { build } from "esbuild";
import { mkdir, readFile, writeFile } from "node:fs/promises";
const index = await readFile("dist/index.html", "utf8");
const css = index.match(/href="([^" ]+\.css)"/)[1];
await mkdir("dist/_qa", { recursive: true });
await build({
  entryPoints: ["qa-previews/frozen-inputs/fixture.tsx"],
  outfile: "dist/_qa/freeze.js",
  bundle: true,
  format: "esm",
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  minify: true,
});
await writeFile(
  "dist/_qa/index.html",
  `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>合成界面核验</title><link rel="stylesheet" href="${css}"><link rel="stylesheet" href="./freeze.css"></head><body><div id="root"></div><script type="module" src="./freeze.js"></script></body></html>`,
);
