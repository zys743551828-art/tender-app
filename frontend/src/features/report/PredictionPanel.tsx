import { Link } from 'react-router-dom';
import type { Calibration, Prediction, PredictionTopic, ScoringModelRef } from '../../api/types';
import { Tag } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { cn } from '../../lib/cn';
import { validationStatusLabel } from '../../lib/labels';
import { coverageText } from '../../lib/nextAction';
import { ScoreRange } from './ScoreRange';
import { textLink } from '../../components/ui/button';

/** 上线后的持续对照（预测与登记的官方成绩）的一句话说明：样本不足时不给误差，不拿它当准确度。 */
export function calibrationText(c: Calibration): string {
  if (c.state === 'calibrated') {
    return `上线以来已有 ${String(c.pairs)} 组预测与官方技术分的对照：平均绝对误差 ${c.mae ?? '暂无'} 分（百分制），平均偏差 ${c.bias ?? '暂无'} 分。`;
  }
  if (c.state === 'insufficient') {
    return `已有 ${String(c.pairs)} 组官方成绩对照，攒到 ${String(c.needed_pairs)} 组才能给出误差，现在只能看相对高低。`;
  }
  return `还没有官方成绩可以对照，估计值只能看相对高低。登记开标结果后会自动对照，攒到 ${String(c.needed_pairs)} 组给出误差。`;
}

/** 打分模型的来历：用多少组官方成绩训练、评估误差多大、适用于哪些项目。 */
function modelText(m: ScoringModelRef): string {
  return `打分模型用 ${String(m.pairs)} 组官方成绩训练与评估，平均绝对误差 ${m.mae} 分（满分百分制）；适用：${m.scope}。`;
}

/**
 * 技术分预测。分数是否经过打分模型校准始终写明：已校准时给出模型的来历与误差；
 * 未校准时“未校准”和一句原因与分数一起出现，不把它说成对结果的承诺，
 * 评分条款没有覆盖全部技术分时写明“只覆盖 X / Y 分”，免得把部分分值误读成满分。
 * 项目关闭“显示分数”时只列失分点，不出现任何分数。
 */
export function PredictionPanel({
  prediction: p,
  projectId,
  showScore = true,
}: {
  prediction: Prediction | null;
  projectId: string;
  showScore?: boolean;
}) {
  const calibrated = p?.validation_status === 'validated_in_scope';
  const coverage = p && !calibrated ? coverageText(p.maximum, p.technical_full_score) : null;
  return (
    <Card aria-labelledby="pred-h" className="mb-5">
      <CardHeader>
        <CardTitle id="pred-h">{showScore ? '技术分预测' : '可能的失分点'}</CardTitle>
        {showScore && p ? (
          <Tag tone={calibrated ? 'green' : 'amber'}>
            {validationStatusLabel(p.validation_status)}
          </Tag>
        ) : null}
      </CardHeader>
      <CardContent>
        {p === null ? (
          <p className="m-0 text-[13px] text-muted-foreground">
            这一轮没有预测：招标文件的评分条款没有写明分值，或预测还没完成。
          </p>
        ) : !showScore ? (
          <TopicList topics={p.topics} projectId={projectId} showScore={false} />
        ) : (
          <>
            {p.status === 'candidate' && p.estimated_value !== null ? (
              <div className="mb-5">
                <p className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-3xl font-semibold tracking-tight tabular">
                    {p.estimated_value}
                    <span className="ml-1 text-sm font-normal text-muted-foreground">分</span>
                  </span>
                  <span className="text-[13px] text-muted-foreground tabular">
                    {calibrated
                      ? `约 80% 把握在 ${p.low ?? '暂无'}–${p.high ?? '暂无'} 分之间 · 技术标满分 ${p.maximum ?? '暂无'} 分`
                      : `区间 ${p.low ?? '暂无'}–${p.high ?? '暂无'} · 评分条款合计 ${p.maximum ?? '暂无'} 分`}
                  </span>
                </p>
                {coverage ? (
                  <p className="m-0 mt-1 text-[13px] text-warning-foreground">
                    技术标满分 {p.technical_full_score} 分，能识别出分值的评分条款 {coverage}
                    ，其余条款没有计入。
                  </p>
                ) : null}
                <ScoreRange prediction={p} />
                <p className="m-0 mt-2 text-xs text-muted-foreground">
                  {calibrated && p.scoring_model ? modelText(p.scoring_model) : p.reason}
                </p>
              </div>
            ) : (
              <p className="m-0 mb-4 text-[13px] text-muted-foreground">{p.reason}</p>
            )}
            <p className="m-0 mb-5 rounded-md bg-subtle px-3 py-2 text-xs leading-relaxed text-muted-foreground">
              {calibrationText(p.calibration)}
            </p>
            <h3 className="mb-1 text-[13px] font-semibold">最可能失分的地方</h3>
            <TopicList topics={p.topics} projectId={projectId} showScore />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TopicList({
  topics,
  projectId,
  showScore,
}: {
  topics: PredictionTopic[];
  projectId: string;
  showScore: boolean;
}) {
  if (topics.length === 0)
    return <p className="m-0 text-[13px] text-muted-foreground">没有列出失分点。</p>;
  return (
    <ul className="m-0 list-none divide-y divide-border p-0">
      {topics.map((t) => (
        <li key={t.topic} className="py-3.5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <strong className="text-[13px] font-medium">{t.topic}</strong>
            {showScore ? (
              <span className="text-xs font-medium whitespace-nowrap text-danger-foreground tabular">
                估计失 {t.points_lost} 分
              </span>
            ) : null}
          </div>
          <p className="m-0 mt-1 text-[13px] text-muted-foreground">{t.assessment}</p>
          {t.evidence.map((ev) => (
            <blockquote
              key={ev.evidence_id}
              className="m-0 mt-2 border-l-2 border-border-strong bg-subtle px-3 py-2 text-[13px] leading-relaxed"
            >
              {ev.quote}{' '}
              <Link
                className={cn(textLink, 'font-sans text-xs whitespace-nowrap')}
                to={`/projects/${projectId}/evidence/${ev.evidence_id}`}
              >
                第 {ev.physical_page} 页
              </Link>
            </blockquote>
          ))}
          {t.limitations ? (
            <small className="mt-1.5 block text-xs text-muted-foreground">
              局限：{t.limitations}
            </small>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
