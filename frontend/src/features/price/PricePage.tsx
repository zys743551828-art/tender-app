import { useMemo, useState } from 'react';
import type { PricePlan, PricePoint, PriceRuleTerm, PriceSimulation } from '../../api/types';
import { Link } from 'react-router-dom';
import { EmptyState, Field, ErrorNotice, Loading, PageHead, Stat, Tag } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { formatDateTime } from '../../lib/format';
import { benchmarkMethodLabel, priceFlagLabel } from '../../lib/labels';
import { cn } from '../../lib/cn';
import { Icon } from '../../components/Icon';
import { useProjectContext } from '../../routes/ProjectLayout';
import { useRuleSet } from '../rules/queries';
import { PriceCurve } from './PriceCurve';
import { useDebounced, usePrice, usePriceHistory, useSavePrice, useSimulation } from './queries';
import {
  EMPTY_DRAFT,
  MAX_CANDIDATES,
  MAX_COMPETITORS,
  MAX_NOTE,
  PRICE_TEMPLATES,
  draftFromPlan,
  draftFromTerm,
  splitPrices,
  toRequest,
  validateDraft,
  type PriceDraft,
} from './validate';
import type { BenchmarkMethod } from '../../api/types';
import { Button, textLink } from '../../components/ui/button';
import { Input, Select, Textarea } from '../../components/ui/input';

/** 换算句：高于基准价 1% 失去几个价格分，即 1 个分约相当于多少 % 的报价。 */
export function exchangeSentence(s: PriceSimulation): string {
  const r = s.exchange_rate;
  if (r.pct_per_point_above === null) return '高于基准价不扣分，无法把 1 个技术分换算成报价。';
  return `报价高于基准价 1% 约失去 ${r.points_per_pct_above} 个价格分，即 1 个技术分约相当于 ${r.pct_per_point_above}% 的报价。`;
}

const METHODS: BenchmarkMethod[] = ['fixed', 'average', 'trimmed_average'];

/**
 * 报价：评标价规则、竞争对手报价估计与候选报价；右侧实时试算（不保存）。
 * 招标文件写明了评标价办法时，第一次打开就按原文填好规则，只需要填报价。
 */
export function PricePage() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const plan = usePrice(pid);
  const rules = useRuleSet(pid);
  if (!project.settings.price) {
    return (
      <>
        <PageHead title="报价" />
        <EmptyState
          title="本项目关闭了报价模块"
          action={
            <Button asChild>
              <Link to={`/projects/${pid}/settings`}>去项目设置</Link>
            </Button>
          }
        >
          报价由其他部门负责时可以关闭；需要时在项目设置的功能开关里重新打开。
        </EmptyState>
      </>
    );
  }
  if (plan.isPending || rules.isPending) return <Loading />;
  if (plan.isError)
    return (
      <ErrorNotice
        error={plan.error}
        onRetry={() => void plan.refetch()}
        title="报价方案无法读取"
      />
    );
  const term = rules.data?.terms.price_rule ?? null;
  return (
    <>
      <PageHead title="报价" lede="试算不同报价的价格分，看 1 个技术分值多少报价。" />
      <PriceWorkspace
        key={plan.data?.plan.plan_id ?? 'none'}
        projectId={pid}
        term={term}
        initial={
          plan.data
            ? draftFromPlan(plan.data.plan)
            : term
              ? draftFromTerm(EMPTY_DRAFT, term)
              : EMPTY_DRAFT
        }
        prefilled={!plan.data && term !== null}
        savedAt={plan.data?.plan.created_at ?? null}
      />
    </>
  );
}

function PriceWorkspace({
  projectId,
  term,
  initial,
  prefilled,
  savedAt,
}: {
  projectId: string;
  term: PriceRuleTerm | null;
  initial: PriceDraft;
  prefilled: boolean;
  savedAt: string | null;
}) {
  const [d, setD] = useState<PriceDraft>(initial);
  const [touched, setTouched] = useState(false);
  const errs = validateDraft(d);
  const shownErrs = touched ? errs : {};
  const request = useMemo(() => toRequest(d), [d]);
  const debounced = useDebounced(request, 400);
  const sim = useSimulation(projectId, debounced);
  const save = useSavePrice(projectId);
  const set = <K extends keyof PriceDraft>(k: K, v: PriceDraft[K]) => {
    setTouched(true);
    setD((x) => ({ ...x, [k]: v }));
  };
  const text = (k: keyof PriceDraft) => (e: { target: { value: string } }) => {
    set(k, e.target.value as never);
  };

  const onSave = () => {
    setTouched(true);
    if (request) save.mutate(request);
  };

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <div>
        <form
          className="mb-5 rounded-lg border border-border bg-card p-5"
          aria-labelledby="pr-h"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            onSave();
          }}
        >
          <h2 id="pr-h" className="m-0 mb-3 text-[15px] font-semibold tracking-tight">
            评标价规则
          </h2>
          {term ? (
            <TermSource
              term={term}
              projectId={projectId}
              prefilled={prefilled}
              onApply={() => {
                setTouched(true);
                setD((x) => draftFromTerm(x, term));
              }}
            />
          ) : (
            <p className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px]">
              <span className="text-muted-foreground">
                招标文件里没有找到评标价办法，可以从常见办法开始：
              </span>
              {PRICE_TEMPLATES.map((t) => (
                <button
                  key={t.label}
                  type="button"
                  className={textLink}
                  onClick={() => {
                    setD((x) => ({ ...x, ...t.apply }));
                  }}
                >
                  {t.label}
                </button>
              ))}
            </p>
          )}
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="价格分满分" error={shownErrs.fullScore}>
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={d.fullScore}
                  onChange={text('fullScore')}
                />
              )}
            </Field>
            <Field label="高于基准价每 1% 扣分" error={shownErrs.aboveDeduct} hint="不扣分填 0">
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={d.aboveDeduct}
                  onChange={text('aboveDeduct')}
                />
              )}
            </Field>
            <Field label="低于基准价每 1% 扣分" error={shownErrs.belowDeduct} hint="不扣分填 0">
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={d.belowDeduct}
                  onChange={text('belowDeduct')}
                />
              )}
            </Field>
            <Field label="最高投标限价（选填）" error={shownErrs.maxLimit} hint="超过将被否决">
              {(p) => (
                <Input {...p} inputMode="decimal" value={d.maxLimit} onChange={text('maxLimit')} />
              )}
            </Field>
            <Field
              label="异常低价线 %（选填）"
              error={shownErrs.abnormalLowPct}
              hint="低于基准价该百分比视为异常低价风险"
            >
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={d.abnormalLowPct}
                  onChange={text('abnormalLowPct')}
                />
              )}
            </Field>
          </div>

          <h3 className="m-0 mt-2 mb-3 border-t border-border pt-5 text-sm font-semibold">
            基准价取法
          </h3>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="取法">
              {(p) => (
                <Select
                  {...p}
                  value={d.method}
                  onChange={(e) => {
                    set('method', e.target.value as BenchmarkMethod);
                  }}
                >
                  {METHODS.map((m) => (
                    <option key={m} value={m}>
                      {benchmarkMethodLabel(m)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {d.method === 'fixed' ? (
              <Field label="固定基准价" error={shownErrs.fixedValue}>
                {(p) => (
                  <Input
                    {...p}
                    inputMode="decimal"
                    value={d.fixedValue}
                    onChange={text('fixedValue')}
                  />
                )}
              </Field>
            ) : null}
            <Field label="系数" error={shownErrs.coefficient} hint="基准价再乘以该系数，没有填 1">
              {(p) => (
                <Input
                  {...p}
                  inputMode="decimal"
                  value={d.coefficient}
                  onChange={text('coefficient')}
                />
              )}
            </Field>
            {d.method === 'trimmed_average' ? (
              <Field
                label="去极值比例 %"
                error={shownErrs.trimPct}
                hint="各去掉该比例的最高与最低报价"
              >
                {(p) => (
                  <Input {...p} inputMode="decimal" value={d.trimPct} onChange={text('trimPct')} />
                )}
              </Field>
            ) : null}
          </div>
          {d.method !== 'fixed' ? (
            <label className="mb-4 flex items-center gap-2 text-[13px] [&_input]:size-4 [&_input]:accent-primary">
              <input
                type="checkbox"
                checked={d.includeOwn}
                onChange={(e) => {
                  set('includeOwn', e.target.checked);
                }}
              />
              把己方报价计入平均
            </label>
          ) : null}
          {d.method !== 'fixed' ? (
            <p className="m-0 text-xs text-muted-foreground">
              基准价取决于其他投标人的报价，下面填的只是估计，实际以开标为准。
            </p>
          ) : null}

          <h3 className="m-0 mt-6 mb-3 border-t border-border pt-5 text-sm font-semibold">报价</h3>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field
              label={`竞争对手报价估计（最多 ${String(MAX_COMPETITORS)} 个）`}
              error={shownErrs.competitors}
              hint={`每行一个，也可以直接粘贴一列；现有 ${String(splitPrices(d.competitors).length)} 个`}
            >
              {(p) => (
                <Textarea {...p} rows={6} value={d.competitors} onChange={text('competitors')} />
              )}
            </Field>
            <Field
              label={`候选报价（最多 ${String(MAX_CANDIDATES)} 个）`}
              error={shownErrs.candidates}
              hint={`每行一个；现有 ${String(splitPrices(d.candidates).length)} 个`}
            >
              {(p) => (
                <Textarea {...p} rows={6} value={d.candidates} onChange={text('candidates')} />
              )}
            </Field>
          </div>
          <Field
            label="备注（选填）"
            error={shownErrs.note}
            hint={`最多 ${String(MAX_NOTE)} 字，随这个版本保存`}
          >
            {(p) => <Input {...p} value={d.note} onChange={text('note')} />}
          </Field>
          {save.isError ? <ErrorNotice error={save.error} title="没有保存" /> : null}
          {save.isSuccess ? (
            <p className="m-0 text-xs text-muted-foreground" role="status">
              已保存。
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" type="submit" disabled={save.isPending}>
              {save.isPending ? '正在保存…' : '保存方案'}
            </Button>
            {savedAt ? (
              <small className="text-muted-foreground">上次保存于 {formatDateTime(savedAt)}</small>
            ) : null}
          </div>
        </form>
        <History
          projectId={projectId}
          onLoad={(p) => {
            setTouched(true);
            setD(draftFromPlan(p));
          }}
        />
      </div>

      <SimulationPanel
        ready={request !== null}
        loading={sim.isFetching}
        error={sim.error}
        data={sim.data ?? null}
        fullScore={d.fullScore}
      />
    </div>
  );
}

/** 评标价规则的原文出处：首次打开时已据此填好；改乱了可以重新填入。 */
function TermSource({
  term,
  projectId,
  prefilled,
  onApply,
}: {
  term: PriceRuleTerm;
  projectId: string;
  prefilled: boolean;
  onApply: () => void;
}) {
  const ev = term.evidence[0];
  return (
    <div className="mb-5 rounded-md border border-border bg-subtle p-3 text-[13px]">
      <p className="m-0 mb-2 flex items-center gap-1.5 font-medium">
        <Icon name="FileCheck2" className="text-primary" />
        {prefilled ? '已按招标文件填好评标价规则，请核对：' : '招标文件写明的评标价规则：'}
      </p>
      <blockquote className="m-0 border-l-2 border-highlight-border bg-card px-3 py-2 leading-relaxed">
        {term.quote}{' '}
        {ev ? (
          <Link
            className={cn(textLink, 'font-sans text-xs whitespace-nowrap')}
            to={`/projects/${projectId}/evidence/${ev.evidence_id}`}
          >
            第 {ev.physical_page} 页
          </Link>
        ) : null}
      </blockquote>
      <button type="button" className={cn(textLink, 'mt-2 text-xs')} onClick={onApply}>
        按招标文件重新填入
      </button>
    </div>
  );
}

function History({ projectId, onLoad }: { projectId: string; onLoad: (p: PricePlan) => void }) {
  const q = usePriceHistory(projectId);
  return (
    <Card aria-labelledby="ph-h" className="mb-5">
      <CardHeader>
        <CardTitle id="ph-h">保存过的方案</CardTitle>
      </CardHeader>
      <CardContent>
        {q.isPending ? <Loading /> : null}
        {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
        {q.isSuccess && q.data.length === 0 ? (
          <p className="text-muted-foreground">还没有保存过。</p>
        ) : null}
        {q.isSuccess && q.data.length > 0 ? (
          <ul className="m-0 list-none divide-y divide-border p-0 [&>li]:py-2.5">
            {q.data.map((p, i) => (
              <li key={p.plan_id} className="flex items-center justify-between gap-3">
                <div className="min-w-0 text-[13px]">
                  <strong className="font-medium tabular">{formatDateTime(p.created_at)}</strong>{' '}
                  {i === 0 ? <Tag tone="green">当前</Tag> : null}
                  <small className="block text-xs text-muted-foreground">
                    候选报价 {p.candidate_prices.length} 个 · 竞争对手估计{' '}
                    {p.competitor_prices.length} 个 ·{' '}
                    {benchmarkMethodLabel(p.params.benchmark.method)}
                    {p.note ? ` · ${p.note}` : ''}
                  </small>
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    onLoad(p);
                  }}
                >
                  载入
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

function flagsText(p: PricePoint): string {
  return p.flags.length === 0 ? '无' : p.flags.map(priceFlagLabel).join('；');
}

function SimulationPanel({
  ready,
  loading,
  error,
  data,
  fullScore,
}: {
  ready: boolean;
  loading: boolean;
  error: unknown;
  data: PriceSimulation | null;
  fullScore: string;
}) {
  return (
    <section
      className="rounded-lg border border-border bg-card p-5 xl:sticky xl:top-6"
      aria-labelledby="sim-h"
      aria-live="polite"
    >
      <h2 id="sim-h" className="mb-3 text-[15px] font-semibold">
        试算结果
      </h2>
      {error ? <ErrorNotice error={error} title="试算未完成" /> : null}
      {loading ? <p className="text-muted-foreground">正在试算…</p> : null}
      {ready && data ? (
        <>
          <dl className="m-0 mb-3 grid grid-cols-2 gap-4">
            <Stat label="评标基准价" value={data.benchmark ?? '无法计算'} />
            <Stat
              label="最优候选"
              value={data.best ? data.best.price : '无'}
              sub={data.best ? `价格分 ${data.best.score}` : undefined}
            />
          </dl>
          <p className="m-0 mb-3 rounded-md bg-primary-soft px-3 py-2 text-[13px] font-medium text-primary-soft-foreground">
            {exchangeSentence(data)}
          </p>
          {data.notes.length > 0 ? (
            <ul className="my-1.5 list-disc pl-5 text-xs text-muted-foreground">
              {data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          {data.candidates.length === 0 ? (
            <p className="text-muted-foreground">还没有可计算的候选报价。</p>
          ) : (
            <div className="relative w-full overflow-x-auto">
              <table className="data-table">
                <caption className="sr-only">候选报价的价格分</caption>
                <thead>
                  <tr>
                    <th scope="col">候选报价</th>
                    <th scope="col" className="text-right">
                      相对基准价
                    </th>
                    <th scope="col" className="text-right">
                      价格分
                    </th>
                    <th scope="col">风险提示</th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((c) => {
                    const best = data.best?.price === c.price;
                    return (
                      <tr key={c.price} className={c.flags.length > 0 ? 'row-alert' : undefined}>
                        <th scope="row" className="font-medium">
                          {c.price} {best ? <Tag tone="green">最优</Tag> : null}
                        </th>
                        <td className="text-right">{c.deviation_pct}%</td>
                        <td className="text-right font-medium">{c.score}</td>
                        <td>{flagsText(c)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {data.best ? (
            <p className="m-0 mt-3 text-[13px] text-muted-foreground">
              最优候选：<strong>{data.best.price}</strong>，价格分 {data.best.score}
              （不含触发风险提示的候选）。
            </p>
          ) : data.candidates.length > 0 ? (
            <p className="font-medium text-danger-foreground">
              没有可用的最优候选：所有候选都触发了风险提示。
            </p>
          ) : null}
          <PriceCurve
            curve={data.curve}
            candidates={data.candidates}
            benchmark={data.benchmark}
            fullScore={fullScore}
            best={data.best}
          />
        </>
      ) : null}
      {!ready ? (
        <p className="text-muted-foreground">填好评标价规则和至少一个候选报价，这里自动试算。</p>
      ) : null}
    </section>
  );
}
