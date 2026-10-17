import { useState } from "react";
import type {
  Bid,
  BidIdentityCorrection,
  BidIdentityView,
  BiddingCompanyPage,
  CorrectBidIdentity,
  CreateBid,
  DefaultBiddingCompanyView,
  EngineeringIdentityPage,
  EngineeringRoundPage,
  RegisteredBiddingCompanyView,
  RegisterBidder,
  SelectDefaultBidder,
} from "./contracts";
import { supportsApi } from "./api";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useCommand } from "./useCommand";
import { useResource } from "./useResource";
import { useDirectory } from "./useDirectory";

type Company = BiddingCompanyPage["items"][number];
function companyLabel(company: Company) {
  return company.name;
}
function BidderPicker({
  selected,
  onSelect,
  disabled = false,
  allowDefault = false,
}: {
  selected: Company | null;
  onSelect: (company: Company | null) => void;
  disabled?: boolean;
  allowDefault?: boolean;
}) {
  const [query, setQuery] = useState("");
  const companies = useDirectory<BiddingCompanyPage>(
    `/identity/bidders?query=${encodeURIComponent(query)}&limit=100`,
  );
  const defaults = useResource<DefaultBiddingCompanyView>(
    allowDefault ? "/identity/default-bidder" : null,
  );
  const [register, setRegister] = useState(false);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [asDefault, setAsDefault] = useState(false);
  const registerCommand = useCommand("identity-register");
  const defaultCommand = useCommand("identity-default");
  const busy = disabled || registerCommand.busy || defaultCommand.busy;
  const items = [
    ...new Map(
      [...(selected ? [selected] : []), ...companies.items].map((company) => [
        company.id,
        company,
      ]),
    ).values(),
  ];
  async function create() {
    const body: RegisterBidder = {
      name: name.trim(),
      reason: reason.trim(),
      set_as_default: asDefault,
    };
    const result = await registerCommand.run<RegisteredBiddingCompanyView>(
      "/identity/bidders",
      body,
      null,
    );
    if (result) {
      onSelect(result.data.bidder);
      setRegister(false);
      setName("");
      setReason("");
      void companies.reload();
      void defaults.reload();
    }
  }
  async function saveDefault() {
    if (!selected || !defaults.etag) return;
    const body: SelectDefaultBidder = { bidder_id: selected.id };
    const result = await defaultCommand.run<DefaultBiddingCompanyView>(
      "/identity/default-bidder",
      body,
      defaults.etag,
      "PUT",
    );
    if (result) void defaults.reload();
  }
  return (
    <fieldset className="identity-picker" disabled={busy}>
      <legend>投标主体</legend>
      <label>
        查找完整公司名称
        <input
          value={query}
          maxLength={200}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="仅搜索已明确登记的主体"
        />
      </label>
      <ResourceState
        {...companies}
        hasData={!!companies.data}
        onRetry={() => void companies.reload()}
      />
      <label>
        本次选择的投标主体
        <select
          aria-label="本次选择的投标主体"
          value={selected?.id ?? ""}
          onChange={(event) =>
            onSelect(
              items.find((company) => company.id === event.target.value) ??
                null,
            )
          }
        >
          <option value="">本公司（部署主体待核验）· 待确认</option>
          {items.map((company) => (
            <option key={company.id} value={company.id}>
              {companyLabel(company)}
            </option>
          ))}
        </select>
      </label>
      {companies.hasMore && (
        <p className="small-note">
          目录还有更多主体，可继续加载或搜索完整名称；近似名称不会自动合并。
        </p>
      )}
      {companies.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={companies.moreBusy}
          onClick={() => void companies.loadMore()}
        >
          加载更多投标主体
        </button>
      )}
      <ErrorNotice
        error={companies.moreError}
        onRetry={() => void companies.loadMore()}
      />
      <p className="small-note">
        选择或确认绑定只说明由谁投标，不证明资质、业绩、项目事实或官方成绩已经核验。
      </p>
      {allowDefault && selected && (
        <>
          <button
            type="button"
            className="text-button"
            disabled={
              busy ||
              !defaults.etag ||
              defaults.data?.bidder?.id === selected.id
            }
            onClick={() => void saveDefault()}
          >
            {defaults.data?.bidder?.id === selected.id
              ? "已是以后新项目的默认主体"
              : "将所选主体设为以后默认"}
          </button>
          <ErrorNotice error={defaultCommand.error} />
          {defaultCommand.conflict && (
            <button
              type="button"
              className="text-button"
              onClick={() => void defaults.reload()}
            >
              读取最新默认主体，保留本次选择
            </button>
          )}
        </>
      )}
      <button
        type="button"
        className="text-button"
        onClick={() => setRegister((old) => !old)}
      >
        {register ? "收起主体登记，保留填写" : "明确登记新的真实主体"}
      </button>
      {register && (
        <div className="identity-register">
          <label>
            真实公司完整名称
            <input
              value={name}
              maxLength={300}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            登记依据与理由
            <textarea
              value={reason}
              maxLength={1000}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={asDefault}
              onChange={(event) => setAsDefault(event.target.checked)}
            />
            同时设为以后新项目的默认主体
          </label>
          <ErrorNotice error={registerCommand.error} />
          <button
            type="button"
            className="button secondary"
            disabled={busy || !name.trim() || !reason.trim()}
            onClick={() => void create()}
          >
            登记并选用此主体
          </button>
        </div>
      )}
    </fieldset>
  );
}

function EngineeringPicker({
  engineeringId,
  roundId,
  onChange,
  disabled = false,
  allowNew = true,
}: {
  engineeringId: string;
  roundId: string;
  onChange: (engineeringId: string, roundId: string) => void;
  disabled?: boolean;
  allowNew?: boolean;
}) {
  const [query, setQuery] = useState("");
  const projects = useDirectory<EngineeringIdentityPage>(
    `/identity/engineering-projects?query=${encodeURIComponent(query)}&limit=100`,
  );
  const rounds = useDirectory<EngineeringRoundPage>(
    engineeringId
      ? `/identity/rounds?engineering_project_id=${encodeURIComponent(engineeringId)}&limit=100`
      : null,
  );
  const [heldProject, setHeldProject] = useState<
    EngineeringIdentityPage["items"][number] | null
  >(null);
  const selected =
    projects.items.find((project) => project.id === engineeringId) ??
    (heldProject?.id === engineeringId ? heldProject : undefined);
  const projectOptions = [
    ...new Map(
      [...(selected ? [selected] : []), ...projects.items].map((project) => [
        project.id,
        project,
      ]),
    ).values(),
  ];
  return (
    <fieldset disabled={disabled} className="identity-engineering">
      <legend>关联工程、标段或轮次</legend>
      <label>
        搜索已有工程完整名称
        <input
          value={query}
          maxLength={200}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <ResourceState
        {...projects}
        hasData={!!projects.data}
        onRetry={() => void projects.reload()}
      />
      <label>
        关联工程
        <select
          aria-label="关联工程"
          value={engineeringId}
          onChange={(event) => {
            setHeldProject(
              projectOptions.find(
                (project) => project.id === event.target.value,
              ) ?? null,
            );
            onChange(event.target.value, "");
          }}
        >
          <option value="">
            {allowNew ? "建立独立新工程" : "保留本项目当前工程与轮次"}
          </option>
          {projectOptions.map((project) => (
            <option key={project.id} value={project.id}>
              {project.title} · {project.region ?? "地区未注明"} ·{" "}
              {project.engineering_type ?? "类型未注明"}
            </option>
          ))}
        </select>
      </label>
      {projects.hasMore && (
        <p className="small-note">工程结果较多，请缩小完整名称范围后选择。</p>
      )}
      {engineeringId && (
        <>
          <p className="small-note">
            {selected?.title} · {selected?.region ?? "地区未注明"} ·{" "}
            {selected?.engineering_type ?? "类型未注明"}
          </p>
          <ResourceState
            {...rounds}
            hasData={!!rounds.data}
            onRetry={() => void rounds.reload()}
          />
          <label>
            标段与轮次
            <select
              aria-label="标段与轮次"
              value={roundId}
              onChange={(event) => onChange(engineeringId, event.target.value)}
            >
              <option value="">
                {allowNew
                  ? "为所选工程建立新标段／下一轮"
                  : "请选择明确的已有标段与轮次"}
              </option>
              {rounds.items.map((round) => (
                <option key={round.id} value={round.id}>
                  {round.engineering_title} · {round.lot ?? "未注明标段"} · 第
                  {round.round_no}轮
                </option>
              ))}
            </select>
          </label>
          {rounds.hasMore && (
            <button
              type="button"
              className="text-button"
              disabled={rounds.moreBusy}
              onClick={() => void rounds.loadMore()}
            >
              加载更多标段与轮次
            </button>
          )}
          <ErrorNotice
            error={rounds.moreError}
            onRetry={() => void rounds.loadMore()}
          />
        </>
      )}
      <p className="small-note">
        明确选择相同已有轮次只复用其身份，不自动带入其他主体的资料、规则、实交或成绩。
      </p>
    </fieldset>
  );
}

export function CreateIdentityForm({
  onCreated,
}: {
  onCreated: (id: string) => void;
}) {
  const enabled = supportsApi("GET", "/identity/default-bidder");
  const defaults = useResource<DefaultBiddingCompanyView>(
    enabled ? "/identity/default-bidder" : null,
  );
  const [choice, setChoice] = useState<Company | null | undefined>(undefined);
  const selected =
    choice === undefined ? (defaults.data?.bidder ?? null) : choice;
  const [title, setTitle] = useState("");
  const [link, setLink] = useState(false);
  const [engineeringId, setEngineeringId] = useState("");
  const [roundId, setRoundId] = useState("");
  const [lot, setLot] = useState("");
  const [region, setRegion] = useState("");
  const [engineeringType, setEngineeringType] = useState("");
  const command = useCommand("bid:create");
  async function create() {
    const body: CreateBid = { title: title.trim() };
    if (selected) body.bidder_id = selected.id;
    if (link && engineeringId) body.engineering_project_id = engineeringId;
    if (link && roundId) body.round_id = roundId;
    if (link && !roundId && lot.trim()) body.lot = lot.trim();
    if (link && !engineeringId) {
      if (region.trim()) body.region = region.trim();
      if (engineeringType.trim())
        body.engineering_type = engineeringType.trim();
    }
    const result = await command.run<Bid>("/bids", body, null);
    if (result) onCreated(result.data.id);
  }
  return (
    <form
      className="identity-create-form"
      onSubmit={(event) => {
        event.preventDefault();
        void create();
      }}
    >
      <fieldset disabled={command.busy}>
        <legend>项目基本信息</legend>
        <label>
          项目名称
          <input
            required
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            autoFocus
            placeholder="例如：滨河路道路提升工程"
          />
        </label>
      </fieldset>
      {enabled && (
        <>
          <ResourceState
            {...defaults}
            hasData={!!defaults.data}
            onRetry={() => void defaults.reload()}
          />
          <BidderPicker
            selected={selected}
            onSelect={setChoice}
            disabled={command.busy}
            allowDefault
          />
          {!selected && (
            <p className="notice warning">
              当前主体待确认。可以先保存独立项目并上传资料，需要可靠身份的知识选用、结果核验等操作仍需有据确认。
            </p>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={link}
              disabled={command.busy}
              onChange={(event) => setLink(event.target.checked)}
            />
            关联工程、标段或轮次（可选）
          </label>
          {link && (
            <>
              <EngineeringPicker
                engineeringId={engineeringId}
                roundId={roundId}
                disabled={command.busy}
                onChange={(engineering, round) => {
                  setEngineeringId(engineering);
                  setRoundId(round);
                }}
              />
              {!roundId && (
                <label>
                  明确新标段名称（可留空）
                  <input
                    value={lot}
                    disabled={command.busy}
                    maxLength={200}
                    onChange={(event) => setLot(event.target.value)}
                  />
                </label>
              )}
              {!engineeringId && (
                <>
                  <label>
                    新工程地区
                    <input
                      value={region}
                      maxLength={200}
                      disabled={command.busy}
                      onChange={(event) => setRegion(event.target.value)}
                    />
                  </label>
                  <label>
                    新工程类型
                    <input
                      value={engineeringType}
                      maxLength={200}
                      disabled={command.busy}
                      onChange={(event) =>
                        setEngineeringType(event.target.value)
                      }
                    />
                  </label>
                </>
              )}
            </>
          )}
        </>
      )}
      <ErrorNotice error={command.error} />
      <button
        className="button primary"
        disabled={
          command.busy ||
          !title.trim() ||
          (enabled && defaults.loading && !defaults.data)
        }
      >
        {command.busy ? "正在创建…" : "创建并上传资料"}
      </button>
    </form>
  );
}

const affectedLabels: Record<keyof BidIdentityView["affected"], string> = {
  reviews: "评审",
  submissions: "实交登记",
  outcomes: "结果记录",
  samples: "研究样本",
  drafts: "正文草稿",
  documents: "文档",
  facts: "工程事实",
  knowledge_citations: "知识引用",
};
export function IdentityPanel({
  bidId,
  onSaved,
}: {
  bidId: string;
  onSaved: () => void;
}) {
  const resource = useResource<BidIdentityView>(`/bids/${bidId}/identity`);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<Company | null>(null);
  const [engineeringId, setEngineeringId] = useState("");
  const [roundId, setRoundId] = useState("");
  const [reason, setReason] = useState("");
  const [base, setBase] = useState<string | null>(null);
  const [compared, setCompared] = useState(false);
  const [saved, setSaved] = useState(false);
  const command = useCommand(`identity-correct:${bidId}`);
  const identity = resource.data?.identity;
  async function correct() {
    if (!selected || !base) return;
    const body: CorrectBidIdentity = {
      bidder_id: selected.id,
      reason: reason.trim(),
    };
    if (roundId) body.round_id = roundId;
    const result = await command.run<BidIdentityCorrection>(
      `/bids/${bidId}/identity`,
      body,
      base,
      "PUT",
    );
    if (result) {
      setSaved(true);
      setEditing(false);
      setReason("");
      void resource.reload();
      onSaved();
    }
  }
  return (
    <section className="panel identity-panel">
      <h2>本项目身份</h2>
      <ResourceState
        {...resource}
        hasData={!!resource.data}
        onRetry={() => void resource.reload()}
      />
      {identity && (
        <>
          <Badge
            tone={
              identity.binding_status === "confirmed" ? "success" : "warning"
            }
          >
            {identity.binding_status === "confirmed"
              ? "本项目身份已明确绑定"
              : "身份待有据确认"}
          </Badge>
          <h3>{identity.bidder_name}</h3>
          <p>
            {identity.engineering_title} · {identity.lot ?? "未注明标段"} · 第
            {identity.round_no}轮
          </p>
          <p className="small-note">
            主体绑定不代替资质、事实或官方成绩核验。以后默认主体变化不会改写本项目。
          </p>
          <button
            type="button"
            className="text-button"
            disabled={command.busy}
            onClick={() => {
              if (!editing) setBase(resource.etag);
              setEditing((old) => !old);
              setSaved(false);
            }}
          >
            {editing
              ? "收起身份表单，保留本次选择"
              : identity.binding_status === "confirmed"
                ? "有据纠正本项目身份"
                : "确认本项目投标主体"}
          </button>
          {editing && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void correct();
              }}
            >
              <BidderPicker
                selected={selected}
                onSelect={setSelected}
                disabled={command.busy}
              />
              <details>
                <summary>同时有据纠正工程与已有轮次（可选）</summary>
                <EngineeringPicker
                  engineeringId={engineeringId}
                  roundId={roundId}
                  allowNew={false}
                  disabled={command.busy}
                  onChange={(engineering, round) => {
                    setEngineeringId(engineering);
                    setRoundId(round);
                  }}
                />
              </details>
              <h3>已关联对象与影响范围</h3>
              <div className="identity-impacts">
                {Object.entries(resource.data!.affected).map(([key, count]) => (
                  <span key={key}>
                    {affectedLabels[key as keyof typeof affectedLabels]} {count}
                  </span>
                ))}
              </div>
              <p className="notice warning">
                纠正追加身份依据，旧冻结评审、实交和结果继续保留当时身份。受影响的当前资格、样本和引用须重新核验，不会因纠正自动通过。
              </p>
              <label>
                本次选择与纠正依据
                <textarea
                  required
                  maxLength={1000}
                  value={reason}
                  disabled={command.busy}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <ErrorNotice error={command.error} />
              {command.conflict && (
                <div className="notice warning">
                  <div>
                    <p>
                      项目已更新，选择和理由保留。先读取当前身份及影响范围，再明确按当前基准继续。
                    </p>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        void resource.reload().then(() => setCompared(true))
                      }
                    >
                      读取当前身份与影响
                    </button>
                    {compared &&
                      resource.etag &&
                      !resource.error &&
                      !resource.loading && (
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => {
                            setBase(resource.etag);
                            setCompared(false);
                            command.clearError();
                          }}
                        >
                          已核对当前身份，保留选择继续
                        </button>
                      )}
                  </div>
                </div>
              )}
              <button
                className="button primary"
                disabled={
                  command.busy ||
                  !selected ||
                  !reason.trim() ||
                  !base ||
                  command.conflict ||
                  (!!engineeringId && !roundId)
                }
              >
                {command.busy ? "正在记录身份依据…" : "确认本项目身份"}
              </button>
            </form>
          )}
          {saved && (
            <p className="inline-success" role="status">
              本项目身份已记录，历史未被改写；受影响资格须重新核验。
            </p>
          )}
        </>
      )}
    </section>
  );
}
