import { useState } from "react";
import { api } from "./api";
import type { AssistantSourcePage, Bid, MaterialView } from "./contracts";
import type { TemplateRequest, TemplateView } from "./taskTriggerContracts";
import { ErrorNotice } from "./components";
import {
  knowledgeStorageKey,
  useKnowledgeInput,
  discardKnowledgeForm,
} from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import {
  newTaskConfiguration,
  isExactPackageTask,
  taskNames,
  taskScopes,
  triggerDescription,
} from "./taskState";
import { ExactPackageTaskTemplateEditor } from "./ExactPackageTaskTemplateEditor";
import { PackageAuthoringTemplateEditor } from "./PackageAuthoringTemplateEditor";
import { isExactPackageAuthoring } from "./taskPackageAuthoringProtocol";
import type { PackageNavigationState } from "./packageNavigation";

export type TaskTemplateEditorProps = {
  bidId: string;
  memberId: string;
  template: TemplateView | null;
  etag: string | null;
  onSaved: (item: TemplateView) => void;
  onClose: () => void;
  onStateChange?: (state: PackageNavigationState) => void;
  formIdentity?: string;
  initialConfiguration?: TemplateRequest;
  requireKindSelection?: boolean;
  external?: {
    busy: boolean;
    pending: boolean;
    error: unknown;
    conflict: boolean;
    submit: (input: TemplateRequest) => Promise<TemplateView | undefined>;
    saveDraftOnly?: (input: TemplateRequest) => Promise<void>;
    rebase: () => Promise<string>;
  };
};

export function TaskTemplateEditor(props: TaskTemplateEditorProps) {
  const configuration =
    props.initialConfiguration ?? props.template?.configuration;
  if (configuration && isExactPackageAuthoring(configuration))
    return (
      <PackageAuthoringTemplateEditor
        key={`${props.memberId}:${props.bidId}:${props.template?.id ?? props.formIdentity ?? "new"}`}
        {...props}
      />
    );
  return configuration && isExactPackageTask(configuration) ? (
    <ExactPackageTaskTemplateEditor
      key={`${props.memberId}:${props.bidId}:${props.template?.id ?? props.formIdentity ?? "new"}`}
      {...props}
    />
  ) : (
    <LegacyTaskTemplateEditor {...props} />
  );
}

function LegacyTaskTemplateEditor({
  bidId,
  memberId,
  template,
  etag,
  onSaved,
  onClose,
  initialConfiguration,
  requireKindSelection = false,
  external,
  formIdentity,
}: TaskTemplateEditorProps) {
  const formKey =
    knowledgeStorageKey(memberId, bidId) +
    `task-template:${formIdentity ?? template?.id ?? "new"}:`;
  const [input, setInput] = useKnowledgeInput<TemplateRequest>(
    formKey + "input",
    initialConfiguration ?? template?.configuration ?? newTaskConfiguration(),
  );
  const [basis, setBasis] = useKnowledgeInput(formKey + "etag", etag ?? "");
  const [kindSelected, setKindSelected] = useState(!requireKindSelection);
  const [rebaseBusy, setRebaseBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const command = useRecordedCommand(
    `task-template:${memberId}:${bidId}:${formIdentity ?? template?.id ?? "new"}`,
  );
  const materials = useResource<MaterialView>(`/bids/${bidId}/materials`);
  const sections = useResource<AssistantSourcePage>(
    input.task_kind === "chapter_suggestion"
      ? `/assistant/sources?kind=section&bid_id=${bidId}`
      : null,
  );
  const options =
    sections.data?.items.filter(
      (item) =>
        item.available &&
        item.bid_id === bidId &&
        item.reference?.kind === "section",
    ) ?? [];
  const sourceSelection = input.source_selection;
  const source =
    sourceSelection?.mode === "exact_package_review" ||
    sourceSelection?.mode === "exact_package_trigger" ||
    sourceSelection?.mode === "exact_package_authoring"
      ? sourceSelection
      : {
          mode: sourceSelection?.mode ?? "current_project",
          version_ids: sourceSelection?.version_ids ?? [],
        };
  const trigger = input.trigger ?? {
    mode: "manual" as const,
    cron: null,
    timezone: "Asia/Shanghai",
  };
  const locked =
    command.busy ||
    !!command.pending ||
    rebaseBusy ||
    !!external?.busy ||
    !!external?.pending;
  const conflict = command.conflict || external?.conflict;
  const missing = [
    ...([
      "exact_package_review",
      "exact_package_trigger",
      "exact_package_authoring",
    ].includes(source.mode)
      ? ["从原精确整包入口恢复此模板输入"]
      : []),
    ...(!kindSelected ? ["明确任务类型"] : []),
    ...(!input.name.trim() ? ["模板名称"] : []),
    ...(!input.instructions.trim() ? ["任务说明"] : []),
    ...(input.task_kind === "chapter_suggestion" && !input.section_id
      ? ["真实目标章节"]
      : []),
    ...(source.mode === "selected_versions" && !source.version_ids.length
      ? ["至少一份明确来源"]
      : []),
    ...(trigger.mode === "schedule" && !trigger.cron?.trim()
      ? ["明确的定时表达式"]
      : []),
    ...(!basis ? ["当前服务器修订基准"] : []),
  ];
  function change(patch: Partial<TemplateRequest>) {
    setSaved(false);
    setInput((old) => ({ ...old, ...patch }));
  }
  async function save() {
    if (locked || missing.length || conflict) return;
    if (external) {
      accept(await external.submit(input));
      return;
    }
    const value = await command.run<TemplateView>(
      template
        ? `/bids/${bidId}/task-definitions/${template.id}`
        : `/bids/${bidId}/task-definitions`,
      input,
      basis,
      template ? "PUT" : "POST",
    );
    accept(value?.data);
  }
  function accept(value: TemplateView | undefined) {
    if (!value) return;
    if (value.bid_id !== bidId || (template && value.id !== template.id)) {
      setFailure(new Error("模板保存身份不一致，输入保留。"));
      return;
    }
    setSaved(true);
    if (!external) discardKnowledgeForm(formKey);
    onSaved(value);
  }
  async function rebase() {
    setRebaseBusy(true);
    setFailure(null);
    try {
      if (external) {
        setBasis(await external.rebase());
        return;
      }
      const value = template
        ? await api<TemplateView>(
            `/bids/${bidId}/task-definitions/${template.id}`,
          )
        : await api<Bid>(`/bids/${bidId}`);
      if (value.data.id !== (template?.id ?? bidId) || !value.etag)
        throw new Error("当前模板或项目基准身份不一致。");
      setBasis(value.etag);
      command.clearError();
    } catch (error) {
      setFailure(error);
    } finally {
      setRebaseBusy(false);
    }
  }
  return (
    <section className="panel task-editor">
      <div className="section-title">
        <h3>
          {external
            ? "完善任务草案，选择保存用途"
            : template
              ? "保存新的模板版本"
              : "创建可复用任务模板"}
        </h3>
        <button className="text-button" onClick={onClose}>
          收起表单，保留输入
        </button>
      </div>
      <p className="small-note">
        保存不运行、不产生正式决定。默认仅手动；事件或定时必须由你在此明确选择。模板文本不能扩大工具权限。
      </p>
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
              required
              maxLength={200}
              aria-label="模板名称"
              value={input.name}
              onChange={(event) => change({ name: event.target.value })}
            />
          </label>
          <label>
            任务类型
            <select
              aria-label="任务类型"
              value={kindSelected ? input.task_kind : ""}
              onChange={(event) => {
                setKindSelected(true);
                change({
                  task_kind: event.target.value as TemplateRequest["task_kind"],
                  section_id: null,
                });
              }}
            >
              {!kindSelected && <option value="">请明确选择任务类型</option>}
              {Object.entries(taskNames).map(([kind, name]) => (
                <option value={kind} key={kind}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <p className="notice neutral">
            {kindSelected
              ? taskScopes[input.task_kind]
              : "任务类型仍待明确；下方保持可编辑，不默认运行任何类型。"}
          </p>
          <label>
            任务说明
            <textarea
              required
              rows={4}
              maxLength={8000}
              aria-label="任务说明"
              value={input.instructions}
              onChange={(event) => change({ instructions: event.target.value })}
            />
          </label>
          {input.task_kind === "chapter_suggestion" && (
            <>
              <ResourceState
                {...sections}
                hasData={!!sections.data}
                onRetry={() => void sections.reload()}
              />
              <label>
                实际目标章节
                <select
                  aria-label="实际目标章节"
                  required
                  value={input.section_id ?? ""}
                  onChange={(event) =>
                    change({ section_id: event.target.value || null })
                  }
                >
                  <option value="">选择已保存章节</option>
                  {input.section_id &&
                    !options.some(
                      (item) => item.reference?.id === input.section_id,
                    ) && (
                      <option value={input.section_id}>
                        原版本所选章节，需核对当前可用性
                      </option>
                    )}
                  {options.map((item) => (
                    <option key={item.reference!.id} value={item.reference!.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>
              <p className="small-note">
                列表为服务端当前部分投影；未列出可先在章节编制保存并返回刷新，不输入章节标识。
              </p>
            </>
          )}
          <label>
            来源范围
            <select
              aria-label="来源范围"
              value={source.mode}
              disabled={
                source.mode === "exact_package_review" ||
                source.mode === "exact_package_trigger" ||
                source.mode === "exact_package_authoring"
              }
              onChange={(event) =>
                change({
                  source_selection: {
                    mode: event.target.value as
                      | "current_project"
                      | "selected_versions",
                    version_ids: [],
                  },
                })
              }
            >
              <option value="current_project">运行时冻结本项目当前来源</option>
              <option value="selected_versions">明确选定资料版本</option>
              {(source.mode === "exact_package_review" ||
                source.mode === "exact_package_trigger" ||
                source.mode === "exact_package_authoring") && (
                <option value={source.mode}>
                  精确整包输入，须从原入口恢复
                </option>
              )}
            </select>
          </label>
          {source.mode === "selected_versions" && (
            <>
              <ResourceState
                {...materials}
                hasData={materials.data?.bid_id === bidId}
                onRetry={() => void materials.reload()}
              />
              {materials.data?.bid_id === bidId &&
                materials.data.documents.map((doc) => (
                  <label className="evidence-select-item" key={doc.id}>
                    <input
                      type="checkbox"
                      checked={source.version_ids.includes(doc.id)}
                      disabled={
                        !source.version_ids.includes(doc.id) &&
                        source.version_ids.length >= 30
                      }
                      onChange={(event) =>
                        change({
                          source_selection: {
                            mode: "selected_versions",
                            version_ids: event.target.checked
                              ? [...source.version_ids, doc.id]
                              : source.version_ids.filter(
                                  (id) => id !== doc.id,
                                ),
                          },
                        })
                      }
                    />
                    {doc.filename} · 原件修订{doc.file_revision}
                  </label>
                ))}
              {source.version_ids.some(
                (id) => !materials.data?.documents.some((doc) => doc.id === id),
              ) && (
                <p className="notice warning">
                  保留了未在当前资料头中列出的原版本；保存时由服务器核验，未偷偷换成最新稿。
                </p>
              )}
            </>
          )}
          <label>
            触发方式
            <select
              aria-label="触发方式"
              value={trigger.mode}
              onChange={(event) =>
                change({
                  trigger: {
                    mode: event.target.value as typeof trigger.mode,
                    cron: null,
                    timezone: "Asia/Shanghai",
                  },
                })
              }
            >
              <option value="manual">仅手动运行（默认）</option>
              <option value="material_updated">资料实际入库更新后触发</option>
              <option value="schedule">明确按时运行</option>
            </select>
          </label>
          {trigger.mode === "schedule" && (
            <>
              <label>
                定时表达式（分 时 日 月 星期）
                <input
                  required
                  placeholder="例如：0 9 * * 1-5"
                  value={trigger.cron ?? ""}
                  onChange={(event) =>
                    change({
                      trigger: { ...trigger, cron: event.target.value },
                    })
                  }
                />
              </label>
              <p className="small-note">
                时区
                Asia/Shanghai。仅支持服务器校验接受的有界频率；错过的时段跳过，不自动补跑历史。
              </p>
            </>
          )}
          {trigger.mode !== "manual" &&
            ["denial_check", "chapter_suggestion"].includes(
              input.task_kind,
            ) && (
              <p className="notice warning">
                之后按此触发可能请求模型处理并产生费用，仍受输入与资格守卫限制；保存不会立即运行。
              </p>
            )}
          <p className="small-note">
            {triggerDescription(trigger)}
            。修改或暂停只影响之后触发，不取消已冻结任务。
          </p>
        </fieldset>
        <ErrorNotice error={failure ?? external?.error ?? command.error} />
        {conflict && (
          <p className="notice warning">
            模板或项目已被修改，原输入保留；请先核对服务器版本再明确继续，不覆盖他人的配置。
          </p>
        )}
        {saved && (
          <p className="notice success">
            模板已保存，未运行。下一次使用以服务器返回的固定版本为准。
          </p>
        )}
        {missing.length > 0 && (
          <p className="small-note" role="status">
            仍需填写或核对：{missing.join("、")}。
          </p>
        )}
        <div className="review-shortcuts">
          <button
            className="button primary"
            disabled={locked || !!missing.length || !!conflict}
          >
            保存任务模板，不运行
          </button>
          {external?.saveDraftOnly && (
            <button
              type="button"
              className="button secondary"
              disabled={locked || !!missing.length || !!conflict}
              onClick={() => void external.saveDraftOnly?.(input)}
            >
              仅保存草案，不建模板
            </button>
          )}
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => void rebase()}
          >
            已核对当前版本，保留输入继续
          </button>
        </div>
      </form>
      {command.pending && !command.busy && (
        <button
          className="button secondary"
          onClick={() =>
            void command
              .retry<TemplateView>()
              .then((value) => accept(value?.data))
          }
        >
          恢复原模板保存结果
        </button>
      )}
    </section>
  );
}
