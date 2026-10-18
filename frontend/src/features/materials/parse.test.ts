import { describe, expect, it } from 'vitest';
import { fileVersion, task } from '../../test/fixtures';
import { extractReadiness, parseOk, parseTaskByVersion } from './parse';

const at = (iso: string) => ({ obtained_at: iso });
const f = (
  id: string,
  role: Parameters<typeof fileVersion>[1],
  iso: string,
  supersedes?: string,
) => ({
  ...fileVersion(id, role, `${id}.pdf`),
  ...at(iso),
  supersedes: supersedes ?? null,
});

describe('parseTaskByVersion', () => {
  it('任务带 file_version_id 时直接配对，同一文件取最新的任务', () => {
    const files = [f('v1', 'tender', '2026-10-01T00:00:00Z')];
    const m = parseTaskByVersion(files, [
      task({
        task_id: 'a',
        kind: 'parse',
        file_version_id: 'v1',
        created_at: '2026-10-01T00:00:01Z',
        state: 'failed',
      }),
      task({
        task_id: 'b',
        kind: 'parse',
        file_version_id: 'v1',
        created_at: '2026-10-01T00:05:00Z',
        state: 'succeeded',
      }),
    ]);
    expect(m.get('v1')?.task_id).toBe('b');
  });

  it('没有 file_version_id 时按创建时间与取得时间最接近一对一配对；只看 parse 任务', () => {
    const files = [
      f('v2', 'supplement', '2026-10-01T01:00:00Z'),
      f('v1', 'tender', '2026-10-01T00:00:00Z'),
    ];
    const m = parseTaskByVersion(files, [
      task({ task_id: 't2', kind: 'parse', created_at: '2026-10-01T01:00:02Z' }),
      task({ task_id: 't1', kind: 'parse', created_at: '2026-10-01T00:00:03Z' }),
      task({ task_id: 'tr', kind: 'rules', created_at: '2026-10-01T00:00:01Z' }),
    ]);
    expect(m.get('v1')?.task_id).toBe('t1');
    expect(m.get('v2')?.task_id).toBe('t2');
  });

  it('超出时间窗口、或不需要解析的用途（图纸）不配对', () => {
    const files = [
      f('v1', 'drawing', '2026-10-01T00:00:00Z'),
      f('v2', 'tender', '2026-10-01T00:00:00Z'),
    ];
    const m = parseTaskByVersion(files, [
      task({ kind: 'parse', created_at: '2026-10-02T00:00:00Z' }),
    ]);
    expect(m.size).toBe(0);
  });
});

describe('extractReadiness', () => {
  const ok = (id: string) => task({ task_id: `t-${id}`, kind: 'parse', state: 'succeeded' });
  it('至少一份招标文件且每份招标文件／补遗的最新版本都解析成功才就绪', () => {
    const files = [
      f('s1', 'supplement', '2026-10-02T00:00:00Z'),
      f('t1', 'tender', '2026-10-01T00:00:00Z'),
    ];
    expect(extractReadiness(files, new Map([['t1', ok('t1')]]))).toMatchObject({
      ready: false,
      hasTender: true,
      waiting: 1,
    });
    expect(
      extractReadiness(
        files,
        new Map([
          ['t1', ok('t1')],
          ['s1', ok('s1')],
        ]),
      ).ready,
    ).toBe(true);
  });

  it('没有招标文件：不就绪；被取代的旧版本不计入；覆盖度 failed 视为未解析', () => {
    expect(
      extractReadiness([f('s1', 'supplement', '2026-10-02T00:00:00Z')], new Map()),
    ).toMatchObject({
      ready: false,
      hasTender: false,
    });
    const files = [
      f('t2', 'tender', '2026-10-02T00:00:00Z', 't1'),
      f('t1', 'tender', '2026-10-01T00:00:00Z'),
    ];
    expect(extractReadiness(files, new Map([['t2', ok('t2')]])).ready).toBe(true);
    const bad = task({ kind: 'parse', state: 'failed', error_code: 'parse_unreadable' });
    expect(parseOk(bad)).toBe(false);
    expect(extractReadiness(files, new Map([['t2', bad]])).ready).toBe(false);
  });
});

it('Word 招标只按已采用的实际 PDF 判断就绪，忽略未采用的转换候选', () => {
  const original = {
    ...f('word', 'tender', '2026-10-02T00:00:00Z'),
    word: {
      current: true,
      state: 'converted' as const,
      error_code: null,
      adopted_pdf_version_id: 'pdf',
      candidates: [],
    },
  };
  const pdf = { ...f('pdf', 'tender', '2026-10-03T00:00:00Z'), source_word_version_id: 'word' };
  const candidate = {
    ...f('candidate', 'tender', '2026-10-04T00:00:00Z'),
    source_word_version_id: 'word',
  };
  expect(
    extractReadiness(
      [original, pdf, candidate],
      new Map([['pdf', task({ kind: 'parse', state: 'succeeded' })]]),
    ).ready,
  ).toBe(true);
  expect(
    extractReadiness(
      [{ ...original, word: { ...original.word, adopted_pdf_version_id: null } }, pdf],
      new Map([['pdf', task({ kind: 'parse', state: 'succeeded' })]]),
    ).ready,
  ).toBe(false);
});
