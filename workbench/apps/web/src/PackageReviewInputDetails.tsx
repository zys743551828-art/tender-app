import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageDependencyPlanView,
  PackageFactScopeView,
  PackageReviewRunInputView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  dependencyPlanPath,
  dependencyPlanScope,
  validatePlan,
} from "./dependencyPlanProtocol";
import { packageReviewPath } from "./packageReviewProtocol";
import { validatePackageReviewInputView } from "./packageReviewInputProtocol";
import { scopeLabels, validateScopeRecord } from "./factScopeValidation";

type Props = DependencyProps & { run: PackageReviewRunView };
type Declaration =
  PackageReviewRunInputView["manifest"]["fact_admission"]["fact_declarations"][number];

function OriginalDeclaration({
  p,
  declaration,
}: {
  p: Props;
  declaration: Declaration;
}) {
  const [record, setRecord] = useState<PackageFactScopeView | null>(null),
    [error, setError] = useState<unknown>(null),
    [reading, setReading] = useState(false);
  const active = useRef(false),
    busy = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function read() {
    if (!active.current || busy.current) return;
    busy.current = true;
    setReading(true);
    setError(null);
    try {
      const base = packageReviewPath(p).replace(
        /\/review-runs$/,
        "/fact-scope-declarations",
      );
      const { data } = await api<PackageFactScopeView>(
        `${base}/${declaration.declaration_id}`,
      );
      await validateScopeRecord(data, p.prepared, declaration.fact_id);
      if (
        data.manifest.id !== declaration.declaration_id ||
        data.digest !== declaration.declaration_digest
      )
        throw new Error("事实声明与本次实际执行依据不符，未展示其他版本。");
      if (active.current) setRecord(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) {
        busy.current = false;
        setReading(false);
      }
    }
  }
  return (
    <li>
      <p>
        事实编号：<code>{declaration.fact_id}</code>
      </p>
      <button
        type="button"
        className="button secondary"
        disabled={reading}
        onClick={() => void read()}
      >
        {reading ? "正在读取原声明…" : "查看原适用声明"}
      </button>
      {record && (
        <div className="package-review__selected">
          <p>
            {record.manifest.action === "bind"
              ? "原适用范围声明"
              : "原适用范围撤回记录"}{" "}
            · {scopeLabels[record.manifest.subject.kind]} ·{" "}
            <code>{record.manifest.subject.id}</code>
          </p>
          <p>{record.manifest.reason}</p>
          <p className="muted">
            记录时间：{record.manifest.recorded_at}
            。这是本次执行引用的历史记录，当前是否仍适用须重新核对。
          </p>
          <details>
            <summary>原声明身份</summary>
            <p>
              声明编号：<code>{record.manifest.id}</code>
            </p>
            <p>
              声明摘要：<code>{record.digest}</code>
            </p>
          </details>
        </div>
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void read()} />
      )}
    </li>
  );
}

export default function PackageReviewInputDetails(p: Props) {
  return (
    <InputDetails
      key={`${JSON.stringify(dependencyPlanScope(p))}:${p.run.id}:${p.run.input_digest}`}
      {...p}
    />
  );
}
function InputDetails(p: Props) {
  const [input, setInput] = useState<PackageReviewRunInputView | null>(null),
    [plan, setPlan] = useState<PackageDependencyPlanView | null>(null),
    [error, setError] = useState<unknown>(null),
    [reading, setReading] = useState<"input" | "plan" | null>(null),
    [page, setPage] = useState(0);
  const active = useRef(false),
    busy = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function read(kind: "input" | "plan") {
    if (!active.current || busy.current || (kind === "plan" && !input)) return;
    busy.current = true;
    setReading(kind);
    setError(null);
    try {
      if (kind === "input") {
        const { data } = await api<unknown>(
          `${packageReviewPath(p)}/${p.run.id}/input`,
        );
        const received = await validatePackageReviewInputView(data, p, p.run);
        if (active.current) {
          setInput(received);
          setPage(0);
        }
      } else {
        const { data } = await api<PackageDependencyPlanView>(
          `${dependencyPlanPath(p)}/${p.run.dependency_plan_id}`,
        );
        await validatePlan(data, p);
        if (
          data.manifest.id !== p.run.dependency_plan_id ||
          data.digest !== p.run.dependency_plan_digest ||
          data.manifest.usage.digest !== input!.manifest.usage_digest ||
          data.manifest.usage.manifest.selected_facts_digest !==
            input!.manifest.selected_facts_digest
        )
          throw new Error("原计划与本次实际执行依据不符，未采用其他计划。");
        if (active.current) setPlan(data);
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) {
        busy.current = false;
        setReading(null);
      }
    }
  }
  function download() {
    if (!input) return;
    try {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(input, null, 2)], {
          type: "application/json;charset=utf-8",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `package-review-input-${p.run.id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setError(null);
    } catch (failure) {
      setError(failure);
    }
  }
  const declarations = input?.manifest.fact_admission.fact_declarations ?? [];
  return (
    <details className="package-review__input">
      <summary>执行依据与原事实声明</summary>
      <p>
        读取本次已受理核查保留的输入、原计划和事实适用声明。历史记录用于核对当时依据，不表示资料当前仍可使用。
      </p>
      <div className="package-review__actions">
        <button
          type="button"
          className="button secondary"
          disabled={reading !== null}
          onClick={() => void read("input")}
        >
          {reading === "input" ? "正在读取执行依据…" : "读取本次执行依据"}
        </button>
        {input && (
          <button type="button" className="button secondary" onClick={download}>
            导出执行依据 JSON
          </button>
        )}
      </div>
      {input && (
        <>
          <p>
            原方法：{input.manifest.executor_method.profile.engine} ·{" "}
            {input.manifest.executor_method.profile.model}
            。用途为已声明要求响应核查，整体覆盖仍为部分。
          </p>
          <p>本次记录了 {declarations.length} 项事实的原适用声明。</p>
          <button
            type="button"
            className="button secondary"
            disabled={reading !== null}
            onClick={() => void read("plan")}
          >
            {reading === "plan" ? "正在读取原计划…" : "查看本次采用的原计划"}
          </button>
          {plan && (
            <div className="package-review__selected">
              <strong>本次采用的原计划</strong>
              <p>{plan.manifest.reason}</p>
              <p>
                {plan.manifest.assessment.manifest.requirement_count} 条要求 ·{" "}
                {plan.manifest.assessment.manifest.selected_fact_count} 项事实
              </p>
              <p>保存时间：{plan.manifest.saved_at}</p>
              <p>
                计划编号：<code>{plan.manifest.id}</code>
              </p>
              <p>
                计划摘要：<code>{plan.digest}</code>
              </p>
              <p className="muted">
                仅读取当时计划；再次执行须重新核对准备输入。
              </p>
            </div>
          )}
          {declarations.length ? (
            <>
              <ul className="package-review__documents">
                {declarations
                  .slice(page * 20, page * 20 + 20)
                  .map((declaration) => (
                    <OriginalDeclaration
                      key={`${declaration.fact_id}:${declaration.declaration_id}`}
                      p={p}
                      declaration={declaration}
                    />
                  ))}
              </ul>
              {declarations.length > 20 && (
                <div className="package-review__pagination">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!page}
                    onClick={() => setPage(page - 1)}
                  >
                    上一页原声明
                  </button>
                  <span>
                    第 {page + 1} / {Math.ceil(declarations.length / 20)} 页
                  </span>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={(page + 1) * 20 >= declarations.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页原声明
                  </button>
                </div>
              )}
            </>
          ) : (
            <p className="muted">
              本次输入未引用事实适用声明。逐条核查的原文依据见报告引用。
            </p>
          )}
          <details>
            <summary>执行依据摘要</summary>
            <dl className="package-review__identity">
              <dt>完整输入摘要</dt>
              <dd>
                <code>{input.digest}</code>
              </dd>
              <dt>事实选择摘要</dt>
              <dd>
                <code>{input.manifest.selected_facts_digest}</code>
              </dd>
              <dt>事实采纳内容摘要</dt>
              <dd>
                <code>{input.manifest.fact_admission.content_digest}</code>
              </dd>
              <dt>清单证明摘要</dt>
              <dd>
                <code>{input.manifest.inventory_proof_digest}</code>
              </dd>
            </dl>
          </details>
        </>
      )}
      {error != null && <ErrorNotice error={error} />}
    </details>
  );
}
