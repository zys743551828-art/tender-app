import { useState } from "react";
import { api } from "./api";
import type {
  ResearchHistoryPage,
  ResearchOutcomePage,
  ResearchOutcomeView,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

export function Archives({ onOpen }: { onOpen: (id: string) => void }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const path = `/history?q=${encodeURIComponent(query)}`;
  const history = useResource<ResearchHistoryPage>(path);
  const [more, setMore] = useState<
    { query: string; page: ResearchHistoryPage }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const pages = more
    .filter((page) => page.query === query)
    .map((page) => page.page);
  const last = pages.at(-1) ?? history.data;
  const items = [
    ...new Map(
      [
        ...(history.data?.items ?? []),
        ...pages.flatMap((page) => page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  async function next() {
    if (busy || last?.next_offset == null) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<ResearchHistoryPage>(
        `${path}&offset=${last.next_offset}`,
      );
      setMore((old) => [...old, { query, page: data }]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content archives-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">资料与结果留存</span>
          <h1>项目档案</h1>
          <p>回看项目、实交与成绩记录，原件及其版本身份始终保留。</p>
        </div>
        <Badge>只读归档视图</Badge>
      </header>
      <section className="panel">
        <form
          className="archive-search"
          onSubmit={(event) => {
            event.preventDefault();
            setMore([]);
            setQuery(input.trim());
            setError(null);
          }}
        >
          <label>
            查找档案项目
            <input
              value={input}
              maxLength={200}
              onChange={(event) => setInput(event.target.value)}
              placeholder="输入项目名称"
            />
          </label>
          <button className="button secondary" disabled={busy}>
            查找档案
          </button>
        </form>
        <ResourceState
          {...history}
          hasData={!!history.data}
          onRetry={() => void history.reload()}
        />
        <ErrorNotice error={error} />
        {history.data && !items.length && (
          <p className="small-empty">
            {query
              ? "未找到符合名称的档案项目，可调整查找条件。"
              : "当前没有可读取的档案项目。新项目与正式记录入库后会出现在这里。"}
          </p>
        )}
        {items.map((item) => (
          <article className="archive-project" key={item.id}>
            <div>
              <h3>{item.title}</h3>
              <p className="small-note">
                建立于 {new Date(item.created_at).toLocaleDateString("zh-CN")} ·
                实交记录 {item.submission_count} · 成绩记录 {item.outcome_count}{" "}
                · 已准入样本 {item.admitted_samples}
              </p>
            </div>
            <button
              className="button secondary"
              onClick={() => onOpen(item.id)}
            >
              查看实交与成绩
            </button>
          </article>
        ))}
        {last?.next_offset != null && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => void next()}
          >
            {busy ? "正在读取更多档案…" : "加载更多档案"}
          </button>
        )}
        <p className="small-note">
          历史标书和官方成绩作为本系统新资料保存。成绩未知不会记成零分，已入库也不等于已核验或具备训练资格。
        </p>
      </section>
    </div>
  );
}

const scoreKindNames = {
  technical_total: "技术总分",
  comprehensive_total: "综合总分",
  unknown: "成绩口径未知",
};
const verificationNames = {
  pending: "待核验",
  verified: "已核验",
  conflict: "存在核验冲突",
  rejected: "核验已驳回",
};
export function OutcomeCard({
  outcome,
  current,
}: {
  outcome: ResearchOutcomeView;
  current: boolean;
}) {
  return (
    <article className="outcome-card">
      <div className="section-heading">
        <strong>{scoreKindNames[outcome.score_kind]}</strong>
        <div>
          <Badge
            tone={outcome.verification === "verified" ? "success" : "warning"}
          >
            {verificationNames[outcome.verification]}
          </Badge>
          <Badge>{current ? "当前成绩记录" : "历史成绩记录"}</Badge>
        </div>
      </div>
      <p className="outcome-value">
        {outcome.value === null ? "未知" : outcome.value}
        {outcome.maximum !== null && <small> / {outcome.maximum}</small>}
      </p>
      <p className="small-note">
        知悉于 {new Date(outcome.known_at).toLocaleString("zh-CN")} · 核验修订{" "}
        {outcome.verification_revision}
      </p>
      {outcome.supersedes_id && (
        <p className="small-note">
          这是一条追加更正记录，原成绩仍留存。当前冲突不会自动回退为旧的已核验成绩。
        </p>
      )}
      <ArtifactActions
        bidId={outcome.bid_id}
        documentId={outcome.source_version_id}
        isPdf={false}
        downloadLabel="下载成绩来源原件"
      />
    </article>
  );
}
export function OutcomesPanel({ bidId }: { bidId: string }) {
  const outcomes = useResource<ResearchOutcomePage>(`/bids/${bidId}/outcomes`);
  const valid =
    outcomes.data?.items.every((item) => item.bid_id === bidId) &&
    outcomes.data.heads.every((item) => item.bid_id === bidId);
  const heads = new Set(outcomes.data?.heads.map((head) => head.outcome_id));
  return (
    <section className="panel outcomes-panel">
      <div className="section-heading">
        <div>
          <h2>实交与官方成绩</h2>
          <p className="small-note">
            成绩与实际提交身份配对。综合分不冒充技术分；真实技术零分与未知状态分别保留。
          </p>
        </div>
      </div>
      <ResourceState
        {...outcomes}
        hasData={!!outcomes.data}
        onRetry={() => void outcomes.reload()}
      />
      {outcomes.data && !valid && (
        <div className="notice error" role="alert">
          成绩项目身份不一致，未展示其他项目数据。
        </div>
      )}
      {valid &&
        outcomes.data?.items.map((item) => (
          <OutcomeCard
            key={item.id}
            outcome={item}
            current={heads.has(item.id)}
          />
        ))}
      {valid && outcomes.data?.items.length === 0 && (
        <p className="small-empty">
          当前项目尚无成绩记录。这不表示成绩为零，也不表示没有实际提交。
        </p>
      )}
      <p className="small-note">
        此工作面当前支持留存记录与原件查阅。实际提交登记和成绩录入需接上可发现的提交身份后开放，不要求填写内部编号。
      </p>
    </section>
  );
}
