import { useEffect, useState } from "react";
import { ApiError } from "./api";
import type { RunView, TaskKindPage, TemplateView } from "./contracts";
import { ErrorNotice } from "./components";
import { packageTaskCapability } from "./packageTaskTemplateSelection";
import type { PackageNavigationState } from "./packageNavigation";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { isExactPackageTask, taskRunNames } from "./taskState";
import { validateTaskPackageTemplate } from "./taskPackageProtocol";
import { useTaskPackageCommand } from "./useTaskPackageCommand";

export function ExactPackageTaskRunControl({
  bidId,
  memberId,
  template,
  etag,
  kinds,
  disabled = false,
  onRun,
  onChanged,
  onStateChange,
}: {
  bidId: string;
  memberId: string;
  template: TemplateView;
  etag: string | null;
  kinds: TaskKindPage | undefined;
  disabled?: boolean;
  onRun: (id: string) => void;
  onChanged: () => void;
  onStateChange?: (state: PackageNavigationState) => void;
}) {
  const command = useTaskPackageCommand({
    kind: "run",
    memberId,
    bidId,
    identity: template.id,
  });
  const [checked, setChecked] = useState<TemplateView | null>(null);
  const [readError, setReadError] = useState<unknown>(null);
  const [accepted, setAccepted] = useState<RunView | null>(null);
  const [adopting, setAdopting] = useState(false);
  const [adoptedEtag, setAdoptedEtag] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setChecked(null);
    setReadError(null);
    void validateTaskPackageTemplate(template, etag, bidId, template.id)
      .then(() => {
        if (active) setChecked(template);
      })
      .catch((error) => {
        if (active) setReadError(error);
      });
    return () => {
      active = false;
    };
  }, [template, etag, bidId]);
  const busy = command.busy || adopting;
  const pending = !!command.pending || command.blocked;
  usePackageScopeGuard(`task-run:${memberId}:${bidId}:${template.id}`, {
    busy,
    pending,
  });
  useEffect(() => {
    onStateChange?.({ busy, pending, dirty: false });
  }, [onStateChange, busy, pending]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  let capability;
  let capabilityError: unknown = null;
  try {
    capability = kinds ? packageTaskCapability(kinds) : null;
  } catch (error) {
    capabilityError = error;
  }
  const methodMatches =
    capability &&
    isExactPackageTask(template.configuration) &&
    template.configuration.source_selection.input.method_digest ===
      capability.method_digest;
  const feeUnknown =
    command.error instanceof ApiError &&
    [
      "MODEL_CALL_REQUIRES_RECONCILIATION",
      "TASK_RECONCILIATION_REQUIRED",
    ].includes(command.error.code);
  const waitingForFreshTemplate = adoptedEtag !== null && adoptedEtag !== etag;
  const available =
    !!checked &&
    checked === template &&
    !!capability?.available &&
    methodMatches &&
    !template.paused &&
    !disabled &&
    !feeUnknown &&
    !waitingForFreshTemplate;
  function accept(value: RunView | undefined) {
    if (!value) return;
    setAccepted(value);
    onRun(value.id);
    onChanged();
  }
  async function run() {
    if (!available || busy || pending || command.conflict || !etag) return;
    const value = await command.run({
      path: `/bids/${bidId}/task-definitions/${template.id}/runs`,
      method: "POST",
      body: { rerun: false },
      etag,
      expected: { kind: "run", template },
    });
    accept(value?.data);
  }
  async function adoptBasis() {
    if (busy || pending) return;
    setAdopting(true);
    try {
      const value = await command.adoptBasis();
      if (!value?.etag) return;
      setAdoptedEtag(value.etag);
      onChanged();
    } finally {
      setAdopting(false);
    }
  }
  return (
    <section
      className="exact-package-task-command"
      aria-label="整包任务手动启动"
    >
      <p className="notice neutral">
        仅手动启动本模板绑定的精确输入。启动可能调用模型并产生费用；本入口不建立定时或资料事件触发，也不创建新输入重跑。
      </p>
      {!kinds && (
        <p className="notice warning">尚未读到整包手动任务能力，不能启动。</p>
      )}
      {capability && (
        <p className={capability.available ? "small-note" : "notice warning"}>
          整包手动执行能力：
          {capability.available
            ? "服务已提供，运行时仍须核验来源与预算"
            : `当前不可用${capability.reason ? `（${capability.reason}）` : ""}`}
          。
        </p>
      )}
      {capability && !methodMatches && (
        <p className="notice warning">
          模板中的核查方法与当前服务不一致。固定输入未被替换，请回整包工作面重新核对。
        </p>
      )}
      {feeUnknown && (
        <p className="notice warning">
          原运行费用尚未核清，不能新建运行绕过账本核对。
        </p>
      )}
      {waitingForFreshTemplate && (
        <p role="status">正在读取已明确采用的当前模板；尚不使用旧头启动。</p>
      )}
      <ErrorNotice error={command.error ?? readError ?? capabilityError} />
      <button
        type="button"
        className="button primary"
        disabled={!available || busy || pending || command.conflict}
        onClick={() => void run()}
      >
        手动运行这份整包输入
      </button>
      {command.conflict && (
        <div className="notice warning">
          <p>模板修订已变化。原启动未被默认为成功，也不会自动用新版本再发。</p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || pending}
            onClick={() => void adoptBasis()}
          >
            读取并采用当前模板，再明确运行
          </button>
        </div>
      )}
      {pending && (
        <p className="notice warning">
          原启动请求尚未确认；只能用原请求体、原键与原修订恢复，不因当前模板变化重发新运行。
        </p>
      )}
      {command.pending && !command.busy && (
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            void command.retry().then((value) => accept(value?.data))
          }
        >
          恢复原整包运行受理结果
        </button>
      )}
      {command.blocked && (
        <p className="notice error">
          本地恢复记录无法核验，保留原记录并阻止新启动。
        </p>
      )}
      {accepted && (
        <div className="notice success">
          <p>
            原命令受理回执：{taskRunNames[accepted.state]}
            。这是原受理时状态，后续进度以该运行的服务器读取为准。
          </p>
          <details className="identity-details">
            <summary>本次任务运行标识</summary>
            <p>{accepted.id}</p>
          </details>
          <button
            type="button"
            className="text-button"
            onClick={() => onRun(accepted.id)}
          >
            查看该任务当前状态
          </button>
        </div>
      )}
    </section>
  );
}
