import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../../api/endpoints';
import { isApiError } from '../../api/errors';
import type { Fact } from '../../api/types';
import { Dialog, DialogActions } from '../../components/Dialog';
import { useToast } from '../../components/Toast';
import { EmptyState, ErrorNotice, Field, Loading, Notice, Tag } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { confirmationLabel } from '../../lib/labels';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { EvidencePicker } from '../evidence/EvidencePicker';
import { useProjectContext } from '../../routes/ProjectLayout';
import { refreshFacts, useFacts } from './queries';
import { toFactRequest, validateFact, type FactDraft } from './validate';
import { Button } from '../../components/ui/button';
import { Input, Textarea } from '../../components/ui/input';

const EMPTY: FactDraft = {
  name: '',
  subject: '',
  scope: '',
  value: '',
  unit: '',
  statement: '',
  evidenceIds: '',
};

/** 依据页的“事实库”标签：人工录入并附证据的事实。 */
export function FactsPanel() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const facts = useFacts(pid);
  const [withdrawing, setWithdrawing] = useState<Fact | null>(null);

  return (
    <>
      <p className="text-muted-foreground">
        事实是评审和改稿建议可以引用的项目参数（例如项目经理资质、工期），每条都要附原文证据。录入后重新评审才会用上。
      </p>
      <Card aria-labelledby="fl-h" className="mb-5">
        <CardHeader>
          <CardTitle id="fl-h">当前事实</CardTitle>
        </CardHeader>
        <CardContent>
          {facts.isPending ? <Loading /> : null}
          {facts.isError ? (
            <ErrorNotice error={facts.error} onRetry={() => void facts.refetch()} />
          ) : null}
          {facts.isSuccess && facts.data.items.length === 0 ? (
            <EmptyState title="还没有录入事实">
              录入后，评审和改稿建议都可以用。每条事实要附原文证据。
            </EmptyState>
          ) : null}
          {facts.isSuccess && facts.data.items.length > 0 ? (
            <>
              <p className="text-muted-foreground">共 {facts.data.items.length} 条。</p>
              <div className="relative w-full overflow-x-auto">
                <table className="data-table stack-mobile" aria-label="当前事实">
                  <thead>
                    <tr>
                      <th scope="col">名称</th>
                      <th scope="col">主体</th>
                      <th scope="col">范围</th>
                      <th scope="col">数值</th>
                      <th scope="col">陈述</th>
                      <th scope="col">状态</th>
                      <th scope="col">证据</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {facts.data.items.map((f) => (
                      <FactRow
                        key={f.fact_id}
                        fact={f}
                        onWithdraw={() => {
                          setWithdrawing(f);
                        }}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
      {withdrawing ? (
        <WithdrawDialog
          projectId={pid}
          fact={withdrawing}
          onClose={() => {
            setWithdrawing(null);
          }}
        />
      ) : null}
      <Card aria-labelledby="fa-h" className="mb-5">
        <CardHeader>
          <CardTitle id="fa-h">录入事实</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="m-0 text-xs text-muted-foreground">录入后不能修改，录错了可以撤回再录。</p>
          <FactForm projectId={pid} />
        </CardContent>
      </Card>
    </>
  );
}

function FactRow({ fact: f, onWithdraw }: { fact: Fact; onWithdraw?: () => void }) {
  return (
    <tr>
      <th scope="row" className="font-medium">
        {f.name}
      </th>
      <td data-label="主体">{f.subject}</td>
      <td data-label="范围">{f.scope}</td>
      <td data-label="数值" className="tabular">
        {f.value_decimal ? `${f.value_decimal}${f.unit ? ` ${f.unit}` : ''}` : '—'}
      </td>
      <td data-label="陈述">{f.statement}</td>
      <td data-label="状态">
        <Tag tone={f.confirmation === 'confirmed' ? 'neutral' : 'gray'}>
          {confirmationLabel(f.confirmation)}
        </Tag>
      </td>
      <td data-label="证据">{f.evidence_ids.length} 处</td>
      {onWithdraw ? (
        <td>
          <Button size="sm" onClick={onWithdraw}>
            撤回
          </Button>
        </td>
      ) : null}
    </tr>
  );
}

function FactForm({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [d, setD] = useState<FactDraft>(EMPTY);
  const [touched, setTouched] = useState(false);
  const errs = validateFact(d);
  const set = (k: keyof FactDraft, v: string) => {
    setD((x) => ({ ...x, [k]: v }));
  };
  const add = useIdempotentAction(
    (b: ReturnType<typeof toFactRequest>, o) => api.facts.add(projectId, b, o),
    {
      onSuccess: async () => {
        await refreshFacts(qc, projectId);
        setD(EMPTY);
        setTouched(false);
        toast.notify('已录入事实');
      },
    },
  );
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(errs).length > 0) return;
    add.mutate(toFactRequest(d));
  };
  const text = (k: keyof FactDraft, label: string, hint?: string) => (
    <Field label={label} error={touched ? (errs[k] ?? null) : null} hint={hint}>
      {(p) => (
        <Input
          {...p}
          value={d[k]}
          onChange={(e) => {
            set(k, e.target.value);
          }}
        />
      )}
    </Field>
  );
  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="grid gap-x-4 sm:grid-cols-2">
        {text('name', '事实名称', '例如：总工期')}
        {text('subject', '主体', '例如：本公司、项目经理')}
        {text('scope', '适用范围', '例如：一标段')}
        {text('value', '数值（选填）', '十进制数，例如 180')}
        {text('unit', '单位（选填）', '例如：日历天')}
      </div>
      <Field label="事实陈述" error={touched ? (errs.statement ?? null) : null}>
        {(p) => (
          <Textarea
            {...p}
            rows={3}
            value={d.statement}
            onChange={(e) => {
              set('statement', e.target.value);
            }}
          />
        )}
      </Field>
      <EvidencePicker
        projectId={projectId}
        value={d.evidenceIds}
        onChange={(v) => {
          set('evidenceIds', v);
        }}
      />
      <Field
        label="证据 ID"
        error={touched ? (errs.evidenceIds ?? null) : null}
        hint="至少一个。上方检索勾选后会自动填入；也可直接填写，多个用逗号或空格分隔。"
      >
        {(p) => (
          <Textarea
            {...p}
            rows={2}
            value={d.evidenceIds}
            onChange={(e) => {
              set('evidenceIds', e.target.value);
            }}
          />
        )}
      </Field>
      {add.isError ? <ErrorNotice error={add.error} title="事实未录入" /> : null}
      <Button variant="primary" type="submit" disabled={add.isPending}>
        {add.isPending ? '正在录入…' : '录入事实'}
      </Button>
    </form>
  );
}

const NOT_CURRENT_TEXT = '该事实已不在当前事实集，已刷新';

function WithdrawDialog({
  projectId,
  fact,
  onClose,
}: {
  projectId: string;
  fact: Fact;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  // 撤回会生成新事实集、条目 ID 全部更换：刷新事实查询，不使用旧 ID。
  const refresh = () => refreshFacts(qc, projectId);
  const m = useIdempotentAction(
    (v: { reason: string }, o) => api.facts.withdraw(projectId, fact.fact_id, v, o),
    {
      onSuccess: async () => {
        await refresh();
        toast.notify('已撤回事实');
        onClose();
      },
      onError: (e) => {
        if (isApiError(e) && e.kind === 'conflict' && e.is('fact_not_current')) void refresh();
      },
    },
  );
  const notCurrent = isApiError(m.error) && m.error.is('fact_not_current');
  const err = touched && !reason.trim() ? '请填写撤回理由' : null;
  return (
    <Dialog title="撤回事实" onClose={onClose}>
      <p className="m-0 mb-3 border-l-2 border-border-strong bg-subtle px-3 py-2 text-sm">
        {fact.name}：{fact.statement}
      </p>
      <Notice tone="plain">
        撤回会生成新的事实集，之后的评审不再包含这条事实；已完成的评审不受影响。
      </Notice>
      <Field label="撤回理由" error={err}>
        {(p) => (
          <Textarea
            {...p}
            rows={3}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-autofocus
          />
        )}
      </Field>
      {m.isError ? (
        notCurrent ? (
          <div
            className="mb-4 rounded-lg border border-danger-border bg-danger-soft px-4 py-3 text-[13px] text-danger-foreground"
            role="alert"
          >
            <strong>事实未撤回</strong>
            <p>{NOT_CURRENT_TEXT}</p>
          </div>
        ) : (
          <ErrorNotice error={m.error} title="事实未撤回" />
        )
      ) : null}
      <DialogActions>
        <Button onClick={onClose}>{notCurrent ? '关闭' : '取消'}</Button>
        <Button
          variant="primary"
          disabled={m.isPending || notCurrent}
          onClick={() => {
            setTouched(true);
            if (reason.trim()) m.mutate({ reason: reason.trim() });
          }}
        >
          {m.isPending ? '正在撤回…' : '确认撤回'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
