import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/endpoints';
import type { Task, TaskEvent, TaskKind } from '../../api/types';
import { invalidateProject } from '../projects/queries';

export const TERMINAL: readonly Task['state'][] = ['succeeded', 'failed', 'cancelled'];

export const taskKeys = {
  list: (projectId: string) => ['projects', projectId, 'tasks'] as const,
  one: (taskId: string) => ['tasks', taskId] as const,
};

export function isActive(t: Task): boolean {
  return !TERMINAL.includes(t.state);
}

/** 只有排队、进行中的任务才有进度事件可推；等待补充事实、正在取消的任务靠轮询。 */
export function isStreamable(t: Pick<Task, 'state'>): boolean {
  return t.state === 'queued' || t.state === 'running';
}

/** 同一页同时保持的 SSE 连接上限（浏览器对同源连接数有限，其余任务靠 4 秒轮询）。 */
export const MAX_CONCURRENT_STREAMS = 3;

/** 任务列表里应当开 SSE 的任务 ID：只取排队/进行中的，最多 MAX_CONCURRENT_STREAMS 个。 */
export function streamTaskIds(tasks: readonly Task[], max = MAX_CONCURRENT_STREAMS): Set<string> {
  return new Set(
    tasks
      .filter(isStreamable)
      .slice(0, max)
      .map((t) => t.task_id),
  );
}

/** 项目的任务列表（服务端最新 50 条）。有未结束的任务时每 4 秒刷新一次。 */
export function useProjectTasks(projectId: string) {
  const qc = useQueryClient();
  const q = useQuery<Task[]>({
    queryKey: taskKeys.list(projectId),
    queryFn: ({ signal }) => api.tasks.list(projectId, { signal }),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 4000 : false),
  });
  // 轮询发现任务由进行中变为成功：项目状态（及 revision）可能已变，刷新项目。
  const seenActive = useRef(new Set<string>());
  const data = q.data;
  useEffect(() => {
    if (!data) return;
    let finished = false;
    for (const t of data) {
      if (isActive(t)) seenActive.current.add(t.task_id);
      else if (seenActive.current.delete(t.task_id) && t.state === 'succeeded') finished = true;
    }
    if (finished) void invalidateProject(qc, projectId);
  }, [data, qc, projectId]);
  return q;
}

/** 项目里最近一个未结束的某类任务（用于离开页面再回来时继续显示进度）。 */
export function useActiveTask(projectId: string, kind: TaskKind): Task | undefined {
  const q = useProjectTasks(projectId);
  return q.data?.find((t) => t.kind === kind && isActive(t));
}

export function useTask(taskId: string) {
  return useQuery<Task>({
    queryKey: taskKeys.one(taskId),
    queryFn: () => api.tasks.get(taskId),
    // SSE 之外的兜底：未结束的任务每 4 秒轮询一次。
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.state) ? false : 4000),
  });
}

/**
 * 订阅任务事件（SSE）。EventSource 自带断线重连并携带 Last-Event-ID；
 * 事件到达时刷新任务查询。不支持 EventSource 的环境只靠轮询。
 */
export function useTaskEvents(taskId: string, projectId: string, active: boolean): TaskEvent[] {
  const qc = useQueryClient();
  const [events, setEvents] = useState<TaskEvent[]>([]);
  useEffect(() => {
    if (!active || typeof EventSource === 'undefined') return;
    const es = new EventSource(api.tasks.eventsUrl(taskId), { withCredentials: true });
    // 后端事件名是 task（event: task），不是默认的 message。
    es.addEventListener('task', (m) => {
      try {
        const ev = JSON.parse((m as MessageEvent<string>).data) as TaskEvent;
        setEvents((xs) => [...xs.slice(-49), ev]);
        void qc.invalidateQueries({ queryKey: taskKeys.one(taskId) });
        void qc.invalidateQueries({ queryKey: taskKeys.list(projectId) });
        // 终态事件：任务成功后项目状态可能变化。
        if (ev.state === 'succeeded') void invalidateProject(qc, projectId);
      } catch {
        /* 忽略无法解析的内容 */
      }
    });
    es.onerror = () => {
      // EventSource 会自动重连；连续失败时轮询兜底仍然有效。
    };
    return () => {
      es.close();
    };
  }, [taskId, projectId, active, qc]);
  return events;
}
