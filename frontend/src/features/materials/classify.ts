import type { FileRole } from '../../api/types';
import type { FileGroup } from './queries';

/** 按文件名猜资料用途：命中关键词即取对应用途，先判断更具体的（补遗、清单、图纸），再判断招标文件与施组。 */
const RULES: [RegExp, FileRole][] = [
  [/补遗|答疑|澄清|更正|修改通知/, 'supplement'],
  [/工程量清单|清单|预算|控制价/, 'boq'],
  [/图纸|施工图|设计图|\.dwg$/i, 'drawing'],
  [/中标|评标结果|成绩|开标记录/, 'official_result'],
  [/施工组织|施组|技术标|技术方案|技术文件/, 'body'],
  [/招标/, 'tender'],
];

/**
 * 猜一个文件的用途。``hint`` 是从其他页面带来的用途（例如“上传修改后的正文”），优先使用。
 * 都没命中时：项目还没有招标文件就当作招标文件，否则当作施组正文——这两样是评审必需的。
 */
export function guessRole(
  name: string,
  groups: readonly FileGroup[],
  hint?: FileRole | null,
): FileRole {
  if (hint) return hint;
  const hit = RULES.find(([re]) => re.test(name));
  if (hit) return hit[1];
  return groups.some((g) => g.role === 'tender') ? 'body' : 'tender';
}

/**
 * 默认记为哪个已有文件的新版本（null 为新文件）：同用途下有同名文件就是它；
 * 施组正文通常只有一份，项目里恰好一份正文时，新传的正文默认是它的新版本（改稿后文件名常会变）。
 */
export function defaultTarget(
  name: string,
  role: FileRole,
  groups: readonly FileGroup[],
): string | null {
  const same = groups.filter((g) => g.role === role);
  const byName = same.find((g) => g.names.includes(name));
  if (byName) return byName.fileId;
  if (role === 'body' && same.length === 1) return same[0]?.fileId ?? null;
  return null;
}
