import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { NextAction, PipelineStatus, ProjectSettings, Report } from '../../api/types';
import { Icon } from '../../components/Icon';
import { EmptyState, ErrorNotice, Loading, PageHead, Stat } from '../../components/ui';
import { Card, CardHeader, CardTitle } from '../../components/ui/card';
import { cn } from '../../lib/cn';
import { formatDateTime } from '../../lib/format';
import { findingCategoryLabel, validationStatusLabel } from '../../lib/labels';
import { actionLabel, actionPath, coverageText } from '../../lib/nextAction';
import { useProjectContext } from '../../routes/ProjectLayout';
import { ComplianceTable } from './ComplianceTable';
import { PipelineBanner } from './PipelineBanner';
import { PredictionPanel } from './PredictionPanel';
import { ProjectAssistant } from './ProjectAssistant';
import { usePipeline, useReport } from './queries';
import { Button, textLink } from '../../components/ui/button';

/**
 * 评审报告：项目的落地页。从上到下回答四个问题——会不会被否决、先做什么、哪些条款没响应好、技术分大概多少。
 * 只汇总后端已有的判定、问题、预测与报价，不在前端做新的判断。
 */
export function ReportPage() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const pipeline = usePipeline(pid);
  const report = useReport(pid);

  if (report.isPending || pipeline.isPending) return <Loading />;
  if (report.isError) {
    return (
      <ErrorNotice
        error={report.error}
        onRetry={() => void report.refetch()}
        title="报告读取失败"
      />
    );
  }
  const status = pipeline.data;
  if (report.data === null) {
    return (
      <>
        <PageHead title="评审报告" />
        {status ? <PipelineBanner pipeline={status} showSteps /> : null}
        <div className="my-5 max-w-lg">
          <ProjectAssistant key={pid} projectId={pid} />
        </div>
        {status?.stage === 'waiting_materials' || !status ? (
          <EmptyState
            icon="FileText"
            title="还没有评审报告"
            action={
              <Button asChild variant="primary">
                <Link to={`/projects/${pid}/materials`}>上传资料</Link>
              </Button>
            }
          >
            上传招标文件和施组正文后自动评审。
          </EmptyState>
        ) : null}
      </>
    );
  }
  const r = report.data;
  const base = `/projects/${pid}`;
  return (
    <>
      <PageHead
        title="评审报告"
        lede={`第 ${String(r.round_no)} 轮 · 基于 ${formatDateTime(r.basis.generated_from_snapshot_at)} 的资料`}
        actions={<ExportButtons projectId={pid} />}
      />
      <PipelineBanner pipeline={status ?? r.pipeline} />
      <Verdict report={r} base={base} settings={project.settings} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <NextActions
            actions={r.next_actions}
            base={base}
            bannerHasAction={needsRestart(status ?? r.pipeline)}
          />
          <ComplianceTable compliance={r.qualification} projectId={pid} />
          <PredictionPanel
            prediction={r.prediction}
            projectId={pid}
            showScore={project.settings.show_score}
          />
        </div>
        <div className="space-y-5 xl:sticky xl:top-6">
          <CategoryLine report={r} base={base} settings={project.settings} />
          <ProjectAssistant key={pid} projectId={pid} />
        </div>
      </div>
    </>
  );
}

function ExportButtons({ projectId }: { projectId: string }) {
  return (
    <>
      <Button asChild size="sm">
        <a href={api.report.docxUrl(projectId)} download>
          <Icon name="Download" />
          下载评审报告（Word）
        </a>
      </Button>
      <Button asChild size="sm">
        <a href={api.report.annotatedPdfUrl(projectId)} download>
          <Icon name="Download" />
          下载批注审阅稿（PDF）
        </a>
      </Button>
    </>
  );
}

/** 结论：一句话回答会不会被否决，下面是三四个关键数字。 */
function Verdict({
  report: r,
  base,
  settings,
}: {
  report: Report;
  base: string;
  settings: ProjectSettings;
}) {
  const open = (c: string) => r.categories.find((x) => x.category === c)?.open ?? 0;
  const risk = open('disqualification') + open('response');
  const q = r.qualification.qualification;
  const unclear = q.unclear + q.failed;
  const p = r.prediction;
  const calibrated = p?.validation_status === 'validated_in_scope';
  const coverage = p && !calibrated ? coverageText(p.maximum, p.technical_full_score) : null;
  const level = risk > 0 ? 'risk' : unclear > 0 ? 'warn' : 'ok';
  const headline =
    risk > 0
      ? `有 ${String(risk)} 个可能导致否决或不满足强制要求的问题还没处理`
      : unclear > 0
        ? `没有发现明确的否决风险，但有 ${String(unclear)} 条要求在正文里找不到明确响应`
        : '没有发现否决风险';
  const best = r.price?.best ?? null;
  return (
    <section
      aria-label="结论"
      data-level={level}
      className={cn(
        'mb-5 rounded-lg border bg-card',
        level === 'risk'
          ? 'is-risk border-danger-border'
          : level === 'warn'
            ? 'border-warning-border'
            : 'border-border',
      )}
    >
      <div className="flex gap-3 px-5 pt-4 pb-4">
        <span
          aria-hidden="true"
          className={cn(
            'mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full',
            level === 'risk'
              ? 'bg-danger-soft text-danger-foreground'
              : level === 'warn'
                ? 'bg-warning-soft text-warning-foreground'
                : 'bg-success-soft text-success-foreground',
          )}
        >
          <Icon
            name={level === 'ok' ? 'Check' : level === 'risk' ? 'CircleAlert' : 'TriangleAlert'}
          />
        </span>
        <div className="min-w-0">
          <p
            className={cn(
              'm-0 text-base font-semibold tracking-tight',
              level === 'risk' && 'text-danger-foreground',
            )}
          >
            {headline}
          </p>
          {r.basis.rules_unconfirmed > 0 && !settings.accept_rules_as_written ? (
            <p className="m-0 mt-1 text-[13px] text-muted-foreground">
              依据的 {r.basis.rules_total} 条规则里有 {r.basis.rules_unconfirmed}{' '}
              条还没核对，暂按原文判断。{' '}
              <Link className={textLink} to={`${base}/basis`}>
                核对规则
              </Link>
            </p>
          ) : null}
        </div>
      </div>
      <dl className="m-0 grid grid-cols-2 border-t border-border sm:grid-cols-3 [&>div]:px-5 [&>div]:py-3.5 [&>div+div]:border-l [&>div+div]:border-border">
        <Stat label="废标／强制要求" value={`满足 ${String(q.satisfied)} / ${String(q.total)}`} />
        {settings.show_score ? (
          <Stat
            label={`预计技术分（${p ? validationStatusLabel(p.validation_status) : '未校准'}）`}
            value={
              p?.status === 'candidate' && p.low !== null && p.high !== null
                ? `${p.low}–${p.high}`
                : '暂无'
            }
            sub={coverage ? <span className="text-warning-foreground">{coverage}</span> : undefined}
          />
        ) : (
          <Stat label="可能的失分点" value={`${String(p?.topics.length ?? 0)} 处`} />
        )}
        {settings.price ? (
          <Stat
            label="报价最优候选"
            value={
              best ? (
                best.price
              ) : (
                <Link className={cn(textLink, 'text-sm')} to={`${base}/price`}>
                  {r.price ? '没有可用候选' : '还没填报价'}
                </Link>
              )
            }
            sub={best ? `价格分 ${best.score}` : undefined}
          />
        ) : null}
      </dl>
    </section>
  );
}

/** 评审本身的动作（开始、重试、重新评审、等待）由顶部的流水线横幅承担，这里只列要人去做的事。 */
const PIPELINE_KEYS = new Set([
  'start_analysis',
  'retry_analysis',
  'reanalyze',
  'wait_analysis',
  'verify_sources',
]);

/** 流水线横幅自带“开始／重新评审”主按钮时，下一步不再用实心按钮，保证一屏只有一个主按钮。 */
function needsRestart(p: PipelineStatus): boolean {
  return (
    !!p.input_verification_required ||
    p.stage === 'failed' ||
    p.stage === 'waiting_start' ||
    (p.stage === 'done' && p.stale_reasons.length > 0)
  );
}

function NextActions({
  actions,
  base,
  bannerHasAction,
}: {
  actions: NextAction[];
  base: string;
  bannerHasAction: boolean;
}) {
  const todo = actions.filter((a) => !PIPELINE_KEYS.has(a.key));
  if (todo.length === 0) return null;
  const remaining = todo.slice(1);
  const criticalKeys = new Set(['handle_disqualification', 'review_unclear', 'confirm_rules']);
  const critical = remaining.filter((a) => criticalKeys.has(a.key));
  const suggestions = remaining.filter((a) => !criticalKeys.has(a.key));
  const count = (items: NextAction[]) => items.reduce((n, a) => n + (a.count ?? 1), 0);
  const row = (a: NextAction, i: number) => (
    <li
      key={a.key}
      className="flex flex-col gap-3 border-b border-border px-5 py-3.5 last:border-0 sm:flex-row sm:items-center"
    >
      <div className="flex min-w-0 flex-1 gap-3">
        <span
          aria-hidden="true"
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground tabular"
        >
          {i + 1}
        </span>
        <div className="min-w-0 flex-1">
          <strong className="block text-[13px] font-medium">{a.title}</strong>
          <p className="m-0 text-xs text-muted-foreground">{a.detail}</p>
        </div>
      </div>
      <Button asChild size="sm" variant={i === 0 && !bannerHasAction ? 'primary' : 'secondary'}>
        <Link to={actionPath(base, a)}>{actionLabel(a)}</Link>
      </Button>
    </li>
  );
  return (
    <Card aria-labelledby="next-h" className="mb-5">
      <CardHeader>
        <CardTitle id="next-h">下一步</CardTitle>
      </CardHeader>
      <ol className="m-0 list-none border-t border-border p-0">{todo.slice(0, 1).map(row)}</ol>
      {todo.length > 1 ? (
        <details key={todo[0]?.key} className="border-t border-border">
          <summary className="cursor-pointer rounded-b-lg px-5 py-3 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
            剩余关键问题 {count(critical)} 项／其他建议 {count(suggestions)} 项
          </summary>
          <ol start={2} className="m-0 list-none border-t border-border p-0">
            {todo.slice(1).map((a, i) => row(a, i + 1))}
          </ol>
        </details>
      ) : null}
    </Card>
  );
}

/** 全部问题：按分类汇总，点击进入对应分类；项目关闭了某项检测时该分类不出现。 */
function CategoryLine({
  report: r,
  base,
  settings,
}: {
  report: Report;
  base: string;
  settings: ProjectSettings;
}) {
  const shown = r.categories.filter(
    (c) =>
      (c.category !== 'consistency' || settings.consistency_check) &&
      (c.category !== 'scope' || settings.scope_check),
  );
  const total = shown.reduce((n, c) => n + c.open, 0);
  return (
    <Card aria-labelledby="cat-h" className="xl:sticky xl:top-6">
      <CardHeader>
        <CardTitle id="cat-h">全部问题</CardTitle>
        <span className="text-xs text-muted-foreground tabular">{total} 个待处理</span>
      </CardHeader>
      <ul className="m-0 list-none px-2 pb-2">
        {shown.map((c) => (
          <li key={c.category}>
            <Link
              to={`${base}/findings?category=${c.category}`}
              className="flex h-9 items-center gap-2 rounded-md px-3 text-[13px] text-foreground no-underline hover:bg-muted"
            >
              <span
                aria-hidden="true"
                className={cn(
                  'size-1.5 rounded-full',
                  c.open === 0
                    ? 'bg-border-strong'
                    : c.category === 'disqualification' || c.category === 'response'
                      ? 'bg-danger'
                      : 'bg-warning',
                )}
              />
              <span className="flex-1">{findingCategoryLabel(c.category)}</span>
              <strong className="font-semibold tabular">{c.open}</strong>
              <span className="text-xs whitespace-nowrap text-muted-foreground tabular">
                待处理 · 共 {c.total}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
