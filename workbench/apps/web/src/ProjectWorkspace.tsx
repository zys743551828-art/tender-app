import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { Bid, MaterialView, ReviewStateView } from "./contracts";
import { supportsApi } from "./api";
import { AssistantDrawer } from "./AssistantDrawer";
import { announceWorkspaceAuxiliary } from "./workspaceAuxiliary";
import { Badge, Icon, Loading } from "./components";
const TaskPanel = lazy(() =>
  import("./TaskPanel").then((module) => ({ default: module.TaskPanel })),
);
const AuthoringPanel = lazy(() =>
  import("./AuthoringPanel").then((module) => ({
    default: module.AuthoringPanel,
  })),
);
const SubmissionPanel = lazy(() =>
  import("./SubmissionPanel").then((module) => ({
    default: module.SubmissionPanel,
  })),
);
const ReportPanel = lazy(() =>
  import("./ReportPanel").then((module) => ({ default: module.ReportPanel })),
);
const PricingPanel = lazy(() =>
  import("./PricingPanel").then((module) => ({ default: module.PricingPanel })),
);
import { OutcomesPanel } from "./Archives";
import { FactsPanel } from "./FactsPanel";
import { MatrixPanel } from "./MatrixPanel";
import { OperationCenter } from "./OperationCenter";
import { ReviewProgress } from "./ReviewProgress";
import { ReviewHistory } from "./ReviewHistory";
import { RetrievalDrawer } from "./RetrievalDrawer";
import { Project } from "./Project";
import { ResourceState } from "./ResourceState";
import { ReviewPanel } from "./ReviewPanel";
import { RulesPanel } from "./RulesPanel";
import { SettingsPanel } from "./SettingsPanel";
import { IdentityPanel } from "./Identity";
import { useResource } from "./useResource";
import { useProjectStream } from "./useProjectStream";
import { actionTarget } from "./workspaceTypes";
import { NextActionControl } from "./NextActionControl";
import { WorkspaceNavigation } from "./WorkspaceNavigation";
import { parseWorkspacePage, workspacePages } from "./workspaceTypes";
import type { WorkspacePage } from "./workspaceTypes";
import { PackageOverviewNextStep } from "./PackageOverviewNextStep";
import { PackageNavigationWorkspace } from "./PackageNavigationWorkspace";
import {
  packageLocation,
  parsePackageLocation,
  type PackageNavigationTarget,
} from "./packageNavigation";

export function ProjectWorkspace({
  id,
  route,
  memberId = "",
  onOpenDraft,
  onOpenPackage,
  onPackageLocation,
  onOpenKnowledge,
  onBack,
  onNavigate,
}: {
  id: string;
  route: string;
  memberId?: string;
  onOpenDraft?: (id: string) => void;
  onOpenPackage?: (target: PackageNavigationTarget | null) => void;
  onPackageLocation?: (
    target: PackageNavigationTarget | null,
    replace?: boolean,
  ) => void;
  onOpenKnowledge?: (knowledgeId: string) => void;
  onBack: () => void;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
}) {
  const [retrievalOpen, setRetrievalOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const closeAssistant = useCallback(() => setAssistantOpen(false), []);
  const closeRetrieval = useCallback(() => setRetrievalOpen(false), []);
  const resource = useResource<Bid>(`/bids/${id}`, 5000);
  const bid = resource.data;
  useProjectStream(bid?.id === id ? bid.stream_id : undefined, id);
  const reviewState = useResource<ReviewStateView>(
    `/bids/${id}/review-state`,
    3000,
  );
  const state = reviewState.data?.bid_id === id ? reviewState.data : undefined;
  const stateError =
    reviewState.error ??
    (reviewState.data && !state
      ? new Error("评审进度项目身份不一致，请刷新核对。")
      : undefined);
  const statePending = !reviewState.unavailable && (!state || !!stateError);
  const refresh = () => {
    void resource.reload();
    void reviewState.reload();
  };
  const defaultReview =
    state?.request?.review_id ??
    state?.current_review?.id ??
    bid?.current_review_id;

  const page = parseWorkspacePage(route.split("?")[0]);
  const explicitReview = new URLSearchParams(route.split("?")[1] ?? "").get(
    "review",
  );
  useEffect(() => {
    if (page === "home" && bid) {
      let saved: WorkspacePage | null = null;
      let savedReview: string | undefined;
      let savedPackage: PackageNavigationTarget | null = null;
      try {
        const value = localStorage.getItem(`tender:position:${id}`);
        if (value) {
          const position = JSON.parse(value) as {
            page: string;
            reviewId?: string;
            packageTarget?: PackageNavigationTarget | null;
          };
          if (workspacePages.some(([key]) => key === position.page)) {
            saved = position.page as WorkspacePage;
            savedReview = position.reviewId;
            if (saved === "packages" && position.packageTarget) {
              try {
                const parsed = parsePackageLocation(
                  packageLocation(id, position.packageTarget),
                );
                if (parsed.ok) savedPackage = parsed.target;
                else saved = "overview";
              } catch {
                saved = "overview";
              }
            }
          }
        }
      } catch {
        /* Browser preferences do not establish a business state. */
      }
      if (saved === "packages" && onOpenPackage) onOpenPackage(savedPackage);
      else onNavigate(saved ?? "overview", savedReview);
    } else if (page !== "home") {
      const packagePosition =
        page === "packages" ? parsePackageLocation(route) : null;
      if (packagePosition && !packagePosition.ok) return;
      try {
        localStorage.setItem(
          `tender:position:${id}`,
          JSON.stringify({
            page,
            reviewId: explicitReview ?? undefined,
            ...(packagePosition?.ok
              ? { packageTarget: packagePosition.target }
              : {}),
          }),
        );
      } catch {
        /* A navigation preference cannot block the current workspace. */
      }
    }
  }, [
    page,
    bid,
    id,
    onNavigate,
    explicitReview,
    reviewState.loading,
    state,
    defaultReview,
    route,
    onOpenPackage,
  ]);
  const nav =
    page === "home" ? null : (
      <div className="workspace-nav-tools">
        <WorkspaceNavigation bidId={id} page={page} onNavigate={onNavigate} />
        {supportsApi("GET", `/bids/${id}/conversations/main`) && (
          <button
            className="button secondary"
            onClick={() => {
              setRetrievalOpen(false);
              announceWorkspaceAuxiliary(id, "assistant");
              setAssistantOpen(true);
            }}
          >
            项目助手
          </button>
        )}
        <button
          className="button secondary"
          onClick={() => {
            setAssistantOpen(false);
            announceWorkspaceAuxiliary(id, "sources");
            setRetrievalOpen(true);
          }}
        >
          查证资料
        </button>
      </div>
    );
  const retrieval = (
    <>
      {assistantOpen && (
        <AssistantDrawer
          bidId={id}
          memberId={memberId}
          onClose={closeAssistant}
          dockTargetId="main-content"
        />
      )}
      {retrievalOpen && (
        <RetrievalDrawer
          bidId={id}
          title={bid?.title ?? "当前项目"}
          onClose={closeRetrieval}
        />
      )}
    </>
  );
  const progress = (
    <ReviewProgress
      state={state}
      etag={reviewState.etag}
      loading={reviewState.loading}
      error={stateError}
      unavailable={reviewState.unavailable}
      onRetry={refresh}
      onNavigate={onNavigate}
    />
  );
  if (page === "materials")
    return (
      <>
        <Project
          id={id}
          memberId={memberId}
          onBack={onBack}
          onAuthoring={() => onNavigate("authoring")}
          onPackages={() => onNavigate("packages")}
          navigation={nav}
          reviewNotice={
            <>
              {(state?.request || stateError) && (
                <details>
                  <summary>单稿处理记录</summary>
                  {progress}
                </details>
              )}
              <div className="notice neutral">
                <div>
                  <strong>原件入库后明确选择整包修订</strong>
                  <p>
                    解析完成不表示核心规则已满足。进入整包核查工作面选择确切包、要求清单和输入；已有单稿历史与原件继续保留。
                  </p>
                  <button
                    className="text-button"
                    onClick={() => onNavigate("packages")}
                  >
                    选择整包继续核查
                  </button>
                </div>
              </div>
            </>
          }
        />
        {retrieval}
      </>
    );
  if (!bid && resource.loading) return <Loading text="正在恢复项目工作区…" />;
  const reviewId = explicitReview ?? defaultReview ?? null;
  const viewingOtherReview =
    explicitReview &&
    explicitReview !== state?.request?.review_id &&
    explicitReview !== state?.current_review?.id;
  return (
    <div
      className={`page-content project-page${page === "authoring" ? " project-page--authoring" : ""}`}
    >
      <button className="back-link" onClick={onBack}>
        <Icon name="back" />
        返回项目列表
      </button>
      <div className="page-heading">
        <div>
          <span className="eyebrow">项目工作区</span>
          <h1>{bid?.title ?? "项目暂时无法读取"}</h1>
          {bid && (
            <div className="project-meta">
              <Badge>
                {
                  {
                    preparation: "准备资料",
                    working: "工作中",
                    submitted: "已登记提交",
                    closed: "已结项",
                    terminated: "已终止",
                  }[bid.phase]
                }
              </Badge>
              <span>资料修订 {bid.material_revision}</span>
              {explicitReview && <span>正在查看指定历史轮次</span>}
            </div>
          )}
        </div>
        {bid && (
          <button
            className="button secondary"
            onClick={() => onNavigate("materials")}
          >
            <Icon name="upload" />
            上传新版资料
          </button>
        )}
      </div>
      <ResourceState
        {...resource}
        hasData={!!bid}
        onRetry={() => void resource.reload()}
      />
      {nav}
      {retrieval}
      {!viewingOtherReview &&
        ["review", "matrix", "operations"].includes(page) &&
        progress}
      {bid && (
        <>
          {page === "overview" &&
            bid.identity?.binding_status === "pending" && (
              <div className="notice warning">
                <div>
                  <strong>投标主体待有据确认</strong>
                  <p>
                    资料可以继续保存；需要可靠身份的知识选用和结果核验仍受限制。
                  </p>
                  <button
                    className="text-button"
                    onClick={() => onNavigate("settings")}
                  >
                    确认本项目投标主体
                  </button>
                </div>
              </div>
            )}
          {page === "tasks" && (
            <Suspense fallback={<Loading text="正在恢复可复用任务…" />}>
              <TaskPanel bidId={id} memberId={memberId} />
            </Suspense>
          )}
          {page === "overview" && (
            <Overview
              bid={bid}
              onNavigate={onNavigate}
              onOpenPackage={onOpenPackage ?? (() => onNavigate("packages"))}
            />
          )}
          {page === "packages" && (
            <PackageNavigationWorkspace
              key={`${id}:${memberId}`}
              bidId={id}
              memberId={memberId}
              route={route}
              disabled={
                !!bid.archived_at ||
                bid.phase === "closed" ||
                bid.phase === "terminated"
              }
              onLocation={onPackageLocation ?? (() => onNavigate("packages"))}
              onReset={() => onNavigate("packages")}
            />
          )}
          {page === "review" && (
            <ReviewPanel
              key={reviewId ?? "none"}
              bid={bid}
              reviewId={reviewId}
              onNavigate={onNavigate}
              onChanged={refresh}
              reviewState={state}
              statePending={statePending}
            />
          )}
          {page === "review" && reviewId && (
            <Suspense fallback={<Loading text="正在读取此轮报告…" />}>
              <ReportPanel
                key={reviewId}
                bidId={id}
                memberId={memberId}
                reviewId={reviewId}
                projectTitle={bid.title}
              />
            </Suspense>
          )}
          {page === "review" && (
            <ReviewHistory
              key={`${id}:${defaultReview ?? "none"}`}
              bidId={id}
              selectedId={reviewId}
              onOpen={(review) => onNavigate("review", review)}
            />
          )}
          {page === "matrix" && (
            <MatrixPanel
              key={reviewId ?? "none"}
              reviewId={reviewId}
              bidId={bid.id}
            />
          )}
          {page === "authoring" && (
            <Suspense fallback={<Loading text="正在打开章节编制…" />}>
              <AuthoringPanel
                bidId={id}
                memberId={memberId}
                projectTitle={bid.title}
                disabled={
                  !!bid.archived_at ||
                  bid.phase === "closed" ||
                  bid.phase === "terminated"
                }
                onPackages={() => onNavigate("packages")}
                draftId={new URLSearchParams(route.split("?")[1] ?? "").get(
                  "draft",
                )}
                onOpenDraft={onOpenDraft ?? (() => {})}
              />
            </Suspense>
          )}
          {page === "pricing" && (
            <Suspense fallback={<Loading text="正在打开报价情景…" />}>
              <PricingPanel
                bidId={bid.id}
                memberId={memberId}
                onSettings={() => onNavigate("settings")}
              />
            </Suspense>
          )}
          {page === "rules" && <RulesPanel bid={bid} onChanged={refresh} />}
          {page === "facts" && <FactsPanel bid={bid} onChanged={refresh} />}
          {page === "outcomes" && (
            <>
              <Suspense fallback={<Loading text="正在读取提交检查…" />}>
                <SubmissionPanel
                  key={bid.id}
                  bidId={bid.id}
                  memberId={memberId}
                  onNavigate={onNavigate}
                  onChanged={refresh}
                  onOpenKnowledge={onOpenKnowledge}
                />
              </Suspense>
              <OutcomesPanel bidId={bid.id} />
            </>
          )}
          {page === "settings" && (
            <>
              <IdentityPanel key={bid.id} bidId={bid.id} onSaved={refresh} />
              <SettingsPanel
                bidId={bid.id}
                onSaved={() => void resource.reload()}
              />
            </>
          )}
          {page === "operations" && (
            <OperationCenter
              bidId={bid.id}
              currentOperationId={state?.current_review?.operation_id}
              preparationOperationId={state?.request?.prepare_operation_id}
              reviewId={state?.request?.review_id ?? undefined}
            />
          )}
        </>
      )}
    </div>
  );
}

function Overview({
  bid,
  onNavigate,
  onOpenPackage,
}: {
  bid: Bid;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
  onOpenPackage: (target: PackageNavigationTarget | null) => void;
}) {
  const materials = useResource<MaterialView>(
    `/bids/${bid.id}/materials`,
    5000,
  );
  const counts = materials.data?.documents;
  const next = bid.next_action;
  return (
    <div>
      <PackageOverviewNextStep
        bidId={bid.id}
        onOpen={onOpenPackage}
        onMaterials={() => onNavigate("materials")}
      />
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>当前资料</h2>
            <p className="muted">
              核对原件及补遗的实际生效关系，再明确选入资料包；文件数和解析状态不代表整包齐全。
            </p>
          </div>
          <button
            className="text-button"
            onClick={() => onNavigate("materials")}
          >
            打开资料工作面
          </button>
        </div>
        <ResourceState
          {...materials}
          hasData={!!materials.data}
          onRetry={() => void materials.reload()}
        />
        {counts && (
          <div className="material-overview">
            <article>
              <span>已入库文件</span>
              <strong>{counts.length}</strong>
            </article>
            <article>
              <span>招标与补遗</span>
              <strong>
                {
                  counts.filter(
                    (document) =>
                      document.role === "tender" ||
                      document.role === "supplement",
                  ).length
                }
              </strong>
            </article>
            <article>
              <span>投标正文</span>
              <strong>
                {counts.filter((document) => document.role === "body").length}
              </strong>
            </article>
            <article>
              <span>解析缺口或待处理</span>
              <strong>
                {
                  counts.filter(
                    (document) => document.parse_coverage !== "complete",
                  ).length
                }
              </strong>
            </article>
          </div>
        )}
        {materials.data?.conflicts.map((conflict, index) => (
          <div className="notice warning" key={index}>
            {conflict}
          </div>
        ))}
      </section>
      <section className="panel">
        <details className="package-legacy-entry">
          <summary>单稿评审历史与原流程</summary>
          <p className="small-note">
            以下建议来自单稿业务记录，不代表整包清单或整包核查的当前进度。原轮次、风险和原件继续可查。
          </p>
          <p>{next.reason}</p>
          {actionTarget(bid.id, next) && (
            <NextActionControl
              bidId={bid.id}
              action={next}
              onNavigate={onNavigate}
            />
          )}
          {bid.current_review_id && (
            <div>
              <div className="section-heading">
                <div>
                  <h2>已有可读取的单稿轮次</h2>
                  <p className="muted">
                    打开风险、分层覆盖及对应原页，确认本轮是否仍属于当前资料。
                  </p>
                </div>
                <button
                  className="button primary"
                  onClick={() => onNavigate("review", bid.current_review_id!)}
                >
                  打开此单稿轮次
                </button>
              </div>
            </div>
          )}
          <button
            type="button"
            className="text-button"
            onClick={() => onNavigate("review")}
          >
            查看单稿评审历史工作面
          </button>
        </details>
      </section>
    </div>
  );
}
