import { useEffect, useState } from "react";
import { api } from "./api";
import type {
  Bid,
  AssistantSourcePage,
  TaskDraftView,
  TaskDraftPage,
  TaskDraftRequest,
  TemplateRequest,
  TemplateView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useTaskPage } from "./useTaskPage";
import { useRecordedCommand } from "./useRecordedCommand";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import { newTaskConfiguration } from "./taskState";
import type { TaskKindPage } from "./contracts";

export function TaskDraftPanel({
  bidId,
  memberId,
  bidEtag,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  bidEtag: string | null;
  onSaved: () => void;
}) {
  const key = knowledgeStorageKey(memberId, bidId) + "task-draft-request:";
  const [text, setText] = useKnowledgeInput(key + "text", "");
  const [sectionId, setSectionId] = useKnowledgeInput(key + "section", "");
  const [basis, setBasis] = useKnowledgeInput(key + "etag", bidEtag ?? "");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(() =>
    new URLSearchParams(window.location.search).get("task_draft"),
  );
  const [failure, setFailure] = useState<unknown>(null);
  const command = useRecordedCommand(`task-draft:${memberId}:${bidId}:create`);
  const drafts = useTaskPage<TaskDraftPage>(
    `/bids/${bidId}/task-definition-drafts?limit=20`,
    0,
    (page) => (page.has_more ? page.next_cursor : null),
  );
  const sections = useResource<AssistantSourcePage>(
    open ? `/assistant/sources?kind=section&bid_id=${bidId}` : null,
  );
  const kinds = useResource<TaskKindPage>("/task-kinds");
  useEffect(() => {
    const sync = () =>
      setSelected(
        new URLSearchParams(window.location.search).get("task_draft"),
      );
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  function select(id: string) {
    const query = new URLSearchParams(window.location.search);
    query.set("task_draft", id);
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    setSelected(id);
  }
  function accept(value: TaskDraftView | undefined) {
    if (!value) return;
    if (value.bid_id !== bidId || value.created_by !== memberId) {
      setFailure(new Error("草案成员或项目身份不一致，未采用。"));
      return;
    }
    select(value.id);
    void drafts.reload();
  }
  async function create() {
    if (!text.trim() || !basis) return;
    const body: TaskDraftRequest = {
      request: text.trim(),
      section_id: sectionId || null,
      source_selection: { mode: "current_project", version_ids: [] },
    };
    const result = await command.run<TaskDraftView>(
      `/bids/${bidId}/task-definition-drafts`,
      body,
      basis,
    );
    accept(result?.data);
  }
  return (
    <section className="task-draft-entry">
      <button
        className="text-button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        用自然语言拟定任务草案／恢复已有草案
      </button>
      {open && (
        <>
          <p className="small-note">
            当前为限定中文解释器，不代表通用自然语言理解已验收。生成的是你的私有可编辑草案，不保存模板、不建立计划、不请求模型或收费运行。
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label>
              想反复完成什么工作
              <textarea
                required
                maxLength={8000}
                aria-label="想反复完成什么工作"
                rows={3}
                value={text}
                disabled={command.busy || !!command.pending}
                onChange={(event) => {
                  if (!basis && bidEtag) setBasis(bidEtag);
                  setText(event.target.value);
                }}
              />
            </label>
            <label>
              如需章节建议，明确选择目标章节
              <select
                aria-label="如需章节建议，明确选择目标章节"
                value={sectionId}
                disabled={command.busy || !!command.pending}
                onChange={(event) => setSectionId(event.target.value)}
              >
                <option value="">尚未指定章节</option>
                {sections.data?.items
                  .filter(
                    (item) =>
                      item.available &&
                      item.bid_id === bidId &&
                      item.reference?.kind === "section",
                  )
                  .map((item) => (
                    <option value={item.reference!.id} key={item.reference!.id}>
                      {item.title}
                    </option>
                  ))}
              </select>
            </label>
            <ResourceState
              {...sections}
              hasData={!!sections.data}
              onRetry={() => void sections.reload()}
            />
            <ErrorNotice error={failure ?? command.error} />
            <button
              className="button secondary"
              disabled={
                !text.trim() ||
                !basis ||
                command.busy ||
                !!command.pending ||
                !!command.conflict
              }
            >
              生成可编辑草案，不保存模板
            </button>
            {command.conflict && (
              <button
                type="button"
                className="text-button"
                onClick={async () => {
                  try {
                    const value = await api<Bid>(`/bids/${bidId}`);
                    if (value.data.id !== bidId || !value.etag)
                      throw new Error("项目身份不一致");
                    setBasis(value.etag);
                    command.clearError();
                  } catch (error) {
                    setFailure(error);
                  }
                }}
              >
                核对当前项目后保留原请求继续
              </button>
            )}
          </form>
          {command.pending && !command.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void command
                  .retry<TaskDraftView>()
                  .then((result) => accept(result?.data))
              }
            >
              恢复原草案受理结果
            </button>
          )}
          <ResourceState
            {...drafts}
            hasData={!!drafts.data}
            onRetry={() => void drafts.reload()}
          />
          <ErrorNotice error={drafts.moreError} />
          {drafts.items
            .filter(
              (item) => item.bid_id === bidId && item.created_by === memberId,
            )
            .map((item) => (
              <button
                className="history-row"
                key={item.id}
                onClick={() => select(item.id)}
              >
                {item.interpretation.name} · 草案修订{item.revision} ·{" "}
                {item.saved_template_id ? "已保存模板" : "可继续编辑"}
              </button>
            ))}
          {drafts.hasMore && (
            <button
              className="text-button"
              disabled={drafts.moreBusy}
              onClick={() => void drafts.more()}
            >
              加载更多我的草案
            </button>
          )}
        </>
      )}
      {selected && (
        <TaskDraftDetail
          key={selected}
          bidId={bidId}
          memberId={memberId}
          id={selected}
          kinds={kinds.data}
          onSaved={() => {
            void drafts.reload();
            onSaved();
          }}
        />
      )}
    </section>
  );
}
function TaskDraftDetail({
  bidId,
  memberId,
  id,
  kinds,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  id: string;
  kinds: TaskKindPage | undefined;
  onSaved: () => void;
}) {
  const path = `/bids/${bidId}/task-definition-drafts/${id}`;
  const resource = useResource<TaskDraftView>(path);
  const draft =
    resource.data?.id === id &&
    resource.data.bid_id === bidId &&
    resource.data.created_by === memberId
      ? resource.data
      : undefined;
  const edit = useRecordedCommand(`task-draft:${memberId}:${bidId}:${id}:edit`);
  const save = useRecordedCommand(`task-draft:${memberId}:${bidId}:${id}:save`);
  const [failure, setFailure] = useState<unknown>(null);
  const [ack, setAck] = useKnowledgeInput<{ etag: string } | null>(
    knowledgeStorageKey(memberId, id) + "task-draft-save-ack",
    null,
  );
  const [intent, setIntent] = useKnowledgeInput<"draft" | "template">(
    knowledgeStorageKey(memberId, id) + "task-draft-intent",
    "draft",
  );
  async function saveAck(
    value: { data: TaskDraftView; etag: string | null } | null,
  ) {
    if (!value) return;
    const current = value.data;
    if (
      current.id !== id ||
      current.bid_id !== bidId ||
      current.created_by !== memberId ||
      !value.etag
    )
      throw new Error("草案确认身份或修订不一致。");
    if (
      current.interpretation.unresolved.length ||
      !current.interpretation.ready_for_template_form
    )
      throw new Error("仍有待明确项；输入可继续编辑，未保存模板。");
    setAck({ etag: value.etag });
    const result = await save.run<TemplateView>(`${path}/save`, {}, value.etag);
    if (result?.data.bid_id === bidId) {
      void resource.reload();
      onSaved();
      return result.data;
    }
    void resource.reload();
  }
  async function submit(input: TemplateRequest) {
    setIntent("template");
    setFailure(null);
    try {
      const result = await edit.run<TaskDraftView>(
        path,
        input,
        ack?.etag ?? resource.etag ?? "",
        "PUT",
      );
      return await saveAck(result);
    } catch (error) {
      setFailure(error);
    }
  }
  async function saveDraftOnly(input: TemplateRequest) {
    setIntent("draft");
    setFailure(null);
    try {
      const value = await edit.run<TaskDraftView>(
        path,
        input,
        ack?.etag ?? resource.etag ?? "",
        "PUT",
      );
      if (value) {
        if (
          value.data.id !== id ||
          value.data.created_by !== memberId ||
          !value.etag
        )
          throw new Error("草案保存身份不一致。");
        setAck({ etag: value.etag });
        void resource.reload();
      }
    } catch (error) {
      setFailure(error);
    }
  }
  async function rebase() {
    const current = await api<TaskDraftView>(path);
    if (
      current.data.id !== id ||
      current.data.created_by !== memberId ||
      !current.etag
    )
      throw new Error("草案基准身份不一致。");
    setAck({ etag: current.etag });
    edit.clearError();
    save.clearError();
    void resource.reload();
    return current.etag;
  }
  const proposal = draft?.interpretation;
  const initial: TemplateRequest = proposal
    ? {
        name: proposal.name,
        task_kind: proposal.task_kind ?? "supplement_impact",
        instructions: proposal.instructions,
        section_id: proposal.section_id,
        source_selection: proposal.source_selection,
        trigger: proposal.trigger,
      }
    : newTaskConfiguration();
  return (
    <section className="task-draft-detail">
      <ResourceState
        {...resource}
        hasData={!!draft}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !draft && (
        <p className="notice error">草案身份不一致，未读取其他成员的草案。</p>
      )}
      {draft && proposal && (
        <>
          <h3>我的可编辑任务草案 · 修订{draft.revision}</h3>
          <p className="small-note">
            创建{new Date(draft.created_at).toLocaleString("zh-CN")}，最近保存
            {new Date(draft.updated_at).toLocaleString("zh-CN")}
            。仅草案持久保存不等于模板或运行。
          </p>
          <details className="coverage-details">
            <summary>原始请求与解释范围</summary>
            <p className="preserve-text">{proposal.raw_request}</p>
            <p>目标：{proposal.target_description}</p>
            <p>输出：{proposal.output_description}</p>
          </details>
          {proposal.unresolved.length > 0 && (
            <div className="notice warning">
              <p>仍需明确，可直接在下方修改，不锁死编辑：</p>
              <ul>
                {proposal.unresolved.map((item, index) => (
                  <li key={index}>
                    {item.field}：{item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {draft.saved_template_id ? (
            <>
              <p className="notice success">
                此草案已一次保存为以下模板；继续修改请建立该模板的新版本，未另建重复模板。
              </p>
              <TaskTemplateCard
                bidId={bidId}
                memberId={memberId}
                id={draft.saved_template_id}
                kinds={kinds}
                onChanged={onSaved}
                onRun={(run) => {
                  window.location.href = `/bids/${bidId}/tasks?run=${encodeURIComponent(run)}`;
                }}
              />
            </>
          ) : (
            <TaskTemplateEditor
              key={id}
              formIdentity={`draft:${id}`}
              bidId={bidId}
              memberId={memberId}
              template={null}
              etag={resource.etag}
              initialConfiguration={initial}
              requireKindSelection={proposal.task_kind === null}
              external={{
                busy: edit.busy || save.busy,
                pending: !!edit.pending || !!save.pending,
                error: failure ?? edit.error ?? save.error,
                conflict: !!edit.conflict || !!save.conflict,
                submit,
                saveDraftOnly,
                rebase,
              }}
              onSaved={() => {
                void resource.reload();
                onSaved();
              }}
              onClose={() => {
                const query = new URLSearchParams(window.location.search);
                query.delete("task_draft");
                window.location.href = `${window.location.pathname}${query.size ? `?${query}` : ""}`;
              }}
            />
          )}
          <ErrorNotice error={failure} />
          {edit.pending && !edit.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void edit
                  .retry<TaskDraftView>()
                  .then(async (value) => {
                    if (intent === "template") return saveAck(value);
                    if (value?.data.id === id && value.etag) {
                      setAck({ etag: value.etag });
                      void resource.reload();
                    }
                  })
                  .catch(setFailure)
              }
            >
              恢复原草案更新结果（保留原保存意图）
            </button>
          )}
          {save.pending && !save.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void save.retry<TemplateView>().then(() => {
                  void resource.reload();
                  onSaved();
                })
              }
            >
              恢复同一次模板保存结果
            </button>
          )}
        </>
      )}
    </section>
  );
}
