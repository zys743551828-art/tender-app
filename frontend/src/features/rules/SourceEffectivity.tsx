import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type {
  EffectivityAction,
  EffectivityPreviewRequest,
  EffectivityQuote,
  RuleSet,
} from '../../api/types';
import { Dialog, DialogActions } from '../../components/Dialog';
import { useToast } from '../../components/Toast';
import { ErrorNotice, Field, Loading, Notice } from '../../components/ui';
import { Button, textLink } from '../../components/ui/button';
import { Textarea } from '../../components/ui/input';
import { useFiles } from '../materials/queries';
import { useDecideEffectivity } from './actions';

const labels: Record<EffectivityAction, string> = {
  partial_replace: '仅替代选中的条款',
  whole_replace: '整份替代原资料要求',
  defer: '关系不明，先标为待核实',
  retain: '核实后保留选中的原要求',
};

export function SourceEffectivity({ projectId, set }: { projectId: string; set: RuleSet }) {
  const [opened, setOpened] = useState<RuleSet | null>(null);
  const toast = useToast();
  if (set.source_version_ids.length < 2 && !set.effectivity_decisions?.length) return null;
  return (
    <section className="mb-5 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="m-0 text-sm font-semibold">补遗影响</h3>
        <Button
          size="sm"
          onClick={() => {
            setOpened(set);
          }}
        >
          核实补遗影响
        </Button>
      </div>
      <p className="text-muted-foreground">
        按原文明确替代范围。局部变化只结束指定要求，原件和其他条款继续保留。
      </p>
      {(set.effectivity_decisions ?? []).slice(-3).map((decision) => (
        <div key={decision.decision_id} className="mt-2 text-xs">
          <strong>{labels[decision.action]}</strong> · {decision.ended_rule_ids.length} 条结束，
          {decision.pending_rule_ids.length} 条待核实。{decision.reason}
          {decision.scope_basis.map((basis) => (
            <Link
              key={basis.evidence_id}
              className={`${textLink} ml-2`}
              to={`/projects/${projectId}/evidence/${basis.evidence_id}`}
            >
              补遗原文
            </Link>
          ))}
        </div>
      ))}
      {opened ? (
        <EffectivityDialog
          projectId={projectId}
          initial={opened}
          onClose={() => {
            setOpened(null);
          }}
          onDone={() => {
            setOpened(null);
            toast.notify('补遗影响已保存，重新评审后生效');
          }}
        />
      ) : null}
    </section>
  );
}

function EffectivityDialog({
  projectId,
  initial,
  onClose,
  onDone,
}: {
  projectId: string;
  initial: RuleSet;
  onClose: () => void;
  onDone: () => void;
}) {
  const files = useFiles(projectId);
  const [oldChoice, setOldChoice] = useState('');
  const [newChoice, setNewChoice] = useState('');
  const [action, setAction] = useState<EffectivityAction>('partial_replace');
  const [selected, setSelected] = useState<string[]>([]);
  const [basis, setBasis] = useState<EffectivityQuote | null>(null);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [reason, setReason] = useState('');
  const candidates = (files.data ?? []).filter((file) =>
    initial.source_version_ids.includes(file.version_id),
  );
  const newId =
    newChoice || (candidates.find((file) => file.role === 'supplement')?.version_id ?? '');
  const originals = candidates.filter((file) => file.version_id !== newId);
  const oldId =
    oldChoice ||
    (originals.find((file) => file.role === 'tender')?.version_id ??
      originals[0]?.version_id ??
      '');
  const currentRules = initial.rules.filter((rule) =>
    rule.evidence.some((ref) => ref.version_id === oldId),
  );
  const source = useQuery({
    queryKey: ['projects', projectId, 'source-evidence', newId, query],
    queryFn: () => api.rules.sourceEvidence(projectId, newId, query),
    enabled: !!newId,
  });
  const preview = useMutation({
    mutationFn: (request: EffectivityPreviewRequest) =>
      api.rules.previewEffectivity(projectId, request),
  });
  const decide = useDecideEffectivity(projectId, onDone);
  const request: EffectivityPreviewRequest = {
    object_version: String(initial.revision),
    old_version_id: oldId,
    new_version_id: newId,
    action,
    rule_ids: action === 'whole_replace' ? [] : selected,
  };
  const previewCurrent =
    preview.data && JSON.stringify(preview.variables) === JSON.stringify(request);
  const canPreview = !!oldId && !!newId && (action === 'whole_replace' || selected.length > 0);
  return (
    <Dialog title="核实补遗影响" onClose={onClose} wide>
      <p className="text-muted-foreground">
        先选资料与范围，查看受影响条款和可能相关的正文位置，再根据补遗原文确认。历史评审与原件保持。
      </p>
      {files.isPending ? (
        <Loading />
      ) : files.isError ? (
        <ErrorNotice error={files.error} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              补遗资料
              <select
                aria-label="补遗资料"
                value={newId}
                className="mt-1 block w-full rounded border border-border p-2"
                onChange={(event) => {
                  setNewChoice(event.target.value);
                  setOldChoice('');
                  setSelected([]);
                  setBasis(null);
                  setQuery('');
                  setSearch('');
                }}
              >
                <option value="">请选择</option>
                {candidates
                  .filter((file) => file.role === 'supplement')
                  .map((file) => (
                    <option key={file.version_id} value={file.version_id}>
                      {file.original_name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="text-sm">
              原资料
              <select
                aria-label="原资料"
                value={oldId}
                className="mt-1 block w-full rounded border border-border p-2"
                onChange={(event) => {
                  setOldChoice(event.target.value);
                  setSelected([]);
                }}
              >
                <option value="">请选择</option>
                {originals.map((file) => (
                  <option key={file.version_id} value={file.version_id}>
                    {file.original_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!newId ? (
            <Notice>当前规则没有对应的补遗资料，请先上传补遗并等待规则提取。</Notice>
          ) : (
            <>
              <fieldset className="my-4">
                <legend className="mb-2 text-sm font-semibold">如何处理原要求</legend>
                {(Object.entries(labels) as [EffectivityAction, string][]).map(([value, label]) => (
                  <label key={value} className="mb-2 flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="effectivity-action"
                      value={value}
                      checked={action === value}
                      onChange={() => {
                        setAction(value);
                      }}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {action === 'whole_replace' ? (
                <Notice>
                  系统将列出原资料的全部条款；同时引用多份原件的要求会保留待核实，不能整页删除。
                </Notice>
              ) : (
                <fieldset className="mb-4 max-h-52 overflow-y-auto rounded border border-border p-3">
                  <legend className="text-sm font-semibold">选择涉及的原条款</legend>
                  {currentRules.map((rule) => (
                    <label key={rule.rule_id} className="my-2 flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selected.includes(rule.rule_id)}
                        onChange={(event) => {
                          setSelected(
                            event.target.checked
                              ? [...selected, rule.rule_id]
                              : selected.filter((id) => id !== rule.rule_id),
                          );
                        }}
                      />
                      {rule.statement}
                    </label>
                  ))}
                </fieldset>
              )}
              <Button
                disabled={!canPreview || preview.isPending}
                onClick={() => {
                  preview.mutate(request);
                }}
              >
                查看影响范围
              </Button>
              {preview.isError ? <ErrorNotice error={preview.error} /> : null}
              {previewCurrent ? (
                <div className="my-3 rounded border border-border p-3 text-sm">
                  <strong>涉及 {preview.data.affected_rule_ids.length} 条原要求</strong>
                  {preview.data.mixed_source_rule_ids.length ? (
                    <p>
                      {preview.data.mixed_source_rule_ids.length}{' '}
                      条同时引用多份资料，整份替代也不能自动结束。
                    </p>
                  ) : null}
                  <h4 className="mt-2 font-semibold">可能相关的正文位置</h4>
                  {preview.data.related_sections.map((section, index) => (
                    <div key={`${section.title}-${index}`} className="mt-2">
                      {section.title}
                      {section.evidence.map((ref) => (
                        <Link
                          className={`${textLink} ml-2`}
                          key={ref.evidence_id}
                          to={`/projects/${projectId}/evidence/${ref.evidence_id}`}
                        >
                          第 {ref.physical_page} 页
                        </Link>
                      ))}
                    </div>
                  ))}
                  {preview.data.gaps.map((gap) => (
                    <p key={gap} className="text-xs text-muted-foreground">
                      {gap}
                    </p>
                  ))}
                </div>
              ) : null}
              <fieldset className="mt-4">
                <legend className="text-sm font-semibold">核对补遗原文</legend>
                <div className="my-2 flex gap-2">
                  <input
                    aria-label="查找补遗原文"
                    className="min-w-0 flex-1 rounded border border-border p-2"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                    }}
                    placeholder="输入条款关键词"
                  />
                  <Button
                    size="sm"
                    onClick={() => {
                      setQuery(search.trim());
                    }}
                  >
                    查找
                  </Button>
                </div>
                {source.isPending ? (
                  <Loading />
                ) : source.isError ? (
                  <ErrorNotice error={source.error} />
                ) : (
                  <div className="max-h-52 overflow-y-auto">
                    {source.data.map((ref) => (
                      <label
                        key={ref.evidence_id}
                        className="my-2 flex items-start gap-2 rounded border border-border p-2 text-sm"
                      >
                        <input
                          type="radio"
                          name="effectivity-basis"
                          checked={basis?.evidence_id === ref.evidence_id}
                          onChange={() => {
                            setBasis({ evidence_id: ref.evidence_id, quote: ref.quote });
                          }}
                        />
                        <span>
                          {ref.quote}
                          <Link
                            className={`${textLink} ml-2 text-xs`}
                            to={`/projects/${projectId}/evidence/${ref.evidence_id}`}
                          >
                            第 {ref.physical_page} 页原文
                          </Link>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </fieldset>
              {basis ? (
                <Field label="采用的逐字范围说明">
                  {(props) => (
                    <Textarea
                      {...props}
                      rows={3}
                      value={basis.quote}
                      onChange={(event) => {
                        setBasis({ ...basis, quote: event.target.value });
                      }}
                    />
                  )}
                </Field>
              ) : null}
              <Field label="核实理由">
                {(props) => (
                  <Textarea
                    {...props}
                    rows={2}
                    value={reason}
                    onChange={(event) => {
                      setReason(event.target.value);
                    }}
                  />
                )}
              </Field>
              {decide.isError ? (
                <ErrorNotice error={decide.error} title="没有保存，请核对范围与当前资料版本" />
              ) : null}
            </>
          )}
        </>
      )}
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          variant="primary"
          disabled={
            !previewCurrent ||
            !reason.trim() ||
            (action !== 'defer' && !basis?.quote.trim()) ||
            decide.isPending
          }
          onClick={() => {
            decide.mutate({ ...request, scope_basis: basis ? [basis] : [], reason: reason.trim() });
          }}
        >
          确认补遗影响
        </Button>
      </DialogActions>
    </Dialog>
  );
}
