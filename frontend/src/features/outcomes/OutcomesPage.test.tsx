import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { FileVersion, Outcome } from '../../api/types';
import { formatDateTime } from '../../lib/format';
import { fileVersion, outcome as baseOutcome, submission } from '../../test/fixtures';
import { ME, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

/** 界面不显示记录编号：测试里按登记时间区分记录，每个编号对应一个不同的登记时间。 */
const KNOWN_AT: Record<string, string> = {};
function knownAt(id: string): string {
  KNOWN_AT[id] ??= new Date(Date.UTC(2026, 9, 6, 2, Object.keys(KNOWN_AT).length)).toISOString();
  return KNOWN_AT[id];
}
function outcome(over: Partial<Outcome> = {}): Outcome {
  const id = over.outcome_id ?? 'out-1';
  return baseOutcome({ known_at: knownAt(id), ...over });
}
const shown = (id: string) => formatDateTime(knownAt(id));

function backend(
  over: {
    outcomes?: Outcome[];
    files?: FileVersion[];
  } = {},
) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/files', () => HttpResponse.json(over.files ?? [])),
    http.get('/api/v1/projects/prj-1/submissions', () =>
      HttpResponse.json([submission(), submission({ submission_id: 'sub-2' })]),
    ),
    http.get('/api/v1/projects/prj-1/outcomes', () => HttpResponse.json(over.outcomes ?? [])),
  );
}

describe('结果登记（提交与结果页“开标结果”标签）', () => {
  it('列出后端保存的全部结果，刷新页面后仍在', async () => {
    backend({ outcomes: [outcome(), outcome({ outcome_id: 'out-2', stage_result: 'awarded' })] });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    const table = await screen.findByRole('table', { name: '已登记的结果' });
    expect(within(table).getByText(shown('out-1'))).toBeInTheDocument();
    expect(within(table).getByText(shown('out-2'))).toBeInTheDocument();
    expect(table).not.toHaveTextContent('out-1'); // 不显示内部编号
    expect(within(table).getAllByText('86.5 / 100')).toHaveLength(2);
  });

  it('没有结果：空状态；提交从后端列表选择，默认选中 URL 指定的提交', async () => {
    backend();
    renderApp('/projects/prj-1/submit?tab=outcomes&submission=sub-2');
    expect(await screen.findByText(/暂无已登记的结果/)).toBeInTheDocument();
    const select = await screen.findByLabelText('关联的实际提交');
    expect(select).toHaveValue('sub-2');
  });

  it('登记结果（无分值·仅阶段结果）：提交所选的提交 ID，成功后重新读取列表', async () => {
    let list = [] as ReturnType<typeof outcome>[];
    backend();
    server.use(http.get('/api/v1/projects/prj-1/outcomes', () => HttpResponse.json(list)));
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post('/api/v1/projects/prj-1/outcomes', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        list = [outcome({ outcome_id: 'out-new' })];
        return HttpResponse.json(list[0]);
      }),
    );
    renderApp('/projects/prj-1/submit?tab=outcomes');
    await screen.findByText(/暂无已登记的结果/);
    await userEvent.selectOptions(screen.getByLabelText('成绩类型'), 'no_score');
    await userEvent.type(screen.getByLabelText('来源说明'), '招标网站公示');
    await userEvent.click(screen.getByRole('button', { name: '登记结果' }));
    expect(await screen.findByText(shown('out-new'))).toBeInTheDocument();
    expect(body).toMatchObject({
      submission_id: 'sub-1',
      source_description: '招标网站公示',
      target: 'no_score',
      value: null,
      maximum: null,
    });
  });

  it('有分值的成绩类型必须同时填分值和满分：留空不发请求，并提示改选“无分值”', async () => {
    backend();
    let posted = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/outcomes', () => {
        posted++;
        return HttpResponse.json(outcome());
      }),
    );
    renderApp('/projects/prj-1/submit?tab=outcomes');
    await screen.findByText(/暂无已登记的结果/);
    // 分值未公布时引导改选“无分值”，而不是留空
    expect(screen.queryByText('未知请留空')).not.toBeInTheDocument();
    expect(screen.getAllByText('未公布请选「无分值（仅阶段结果）」')).toHaveLength(2);
    await userEvent.type(screen.getByLabelText('来源说明'), '公示');
    await userEvent.click(screen.getByRole('button', { name: '登记结果' }));
    expect(await screen.findAllByText(/未公布请选「无分值（仅阶段结果）」/)).toHaveLength(2);
    expect(screen.getByText('请填写分值；未公布请选「无分值（仅阶段结果）」')).toBeInTheDocument();
    expect(screen.getByText('请填写满分；未公布请选「无分值（仅阶段结果）」')).toBeInTheDocument();
    expect(posted).toBe(0);
  });

  it('来源资料只列“官方结果”用途的文件；没有时给出到资料上传的提示', async () => {
    backend({
      files: [
        fileVersion('ver-o', 'official_result', '成绩公示.pdf'),
        fileVersion('ver-x', 'other', '杂项.pdf'),
        fileVersion('ver-b', 'body', '技术标.pdf'),
      ],
    });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    const sel = await screen.findByLabelText('来源资料（选填）');
    await waitFor(() => {
      expect(within(sel).getByRole('option', { name: '成绩公示.pdf' })).toBeInTheDocument();
    });
    expect(within(sel).queryByRole('option', { name: '杂项.pdf' })).not.toBeInTheDocument();
    expect(within(sel).queryByRole('option', { name: '技术标.pdf' })).not.toBeInTheDocument();
  });

  it('没有官方结果资料：来源下拉为空，并提示用“官方结果”用途上传', async () => {
    backend({ files: [fileVersion('ver-x', 'other', '杂项.pdf')] });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    expect(await screen.findByText(/还没有官方结果资料/)).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: '“资料”' });
    expect(link).toHaveAttribute('href', '/projects/prj-1/materials');
    expect(screen.getByText(/用“官方结果”用途上传/)).toBeInTheDocument();
    const sel = screen.getByLabelText('来源资料（选填）');
    expect(within(sel).queryByRole('option', { name: '杂项.pdf' })).not.toBeInTheDocument();
  });

  it('“核实来源”只出现在官方来源、未被取代、未核实的记录上；被取代的标“已被取代”', async () => {
    backend({
      files: [fileVersion('ver-o', 'official_result', '成绩公示.pdf')],
      outcomes: [
        // 新记录取代 out-old；out-old 本身是官方来源但已被取代
        outcome({ outcome_id: 'out-new', source_kind: 'official', supersedes: 'out-old' }),
        outcome({ outcome_id: 'out-old', source_kind: 'official' }),
        outcome({ outcome_id: 'out-user', source_kind: 'user_reported' }),
        outcome({
          outcome_id: 'out-ok',
          source_kind: 'official',
          verification_status: 'verified',
        }),
      ],
    });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    const table = await screen.findByRole('table', { name: '已登记的结果' });
    const row = (id: string) => within(table).getByText(shown(id)).closest('tr')!;
    expect(within(row('out-new')).getByRole('button', { name: '核实来源' })).toBeInTheDocument();
    expect(within(row('out-old')).queryByRole('button', { name: '核实来源' })).toBeNull();
    expect(within(row('out-old')).getByText('已被取代')).toBeInTheDocument();
    expect(within(row('out-new')).queryByText('已被取代')).toBeNull();
    expect(within(row('out-user')).queryByRole('button', { name: '核实来源' })).toBeNull();
    expect(within(row('out-ok')).queryByRole('button', { name: '核实来源' })).toBeNull();
  });

  it('更正的原记录下拉不列已被取代的记录；报送结果标注需以官方来源重新登记', async () => {
    backend({
      outcomes: [
        outcome({ outcome_id: 'out-new', supersedes: 'out-old' }),
        outcome({ outcome_id: 'out-old' }),
        outcome({ outcome_id: 'out-other', submission_id: 'sub-2' }),
      ],
    });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    const sel = await screen.findByLabelText('更正的原记录（选填）');
    await waitFor(() => {
      expect(
        within(sel).getByRole('option', { name: new RegExp(shown('out-new')) }),
      ).toBeInTheDocument();
    });
    expect(
      within(sel).queryByRole('option', { name: new RegExp(shown('out-old')) }),
    ).not.toBeInTheDocument();
    expect(
      within(sel).queryByRole('option', { name: new RegExp(shown('out-other')) }),
    ).not.toBeInTheDocument();
    const table = await screen.findByRole('table', { name: '已登记的结果' });
    // 未被取代的报送结果有说明；被取代的 out-old 没有
    const row = (id: string) => within(table).getByText(shown(id)).closest('tr')!;
    expect(within(row('out-new')).getByText('报送结果需以官方来源重新登记')).toBeInTheDocument();
    expect(within(row('out-old')).queryByText('报送结果需以官方来源重新登记')).toBeNull();
  });

  it('核实对话框的来源下拉同样只列官方结果资料', async () => {
    backend({
      files: [
        fileVersion('ver-o', 'official_result', '成绩公示.pdf'),
        fileVersion('ver-x', 'other', '杂项.pdf'),
      ],
      outcomes: [outcome({ outcome_id: 'out-1', source_kind: 'official' })],
    });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    await userEvent.click(await screen.findByRole('button', { name: '核实来源' }));
    const dlg = await screen.findByRole('dialog', { name: '核实官方来源' });
    const sel = within(dlg).getByLabelText('来源资料');
    expect(within(sel).getByRole('option', { name: '成绩公示.pdf' })).toBeInTheDocument();
    expect(within(sel).queryByRole('option', { name: '杂项.pdf' })).not.toBeInTheDocument();
  });

  it('“更正的原记录”只列所选提交下的记录；换提交后清掉已选值', async () => {
    backend({
      outcomes: [
        outcome({ outcome_id: 'out-a', submission_id: 'sub-1' }),
        outcome({ outcome_id: 'out-b', submission_id: 'sub-2' }),
      ],
    });
    renderApp('/projects/prj-1/submit?tab=outcomes');
    const sup = await screen.findByLabelText('更正的原记录（选填）');
    await waitFor(() => {
      expect(
        within(sup).getByRole('option', { name: new RegExp(shown('out-a')) }),
      ).toBeInTheDocument();
    });
    expect(
      within(sup).queryByRole('option', { name: new RegExp(shown('out-b')) }),
    ).not.toBeInTheDocument();
    await userEvent.selectOptions(sup, 'out-a');
    expect(sup).toHaveValue('out-a');
    await userEvent.selectOptions(screen.getByLabelText('关联的实际提交'), 'sub-2');
    expect(sup).toHaveValue('');
    expect(
      within(sup).getByRole('option', { name: new RegExp(shown('out-b')) }),
    ).toBeInTheDocument();
    expect(
      within(sup).queryByRole('option', { name: new RegExp(shown('out-a')) }),
    ).not.toBeInTheDocument();
  });
});
