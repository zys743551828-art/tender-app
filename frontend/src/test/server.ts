import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

/**
 * 页面测试用的假后端（msw）。各用例用 server.use(...) 声明自己需要的接口，优先于这里的默认值。
 * 默认值描述“一个刚建好、什么都还没上传的新项目”：流水线在等资料，没有报告、没有报价方案，
 * 这样页面测试只需声明自己关心的接口。
 */
export const server = setupServer(
  http.get('/api/v1/projects/:id/pipeline', () =>
    HttpResponse.json({
      project_id: 'prj-1',
      stage: 'waiting_materials',
      steps: [
        { key: 'materials', state: 'waiting', task_id: null, message: null },
        { key: 'rules', state: 'waiting', task_id: null, message: null },
        { key: 'review', state: 'waiting', task_id: null, message: null },
        { key: 'prediction', state: 'waiting', task_id: null, message: null },
      ],
      missing: ['tender', 'body'],
      snapshot_id: null,
      round_no: null,
      stale_reasons: [],
      rules_total: 0,
      rules_unconfirmed: 0,
    }),
  ),
  http.get('/api/v1/projects/:id/report', () =>
    HttpResponse.json(
      {
        code: 'report_not_ready',
        message: '还没有完成的评审',
        request_id: 'req-default',
        retryable: false,
        details: {},
      },
      { status: 404 },
    ),
  ),
  http.get('/api/v1/projects/:id/price', () => HttpResponse.json(null)),
  http.get('/api/v1/projects/:id/price/history', () => HttpResponse.json([])),
  http.get('/api/v1/projects/:id/files', () => HttpResponse.json([])),
  http.get('/api/v1/projects/:id/tasks', () => HttpResponse.json([])),
  http.get('/api/v1/projects/:id/rules', () =>
    HttpResponse.json(
      {
        code: 'not_found',
        message: '对象不存在，或你无权访问',
        request_id: 'req-default',
        retryable: false,
        details: {},
      },
      { status: 404 },
    ),
  ),
  http.get('/api/v1/projects/:id/facts', () => HttpResponse.json({ fact_set_id: null, items: [] })),
  http.get('/api/v1/projects/:id/snapshots', () => HttpResponse.json([])),
  http.get('/api/v1/projects/:id/submissions', () => HttpResponse.json([])),
  http.get('/api/v1/projects/:id/findings', () =>
    HttpResponse.json({ items: [], next_cursor: null }),
  ),
  http.get('/api/v1/projects/:id/outcomes', () => HttpResponse.json([])),
);
