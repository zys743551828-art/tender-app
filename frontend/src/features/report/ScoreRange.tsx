import type { Prediction } from '../../api/types';
import { Tooltip } from '../../components/ui/tooltip';

/** 数值只用于画图；界面上显示的分值一律用后端给的十进制字符串。 */
function num(v: string | null): number | null {
  if (v === null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * 估计与区间条：底条是 0 到满分，深色段是区间 low–high，竖线是估计值。
 * 文字描述同时写在 aria-label 里，不依赖颜色传达含义。
 */
export function ScoreRange({ prediction: p }: { prediction: Prediction }) {
  const max = num(p.maximum);
  const low = num(p.low);
  const high = num(p.high);
  const est = num(p.estimated_value);
  if (max === null || max <= 0 || low === null || high === null || est === null) return null;
  const pct = (v: number) => `${String((Math.max(0, Math.min(max, v)) / max) * 100)}%`;
  const label =
    p.validation_status === 'validated_in_scope'
      ? `技术标得分估计 ${p.estimated_value ?? ''}，约 80% 把握在 ${p.low ?? ''} 至 ${p.high ?? ''} 之间，技术标满分 ${p.maximum ?? ''} 分`
      : `技术标得分估计 ${p.estimated_value ?? ''}，区间 ${p.low ?? ''} 至 ${p.high ?? ''}，评分条款合计 ${p.maximum ?? ''} 分`;
  return (
    <figure className="m-0 mt-4 max-w-xl">
      <div role="img" aria-label={label} className="relative pt-5 pb-5">
        <div className="h-2 rounded-full bg-muted" />
        <Tooltip content={`区间 ${p.low ?? ''}–${p.high ?? ''} 分`}>
          <div
            className="absolute top-5 h-2 rounded-full bg-primary/70"
            style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})` }}
          />
        </Tooltip>
        <div
          className="absolute top-3.5 h-5 w-0.5 -translate-x-1/2 rounded-full bg-foreground"
          style={{ left: pct(est) }}
        />
        <span
          className="absolute top-0 -translate-x-1/2 text-xs font-semibold tabular"
          style={{ left: pct(est) }}
        >
          {p.estimated_value}
        </span>
        <span className="absolute bottom-0 left-0 text-[11px] text-muted-foreground tabular">
          0
        </span>
        <span className="absolute right-0 bottom-0 text-[11px] text-muted-foreground tabular">
          {p.maximum}
        </span>
      </div>
      <figcaption className="sr-only">
        深色段为 {p.low}–{p.high} 分的区间，竖线为估计值 {p.estimated_value}，评分条款合计{' '}
        {p.maximum} 分。
      </figcaption>
    </figure>
  );
}
