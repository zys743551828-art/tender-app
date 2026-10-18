import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { EvidenceRef, RecognitionReviewRequest } from '../../api/types';
import { ErrorNotice, Loading, Notice } from '../../components/ui';
import { Button, textLink } from '../../components/ui/button';
import { Textarea } from '../../components/ui/input';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { refreshRules } from '../rules/actions';

const decisionLabel = { accept: '确认摘录', correct: '订正摘录', reject: '排除此候选' };

export function RecognitionPanel({
  projectId,
  versionId,
  initiallyOpen = false,
}: {
  projectId: string;
  versionId: string;
  initiallyOpen?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ['recognition', versionId, offset],
    queryFn: () => api.recognition.list(versionId, offset),
    enabled: open,
  });
  return (
    <section className="my-5 rounded-lg border border-border p-4" aria-label="识别候选核验">
      <Button onClick={() => setOpen(!open)} aria-expanded={open}>
        核验识别候选
      </Button>
      {open ? (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            逐条对照原页核对。人工核验只代表该摘录，不代表整页、表格关系或图形语义完整。核验后需按当前资料重新评审，原报告保留。
          </p>
          <Button onClick={() => void q.refetch()}>刷新候选</Button>
          {q.isPending ? <Loading /> : null}
          {q.isError ? <ErrorNotice error={q.error} onRetry={() => void q.refetch()} /> : null}
          {q.data ? (
            <>
              <p>
                共 {q.data.total} 条候选，{q.data.pending_count} 条待核验。
              </p>
              {!q.data.can_review && q.data.items.length > 0 ? (
                <Notice>
                  当前稿件或解析已变化，或解析仍在进行。请返回资料列表选择当前采用稿，等待解析完成后刷新。
                </Notice>
              ) : null}
              {q.data.total === 0 ? (
                <p>
                  此解析没有可核验的 OCR／表格候选。扫描识别失败或没有候选时，请补交可复制文字的
                  PDF。
                </p>
              ) : null}
              {q.data.items.map((item) => (
                <CandidateForm
                  key={`${q.data.parse_id ?? ''}:${item.evidence_id}`}
                  projectId={projectId}
                  versionId={versionId}
                  parseId={q.data.parse_id ?? ''}
                  evidence={item}
                  disabled={!q.data.can_review}
                />
              ))}
              <div className="flex gap-3">
                <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>
                  上一页候选
                </Button>
                <Button
                  disabled={q.data.next_offset === null}
                  onClick={() => setOffset(q.data.next_offset ?? 0)}
                >
                  下一页候选
                </Button>
                <Button asChild>
                  <Link to={`/projects/${projectId}`}>返回报告并重新评审</Link>
                </Button>
              </div>
              <details>
                <summary>最近的核验记录（最多 20 条）</summary>
                {q.data.history.map((review) => (
                  <article
                    className="my-3 border-t border-border pt-2 text-sm"
                    key={review.review_id}
                  >
                    <strong>
                      {decisionLabel[review.decision]} · {review.actor_name}
                    </strong>
                    <p className="whitespace-pre-wrap">原摘录：{review.original_quote}</p>
                    {review.decision === 'correct' ? (
                      <p className="whitespace-pre-wrap">订正为：{review.result_quote}</p>
                    ) : null}
                    <p>说明：{review.reason}</p>
                  </article>
                ))}
              </details>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function CandidateForm({
  projectId,
  versionId,
  parseId,
  evidence,
  disabled,
}: {
  projectId: string;
  versionId: string;
  parseId: string;
  evidence: EvidenceRef;
  disabled: boolean;
}) {
  const [decision, setDecision] = useState<RecognitionReviewRequest['decision']>('accept');
  const [quote, setQuote] = useState(evidence.quote);
  const [reason, setReason] = useState('');
  const [original, setOriginal] = useState(false);
  const [numbers, setNumbers] = useState(false);
  const qc = useQueryClient();
  const action = useIdempotentAction(
    (body: RecognitionReviewRequest, options) => api.recognition.review(versionId, body, options),
    {
      onSuccess: async () => {
        await Promise.all([
          qc.invalidateQueries({ queryKey: ['recognition', versionId] }),
          refreshRules(qc, projectId),
        ]);
      },
    },
  );
  const numeric = /[\p{N}零〇一二两三四五六七八九十百千万亿%‰]/u.test(evidence.quote + quote);
  const prefix = `recognition-${evidence.evidence_id}`;
  const busy = disabled || action.isPending;
  return (
    <form
      className="space-y-3 rounded-md border border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        action.mutate({
          expected_parse_id: parseId,
          evidence_id: evidence.evidence_id,
          decision,
          corrected_quote: decision === 'correct' ? quote.trim() : null,
          reason: reason.trim(),
          reviewed_original: original,
          reviewed_numbers: numbers,
        });
      }}
    >
      <p className="text-sm">
        {evidence.kind === 'table' ? '表格摘录' : 'OCR 摘录'} · 第 {evidence.physical_page} 页 ·{' '}
        {evidence.semantic_review === 'pending'
          ? '待核验'
          : evidence.semantic_review === 'supported'
            ? '已核验'
            : '已排除'}
      </p>
      <Link
        className={textLink}
        to={`/projects/${projectId}/files/${versionId}?page=${String(evidence.physical_page)}&verify=1`}
      >
        查看原页第 {evidence.physical_page} 页
      </Link>
      <p className="whitespace-pre-wrap break-words text-sm">{evidence.quote}</p>
      <label htmlFor={`${prefix}-decision`}>处理方式</label>
      <select
        id={`${prefix}-decision`}
        disabled={busy}
        value={decision}
        onChange={(event) => {
          setDecision(event.target.value as RecognitionReviewRequest['decision']);
          setOriginal(false);
          setNumbers(false);
        }}
      >
        <option value="accept">确认摘录</option>
        <option value="correct">订正摘录</option>
        <option value="reject">排除此候选</option>
      </select>
      {decision === 'correct' ? (
        <div>
          <label htmlFor={`${prefix}-quote`}>对照原页订正</label>
          <Textarea
            id={`${prefix}-quote`}
            maxLength={2000}
            value={quote}
            disabled={busy}
            onChange={(event) => {
              setQuote(event.target.value);
              setOriginal(false);
              setNumbers(false);
            }}
          />
        </div>
      ) : null}
      <div>
        <label htmlFor={`${prefix}-reason`}>核验说明</label>
        <Textarea
          id={`${prefix}-reason`}
          maxLength={1000}
          value={reason}
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <label className="flex gap-2">
        <input
          type="checkbox"
          checked={original}
          disabled={busy}
          onChange={(event) => setOriginal(event.target.checked)}
        />
        已对照原页核对该候选
      </label>
      {numeric && decision !== 'reject' ? (
        <label className="flex gap-2">
          <input
            type="checkbox"
            checked={numbers}
            disabled={busy}
            onChange={(event) => setNumbers(event.target.checked)}
          />
          已单独核对数字、符号与单位
        </label>
      ) : null}
      <Button
        type="submit"
        disabled={
          busy ||
          !original ||
          !reason.trim() ||
          (numeric && decision !== 'reject' && !numbers) ||
          (decision === 'correct' && (!quote.trim() || quote.trim() === evidence.quote))
        }
      >
        {action.isPending ? '正在保存…' : '保存此条核验'}
      </Button>
      {action.isError ? (
        <ErrorNotice error={action.error} title="未保存核验，请刷新候选后重试" />
      ) : null}
    </form>
  );
}
