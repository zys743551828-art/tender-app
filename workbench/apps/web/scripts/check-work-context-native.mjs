/* global Buffer, console, process, URL */
// Replay unchanged synthetic native HTTP JSON through the current TS validators.
// Usage: node scripts/check-work-context-native.mjs BUNDLE.json NEW_RECEIPT.json
import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build, version as esbuildVersion } from "esbuild";

const scriptPath = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(scriptPath), "..");
const [bundleArgument, receiptArgument, ...extra] = process.argv.slice(2);
if (!bundleArgument || !receiptArgument || extra.length) {
  throw new Error(
    "Usage: node scripts/check-work-context-native.mjs BUNDLE.json NEW_RECEIPT.json",
  );
}
const inputPath = path.resolve(bundleArgument);
const receiptPath = path.resolve(receiptArgument);
assert.notEqual(inputPath, receiptPath, "Receipt must not replace the input");
const compiledPath = `${receiptPath}.validators.mjs`;
// Independent receipts preserve both failures and later corrections.
await fs.mkdir(path.dirname(receiptPath), { recursive: true });
const receiptFile = await fs.open(receiptPath, "wx");
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const sourceHashes = new Map();
const expectedLabels = [
  "package_review_run",
  "package_submission",
  "choices_package_review_run",
  "choices_package_submission",
  "draft_snapshot",
  "build",
  "build_relations",
  "draft_snapshot_sparse_ordinal",
  "draft_snapshot_rich",
  "choices_draft_snapshot",
  "choices_build",
  "historical_image_metadata",
];
const receipt = {
  version: "work-context-native-frontend/1",
  passed: false,
  started_at: new Date().toISOString(),
  node: process.version,
  esbuild: esbuildVersion,
  input: { path: inputPath, sha256: null, bytes: null, unchanged: false },
  compiled_validators: { path: compiledPath, sha256: null },
  source_sha256: {},
  sources_unchanged: false,
  synthetic_only: true,
  responses_expected: 12,
  protocol_checks_expected: 11,
  body_values_modified: false,
  checks: [],
  limitations: [
    "Offline replay of real routed native API JSON from explicit synthetic fixtures; no live database or HTTP request is performed by this script.",
    "Image bytes are the native test fixture's normalized PNG, not a captured bytes HTTP response; metadata/binding/hash/IHDR consistency does not assert browser decoding or transport correctness.",
    "No renderer, navigation, pagination interaction, permissions, real document quality or prediction quality is established by this replay alone.",
  ],
};
let initialInput;

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

async function check(label, kind, action) {
  try {
    await action();
    receipt.checks.push({ label, kind, passed: true });
    return true;
  } catch (error) {
    receipt.checks.push({
      label,
      kind,
      passed: false,
      error: String(error instanceof Error ? error.message : error).slice(
        0,
        500,
      ),
    });
    return false;
  }
}

try {
  initialInput = await fs.readFile(inputPath);
  receipt.input.sha256 = hash(initialInput);
  receipt.input.bytes = initialInput.length;
  const bundle = freeze(JSON.parse(initialInput.toString("utf8")));
  assert.equal(bundle.version, "synthetic-work-context-http-bundle/1");
  assert.equal(bundle.synthetic, true, "Only explicit synthetic fixtures");
  assert.ok(Array.isArray(bundle.responses));
  assert.deepEqual(
    bundle.responses.map((row) => row.label).sort(),
    [...expectedLabels].sort(),
    "Require all 11 native contexts/directories/relations and image metadata",
  );
  const rows = new Map(bundle.responses.map((row) => [row.label, row]));
  const bodyBefore = new Map();
  for (const row of bundle.responses) {
    assert.equal(row.status, 200);
    assert.ok(row.body && typeof row.body === "object");
    const url = new URL(row.path);
    assert.equal(url.username, "");
    assert.equal(url.password, "");
    assert.equal(url.hash, "");
    bodyBefore.set(row.label, JSON.stringify(row.body));
  }

  // Record the actual bytes supplied to esbuild, not hashes read after bundling.
  for (const name of [
    "scripts/check-work-context-native.mjs",
    "package.json",
    "package-lock.json",
  ]) {
    sourceHashes.set(name, hash(await fs.readFile(path.join(root, name))));
  }
  const compiled = await build({
    absWorkingDir: root,
    stdin: {
      contents: `
export { validateAuthoringWorkContext } from "./src/workContextAuthoringProtocol";
export { validatePackageWorkContext } from "./src/workContextProtocol";
export { validateWorkContextChoices, validateWorkContextRelations, workContextSelectionId } from "./src/workContextDirectoryProtocol";
`,
      resolveDir: root,
      sourcefile: "native-response-entry.ts",
      loader: "ts",
    },
    bundle: true,
    platform: "node",
    format: "esm",
    write: false,
    metafile: true,
    logLevel: "silent",
    plugins: [
      {
        name: "record-exact-source-bytes",
        setup(builder) {
          builder.onLoad(
            { filter: /\.(ts|tsx|js|jsx|json)$/ },
            async (args) => {
              const relative = path.relative(root, args.path);
              if (
                relative.startsWith("..") ||
                relative.split(path.sep).includes("node_modules")
              )
                return;
              const contents = await fs.readFile(args.path);
              sourceHashes.set(relative, hash(contents));
              return {
                contents,
                loader: path.extname(args.path).slice(1),
              };
            },
          );
        },
      },
    ],
  });
  assert.equal(compiled.outputFiles.length, 1);
  const compiledBytes = compiled.outputFiles[0].contents;
  receipt.compiled_validators.sha256 = hash(compiledBytes);
  await fs.writeFile(compiledPath, compiledBytes, { flag: "wx" });
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
  const validators = await import(pathToFileURL(compiledPath).href);
  let verifiedBuild;
  let verifiedRich;
  // Relations only see the successful outputs of a fully validated exact build.
  for (const label of [
    "build",
    ...expectedLabels.filter(
      (item) => item !== "build" && item !== "historical_image_metadata",
    ),
  ]) {
    const row = rows.get(label);
    await check(label, "current_ts_protocol", async () => {
      const url = new URL(row.path);
      const data = row.body;
      if (label.startsWith("choices_")) {
        const match = url.pathname.match(
          /^\/api\/v1\/bids\/([^/]+)\/work-contexts\/choices$/,
        );
        assert.ok(match, "Wrong directory endpoint");
        const kind = label.slice("choices_".length);
        assert.deepEqual(url.searchParams.getAll("kind"), [kind]);
        await validators.validateWorkContextChoices(data, match[1], kind);
      } else if (label === "build_relations") {
        assert.ok(verifiedBuild, "The exact build must first pass validation");
        assert.equal(
          url.pathname,
          `/api/v1/bids/${verifiedBuild.selection.bid_id}/work-contexts/build/${verifiedBuild.selection.build_id}/relations`,
        );
        assert.deepEqual(url.searchParams.getAll("target"), [
          "package_revision",
        ]);
        await validators.validateWorkContextRelations(
          data,
          verifiedBuild.selection,
          verifiedBuild.build.outputs,
        );
      } else {
        const match = url.pathname.match(
          /^\/api\/v1\/bids\/([^/]+)\/work-contexts\/(draft_snapshot|build|package_review_run|package_submission)\/([^/]+)$/,
        );
        assert.ok(match, "Wrong exact resolver endpoint");
        const target = {
          kind: match[2],
          id: match[3],
          selectionDigest: data.selection_digest,
        };
        const validate = ["draft_snapshot", "build"].includes(match[2])
          ? validators.validateAuthoringWorkContext
          : validators.validatePackageWorkContext;
        const verified = await validate(data, match[1], target);
        assert.equal(
          validators.workContextSelectionId(verified.selection),
          match[3],
        );
        if (label === "build") verifiedBuild = verified;
        if (label === "draft_snapshot_rich") verifiedRich = verified;
      }
      assert.equal(
        JSON.stringify(row.body),
        bodyBefore.get(label),
        "A validator changed the native response",
      );
    });
  }

  let verifiedImage;
  await check("historical_image_metadata", "image_binding_consistency", () => {
    assert.ok(verifiedRich?.document, "Rich snapshot must pass validation");
    const row = rows.get("historical_image_metadata");
    const image = row.body;
    const binding = verifiedRich.document.images.find(
      (item) => item.asset_version_id === image.id,
    );
    assert.ok(binding, "Metadata is absent from the frozen image list");
    assert.equal(image.bid_id, verifiedRich.selection.bid_id);
    assert.equal(image.asset_id, binding.asset_id);
    assert.equal(image.id, binding.asset_version_id);
    assert.equal(image.revision, binding.asset_revision);
    assert.equal(image.digest, binding.version_digest);
    assert.equal(binding.media_type, "image/png");
    assert.equal(
      new URL(row.path).pathname,
      `/api/v1/bids/${image.bid_id}/authoring-images/${image.asset_id}/versions/${image.id}`,
    );
    const proof = image.normalization_proof;
    assert.equal(proof.protocol, "authoring-raster-normalization/1");
    assert.equal(proof.output_media_type, "image/png");
    assert.equal(proof.output_digest, binding.normalized_sha256);
    assert.ok(Number.isSafeInteger(proof.output_byte_size));
    assert.ok(proof.output_byte_size > 0 && proof.output_byte_size <= 16777216);
    for (const key of ["width_px", "height_px"]) {
      assert.ok(Number.isSafeInteger(image[key]));
      assert.ok(image[key] > 0 && image[key] <= 10000);
      assert.equal(proof[key], image[key]);
    }
    assert.ok(image.width_px * image.height_px <= 16000000);
    verifiedImage = image;
  });
  await check("synthetic_normalized_png", "image_byte_consistency", () => {
    assert.ok(verifiedImage, "Metadata must match the frozen image binding");
    const supplied = bundle.synthetic_normalized_image;
    assert.equal(supplied.asset_id, verifiedImage.asset_id);
    assert.equal(supplied.asset_version_id, verifiedImage.id);
    assert.equal(supplied.media_type, "image/png");
    assert.equal(typeof supplied.base64, "string");
    assert.ok(supplied.base64.length <= 22369624);
    const bytes = Buffer.from(supplied.base64, "base64");
    assert.equal(
      bytes.toString("base64"),
      supplied.base64,
      "Non-canonical base64",
    );
    assert.equal(
      bytes.length,
      verifiedImage.normalization_proof.output_byte_size,
    );
    assert.equal(hash(bytes), supplied.sha256);
    assert.equal(hash(bytes), verifiedImage.normalization_proof.output_digest);
    assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    assert.equal(bytes.readUInt32BE(8), 13, "PNG IHDR length");
    assert.equal(bytes.subarray(12, 16).toString("ascii"), "IHDR");
    assert.equal(bytes.readUInt32BE(16), verifiedImage.width_px);
    assert.equal(bytes.readUInt32BE(20), verifiedImage.height_px);
  });
  receipt.body_values_modified = bundle.responses.some(
    (row) => JSON.stringify(row.body) !== bodyBefore.get(row.label),
  );
  assert.equal(receipt.body_values_modified, false);
  assert.equal(receipt.checks.length, 13);
  receipt.passed = receipt.checks.every((item) => item.passed);
} catch (error) {
  receipt.error = String(error instanceof Error ? error.message : error).slice(
    0,
    1000,
  );
} finally {
  try {
    receipt.input.unchanged =
      initialInput !== undefined &&
      hash(await fs.readFile(inputPath)) === hash(initialInput);
    receipt.source_sha256 = Object.fromEntries(
      [...sourceHashes].sort(([a], [b]) => a.localeCompare(b)),
    );
    receipt.sources_unchanged =
      sourceHashes.size > 3 &&
      (
        await Promise.all(
          [...sourceHashes].map(
            async ([name, digest]) =>
              digest === hash(await fs.readFile(path.join(root, name))),
          ),
        )
      ).every(Boolean);
    receipt.passed &&= receipt.input.unchanged && receipt.sources_unchanged;
  } catch (error) {
    receipt.passed = false;
    receipt.finalization_error = String(error);
  }
  receipt.finished_at = new Date().toISOString();
  await receiptFile.writeFile(JSON.stringify(receipt, null, 2) + "\n");
  await receiptFile.close();
}
console.log(
  JSON.stringify({
    passed: receipt.passed,
    checks: receipt.checks.length,
    accepted: receipt.checks.filter((item) => item.passed).length,
    receipt: receiptPath,
  }),
);
if (!receipt.passed) process.exitCode = 1;
