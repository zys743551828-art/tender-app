import { useState } from "react";
import { createRoot } from "react-dom/client";
import Workspace from "../../src/PackageFactChangeWorkspace";
import { changeId as id, changeReply, factChangeFixture } from "./factChange";
import type { PendingFactChange } from "../../src/factChangeProtocol";
import type { PackageFactChangeView } from "../../src/contracts";
const fixture = await factChangeFixture();
let loseAck = false;
const receipts = new Map<string, { body: string; value: PackageFactChangeView }>();
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
window.fetch = async (input, options) => {
  const path = String(input).split("?")[0];
  if (path.endsWith("/fact-context")) return json(fixture.page);
  if (path.endsWith(`/facts/${id(51)}`)) return json(fixture.detail);
  if (path.endsWith(`/revisions/${id(4)}`)) return json(fixture.target);
  if (path.endsWith(`/revisions/${id(31)}`)) return json(fixture.authority);
  if (path.endsWith(`/revisions/${id(4)}/evidence`)) return json(fixture.directory);
  if (path.endsWith(`/evidence/${id(60)}`)) return json(fixture.evidence);
  if (path.endsWith(`/documents/${id(40)}`)) return json(fixture.document);
  if (options?.method === "POST" && /\/fact-(confirmations|withdrawals)$/.test(path)) {
    const key = new Headers(options.headers).get("Idempotency-Key")!;
    const body = String(options.body);
    const prior = receipts.get(key);
    if (prior && prior.body !== body) return json({ code: "IDEMPOTENCY_CONFLICT" }, 409);
    if (prior) return json(prior.value, 201);
    const pending = { kind: path.endsWith("fact-confirmations") ? "confirm" : "withdraw", key, body: JSON.parse(body) } as PendingFactChange;
    const value = await changeReply(fixture, pending);
    receipts.set(key, { body, value });
    if (loseAck) { loseAck = false; throw new Error("合成场景：已保存，回执丢失。请恢复原操作。"); }
    return json(value, 201);
  }
  if (path.includes("/fact-changes/")) return json(receipts.get(path.split("/").at(-1)!)?.value ?? { code: "NOT_FOUND" });
  throw new Error("合成夹具拒绝其他请求，不连接业务服务");
};
function Fixture() {
  const [width, setWidth] = useState("1200");
  return <main style={{ padding: 16, maxWidth: Number(width), margin: "auto", boxSizing: "border-box", overflowWrap: "anywhere" }}>
    <h2>项目事实 · 合成界面验收</h2>
    <p>使用真实组件，所有请求在页面内模拟。用于交互及布局核对，不代表真实原件或正式评审通过。</p>
    <label>验证容器宽度 <select aria-label="验证容器宽度" value={width} onChange={e => setWidth(e.target.value)}><option value="1200">1200px</option><option value="768">768px</option><option value="390">390px</option></select></label>
    <button type="button" onClick={() => { loseAck = true; }}>下一次保存丢失回执</button>
    <Workspace scope={fixture.scope} frozen={fixture.frozen} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
