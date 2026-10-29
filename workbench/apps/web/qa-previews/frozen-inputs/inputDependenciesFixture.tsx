import { useState } from "react";
import { createRoot } from "react-dom/client";
import Workspace from "../../src/PackageInputDependencyWorkspace";
import "../../src/packageFrozenInput.css";
import { inputDependencyFixture, dependencyReply } from "./inputDependencies";
import { changeId as id } from "./factChange";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import type { CheckPackageInputDependencies } from "../../src/contracts";
const fixture = await inputDependencyFixture();
const first = fixture.inventory.manifest.requirements[0];
first.rule_snapshot.statement = String(first.rule_snapshot.statement).repeat(
  24,
);
first.rule_digest = await frozenManifestDigest(first.rule_snapshot);
fixture.inventory.digest = await frozenManifestDigest(
  fixture.inventory.manifest,
);
let failNext = false;
window.fetch = async (input, options) => {
  const url = String(input).split("?")[0];
  const json = (v: unknown) =>
    new Response(JSON.stringify(v), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  if (url.endsWith("/dependency-check")) {
    if (failNext) {
      failNext = false;
      throw new Error("合成核对暂时失败，未保存任何记录");
    }
    return json(
      await dependencyReply(
        fixture,
        JSON.parse(String(options?.body)) as CheckPackageInputDependencies,
      ),
    );
  }
  if (url.endsWith(`/requirement-inventories/${id(5)}`))
    return json(fixture.inventory);
  if (url.endsWith("/facts")) return json(fixture.directory);
  if (url.endsWith(`/evidence/${id(61)}`))
    return json({
      id: id(61),
      document_version_id: id(42),
      parse_run_id: id(43),
      physical_page: 2,
      printed_label: null,
      kind: "text",
      quote: "合同工期应满足本工程要求，具体取值应核对项目资料。",
      bbox: null,
      page_width: 595,
      page_height: 842,
      rotation: 0,
      source_status: "published",
    });
  if (url.endsWith(`/documents/${id(42)}`))
    return json({
      id: id(42),
      bid_id: fixture.props.scope.bidId,
      filename: "合成招标文件.pdf",
      role: "tender",
      sha256: "f".repeat(64),
    });
  throw new Error("合成夹具拒绝其他请求，不连接业务服务");
};
function Fixture() {
  const [width, setWidth] = useState("1200");
  return (
    <main
      style={{
        padding: 16,
        maxWidth: Number(width),
        margin: "auto",
        boxSizing: "border-box",
        overflowWrap: "anywhere",
      }}
    >
      <h2>逐条事实需求 · 合成界面验收</h2>
      <p>
        使用真实组件与页面内模拟响应，不连接业务库。验证人工依赖草稿、事实选择、失败及布局，不代表真实完整性通过。
      </p>
      <label>
        验证容器宽度
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
      <button
        type="button"
        onClick={() => {
          failNext = true;
        }}
      >
        模拟下一次核对失败
      </button>
      <section className="package-frozen-input">
        <Workspace {...fixture.props} />
      </section>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
