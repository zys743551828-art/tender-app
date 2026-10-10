const dtf = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const df = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '暂无';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '暂无' : dtf.format(d);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '暂无';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '暂无' : df.format(d);
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '未知';
  if (n < 1024) return `${String(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / 1024 / 1024).toFixed(1)} MiB`;
}

const DAY = 86_400_000;

/** 距截止的人话描述；未设置截止则写"截止时间未设置"，不猜。 */
export function deadlineText(
  iso: string | null,
  now: number = Date.now(),
): { text: string; urgent: boolean } {
  if (!iso) return { text: '截止时间未设置', urgent: false };
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return { text: '截止时间未设置', urgent: false };
  const diff = t - now;
  const base = formatDateTime(iso);
  if (diff < 0) return { text: `${base} · 已过截止`, urgent: true };
  const days = Math.ceil(diff / DAY);
  if (diff < DAY) return { text: `${base} · 不足 1 天`, urgent: true };
  return { text: `${base} · 还剩 ${String(days)} 天`, urgent: days <= 3 };
}

/** datetime-local 值（本地时间，无时区）→ ISO（UTC）。空串 → null。 */
export function localInputToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function isoToLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${String(d.getFullYear())}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 十进制字符串校验（与契约 pattern 一致），分值不转 number。 */
export const DECIMAL_RE = /^(0|[1-9][0-9]*)(\.[0-9]+)?$/;

/** 比较两个十进制字符串（非负）。返回 -1/0/1。 */
export function compareDecimal(a: string, b: string): number {
  const [ai = '0', af = ''] = a.split('.');
  const [bi = '0', bf = ''] = b.split('.');
  if (ai.length !== bi.length) return ai.length < bi.length ? -1 : 1;
  if (ai !== bi) return ai < bi ? -1 : 1;
  const n = Math.max(af.length, bf.length);
  const x = af.padEnd(n, '0');
  const y = bf.padEnd(n, '0');
  return x === y ? 0 : x < y ? -1 : 1;
}

/** 0–1 的比例字符串 → 百分数文字（保留一位小数，整数不带小数）；没有则写“暂无”。 */
export function formatRate(fraction: string | null | undefined): string {
  if (fraction === null || fraction === undefined) return '暂无';
  const n = Number(fraction);
  if (!Number.isFinite(n)) return '暂无';
  const pct = Math.round(n * 1000) / 10;
  return `${String(pct)}%`;
}
