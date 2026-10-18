import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { Report, Submission } from '../../api/types';
import { Tabs } from '../../components/Tabs';
import { useToast } from '../../components/Toast';
import { EmptyState, ErrorNotice, Field, Loading, Notice, PageHead } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { submissionErrorHint, submissionGateItems } from '../../lib/errorHints';
import { formatDateTime, isoToLocalInput, localInputToIso } from '../../lib/format';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { Icon } from '../../components/Icon';
import { cn } from '../../lib/cn';
import { useProjectContext } from '../../routes/ProjectLayout';
import { findingKeys, useSnapshot } from '../findings/queries';
import { fileKeys, useFiles, versionNumberOf } from '../materials/queries';
import { OutcomesSection } from '../outcomes/OutcomesPage';
import { submissionKeys, useSubmissions } from '../outcomes/queries';
import { invalidateProject } from '../projects/queries';
import { PipelineBanner } from '../report/PipelineBanner';
import { pipelineKey, reportKey, usePipeline, useReport } from '../report/queries';
import { snapshotKeys } from '../snapshots/queries';
import { Button, textLink } from '../../components/ui/button';
import { Input, Select } from '../../components/ui/input';

interface Check {
  key: string;
  ok: boolean;
  title: string;
  /** 没通过时的说明与去处理的入口。 */
  problem?: string;
  to?: string;
  cta?: string;
}

/** 登记提交前的三项检查，与后端登记门槛对应；最终仍以服务端判定为准。 */
export function gateChecks(
  report: Report | null,
  staleOrRunning: boolean,
  acceptRulesAsWritten = false,
): Check[] {
  // 服务端的下一步按当前有效规则及确认状态计算；响应矩阵保留评审时的依据状态。
  const unconfirmed = report?.next_actions.find((a) => a.key === 'confirm_rules')?.count ?? 0;
  const open = (c: string) => report?.categories.find((x) => x.category === c)?.open ?? 0;
  const critical = open('disqualification') + open('response');
  return [
    {
      key: 'fresh',
      ok: report !== null && !staleOrRunning,
      title: '评审基于最新的资料和规则',
      problem:
        report === null ? '还没有完成的评审。' : '评审还在进行，或资料、规则有更新，需要重新评审。',
      to: '',
      cta: '看报告',
    },
    {
      key: 'rules',
      ok: report !== null && (unconfirmed === 0 || acceptRulesAsWritten),
      title: acceptRulesAsWritten
        ? '废标／强制类规则按原文接受（项目设置）'
        : '废标／强制类规则已核对',
      problem: `还有 ${String(unconfirmed)} 条没有核对。`,
      to: 'basis',
      cta: '确认规则',
    },
    {
      key: 'critical',
      ok: report !== null && critical === 0,
      title: '可能导致否决的问题已处理',
      problem: `还有 ${String(critical)} 个没有处理。`,
      to: 'findings?priority=qualification',
      cta: '处理问题',
    },
  ];
}

/** 提交与结果：登记提交与开标结果登记同页两个标签。 */
export function SubmitPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') === 'outcomes' ? 'outcomes' : 'submit';
  return (
    <>
      <PageHead
        title="提交与结果"
        lede="登记实际提交的版本；开标后登记结果和得分，用来校准预测。"
      />
      <Tabs
        label="提交与结果"
        active={tab}
        onChange={(id) => {
          setSp(
            (prev) => {
              const n = new URLSearchParams(prev);
              if (id === 'outcomes') n.set('tab', 'outcomes');
              else n.delete('tab');
              return n;
            },
            { replace: true },
          );
        }}
        tabs={[
          { id: 'submit', label: '提交登记', panel: <SubmitTab /> },
          { id: 'outcomes', label: '开标结果', panel: <OutcomesTab /> },
        ]}
      />
    </>
  );
}

function OutcomesTab() {
  const { project } = useProjectContext();
  const submissions = useSubmissions(project.project_id);
  if (submissions.isPending) return <Loading />;
  if (submissions.isError)
    return <ErrorNotice error={submissions.error} onRetry={() => void submissions.refetch()} />;
  if (submissions.data.length === 0) {
    return (
      <EmptyState
        icon="Flag"
        title="还没有登记过实际提交"
        action={
          <Button asChild>
            <Link to={`/projects/${project.project_id}/submit`}>去登记提交</Link>
          </Button>
        }
      >
        先登记提交，开标后再来登记结果。
      </EmptyState>
    );
  }
  return <OutcomesSection />;
}

function SubmitTab() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const base = `/projects/${pid}`;
  const qc = useQueryClient();
  const toast = useToast();
  const files = useFiles(pid);
  const submissions = useSubmissions(pid);
  const pipeline = usePipeline(pid);
  const report = useReport(pid);
  const snapshotId = pipeline.data?.snapshot_id ?? '';
  const snapshot = useSnapshot(snapshotId);
  const [created, setCreated] = useState<Submission | null>(null);
  const [ack, setAck] = useState(false);
  const [submittedAt, setSubmittedAt] = useState(() => isoToLocalInput(new Date().toISOString()));
  const [receiptId, setReceiptId] = useState('');
  const [touched, setTouched] = useState(false);

  const submit = useIdempotentAction(
    (b: Parameters<typeof api.submissions.create>[1], o) => api.submissions.create(pid, b, o),
    {
      onSuccess: (s) => {
        setCreated(s);
        void qc.invalidateQueries({ queryKey: submissionKeys.list(pid) });
        void invalidateProject(qc, pid);
        toast.notify('已登记实际提交');
      },
      // 409（评审不是最新、规则未确认、关键问题未处理）：说明所依据的数据已变，重新读取。
      onError: () => {
        for (const queryKey of [
          snapshotKeys.list(pid),
          findingKeys.list(pid),
          pipelineKey(pid),
          reportKey(pid),
          fileKeys.list(pid),
        ]) {
          void qc.invalidateQueries({ queryKey });
        }
      },
    },
  );

  if (files.isPending || pipeline.isPending || report.isPending) return <Loading />;
  if (!files.data || !pipeline.data || report.isError) {
    return (
      <ErrorNotice error={files.error ?? pipeline.error ?? report.error} title="提交页无法打开" />
    );
  }
  const rep = report.data ?? null;
  const stale = pipeline.data.stage !== 'done' || pipeline.data.stale_reasons.length > 0;
  const checks = gateChecks(rep, stale, project.settings.accept_rules_as_written);
  const failed = checks.filter((c) => !c.ok);
  const ready = failed.length === 0;
  const bodyFile = snapshot.data
    ? files.data.find((f) => f.version_id === snapshot.data.body_version_id)
    : undefined;
  const openTotal = rep?.categories.reduce((n, c) => n + c.open, 0) ?? 0;
  const openQualification =
    (rep?.categories.find((c) => c.category === 'disqualification')?.open ?? 0) +
    (rep?.categories.find((c) => c.category === 'response')?.open ?? 0);
  const nonCritical = openTotal - openQualification;

  const errs = {
    at: !localInputToIso(submittedAt) ? '请填写实际提交时间' : null,
    ack: nonCritical > 0 && !ack ? '请先确认你已知晓这些未结案问题' : null,
  };
  const valid = Object.values(errs).every((e) => e === null);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    const at = localInputToIso(submittedAt);
    if (!valid || !at || !snapshot.data) return;
    const receipt = files.data.find((f) => f.artifact.artifact_id === receiptId);
    submit.mutate({
      body_version_id: snapshot.data.body_version_id,
      snapshot_id: snapshot.data.snapshot_id,
      submitted_at: at,
      receipt_artifact_id: receipt ? receipt.artifact.artifact_id : null,
    });
  };
  const gateItems = submissionGateItems(submit.error);

  return (
    <>
      <PipelineBanner pipeline={pipeline.data} />
      {created ? (
        <Notice tone="plain">
          已登记，提交于 {formatDateTime(created.submitted_at)}。{' '}
          <Link className={textLink} to={`${base}/submit?tab=outcomes`}>
            开标后登记结果
          </Link>
        </Notice>
      ) : null}
      <Card aria-labelledby="sub-h" className="mb-5">
        <CardHeader>
          <CardTitle id="sub-h">登记提交</CardTitle>
        </CardHeader>
        <CardContent>
          <ul
            className="m-0 mb-4 list-none divide-y divide-border overflow-hidden rounded-md border border-border p-0"
            aria-label="登记前的检查"
          >
            {checks.map((c) => (
              <li
                key={c.key}
                data-ok={c.ok}
                className={cn('flex items-center gap-3 px-3.5 py-3', !c.ok && 'bg-danger-soft/50')}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    'inline-flex size-5 shrink-0 items-center justify-center rounded-full',
                    c.ok
                      ? 'bg-success text-white dark:text-background'
                      : 'bg-danger text-white dark:text-background',
                  )}
                >
                  <Icon name={c.ok ? 'Check' : 'X'} size={12} strokeWidth={2.5} />
                </span>
                <span className="flex min-w-0 flex-1 flex-col text-[13px]">
                  <strong className="font-medium">{c.title}</strong>
                  <span className="sr-only">{c.ok ? '（通过）' : '（未通过）'}</span>
                  {!c.ok && c.problem ? (
                    <small className="text-xs text-danger-foreground">{c.problem}</small>
                  ) : null}
                </span>
                {!c.ok && c.to !== undefined ? (
                  <Button asChild size="sm">
                    <Link to={c.to ? `${base}/${c.to}` : base}>{c.cta}</Link>
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          {!ready ? (
            <p className="m-0 text-[13px] text-muted-foreground">
              上面 {failed.length} 项处理好后，就可以在这里登记。
            </p>
          ) : (
            <form onSubmit={onSubmit} noValidate>
              <div className="grid gap-x-4 sm:grid-cols-2">
                <Field label="提交的正文" hint="即最近一轮评审用的版本">
                  {(p) => (
                    <Input
                      {...p}
                      readOnly
                      value={
                        bodyFile
                          ? `${bodyFile.original_name}（第 ${String(versionNumberOf(files.data, bodyFile))} 版）`
                          : '读取中…'
                      }
                    />
                  )}
                </Field>
                <Field label="实际提交时间" error={touched ? errs.at : null}>
                  {(p) => (
                    <Input
                      {...p}
                      type="datetime-local"
                      value={submittedAt}
                      onChange={(e) => {
                        setSubmittedAt(e.target.value);
                      }}
                    />
                  )}
                </Field>
                <Field label="提交回执（选填）" hint="在“资料”里以“已提交文件”上传后可选">
                  {(p) => (
                    <Select
                      {...p}
                      value={receiptId}
                      onChange={(e) => {
                        setReceiptId(e.target.value);
                      }}
                    >
                      <option value="">没有回执</option>
                      {files.data
                        .filter((f) => f.role === 'submission')
                        .map((f) => (
                          <option key={f.version_id} value={f.artifact.artifact_id}>
                            {f.original_name}
                          </option>
                        ))}
                    </Select>
                  )}
                </Field>
              </div>
              {nonCritical > 0 ? (
                <label className="mb-4 flex items-center gap-2 text-[13px] [&_input]:size-4 [&_input]:accent-primary">
                  <input
                    type="checkbox"
                    checked={ack}
                    aria-invalid={touched && errs.ack ? true : undefined}
                    onChange={(e) => {
                      setAck(e.target.checked);
                    }}
                  />
                  还有 {nonCritical} 个影响得分的问题没处理，我知道登记提交不代表它们已解决
                </label>
              ) : null}
              {touched && errs.ack ? (
                <p className="m-0 text-xs font-medium text-danger-foreground">{errs.ack}</p>
              ) : null}
              {submit.isError ? (
                <>
                  <ErrorNotice
                    error={submit.error}
                    title="没有登记成功"
                    hint={submissionErrorHint(submit.error)}
                  />
                  {gateItems.length > 0 ? (
                    <ul className="my-1.5 list-disc pl-5" aria-label="未满足的提交条件">
                      {gateItems.map((g) => (
                        <li key={g}>{g}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
              <Button variant="primary" type="submit" disabled={submit.isPending}>
                {submit.isPending ? '正在登记…' : '登记提交'}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>

      <Card aria-labelledby="sl-h" className="mb-5">
        <CardHeader>
          <CardTitle id="sl-h">已登记的提交</CardTitle>
        </CardHeader>
        <CardContent>
          {submissions.isPending ? <Loading /> : null}
          {submissions.isError ? (
            <ErrorNotice error={submissions.error} onRetry={() => void submissions.refetch()} />
          ) : null}
          {submissions.isSuccess && submissions.data.length === 0 ? (
            <p className="text-muted-foreground">还没有登记过。</p>
          ) : null}
          {submissions.isSuccess && submissions.data.length > 0 ? (
            <div className="relative w-full overflow-x-auto">
              <table className="data-table stack-mobile">
                <caption className="sr-only">已登记的提交</caption>
                <thead>
                  <tr>
                    <th scope="col">提交时间</th>
                    <th scope="col">正文</th>
                    <th scope="col">回执</th>
                    <th scope="col">
                      <span className="sr-only">操作</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.data.map((x) => {
                    const body = files.data.find((f) => f.version_id === x.body_version_id);
                    return (
                      <tr key={x.submission_id}>
                        <th scope="row" className="min-w-[200px]">
                          {formatDateTime(x.submitted_at)}
                          {x.supersedes ? <small>更正了之前的一次登记</small> : null}
                        </th>
                        <td data-label="正文">
                          {body
                            ? `${body.original_name}（第 ${String(versionNumberOf(files.data, body))} 版）`
                            : '施组正文'}
                        </td>
                        <td data-label="回执">{x.receipt_artifact ? '已上传' : '无'}</td>
                        <td>
                          <Link
                            className={textLink}
                            to={`${base}/submit?tab=outcomes&submission=${x.submission_id}`}
                          >
                            登记结果
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </>
  );
}
