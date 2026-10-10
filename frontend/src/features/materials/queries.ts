import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { FileRole, FileVersion } from '../../api/types';

export const fileKeys = {
  list: (projectId: string) => ['projects', projectId, 'files'] as const,
};

export function useFiles(projectId: string) {
  return useQuery<FileVersion[]>({
    queryKey: fileKeys.list(projectId),
    queryFn: ({ signal }) => api.files.list(projectId, { signal }),
  });
}

/** 已被更新版本取代的文件版本 ID（后端按“最新在前”返回，supersedes 指向被取代的旧版本）。 */
export function supersededVersionIds(files: readonly FileVersion[]): Set<string> {
  const out = new Set<string>();
  for (const f of files) if (f.supersedes) out.add(f.supersedes);
  return out;
}

/** 一个逻辑文件（同 file_id 的全部版本）。 */
export interface FileGroup {
  fileId: string;
  role: FileRole;
  /** 最新版本（未被同文件其他版本取代的那个）。 */
  latest: FileVersion;
  /** 当前版本号（从 1 起）。 */
  versionNo: number;
  names: string[];
}

/** 把版本清单按 file_id 归并；版本号 = 沿 supersedes 链的长度，链断开时退回按取得时间排序。 */
export function groupFiles(files: readonly FileVersion[]): FileGroup[] {
  const byFile = new Map<string, FileVersion[]>();
  for (const f of files) byFile.set(f.file_id, [...(byFile.get(f.file_id) ?? []), f]);
  const out: FileGroup[] = [];
  for (const [fileId, vs] of byFile) {
    const superseded = new Set(vs.map((v) => v.supersedes).filter((x): x is string => !!x));
    const heads = vs.filter((v) => !superseded.has(v.version_id));
    const latest = [...(heads.length > 0 ? heads : vs)].sort((a, b) =>
      b.obtained_at.localeCompare(a.obtained_at),
    )[0];
    if (!latest) continue;
    out.push({
      fileId,
      role: latest.role,
      latest,
      versionNo: vs.length,
      names: [...new Set(vs.map((v) => v.original_name))],
    });
  }
  return out.sort((a, b) => b.latest.obtained_at.localeCompare(a.latest.obtained_at));
}

/** 某个版本在其文件里是第几版（按取得时间升序，从 1 起）。 */
export function versionNumberOf(files: readonly FileVersion[], v: FileVersion): number {
  const same = files
    .filter((f) => f.file_id === v.file_id)
    .sort((a, b) => a.obtained_at.localeCompare(b.obtained_at));
  const i = same.findIndex((f) => f.version_id === v.version_id);
  return i < 0 ? same.length + 1 : i + 1;
}
