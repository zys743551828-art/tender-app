import { useMutation } from '@tanstack/react-query';
import { useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/endpoints';
import type { FileVersion, SearchHit, SearchRequest, SearchResult } from '../../api/types';
import { ErrorNotice, Field, Notice } from '../../components/ui';
import { formatDateTime } from '../../lib/format';
import { evidenceKindLabel, indexStateLabel } from '../../lib/labels';
import { useFiles } from '../materials/queries';
import { useSnapshots } from '../snapshots/queries';
import { Icon } from '../../components/Icon';
import { Button, textLink } from '../../components/ui/button';
import { Input, Select } from '../../components/ui/input';

export const TOP_K_MAX = 50;

export interface SearchDraft {
  query: string;
  topK: string;
  mode: SearchRequest['mode'];
}

export function validateSearch(d: SearchDraft): Partial<Record<keyof SearchDraft, string>> {
  const e: Partial<Record<keyof SearchDraft, string>> = {};
  const q = d.query.trim();
  if (!q) e.query = '请输入要检索的内容';
  else if (q.length > 500) e.query = '检索内容不能超过 500 字';
  const k = Number(d.topK);
  if (!/^\d+$/.test(d.topK) || k < 1 || k > TOP_K_MAX)
    e.topK = `条数须为 1 到 ${String(TOP_K_MAX)} 的整数`;
  return e;
}

/** 后端 gaps 形如 `code:说明`；只展示说明（没有冒号则原样展示）。 */
export function gapText(g: string): string {
  const i = g.indexOf(':');
  return i >= 0 ? g.slice(i + 1) : g;
}

/**
 * 证据检索框 + 结果。默认检索项目当前资料；也可以限定在某一轮评审的输入所含的资料内。
 * renderAction 让调用方（事实表单的证据选择器）在每条结果旁加“选用”。
 */
export function EvidenceSearch({
  projectId,
  renderAction,
  compact = false,
}: {
  projectId: string;
  renderAction?: (hit: SearchHit) => ReactNode;
  compact?: boolean;
}) {
  const { snapshots } = useSnapshots(projectId);
  const files = useFiles(projectId);
  const [picked, setPicked] = useState('');
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState('10');
  const [mode, setMode] = useState<SearchRequest['mode']>('hybrid');
  const [touched, setTouched] = useState(false);
  // ''＝项目当前资料；其余是某一轮评审的输入 ID。
  const snapshotId = picked;
  const draft: SearchDraft = { query, topK, mode };
  const errs = touched ? validateSearch(draft) : {};

  const search = useMutation<SearchResult, Error, SearchRequest>({
    mutationFn: (b) => api.evidence.search(projectId, b),
  });
  const run = () => {
    setTouched(true);
    if (Object.keys(validateSearch(draft)).length > 0) return;
    search.mutate({
      ...(snapshotId ? { snapshot_id: snapshotId } : {}),
      query: query.trim(),
      top_k: Number(topK),
      mode,
    });
  };
  const onEnter = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      run();
    }
  };

  const res = search.data;
  return (
    <div role="search" aria-label="证据检索">
      <Field label="检索内容" error={errs.query}>
        {(p) => (
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <Icon
                name="Search"
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                {...p}
                className="pl-9"
                value={query}
                maxLength={500}
                placeholder="例如：工期、安全文明施工、混凝土强度"
                onChange={(e) => {
                  setQuery(e.target.value);
                }}
                onKeyDown={onEnter}
              />
            </div>
            <Button variant="primary" disabled={search.isPending} onClick={run}>
              {search.isPending ? '正在检索…' : '检索'}
            </Button>
          </div>
        )}
      </Field>
      <div className="grid gap-x-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Field label="检索范围" hint="也可以只看某一轮评审用到的资料">
          {(p) => (
            <Select
              {...p}
              value={snapshotId}
              onChange={(e) => {
                setPicked(e.target.value);
              }}
            >
              <option value="">当前资料</option>
              {snapshots.map((s, i) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  第 {snapshots.length - i} 轮评审用到的资料 · {formatDateTime(s.as_of)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="检索方式">
          {(p) => (
            <Select
              {...p}
              value={mode}
              onChange={(e) => {
                setMode(e.target.value as SearchRequest['mode']);
              }}
            >
              <option value="hybrid">按意思找</option>
              <option value="keyword">只按字面</option>
            </Select>
          )}
        </Field>
        <Field label="最多返回条数" error={errs.topK}>
          {(p) => (
            <Input
              {...p}
              inputMode="numeric"
              value={topK}
              onChange={(e) => {
                setTopK(e.target.value);
              }}
              onKeyDown={onEnter}
            />
          )}
        </Field>
      </div>
      {search.isError ? <ErrorNotice error={search.error} title="检索未完成" /> : null}
      {res ? (
        <div aria-live="polite" className="mt-2">
          <p className="mb-3 text-[13px] text-muted-foreground">
            共 {res.hits.length} 条 · 实际使用{res.mode_used === 'hybrid' ? '混合检索' : '关键词'} ·{' '}
            {indexStateLabel(res.index_state)}
          </p>
          {res.gaps.map((g) => (
            <Notice key={g} tone="plain">
              {gapText(g)}
            </Notice>
          ))}
          {res.hits.length === 0 ? (
            <p className="m-0 text-[13px] text-muted-foreground">
              没有找到相关证据。换个说法，或确认资料已上传并解析成功。
            </p>
          ) : (
            <ol
              className="m-0 list-none divide-y divide-border rounded-md border border-border p-0"
              aria-label="检索结果"
            >
              {res.hits.map((h) => (
                <HitItem
                  key={h.evidence.evidence_id}
                  hit={h}
                  projectId={projectId}
                  files={files.data}
                  action={renderAction?.(h)}
                  compact={compact}
                />
              ))}
            </ol>
          )}
        </div>
      ) : null}
    </div>
  );
}

function HitItem({
  hit,
  projectId,
  files,
  action,
  compact,
}: {
  hit: SearchHit;
  projectId: string;
  files: FileVersion[] | undefined;
  action: ReactNode;
  compact: boolean;
}) {
  const e = hit.evidence;
  const file = files?.find((f) => f.version_id === e.version_id);
  return (
    <li className="px-4 py-3">
      <blockquote className="m-0 mb-1.5 text-[13px] leading-relaxed">{e.quote}</blockquote>
      {(e.effectivity_notes ?? []).map((note) => (
        <Notice key={note}>{note}</Notice>
      ))}
      <p className="m-0 text-xs text-muted-foreground">
        {file ? file.original_name : e.file_name} · 第 {e.physical_page} 页
        {e.printed_page ? `（原件页码 ${e.printed_page}）` : ''} · {evidenceKindLabel(e.kind)}
      </p>
      <p className="m-0 mt-1.5 text-xs text-muted-foreground">
        <Link
          className={textLink}
          to={`/projects/${projectId}/evidence/${e.evidence_id}`}
          {...(compact ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
        >
          查看原页{compact ? '（新窗口）' : ''}
        </Link>
        {action ? <> · {action}</> : null}
      </p>
    </li>
  );
}
