import { useState } from "react";
import { createRoot } from "react-dom/client";
import Workspace from "../../src/PackageInputDependencyWorkspace";
import "../../src/packageFrozenInput.css";
import {
  dependencyPlanFixture,
  dependencyPlanAssessment,
  dependencyPlanPage,
  dependencyPlanReply,
} from "./dependencyPlan";
import { changeId as id } from "./factChange";
import { dependencyPlanScope } from "../../src/dependencyPlanProtocol";
import { dependencyPlanStorageKey } from "../../src/dependencyPlanRecovery";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import type {
  PackageDependencyPlanView,
  SavePackageDependencyPlan,
} from "../../src/contracts";

const fixture = await dependencyPlanFixture();
const first = fixture.inventory.manifest.requirements[0];
first.rule_snapshot.statement = String(first.rule_snapshot.statement).repeat(
  24,
);
first.rule_digest = await frozenManifestDigest(first.rule_snapshot);
fixture.inventory.digest = await frozenManifestDigest(
  fixture.inventory.manifest,
);
const serverKey = "qa:dependency-plan:synthetic-server";
type Saved = {
  key: string;
  body: SavePackageDependencyPlan;
  value: PackageDependencyPlanView;
};
const saved: Saved[] = JSON.parse(sessionStorage.getItem(serverKey) ?? "[]");
let dropNext = false;
const json = (v: unknown, status = 200) =>
  new Response(JSON.stringify(v), {
    status,
    headers: { "Content-Type": "application/json" },
  });
window.fetch = async (input, options) => {
  const url = new URL(String(input), window.location.origin),
    path = url.pathname;
  if (path.endsWith("/dependency-check"))
    return json(
      await dependencyPlanAssessment(
        fixture,
        JSON.parse(String(options?.body)),
      ),
    );
  if (path.endsWith("/dependency-plans")) {
    if (options?.method === "POST") {
      const key = new Headers(options.headers).get("Idempotency-Key")!;
      const body = JSON.parse(
        String(options.body),
      ) as SavePackageDependencyPlan;
      let found = saved.find((row) => row.key === key);
      if (found && JSON.stringify(found.body) !== JSON.stringify(body))
        return json(
          {
            code: "IDEMPOTENCY_CONFLICT",
            message: "合成键对应其他请求",
            retryable: false,
            details: {},
          },
          409,
        );
      if (!found) {
        found = {
          key,
          body,
          value: await dependencyPlanReply(
            fixture,
            body,
            id(95 + saved.length),
          ),
        };
        saved.push(found);
        sessionStorage.setItem(serverKey, JSON.stringify(saved));
      }
      if (dropNext) {
        dropNext = false;
        throw new Error(
          "合成服务器已保存，当前故意丢失回执；请刷新后恢复原请求。",
        );
      }
      return json(found.value, 201);
    }
    return json(
      dependencyPlanPage(
        fixture,
        saved.map((row) => row.value),
      ),
    );
  }
  if (path.includes("/dependency-plans/")) {
    const found = saved.find(
      (row) => row.value.manifest.id === path.split("/").at(-1),
    );
    if (found) return json(found.value);
    return json(
      {
        code: "PACKAGE_DEPENDENCY_PLAN_NOT_FOUND",
        message: "没有这份合成计划",
        retryable: false,
        details: {},
      },
      404,
    );
  }
  if (path.endsWith(`/requirement-inventories/${id(5)}`))
    return json(fixture.inventory);
  if (path.endsWith("/facts")) return json(fixture.directory);
  throw new Error("合成夹具拒绝其他请求，不连接业务服务");
};
function Fixture() {
  const [width, setWidth] = useState("1200"),
    [notice, setNotice] = useState("");
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
      <h2>依赖计划保存与恢复 · 合成界面验收</h2>
      <p>
        真实组件和页面内模拟响应，不连接业务库。演示明确保存、原回执恢复与历史边界，不代表真实评审效果。
      </p>
      <label>
        内容容器宽度
        <select value={width} onChange={(e) => setWidth(e.target.value)}>
          {["1200", "768", "390"].map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="button secondary"
        onClick={() => {
          dropNext = true;
          setNotice(
            "下一次保存将模拟服务端已保存但回执丢失，可刷新页面验证原请求恢复。",
          );
        }}
      >
        下一次保存模拟丢回执
      </button>
      <button
        type="button"
        className="text-button"
        onClick={() => {
          sessionStorage.removeItem(serverKey);
          sessionStorage.removeItem(
            dependencyPlanStorageKey(dependencyPlanScope(fixture.props)),
          );
          window.location.reload();
        }}
      >
        清空本页合成验收记录
      </button>
      {notice && <p role="status">{notice}</p>}
      <section className="package-frozen-input">
        <Workspace {...fixture.props} />
      </section>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
