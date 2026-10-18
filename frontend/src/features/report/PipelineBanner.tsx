import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { NextAction, PipelineStatus, PipelineStepState } from '../../api/types';
import { Icon } from '../../components/Icon';
import { ErrorNotice } from '../../components/ui';
import { cn } from '../../lib/cn';
import {
  missingMaterialLabel,
  pipelineStateLabel,
  pipelineStepLabel,
  staleReasonLabel,
} from '../../lib/labels';
import { useProjectContext } from '../../routes/ProjectLayout';
import { useRestartAnalysis } from './queries';
import { Button } from '../../components/ui/button';

const STATE_TEXT: Record<PipelineStepState, string> = {
  waiting: 'text-muted-foreground',
  running: 'text-primary',
  done: 'text-success-foreground',
  failed: 'text-danger-foreground',
};

/**
 * 评审流水线：资料 → 规则 → 核对 → 预测。上传即评审，不需要人点“下一步”；
 * 进行中显示进度，失败给出“重新评审”，资料／规则／事实有更新时提示报告已落后于最新输入。
 * 状态用文字和符号表达，不只靠颜色。
 */
export function PipelineBanner({
  pipeline,
  showSteps = false,
  requiredAction,
}: {
  pipeline: PipelineStatus;
  /** 评审完成且没有更新时默认不占版面；资料页始终显示进度。 */
  showSteps?: boolean;
  requiredAction?: NextAction;
}) {
  const { project } = useProjectContext();
  const restart = useRestartAnalysis(project.project_id);
  const base = `/projects/${project.project_id}`;
  const stale = pipeline.stage === 'done' && pipeline.stale_reasons.length > 0;
  const failed = pipeline.steps.filter((s) => s.state === 'failed');

  const restartButton = (
    <Button
      variant="primary"
      size="sm"
      disabled={restart.isPending}
      onClick={() => {
        restart.mutate(null);
      }}
    >
      {restart.isPending ? '正在提交…' : '重新评审'}
    </Button>
  );
  const startButton = (
    <Button
      variant="primary"
      size="sm"
      disabled={restart.isPending}
      onClick={() => {
        restart.mutate(null);
      }}
    >
      {restart.isPending ? '正在提交…' : '开始评审'}
    </Button>
  );

  const steps = (
    <ol className="m-0 flex list-none flex-wrap items-start gap-y-3 p-0" aria-label="评审进度">
      {pipeline.steps.map((s, i) => (
        <li key={s.key} className="flex min-w-[140px] flex-1 items-start gap-2">
          <span
            aria-hidden="true"
            className={cn(
              'mt-px inline-flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px]',
              s.state === 'done' && 'border-success bg-success text-white dark:text-background',
              s.state === 'running' && 'border-primary text-primary',
              s.state === 'failed' && 'border-danger bg-danger text-white dark:text-background',
              s.state === 'waiting' && 'border-border-strong text-muted-foreground',
            )}
          >
            {s.state === 'done' ? (
              <Icon name="Check" size={12} strokeWidth={2.5} />
            ) : s.state === 'running' ? (
              <Icon name="LoaderCircle" size={12} className="animate-spin" />
            ) : s.state === 'failed' ? (
              <Icon name="X" size={12} strokeWidth={2.5} />
            ) : null}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-medium">{pipelineStepLabel(s.key)}</span>
            <span className={cn('block text-xs', STATE_TEXT[s.state])}>
              {pipelineStateLabel(s.state)}
            </span>
            {s.message ? (
              <small className="block text-xs text-muted-foreground">{s.message}</small>
            ) : null}
          </span>
          {i < pipeline.steps.length - 1 ? (
            <span
              aria-hidden="true"
              className="mx-3 mt-2.5 hidden h-px flex-1 bg-border sm:block"
            />
          ) : null}
        </li>
      ))}
    </ol>
  );

  let title: ReactNode = null;
  let detail: ReactNode = null;
  let action: ReactNode = null;
  let tone: 'warning' | 'danger' | 'ai' | 'neutral' = 'neutral';
  if (pipeline.word_pdf_required) {
    tone = 'warning';
    title = '先核对或补交此稿的 PDF';
    detail = '在对应 Word 原稿处处理，其他资料与历史报告保留。';
    action = (
      <Button asChild size="sm">
        <Link to={`${base}/materials`}>处理此稿的 PDF</Link>
      </Button>
    );
  } else if (pipeline.input_verification_required) {
    tone = 'warning';
    title = '先核实补遗或投标条件，再继续评审';
    detail = '原文的生效关系尚待核实，已有报告保持原来的依据。';
    action = (
      <Button asChild size="sm" variant="primary">
        <Link to={`${base}/basis`}>核实补遗依据</Link>
      </Button>
    );
  } else if (pipeline.stage === 'waiting_materials') {
    tone = 'warning';
    title = `还缺${pipeline.missing.map(missingMaterialLabel).join('、') || '资料'}，暂时不能评审`;
    detail = '上传后自动评审，不需要再点别的。';
    action = (
      <Button asChild size="sm">
        <Link to={`${base}/materials`}>上传资料</Link>
      </Button>
    );
  } else if (pipeline.stage === 'waiting_start') {
    tone = 'warning';
    title = pipeline.round_no ? '资料有更新，等待开始新一轮评审' : '资料已就绪，等待开始评审';
    detail = (
      <>
        本项目设置为手动开始评审，可以在项目设置里改为自动。
        {pipeline.stale_reasons.length > 0 ? (
          <ul className="my-1 list-disc pl-5">
            {pipeline.stale_reasons.map((r) => (
              <li key={r}>{staleReasonLabel(r)}</li>
            ))}
          </ul>
        ) : null}
      </>
    );
    action = startButton;
  } else if (pipeline.stage === 'running') {
    tone = 'ai';
    title = '正在评审';
    detail = '可以离开本页，完成后报告自动更新。';
  } else if (pipeline.stage === 'failed') {
    tone = 'danger';
    title = '评审中断';
    detail = `${
      failed
        .map((s) => `${pipelineStepLabel(s.key)}失败${s.message ? `：${s.message}` : ''}`)
        .join('；') || '某个环节失败了。'
    }已完成的环节不会重做。`;
    action = restartButton;
  } else if (stale) {
    tone = 'warning';
    title = '资料或规则有更新，报告还是基于更早的版本';
    detail = (
      <ul className="my-1 list-disc pl-5">
        {pipeline.stale_reasons.map((r) => (
          <li key={r}>{staleReasonLabel(r)}</li>
        ))}
      </ul>
    );
    action = restartButton;
  } else if (requiredAction?.key === 'retry_analysis') {
    tone = 'danger';
    title = requiredAction.title;
    detail = requiredAction.detail;
    action = restartButton;
  }

  const showStepList =
    pipeline.stage !== 'waiting_materials' && (showSteps || pipeline.stage !== 'done' || stale);
  if (!title && !showSteps) return null;
  return (
    <section
      aria-label="评审流水线"
      aria-live="polite"
      data-tone={tone}
      className={cn(
        'mb-5 rounded-lg border bg-card',
        tone === 'danger' && 'border-danger-border',
        tone === 'warning' && 'border-warning-border',
        tone === 'ai' && 'border-ai-border',
        tone === 'neutral' && 'border-border',
      )}
    >
      {title ? (
        <div
          className={cn(
            'flex flex-col gap-3 rounded-t-lg px-5 py-3.5 sm:flex-row sm:items-center',
            !showStepList && 'rounded-b-lg',
            tone === 'danger' && 'bg-danger-soft text-danger-foreground',
            tone === 'warning' && 'bg-warning-soft text-warning-foreground',
            tone === 'ai' && 'bg-ai-soft text-ai-foreground',
          )}
        >
          <Icon
            name={
              tone === 'danger' ? 'CircleAlert' : tone === 'ai' ? 'LoaderCircle' : 'TriangleAlert'
            }
            className={cn('hidden shrink-0 sm:block', tone === 'ai' && 'animate-spin')}
          />
          <div className="min-w-0 flex-1 text-[13px]">
            <strong className="block font-semibold">{title}</strong>
            {detail ? <div className="opacity-90">{detail}</div> : null}
          </div>
          {action}
        </div>
      ) : null}
      {showStepList ? <div className="px-5 py-4">{steps}</div> : null}
      {restart.isError ? (
        <div className="px-5 pb-4">
          <ErrorNotice error={restart.error} title="没有开始评审" />
        </div>
      ) : null}
    </section>
  );
}
