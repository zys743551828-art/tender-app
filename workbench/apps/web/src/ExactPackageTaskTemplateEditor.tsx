import { useEffect, useState } from "react";
import type { TemplateRequest, TemplateView } from "./contracts";
import { ErrorNotice } from "./components";
import { ExactPackageTaskScope } from "./ExactPackageTaskScope";
import {
  discardKnowledgeForm,
  knowledgeStorageKey,
  useKnowledgeInput,
} from "./knowledgeStorage";
import { usePackageScopeGuard } from "./packageScopeGuard";
import type { TaskTemplateEditorProps } from "./TaskTemplateEditor";
import {
  exactPackageTaskScope,
  isExactPackageTask,
  newTaskConfiguration,
  sameTaskPackageSource,
} from "./taskState";
import { useTaskPackageCommand } from "./useTaskPackageCommand";

/** Exact package templates use their own verified command; old task commands are unchanged. */
export function ExactPackageTaskTemplateEditor({
  bidId,
  memberId,
  template,
  etag,
  onSaved,
  onClose,
  initialConfiguration,
  formIdentity,
  external,
  onStateChange,
}: TaskTemplateEditorProps) {
  const identity = template?.id ?? formIdentity ?? "new";
  const formKey =
    knowledgeStorageKey(memberId, bidId) + `task-template:${identity}:`;
  const [initial] = useState(() =>
    structuredClone(
      initialConfiguration ?? template?.configuration ?? newTaskConfiguration(),
    ),
  );
  const [input, setInput] = useKnowledgeInput<TemplateRequest>(
    formKey + "input",
    initial,
  );
  const [basis, setBasis] = useKnowledgeInput(formKey + "etag", etag ?? "");
  const [previous, setPrevious] = useKnowledgeInput<TemplateView | null>(
    formKey + "previous",
    template,
  );
  const [saved, setSaved] = useState(false);
  const [rebasing, setRebasing] = useState(false);
  const [headMismatch, setHeadMismatch] = useState(false);
  const [adoption, setAdoption] = useState<{
    etag: string;
    observedProp: string | null;
  } | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const command = useTaskPackageCommand({
    kind: "template",
    memberId,
    bidId,
    identity,
  });
  const busy = command.busy || rebasing;
  const pending = !!command.pending || command.blocked;
  const staleBasis =
    !!etag &&
    basis !== etag &&
    !(adoption?.etag === basis && adoption.observedProp === etag);
  const sourceMatches =
    isExactPackageTask(input) && sameTaskPackageSource(input, initial);
  const dirty =
    !saved &&
    (!sourceMatches ||
      input.name !== initial.name ||
      input.instructions !== initial.instructions ||
      input.task_kind !== initial.task_kind ||
      input.section_id !== initial.section_id ||
      input.trigger?.mode !== initial.trigger?.mode ||
      input.trigger?.cron !== initial.trigger?.cron ||
      input.trigger?.timezone !== initial.trigger?.timezone);
  usePackageScopeGuard(`task-template:${memberId}:${bidId}:${identity}`, {
    busy,
    pending,
    dirty,
  });
  useEffect(() => {
    onStateChange?.({ busy, pending, dirty });
  }, [onStateChange, busy, pending, dirty]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  const missing = [
    ...(!sourceMatches ? ["原精确整包来源（未用当前项目资料替代）"] : []),
    ...(input.task_kind !== "denial_check" || input.section_id != null
      ? ["整包否决核对类型"]
      : []),
    ...(input.trigger?.mode !== "manual" || input.trigger.cron != null
      ? ["仅手动触发"]
      : []),
    ...(typeof input.name !== "string" || !input.name.trim()
      ? ["模板名称"]
      : []),
    ...(typeof input.instructions !== "string" || !input.instructions.trim()
      ? ["任务说明"]
      : []),
    ...(!basis ? ["服务器修订基准"] : []),
    ...(external ? ["从精确整包入口使用受核验的保存命令"] : []),
  ];
  function accept(value: TemplateView | undefined) {
    if (!value) return;
    // The strict command validated identity, full configuration, digest, revision and ETag first.
    setSaved(true);
    discardKnowledgeForm(formKey);
    onSaved(value);
  }
  async function save() {
    if (
      busy ||
      pending ||
      saved ||
      command.conflict ||
      headMismatch ||
      staleBasis ||
      missing.length
    )
      return;
    const value = await command.run({
      path: template
        ? `/bids/${bidId}/task-definitions/${template.id}`
        : `/bids/${bidId}/task-definitions`,
      method: template ? "PUT" : "POST",
      body: input,
      etag: basis,
      expected: { kind: "template", request: input, previous },
    });
    accept(value?.data);
  }
  async function adoptBasis() {
    if (busy || pending || saved) return;
    setRebasing(true);
    setFailure(null);
    try {
      const value = await command.adoptBasis();
      if (!value?.etag) return;
      if (template) {
        if (
          !("configuration" in value.data) ||
          !sameTaskPackageSource(value.data.configuration, initial)
        ) {
          setHeadMismatch(true);
          throw new Error(
            "当前模板的固定来源已改变，原输入保留。请从对应的精确整包入口核对，不能用新头替换原来源。",
          );
        }
        setPrevious(value.data);
      }
      setHeadMismatch(false);
      setBasis(value.etag);
      setAdoption({ etag: value.etag, observedProp: etag });
    } catch (error) {
      setFailure(error);
    } finally {
      setRebasing(false);
    }
  }
  const locked = busy || pending || saved;
  return (
    <section className="panel task-editor exact-package-task-command">
      <div className="section-title">
        <h3>{template ? "保存整包任务的新版本" : "保存精确整包手动任务"}</h3>
        <button type="button" className="text-button" onClick={onClose}>
          收起表单，保留输入
        </button>
      </div>
      <p className="small-note">
        保存只记录模板，不启动核查或模型调用。固定来源只读；如需另一个包、清单或计划，请在整包工作面明确选择并创建另一模板。
      </p>
      <p className="notice neutral">{exactPackageTaskScope}</p>
      {isExactPackageTask(initial) && (
        <ExactPackageTaskScope
          bidId={bidId}
          selection={initial.source_selection.input}
        />
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={locked}>
          <label>
            模板名称
            <input
              aria-label="模板名称"
              required
              maxLength={200}
              value={typeof input.name === "string" ? input.name : ""}
              onChange={(event) =>
                setInput((value) => ({ ...value, name: event.target.value }))
              }
            />
          </label>
          <label>
            任务类型
            <input aria-label="任务类型" readOnly value="整包否决核对" />
          </label>
          <label>
            任务说明
            <textarea
              aria-label="任务说明"
              required
              rows={4}
              maxLength={8000}
              value={
                typeof input.instructions === "string" ? input.instructions : ""
              }
              onChange={(event) =>
                setInput((value) => ({
                  ...value,
                  instructions: event.target.value,
                }))
              }
            />
          </label>
          <label>
            触发方式
            <input aria-label="触发方式" readOnly value="仅手动运行" />
          </label>
        </fieldset>
        <ErrorNotice error={failure ?? command.error} />
        {staleBasis && !saved && (
          <p className="notice warning">
            服务器模板修订已更新；表单与原基准仍保留。请明确读取并采用当前修订，再保存新版本。
          </p>
        )}
        {command.conflict && (
          <p className="notice warning">
            保存基准已变化，原输入保留。先明确读取并采用当前修订；不会在后台换头重试。
          </p>
        )}
        {pending && (
          <p className="notice warning">
            原保存请求尚未确认。恢复会使用原请求体、原幂等键和原修订条件；读取模板历史不能代替这份回执。
          </p>
        )}
        {command.blocked && (
          <p className="notice error">
            浏览器恢复记录无法核验，不能发送新命令或丢弃原记录。
          </p>
        )}
        {saved && <p className="notice success">模板已保存，未运行。</p>}
        {missing.length > 0 && (
          <p className="small-note" role="status">
            仍需填写或核对：{missing.join("、")}。
          </p>
        )}
        <div className="review-shortcuts">
          <button
            className="button primary"
            disabled={
              locked ||
              command.conflict ||
              headMismatch ||
              staleBasis ||
              !!missing.length
            }
          >
            保存任务模板，不运行
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => void adoptBasis()}
          >
            读取并采用当前修订，保留输入
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => {
              setInput(structuredClone(initial));
              setFailure(null);
            }}
          >
            放弃未发送的文字修改
          </button>
        </div>
      </form>
      {command.pending && !command.busy && (
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            void command.retry().then((value) => accept(value?.data))
          }
        >
          恢复原模板保存结果
        </button>
      )}
    </section>
  );
}
