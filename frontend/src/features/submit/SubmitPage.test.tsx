import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Report } from '../../api/types';
import {
  fileVersion,
  pipeline,
  report,
  snapshot,
  submission,
  verdictRow,
  compliance,
} from '../../test/fixtures';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

type Cat = Report['categories'][number];

function cats(over: Partial<Record<Cat['category'], number>> = {}): Cat[] {
  return (['disqualification', 'response', 'consistency', 'scope', 'improvement'] as const).map(
    (category) => ({
      category,
      total: over[category] ?? 0,
      open: over[category] ?? 0,
      resolved: 0,
    }),
  );
}

function backend(
  subs: ReturnType<typeof submission>[],
  o: {
    report?: Report | null;
    pipelineOver?: Parameters<typeof pipeline>[0];
  } = {},
) {
  const rep = o.report === undefined ? report({ categories: cats(), prediction: null }) : o.report;
  server.use(
    http.get('/api/v1/projects/prj-1/pipeline', () => HttpResponse.json(pipeline(o.pipelineOver))),
    http.get('/api/v1/projects/prj-1/report', () =>
      rep
        ? HttpResponse.json(rep)
        : HttpResponse.json(apiError('report_not_ready', '还没有完成的评审'), { status: 404 }),
    ),
    http.get('/api/v1/projects/prj-1/files', () =>
      HttpResponse.json([
        fileVersion('ver-t', 'tender', '招标文件.pdf'),
        fileVersion('ver-b', 'body', '技术标.pdf'),
      ]),
    ),
    http.get('/api/v1/snapshots/snp-1', () => HttpResponse.json(snapshot())),
    http.get('/api/v1/projects/prj-1/submissions', () => HttpResponse.json(subs)),
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
  );
}

async function fillAndSubmit(user = userEvent) {
  const at = await screen.findByLabelText('实际提交时间');
  await user.clear(at);
  await user.type(at, '2026-10-05T10:00');
  await user.click(screen.getByRole('button', { name: '登记提交' }));
}

describe('提交与结果页：登记前的检查', () => {
  it('全部通过：直接显示登记表单，提交时间默认填好当前时间', async () => {
    backend([]);
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByRole('button', { name: '登记提交' })).toBeEnabled();
    expect(screen.getByLabelText('实际提交时间')).not.toHaveValue('');
  });

  it('可能导致否决的问题没处理完：该项未通过并给出“处理问题”，不显示登记表单', async () => {
    backend([], { report: report({ categories: cats({ disqualification: 1, response: 1 }) }) });
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByText('还有 2 个没有处理。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '处理问题' })).toHaveAttribute(
      'href',
      '/projects/prj-1/findings?category=disqualification',
    );
    expect(screen.getByText('上面 1 项处理好后，就可以在这里登记。')).toBeInTheDocument();
    expect(screen.queryByLabelText('实际提交时间')).not.toBeInTheDocument();
  });
  it('废标／否决／强制类规则未确认：该项未通过并链接到依据页', async () => {
    const rows = [verdictRow({ kind: 'disqualification', rule_basis: 'unconfirmed' })];
    backend([], { report: report({ qualification: compliance(rows), categories: cats() }) });
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByText('还有 1 条没有核对。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '确认规则' })).toHaveAttribute(
      'href',
      '/projects/prj-1/basis',
    );
  });

  it('评分条款的规则未确认不挡提交', async () => {
    const rows = [verdictRow({ kind: 'scoring', rule_basis: 'unconfirmed' })];
    backend([], { report: report({ qualification: compliance(rows), categories: cats() }) });
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByRole('button', { name: '登记提交' })).toBeInTheDocument();
  });

  it('项目设置为规则按原文接受时，未核对的废标／强制类规则不挡提交', async () => {
    const rows = [verdictRow({ kind: 'disqualification', rule_basis: 'unconfirmed' })];
    backend([], { report: report({ qualification: compliance(rows), categories: cats() }) });
    server.use(
      http.get('/api/v1/projects/prj-1', () =>
        HttpResponse.json(
          project({ settings: { ...project().settings, accept_rules_as_written: true } }),
        ),
      ),
    );
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByText('废标／强制类规则按原文接受（项目设置）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '登记提交' })).toBeInTheDocument();
  });

  it('资料有更新：说明评审落后于最新输入，并链接到报告', async () => {
    backend([], { pipelineOver: { stale_reasons: ['body_updated'] } });
    renderApp('/projects/prj-1/submit');
    expect(
      await screen.findByText('评审还在进行，或资料、规则有更新，需要重新评审。'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '看报告' })).toHaveAttribute('href', '/projects/prj-1');
  });

  it('没有完成的评审：该项未通过', async () => {
    backend([], { report: null, pipelineOver: { snapshot_id: null, round_no: null } });
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByText('还没有完成的评审。')).toBeInTheDocument();
  });
});

describe('提交与结果页：登记提交', () => {
  it('已登记的提交来自后端列表，并链接到“开标结果”标签', async () => {
    backend([submission()]);
    renderApp('/projects/prj-1/submit');
    const table = await screen.findByRole('table', { name: '已登记的提交' });
    expect(within(table).getByText('技术标.pdf（第 1 版）')).toBeInTheDocument();
    expect(table).not.toHaveTextContent('sub-1'); // 不显示内部编号
    expect(within(table).getByRole('link', { name: '登记结果' })).toHaveAttribute(
      'href',
      '/projects/prj-1/submit?tab=outcomes&submission=sub-1',
    );
  });

  it('请求体符合 SubmissionRequest：正文与输入取最近一轮评审，不让用户另选', async () => {
    backend([]);
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/submissions', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(submission());
      }),
    );
    renderApp('/projects/prj-1/submit');
    const bodyField = await screen.findByLabelText('提交的正文');
    expect(bodyField).toHaveAttribute('readonly');
    await waitFor(() => {
      expect(bodyField).toHaveValue('技术标.pdf（第 1 版）');
    });
    await fillAndSubmit();
    expect(await screen.findByText('已登记实际提交')).toBeInTheDocument();
    expect(body).toMatchObject({
      body_version_id: 'ver-b',
      snapshot_id: 'snp-1',
      receipt_artifact_id: null,
    });
  });

  it('还有未结案的其他问题：必须勾选“已知晓”才能登记', async () => {
    backend([], { report: report({ categories: cats({ consistency: 1, improvement: 1 }) }) });
    let posted = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/submissions', () => {
        posted++;
        return HttpResponse.json(submission());
      }),
    );
    renderApp('/projects/prj-1/submit');
    const ack = await screen.findByRole('checkbox', { name: /还有 2 个影响得分的问题没处理/ });
    await fillAndSubmit();
    expect(await screen.findByText('请先确认你已知晓这些未结案问题')).toBeInTheDocument();
    expect(posted).toBe(0);
    await userEvent.click(ack);
    await userEvent.click(screen.getByRole('button', { name: '登记提交' }));
    expect(await screen.findByText('已登记实际提交')).toBeInTheDocument();
    expect(posted).toBe(1);
  });

  it('没有未结案问题时不出现确认框', async () => {
    backend([]);
    renderApp('/projects/prj-1/submit');
    await screen.findByLabelText('实际提交时间');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('登记成功后重新读取项目', async () => {
    backend([]);
    let projectGets = 0;
    server.use(
      http.get('/api/v1/projects/prj-1', () => {
        projectGets++;
        return HttpResponse.json(project());
      }),
      http.post('/api/v1/projects/prj-1/submissions', () => HttpResponse.json(submission())),
    );
    renderApp('/projects/prj-1/submit');
    await screen.findByLabelText('实际提交时间');
    const before = projectGets;
    await fillAndSubmit();
    await screen.findByText('已登记实际提交');
    await waitFor(() => {
      expect(projectGets).toBeGreaterThan(before);
    });
  });

  it.each([
    [
      'qualification_rules_unconfirmed',
      '还有 2 条废标／否决／强制类规则没有人工确认',
      /请到“依据”页确认或驳回/,
      '废标／否决／强制类规则尚未全部确认',
    ],
    [
      'critical_findings_open',
      '还有 3 个关键或废标／响应类问题未处理完',
      /请到“问题”页确认并修改、驳回或标记已解决/,
      '关键问题或废标／强制响应类问题尚未处理完',
    ],
    ['snapshot_not_latest', '该快照已被更新的快照取代', /请回到“报告”点击“重新评审”/, null],
  ])(
    '409 %s：显示后端消息、补一句下一步并逐项列出未满足的条件',
    async (code, message, hint, item) => {
      backend([]);
      server.use(
        http.post('/api/v1/projects/prj-1/submissions', () =>
          HttpResponse.json(apiError(code, message), { status: 409 }),
        ),
      );
      renderApp('/projects/prj-1/submit');
      await fillAndSubmit();
      const alert = await screen.findByRole('alert');
      expect(within(alert).getByText(message)).toBeInTheDocument();
      expect(within(alert).getByText(hint)).toBeInTheDocument();
      if (item) {
        expect(
          within(screen.getByRole('list', { name: '未满足的提交条件' })).getByText(item),
        ).toBeInTheDocument();
      }
    },
  );

  it('提交时间必填，缺了不发请求', async () => {
    backend([]);
    let posted = false;
    server.use(
      http.post('/api/v1/projects/prj-1/submissions', () => {
        posted = true;
        return HttpResponse.json(submission());
      }),
    );
    renderApp('/projects/prj-1/submit');
    await userEvent.clear(await screen.findByLabelText('实际提交时间'));
    await userEvent.click(screen.getByRole('button', { name: '登记提交' }));
    expect(await screen.findByText('请填写实际提交时间')).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it('还没有登记过提交时给出空状态；“开标结果”标签提示先登记提交', async () => {
    backend([]);
    renderApp('/projects/prj-1/submit');
    expect(await screen.findByText('还没有登记过。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: '开标结果' }));
    expect(await screen.findByText(/先登记提交，开标后再来登记结果/)).toBeInTheDocument();
  });
});
