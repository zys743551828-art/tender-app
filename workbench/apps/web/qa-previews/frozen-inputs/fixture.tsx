import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import Workspace from "../../src/PackageFrozenInputWorkspace";
import {
  frozenManifestDigest,
  freezeStorageKey,
} from "../../src/packageFrozenInput";
import type { FreezeScope } from "../../src/packageFrozenInput";
import type {
  FreezePackageReviewInput,
  PackageReviewFrozenInputView,
} from "../../src/contracts";
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope: FreezeScope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const body: FreezePackageReviewInput = {
  package_digest: "a".repeat(64),
  inventory_digest: "b".repeat(64),
  input_digest: "c".repeat(64),
  context_digest: "d".repeat(64),
  coverage_attempt_id: null,
  coverage_digest: null,
};
async function reply(): Promise<PackageReviewFrozenInputView> {
  const manifest: PackageReviewFrozenInputView["manifest"] = {
    version: "package-review-frozen-input/1",
    kind: "frozen_input",
    id: id(6),
    bid_id: scope.bidId,
    package_id: scope.packageId,
    revision_id: scope.revisionId,
    inventory_id: scope.inventoryId,
    actor_id: scope.memberId,
    command_id: id(7),
    input_digest: body.input_digest,
    context_digest: body.context_digest,
    evidence_digest: "e".repeat(64),
    as_of: "2026-10-19T08:00:00Z",
    frozen_at: "2026-10-19T08:00:01Z",
    blockers: ["PACKAGE_REVIEW_EXECUTOR_NOT_READY"],
    review_ready: false,
    launch_available: false,
    execution_context: {
      version: "package-review-context/1",
      kind: "candidate",
      input_digest: body.input_digest,
      semantic_digest: body.context_digest,
      snapshot_digest: "1".repeat(64),
      as_of: "2026-10-19T08:00:00Z",
      purpose: "prebid_compliance",
      method_digest: "2".repeat(64),
      policy_digest: "3".repeat(64),
      facts_digest: "4".repeat(64),
      sources_digest: "5".repeat(64),
      fact_set_id: null,
      fact_count: 0,
      confirmed_fact_count: 0,
      facts_binding: "empty",
      executor_available: false,
      formal_scoring_eligible: false,
    },
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}

let offline = true;
async function historical(n: number) {
  const record = await reply();
  record.manifest.id = id(6 + n);
  record.manifest.frozen_at =
    n === 0
      ? "2026-10-19T08:00:01Z"
      : `2026-10-19T08:00:00.${String(1000000 - n).padStart(6, "0")}Z`;
  record.digest = await frozenManifestDigest(record.manifest);
  return record;
}
window.fetch = async (path) => {
  const url = String(path);
  if (!url.includes("/frozen-review-inputs"))
    throw new Error("夹具拒绝业务请求");
  if (offline) throw new Error("合成场景：保存回执丢失，请恢复原请求。");
  if (url.endsWith("/execution-check")) {
    const selectedId = url.split("/").at(-2);
    const n = [id(6), id(7), id(8)].indexOf(selectedId ?? "");
    const record = await historical(n < 0 ? 0 : n);
    return new Response(
      JSON.stringify({
        kind: "eligibility_observation",
        frozen_input_id: record.manifest.id,
        frozen_digest: record.digest,
        input_digest: record.manifest.input_digest,
        checked_at: "2026-10-19T08:02:00Z",
        current_context: {
          ...record.manifest.execution_context,
          as_of: "2026-10-19T08:02:00Z",
          snapshot_digest: "7".repeat(64),
        },
        parse_evidence_status: "matched",
        original_verification: "not_performed",
        review_ready: false,
        launch_available: false,
        publication_authorized: false,
        blockers: [
          "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
          "PACKAGE_REVIEW_FACTS_UNPROVEN",
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }
  const list = url.includes("?limit=");
  const more = url.includes("cursor=");
  const items = await Promise.all(
    (more ? [2] : [0, 1]).map(async (n) => {
      const record = await historical(n);
      const m = record.manifest;
      return {
        id: m.id,
        digest: record.digest,
        actor_id: m.actor_id,
        frozen_at: m.frozen_at,
        input_digest: m.input_digest,
        context_digest: m.context_digest,
      };
    }),
  );
  const selected = [id(7), id(8)].indexOf(url.split("/").at(-1) ?? "");
  const data = list
    ? {
        bid_id: scope.bidId,
        package_id: scope.packageId,
        revision_id: scope.revisionId,
        inventory_id: scope.inventoryId,
        items,
        has_more: !more,
        next_cursor: more ? null : "synthetic-next-page",
      }
    : await historical(selected < 0 ? 0 : selected + 1);
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
function Fixture() {
  const [width, setWidth] = useState("1200");
  const [serial, setSerial] = useState(0);
  return (
    <main
      style={{ padding: 16, maxWidth: Number(width), margin: "auto" }}
      data-testid="qa-shell"
    >
      <h2>冻结输入界面 · 合成验证夹具</h2>
      <p>
        仅检查真实组件的交互与容器布局。所有请求在页面内模拟，不连接业务库，不代表真实原件或正式评审通过。
      </p>
      <label>
        验证容器宽度{" "}
        <select
          aria-label="验证容器宽度"
          value={width}
          onChange={(e) => setWidth(e.target.value)}
        >
          <option value="1200">1200px</option>
          <option value="768">768px</option>
          <option value="390">390px</option>
        </select>
      </label>
      <label style={{ display: "block", marginBlock: 12 }}>
        <input
          style={{ width: "auto", minHeight: 0, marginRight: 8 }}
          type="checkbox"
          defaultChecked
          onChange={(e) => {
            offline = e.target.checked;
          }}
        />
        模拟断网（只影响夹具）
      </label>
      <button
        onClick={() => {
          sessionStorage.removeItem(freezeStorageKey(scope));
          setSerial((v) => v + 1);
        }}
      >
        重置夹具记录
      </button>
      <Workspace key={serial} scope={scope} candidate={body} />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
