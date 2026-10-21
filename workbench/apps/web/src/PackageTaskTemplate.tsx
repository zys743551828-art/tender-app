import { useEffect, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  Bid,
  TaskKindPage,
  TemplateRequest,
  TemplateView,
} from "./contracts";
import { ErrorNotice } from "./components";
import {
  packageTaskCapability,
  packageTaskConfiguration,
} from "./packageTaskTemplateSelection";
import type { PackageTaskSelectionProps } from "./packageTaskTemplateSelection";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { TaskTemplateEditor } from "./TaskTemplateEditor";

/** Keep the explicitly opened selection stable while a different plan is inspected. */
export default function PackageTaskTemplate(props: PackageTaskSelectionProps) {
  const [session, setSession] = useState<PackageTaskSelectionProps | null>(
    null,
  );
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<TemplateView | null>(null);
  const available = supportsApi(
    "POST",
    `/bids/${props.scope.bidId}/task-definitions`,
  );
  return (
    <section className="package-review__selected" aria-label="保存整包手动任务">
      <h4>把这份输入保存为手动任务</h4>
      <p>
        模板记录已选整包修订、冻结输入和依赖计划。保存后，可在“可复用任务”中明确启动；保存本身不运行核查。
      </p>
      <button
        type="button"
        className="button secondary"
        disabled={!available}
        aria-expanded={open}
        onClick={() => {
          if (!session)
            setSession(
              structuredClone({
                scope: props.scope,
                frozen: props.frozen,
                prepared: props.prepared,
                plan: props.plan,
              }),
            );
          setOpen(true);
        }}
      >
        {session ? "继续填写手动任务模板" : "保存为手动任务"}
      </button>
      {!available && (
        <p className="muted">当前服务尚未提供任务模板保存接口。</p>
      )}
      {session && (
        <div hidden={!open}>
          {session.plan.digest !== props.plan.digest && (
            <p className="notice neutral">
              表单保留打开时选用的计划，上方的新选择不会替换正在编辑或等待回执的任务输入。
            </p>
          )}
          <TemplateSession
            {...session}
            onClose={() => setOpen(false)}
            onSaved={(item) => {
              setSaved(item);
              setSession(null);
              setOpen(false);
            }}
          />
        </div>
      )}
      {saved && (
        <div className="notice success" role="status">
          <strong>已保存模板：{saved.configuration.name}</strong>
          <p>此操作没有启动核查。模板版本：{saved.revision}。</p>
          <a className="text-link" href={`/bids/${props.scope.bidId}/tasks`}>
            前往可复用任务查看并手动运行
          </a>
        </div>
      )}
    </section>
  );
}

function TemplateSession({
  onSaved,
  onClose,
  ...props
}: PackageTaskSelectionProps & {
  onSaved: (item: TemplateView) => void;
  onClose: () => void;
}) {
  const [selection] = useState(props);
  const [ready, setReady] = useState<{
    configuration: TemplateRequest;
    etag: string;
    runAvailable: boolean;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const identity = `package:${selection.prepared.manifest.id}:${selection.plan.manifest.id}`;
  usePackageScopeGuard(`task-template-read:${identity}`, { busy: loading });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [kinds, bid] = await Promise.all([
          api<TaskKindPage>("/task-kinds"),
          api<Bid>(`/bids/${selection.scope.bidId}`),
        ]);
        if (
          bid.data.id !== selection.scope.bidId ||
          !bid.etag ||
          !new RegExp(`^"bid:${selection.scope.bidId}:[a-f0-9]{64}"$`).test(
            bid.etag,
          )
        )
          throw new Error("项目修订基准身份不一致，未创建模板表单。");
        const capability = packageTaskCapability(kinds.data);
        const configuration = await packageTaskConfiguration(
          selection,
          capability,
        );
        if (active)
          setReady({
            configuration,
            etag: bid.etag,
            runAvailable: capability.available,
          });
      } catch (failure) {
        if (active) setError(failure);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [attempt, selection]);
  return (
    <>
      {loading && <p role="status">正在核对所选输入和当前项目修订…</p>}
      {error != null && (
        <ErrorNotice
          error={error}
          onRetry={() => setAttempt((value) => value + 1)}
        />
      )}
      {ready && !loading && error == null && (
        <>
          {!ready.runAvailable && (
            <p className="notice neutral">
              目前执行服务尚未就绪，仍可保存这份手动模板；运行时将重新核验执行条件。
            </p>
          )}
          <TaskTemplateEditor
            bidId={selection.scope.bidId}
            memberId={selection.scope.memberId}
            template={null}
            etag={ready.etag}
            formIdentity={identity}
            initialConfiguration={ready.configuration}
            onSaved={onSaved}
            onClose={onClose}
          />
        </>
      )}
    </>
  );
}
