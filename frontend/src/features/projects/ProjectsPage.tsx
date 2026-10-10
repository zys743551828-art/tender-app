import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { ProjectCreate, ProjectOverview } from '../../api/types';
import { Dialog, DialogActions } from '../../components/Dialog';
import { EmptyState, ErrorNotice, Field, Loading, PageHead } from '../../components/ui';
import { deadlineText, localInputToIso } from '../../lib/format';
import { projectStateLabel } from '../../lib/labels';
import { actionLabel, actionPath, coverageText } from '../../lib/nextAction';
import { useCreateProject, useProjects } from './queries';
import { Icon } from '../../components/Icon';
import { Button, textLink } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { cn } from '../../lib/cn';

const CLOSED = new Set(['archived', 'cancelled', 'failed_tender']);

/** 进行中的项目按“有否决风险 → 截止早 → 新建晚”排在前面；已结束的放最后。 */
function order(a: ProjectOverview, b: ProjectOverview): number {
  const closed = Number(CLOSED.has(a.state)) - Number(CLOSED.has(b.state));
  if (closed !== 0) return closed;
  const risk = Number(b.summary.qualification_open > 0) - Number(a.summary.qualification_open > 0);
  if (risk !== 0) return risk;
  const da = a.deadline ? Date.parse(a.deadline) : Infinity;
  const db = b.deadline ? Date.parse(b.deadline) : Infinity;
  if (da !== db) return da - db;
  return b.created_at.localeCompare(a.created_at);
}

/**
 * 项目总览：每个项目一行，直接给出最要紧的三件事——有没有否决风险、预计技术分、下一步做什么。
 * 下一步与报告里的“下一步”同源（后端 summary.next_action），两处不会说法不一。
 */
export function ProjectsPage() {
  const q = useProjects();
  const [creating, setCreating] = useState(false);
  const projects = [...(q.data ?? [])].sort(order);
  const open = projects.filter((p) => !CLOSED.has(p.state));
  const risky = open.filter((p) => p.summary.qualification_open > 0).length;
  const create = (
    <Button
      variant="primary"
      onClick={() => {
        setCreating(true);
      }}
    >
      <Icon name="Plus" />
      新建项目
    </Button>
  );

  return (
    <>
      <PageHead
        title="项目"
        lede={
          q.isSuccess && projects.length > 0
            ? `${String(open.length)} 个进行中${risky > 0 ? `，${String(risky)} 个有未处理的否决风险` : ''}`
            : undefined
        }
        actions={create}
      />
      {q.isPending ? <Loading /> : null}
      {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
      {q.isSuccess && projects.length === 0 ? (
        <EmptyState
          title="建一个项目，上传招标文件和施组正文"
          icon="Building2"
          action={
            <Button
              onClick={() => {
                setCreating(true);
              }}
            >
              新建项目
            </Button>
          }
        >
          资料齐了自动评审：查出可能被否决的地方，估计技术分，列出最值得改的问题。
        </EmptyState>
      ) : null}
      {q.isSuccess && projects.length > 0 ? (
        <ul
          className="m-0 list-none divide-y divide-border overflow-hidden rounded-lg border border-border bg-card p-0"
          aria-label="项目清单"
        >
          {projects.map((p) => (
            <ProjectRow key={p.project_id} project={p} />
          ))}
        </ul>
      ) : null}
      {creating ? (
        <CreateProjectDialog
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}
    </>
  );
}

function meta(p: ProjectOverview): string {
  return [p.lot, p.round > 1 ? `第 ${String(p.round)} 轮` : null, p.region, p.engineering_type]
    .filter(Boolean)
    .join(' · ');
}

function RiskCell({ reviewed, open }: { reviewed: boolean; open: number }) {
  if (!reviewed) return <span className="text-muted-foreground">尚未评审</span>;
  if (open > 0)
    return (
      <span className="inline-flex items-center gap-1.5 font-medium text-danger-foreground">
        <span aria-hidden="true" className="size-1.5 rounded-full bg-danger" />
        {open} 个未处理
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-success-foreground">
      <Icon name="Check" size={14} />
      未发现
    </span>
  );
}

function ProjectRow({ project: p }: { project: ProjectOverview }) {
  const base = `/projects/${p.project_id}`;
  const dl = deadlineText(p.deadline);
  const s = p.summary;
  const pred = s.prediction;
  const scored = p.settings.show_score && pred?.status === 'candidate' && pred.low !== null;
  const coverage =
    pred && pred.validation_status !== 'validated_in_scope'
      ? coverageText(pred.maximum, pred.technical_full_score)
      : null;
  const closed = CLOSED.has(p.state);
  const info = meta(p);
  return (
    <li
      className={cn(
        'group grid grid-cols-1 items-center gap-x-8 gap-y-3 px-5 py-4 transition-colors hover:bg-subtle lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1.4fr)_minmax(220px,0.95fr)]',
        closed && 'text-muted-foreground',
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-sm font-medium">
          <Link to={base} className="text-inherit no-underline hover:underline">
            {p.title}
          </Link>
        </h2>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {info ? `${info} · ` : ''}
          <span className={cn(dl.urgent && !closed && 'font-medium text-danger-foreground')}>
            {p.deadline ? dl.text : '未设截止时间'}
          </span>
        </p>
      </div>
      <dl className="m-0 grid grid-cols-3 gap-4 text-[13px]">
        <div>
          <dt className="text-xs text-muted-foreground">否决风险</dt>
          <dd className="m-0 mt-0.5">
            <RiskCell reviewed={s.reviewed} open={s.qualification_open} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">预计技术分</dt>
          <dd className="m-0 mt-0.5 font-medium tabular">
            {scored ? (
              `${pred.low ?? ''}–${pred.high ?? ''}`
            ) : (
              <span className="font-normal text-muted-foreground">
                {s.reviewed ? '暂无' : '尚未评审'}
              </span>
            )}
            {coverage ? (
              <small className="block text-xs font-normal text-warning-foreground">
                {coverage}
              </small>
            ) : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">状态</dt>
          <dd className="m-0 mt-0.5">{projectStateLabel(p.state)}</dd>
        </div>
      </dl>
      <div className="flex items-center justify-between gap-3 lg:justify-end">
        {s.next_action && !closed ? (
          <>
            <span className="line-clamp-2 text-xs text-muted-foreground lg:text-right">
              {s.next_action.title}
            </span>
            <Button asChild size="sm">
              <Link to={actionPath(base, s.next_action)}>{actionLabel(s.next_action)}</Link>
            </Button>
          </>
        ) : (
          <Button asChild size="sm" variant="ghost">
            <Link to={base}>查看报告</Link>
          </Button>
        )}
      </div>
    </li>
  );
}

export interface Draft {
  title: string;
  tender_number: string;
  lot: string;
  region: string;
  engineering_type: string;
  deadline: string;
}
const EMPTY: Draft = {
  title: '',
  tender_number: '',
  lot: '',
  region: '',
  engineering_type: '',
  deadline: '',
};

/** 只有项目名称必填；其余信息可以建好后在“设置”里补。 */
export function validateProject(d: Draft): Partial<Record<keyof Draft, string>> {
  const e: Partial<Record<keyof Draft, string>> = {};
  if (!d.title.trim()) e.title = '请填写项目名称';
  if (d.deadline && localInputToIso(d.deadline) === null) e.deadline = '截止时间格式不正确';
  return e;
}

function CreateProjectDialog({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [d, setD] = useState<Draft>(EMPTY);
  const [touched, setTouched] = useState(false);
  const [more, setMore] = useState(false);
  const create = useCreateProject((p) => {
    onClose();
    nav(`/projects/${p.project_id}/materials`);
  });
  const errs = touched ? validateProject(d) : {};
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => {
    setD((x) => ({ ...x, [k]: e.target.value }));
  };
  const opt = (v: string) => v.trim() || null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(validateProject(d)).length > 0) return;
    const body: ProjectCreate = {
      title: d.title.trim(),
      tender_number: opt(d.tender_number),
      lot: opt(d.lot),
      region: opt(d.region),
      engineering_type: opt(d.engineering_type),
      deadline: localInputToIso(d.deadline),
    };
    create.mutate(body);
  };

  return (
    <Dialog title="新建项目" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <Field label="项目名称" error={errs.title}>
          {(p) => (
            <Input
              {...p}
              value={d.title}
              onChange={set('title')}
              placeholder="例如：城市支路及排水改造工程"
              data-autofocus
            />
          )}
        </Field>
        <Field label="投标截止（选填）" error={errs.deadline}>
          {(p) => (
            <Input {...p} type="datetime-local" value={d.deadline} onChange={set('deadline')} />
          )}
        </Field>
        {more ? (
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="标段（选填）">
              {(p) => <Input {...p} value={d.lot} onChange={set('lot')} />}
            </Field>
            <Field label="招标编号（选填）">
              {(p) => <Input {...p} value={d.tender_number} onChange={set('tender_number')} />}
            </Field>
            <Field label="地区（选填）">
              {(p) => <Input {...p} value={d.region} onChange={set('region')} />}
            </Field>
            <Field label="工程类型（选填）">
              {(p) => (
                <Input {...p} value={d.engineering_type} onChange={set('engineering_type')} />
              )}
            </Field>
          </div>
        ) : (
          <button
            type="button"
            className={textLink}
            onClick={() => {
              setMore(true);
            }}
          >
            填写标段、招标编号等更多信息
          </button>
        )}
        {create.isError ? <ErrorNotice error={create.error} title="项目没有建立" /> : null}
        <DialogActions>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" type="submit" disabled={create.isPending}>
            {create.isPending ? '正在建立…' : '建立并上传资料'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
