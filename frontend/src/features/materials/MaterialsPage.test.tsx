import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import type { FileVersion, Task } from '../../api/types';
import { fileVersion, pipeline, task } from '../../test/fixtures';
import { ME, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

const withTime = (v: FileVersion, iso: string): FileVersion => ({ ...v, obtained_at: iso });

function backend(files: FileVersion[], tasks: Task[]) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/files', () => HttpResponse.json(files)),
    http.get('/api/v1/projects/prj-1/tasks', () => HttpResponse.json(tasks)),
  );
}

describe('资料：解析状态与评审进度', () => {
  it('每个文件显示解析状态；上传即评审，页面没有“下一步”按钮，顶部显示流水线进度', async () => {
    backend(
      [
        withTime(fileVersion('ver-t', 'tender', '招标文件.pdf'), '2026-10-01T00:00:00Z'),
        withTime(fileVersion('ver-d', 'drawing', '图纸.pdf'), '2026-10-01T00:10:00Z'),
      ],
      [
        task({
          task_id: 'tsk-p',
          kind: 'parse',
          state: 'succeeded',
          created_at: '2026-10-01T00:00:02Z',
        }),
      ],
    );
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          pipeline({
            stage: 'running',
            snapshot_id: null,
            steps: [
              { key: 'materials', state: 'done', task_id: null, message: null },
              { key: 'rules', state: 'running', task_id: 't1', message: null },
              { key: 'review', state: 'waiting', task_id: null, message: null },
              { key: 'prediction', state: 'waiting', task_id: null, message: null },
            ],
          }),
        ),
      ),
    );
    renderApp('/projects/prj-1/materials');
    const table = await screen.findByRole('table', { name: '项目资料' });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]!).getByText('已完成')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('无需解析')).toBeInTheDocument();
    const steps = within(await screen.findByRole('list', { name: '评审进度' }));
    expect(steps.getByText('资料解析')).toBeInTheDocument();
    expect(steps.getByText('评分预测')).toBeInTheDocument();
    expect(steps.getByText('进行中')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /下一步/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /下一步/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看评审进度' })).toHaveAttribute(
      'href',
      '/projects/prj-1',
    );
  });

  it('评审完成后直接提供查看报告的入口', async () => {
    backend([], []);
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(pipeline({ stage: 'done' })),
      ),
    );
    renderApp('/projects/prj-1/materials');
    expect(await screen.findByRole('link', { name: '查看评审报告' })).toHaveAttribute(
      'href',
      '/projects/prj-1',
    );
  });

  it('解析失败：如实显示状态与原因', async () => {
    backend(
      [withTime(fileVersion('ver-t', 'tender', '招标文件.pdf'), '2026-10-01T00:00:00Z')],
      [
        task({
          kind: 'parse',
          state: 'failed',
          created_at: '2026-10-01T00:00:02Z',
          error_code: 'STORAGE_UNAVAILABLE',
          message: '第 3 页无法读取',
        }),
      ],
    );
    renderApp('/projects/prj-1/materials');
    expect(await screen.findByText('失败')).toBeInTheDocument();
    expect(screen.getByText('第 3 页无法读取')).toBeInTheDocument();
    expect(screen.getByText(/还有 1 份招标文件／补遗正在解析/)).toBeInTheDocument();
  });

  it('没有招标文件：说明暂时不能评审；文件列表不显示校验值等内部信息', async () => {
    backend([fileVersion('ver-b', 'body', '技术标.pdf')], []);
    renderApp('/projects/prj-1/materials');
    expect(await screen.findByText('还没有招标文件，暂时不能评审。')).toBeInTheDocument();
    const table = screen.getByRole('table', { name: '项目资料' });
    expect(within(table).getByText('第 1 版')).toBeInTheDocument();
    expect(table).not.toHaveTextContent(/sha256/i);
  });
});

describe('资料：重复上传', () => {
  it('服务端返回清单里已有的版本：提示没有产生新版本', async () => {
    const existing = fileVersion('ver-t', 'tender', '招标文件.pdf');
    backend([existing], []);
    vi.resetModules();
    vi.doMock('../upload/uploader', async (orig) => {
      const real = await orig<typeof import('../upload/uploader')>();
      class FakeUploader {
        private listeners = new Set<(s: unknown) => void>();
        private state = {
          phase: 'idle',
          hashedBytes: 0,
          uploadedBytes: 0,
          totalBytes: 10,
          parts: [],
          error: null,
          requestId: null,
          version: null as FileVersion | null,
        };
        getState() {
          return this.state;
        }
        subscribe(fn: (s: unknown) => void) {
          this.listeners.add(fn);
          return () => this.listeners.delete(fn);
        }
        start() {
          this.state = { ...this.state, phase: 'done', version: existing };
          for (const l of this.listeners) l(this.state);
          return Promise.resolve();
        }
        retry() {
          return Promise.resolve();
        }
        cancel() {
          /* 无 */
        }
      }
      return { ...real, Uploader: FakeUploader };
    });
    const { renderApp: render } = await import('../../test/helpers');
    render('/projects/prj-1/materials');
    const input = await screen.findByLabelText('选择文件');
    await userEvent.upload(
      input,
      new File(['0123456789'], '招标文件.pdf', { type: 'application/pdf' }),
    );
    await userEvent.click(screen.getByRole('button', { name: '上传 1 个文件' }));
    expect(await screen.findByText(/没有产生新版本/)).toBeInTheDocument();
    vi.doUnmock('../upload/uploader');
  });
});

describe('资料：用途与版本', () => {
  async function renderWithFakeUploader(files: FileVersion[], doneVersion: FileVersion | null) {
    backend(files, []);
    vi.resetModules();
    const inputs: { file: { name: string }; role: string; versionOfFileId?: string | null }[] = [];
    vi.doMock('../upload/uploader', async (orig) => {
      const real = await orig<typeof import('../upload/uploader')>();
      class FakeUploader {
        private listeners = new Set<(s: unknown) => void>();
        private state = {
          phase: 'idle',
          hashedBytes: 0,
          uploadedBytes: 0,
          totalBytes: 10,
          parts: [],
          error: null,
          requestId: null,
          version: null as FileVersion | null,
        };
        constructor(
          _deps: unknown,
          input: { file: { name: string }; role: string; versionOfFileId?: string | null },
        ) {
          inputs.push(input);
        }
        getState() {
          return this.state;
        }
        subscribe(fn: (s: unknown) => void) {
          this.listeners.add(fn);
          return () => this.listeners.delete(fn);
        }
        start() {
          this.state = { ...this.state, phase: 'done', version: doneVersion };
          for (const l of this.listeners) l(this.state);
          return Promise.resolve();
        }
        retry() {
          return Promise.resolve();
        }
        cancel() {
          /* 无 */
        }
      }
      return { ...real, Uploader: FakeUploader };
    });
    const { renderApp: render } = await import('../../test/helpers');
    return { render, inputs };
  }
  const pdf = (name: string) => new File(['0123456789'], name, { type: 'application/pdf' });

  it('按文件名猜用途与版本：同名为新版本，唯一一份正文默认是它的新版本；上传前可以改', async () => {
    const tender = fileVersion('ver-t', 'tender', '招标文件.pdf');
    const body = fileVersion('ver-b1', 'body', '施组.pdf');
    const { render, inputs } = await renderWithFakeUploader([tender, body], null);
    render('/projects/prj-1/materials');
    const input = await screen.findByLabelText('选择文件');
    await waitFor(() => {
      expect(screen.getByRole('table', { name: '项目资料' })).toBeInTheDocument();
    });
    await userEvent.upload(input, [
      pdf('招标文件.pdf'),
      pdf('施工组织设计-修改.pdf'),
      pdf('补遗书.pdf'),
    ]);
    const list = within(screen.getByRole('list', { name: '待上传' }));
    expect(list.getByLabelText('招标文件.pdf 的用途')).toHaveValue('tender');
    expect(list.getByLabelText('招标文件.pdf 记为')).toHaveValue(tender.file_id);
    expect(list.getByLabelText('施工组织设计-修改.pdf 的用途')).toHaveValue('body');
    expect(list.getByLabelText('施工组织设计-修改.pdf 记为')).toHaveValue(body.file_id);
    expect(list.getByLabelText('补遗书.pdf 的用途')).toHaveValue('supplement');
    expect(list.getByLabelText('补遗书.pdf 记为')).toHaveValue('');
    // 改成新文件
    await userEvent.selectOptions(list.getByLabelText('招标文件.pdf 记为'), '');
    expect(inputs).toHaveLength(0); // 点上传之前不传
    await userEvent.click(screen.getByRole('button', { name: '上传 3 个文件' }));
    expect(inputs.map((i) => [i.file.name, i.role, i.versionOfFileId])).toEqual([
      ['招标文件.pdf', 'tender', null],
      ['施工组织设计-修改.pdf', 'body', body.file_id],
      ['补遗书.pdf', 'supplement', null],
    ]);
    vi.doUnmock('../upload/uploader');
  });

  it('?role=body 带来的用途优先；结果显示“已记为 X 的第 N 版”', async () => {
    const v1 = withTime(fileVersion('ver-b1', 'body', '技术标.pdf'), '2026-10-01T00:00:00Z');
    const v2 = {
      ...withTime(fileVersion('ver-b2', 'body', 'scan.pdf'), '2026-10-02T00:00:00Z'),
      file_id: v1.file_id,
      supersedes: 'ver-b1',
    };
    const { render, inputs } = await renderWithFakeUploader([v1], v2);
    render('/projects/prj-1/materials?role=body');
    const input = await screen.findByLabelText('选择文件');
    await waitFor(() => {
      expect(screen.getByRole('table', { name: '项目资料' })).toBeInTheDocument();
    });
    await userEvent.upload(input, pdf('scan.pdf'));
    await userEvent.click(screen.getByRole('button', { name: '上传 1 个文件' }));
    expect(inputs[0]).toMatchObject({ role: 'body', versionOfFileId: v1.file_id });
    expect(await screen.findByText(/已记为「scan\.pdf」的第 2 版/)).toBeInTheDocument();
    vi.doUnmock('../upload/uploader');
  });
});
