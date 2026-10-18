import type { FileRole, FileVersion, Task } from '../../api/types';

/** 上传完成后后端只为这些用途的文件排解析任务。 */
export const PARSED_ROLES: readonly FileRole[] = ['tender', 'supplement', 'body', 'submission'];

/** 解析任务与文件版本的时间配对窗口：任务在上传完成时入队，通常与取得时间相差几秒。 */
const PAIR_WINDOW_MS = 10 * 60_000;

/**
 * 把 kind=parse 的任务配到文件版本上。任务若带 file_version_id 就直接用；
 * 否则按“创建时间与文件取得时间最接近”一对一配对（窗口内）。配不上的文件没有状态（旧任务可能已不在最新 50 条里）。
 */
export function parseTaskByVersion(
  files: readonly FileVersion[],
  tasks: readonly Task[],
): Map<string, Task> {
  const out = new Map<string, Task>();
  const parses = tasks.filter((t) => t.kind === 'parse');
  const used = new Set<string>();
  for (const t of parses) {
    if (t.file_version_id && files.some((f) => f.version_id === t.file_version_id)) {
      const prev = out.get(t.file_version_id);
      if (!prev || Date.parse(t.created_at) > Date.parse(prev.created_at))
        out.set(t.file_version_id, t);
      used.add(t.task_id);
    }
  }
  const pending = files.filter((f) => PARSED_ROLES.includes(f.role) && !out.has(f.version_id));
  interface Pair {
    f: FileVersion;
    t: Task;
    gap: number;
  }
  const pairs: Pair[] = [];
  for (const f of pending)
    for (const t of parses) {
      if (used.has(t.task_id) || t.file_version_id) continue;
      const gap = Math.abs(Date.parse(t.created_at) - Date.parse(f.obtained_at));
      if (gap <= PAIR_WINDOW_MS) pairs.push({ f, t, gap });
    }
  pairs.sort((a, b) => a.gap - b.gap);
  const doneFiles = new Set<string>();
  for (const { f, t } of pairs) {
    if (used.has(t.task_id) || doneFiles.has(f.version_id)) continue;
    used.add(t.task_id);
    doneFiles.add(f.version_id);
    out.set(f.version_id, t);
  }
  return out;
}

/** 解析成功：任务成功完成。读不出文字的文件后端直接把任务标为失败并给出原因。 */
export function parseOk(t: Task | undefined): boolean {
  return t?.state === 'succeeded';
}

export interface ExtractReadiness {
  /** 至少有一份招标文件，且每份招标文件／补遗的最新版本都解析成功。 */
  ready: boolean;
  hasTender: boolean;
  /** 还没解析成功的招标文件／补遗数量（未知状态也算）。 */
  waiting: number;
}

/** 提取规则前的资料就绪度；只看每个文件的最新版本（后端按“最新在前”返回，被取代的旧版本忽略）。 */
export function extractReadiness(
  files: readonly FileVersion[],
  parse: ReadonlyMap<string, Task>,
): ExtractReadiness {
  const superseded = new Set(files.flatMap((f) => (f.supersedes ? [f.supersedes] : [])));
  const heads = files.filter(
    (f) =>
      (f.role === 'tender' || f.role === 'supplement') &&
      !superseded.has(f.version_id) &&
      !f.source_word_version_id,
  );
  const hasTender = heads.some((f) => f.role === 'tender');
  const waiting = heads.filter(
    (f) => !parseOk(parse.get(f.word ? (f.word.adopted_pdf_version_id ?? '') : f.version_id)),
  ).length;
  return { ready: hasTender && waiting === 0, hasTender, waiting };
}
