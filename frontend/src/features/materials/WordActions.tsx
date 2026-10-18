import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { FileVersion } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/ui';
import { Button, textLink } from '../../components/ui/button';
import { Textarea } from '../../components/ui/input';
import { newIdempotencyKey } from '../../lib/uuid';

export function WordActions({
  file,
  onUpload,
}: {
  file: FileVersion;
  onUpload: (pdf: File) => void;
}) {
  const word = file.word;
  const qc = useQueryClient();
  const [mode, setMode] = useState<string | null>(null);
  const [pdf, setPdf] = useState<File | null>(null);
  const [checked, setChecked] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!word) return null;
  const refresh = async () => {
    for (const name of ['files', 'tasks', 'pipeline', 'report'])
      await qc.invalidateQueries({ queryKey: ['projects', file.project_id, name] });
  };
  const open = (next: string) => {
    setMode(next);
    setChecked(false);
    setPdf(null);
    setReason('');
    setError(null);
  };
  const submit = async () => {
    if (!checked) return;
    if (mode === 'upload') {
      if (pdf) {
        onUpload(pdf);
        setMode(null);
      }
      return;
    }
    if (!mode || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.files.adoptWordPdf(
        file.version_id,
        { link_id: mode, reviewed_pdf: true, reason },
        { idempotencyKey: newIdempotencyKey() },
      );
      await refresh();
      setMode(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const retry = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.files.retryWord(file.version_id, { idempotencyKey: newIdempotencyKey() });
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-2 grid gap-2 text-xs">
      <p>
        {!word.current
          ? '历史 Word 原稿'
          : word.adopted_pdf_version_id
            ? '已关联实际评审 PDF，Word 原稿保留'
            : word.state === 'needs_review'
              ? 'PDF 已生成，请核对版式后采用'
              : word.state === 'failed'
                ? '未取得可采用的 PDF，可只补交此稿'
                : 'Word 已接收，等待可采用的 PDF'}
      </p>
      <a className={textLink} href={api.files.contentUrl(file.version_id)}>
        下载 Word 原稿
      </a>
      {word.candidates.map((candidate) => (
        <div key={candidate.link_id} className="grid gap-1 border-l border-border pl-2">
          <Link
            className={textLink}
            to={`/projects/${file.project_id}/files/${candidate.pdf_version_id}`}
          >
            查看{candidate.method === 'user_declared' ? '用户补交' : '转换生成'}的 PDF
          </Link>
          <span>
            {candidate.method === 'user_declared'
              ? '用户声明对应此稿，内容对应关系未经系统核实'
              : candidate.gaps.length
                ? '文字、字体或复杂版式仍需核对'
                : '固定方法转换，评审对象为此 PDF'}
          </span>
          {word.adopted_pdf_version_id === candidate.pdf_version_id ? (
            <strong>已采用</strong>
          ) : word.current ? (
            <Button size="sm" disabled={busy} onClick={() => open(candidate.link_id)}>
              核对后采用此 PDF
            </Button>
          ) : null}
        </div>
      ))}
      {word.current ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => open('upload')}>
            上传此稿的 PDF
          </Button>
          <Button size="sm" disabled={busy} onClick={() => void retry()}>
            重试 Word 转换
          </Button>
        </div>
      ) : null}
      {error && !mode ? <ErrorNotice error={error} /> : null}
      {mode ? (
        <Dialog
          title={mode === 'upload' ? '为此稿补交 PDF' : '采用实际评审 PDF'}
          description={`对应原稿：${file.original_name}（第 ${file.version_number} 版）`}
          onClose={() => {
            if (!busy) setMode(null);
          }}
        >
          <div className="grid gap-4">
            <p>
              Word 原稿和历史报告保留，后续评审读取实际 PDF。补交关系由你声明，系统不会据此判定 Word
              原稿合格。
            </p>
            {mode === 'upload' ? (
              <label>
                选择此稿的 PDF
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(e) => setPdf(e.target.files?.[0] ?? null)}
                />
              </label>
            ) : (
              <label htmlFor={`word-adopt-reason-${file.version_id}`}>
                采用依据
                <Textarea
                  id={`word-adopt-reason-${file.version_id}`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )}
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
              />
              {mode === 'upload'
                ? '我声明所选 PDF 对应上方这版 Word，供实际评审使用'
                : '我已查看并核对此 PDF，确认用它进行评审'}
            </label>
            {error ? <ErrorNotice error={error} /> : null}
            <Button
              disabled={busy || !checked || (mode === 'upload' ? !pdf : !reason.trim())}
              onClick={() => void submit()}
            >
              {mode === 'upload' ? '上传并用于评审' : '采用此 PDF'}
            </Button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
