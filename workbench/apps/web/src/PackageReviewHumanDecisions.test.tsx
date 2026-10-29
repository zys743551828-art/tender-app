import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import HumanDecisions from "./PackageReviewHumanDecisions";
import type {
  PackageReviewHumanDecisionView,
  SavePackageReviewHumanDecision,
} from "./contracts";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import {
  packageReviewDecisionBody,
  packageReviewDecisionCurrent,
  packageReviewDecisionReply,
} from "../qa-previews/frozen-inputs/packageReviewDecision";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import {
  loadPackageReviewDecisionRecord,
  storePackageReviewDecisionRecord,
} from "./packageReviewDecisionRecovery";
import { frozenManifestDigest } from "./packageFrozenInput";

let f: Awaited<ReturnType<typeof packageReviewFixture>>;
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
const firstArticle = () =>
  screen.getByRole("article", {
    name: `要求：${f.completed.result!.manifest.matrix[0].requirement_statement}`,
  });
async function openFirst() {
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "记录人工判断" }),
  );
  await screen.findByText(
    `已读取 ${f.completed.result!.manifest.matrix.length} 条要求的人工状态；保存时仍须通过版本核对。`,
  );
}
async function fillFirst(reason = "合成意见：已核对本条原文") {
  await userEvent.type(
    within(firstArticle()).getByLabelText("本次人工理由（必填）"),
    reason,
  );
  await userEvent.click(within(firstArticle()).getAllByRole("checkbox")[0]);
}
type Posted = { key: string | null; body: SavePackageReviewHumanDecision };
const post = (options: RequestInit): Posted => ({
  key: new Headers(options.headers).get("Idempotency-Key"),
  body: JSON.parse(String(options.body)),
});
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("ignores a late current-head read superseded by recovery of the original request", async () => {
  const p = { ...f.props, run: f.completed },
    body = await packageReviewDecisionBody(f),
    head = await packageReviewDecisionReply(f, body),
    record = loadPackageReviewDecisionRecord(p);
  record.pending = {
    key: id(990),
    requirementId: f.completed.result!.manifest.matrix[0].requirement_id,
    previousSequence: null,
    body,
  };
  storePackageReviewDecisionRecord(record);
  let finishOld!: (value: Response) => void,
    reads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") return json(head, 201);
      reads++;
      if (reads === 1)
        return new Promise<Response>((resolve) => {
          finishOld = resolve;
        });
      return json(await packageReviewDecisionCurrent(f, [head]));
    }),
  );
  render(<HumanDecisions {...f.props} run={f.completed} />);
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前人工状态" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原人工处置请求" }),
  );
  await waitFor(() =>
    expect(
      within(firstArticle()).getByText(/确认此项判断 · 第 1 版/),
    ).toBeInTheDocument(),
  );
  const stale = await packageReviewDecisionCurrent(f);
  await act(async () => {
    finishOld(json(stale));
  });
  expect(
    within(firstArticle()).getByText(/确认此项判断 · 第 1 版/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(loadPackageReviewDecisionRecord(p).pending).toBeNull();
});

it("explicitly records an opinion against the observed head while preserving the machine matrix and partial boundary", async () => {
  let head: PackageReviewHumanDecisionView | null = null;
  const posts: Posted[] = [],
    original = structuredClone(f.completed);
  const fetcher = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === "POST") {
      const request = post(options);
      posts.push(request);
      head = await packageReviewDecisionReply(f, request.body);
      return json(head, 201);
    }
    return json(await packageReviewDecisionCurrent(f, head ? [head] : []));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<HumanDecisions {...f.props} run={f.completed} />);
  expect(fetcher).not.toHaveBeenCalled();
  await openFirst();
  await fillFirst();
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "不采用此项判断" }),
  );
  await screen.findByText("原请求已核对受理");
  await waitFor(() =>
    expect(
      within(firstArticle()).getByText(/不采用此项判断 · 第 1 版/),
    ).toBeInTheDocument(),
  );
  expect(posts).toHaveLength(1);
  expect(posts[0].body.expected_head).toBeNull();
  expect(posts[0].body.state).toBe("rejected");
  expect(posts[0].body.selected_quotes).toEqual([
    original.result!.manifest.matrix[0].target_quotes[0],
  ]);
  expect(f.completed).toEqual(original);
  expect(screen.getByText(/整体覆盖仍为部分/)).toBeInTheDocument();
  expect(
    loadPackageReviewDecisionRecord({ ...f.props, run: f.completed }).pending,
  ).toBeNull();
});

it("recovers a lost ACK with the exact old key/body, then displays a newer current head separately from the old receipt", async () => {
  let committed: PackageReviewHumanDecisionView | null = null,
    latest: PackageReviewHumanDecisionView | null = null;
  const posts: Posted[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") {
        const request = post(options);
        posts.push(request);
        if (!committed) {
          committed = await packageReviewDecisionReply(f, request.body);
          throw new TypeError("synthetic lost ACK");
        }
        return json(committed, 201);
      }
      return json(
        await packageReviewDecisionCurrent(f, latest ? [latest] : []),
      );
    }),
  );
  const view = render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst();
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "确认此项判断" }),
  );
  await screen.findByText("NETWORK_ERROR");
  view.unmount();
  const newerBody = await packageReviewDecisionBody(
    f,
    0,
    committed,
    "needs_review",
  );
  newerBody.reason = "另一成员的新判断：仍需补查";
  latest = await packageReviewDecisionReply(f, newerBody, 0, 2, id(999));
  render(<HumanDecisions {...f.props} run={f.completed} />);
  expect(posts).toHaveLength(1);
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原人工处置请求" }),
  );
  await screen.findByText("原请求已核对受理");
  await waitFor(() =>
    expect(
      within(firstArticle()).getByText("另一成员的新判断：仍需补查"),
    ).toBeInTheDocument(),
  );
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
  expect(
    within(firstArticle()).getByText(/需要复查 · 第 2 版/),
  ).toBeInTheDocument();
  expect(screen.getByText(/确认此项判断 · 第/)).toHaveTextContent("第 1 版");
});

it("keeps an unknown or mismatched ACK pending and blocks replacement decisions", async () => {
  let writes = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") {
        writes++;
        const request = post(options),
          ack = await packageReviewDecisionReply(f, {
            ...request.body,
            state: "rejected",
          });
        return json(ack, 201);
      }
      return json(await packageReviewDecisionCurrent(f));
    }),
  );
  render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst();
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "确认此项判断" }),
  );
  await screen.findByText(/人工记录与原核查结果、条款、引用或版本不符/);
  expect(screen.queryByText("原请求已核对受理")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "恢复原人工处置请求" }),
  ).toBeEnabled();
  expect(
    within(firstArticle()).getByRole("button", { name: "需要复查" }),
  ).toBeDisabled();
  expect(writes).toBe(1);
  expect(
    loadPackageReviewDecisionRecord({ ...f.props, run: f.completed }).pending
      ?.body.state,
  ).toBe("confirmed");
});

it("refreshes a rejected CAS without discarding the draft and requires a new explicit decision against the new head", async () => {
  let latest: PackageReviewHumanDecisionView | null = null;
  const posts: Posted[] = [];
  const otherBody = await packageReviewDecisionBody(f, 0, null, "rejected");
  otherBody.reason = "另一成员先提交的判断";
  const other = await packageReviewDecisionReply(f, otherBody, 0, 1, id(999));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") {
        const request = post(options);
        posts.push(request);
        if (posts.length === 1) {
          latest = other;
          return json(
            {
              code: "PACKAGE_REVIEW_DECISION_HEAD_CHANGED",
              message: "其他成员已更新此项人工处置，请读取当前状态后再决定",
            },
            409,
          );
        }
        latest = await packageReviewDecisionReply(f, request.body, 0, 2);
        return json(latest, 201);
      }
      return json(
        await packageReviewDecisionCurrent(f, latest ? [latest] : []),
      );
    }),
  );
  render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst("保留草稿：需补查签章");
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "确认此项判断" }),
  );
  await screen.findByText("PACKAGE_REVIEW_DECISION_HEAD_CHANGED");
  await waitFor(() =>
    expect(
      within(firstArticle()).getByText(otherBody.reason),
    ).toBeInTheDocument(),
  );
  expect(
    within(firstArticle()).getByLabelText("本次人工理由（必填）"),
  ).toHaveValue("保留草稿：需补查签章");
  expect(within(firstArticle()).getAllByRole("checkbox")[0]).toBeChecked();
  expect(posts).toHaveLength(1);
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "需要复查" }),
  );
  await screen.findByText("原请求已核对受理");
  expect(posts).toHaveLength(2);
  expect(posts[1].key).not.toBe(posts[0].key);
  expect(posts[1].body.expected_head).toEqual({
    id: other.manifest.id,
    digest: other.digest,
  });
  expect(posts[1].body.reason).toBe("保留草稿：需补查签章");
});

it("preserves a draft across true matrix pages, filters and remount without submitting it", async () => {
  f = await packageReviewFixture(25);
  const current = await packageReviewDecisionCurrent(f),
    fetcher = vi.fn(async () => json(current));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst("跨页保留的人工草稿");
  await userEvent.click(screen.getByRole("button", { name: "下一页要求" }));
  expect(screen.getAllByRole("article")).toHaveLength(5);
  await userEvent.click(screen.getByRole("button", { name: "上一页要求" }));
  expect(
    within(firstArticle()).getByLabelText("本次人工理由（必填）"),
  ).toHaveValue("跨页保留的人工草稿");
  await userEvent.selectOptions(
    screen.getByLabelText("筛选核查结论"),
    "unable_to_judge",
  );
  await userEvent.selectOptions(screen.getByLabelText("筛选核查结论"), "all");
  expect(
    within(firstArticle()).getByLabelText("本次人工理由（必填）"),
  ).toHaveValue("跨页保留的人工草稿");
  view.unmount();
  render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  expect(
    within(firstArticle()).getByLabelText("本次人工理由（必填）"),
  ).toHaveValue("跨页保留的人工草稿");
  expect(within(firstArticle()).getAllByRole("checkbox")[0]).toBeChecked();
  expect(
    loadPackageReviewDecisionRecord({ ...f.props, run: f.completed }).pending,
  ).toBeNull();
});

it("ignores a late accepted response after switching runs and leaves the original pending key recoverable", async () => {
  let resolve!: (value: Response) => void,
    saved: Posted | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") {
        saved = post(options);
        return new Promise<Response>((done) => {
          resolve = done;
        });
      }
      return json(await packageReviewDecisionCurrent(f));
    }),
  );
  const view = render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst();
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "确认此项判断" }),
  );
  await waitFor(() => expect(saved).not.toBeNull());
  const next = structuredClone(f.completed);
  next.id = id(999);
  next.result!.manifest.run_id = next.id;
  next.result!.digest = await frozenManifestDigest(next.result!.manifest);
  view.rerender(<HumanDecisions {...f.props} run={next} />);
  const ack = await packageReviewDecisionReply(f, saved!.body);
  await act(async () => {
    resolve(json(ack, 201));
  });
  expect(screen.queryByText("原请求已核对受理")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "恢复原人工处置请求" }),
  ).not.toBeInTheDocument();
  expect(
    loadPackageReviewDecisionRecord({ ...f.props, run: f.completed }).pending
      ?.key,
  ).toBe(saved!.key);
});

it("keeps the accepted request recoverable if storage fails after its ACK and does not claim that it was unsent", async () => {
  let deny = false,
    head: PackageReviewHumanDecisionView | null = null;
  const originalSet = Storage.prototype.setItem,
    posts: Posted[] = [];
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (deny) throw new DOMException("full", "QuotaExceededError");
    originalSet.call(this, key, value);
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") {
        const request = post(options);
        posts.push(request);
        head ??= await packageReviewDecisionReply(f, request.body);
        deny = posts.length === 1;
        return json(head, 201);
      }
      return json(await packageReviewDecisionCurrent(f, head ? [head] : []));
    }),
  );
  render(<HumanDecisions {...f.props} run={f.completed} />);
  await openFirst();
  await fillFirst();
  await userEvent.click(
    within(firstArticle()).getByRole("button", { name: "确认此项判断" }),
  );
  await screen.findByText(/浏览器未能更新人工处置恢复记录/);
  expect(screen.getByText("原请求已核对受理")).toBeInTheDocument();
  expect(screen.queryByText(/未发送新的请求/)).not.toBeInTheDocument();
  deny = false;
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原人工处置请求" }),
  );
  await waitFor(() =>
    expect(
      loadPackageReviewDecisionRecord({ ...f.props, run: f.completed }).pending,
    ).toBeNull(),
  );
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
});
