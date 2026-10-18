import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import { isApiError } from '../../api/errors';
import type { AssistantCard, AssistantReply } from '../../api/types';
import { ErrorNotice } from '../../components/ui';
import { Button, textLink } from '../../components/ui/button';
import { Card, CardHeader, CardTitle } from '../../components/ui/card';
import { Textarea } from '../../components/ui/input';
import { useIdempotentAction } from '../../lib/useIdempotentAction';

const labels = {
  materials: '资料',
  basis: '核对依据',
  findings: '查看问题',
  submit: '登记提交',
  outcomes: '登记成绩',
};

export function ProjectAssistant({ projectId }: { projectId: string }) {
  const [message, setMessage] = useState('');
  const ask = useMutation({
    mutationFn: (question: string) => api.assistant.ask(projectId, question),
  });
  const send = (question: string) => {
    if (!question.trim() || ask.isPending) return;
    ask.reset();
    ask.mutate(question.trim());
  };
  return (
    <Card aria-label="项目 AI 助手">
      <CardHeader>
        <CardTitle>项目 AI 助手</CardTitle>
      </CardHeader>
      <div className="space-y-3 px-4 pb-4 text-[13px]">
        <p className="text-xs text-muted-foreground">
          围绕当前项目单次提问。回答是建议，操作需点击确认；刷新页面后清空。
        </p>
        <div className="flex flex-wrap gap-2">
          {['先改哪项', '检查新版', '确认规则'].map((text) => (
            <Button
              key={text}
              size="sm"
              disabled={ask.isPending}
              onClick={() => {
                setMessage(text);
                send(text);
              }}
            >
              {text}
            </Button>
          ))}
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            send(message);
          }}
          className="space-y-2"
        >
          <Textarea
            aria-label="向项目 AI 提问"
            maxLength={1000}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="例如：先处理哪些否决风险？"
            disabled={ask.isPending}
          />
          <Button type="submit" size="sm" disabled={!message.trim() || ask.isPending}>
            {ask.isPending ? '正在回答…' : '发送问题'}
          </Button>
        </form>
        {ask.isError ? <ErrorNotice error={ask.error} /> : null}
        {ask.data ? <AssistantResult key={ask.submittedAt} reply={ask.data} /> : null}
      </div>
    </Card>
  );
}

function AssistantResult({ reply }: { reply: AssistantReply }) {
  const base = `/projects/${reply.project_id}`;
  return (
    <div className="space-y-3" aria-live="polite">
      <p className="text-xs text-muted-foreground">
        {reply.mode === 'model' ? 'AI 建议草稿' : '项目状态提示'} · 最多 12 个问题和 20 条规则摘要
      </p>
      <p className="whitespace-pre-wrap break-words">{reply.answer}</p>
      <div className="rounded-md bg-muted p-2 text-xs break-all">
        <p>
          {reply.project_title} · {reply.lot ?? '未填标段'} · 第 {reply.round} 轮
        </p>
        <p>正文：{reply.body_version_id ?? '尚无正文'}</p>
        <p>评审输入：{reply.snapshot_id ?? '尚未冻结'}</p>
        {reply.materials.map((file) => (
          <p key={file.version_id}>
            <a
              className={textLink}
              href={api.files.contentUrl(file.version_id)}
              target="_blank"
              rel="noreferrer"
            >
              {file.filename}
            </a>{' '}
            · {file.version_id}
          </p>
        ))}
      </div>
      {reply.cards.map((card) => (
        <Confirmation key={card.kind} card={card} projectId={reply.project_id} />
      ))}
      <div className="flex flex-wrap gap-3">
        {reply.links.map((key) => (
          <Link
            key={key}
            className={textLink}
            to={key === 'outcomes' ? `${base}/submit?tab=outcomes` : `${base}/${key}`}
          >
            {labels[key]}
          </Link>
        ))}
      </div>
    </div>
  );
}

function Confirmation({ card, projectId }: { card: AssistantCard; projectId: string }) {
  const qc = useQueryClient();
  const [ack, setAck] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const submit = useIdempotentAction(
    async (_: null, options) => {
      if (card.kind === 'analysis') {
        await api.pipeline.confirmStart(projectId, card.expected_context, options);
        return '评审请求已受理，请查看流水线进度。';
      }
      const result = await api.rules.confirmPending(
        projectId,
        {
          object_version: card.object_version ?? '',
          rule_ids: card.rule_ids,
          expected_context: card.expected_context,
        },
        options,
      );
      return `已确认 ${result.confirmed} 条，已处理而跳过 ${result.skipped} 条。`;
    },
    {
      onSuccess: async (result) => {
        setDone(result);
        await qc.invalidateQueries({ queryKey: ['projects'] });
      },
    },
  );
  return (
    <section aria-label={card.title} className="space-y-2 rounded-md border border-border p-3">
      <strong>{card.title}</strong>
      <p>{card.detail}</p>
      {card.rule_statements.length ? (
        <ol className="list-decimal space-y-2 pl-4">
          {card.rule_statements.map((text, index) => (
            <li key={card.rule_ids[index]}>{text}</li>
          ))}
        </ol>
      ) : null}
      {done ? (
        <p role="status">{done}</p>
      ) : (
        <>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={ack}
              disabled={submit.isPending}
              onChange={(event) => setAck(event.target.checked)}
            />
            {card.kind === 'analysis'
              ? '已核对本卡项目和输入，确认启动评审'
              : '已逐条对照原文，按上述内容确认'}
          </label>
          <Button
            size="sm"
            disabled={!ack || submit.isPending || submit.isError}
            onClick={() => submit.mutate(null)}
          >
            {submit.isPending ? '正在提交…' : '确认执行'}
          </Button>
        </>
      )}
      {submit.isError ? (
        <>
          <ErrorNotice error={submit.error} />
          <p>请重新提问获取当前状态和新卡。</p>
          {isApiError(submit.error) && submit.error.retryable ? (
            <Button size="sm" onClick={() => submit.mutate(null)} disabled={submit.isPending}>
              重试同一卡片
            </Button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
