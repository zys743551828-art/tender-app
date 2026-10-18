import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { Outcome, OutcomeTarget, StageResult } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { useToast } from '../../components/Toast';
import { ErrorNotice, Field, Loading, Notice, Tag } from '../../components/ui';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { formatDateTime, localInputToIso } from '../../lib/format';
import {
  outcomeTargetLabel,
  sourceKindLabel,
  stageResultLabel,
  verificationLabel,
} from '../../lib/labels';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { useProjectContext } from '../../routes/ProjectLayout';
import { useFiles } from '../materials/queries';
import { invalidateProject } from '../projects/queries';
import { outcomeKeys, useOutcomes, useSubmissions } from './queries';
import { toOutcomeRequest, validateOutcome, type OutcomeDraft } from './validate';
import { Button, textLink } from '../../components/ui/button';
import { Input, Select, Textarea } from '../../components/ui/input';

const TARGETS: OutcomeTarget[] = ['technical_total', 'composite_total', 'no_score'];
const STAGES: StageResult[] = [
  'pending',
  'technical_shortlisted',
  'not_shortlisted',
  'rejected',
  'candidate',
  'awarded',
  'not_awarded',
  'cancelled',
  'failed_tender',
];

/** 结果登记与核实：放在“提交与结果”页下半部分，提交登记后在这里继续。 */
export function OutcomesSection() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const qc = useQueryClient();
  const toast = useToast();
  const [sp] = useSearchParams();
  const submissions = useSubmissions(pid);
  const outcomes = useOutcomes(pid);
  const files = useFiles(pid);
  const [verifying, setVerifying] = useState<Outcome | null>(null);
  const [identity, setIdentity] = useState(project);
  const [identityAck, setIdentityAck] = useState(false);
  const initialized = useRef(false);

  const [d, setD] = useState<OutcomeDraft>({
    submissionId: sp.get('submission') ?? '',
    sourceKind: 'user_reported',
    target: 'technical_total',
    value: '',
    maximum: '',
    aggregation: '',
    stageResult: 'pending',
    publishedAt: '',
    sourceArtifactId: '',
    sourcePage: '',
    sourceDescription: '',
    supersedes: '',
  });
  const [touched, setTouched] = useState(false);
  const replaced = new Set(
    (submissions.data ?? []).flatMap((s) => (s.supersedes ? [s.supersedes] : [])),
  );
  const currentSubmissions = (submissions.data ?? []).filter(
    (s) => !s.superseded && !replaced.has(s.submission_id),
  );
  useEffect(() => {
    if (initialized.current || !submissions.isSuccess) return;
    initialized.current = true;
    const selected = d.submissionId
      ? submissions.data.find((s) => s.submission_id === d.submissionId)
      : currentSubmissions.length === 1
        ? currentSubmissions[0]
        : undefined;
    if (selected)
      setD((draft) => ({
        ...draft,
        submissionId: draft.submissionId || selected.submission_id,
        maximum:
          draft.maximum ||
          (draft.target === 'technical_total' ? (selected.technical_maximum ?? '') : ''),
      }));
  }, [submissions.isSuccess, submissions.data, currentSubmissions, d.submissionId]);
  const submissionValue = d.submissionId;
  const selectedSubmission = (submissions.data ?? []).find(
    (s) => s.submission_id === submissionValue,
  );
  const identityStale = identity.revision !== project.revision;
  const identityDiffers =
    !!selectedSubmission &&
    (selectedSubmission.project_title !== identity.title ||
      selectedSubmission.lot !== identity.lot ||
      selectedSubmission.round !== identity.round);
  const submissionStale =
    !!selectedSubmission &&
    (selectedSubmission.superseded === true || replaced.has(selectedSubmission.submission_id));
  const errs = touched ? validateOutcome({ ...d, submissionId: submissionValue }) : {};
  const set = <K extends keyof OutcomeDraft>(k: K, v: OutcomeDraft[K]) => {
    setD((x) => ({ ...x, [k]: v }));
  };
  // 后端只接受“官方结果”用途的资料作为来源（source_artifact_invalid），所以只列这一类。
  const evidenceFiles = (files.data ?? []).filter((f) => f.role === 'official_result');
  // 已被后来的记录取代（更正或核实）的结果：只作历史保留。
  const supersededIds = new Set(
    (outcomes.data ?? []).flatMap((o) => (o.supersedes ? [o.supersedes] : [])),
  );
  // 更正只能指向同一次提交下、且尚未被取代的记录（已被取代的只作历史保留，后端会拒绝再次更正）。
  const sameSubmission = (outcomes.data ?? []).filter(
    (o) => o.submission_id === submissionValue && !supersededIds.has(o.outcome_id),
  );

  const create = useIdempotentAction(
    (b: Parameters<typeof api.outcomes.create>[1], o) => api.outcomes.create(pid, b, o),
    {
      onSuccess: () => {
        void qc.invalidateQueries({ queryKey: outcomeKeys.list(pid) });
        void invalidateProject(qc, pid);
        toast.notify('结果已登记');
        setTouched(false);
        setD((x) => ({
          ...x,
          value: '',
          maximum: '',
          aggregation: '',
          sourceDescription: '',
          supersedes: '',
          sourcePage: '',
          sourceArtifactId: '',
        }));
      },
    },
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    const draft = { ...d, submissionId: submissionValue };
    if (
      Object.keys(validateOutcome(draft)).length > 0 ||
      identityStale ||
      submissionStale ||
      (identityDiffers && !identityAck)
    )
      return;
    create.mutate({
      ...toOutcomeRequest(draft, localInputToIso),
      expected_project_revision: identity.revision,
      acknowledge_identity_difference: identityAck,
    });
  };

  const scored = d.target !== 'no_score';
  return (
    <div id="outcomes">
      <Card aria-labelledby="oc-h" className="mb-5">
        <CardHeader>
          <CardTitle id="oc-h">登记结果</CardTitle>
        </CardHeader>
        <CardContent>
          <Notice tone="plain">
            报送结果与官方核验分开保存；迟到或更正会生成新记录，历史记录始终可查。
          </Notice>
          <div className="my-3 rounded-md bg-muted p-3 text-[13px]" aria-label="成绩登记身份">
            <p>
              {identity.title} · {identity.lot ?? '未填标段'} · 第 {identity.round} 轮
            </p>
            {selectedSubmission ? (
              <>
                <p>
                  提交时身份：{selectedSubmission.project_title ?? '未留存项目名称'} ·{' '}
                  {selectedSubmission.lot ?? '未填标段'} ·{' '}
                  {selectedSubmission.round == null
                    ? '轮次未知'
                    : `第 ${selectedSubmission.round} 轮`}
                </p>
                <p>
                  实际提交稿：{selectedSubmission.body_name ?? selectedSubmission.body_version_id} ·{' '}
                  {formatDateTime(selectedSubmission.submitted_at)}
                </p>
                <p className="break-all">
                  正文 {selectedSubmission.body_version_id} · 评审输入{' '}
                  {selectedSubmission.snapshot_id}
                </p>
                {selectedSubmission.body_sha256 ? (
                  <p className="break-all text-xs text-muted-foreground">
                    SHA-256 {selectedSubmission.body_sha256}
                  </p>
                ) : null}
              </>
            ) : (
              <p>请选择对应的实际提交；多份提交不会自动猜测。</p>
            )}
            {identityStale ? (
              <>
                <p role="alert">项目身份或状态已更新，请核对后重新载入。</p>
                <Button
                  size="sm"
                  onClick={() => {
                    setIdentity(project);
                    setIdentityAck(false);
                  }}
                >
                  重新载入登记身份
                </Button>
              </>
            ) : null}
            {submissionStale ? (
              <p role="alert">此提交已被更正，请选择更正后的实际提交；不会自动切换稿件。</p>
            ) : null}
            {identityDiffers ? (
              <label className="mt-2 flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={identityAck}
                  onChange={(e) => setIdentityAck(e.target.checked)}
                />
                当前项目身份与提交时不同或未留存；我已核对原件，此成绩对应上方实际提交稿
              </label>
            ) : null}
          </div>
          <form onSubmit={submit} noValidate>
            <div className="grid gap-x-4 sm:grid-cols-2">
              <Field label="关联的实际提交" error={errs.submissionId} hint="选择这份结果对应的提交">
                {(p) => (
                  <Select
                    {...p}
                    value={submissionValue}
                    onChange={(e) => {
                      // 换了提交，之前选的“更正的原记录”可能属于另一次提交，必须清掉。
                      const selected = submissions.data?.find(
                        (s) => s.submission_id === e.target.value,
                      );
                      setIdentityAck(false);
                      setD((x) => ({
                        ...x,
                        submissionId: e.target.value,
                        supersedes: '',
                        value: '',
                        maximum:
                          x.target === 'technical_total' ? (selected?.technical_maximum ?? '') : '',
                        scoreUnknown: false,
                      }));
                    }}
                  >
                    <option value="">
                      {currentSubmissions.length ? '请选择实际提交' : '没有可登记的当前提交'}
                    </option>
                    {(submissions.data ?? []).map((x) => (
                      <option key={x.submission_id} value={x.submission_id}>
                        {x.body_name ?? '正文'} · 提交于 {formatDateTime(x.submitted_at)}
                        {x.superseded || replaced.has(x.submission_id) ? '（已更正）' : ''}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field
                label="结果来源类型"
                hint={
                  d.sourceKind === 'user_reported'
                    ? '报送结果需以官方来源重新登记：自行报送的结果不能直接核实，拿到成绩公示等原件后再登记一条“官方”结果'
                    : '官方结果请选择来源资料并填写页码，之后才能核实'
                }
              >
                {(p) => (
                  <Select
                    {...p}
                    value={d.sourceKind}
                    onChange={(e) => {
                      set('sourceKind', e.target.value as OutcomeDraft['sourceKind']);
                    }}
                  >
                    <option value="user_reported">{sourceKindLabel('user_reported')}</option>
                    <option value="official">{sourceKindLabel('official')}</option>
                  </Select>
                )}
              </Field>
              <Field label="成绩类型">
                {(p) => (
                  <Select
                    {...p}
                    value={d.target}
                    onChange={(e) => {
                      const target = e.target.value as OutcomeTarget;
                      setD((x) => ({
                        ...x,
                        target,
                        value: '',
                        maximum:
                          target === 'technical_total'
                            ? (selectedSubmission?.technical_maximum ?? '')
                            : '',
                        scoreUnknown: false,
                      }));
                    }}
                  >
                    {TARGETS.map((t) => (
                      <option key={t} value={t}>
                        {outcomeTargetLabel(t)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {scored ? (
                <label className="my-2 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!!d.scoreUnknown}
                    onChange={(e) =>
                      setD((x) => ({ ...x, scoreUnknown: e.target.checked, value: '' }))
                    }
                  />
                  分值未知，先保存待核验记录
                </label>
              ) : null}
              <Field label="阶段结果" error={errs.stageResult}>
                {(p) => (
                  <Select
                    {...p}
                    value={d.stageResult}
                    onChange={(e) => {
                      set('stageResult', e.target.value as StageResult);
                    }}
                  >
                    {STAGES.map((t) => (
                      <option key={t} value={t}>
                        {stageResultLabel(t)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field
                label="分值"
                error={errs.value}
                hint={scored ? '未公布可勾选「分值未知」；仅阶段结果可选无分值' : '无分值类型不填'}
              >
                {(p) => (
                  <Input
                    {...p}
                    inputMode="decimal"
                    disabled={!scored || !!d.scoreUnknown}
                    value={d.value}
                    onChange={(e) => {
                      set('value', e.target.value);
                    }}
                  />
                )}
              </Field>
              <Field
                label="满分"
                error={errs.maximum}
                hint={
                  scored
                    ? selectedSubmission?.technical_maximum && d.target === 'technical_total'
                      ? '预填本次提交评审的满分候选；请按官方量尺核对，可修改'
                      : '满分未知可在勾选「分值未知」后留空'
                    : '无分值类型不填'
                }
              >
                {(p) => (
                  <Input
                    {...p}
                    inputMode="decimal"
                    disabled={!scored}
                    value={d.maximum}
                    onChange={(e) => {
                      set('maximum', e.target.value);
                    }}
                  />
                )}
              </Field>
              <Field label="聚合方式（选填）" hint="例如评委平均、去掉最高最低后平均">
                {(p) => (
                  <Input
                    {...p}
                    value={d.aggregation}
                    onChange={(e) => {
                      set('aggregation', e.target.value);
                    }}
                  />
                )}
              </Field>
              <Field label="公布时间（选填）">
                {(p) => (
                  <Input
                    {...p}
                    type="datetime-local"
                    value={d.publishedAt}
                    onChange={(e) => {
                      set('publishedAt', e.target.value);
                    }}
                  />
                )}
              </Field>
              <Field
                label="来源资料（选填）"
                error={errs.sourceArtifactId}
                hint={
                  evidenceFiles.length === 0
                    ? '还没有官方结果资料：请先在“资料”以“官方结果”用途上传'
                    : '只能选择以“官方结果”用途导入的资料'
                }
              >
                {(p) => (
                  <Select
                    {...p}
                    value={d.sourceArtifactId}
                    onChange={(e) => {
                      set('sourceArtifactId', e.target.value);
                    }}
                  >
                    <option value="">
                      {evidenceFiles.length === 0 ? '暂无官方结果资料' : '不选'}
                    </option>
                    {evidenceFiles.map((f) => (
                      <option key={f.version_id} value={f.artifact.artifact_id}>
                        {f.original_name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="来源页码（选填）" error={errs.sourcePage}>
                {(p) => (
                  <Input
                    {...p}
                    inputMode="numeric"
                    value={d.sourcePage}
                    onChange={(e) => {
                      set('sourcePage', e.target.value);
                    }}
                  />
                )}
              </Field>
              <Field label="更正的原记录（选填）" hint="更正所选提交下的已有记录时选择，原记录保留">
                {(p) => (
                  <Select
                    {...p}
                    value={d.supersedes}
                    onChange={(e) => {
                      set('supersedes', e.target.value);
                    }}
                  >
                    <option value="">不更正任何记录</option>
                    {sameSubmission.map((o) => (
                      <option key={o.outcome_id} value={o.outcome_id}>
                        {formatDateTime(o.known_at)} 登记 · {stageResultLabel(o.stage_result)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            </div>
            <Field label="来源说明" error={errs.sourceDescription}>
              {(p) => (
                <Textarea
                  {...p}
                  rows={2}
                  value={d.sourceDescription}
                  onChange={(e) => {
                    set('sourceDescription', e.target.value);
                  }}
                />
              )}
            </Field>
            {evidenceFiles.length === 0 && files.isSuccess ? (
              <p className="text-muted-foreground">
                需要官方来源时，先到
                <Link className={textLink} to={`/projects/${pid}/materials`}>
                  “资料”
                </Link>
                用“官方结果”用途上传成绩公示等原件。
              </p>
            ) : null}
            {create.isError ? <ErrorNotice error={create.error} title="结果未登记" /> : null}
            <Button
              variant="primary"
              type="submit"
              disabled={
                create.isPending ||
                identityStale ||
                submissionStale ||
                (identityDiffers && !identityAck)
              }
            >
              {create.isPending ? '正在登记…' : '登记结果'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card aria-labelledby="oc-l" className="mb-5">
        <CardHeader>
          <CardTitle id="oc-l">已登记的结果</CardTitle>
        </CardHeader>
        <CardContent>
          {outcomes.isPending ? <Loading /> : null}
          {outcomes.isError ? (
            <ErrorNotice error={outcomes.error} onRetry={() => void outcomes.refetch()} />
          ) : null}
          {outcomes.isSuccess && outcomes.data.length === 0 ? (
            <p className="text-muted-foreground">暂无已登记的结果。未公布的结果不会被当作 0 分。</p>
          ) : null}
          {outcomes.isSuccess && outcomes.data.length > 0 ? (
            <div className="relative w-full overflow-x-auto">
              <table className="data-table stack-mobile">
                <caption className="sr-only">已登记的结果</caption>
                <thead>
                  <tr>
                    <th scope="col">记录</th>
                    <th scope="col">类型</th>
                    <th scope="col">分值／满分</th>
                    <th scope="col">阶段</th>
                    <th scope="col">核实</th>
                    <th scope="col">
                      <span className="sr-only">操作</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {outcomes.data.map((o) => (
                    <tr key={o.outcome_id}>
                      <th scope="row" className="min-w-[200px]">
                        {formatDateTime(o.known_at)}
                        <small>{sourceKindLabel(o.source_kind)}</small>
                        {supersededIds.has(o.outcome_id) ? <Tag tone="gray">已被取代</Tag> : null}
                      </th>
                      <td data-label="类型">{outcomeTargetLabel(o.target)}</td>
                      <td data-label="分值／满分">
                        {o.value ?? '未知'} / {o.maximum ?? '未知'}
                      </td>
                      <td data-label="阶段">{stageResultLabel(o.stage_result)}</td>
                      <td data-label="核实">
                        <Tag
                          tone={
                            o.verification_status === 'verified'
                              ? 'green'
                              : o.verification_status === 'conflict'
                                ? 'red'
                                : 'amber'
                          }
                        >
                          {verificationLabel(o.verification_status)}
                        </Tag>
                      </td>
                      <td>
                        {o.source_kind === 'user_reported' && !supersededIds.has(o.outcome_id) ? (
                          <small className="text-muted-foreground">
                            报送结果需以官方来源重新登记
                          </small>
                        ) : null}
                        {o.target !== 'no_score' && o.value === null ? (
                          <small>分值未知，补齐后再核验</small>
                        ) : null}
                        {(o.target === 'no_score' || o.value !== null) &&
                        o.source_kind === 'official' &&
                        o.verification_status !== 'verified' &&
                        !supersededIds.has(o.outcome_id) ? (
                          <button
                            type="button"
                            className={textLink}
                            onClick={() => {
                              setVerifying(o);
                            }}
                          >
                            核实来源
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>
      {verifying ? (
        <VerifyDialog
          outcome={verifying}
          files={evidenceFiles.map((f) => ({ id: f.artifact.artifact_id, name: f.original_name }))}
          onClose={() => {
            setVerifying(null);
          }}
          onDone={() => {
            void qc.invalidateQueries({ queryKey: outcomeKeys.list(pid) });
            void invalidateProject(qc, pid);
            setVerifying(null);
          }}
        />
      ) : null}
    </div>
  );
}

function VerifyDialog({
  outcome,
  files,
  onClose,
  onDone,
}: {
  outcome: Outcome;
  files: { id: string; name: string }[];
  onClose: () => void;
  onDone: (o: Outcome) => void;
}) {
  const [artifact, setArtifact] = useState('');
  const [page, setPage] = useState('');
  const [agg, setAgg] = useState(outcome.aggregation ?? '');
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const m = useIdempotentAction(
    (b: Parameters<typeof api.outcomes.verify>[1], o) =>
      api.outcomes.verify(outcome.outcome_id, b, o),
    {
      onSuccess: onDone,
    },
  );
  const errs = {
    artifact: !artifact ? '请选择官方来源资料' : null,
    page: !/^[1-9][0-9]*$/.test(page.trim()) ? '请填写来源所在页码' : null,
    agg: !agg.trim() ? '请说明聚合方式' : null,
    reason: !reason.trim() ? '请填写核实说明' : null,
  };
  return (
    <Dialog title="核实官方来源" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          if (Object.values(errs).some(Boolean)) return;
          m.mutate({
            source_artifact_id: artifact,
            source_page: Number(page),
            aggregation: agg.trim(),
            reason: reason.trim(),
          });
        }}
        noValidate
      >
        <Field
          label="来源资料"
          error={touched ? errs.artifact : null}
          hint={
            files.length === 0 ? '还没有官方结果资料：请先在“资料”以“官方结果”用途上传' : undefined
          }
        >
          {(p) => (
            <Select
              {...p}
              value={artifact}
              onChange={(e) => {
                setArtifact(e.target.value);
              }}
            >
              <option value="">{files.length === 0 ? '暂无官方结果资料' : '请选择'}</option>
              {files.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="来源页码" error={touched ? errs.page : null}>
          {(p) => (
            <Input
              {...p}
              inputMode="numeric"
              value={page}
              onChange={(e) => {
                setPage(e.target.value);
              }}
            />
          )}
        </Field>
        <Field label="聚合方式" error={touched ? errs.agg : null}>
          {(p) => (
            <Input
              {...p}
              value={agg}
              onChange={(e) => {
                setAgg(e.target.value);
              }}
            />
          )}
        </Field>
        <Field label="核实说明" error={touched ? errs.reason : null}>
          {(p) => (
            <Textarea
              {...p}
              rows={2}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
            />
          )}
        </Field>
        {m.isError ? <ErrorNotice error={m.error} title="核实未保存" /> : null}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" type="submit" disabled={m.isPending}>
            提交核实
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
