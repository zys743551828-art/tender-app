import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { RoundTrend } from '../../api/types';
import { scoreTicks, useChartColors } from '../../lib/chartColors';
import { cn } from '../../lib/cn';

export interface BarDatum {
  label: string;
  value: number;
  /** 需要警示的一项（例如“提交时仍未处理”大于 0）。 */
  alert?: boolean;
}

/** 横向条形：标签与数值都直接写出，不靠颜色区分；整组有一句完整的读屏描述。 */
export function BarChart({ data, ariaLabel }: { data: BarDatum[]; ariaLabel: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div role="img" aria-label={ariaLabel} className="my-4 grid gap-2">
      {data.map((d) => (
        <div
          key={d.label}
          aria-hidden="true"
          className="grid grid-cols-[minmax(96px,160px)_minmax(0,1fr)_40px] items-center gap-3 text-[13px]"
        >
          <span className="truncate text-muted-foreground">{d.label}</span>
          <span className="h-2 overflow-hidden rounded-full bg-muted">
            {d.value > 0 ? (
              <span
                className={cn(
                  'block h-full rounded-full',
                  d.alert && d.value > 0 ? 'bg-danger' : 'bg-primary',
                )}
                style={{ width: `${String(Math.max(2, (d.value / max) * 100))}%` }}
              />
            ) : null}
          </span>
          <span className="text-right font-medium tabular">{d.value}</span>
        </div>
      ))}
    </div>
  );
}

interface TrendRow {
  round: string;
  value: number | null;
}

function TrendTip({ active, payload }: { active?: boolean; payload?: { payload: TrendRow }[] }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <p className="m-0 font-medium">{row.round}</p>
      <p className="m-0 text-muted-foreground tabular">预测得分估计 {row.value ?? '暂无'}</p>
    </div>
  );
}

/**
 * 逐轮趋势：折线是每一轮评审的预测得分估计，横轴是轮次，纵轴 0 到满分；
 * 有官方技术分时用虚线标出。没有估计的轮次断开不连线；不足两轮不画。悬停看数值，同样的数值在下方表格里。
 */
export function TrendChart({ trend }: { trend: RoundTrend }) {
  const c = useChartColors();
  const max = Number(trend.maximum);
  // 只有一轮时没有“趋势”可看，数值见下方表格。
  if (!Number.isFinite(max) || max <= 0 || trend.rounds.length < 2) return null;
  const data: TrendRow[] = trend.rounds.map((r) => {
    const v = r.estimated_value === null ? null : Number(r.estimated_value);
    return {
      round: `第 ${String(r.round_no)} 轮`,
      value: v !== null && Number.isFinite(v) ? v : null,
    };
  });
  const actual = trend.actual_value === null ? null : Number(trend.actual_value);
  const label = `${trend.title} 逐轮预测得分估计，满分 ${trend.maximum ?? ''}${trend.actual_value ? `，实际技术分 ${trend.actual_value}` : ''}`;
  const tick = { fill: c['muted-foreground'], fontSize: 11 };
  return (
    <div role="img" aria-label={label} className="h-[200px] w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={240}>
        <LineChart data={data} margin={{ top: 16, right: 16, bottom: 0, left: -16 }}>
          <CartesianGrid stroke={c.border} vertical={false} />
          <XAxis
            dataKey="round"
            tick={tick}
            tickLine={false}
            axisLine={{ stroke: c.border }}
            padding={{ left: 24, right: 24 }}
          />
          <YAxis
            type="number"
            domain={[0, max]}
            ticks={scoreTicks(max)}
            tick={tick}
            tickLine={false}
            axisLine={false}
            width={44}
          />
          <Tooltip
            content={<TrendTip />}
            cursor={{ stroke: c['muted-foreground'], strokeDasharray: '3 3' }}
            isAnimationActive={false}
          />
          {actual !== null && Number.isFinite(actual) ? (
            <ReferenceLine
              y={actual}
              stroke={c['muted-foreground']}
              strokeDasharray="4 4"
              label={{
                value: `实际技术分 ${trend.actual_value ?? ''}`,
                position: 'insideTopRight',
                fill: c['muted-foreground'],
                fontSize: 11,
              }}
            />
          ) : null}
          <Line
            dataKey="value"
            type="linear"
            stroke={c.primary}
            strokeWidth={2}
            connectNulls={false}
            dot={{ r: 4, fill: c.primary, stroke: c.card, strokeWidth: 2 }}
            activeDot={{ r: 5, fill: c.primary, stroke: c.card, strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
