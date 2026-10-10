import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { isApiError } from '../../api/errors';
import type { Project, ProjectSettings, ProjectUpdate } from '../../api/types';
import { useToast } from '../../components/Toast';
import { ErrorNotice, Field, PageHead } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { formatDateTime, isoToLocalInput, localInputToIso } from '../../lib/format';
import { projectStateLabel } from '../../lib/labels';
import { useProjectContext } from '../../routes/ProjectLayout';
import { projectKeys, useRefetchProjectOnMount, useUpdateProject } from './queries';
import { validateProject, type Draft } from './ProjectsPage';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';

function toDraft(p: Project): Draft {
  return {
    title: p.title,
    tender_number: p.tender_number ?? '',
    lot: p.lot ?? '',
    region: p.region ?? '',
    engineering_type: p.engineering_type ?? '',
    deadline: isoToLocalInput(p.deadline),
  };
}

/** 只把用户改过且与当前值不同的字段放进 PATCH（后端按“出现的字段”更新）。 */
export function diffProject(base: Draft, edits: Partial<Draft>): ProjectUpdate {
  const out: ProjectUpdate = {};
  const eff = { ...base, ...edits };
  if (eff.title !== base.title) out.title = eff.title.trim();
  const opt = (v: string) => v.trim() || null;
  if (eff.tender_number !== base.tender_number) out.tender_number = opt(eff.tender_number);
  if (eff.lot !== base.lot) out.lot = opt(eff.lot);
  if (eff.region !== base.region) out.region = opt(eff.region);
  if (eff.engineering_type !== base.engineering_type)
    out.engineering_type = opt(eff.engineering_type);
  if (eff.deadline !== base.deadline) out.deadline = localInputToIso(eff.deadline);
  return out;
}

/** 项目设置：基本信息与功能开关。 */
export function SettingsPage() {
  const { project } = useProjectContext();
  useRefetchProjectOnMount(project.project_id);
  return (
    <>
      <PageHead title="项目设置" />
      <Card aria-labelledby="ps-h" className="mb-5">
        <CardHeader>
          <CardTitle id="ps-h">项目信息</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-[13px] text-muted-foreground">
            {projectStateLabel(project.state)} · 创建于 {formatDateTime(project.created_at)}
          </p>
          <EditForm project={project} />
        </CardContent>
      </Card>
      <FeaturesPanel project={project} />
    </>
  );
}

/** 开关外观：原生复选框（键盘、读屏都可靠），画成拨动开关。 */
const switchCls =
  'relative mt-0.5 !h-5 !w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-border-strong transition-colors duration-150 before:absolute before:top-0.5 before:left-0.5 before:size-4 before:rounded-full before:bg-white before:shadow-sm before:transition-transform before:duration-150 checked:bg-primary checked:before:translate-x-4 disabled:cursor-not-allowed disabled:opacity-50';

/** 功能开关的说明：只用需要的部分。废标／否决检测与证据溯源是核心，没有开关。 */
export const FEATURE_SWITCHES: { key: keyof ProjectSettings; label: string; detail: string }[] = [
  {
    key: 'auto_start',
    label: '资料齐了自动开始评审',
    detail: '关闭后资料照常解析，评审等你在报告页点“开始评审”，避免资料没传完就开始。',
  },
  {
    key: 'accept_rules_as_written',
    label: '规则按原文接受',
    detail:
      '开启后，未人工确认的废标／否决／强制类规则按模型提取的原文接受，不再阻止登记提交。把关强度降低，适合非常熟悉的标段。',
  },
  {
    key: 'consistency_check',
    label: '前后矛盾检测',
    detail: '同一个量在正文不同位置取值不同、大段重复。关闭后报告不出现这一类。',
  },
  {
    key: 'scope_check',
    label: '范围残留检测',
    detail: '正文出现招标文件里没有的工程对象，多为套用其他项目模板。关闭后报告不出现这一类。',
  },
  {
    key: 'show_score',
    label: '显示预测分数',
    detail: '关闭后报告只列可能的失分点，不显示分数估计与区间（预测照常进行）。',
  },
  {
    key: 'price',
    label: '报价模块',
    detail: '报价由其他部门负责时可以关闭，导航和报告里不再出现报价。',
  },
  {
    key: 'outcome_tracking',
    label: '提示登记开标结果',
    detail: '开标结果用来校准预测；关闭后提交后不再提示登记。',
  },
];

function FeaturesPanel({ project }: { project: Project }) {
  const toast = useToast();
  const [draft, setDraft] = useState<ProjectSettings>(project.settings);
  const changed = FEATURE_SWITCHES.filter((f) => draft[f.key] !== project.settings[f.key]);
  const update = useUpdateProject(project.project_id, (p) => {
    setDraft(p.settings);
    toast.notify('功能开关已保存');
  });
  return (
    <Card aria-labelledby="pf-h" className="mb-5">
      <CardHeader>
        <CardTitle id="pf-h">功能开关</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground">
          只用需要的部分。废标／否决检测与证据溯源是核心，没有开关；其余模块可以按项目关闭。
        </p>
        <ul className="m-0 my-3 list-none divide-y divide-border border-y border-border p-0">
          {FEATURE_SWITCHES.map((f) => (
            <li key={f.key} className="flex items-start justify-between gap-6 py-3.5">
              <span className="flex min-w-0 flex-col gap-0.5">
                <label htmlFor={`sw-${f.key}`} className="cursor-pointer text-[13px] font-medium">
                  {f.label}
                </label>
                <small id={`sw-${f.key}-d`} className="text-xs text-muted-foreground">
                  {f.detail}
                </small>
              </span>
              <input
                id={`sw-${f.key}`}
                type="checkbox"
                className={switchCls}
                aria-describedby={`sw-${f.key}-d`}
                checked={draft[f.key]}
                disabled={update.isPending}
                onChange={(e) => {
                  setDraft((d) => ({ ...d, [f.key]: e.target.checked }));
                }}
              />
            </li>
          ))}
        </ul>
        {update.isError ? <ErrorNotice error={update.error} title="功能开关未保存" /> : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            disabled={changed.length === 0 || update.isPending}
            onClick={() => {
              update.mutate({ revision: project.revision, body: { settings: draft } });
            }}
          >
            {update.isPending ? '正在保存…' : '保存开关'}
          </Button>
          <Button
            disabled={changed.length === 0 || update.isPending}
            onClick={() => {
              setDraft(project.settings);
              update.reset();
            }}
          >
            放弃修改
          </Button>
          <span className="m-0 text-xs text-muted-foreground">
            {changed.length
              ? `将修改：${changed.map((f) => f.label).join('、')}`
              : '开关没有改动。'}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function EditForm({ project }: { project: Project }) {
  const qc = useQueryClient();
  const toast = useToast();
  const base = toDraft(project);
  const [edits, setEdits] = useState<Partial<Draft>>({});
  const [touched, setTouched] = useState(false);
  const eff: Draft = { ...base, ...edits };
  const body = diffProject(base, edits);
  const changed = Object.keys(body).length > 0;
  const errs = touched ? validateProject(eff) : {};

  const update = useUpdateProject(project.project_id, () => {
    setEdits({});
    setTouched(false);
    toast.notify('项目信息已保存');
  });
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => {
    setEdits((x) => ({ ...x, [k]: e.target.value }));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!changed || Object.keys(validateProject(eff)).length > 0) return;
    update.mutate({ revision: project.revision, body });
  };
  const stale = isApiError(update.error) && update.error.kind === 'stale';

  return (
    <form onSubmit={submit} noValidate>
      <Field label="项目名称" error={errs.title}>
        {(p) => <Input {...p} value={eff.title} onChange={set('title')} />}
      </Field>
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="投标截止" error={errs.deadline} hint="清空后保存即取消截止时间">
          {(p) => (
            <Input {...p} type="datetime-local" value={eff.deadline} onChange={set('deadline')} />
          )}
        </Field>
        <Field label="标段">{(p) => <Input {...p} value={eff.lot} onChange={set('lot')} />}</Field>
        <Field label="招标编号">
          {(p) => <Input {...p} value={eff.tender_number} onChange={set('tender_number')} />}
        </Field>
        <Field label="地区">
          {(p) => <Input {...p} value={eff.region} onChange={set('region')} />}
        </Field>
        <Field label="工程类型">
          {(p) => <Input {...p} value={eff.engineering_type} onChange={set('engineering_type')} />}
        </Field>
      </div>
      {update.isError ? (
        <>
          <ErrorNotice error={update.error} title={stale ? '项目已被他人修改' : '项目信息未保存'} />
          {stale ? (
            <p>
              <Button
                onClick={() => {
                  update.reset();
                  void qc.invalidateQueries({ queryKey: projectKeys.detail(project.project_id) });
                }}
              >
                载入最新版本
              </Button>{' '}
              <span className="text-muted-foreground">
                未改动的字段会更新为最新值，你改过的字段保持不变，确认后再保存。
              </span>
            </p>
          ) : null}
        </>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          type="submit"
          disabled={update.isPending || !changed}
          aria-describedby="ps-tip"
        >
          {update.isPending ? '正在保存…' : '保存修改'}
        </Button>
        <Button
          disabled={!changed || update.isPending}
          onClick={() => {
            setEdits({});
            setTouched(false);
            update.reset();
          }}
        >
          放弃修改
        </Button>
        <span id="ps-tip" className="text-xs text-muted-foreground">
          {changed ? `将更新 ${String(Object.keys(body).length)} 个字段。` : '没有修改。'}
        </span>
      </div>
    </form>
  );
}
