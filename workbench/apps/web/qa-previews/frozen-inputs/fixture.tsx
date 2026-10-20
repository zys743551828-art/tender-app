import React, { useState } from "react";
import { prepared } from "./prepared";
import { scopeObservation, scopeReply } from "./factScope";
import { factScopeStorageKey } from "../../src/factScopeRecovery";
import {
  executionScope,
  executionStorageKey,
} from "../../src/executionInputRecovery";
import { createRoot } from "react-dom/client";
import Workspace from "../../src/PackageFrozenInputWorkspace";
import {
  frozenManifestDigest,
  freezeStorageKey,
} from "../../src/packageFrozenInput";
import type { FreezeScope } from "../../src/packageFrozenInput";
import type {
  ChangePackageFactScope,
  PackageFactScopeView,
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
export async function reply(): Promise<PackageReviewFrozenInputView> {
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
      fact_set_id: id(50),
      fact_count: 1,
      confirmed_fact_count: 1,
      facts_binding: "unproven",
      executor_available: false,
      formal_scoring_eligible: false,
    },
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}

let offline = true;
let scopeChanged = false;
let loseScopeAck = false;
const scopeRecords = new Map<string, PackageFactScopeView>();
const scopeHeads = new Map<string, PackageFactScopeView>();
const scopeRequests = new Map<string, string>();
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
const preparedRecords = new Map<string, Awaited<ReturnType<typeof prepared>>>();
window.fetch = async (path, options) => {
  const url = String(path);
  if (!url.includes("/frozen-review-inputs"))
    throw new Error("夹具拒绝业务请求");
  if (offline) throw new Error("合成场景：保存回执丢失，请恢复原请求。");
  if (url.includes("/execution-inputs")) {
    const parts = url.split("/");
    if (url.includes("/fact-scope-declarations") || url.endsWith("/scope-declaration")) {
      const preparedId=parts[parts.indexOf("execution-inputs")+1];
      const saved=preparedRecords.get(preparedId);
      const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json"}});
      if(!saved)return json({code:"PACKAGE_EXECUTION_INPUT_NOT_FOUND"},404);
      if(url.endsWith("/scope-declaration")){
        const fact=parts.at(-2)!;
        return json(scopeObservation(saved,fact,scopeHeads.get(`${preparedId}:${fact}`)??null,scopeChanged));
      }
      if(options?.method!=="POST")return json(scopeRecords.get(parts.at(-1)!)??{code:"PACKAGE_FACT_SCOPE_NOT_FOUND"},scopeRecords.has(parts.at(-1)!)?200:404);
      const key=new Headers(options.headers).get("Idempotency-Key")!;
      const request=JSON.parse(String(options.body)) as ChangePackageFactScope;
      if(scopeRequests.has(key)&&scopeRequests.get(key)!==JSON.stringify(request))return json({code:"IDEMPOTENCY_CONFLICT"},409);
      let value=scopeRecords.get(key);
      if(!value){
        const previous=scopeHeads.get(`${preparedId}:${request.fact_id}`)??null;
        if((previous?.digest??null)!==request.previous_digest)return json({code:"PACKAGE_FACT_SCOPE_CHANGED"},409);
        value=await scopeReply(saved,request,scope.memberId,key,previous);
        scopeRecords.set(key,value);scopeHeads.set(`${preparedId}:${request.fact_id}`,value);scopeRequests.set(key,JSON.stringify(request));
        if(loseScopeAck){loseScopeAck=false;throw new Error("合成场景：范围已保存，回执丢失；请恢复原请求。");}
      }
      return json(value,201);
    }
    if (url.endsWith("/fact-check")) {
      const saved = preparedRecords.get(parts.at(-2)!);
      if (!saved)
        return new Response(
          JSON.stringify({ code: "PACKAGE_EXECUTION_INPUT_NOT_FOUND" }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        );
      const m = saved.manifest,
        b = m.identity.binding;
      return new Response(
        JSON.stringify({
          kind: "fact_validation_observation",
          bid_id: m.bid_id,
          package_id: m.package_id,
          revision_id: m.revision_id,
          inventory_id: m.inventory_id,
          frozen_input_id: m.frozen_input_id,
          execution_input_id: m.id,
          execution_input_digest: saved.digest,
          prepared_context_digest: b.context_digest,
          observed_context_digest: scopeChanged?"f".repeat(64):b.context_digest,
          observed_facts_digest: m.execution_context.facts_digest,
          matches_prepared_context: !scopeChanged,
          checked_at: "2026-10-20T08:00:00Z",
          fact_count: 1,
          provenance_verified_count: scopeChanged?0:1,
          fact_checks: [
            {
              fact_id: id(90),
              provenance_status: scopeChanged?"unproven":"verified",
              scope_binding: "unproven",
              facts_qualified: false,
              blockers: scopeChanged?["FACT_SOURCE_NOT_EFFECTIVE","FACT_SCOPE_MAPPING_REQUIRED"]:["FACT_SCOPE_MAPPING_REQUIRED"],
            },
          ],
          blockers: [],
          facts_qualified: false,
          original_verification: "not_performed",
          review_ready: false,
          launch_available: false,
          publication_authorized: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    const frozenId = parts[parts.indexOf("execution-inputs") - 1];
    const n = [id(6), id(7), id(8)].indexOf(frozenId);
    const frozen = await historical(Math.max(0, n));
    const key =
      options?.method === "POST"
        ? new Headers(options.headers).get("Idempotency-Key")!
        : parts.at(-1)!;
    let data = preparedRecords.get(key);
    if (!data && options?.method === "POST") {
      data = await prepared(frozen, id(20 + preparedRecords.size));
      preparedRecords.set(key, data);
      preparedRecords.set(data.manifest.id, data);
    }
    return new Response(JSON.stringify(data ?? { message: "夹具记录不存在" }), {
      status: data ? 200 : 404,
      headers: { "Content-Type": "application/json" },
    });
  }
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
      <label style={{display:"block",marginBlock:12}}><input style={{width:"auto",minHeight:0,marginRight:8}} type="checkbox" onChange={e=>{scopeChanged=e.target.checked;}}/>模拟来源停用（只影响范围观察）</label>
      <button type="button" onClick={()=>{loseScopeAck=true;}}>下一次范围保存丢失回执</button>
      <button
        onClick={async () => {
          sessionStorage.removeItem(freezeStorageKey(scope));
          for (const n of [0, 1, 2])
            sessionStorage.removeItem(
              executionStorageKey(executionScope(scope, await historical(n))),
            );
          for(const value of new Set(preparedRecords.values()))sessionStorage.removeItem(factScopeStorageKey({...scope,frozenId:value.manifest.frozen_input_id,preparedId:value.manifest.id,preparedDigest:value.digest}));
          preparedRecords.clear();
          scopeRecords.clear();scopeHeads.clear();scopeRequests.clear();loseScopeAck=false;
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
