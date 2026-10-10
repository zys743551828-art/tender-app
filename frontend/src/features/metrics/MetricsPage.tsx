import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { Metrics } from '../../api/types';
import { EmptyState, ErrorNotice, Loading, PageHead, ProgressBar, Stat } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { formatRate } from '../../lib/format';
import { calibrationText } from '../report/PredictionPanel';
import { BarChart, TrendChart } from './charts';

export const metricsKey = ['metrics'] as const;

/**
 * 度量：只看与中标有关的结果——入围率与中标率、废标／否决风险是否在提交前闭环、预测是否被官方成绩校准过、
 * 每一轮整改带来的预测得分变化。不统计耗时、工时等过程指标。
 */
export function MetricsPage() {
  const q = useQuery<Metrics>({
    queryKey: metricsKey,
    queryFn: ({ signal }) => api.metrics.get({ signal }),
  });
  if (q.isPending) return <Loading />;
  if (q.isError)
    return <ErrorNotice error={q.error} onRetry={() => void q.refetch()} title="度量无法读取" />;
  const m = q.data;
  const o = m.outcomes;
  const k = m.qualification;
  const c = m.calibration;
  return (
    <>
      <PageHead title="度量" lede="入围率、中标率，否决风险有没有在提交前处理掉，预测准不准。" />
      {o.submissions === 0 ? (
        <EmptyState icon="ChartNoAxesCombined" title="登记过提交和开标结果后，这里才有数字">
          在项目的“提交与结果”里登记实际提交，开标后登记结果和技术分。入围率、中标率和预测误差都从这些登记算出来。
        </EmptyState>
      ) : (
        <>
          <Card aria-labelledby="m-out" className="mb-5">
            <CardHeader>
              <CardTitle id="m-out">结果</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="m-0 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="已提交" value={String(o.submissions)} />
                <Stat label="已出结果" value={String(o.decided)} />
                <Stat label="入围率" value={formatRate(o.shortlist_rate)} />
                <Stat label="中标率" value={formatRate(o.award_rate)} />
              </dl>
              <BarChart
                ariaLabel={`结果分布：入围 ${String(o.shortlisted)}，不入围 ${String(o.not_shortlisted)}，被否决 ${String(o.rejected)}，中标 ${String(o.awarded)}，未中标 ${String(o.not_awarded)}`}
                data={[
                  { label: '入围', value: o.shortlisted },
                  { label: '不入围', value: o.not_shortlisted },
                  { label: '被否决', value: o.rejected },
                  { label: '中标', value: o.awarded },
                  { label: '未中标', value: o.not_awarded },
                ]}
              />
              <p className="m-0 text-xs text-muted-foreground">
                入围率 = 入围数 ÷ 已出入围结果数；中标率 = 中标数 ÷ 已出最终结果数。
              </p>
            </CardContent>
          </Card>

          <Card aria-labelledby="m-q" className="mb-5">
            <CardHeader>
              <CardTitle id="m-q">废标／否决风险闭环</CardTitle>
            </CardHeader>
            <CardContent>
              <BarChart
                ariaLabel={`废标风险闭环：评审发现 ${String(k.identified)}，提交前已解决或驳回 ${String(k.resolved_or_dismissed)}，提交时仍未处理 ${String(k.open_at_submission)}，招标方实际否决 ${String(k.rejected_by_buyer)}`}
                data={[
                  { label: '评审发现', value: k.identified },
                  { label: '提交前已解决或驳回', value: k.resolved_or_dismissed },
                  { label: '提交时仍未处理', value: k.open_at_submission, alert: true },
                  { label: '招标方实际否决', value: k.rejected_by_buyer, alert: true },
                ]}
              />
              <p className="m-0 text-xs text-muted-foreground">
                “提交时仍未处理”应为 0；“招标方实际否决”大于 0 时，回看那几个项目是不是漏判了。
              </p>
            </CardContent>
          </Card>

          <Card aria-labelledby="m-cal" className="mb-5">
            <CardHeader>
              <CardTitle id="m-cal">预测校准</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="m-0 mb-3 text-[13px]">{calibrationText(c)}</p>
              <ProgressBar
                value={Math.min(1, c.pairs / Math.max(1, c.needed_pairs))}
                label={`对照样本 ${String(c.pairs)} / ${String(c.needed_pairs)}`}
              />
              <p className="m-0 mt-1.5 text-xs text-muted-foreground tabular">
                对照样本 {c.pairs} / {c.needed_pairs} 组
              </p>
            </CardContent>
          </Card>
        </>
      )}

      {m.trends.length === 0 ? null : (
        <Card aria-labelledby="m-tr" className="mb-5">
          <CardHeader>
            <CardTitle id="m-tr">逐轮整改与预测得分</CardTitle>
          </CardHeader>
          <CardContent>
            {m.trends.map((t) => (
              <article
                key={t.project_id}
                className="border-t border-border pt-4 first:border-0 first:pt-0 [&+&]:mt-5"
              >
                <h3 className="m-0 mb-2 text-sm font-medium">{t.title}</h3>
                <TrendChart trend={t} />
                <div className="relative w-full overflow-x-auto">
                  <table className="data-table">
                    <caption className="sr-only">{t.title} 逐轮数据</caption>
                    <thead>
                      <tr>
                        <th scope="col">轮次</th>
                        <th scope="col" className="num">
                          预测得分估计
                        </th>
                        <th scope="col" className="num">
                          未处理问题
                        </th>
                        <th scope="col" className="num">
                          已处理问题
                        </th>
                        <th scope="col" className="num">
                          未处理的废标／强制类问题
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {t.rounds.map((r) => (
                        <tr key={r.snapshot_id}>
                          <th scope="row">第 {r.round_no} 轮</th>
                          <td className="num">{r.estimated_value ?? '暂无'}</td>
                          <td className="num">{r.open_findings}</td>
                          <td className="num">{r.resolved_findings}</td>
                          <td className="num">{r.open_qualification}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="m-0 mt-2 text-xs text-muted-foreground">
                  评分条款合计 {t.maximum ?? '暂无'} 分 · 实际技术分 {t.actual_value ?? '尚未登记'}
                </p>
              </article>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
