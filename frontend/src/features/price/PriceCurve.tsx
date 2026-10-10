import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { PricePoint } from '../../api/types';
import { scoreTicks, useChartColors } from '../../lib/chartColors';
import { priceFlagLabel } from '../../lib/labels';

function n(v: string): number {
  return Number(v);
}

interface Row {
  x: number;
  curve?: number;
  candidate?: number;
  flags?: string[];
  best?: boolean;
}

function TipBody({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const score = row.candidate ?? row.curve;
  return (
    <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <p className="m-0 font-medium tabular">报价 {row.x}</p>
      <p className="m-0 text-muted-foreground tabular">价格分 {score}</p>
      {row.best ? <p className="m-0 text-primary">最优候选</p> : null}
      {row.flags?.length ? (
        <p className="m-0 text-danger-foreground">{row.flags.map(priceFlagLabel).join('；')}</p>
      ) : null}
    </div>
  );
}

/**
 * 价格分曲线：横轴报价，纵轴价格分（0 到满分）。虚线是基准价，圆点是候选报价；
 * 悬停看具体数值，所有数值同时在下方结果表里以文字给出，图只是辅助。
 */
export function PriceCurve({
  curve,
  candidates,
  benchmark,
  fullScore,
  best,
}: {
  curve: PricePoint[];
  candidates: PricePoint[];
  benchmark: string | null;
  fullScore: string;
  best: PricePoint | null;
}) {
  const c = useChartColors();
  const line: Row[] = curve
    .map((p) => ({ x: n(p.price), curve: n(p.score) }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.curve));
  const full = n(fullScore);
  if (line.length < 2 || !Number.isFinite(full) || full <= 0) return null;
  const dots: Row[] = candidates
    .map((p) => ({
      x: n(p.price),
      candidate: n(p.score),
      flags: p.flags,
      best: best !== null && best.price === p.price,
    }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.candidate));
  const xs = line.map((p) => p.x);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const bench = benchmark === null ? null : n(benchmark);
  const label = `价格分曲线：报价从 ${String(Math.round(xMin))} 到 ${String(Math.round(xMax))}，价格分在 0 到 ${fullScore} 之间${benchmark ? `，基准价 ${benchmark}` : ''}`;
  const tick = { fill: c['muted-foreground'], fontSize: 11 };
  return (
    <figure className="m-0 mt-4">
      <div role="img" aria-label={label} className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%" minWidth={240}>
          <ComposedChart margin={{ top: 24, right: 12, bottom: 4, left: -12 }}>
            <CartesianGrid stroke={c.border} vertical={false} />
            <XAxis
              type="number"
              dataKey="x"
              domain={[xMin, xMax]}
              tick={tick}
              tickLine={false}
              axisLine={{ stroke: c.border }}
              tickFormatter={(v: number) => String(Math.round(v))}
            />
            <YAxis
              type="number"
              domain={[0, full]}
              ticks={scoreTicks(full)}
              tick={tick}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              content={<TipBody />}
              cursor={{ stroke: c['muted-foreground'], strokeDasharray: '3 3' }}
              isAnimationActive={false}
            />
            {bench !== null && bench >= xMin && bench <= xMax ? (
              <ReferenceLine
                x={bench}
                stroke={c['muted-foreground']}
                strokeDasharray="4 4"
                label={{
                  value: `基准价 ${benchmark ?? ''}`,
                  position: 'top',
                  fill: c['muted-foreground'],
                  fontSize: 11,
                }}
              />
            ) : null}
            <Line
              data={line}
              dataKey="curve"
              type="linear"
              stroke={c.primary}
              strokeWidth={2}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />
            <Scatter
              data={dots}
              dataKey="candidate"
              isAnimationActive={false}
              shape={(props: { cx?: number; cy?: number; payload?: Row }) => {
                const r = props.payload;
                if (props.cx === undefined || props.cy === undefined || !r) return <g />;
                const flagged = (r.flags?.length ?? 0) > 0;
                return (
                  <g>
                    <circle
                      cx={props.cx}
                      cy={props.cy}
                      r={r.best ? 6 : 5}
                      fill={flagged ? c.card : c.primary}
                      stroke={flagged ? c.danger : c.card}
                      strokeWidth={2}
                    />
                    {r.best ? (
                      <circle
                        cx={props.cx}
                        cy={props.cy}
                        r={9}
                        fill="none"
                        stroke={c.foreground}
                        strokeWidth={1.5}
                      />
                    ) : null}
                  </g>
                );
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-xs text-muted-foreground">
        空心红圈是触发风险提示的候选，外加一圈的是最优候选。具体数值见上表。
      </figcaption>
    </figure>
  );
}
