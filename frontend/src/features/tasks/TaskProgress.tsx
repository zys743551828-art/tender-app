import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { ErrorNotice, Loading, Notice, Tag } from '../../components/ui';
import { purposeLabel, taskKindLabel, taskStageLabel, taskStateLabel } from '../../lib/labels';
import { invalidateProject } from '../projects/queries';
import { isStreamable, useTask, useTaskEvents } from './queries';
import { STATE_TONE, errorHint } from './shared';
import { WaitingInputNotice } from './WaitingInputNotice';
import { textLink } from '../../components/ui/button';

/**
 * 跟踪一个任务：显示状态与阶段（SSE，轮询兜底）。任务成功时调用一次 onSucceeded，
 * 由调用方刷新各自的列表（规则、问题、改稿建议）。
 */
export function TaskProgress({
  taskId,
  projectId,
  onSucceeded,
}: {
  taskId: string;
  projectId: string;
  onSucceeded?: () => void;
}) {
  const q = useTask(taskId);
  const t = q.data;
  const qc = useQueryClient();
  const streaming = t !== undefined && isStreamable(t);
  const events = useTaskEvents(taskId, projectId, streaming);
  // 记录已触发回调的任务 ID：换了任务（重新评审）后必须能再次触发。
  const firedFor = useRef<string | null>(null);
  useEffect(() => {
    if (t?.state === 'succeeded' && firedFor.current !== taskId) {
      firedFor.current = taskId;
      void invalidateProject(qc, projectId);
      onSucceeded?.();
    }
  }, [t?.state, taskId, projectId, qc, onSucceeded]);

  if (q.isPending) return <Loading label="正在读取任务进度…" />;
  if (q.isError || !t) {
    return (
      <ErrorNotice error={q.error} title="任务进度无法读取" onRetry={() => void q.refetch()} />
    );
  }
  const stage = events.at(-1)?.stage ?? t.stage;
  return (
    <div
      className="grid gap-2 rounded-md border border-border px-4 py-3 text-[13px] [&_p]:m-0"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-2">
        <strong className="font-medium">{taskKindLabel(t.kind)}</strong>
        <Tag tone={STATE_TONE[t.state]}>{taskStateLabel(t.state)}</Tag>
        <span className="text-xs text-muted-foreground">
          {purposeLabel(t.purpose)} · 第 {t.attempt} 次尝试
        </span>
      </div>
      {t.state === 'succeeded' ? null : (
        <p className="text-muted-foreground">当前阶段：{taskStageLabel(stage)}</p>
      )}
      {t.state === 'waiting_input' ? <WaitingInputNotice projectId={projectId} /> : null}
      {t.message ? <p className="text-muted-foreground">{t.message}</p> : null}
      {t.state === 'failed' ? (
        <Notice>
          {t.error_code ? errorHint(t.error_code) : '任务失败。'}
          <Link className={textLink} to={`/projects/${projectId}`}>
            回到“报告”重新评审
          </Link>
        </Notice>
      ) : null}
      {t.state === 'cancelled' ? <p className="text-muted-foreground">任务已取消。</p> : null}
    </div>
  );
}
