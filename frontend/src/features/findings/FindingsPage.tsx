import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  FINDING_CATEGORIES,
  type Finding,
  type FindingCategory,
  type FindingStatus,
} from '../../api/types';
import { Tabs, type TabDef } from '../../components/Tabs';
import { EmptyState, ErrorNotice, Loading, PageHead, Tag } from '../../components/ui';
import {
  findingCategoryHint,
  findingCategoryLabel,
  findingImpactLabel,
  findingSeverityLabel,
  findingStatusLabel,
} from '../../lib/labels';
import { useProjectContext } from '../../routes/ProjectLayout';
import { PipelineBanner } from '../report/PipelineBanner';
import { usePipeline, useReport } from '../report/queries';
import { FindingDetail } from './FindingDetail';
import { OPEN_STATUSES, findingCode, statusTone } from './shared';
import { useFindings } from './queries';
import { Button, textLink } from '../../components/ui/button';
import { Kbd } from '../../components/ui/kbd';
import { cn } from '../../lib/cn';
import { Select } from '../../components/ui/input';

const STATUSES: FindingStatus[] = [
  'candidate',
  'confirmed',
  'deferred',
  'revision_pending',
  'recheck_pending',
  'resolved',
  'rejected',
];

function asCategory(v: string | null): FindingCategory {
  return FINDING_CATEGORIES.find((c) => c === v) ?? 'disqualification';
}

/**
 * 问题：按分类分页签，列表（键集分页）＋详情＋证据与复核。问题属于最近一轮已完成的评审；
 * 新一轮评审完成后列表自动换成新一轮的问题。
 */
export function FindingsPage() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const [sp, setSp] = useSearchParams();
  const [status, setStatus] = useState('');
  const pipeline = usePipeline(pid);
  const report = useReport(pid);
  const qualificationEntry = sp.get('priority') === 'qualification' && !sp.has('category');
  const priorityCategory = report.data?.categories.some(
    (c) => c.category === 'disqualification' && c.open > 0,
  )
    ? 'disqualification'
    : report.data?.categories.some((c) => c.category === 'response' && c.open > 0)
      ? 'response'
      : 'disqualification';
  const category = qualificationEntry ? priorityCategory : asCategory(sp.get('category'));
  // 只在入口解析一次，审核后仍留在原分类，显式分类链接也不受影响。
  useEffect(() => {
    if (!qualificationEntry || !report.isSuccess) return;
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('priority');
        next.set('category', priorityCategory);
        return next;
      },
      { replace: true },
    );
  }, [qualificationEntry, report.isSuccess, priorityCategory, setSp]);
  const snapshotId = pipeline.data?.snapshot_id ?? undefined;
  const q = useFindings(
    pid,
    { snapshotId, status: status || undefined, category },
    { enabled: snapshotId !== undefined && (!qualificationEntry || report.isSuccess) },
  );
  const base = `/projects/${pid}`;

  const shown = useMemo(() => q.data?.pages.flatMap((p) => p.items) ?? [], [q.data]);
  const selectedId = sp.get('finding');
  const selected = shown.find((f) => f.finding_id === selectedId) ?? shown[0] ?? null;
  const selectedIndex = selected
    ? shown.findIndex((f) => f.finding_id === selected.finding_id)
    : -1;
  const openCount = shown.filter((f) => OPEN_STATUSES.includes(f.status)).length;
  const detailRef = useRef<HTMLDivElement>(null);

  const setParam = (key: string, value: string | null, resetFinding: boolean) => {
    setSp(
      (prev) => {
        const n = new URLSearchParams(prev);
        if (value === null) n.delete(key);
        else n.set(key, value);
        if (resetFinding) n.delete('finding');
        return n;
      },
      { replace: true },
    );
  };
  const select = (f: Finding, scroll = true) => {
    setParam('finding', f.finding_id, false);
    // 手机上列表与详情上下堆叠：选中后把详情带到视野里。
    if (scroll && window.matchMedia('(max-width: 850px)').matches) {
      detailRef.current?.scrollIntoView({ block: 'start' });
    }
  };
  const step = (delta: 1 | -1) => {
    const f = shown[selectedIndex + delta];
    if (f) select(f, false);
  };
  /** 处理完一条后，跳到列表里它后面的下一条未处理问题（没有就留在原地）。 */
  const advance = () => {
    if (!selected) return;
    const next = shown.slice(selectedIndex + 1).find((f) => OPEN_STATUSES.includes(f.status));
    if (next) select(next, false);
  };
  // J / K 在问题之间切换；在输入框里打字时不响应。
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
      if (e.key === 'j') stepRef.current(1);
      else if (e.key === 'k') stepRef.current(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  const counts = report.data?.categories;
  const tabs: TabDef[] = FINDING_CATEGORIES.map((c) => {
    const n = counts?.find((x) => x.category === c);
    return {
      id: c,
      label: n ? `${findingCategoryLabel(c)}（${String(n.open)}）` : findingCategoryLabel(c),
      panel: null,
    };
  });

  const list = (
    <>
      <p className="-mt-2 mb-4 text-[13px] text-muted-foreground">
        {findingCategoryHint(category)}
      </p>
      {qualificationEntry && report.isPending ? <Loading /> : null}
      {qualificationEntry && report.isError ? (
        <ErrorNotice error={report.error} onRetry={() => void report.refetch()} />
      ) : null}
      {q.isPending && snapshotId !== undefined && !qualificationEntry ? <Loading /> : null}
      {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
      {q.isSuccess && shown.length === 0 && !status ? (
        <EmptyState
          icon="CircleCheck"
          title={`这一轮没有发现“${findingCategoryLabel(category)}”问题`}
        >
          图纸、示意图里的内容仍需要人看。
        </EmptyState>
      ) : null}
      {q.isSuccess && (shown.length > 0 || status) ? (
        <div className="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside
            className="overflow-hidden rounded-lg border border-border bg-card xl:sticky xl:top-6"
            aria-label="问题列表"
          >
            <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
              <span className="flex-1 text-xs text-muted-foreground">
                {status ? '已按状态筛选' : `${String(openCount)} 项待处理`}
                {q.hasNextPage ? '（已加载部分）' : ''}
              </span>
              <Select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                }}
                aria-label="按状态筛选"
                className="h-8 w-auto text-xs"
              >
                <option value="">全部状态</option>
                {STATUSES.map((n) => (
                  <option key={n} value={n}>
                    {findingStatusLabel(n)}
                  </option>
                ))}
              </Select>
            </div>
            {shown.length === 0 ? (
              <p className="m-0 p-4 text-[13px] text-muted-foreground">没有符合筛选条件的问题。</p>
            ) : (
              <ul className="m-0 max-h-[calc(100dvh-220px)] list-none overflow-y-auto p-1.5">
                {shown.map((f) => {
                  const on = selected?.finding_id === f.finding_id;
                  return (
                    <li key={f.finding_id}>
                      <button
                        type="button"
                        aria-current={on ? 'true' : undefined}
                        onClick={() => {
                          select(f);
                        }}
                        className={cn(
                          'flex w-full cursor-pointer flex-col items-start gap-1.5 rounded-md px-3 py-2.5 text-left transition-colors',
                          on ? 'bg-muted ring-1 ring-border' : 'hover:bg-subtle',
                        )}
                      >
                        <span className="flex w-full items-start gap-2">
                          <span
                            aria-hidden="true"
                            className={cn(
                              'mt-1.5 size-1.5 shrink-0 rounded-full',
                              OPEN_STATUSES.includes(f.status)
                                ? f.severity === 'critical'
                                  ? 'bg-danger'
                                  : 'bg-warning'
                                : 'bg-border-strong',
                            )}
                          />
                          <span className="text-[13px] leading-snug font-medium break-words">
                            {f.statement}
                          </span>
                        </span>
                        <span className="flex flex-wrap items-center gap-1.5 pl-3.5">
                          {f.severity === 'critical' ? (
                            <Tag tone="red">{findingSeverityLabel(f.severity)}</Tag>
                          ) : null}
                          {f.status === 'candidate' ? (
                            <Tag tone="ai">待核实</Tag>
                          ) : (
                            <Tag tone={statusTone(f.status)}>{findingStatusLabel(f.status)}</Tag>
                          )}
                          <span className="font-mono text-[11px] text-muted-foreground">
                            {findingCode(f.finding_id)} · {findingImpactLabel(f.impact)}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
              {q.hasNextPage ? (
                <button
                  type="button"
                  className={cn(textLink, 'text-xs')}
                  disabled={q.isFetchingNextPage}
                  onClick={() => void q.fetchNextPage()}
                >
                  {q.isFetchingNextPage ? '加载中…' : '加载更多'}
                </button>
              ) : (
                `共 ${String(shown.length)} 条`
              )}
            </div>
          </aside>
          {selected ? (
            <div ref={detailRef} className="min-w-0 scroll-mt-4">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
                <span className="mr-1 text-muted-foreground tabular">
                  第 {selectedIndex + 1} / {shown.length} 条
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={selectedIndex <= 0}
                  title="快捷键 K"
                  aria-keyshortcuts="k"
                  onClick={() => {
                    step(-1);
                  }}
                >
                  ‹ 上一条
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={selectedIndex >= shown.length - 1}
                  title="快捷键 J"
                  aria-keyshortcuts="j"
                  onClick={() => {
                    step(1);
                  }}
                >
                  下一条 ›
                </Button>
                <span className="ml-auto hidden items-center gap-1 text-xs text-muted-foreground sm:flex">
                  <Kbd>K</Kbd>
                  <Kbd>J</Kbd>
                  切换
                </span>
              </div>
              <FindingDetail
                key={selected.finding_id}
                finding={selected}
                projectId={pid}
                onReviewed={advance}
              />
            </div>
          ) : (
            <p className="m-0 rounded-lg border border-dashed border-border-strong p-10 text-center text-[13px] text-muted-foreground">
              从左侧选择一条问题。
            </p>
          )}
        </div>
      ) : null}
    </>
  );

  return (
    <>
      <PageHead
        title="问题"
        lede="逐条核实：成立的确认，不成立的驳回。处理完一条自动跳到下一条。"
        actions={
          project.state === 'ready_to_submit' ? (
            <Button asChild>
              <Link to={`${base}/submit`}>问题已处理完，去登记提交</Link>
            </Button>
          ) : undefined
        }
      />
      {pipeline.data ? <PipelineBanner pipeline={pipeline.data} /> : null}
      {pipeline.isPending ? <Loading /> : null}
      {pipeline.isError ? (
        <ErrorNotice error={pipeline.error} onRetry={() => void pipeline.refetch()} />
      ) : null}
      {pipeline.isSuccess && snapshotId === undefined ? (
        <EmptyState
          title="还没有完成的评审"
          action={
            <Button asChild>
              <Link to={base}>查看评审进度</Link>
            </Button>
          }
        >
          评审完成后，发现的问题会出现在这里。
        </EmptyState>
      ) : null}
      {snapshotId !== undefined ? (
        <Tabs
          tabs={tabs.map((t) => ({ ...t, panel: t.id === category ? list : null }))}
          active={category}
          onChange={(id) => {
            setParam('category', id, true);
          }}
          label="问题分类"
        />
      ) : null}
    </>
  );
}
