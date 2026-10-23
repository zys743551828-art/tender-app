import { lazy, Suspense, useState } from "react";
import { api } from "./api";
import type {
  ResearchCapabilities,
  ResearchGroupingRequest,
  ResearchGroupingView,
  ResearchListedSample,
  ResearchOutcomeDetail,
  ResearchSamplePage,
} from "./contracts";
import { Badge, ErrorNotice, Loading } from "./components";
import { OutcomeCard } from "./Archives";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";

const PackageHistoricalResearch = lazy(() =>
  import("./PackageHistoricalResearch").then((module) => ({
    default: module.PackageHistoricalResearch,
  })),
);

export function Research({
  memberId,
  onOpen,
  onOpenPackage,
}: {
  memberId: string;
  onOpen: (id: string) => void;
  onOpenPackage?: (id: string) => void;
}) {
  const [view, setView] = useState<"package" | "legacy">("package");
  const [legacyOpened, setLegacyOpened] = useState(false);
  return (
    <div className="page-content research-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">独立研究空间</span>
          <h1>评分研究</h1>
          <p>选择确切实交与证据，冻结研究方案，再核对独立执行的结果。</p>
        </div>
        <Badge>回溯研究 · 正式预测未开放</Badge>
      </header>
      <nav className="review-shortcuts" aria-label="研究记录类型">
        <button
          type="button"
          aria-pressed={view === "package"}
          onClick={() => setView("package")}
        >
          整包历史研究
        </button>
        <button
          type="button"
          aria-pressed={view === "legacy"}
          onClick={() => {
            setLegacyOpened(true);
            setView("legacy");
          }}
        >
          既有单稿研究记录
        </button>
      </nav>
      <div hidden={view !== "package"}>
        <Suspense fallback={<Loading text="正在打开整包历史研究…" />}>
          <PackageHistoricalResearch
            key={memberId}
            memberId={memberId}
            onOpenBid={onOpenPackage ?? onOpen}
          />
        </Suspense>
      </div>
      {legacyOpened && (
        <div hidden={view !== "legacy"}>
          <LegacyResearch onOpen={onOpen} />
        </div>
      )}
    </div>
  );
}

function LegacyResearch({ onOpen }: { onOpen: (id: string) => void }) {
  const capabilities = useResource<ResearchCapabilities>(
    "/research/capabilities",
  );
  const samples = useResource<ResearchSamplePage>("/research/samples");
  const [more, setMore] = useState<ResearchSamplePage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const items = [
    ...new Map(
      [
        ...(samples.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const last = more.at(-1) ?? samples.data;
  async function next() {
    if (busy || last?.next_offset == null) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<ResearchSamplePage>(
        `/research/samples?offset=${last.next_offset}`,
      );
      setMore((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content research-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">独立研究空间</span>
          <h2>既有单稿研究记录</h2>
          <p>核对正式标签与来源分组，为受控实验准备可靠样本。</p>
        </div>
        <Badge>与业务评审分开</Badge>
      </header>
      <section className="panel">
        <h2>当前研究资格与范围</h2>
        <ResourceState
          {...capabilities}
          hasData={!!capabilities.data}
          onRetry={() => void capabilities.reload()}
        />
        {capabilities.data && (
          <>
            {!capabilities.data.source_authority_configured && (
              <div className="notice neutral">
                成绩来源核验服务尚未完成配置。既有记录可以查阅；这不表示官方来源已经核验，也不要求用户配置评审模型。
              </div>
            )}
            <div className="notice warning">
              <div>
                <strong>正式预测与模型发布尚不可用</strong>
                {capabilities.data.formal_prediction.reasons.map(
                  (reason, index) => (
                    <p key={index}>{reason}</p>
                  ),
                )}
              </div>
            </div>
            <p className="small-note">
              正式评分必须覆盖完整相关章节、每项三次判断。普通资料检索摘录不替代完整评分，样本准入不代表模型已经通过独立评测。
            </p>
            <p className="small-note">
              {capabilities.data.price.available
                ? `研究价格快照可用（${capabilities.data.price.currency}），预算须另行冻结并明确确认。`
                : "当前没有可用的研究价格快照，不能据此启动收费批次。"}{" "}
              本页不会发出模型执行请求。
            </p>
          </>
        )}
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>研究样本</h2>
            <p className="small-note">
              当前成绩更正、提交变化与来源同组会影响准入。每条样本保留实际结果和核对理由。
            </p>
          </div>
        </div>
        <ResourceState
          {...samples}
          hasData={!!samples.data}
          onRetry={() => void samples.reload()}
        />
        <ErrorNotice error={error} />
        {samples.data && !items.length && (
          <p className="small-empty">
            尚无可读取的研究样本。先保留真实实交、官方技术分及原件，再核验准入；不会用合成分数填充研究结果。
          </p>
        )}
        {items.map((item, index) => (
          <SampleCard
            key={item.id}
            sample={item}
            number={index + 1}
            onOpen={() => onOpen(item.bid_id)}
          />
        ))}
        {last?.next_offset != null && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => void next()}
          >
            {busy ? "正在读取更多样本…" : "加载更多样本"}
          </button>
        )}
      </section>
    </div>
  );
}
function SampleCard({
  sample,
  number,
  onOpen,
}: {
  sample: ResearchListedSample;
  number: number;
  onOpen: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="sample-card">
      <div className="section-heading">
        <strong>样本 {number}</strong>
        <div>
          <Badge tone={sample.admission === "admitted" ? "success" : "warning"}>
            {sample.admission === "admitted"
              ? "已准入"
              : sample.admission === "rejected"
                ? "已拒绝准入"
                : "准入待核验"}
          </Badge>
          <Badge>{sample.current ? "当前配对" : "历史配对"}</Badge>
        </div>
      </div>
      <p className="small-note">
        知悉于 {new Date(sample.known_at).toLocaleString("zh-CN")}
      </p>
      {sample.reasons.map((reason, index) => (
        <p className="small-note" key={index}>
          {reason}
        </p>
      ))}
      <div className="review-shortcuts">
        <button className="button secondary" onClick={onOpen}>
          查看所属项目与成绩
        </button>
        <button className="text-button" onClick={() => setOpen((old) => !old)}>
          {open ? "收起样本依据与归组" : "核对样本依据与归组"}
        </button>
      </div>
      {open && <SampleDetails sample={sample} />}
    </article>
  );
}
function SampleDetails({ sample }: { sample: ResearchListedSample }) {
  const outcome = useResource<ResearchOutcomeDetail>(
    `/outcomes/${sample.outcome_id}`,
  );
  const grouping = useResource<ResearchGroupingView>(
    `/research/samples/${sample.id}/grouping`,
  );
  return (
    <>
      <ResourceState
        {...outcome}
        hasData={!!outcome.data}
        onRetry={() => void outcome.reload()}
      />
      {outcome.data &&
        (outcome.data.bid_id !== sample.bid_id ||
          outcome.data.submission_id !== sample.submission_id ||
          outcome.data.id !== sample.outcome_id) && (
          <div className="notice error" role="alert">
            样本和成绩身份不一致，未展示不相关标签。
          </div>
        )}
      {outcome.data?.bid_id === sample.bid_id &&
        outcome.data.submission_id === sample.submission_id &&
        outcome.data.id === sample.outcome_id && (
          <OutcomeCard outcome={outcome.data} current={outcome.data.current} />
        )}
      <ResourceState
        {...grouping}
        hasData={!!grouping.data}
        onRetry={() => void grouping.reload()}
      />
      {grouping.data?.sample_id === sample.id && grouping.etag && (
        <GroupingForm
          key={sample.id}
          sample={sample}
          value={grouping.data}
          etag={grouping.etag}
          onSaved={() => void grouping.reload()}
        />
      )}
    </>
  );
}
function GroupingForm({
  sample,
  value,
  etag,
  onSaved,
}: {
  sample: ResearchListedSample;
  value: ResearchGroupingView;
  etag: string;
  onSaved: () => void;
}) {
  const [template, setTemplate] = useState(value.metadata.template_key ?? "");
  const [duplicate, setDuplicate] = useState(
    value.metadata.near_duplicate_key ?? "",
  );
  const [reason, setReason] = useState(value.metadata.reason);
  const [reviewed, setReviewed] = useState(value.metadata.reviewed);
  const [base, setBase] = useState({ value, etag });
  const [remote, setRemote] = useState<{
    value: ResearchGroupingView;
    etag: string;
  } | null>(null);
  const [readError, setReadError] = useState<unknown>(null);
  const [savedRevision, setSavedRevision] = useState<number | null>(null);
  const [reading, setReading] = useState(false);
  const command = useCommand(`sample-grouping:${sample.id}`);
  async function save() {
    const body: ResearchGroupingRequest = {
      template_key: template.trim() || null,
      near_duplicate_key: duplicate.trim() || null,
      reviewed,
      reason: reason.trim(),
    };
    const result = await command.run<ResearchGroupingView>(
      `/research/samples/${sample.id}/grouping`,
      body,
      base.etag,
    );
    if (result && result.etag && result.data.sample_id === sample.id) {
      setBase({ value: result.data, etag: result.etag });
      setSavedRevision(result.data.revision);
      setRemote(null);
      onSaved();
    }
  }
  async function compare() {
    if (reading) return;
    setReading(true);
    setReadError(null);
    try {
      const result = await api<ResearchGroupingView>(
        `/research/samples/${sample.id}/grouping`,
      );
      if (!result.etag || result.data.sample_id !== sample.id)
        throw new Error("来源分组身份或保存令牌无法核对，当前输入保留。");
      setRemote({ value: result.data, etag: result.etag });
    } catch (failure) {
      setReadError(failure);
    } finally {
      setReading(false);
    }
  }
  return (
    <form
      className="sample-grouping"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h4>有依据的来源分组</h4>
      <p className="small-note">
        相同项目及原件摘要由服务器归组；模板和近重复来源需人工核对。分组变化会暂停受影响实验，不可把相关样本拆开获取独立评测资格。
      </p>
      <label>
        共同模板标记（可选）
        <input
          value={template}
          maxLength={100}
          disabled={command.busy}
          onChange={(event) => setTemplate(event.target.value)}
          placeholder="使用有依据的统一名称"
        />
      </label>
      <label>
        近重复来源标记（可选）
        <input
          value={duplicate}
          maxLength={100}
          disabled={command.busy}
          onChange={(event) => setDuplicate(event.target.value)}
        />
      </label>
      <label>
        核对依据与理由
        <textarea
          required
          value={reason}
          maxLength={4000}
          disabled={command.busy}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={reviewed}
          disabled={command.busy}
          onChange={(event) => setReviewed(event.target.checked)}
        />
        已根据资料完成来源关系核对
      </label>
      <ErrorNotice error={readError ?? command.error} />
      {command.conflict && (
        <p className="notice warning">
          分组已被更新。当前输入保留，请先重新读取并比较，不自动覆盖其他成员决定。
        </p>
      )}
      {(command.conflict || value.revision !== base.value.revision) && (
        <button
          type="button"
          className="text-button"
          disabled={reading || command.busy}
          onClick={() => void compare()}
        >
          {reading ? "正在读取最新分组…" : "读取最新分组并比较"}
        </button>
      )}
      {remote && (
        <div className="notice warning">
          <div>
            <strong>服务器来源分组 · 修订 {remote.value.revision}</strong>
            <p>
              共同模板：{remote.value.metadata.template_key ?? "未填写"}
              ；近重复来源：
              {remote.value.metadata.near_duplicate_key ?? "未填写"}；
              {remote.value.metadata.reviewed ? "已核对" : "尚未完成核对"}
            </p>
            <p>{remote.value.metadata.reason}</p>
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setBase(remote);
                setRemote(null);
                command.clearError();
                setSavedRevision(null);
              }}
            >
              保留上述输入，按最新分组继续保存
            </button>
          </div>
        </div>
      )}
      {savedRevision !== null && (
        <p className="inline-success" role="status">
          来源分组已保存为修订 {savedRevision}，不代表模型已经发布。
        </p>
      )}
      <p className="small-note">
        当前同组样本 {value.related_sample_ids.length} 条；
        {value.eligible_label_pair
          ? "此标签配对符合当前检查"
          : "此标签配对尚不符合当前准入检查"}
        ，均不代表模型取得业务发布资格。
      </p>
      <button
        className="button secondary"
        disabled={command.busy || !reason.trim()}
      >
        {command.busy ? "正在核对并保存分组…" : "保存来源分组核对"}
      </button>
    </form>
  );
}
