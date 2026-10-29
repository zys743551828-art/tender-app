import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SubmissionPanel } from "./SubmissionPanel";
import {
  useRecordedCommand,
  clearRecordedCommands,
} from "./useRecordedCommand";

// Contract-driven component mechanisms, not live API acceptance.
vi.mock("./contracts", async (original) => ({
  ...(await original<typeof import("./contracts")>()),
  implementedOperations: [
    "GET /api/v1/bids/{bid_id}/submission-gate",
    "GET /api/v1/bids/{bid_id}/submissions",
    "GET /api/v1/bids/{bid_id}/submission-documents",
    "POST /api/v1/bids/{bid_id}/submissions",
    "POST /api/v1/bids/{bid_id}/submission-facts",
    "POST /api/v1/submissions/{submission_id}/corrections",
    "GET /api/v1/submissions/{submission_id}",
    "GET /api/v1/findings/{id}",
  ],
}));
const gate = {
  allowed: true,
  bid_revision: 3,
  body_version_id: "body",
  blockers: [],
  review_id: "review",
  material_revision: 2,
  current_identity_digest: "a".repeat(64),
  current_review_manifest_digest: "b".repeat(64),
  pending_core_rule_ids: [],
  blocking_finding_ids: [],
  warnings: [],
};
const record = {
  id: "submission",
  bid_id: "bid",
  body_version_id: "body",
  review_id: "review",
  kind: "standard",
  submitted_at: "2020-01-01T12:00:00Z",
  recorded_by: "actor",
  gate_checked: true,
  evidence_ref: "body",
  current: true,
  supersedes_id: null,
  identity: null,
  original_name: "actual.pdf",
  artifact_kind: "bid_body",
  checks_label: "核心提交检查已通过",
  open_risk_snapshot: null,
  platform_submission_verified: false,
  explanation: null,
  correction_reason: null,
};
const documents = {
  items: [
    {
      document_version_id: "body",
      original_name: "actual.pdf",
      artifact_kind: "bid_body",
      digest: "d".repeat(64),
      byte_size: 999,
      media_type: "application/pdf",
    },
  ],
  has_more: false,
  next_cursor: null,
};
const response = (value: unknown, tag = '"bid:3"', status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { ETag: tag } });
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

it("线下补录选择真实原件及自身附件，一次保存并持续标明未完整检查/未核验平台", async () => {
  const user = userEvent.setup();
  const writes: { body: unknown; headers: Headers }[] = [];
  let recorded = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({
          body: JSON.parse(String(init.body)),
          headers: new Headers(init.headers),
        });
        recorded = true;
        return response({
          ...record,
          kind: "offline_fact",
          review_id: null,
          gate_checked: false,
          checks_label: "未经过系统完整检查",
          explanation: "当时线下已提交",
        });
      }
      if (url.includes("submission-documents")) return response(documents);
      if (url.includes("submission-gate"))
        return response({
          ...gate,
          allowed: false,
          blockers: [
            {
              code: "BID_IDENTITY_UNCONFIRMED",
              object_id: "bid",
              message: "主体待确认",
            },
          ],
        });
      if (url.includes("/submissions"))
        return response({
          items: recorded
            ? [
                {
                  ...record,
                  kind: "offline_fact",
                  gate_checked: false,
                  checks_label: "未经过系统完整检查",
                },
              ]
            : [],
          has_more: false,
          next_cursor: null,
        });
      throw new Error("unexpected read");
    }),
  );
  render(
    <SubmissionPanel
      bidId="bid"
      memberId="member"
      onNavigate={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "补录线下已发生的提交" }),
  );
  await user.selectOptions(
    await screen.findByLabelText("实际提交的原件"),
    "body",
  );
  await user.type(
    screen.getByLabelText("未经过完整检查的原因与已发生事实依据"),
    "当时线下已提交",
  );
  await user.type(
    screen.getByLabelText("真实提交时间（本地时间）"),
    "2020-01-01T12:00:00",
  );
  await user.click(
    screen.getByRole("button", { name: "使用实交稿自身作为声明附件" }),
  );
  await user.click(screen.getByRole("button", { name: "保存线下提交事实" }));
  await screen.findByText("已保存实交记录");
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toEqual({
    actual_document_version_id: "body",
    submitted_at: new Date("2020-01-01T12:00:00").toISOString(),
    evidence_ref: "body",
    explanation: "当时线下已提交",
  });
  expect(writes[0].headers.get("If-Match")).toBe('"bid:3"');
  expect(
    screen.getAllByText(/用户声明，未核验交易平台回执/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByRole("button", { name: "登记已检查的实际提交" }),
  ).toBeDisabled();
});

it("412保留实际时间与附件，只在明确重读后使用新Gate身份；更正用Bid tag而非原记录tag", async () => {
  const user = userEvent.setup();
  const writes: { body: unknown; tag: string | null }[] = [];
  let revision = 3;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({
          body: JSON.parse(String(init.body)),
          tag: new Headers(init.headers).get("If-Match"),
        });
        if (writes.length === 1) {
          revision = 4;
          return response(
            { code: "SUBMISSION_INPUT_CHANGED", message: "稿件更新" },
            '"bid:4"',
            412,
          );
        }
        return response({
          ...record,
          id: "corrected",
          supersedes_id: "submission",
        });
      }
      if (url.includes("submission-documents")) return response(documents);
      if (url.includes("submission-gate"))
        return response(
          { ...gate, bid_revision: revision },
          `"bid:${revision}"`,
        );
      if (url.endsWith("/submissions/submission"))
        return response(record, '"submission-read-only"');
      return response({ items: [record], has_more: false, next_cursor: null });
    }),
  );
  render(
    <SubmissionPanel
      bidId="bid"
      memberId="member"
      onNavigate={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "追加更正此实交记录" }),
  );
  await user.type(screen.getByLabelText("本次追加更正理由"), "校正真实时点");
  await waitFor(() =>
    expect(screen.getByLabelText("本项目提交声明附件")).toHaveValue("body"),
  );
  await user.click(screen.getByRole("button", { name: "保存追加更正" }));
  await screen.findByText("稿件更新");
  expect(screen.getByLabelText("本次追加更正理由")).toHaveValue("校正真实时点");
  expect(screen.getByLabelText("本项目提交声明附件")).toHaveValue("body");
  await user.click(
    screen.getByRole("button", { name: "读取当前检查依据，保留表单" }),
  );
  await screen.findByText(/本表依据项目修订 4/);
  await user.click(screen.getByRole("button", { name: "保存追加更正" }));
  await screen.findByText("已保存实交记录");
  expect(writes.map((write) => write.tag)).toEqual(['"bid:3"', '"bid:4"']);
  expect(writes[1].body).toMatchObject({
    kind: "standard",
    reason: "校正真实时点",
    submission: {
      body_version_id: "body",
      review_id: "review",
      material_revision: 2,
    },
  });
});

it("失响应刷新后重放原body/key/If-Match，迟到卸载ACK不清除恢复身份，其他成员不读取私有请求", async () => {
  const writes: { body: BodyInit | null | undefined; headers: Headers }[] = [];
  let resolve: (value: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      writes.push({ body: init?.body, headers: new Headers(init?.headers) });
      if (writes.length === 1)
        return new Promise<Response>((done) => {
          resolve = done;
        });
      return response(record);
    }),
  );
  function Harness() {
    const command = useRecordedCommand("submission:member:bid:new");
    return (
      <>
        <button
          onClick={() =>
            void command.run(
              "/bids/bid/submissions",
              { immutable: "original" },
              '"bid:old"',
            )
          }
        >
          开始
        </button>
        <button onClick={() => void command.retry()}>恢复</button>
        {command.pending && <p>原请求待恢复</p>}
      </>
    );
  }
  const user = userEvent.setup();
  const view = render(<Harness />);
  await user.click(screen.getByText("开始"));
  await screen.findByText("原请求待恢复");
  view.unmount();
  await act(async () => {
    resolve(response(record));
  });
  render(<Harness />);
  expect(screen.getByText("原请求待恢复")).toBeVisible();
  await user.click(screen.getByText("恢复"));
  await waitFor(() =>
    expect(screen.queryByText("原请求待恢复")).not.toBeInTheDocument(),
  );
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual(writes[1].body);
  for (const field of ["If-Match", "Idempotency-Key"])
    expect(writes[0].headers.get(field)).toEqual(writes[1].headers.get(field));
  sessionStorage.setItem(
    "tender:command-record:submission:other:bid:new",
    "private",
  );
  clearRecordedCommands("member");
  expect(
    sessionStorage.getItem("tender:command-record:submission:other:bid:new"),
  ).toBeNull();
});

it("多个阻断保持可定位，关闭检测遗留关键风险仍可读原页和发现轮次", async () => {
  const user = userEvent.setup();
  const nav = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("submission-gate"))
        return response({
          ...gate,
          allowed: false,
          blockers: [
            {
              code: "CORE_RULE_CONFIRMATION_REQUIRED",
              object_id: "rules",
              message: "3项核心规则待确认",
            },
            {
              code: "OPEN_BLOCKING_FINDING",
              object_id: "risk",
              message: "先前关键风险",
            },
          ],
        });
      if (url.endsWith("/findings/risk"))
        return response({
          id: "risk",
          statement: "先前关键风险正文",
          evidence_ids: [],
          origin_review_id: "old-review",
          detection_run_state: "not_run_this_round",
        });
      return response({ items: [], has_more: false, next_cursor: null });
    }),
  );
  render(
    <SubmissionPanel
      bidId="bid"
      memberId="member"
      onNavigate={nav}
      onChanged={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "前往处理此阻断" }),
  );
  expect(nav).toHaveBeenCalledWith("rules");
  await user.click(
    screen.getByRole("button", { name: "定位此阻断风险与原页" }),
  );
  await screen.findByText("先前检测发现，本轮未运行；尚未有效解决。");
  await user.click(
    screen.getByRole("button", { name: "打开发现此问题的评审轮次" }),
  );
  expect(nav).toHaveBeenCalledWith("review", "old-review");
});
