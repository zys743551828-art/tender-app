// Local synthetic pages share the existing production CSS and bundled PDF runtime.
import { build } from "esbuild";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
export async function buildFixture(
  entryPoint,
  name,
  title,
  page = `${name}.html`,
) {
  const html = await readFile("dist/index.html", "utf8");
  const css = html.match(/href="([^" ]+\.css)"/)[1];
  await mkdir("dist/_qa", { recursive: true });
  await copyFile(
    "node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
    "dist/_qa/pdf.worker.min.mjs",
  );
  await build({
    entryPoints: [entryPoint],
    outfile: `dist/_qa/${name}.js`,
    bundle: true,
    format: "esm",
    jsx: "automatic",
    define: { "process.env.NODE_ENV": '"production"' },
    minify: true,
    plugins: [
      {
        name: "qa-vite-worker-url",
        setup(builder) {
          builder.onResolve(
            { filter: /^pdfjs-dist\/build\/pdf\.worker\.min\.mjs\?url$/ },
            () => ({ path: "pdf-worker-url", namespace: "qa-url" }),
          );
          builder.onLoad({ filter: /.*/, namespace: "qa-url" }, () => ({
            contents: 'export default "/_qa/pdf.worker.min.mjs";',
            loader: "js",
          }));
        },
      },
    ],
  });
  await writeFile(
    `dist/_qa/${page}`,
    `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><link rel="stylesheet" href="${css}"><link rel="stylesheet" href="./${name}.css"></head><body><div id="root"></div><script type="module" src="./${name}.js"></script></body></html>`,
  );
}
