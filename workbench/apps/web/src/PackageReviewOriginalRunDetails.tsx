import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageExecutionInputView,
  PackageReviewFrozenInputView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import type { PackageReviewHistoricalReference } from "./packageReviewHistoricalRun";
import { matchesPackageReviewHistoricalReference } from "./packageReviewHistoricalRun";
import {
  freezePath,
  frozenManifestDigest,
  validateFrozenInput,
} from "./packageFrozenInput";
import { executionPath } from "./executionInputRecovery";
import { validateExecutionInput } from "./executionInputValidation";
import { validatePackageReviewRun } from "./packageReviewProtocol";
import PackageReviewProgress from "./PackageReviewProgress";

type Props = {
  memberId: string;
  reference: PackageReviewHistoricalReference;
  label: string;
  requirement?: { id: string; rowDigest: string };
  onClose: () => void;
};
export default function PackageReviewOriginalRunDetails(p: Props) {
  return (
    <OriginalRunDetails
      key={JSON.stringify({
        memberId: p.memberId,
        reference: p.reference,
        requirement: p.requirement,
      })}
      {...p}
    />
  );
}
function OriginalRunDetails({
  memberId,
  reference,
  label,
  requirement,
  onClose,
}: Props) {
  const [initial] = useState(() => ({ memberId, reference, requirement })),
    [preparedProps, setPreparedProps] = useState<DependencyProps | null>(null),
    [run, setRun] = useState<PackageReviewRunView | null>(null),
    [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(null);
  const heading = useRef<HTMLHeadingElement | null>(null),
    active = useRef(false),
    busy = useRef(false),
    ticket = useRef(0);
  const read = useCallback(async () => {
    if (!active.current || busy.current) return;
    const request = ++ticket.current;
    busy.current = true;
    setReading(true);
    setError(null);
    try {
      const r = initial.reference,
        scope = {
          memberId: initial.memberId,
          bidId: r.scope.bid_id,
          packageId: r.scope.package_id,
          revisionId: r.scope.revision_id,
          inventoryId: r.scope.inventory_id,
        },
        preparedBase = `${executionPath(scope, r.frozen_input_id)}/${r.execution_input_id}`;
      const [frozenReply, preparedReply, runReply] = await Promise.all([
        api<PackageReviewFrozenInputView>(
          `${freezePath(scope)}/${r.frozen_input_id}`,
        ),
        api<PackageExecutionInputView>(preparedBase),
        api<unknown>(`${preparedBase}/review-runs/${r.id}`),
      ]);
      const frozen = frozenReply.data,
        prepared = preparedReply.data;
      await validateFrozenInput(frozen, scope, r.frozen_input_id);
      if (frozen.digest !== r.frozen_input_digest)
        throw new Error("原冻结输入摘要与所选运行不符，未打开其他资料。");
      await validateExecutionInput(
        prepared,
        scope,
        frozen,
        r.execution_input_id,
      );
      if (prepared.digest !== r.execution_input_digest)
        throw new Error("原执行准备摘要与所选运行不符，未打开其他版本。");
      const p = { scope, frozen, prepared },
        received = await validatePackageReviewRun(runReply.data, p, r.id);
      if (!matchesPackageReviewHistoricalReference(received, r))
        throw new Error("原核查身份或结果摘要与所选记录不符，未采用其他结果。");
      if (initial.requirement) {
        const row = received.result?.manifest.matrix.find(
          (item) => item.requirement_id === initial.requirement!.id,
        );
        if (
          !row ||
          (await frozenManifestDigest(row)) !== initial.requirement.rowDigest
        )
          throw new Error(
            "所选原要求或机器行摘要与对比不符，未定位到其他条款。",
          );
      }
      if (!active.current || request !== ticket.current) return;
      setPreparedProps(p);
      setRun(received);
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        busy.current = false;
        setReading(false);
      }
    }
  }, [initial]);
  useEffect(() => {
    active.current = true;
    heading.current?.focus();
    void read();
    const requests = ticket;
    return () => {
      active.current = false;
      busy.current = false;
      requests.current++;
    };
  }, [read]);
  return (
    <section className="package-review__original" aria-label={label}>
      <div className="package-review__heading">
        <div>
          <h4 ref={heading} tabIndex={-1}>
            {label}
          </h4>
          <p>
            按原冻结输入和执行准备定位，当前编辑中的计划与草稿不变。人工状态可能在对比或原回执形成后继续更新。
          </p>
        </div>
        <button type="button" className="button secondary" onClick={onClose}>
          关闭原核查详情
        </button>
      </div>
      {reading && <p role="status">正在读取原冻结、执行准备和完整核查记录…</p>}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void read()} />
      )}
      {run && preparedProps && (
        <PackageReviewProgress
          key={`${run.id}:${run.input_digest}`}
          {...preparedProps}
          run={run}
          onChange={setRun}
          showComparison={false}
          focusRequirementId={initial.requirement?.id}
        />
      )}
    </section>
  );
}
