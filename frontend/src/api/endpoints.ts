import { apiClient, toPage, type ApiClient, type RequestOptions } from './client';
import type {
  AdoptRequest,
  Compliance,
  ConfirmRulesRequest,
  ConfirmRulesResult,
  EffectivityPreview,
  EffectivityPreviewRequest,
  EffectivityRequest,
  FactList,
  FactRequest,
  FactSetResult,
  FileVersion,
  WordStatus,
  Finding,
  InputSnapshot,
  LoginRequest,
  Me,
  Metrics,
  Outcome,
  OutcomeRequest,
  OutcomeVerifyRequest,
  Page,
  PipelineStatus,
  Prediction,
  PricePlan,
  PricePlanRequest,
  PricePlanWithSimulation,
  PriceSimulation,
  Project,
  ProjectCreate,
  ProjectOverview,
  ProjectUpdate,
  RejectRevisionRequest,
  Report,
  Review,
  ReviewRequest,
  ResolveTermRequest,
  Revision,
  RevisionDiff,
  RevisionRequest,
  RuleSet,
  SearchRequest,
  SearchResult,
  Submission,
  SubmissionRequest,
  Task,
  UploadComplete,
  UploadRequest,
  UploadSession,
  EvidenceRef,
} from './types';

type Idem = Pick<RequestOptions, 'idempotencyKey' | 'signal'>;

/** 与 openapi.json 路径一一对应的类型化调用；路径前缀 /api/v1 由客户端添加。 */
export function createEndpoints(c: ApiClient) {
  return {
    auth: {
      login: (b: LoginRequest, o?: Idem) =>
        c.post<Me>('/auth/login', b, { ...o, skipAuthRedirect: true, noCsrf: true }),
      logout: (o?: Idem) => c.post<undefined>('/auth/logout', undefined, o),
      me: (o?: { signal?: AbortSignal }) => c.get<Me>('/me', { ...o, skipAuthRedirect: true }),
    },
    projects: {
      list: (o?: { signal?: AbortSignal }) => c.get<ProjectOverview[]>('/projects', o),
      get: (id: string, o?: { signal?: AbortSignal }) => c.get<Project>(`/projects/${id}`, o),
      create: (b: ProjectCreate, o?: Idem) => c.post<Project>('/projects', b, o),
      update: (id: string, revision: number | string, b: ProjectUpdate, o?: Idem) =>
        c.patch<Project>(`/projects/${id}`, b, { ...o, ifMatch: revision }),
    },
    files: {
      adoptWordPdf: (
        versionId: string,
        body: { link_id: string; reason: string; reviewed_pdf: boolean },
        o?: Idem,
      ) => c.post<WordStatus>(`/files/${versionId}/word:adopt`, body, o),
      retryWord: (versionId: string, o?: Idem) =>
        c.post<WordStatus>(`/files/${versionId}/word:retry`, {}, o),
      list: async (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<FileVersion[]>(`/projects/${projectId}/files`, o),
      /** PDF.js 直接读取此地址（同源 cookie 鉴权，Range）。 */
      contentUrl: (versionId: string) => c.url(`/files/${versionId}/content`),
    },
    uploads: {
      init: (projectId: string, b: UploadRequest, o?: Idem) =>
        c.post<UploadSession>(`/projects/${projectId}/uploads`, b, o),
      refreshUrls: (uploadId: string, o?: Idem) =>
        c.post<UploadSession>(`/uploads/${uploadId}/urls`, undefined, o),
      complete: (uploadId: string, b: UploadComplete, o?: Idem) =>
        c.post<FileVersion>(`/uploads/${uploadId}/complete`, b, o),
    },
    snapshots: {
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<InputSnapshot[]>(`/projects/${projectId}/snapshots`, o),
      get: (id: string) => c.get<InputSnapshot>(`/snapshots/${id}`),
    },
    rules: {
      get: (projectId: string) => c.get<RuleSet>(`/projects/${projectId}/rules`),
      resolveTerm: (projectId: string, b: ResolveTermRequest, o?: Idem) =>
        c.post<RuleSet>(`/projects/${projectId}/rules/terms:resolve`, b, o),
      previewEffectivity: (projectId: string, b: EffectivityPreviewRequest) =>
        c.post<EffectivityPreview>(`/projects/${projectId}/rules/effectivity:preview`, b),
      decideEffectivity: (projectId: string, b: EffectivityRequest, o?: Idem) =>
        c.post<RuleSet>(`/projects/${projectId}/rules/effectivity:decide`, b, o),
      sourceEvidence: (projectId: string, versionId: string, query = '') =>
        c.get<EvidenceRef[]>(`/projects/${projectId}/rules/source-evidence/${versionId}`, {
          query: { query },
        }),
      review: (ruleId: string, b: ReviewRequest, o?: Idem) =>
        c.post<Review>(`/rules/${ruleId}/reviews`, b, o),
      /** 一次确认多条未审核的规则（按原文接受）；已有决定的不受影响。 */
      confirmPending: (projectId: string, b: ConfirmRulesRequest, o?: Idem) =>
        c.post<ConfirmRulesResult>(`/projects/${projectId}/rules:confirm`, b, o),
    },
    findings: {
      list: async (
        projectId: string,
        q: {
          cursor?: string | null;
          limit?: number;
          snapshotId?: string | null;
          status?: string | null;
          category?: string | null;
        } = {},
      ): Promise<Page<Finding>> =>
        toPage(
          await c.get<{ items: Finding[]; next_cursor: string | null }>(
            `/projects/${projectId}/findings`,
            {
              query: {
                cursor: q.cursor,
                limit: q.limit ?? 25,
                snapshot_id: q.snapshotId,
                status: q.status,
                category: q.category,
              },
            },
          ),
        ),
      get: (id: string) => c.get<Finding>(`/findings/${id}`),
      review: (id: string, b: ReviewRequest, o?: Idem) =>
        c.post<Review>(`/findings/${id}/reviews`, b, o),
    },
    evidence: {
      get: (id: string) => c.get<EvidenceRef>(`/evidence/${id}`),
      /** [差异] 任务书写作 /projects/{id}/evidence/search；openapi 实际为 /projects/{id}/search。 */
      search: (projectId: string, b: SearchRequest, o?: Idem) =>
        c.post<SearchResult>(`/projects/${projectId}/search`, b, o),
    },
    pipeline: {
      get: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<PipelineStatus>(`/projects/${projectId}/pipeline`, o),
      /** 重新评审：基于最新资料、规则与事实再走一遍；202 返回新的流水线状态。 */
      restart: (projectId: string, o?: Idem) =>
        c.post<PipelineStatus>(`/projects/${projectId}/analysis`, undefined, o),
    },
    report: {
      /** 还没有完成的评审时 404 report_not_ready。 */
      get: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<Report>(`/projects/${projectId}/report`, o),
      compliance: (projectId: string, snapshotId?: string, o?: { signal?: AbortSignal }) =>
        c.get<Compliance>(`/projects/${projectId}/compliance`, {
          ...o,
          query: { snapshot_id: snapshotId },
        }),
      /** 没有预测时返回 null。 */
      prediction: (projectId: string, snapshotId?: string, o?: { signal?: AbortSignal }) =>
        c.get<Prediction | null>(`/projects/${projectId}/prediction`, {
          ...o,
          query: { snapshot_id: snapshotId },
        }),
      /** 下载链接：同源 cookie 鉴权，浏览器直接下载，不经 fetch。 */
      docxUrl: (projectId: string) => c.url(`/projects/${projectId}/report.docx`),
      annotatedPdfUrl: (projectId: string) => c.url(`/projects/${projectId}/body.annotated.pdf`),
    },
    price: {
      /** 还没有保存过报价方案时返回 null。 */
      get: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<PricePlanWithSimulation | null>(`/projects/${projectId}/price`, o),
      /** 每次保存追加一个版本。 */
      save: (projectId: string, b: PricePlanRequest, o?: Idem) =>
        c.put<PricePlanWithSimulation>(`/projects/${projectId}/price`, b, o),
      /** 不保存，只按给定参数试算。 */
      simulate: (projectId: string, b: PricePlanRequest, o?: Idem) =>
        c.post<PriceSimulation>(`/projects/${projectId}/price:simulate`, b, o),
      history: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<PricePlan[]>(`/projects/${projectId}/price/history`, o),
    },
    metrics: {
      get: (o?: { signal?: AbortSignal }) => c.get<Metrics>('/metrics', o),
    },
    tasks: {
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<Task[]>(`/projects/${projectId}/tasks`, o),
      get: (id: string) => c.get<Task>(`/tasks/${id}`),
      eventsUrl: (id: string) => c.url(`/tasks/${id}/events`),
      cancel: (id: string, o?: Idem) => c.post<Task>(`/tasks/${id}/cancel`, undefined, o),
      retry: (id: string, o?: Idem) => c.post<Task>(`/tasks/${id}/retry`, undefined, o),
    },
    revisions: {
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<Revision[]>(`/projects/${projectId}/revisions`, o),
      /** 差异正文：逐条原文、替换文与被丢弃的候选。 */
      diff: (id: string, o?: { signal?: AbortSignal }) =>
        c.get<RevisionDiff>(`/revisions/${id}/diff`, o),
      /** 202 返回任务（不是 Revision）；完成后用 list 查询建议。 */
      propose: (projectId: string, b: RevisionRequest, o?: Idem) =>
        c.post<Task>(`/projects/${projectId}/revisions`, b, o),
      adopt: (id: string, b: AdoptRequest, o?: Idem) =>
        c.post<Revision>(`/revisions/${id}/adopt`, b, o),
      reject: (id: string, b: RejectRevisionRequest, o?: Idem) =>
        c.post<Revision>(`/revisions/${id}/reject`, b, o),
    },
    facts: {
      /** 当前（最新）事实集；每次 add 都会生成新事实集，条目 ID 随之更换。 */
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<FactList>(`/projects/${projectId}/facts`, o),
      add: (projectId: string, b: FactRequest, o?: Idem) =>
        c.post<FactSetResult>(`/projects/${projectId}/facts`, b, o),
      withdraw: (projectId: string, factId: string, b: { reason: string }, o?: Idem) =>
        c.post<FactSetResult>(`/projects/${projectId}/facts/${factId}/withdraw`, b, o),
    },
    submissions: {
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<Submission[]>(`/projects/${projectId}/submissions`, o),
      create: (projectId: string, b: SubmissionRequest, o?: Idem) =>
        c.post<Submission>(`/projects/${projectId}/submissions`, b, o),
    },
    outcomes: {
      list: (projectId: string, o?: { signal?: AbortSignal }) =>
        c.get<Outcome[]>(`/projects/${projectId}/outcomes`, o),
      create: (projectId: string, b: OutcomeRequest, o?: Idem) =>
        c.post<Outcome>(`/projects/${projectId}/outcomes`, b, o),
      verify: (id: string, b: OutcomeVerifyRequest, o?: Idem) =>
        c.post<Outcome>(`/outcomes/${id}/verify`, b, o),
    },
  };
}

export type Api = ReturnType<typeof createEndpoints>;
export const api: Api = createEndpoints(apiClient);
