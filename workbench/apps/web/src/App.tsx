import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { FormEvent } from "react";
import { api, setAuth, supportsApi } from "./api";
import type { AuthView, Bid, BidPage } from "./contracts";
import { Badge, Brand, ErrorNotice, Icon, Loading } from "./components";
import { NavigationGuardContext } from "./navigationGuard";
import type { NavigationGuard } from "./navigationGuard";
import { clearAuthoringStorage } from "./editorStorage";
import { clearKnowledgeStorage } from "./knowledgeStorage";
import { clearRecordedCommands } from "./useRecordedCommand";
import { ProjectWorkspace } from "./ProjectWorkspace";
import { Archives } from "./Archives";
import { Research } from "./Research";
const AssistantHub = lazy(() =>
  import("./AssistantWorkspace").then((module) => ({
    default: module.AssistantHub,
  })),
);
const Metrics = lazy(() =>
  import("./Metrics").then((module) => ({ default: module.Metrics })),
);
const Knowledge = lazy(() =>
  import("./Knowledge").then((module) => ({ default: module.Knowledge })),
);
import { CreateIdentityForm } from "./Identity";
import type { WorkspacePage } from "./workspaceTypes";

function projectFromPath(pathname: string) {
  return pathname.match(/^\/bids\/([^/]+)/)?.[1] ?? null;
}

export function App() {
  const [auth, updateAuth] = useState<AuthView | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [expired, setExpired] = useState(false);
  const [route, setRoute] = useState(
    () => window.location.pathname + window.location.search,
  );
  const routeRef = useRef(route);
  routeRef.current = route;
  const navigationGuard = useRef<NavigationGuard | null>(null);
  const navigating = useRef(false);
  const registerGuard = useCallback((guard: NavigationGuard) => {
    navigationGuard.current = guard;
    return () => {
      if (navigationGuard.current === guard) navigationGuard.current = null;
    };
  }, []);
  const projectId = projectFromPath(route.split("?")[0]);
  const area =
    route.split("?")[0] === "/assistant"
      ? "assistant"
      : route.split("?")[0] === "/history"
        ? "history"
        : route.split("?")[0] === "/research"
          ? "research"
          : route.split("?")[0] === "/metrics"
            ? "metrics"
            : route.split("?")[0] === "/knowledge"
              ? "knowledge"
              : "projects";
  const openArea = async (
    value: "history" | "research" | "knowledge" | "metrics" | "assistant",
    itemId?: string,
  ) => {
    if (navigating.current) return;
    navigating.current = true;
    try {
      if (navigationGuard.current && !(await navigationGuard.current())) return;
      const path = `/${value}${itemId ? `?item=${encodeURIComponent(itemId)}` : ""}`;
      window.history.pushState({}, "", path);
      setRoute(path);
    } finally {
      navigating.current = false;
    }
  };
  const navigate = useCallback(
    async (
      id: string | null,
      page?: WorkspacePage,
      reviewId?: string,
      draftId?: string,
    ) => {
      if (navigating.current) return;
      navigating.current = true;
      try {
        if (navigationGuard.current && !(await navigationGuard.current()))
          return;
        const query = new URLSearchParams();
        if (reviewId) query.set("review", reviewId);
        if (draftId) query.set("draft", draftId);
        const path = id
          ? `/bids/${id}${page ? `/${page}` : ""}${query.size ? `?${query}` : ""}`
          : "/projects";
        window.history.pushState({}, "", path);
        setRoute(path);
      } finally {
        navigating.current = false;
      }
    },
    [],
  );
  const loggedIn = useCallback((value: AuthView) => {
    setAuth(value);
    clearAuthoringStorage(value.member.id);
    clearKnowledgeStorage(value.member.id);
    clearRecordedCommands(value.member.id);
    updateAuth(value);
    setExpired(false);
  }, []);
  useEffect(() => {
    let active = true;
    api<AuthView>("/auth/session")
      .then(({ data }) => {
        if (active) loggedIn(data);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setRestoring(false);
      });
    const sessionExpired = () => setExpired(true);
    const pop = () => {
      const target = window.location.pathname + window.location.search;
      if (!navigationGuard.current) {
        setRoute(target);
        return;
      }
      window.history.replaceState({}, "", routeRef.current);
      void navigationGuard
        .current()
        .then((allowed) => {
          if (allowed) {
            window.history.replaceState({}, "", target);
            setRoute(target);
          }
        })
        .catch(() => {});
    };
    window.addEventListener("session-expired", sessionExpired);
    window.addEventListener("popstate", pop);
    return () => {
      active = false;
      window.removeEventListener("session-expired", sessionExpired);
      window.removeEventListener("popstate", pop);
    };
  }, [loggedIn]);
  if (restoring)
    return (
      <div className="startup">
        <Brand />
        <Loading text="正在恢复工作区…" />
      </div>
    );
  if (!auth) return <Login onLogin={loggedIn} />;
  return (
    <NavigationGuardContext.Provider value={registerGuard}>
      <div className="app-shell">
        <a className="skip-link" href="#main-content">
          跳到主要内容
        </a>
        <aside className="sidebar" inert={expired} aria-hidden={expired}>
          <Brand />
          <div className="workspace-name">
            <span className="workspace-avatar">标</span>
            <span>
              标书工作区<small>内部协作空间</small>
            </span>
          </div>
          <p className="nav-label">投标工作</p>
          <nav aria-label="主导航">
            <button
              className={`nav-item${area === "projects" ? " active" : ""}`}
              onClick={() => navigate(null)}
            >
              <Icon name="briefcase" />
              投标项目
            </button>
            <button
              className={`nav-item${area === "history" ? " active" : ""}`}
              onClick={() => void openArea("history")}
            >
              <Icon name="archive" />
              项目档案
            </button>
            <button
              className={`nav-item${area === "research" ? " active" : ""}`}
              onClick={() => void openArea("research")}
            >
              <Icon name="flask" />
              评分研究
            </button>
            {supportsApi("GET", "/knowledge") && (
              <button
                className={`nav-item${area === "knowledge" ? " active" : ""}`}
                onClick={() => void openArea("knowledge")}
              >
                <Icon name="book" />
                企业知识
              </button>
            )}
            {supportsApi("GET", "/metrics") && (
              <button
                className={`nav-item${area === "metrics" ? " active" : ""}`}
                onClick={() => void openArea("metrics")}
              >
                <Icon name="chart" />
                业务结果与指标
              </button>
            )}
            {supportsApi("GET", "/assistant/global-conversations/main") && (
              <button
                className={`nav-item${area === "assistant" ? " active" : ""}`}
                onClick={() => void openArea("assistant")}
              >
                <Icon name="assistant" />
                工作助手
              </button>
            )}
          </nav>
          <div className="sidebar-bottom">
            <div className="privacy-note">
              <span className="secure-dot" />
              资料在私有工作区保存
            </div>
            <div className="account">
              <span className="avatar">
                {auth.member.display_name.slice(0, 1)}
              </span>
              <span>
                {auth.member.display_name}
                <small>已登录成员</small>
              </span>
              <Logout
                beforeLogout={() =>
                  navigationGuard.current?.() ?? Promise.resolve(true)
                }
                onLogout={() => {
                  clearAuthoringStorage();
                  clearKnowledgeStorage();
                  clearRecordedCommands();
                  updateAuth(null);
                  setExpired(false);
                }}
              />
            </div>
          </div>
        </aside>
        <div className="workspace" inert={expired} aria-hidden={expired}>
          <header className="topbar">
            <span>
              投标工作 <span className="breadcrumb-separator">/</span>{" "}
              <strong>
                {area === "assistant"
                  ? "工作助手"
                  : area === "history"
                    ? "项目档案"
                    : area === "research"
                      ? "评分研究"
                      : area === "metrics"
                        ? "业务结果与指标"
                        : area === "knowledge"
                          ? "企业知识"
                          : "投标项目"}
              </strong>
            </span>
            <select
              className="mobile-area-picker"
              aria-label="切换工作区"
              value={area}
              onChange={(event) => {
                const value = event.target.value;
                if (
                  value === "history" ||
                  value === "research" ||
                  value === "knowledge" ||
                  value === "metrics" ||
                  value === "assistant"
                )
                  void openArea(value);
                else void navigate(null);
              }}
            >
              {supportsApi("GET", "/metrics") && (
                <option value="metrics">业务结果与指标</option>
              )}
              {supportsApi("GET", "/assistant/global-conversations/main") && (
                <option value="assistant">工作助手</option>
              )}
              <option value="projects">投标项目</option>
              <option value="history">项目档案</option>
              <option value="research">评分研究</option>
              {supportsApi("GET", "/knowledge") && (
                <option value="knowledge">企业知识</option>
              )}
            </select>
            <span className="environment-label">资料工作区</span>
          </header>
          <main id="main-content">
            {projectId ? (
              <ProjectWorkspace
                key={`${auth.member.id}:${projectId}`}
                id={projectId}
                memberId={auth.member.id}
                route={route}
                onOpenDraft={(draftId) =>
                  void navigate(projectId, "authoring", undefined, draftId)
                }
                onBack={() => navigate(null)}
                onNavigate={(page, reviewId) =>
                  navigate(projectId, page, reviewId)
                }
              />
            ) : area === "assistant" ? (
              <Suspense fallback={<Loading text="正在恢复主会话…" />}>
                <AssistantHub
                  key={`${auth.member.id}:${route}`}
                  memberId={auth.member.id}
                  bidId={new URLSearchParams(route.split("?")[1] ?? "").get(
                    "bid",
                  )}
                />
              </Suspense>
            ) : area === "history" ? (
              <Archives
                key={auth.member.id}
                memberId={auth.member.id}
                onOpen={(id) => void navigate(id, "outcomes")}
              />
            ) : area === "research" ? (
              <Research
                key={auth.member.id}
                onOpen={(id) => void navigate(id, "outcomes")}
              />
            ) : area === "metrics" ? (
              <Suspense fallback={<Loading text="正在打开业务指标…" />}>
                <Metrics key={auth.member.id} />
              </Suspense>
            ) : area === "knowledge" ? (
              <Suspense fallback={<Loading text="正在打开企业知识…" />}>
                <Knowledge
                  key={auth.member.id}
                  memberId={auth.member.id}
                  selectedId={new URLSearchParams(
                    route.split("?")[1] ?? "",
                  ).get("item")}
                  onSelect={(itemId) => void openArea("knowledge", itemId)}
                />
              </Suspense>
            ) : (
              <Projects key={auth.member.id} onOpen={navigate} />
            )}
          </main>
        </div>
        {expired && (
          <div
            className="session-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="重新登录工作区"
          >
            <Login onLogin={loggedIn} expired />
          </div>
        )}
      </div>
    </NavigationGuardContext.Provider>
  );
}

function Login({
  onLogin,
  expired = false,
}: {
  onLogin: (auth: AuthView) => void;
  expired?: boolean;
}) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<AuthView>("/auth/login", {
        method: "POST",
        body: { login_name: name, password },
      });
      onLogin(data);
      setPassword("");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <Brand />
        <div>
          <span className="eyebrow">每一份依据，都有来处</span>
          <h1>
            把精力留给
            <br />
            更好的投标。
          </h1>
          <p>
            从招标资料到投标标书，集中保存原件、版本和解析依据，为有据可查的评审做好准备。
          </p>
          <div className="story-line">
            <Icon name="file" />
            私有资料 · 清晰版本 · 原页依据
          </div>
        </div>
        <small>AI 投标标书工作台</small>
      </div>
      <section className="login-panel">
        <form onSubmit={(event) => void submit(event)} className="login-form">
          <div className="mobile-brand">
            <Brand />
          </div>
          <span className="eyebrow">欢迎回到工作区</span>
          <h2>{expired ? "登录已过期" : "登录投标工作台"}</h2>
          <p className="muted">
            {expired
              ? "当前页面和待处理资料已保留。登录后请核对当前版本，再继续操作。"
              : "使用团队提供的账号，继续你的投标工作。"}
          </p>
          <ErrorNotice error={error} />
          <label>
            账号
            <input
              name="username"
              autoComplete="username"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button className="button primary full" type="submit" disabled={busy}>
            {busy ? "正在登录…" : "登录工作区"}
            <Icon name="arrow" />
          </button>
          <p className="login-help">
            账号由系统维护人员创建。登录后可查看和协作处理工作区项目。
          </p>
        </form>
      </section>
    </div>
  );
}

function Logout({
  onLogout,
  beforeLogout,
}: {
  onLogout: () => void;
  beforeLogout: () => Promise<boolean>;
}) {
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="text-button logout"
      disabled={busy}
      onClick={async () => {
        if (!(await beforeLogout())) return;
        setBusy(true);
        try {
          await api("/auth/logout", { method: "POST" });
          onLogout();
        } catch {
          setError(true);
        } finally {
          setBusy(false);
        }
      }}
      aria-label={error ? "退出失败，重试退出登录" : "退出登录"}
      title={error ? "退出失败，请重试" : "退出登录"}
    >
      {error ? "重试退出" : "退出"}
    </button>
  );
}

function Projects({
  onOpen,
}: {
  onOpen: (id: string, page?: WorkspacePage) => void;
}) {
  const [projects, setProjects] = useState<Bid[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const load = useCallback(async (next?: string) => {
    setError(null);
    try {
      const { data } = await api<BidPage>(
        `/bids${next ? `?cursor=${encodeURIComponent(next)}` : ""}`,
      );
      setProjects((old) =>
        next ? [...(old ?? []), ...data.items] : data.items,
      );
      setCursor(data.has_more ? data.next_cursor : null);
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const visible = projects?.filter((project) =>
    project.title.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <span className="eyebrow">投标工作</span>
          <h1>投标项目</h1>
          <p className="muted">资料、版本与依据，围绕每一个项目集中管理。</p>
        </div>
        <button className="button primary" onClick={() => setCreating(true)}>
          ＋ 新建投标
        </button>
      </div>
      <ErrorNotice error={error} onRetry={() => void load()} />
      <section className="panel create-panel" hidden={!creating}>
        <div className="section-heading">
          <h2>新建投标项目</h2>
          <button className="text-button" onClick={() => setCreating(false)}>
            收起
          </button>
        </div>
        <p className="muted">先起个名称，即可上传招标资料和投标正文。</p>
        <CreateIdentityForm onCreated={(id) => onOpen(id, "materials")} />
      </section>
      <section className="panel project-list">
        <div className="list-toolbar">
          <div className="list-title">
            <h2>全部项目</h2>
            {projects && (
              <span className="count">
                {projects.length}
                {cursor ? "+" : ""}
              </span>
            )}
          </div>
          <label className="search-label">
            <span className="sr-only">搜索已加载项目</span>
            <input
              type="search"
              placeholder="搜索已加载项目…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        {!projects && !error && <Loading />}
        {visible?.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">
              <Icon name="file" />
            </div>
            <h3>{search ? "没有找到匹配项目" : "从一份资料，开始一个项目"}</h3>
            <p>
              {search
                ? "试试其他项目名称。"
                : "只需项目名称。上传PDF后，查看已保存的原件和真实解析范围。"}
            </p>
            {!search && (
              <button
                className="button secondary"
                onClick={() => setCreating(true)}
              >
                新建投标项目
                <Icon name="arrow" />
              </button>
            )}
          </div>
        )}
        {!!visible?.length && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>项目名称</th>
                  <th>工作阶段</th>
                  <th>当前资料</th>
                  <th>下一步</th>
                  <th>
                    <span className="sr-only">打开</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((project) => (
                  <tr key={project.id}>
                    <td>
                      <button
                        className="project-link"
                        onClick={() => onOpen(project.id)}
                      >
                        <span className="document-icon">
                          <Icon name="file" />
                        </span>
                        {project.title}
                      </button>
                      {project.identity && (
                        <p className="small-note project-identity-caption">
                          {project.identity.engineering_title} ·{" "}
                          {project.identity.lot ?? "未注明标段"} · 第
                          {project.identity.round_no}轮<br />
                          {project.identity.bidder_name} ·{" "}
                          {project.identity.binding_status === "confirmed"
                            ? "身份已绑定"
                            : "身份待确认"}
                        </p>
                      )}
                    </td>
                    <td>
                      <Badge>
                        {
                          {
                            preparation: "准备中",
                            working: "工作中",
                            submitted: "已登记提交",
                            closed: "已结项",
                            terminated: "已终止",
                          }[project.phase]
                        }
                      </Badge>
                    </td>
                    <td>资料包 {project.material_revision}</td>
                    <td className="next-action-cell">
                      {project.next_action.reason || "上传并核对资料"}
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`打开${project.title}`}
                        onClick={() => onOpen(project.id)}
                      >
                        <Icon name="arrow" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {cursor && (
          <div className="load-more">
            <button
              className="button secondary"
              onClick={() => void load(cursor)}
            >
              加载更多项目
            </button>
          </div>
        )}
      </section>
      <p className="footnote">
        当前切片提供资料入库与PDF解析。评审、评分及提交能力以项目中的实际可用状态为准。
      </p>
    </div>
  );
}
