import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringGenerationBatch } from "./AuthoringGenerationBatch";
import type {
  AuthoringGenerationBatchCreateRequest,
  AuthoringGenerationBatchResolveRequest,
  AuthoringGenerationBatchRetryRequest,
  AuthoringGenerationBatchReceipt,
} from "./contracts";
import type { PendingGeneration } from "./authoringGenerationRecovery";
import {
  generationPath,
  generationStorageKey,
  readGenerationRecovery,
  storeGenerationRecovery,
} from "./authoringGenerationRecovery";
import {
  generationCapabilities,
  generationFixture,
  generationHead,
  generationId,
  generationReceipt,
  generationScope,
} from "./authoringGenerationFixtures.test-support";

const base = `/api/v1${generationPath(generationScope)}`;
const response = (data: unknown, status = 200, etag?: string) =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
type Kind = "create" | "retry" | "resolve";
async function setup() {
  const fixture = await generationFixture();
  const server = {
    ...fixture,
    capabilities: structuredClone(generationCapabilities),
    documents: [] as unknown[],
    writes: [] as { kind: Kind; options: RequestInit }[],
    detailReads: 0,
    candidateReads: 0,
    historyReads: 0,
    onWrite: null as
      | null
      | ((kind: Kind, options: RequestInit) => Promise<Response>),
  };
  const receipts = new Map<string, AuthoringGenerationBatchReceipt>();
  async function accept(kind: Kind, options: RequestInit) {
    const headers = new Headers(options.headers),
      key = headers.get("Idempotency-Key")!;
    if (receipts.has(key)) return response(receipts.get(key));
    const raw = JSON.parse(String(options.body)) as
      | AuthoringGenerationBatchCreateRequest
      | AuthoringGenerationBatchRetryRequest
      | AuthoringGenerationBatchResolveRequest;
    const common = {
      key,
      etag: headers.get("If-Match")!,
      baseDraftRevision: server.batch.base_draft_revision,
    };
    const pending: PendingGeneration =
      kind === "create"
        ? {
            ...common,
            kind,
            body: raw as AuthoringGenerationBatchCreateRequest,
            baseDraftRevision: (raw as AuthoringGenerationBatchCreateRequest)
              .base_draft_revision,
          }
        : kind === "retry"
          ? {
              ...common,
              kind,
              batchId: server.batch.batch_id,
              body: raw as AuthoringGenerationBatchRetryRequest,
            }
          : {
              ...common,
              kind,
              batchId: server.batch.batch_id,
              body: raw as AuthoringGenerationBatchResolveRequest,
            };
    const receipt = await generationReceipt(server.batch, pending);
    if (pending.kind === "create") {
      server.batch.base_draft_revision = pending.body.base_draft_revision;
      server.batch.base_draft_etag = pending.etag;
      server.batch.reason = pending.body.reason;
      server.batch.preparation = { ...receipt.command, request: pending.body };
      server.batch.sections = pending.body.sections.map((section) => ({
        ...server.batch.sections.find(
          (item) => item.section_id === section.section_id,
        )!,
        ...section,
      }));
      server.batch.section_count = server.batch.sections.length;
      server.batch.ready_count = server.batch.sections.length;
      server.batch.budget.limit_minor = pending.body.total_limit_minor;
      for (const section of server.batch.sections)
        section.budget.limit_minor = section.budget_limit_minor;
      for (const candidate of server.candidates) {
        candidate.base_draft_revision = pending.body.base_draft_revision;
        candidate.base_draft_etag = pending.etag;
        candidate.base_section_revision =
          pending.body.sections.find(
            (section) => section.section_id === candidate.section_id,
          )?.base_section_revision ?? candidate.base_section_revision;
      }
    } else if (pending.kind === "retry") {
      const section = server.batch.sections.find(
        (item) => item.section_id === pending.body.section_id,
      )!;
      const previous = section.attempts.at(-1)!;
      section.current_attempt++;
      section.attempts.push({
        ...previous,
        attempt: section.current_attempt,
        job_id: receipt.created_job_ids[0],
        operation_id: generationId(94),
        writing_plan_id: generationId(95),
        state: "queued",
        publication_state: "pending",
        action_id: null,
        candidate_digest: null,
        candidate_url: null,
        charged_minor: null,
        budget_state: "held",
        requires_reconciliation: false,
        error_code: null,
        retry_allowed: false,
        retry_blocked_reason: {
          code: "RUNNING",
          message: "当前尝试尚未结束。",
        },
      });
    } else {
      server.batch.state = receipt.batch_state;
      server.batch.resolution = receipt;
      for (const candidate of server.candidates)
        candidate.state = receipt.applied_section_ids.includes(
          candidate.section_id,
        )
          ? "executed"
          : "rejected";
    }
    server.batch.etag = '"batch-after-command"';
    receipts.set(key, receipt);
    return response(receipt);
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/authoring/generation-batch-capabilities")
        return response(server.capabilities);
      if (url === `/api/v1/bids/${generationScope.bidId}/materials`)
        return response({
          bid_id: generationScope.bidId,
          documents: server.documents,
          material_revision: 1,
          conflicts: [],
          snapshot_id: generationId(299),
        });
      const kind: Kind | null =
        options?.method !== "POST"
          ? null
          : url === base
            ? "create"
            : url.endsWith("/retry")
              ? "retry"
              : url.endsWith("/resolve")
                ? "resolve"
                : null;
      if (kind && options) {
        server.writes.push({ kind, options });
        return server.onWrite
          ? server.onWrite(kind, options)
          : accept(kind, options);
      }
      if (url === base) {
        server.historyReads++;
        return response({
          bid_id: generationScope.bidId,
          draft_id: generationScope.draftId,
          items: [server.batch],
          has_more: false,
          next_cursor: null,
        });
      }
      if (url === `${base}/${server.batch.batch_id}`) {
        server.detailReads++;
        return response(server.batch, 200, server.batch.etag);
      }
      const candidate = server.candidates.find(
        (item) =>
          url ===
          `${base}/${server.batch.batch_id}/candidates/${item.action_id}`,
      );
      if (candidate) {
        server.candidateReads++;
        return response(candidate, 200, candidate.etag);
      }
      return response(
        {
          code: "TEST_ROUTE_NOT_FOUND",
          message: `Synthetic route missing: ${url}`,
        },
        404,
      );
    }),
  );
  return Object.assign(server, { accept });
}
type Server = Awaited<ReturnType<typeof setup>>;
function seed(server: Server) {
  storeGenerationRecovery({
    version: 1,
    scope: generationScope,
    pending: null,
    lastBatchId: server.batch.batch_id,
  });
}
function mount(
  overrides: Partial<ComponentProps<typeof AuthoringGenerationBatch>> = {},
) {
  const props = {
    ...generationScope,
    draft: structuredClone(generationHead.data),
    disabled: false,
    prepare: vi.fn(async () => structuredClone(generationHead)),
    onChanged: vi.fn(async () => undefined),
    onBusy: vi.fn(),
    ...overrides,
  };
  return { ...render(<AuthoringGenerationBatch {...props} />), props };
}
async function fillForm() {
  await userEvent.click(
    screen.getByRole("button", { name: "设置新的多章编写批次" }),
  );
  await userEvent.click(
    await screen.findByRole("checkbox", { name: "本批选择章节：施工组织" }),
  );
  await userEvent.click(
    screen.getByRole("checkbox", { name: "本批选择章节：质量保障" }),
  );
  fireEvent.change(screen.getByLabelText("施工组织的编写目标"), {
    target: { value: "完善施工组织的多处正文" },
  });
  fireEvent.change(screen.getByLabelText("质量保障的编写目标"), {
    target: { value: "完善质量保障的多处正文" },
  });
  fireEvent.change(screen.getByLabelText("施工组织的额度"), {
    target: { value: "0.1" },
  });
  fireEvent.change(screen.getByLabelText("质量保障的额度"), {
    target: { value: "0.1" },
  });
  fireEvent.change(screen.getByLabelText("本批总预算"), {
    target: { value: "0.2" },
  });
  fireEvent.change(screen.getByLabelText("本次批量编写理由"), {
    target: { value: "明确预算后逐章核对" },
  });
}
async function reviewFirst() {
  await userEvent.click(
    await screen.findByRole("button", { name: "核对施工组织的完整前后稿" }),
  );
  const checkbox = await screen.findByRole("checkbox", {
    name: "已核对完整前后稿，选择应用施工组织",
  });
  await waitFor(() => expect(checkbox).toBeEnabled());
  await userEvent.click(checkbox);
  fireEvent.change(screen.getByLabelText("本次应用或关闭理由"), {
    target: { value: "已核对多处修改、表格和未选内容" },
  });
  return checkbox;
}
function failSecond(server: Server, unknown = false) {
  const section = server.batch.sections[1],
    attempt = section.attempts[0];
  Object.assign(attempt, {
    state: "failed",
    publication_state: "failed",
    action_id: null,
    candidate_digest: null,
    candidate_url: null,
    error_code: "SYNTHETIC_PROVIDER_FAILURE",
    budget_state: unknown ? "unknown" : "settled",
    requires_reconciliation: unknown,
    charged_minor: unknown ? null : 2000000,
    retry_allowed: !unknown,
    retry_blocked_reason: unknown
      ? { code: "RECONCILIATION_REQUIRED", message: "先核清原尝试费用。" }
      : null,
  });
  section.budget.requires_reconciliation = unknown;
  server.batch.budget.requires_reconciliation = unknown;
  server.batch.ready_count = 1;
  server.batch.failed_count = 1;
}
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("saves before spending and freezes exact head, chapter revisions, goals, sources and integer budget", async () => {
  const server = await setup();
  server.documents = [
    {
      id: generationId(250),
      bid_id: generationScope.bidId,
      filename: "确切补遗.pdf",
      file_revision: 3,
      sha256: "6".repeat(64),
      role: "supplement",
      artifact_kind: null,
      parse_coverage: "complete",
    },
  ];
  let finish!: (value: typeof generationHead) => void;
  const prepare = vi.fn(
    () =>
      new Promise<typeof generationHead>((resolve) => {
        finish = resolve;
      }),
  );
  mount({ prepare });
  await fillForm();
  const group = screen.getByRole("group", { name: "施工组织" });
  await userEvent.click(
    within(group).getByText("本章确切资料版本 · 已选 0 / 30"),
  );
  await userEvent.click(
    within(group).getByRole("checkbox", {
      name: "施工组织的来源：确切补遗.pdf版本3",
    }),
  );
  const submit = screen.getByRole("button", {
    name: "保存当前编辑并按预算生成 2 章候选",
  });
  fireEvent.change(screen.getByLabelText("本批总预算"), {
    target: { value: "0.1" },
  });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("本批总预算"), {
    target: { value: "0.2000000001" },
  });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("本批总预算"), {
    target: { value: "0.2" },
  });
  await userEvent.click(submit);
  expect(prepare).toHaveBeenCalledTimes(1);
  expect(server.writes).toHaveLength(0);
  const saved = structuredClone(generationHead);
  saved.data.revision = 8;
  saved.etag = '"draft-8"';
  saved.data.sections[0].revision = 4;
  saved.data.sections[1].revision = 5;
  await act(async () => finish(saved));
  await screen.findByRole("region", { name: "批次操作回执" });
  expect(server.writes).toHaveLength(1);
  const request = JSON.parse(String(server.writes[0].options.body));
  expect(request).toMatchObject({
    base_draft_revision: 8,
    amount_scale: 1000000000,
    total_limit_minor: 200000000,
  });
  expect(request.sections).toEqual([
    {
      section_id: generationId(10),
      base_section_revision: 4,
      instruction: "完善施工组织的多处正文",
      source_version_ids: [generationId(250)],
      selected_node_ids: null,
      max_tokens: 1024,
      budget_limit_minor: 100000000,
    },
    {
      section_id: generationId(11),
      base_section_revision: 5,
      instruction: "完善质量保障的多处正文",
      source_version_ids: [],
      selected_node_ids: null,
      max_tokens: 1024,
      budget_limit_minor: 100000000,
    },
  ]);
  expect(new Headers(server.writes[0].options.headers).get("If-Match")).toBe(
    '"draft-8"',
  );
  expect(readGenerationRecovery(generationScope).pending).toBeNull();
});
it("previews complete before/after merged tables and applies only a selected successful chapter once", async () => {
  const server = await setup();
  failSecond(server);
  seed(server);
  const { props } = mount();
  const checkbox = await reviewFirst();
  const preview = screen.getByLabelText("施工组织的候选核对");
  expect(
    within(preview).getByRole("heading", { name: "施工组织：原稿" }),
  ).toBeInTheDocument();
  expect(
    within(preview).getByRole("heading", { name: "施工组织：候选稿" }),
  ).toBeInTheDocument();
  expect(within(preview).getAllByRole("table")).toHaveLength(2);
  expect(within(preview).getAllByText("合并表头")).toHaveLength(2);
  expect(
    within(preview).getAllByText("这一段保持原样，人工确认内容不被替换。"),
  ).toHaveLength(2);
  expect(within(preview).getByText("施工组织候选目标")).toBeInTheDocument();
  expect(within(preview).getByText("施工组织候选步骤")).toBeInTheDocument();
  expect(checkbox).toBeChecked();
  expect(server.writes).toHaveLength(0);
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  expect(await screen.findByText("已确认应用")).toBeInTheDocument();
  expect(server.writes).toHaveLength(1);
  expect(props.prepare).toHaveBeenCalledTimes(1);
  expect(props.onChanged).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(server.writes[0].options.body)).selections).toEqual([
    {
      section_id: generationId(10),
      attempt: 1,
      job_id: generationId(40),
      action_id: generationId(70),
      candidate_digest: "e".repeat(64),
    },
  ]);
  expect(server.batch.resolution?.unselected_section_ids).toEqual([
    generationId(11),
  ]);
});
it("keeps polling worker-success publication-pending and does not permit premature partial application", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const server = await setup();
  const original = structuredClone(server.batch.sections[1].attempts[0]);
  Object.assign(server.batch.sections[1].attempts[0], {
    publication_state: "pending",
    action_id: null,
    candidate_digest: null,
    candidate_url: null,
  });
  seed(server);
  mount();
  await reviewFirst();
  expect(screen.getByText(/模型任务已完成，候选整理中/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  ).toBeDisabled();
  const reads = server.detailReads;
  server.batch.sections[1].attempts[0] = original;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000);
  });
  await screen.findByRole("button", { name: "核对质量保障的完整前后稿" });
  expect(server.detailReads).toBeGreaterThan(reads);
  expect(server.writes).toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  ).toBeEnabled();
});
it("preserves unknown provider expense and blocks retry or partial application until reconciliation", async () => {
  const server = await setup();
  failSecond(server, true);
  seed(server);
  mount();
  await reviewFirst();
  expect(screen.getByText(/此尝试的调用或费用状态未核清/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /明确重试质量保障/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  ).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});
it("requires a new explicit reason to retry only the authorized failed chapter under its old cumulative budget", async () => {
  const server = await setup();
  failSecond(server);
  seed(server);
  mount();
  const button = await screen.findByRole("button", {
    name: "明确重试质量保障（继续占用本章额度）",
  });
  expect(button).toBeDisabled();
  expect(server.writes).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("质量保障的重试理由"), {
    target: { value: "原费用已核清，明确重试该章" },
  });
  await userEvent.click(button);
  await screen.findByText("已确认新尝试");
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].kind).toBe("retry");
  expect(JSON.parse(String(server.writes[0].options.body))).toEqual({
    batch_digest: server.batch.batch_digest,
    section_id: generationId(11),
    previous_attempt: 1,
    previous_job_id: generationId(41),
    reason: "原费用已核清，明确重试该章",
  });
  expect(new Headers(server.writes[0].options.headers).get("If-Match")).toBe(
    generationHead.etag,
  );
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("质量保障的编写状态")).getByText("等待执行"),
    ).toBeInTheDocument(),
  );
  expect(server.batch.sections[1].budget_limit_minor).toBe(100000000);
});
it("recovers a lost create ACK with the original key/body/etag after remount even when new work is disabled", async () => {
  const server = await setup();
  server.onWrite = async (kind, options) => {
    await server.accept(kind, options);
    throw new TypeError("ACK lost");
  };
  const first = mount();
  await fillForm();
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前编辑并按预算生成 2 章候选" }),
  );
  await screen.findByRole("button", { name: "恢复原批次请求结果" });
  expect(readGenerationRecovery(generationScope).pending?.kind).toBe("create");
  first.unmount();
  server.onWrite = null;
  server.capabilities.enabled = false;
  server.capabilities.unavailable_reason = {
    code: "MODEL_DISABLED",
    message: "模型已暂停。",
  };
  const prepare = vi.fn(async () => {
    throw new Error("Recovery must not take a new head");
  });
  mount({ disabled: true, prepare });
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原批次请求结果" }),
  );
  await screen.findByRole("region", { name: "批次操作回执" });
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1].options.body).toBe(server.writes[0].options.body);
  expect(
    new Headers(server.writes[1].options.headers).get("Idempotency-Key"),
  ).toBe(new Headers(server.writes[0].options.headers).get("Idempotency-Key"));
  expect(new Headers(server.writes[1].options.headers).get("If-Match")).toBe(
    generationHead.etag,
  );
  expect(prepare).not.toHaveBeenCalled();
  expect(readGenerationRecovery(generationScope).pending).toBeNull();
});
it("recovers a committed atomic apply after lost ACK without rebasing to the now newer draft", async () => {
  const server = await setup();
  seed(server);
  server.onWrite = async (kind, options) => {
    await server.accept(kind, options);
    throw new TypeError("ACK lost after commit");
  };
  const first = mount();
  await reviewFirst();
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  await screen.findByRole("button", { name: "恢复原批次请求结果" });
  expect(server.batch.state).toBe("applied");
  first.unmount();
  server.onWrite = null;
  const prepare = vi.fn(async () => {
    throw new Error("Do not rebase recovered command");
  });
  mount({
    disabled: true,
    draft: { ...generationHead.data, revision: 8 },
    prepare,
  });
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原批次请求结果" }),
  );
  await waitFor(() =>
    expect(readGenerationRecovery(generationScope).pending).toBeNull(),
  );
  expect(server.writes[1].options.body).toBe(server.writes[0].options.body);
  expect(
    new Headers(server.writes[1].options.headers).get("Idempotency-Key"),
  ).toBe(new Headers(server.writes[0].options.headers).get("Idempotency-Key"));
  expect(prepare).not.toHaveBeenCalled();
});
it("retains the pending paid request when an ACK contains a forged scoped request digest", async () => {
  const server = await setup();
  server.onWrite = async (kind, options) => {
    const result = await server.accept(kind, options);
    const receipt = await result.json();
    receipt.command.request_digest = "0".repeat(64);
    return response(receipt);
  };
  mount();
  await fillForm();
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前编辑并按预算生成 2 章候选" }),
  );
  await screen.findByText(/原请求保留，尚未确认操作成功/);
  expect(readGenerationRecovery(generationScope).pending?.kind).toBe("create");
  expect(
    screen.queryByRole("region", { name: "批次操作回执" }),
  ).not.toBeInTheDocument();
});
it("keeps the full candidate and explicit selection after a definitive server CAS rejection", async () => {
  const server = await setup();
  seed(server);
  server.onWrite = async () =>
    response(
      { code: "CAS_CONFLICT", message: "草稿保存条件已变化", retryable: false },
      412,
    );
  mount();
  const selected = await reviewFirst();
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  await screen.findByText("草稿保存条件已变化");
  await waitFor(() =>
    expect(readGenerationRecovery(generationScope).pending).toBeNull(),
  );
  expect(selected).toBeChecked();
  expect(screen.getByText("施工组织候选步骤")).toBeInTheDocument();
  expect(server.writes).toHaveLength(1);
});
it("blocks apply when flushing advances the base draft and preserves the candidate without an automatic rebase", async () => {
  const server = await setup();
  seed(server);
  mount({
    prepare: vi.fn(async () => ({
      data: { ...generationHead.data, revision: 8 },
      etag: '"draft-8"',
    })),
  });
  const selected = await reviewFirst();
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  await screen.findByText(/保存后的草稿已偏离本批冻结基准/);
  expect(selected).toBeChecked();
  expect(server.writes).toHaveLength(0);
});
it("checks expiry again after a delayed save before issuing the atomic application", async () => {
  let now = Date.parse("2026-10-21T13:00:00Z");
  vi.spyOn(Date, "now").mockImplementation(() => now);
  const server = await setup();
  seed(server);
  server.candidates[0].expires_at = new Date(now + 1000).toISOString();
  let finish!: (value: typeof generationHead) => void;
  mount({
    prepare: vi.fn(
      () =>
        new Promise<typeof generationHead>((resolve) => {
          finish = resolve;
        }),
    ),
  });
  await reviewFirst();
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  now += 2000;
  await act(async () => finish(generationHead));
  await screen.findByText(/候选在保存当前编辑期间已过期/);
  expect(server.writes).toHaveLength(0);
});
it("allows read-only history despite corrupt recovery and preserves the original corrupt bytes", async () => {
  const server = await setup();
  const raw = '{"version":1,"pending":"damaged"}';
  sessionStorage.setItem(generationStorageKey(generationScope), raw);
  mount();
  await screen.findByText(/恢复记录无法核验/);
  await userEvent.click(screen.getByRole("button", { name: "读取批次历史" }));
  await userEvent.click(
    await screen.findByRole("button", {
      name: `查看批次 ${server.batch.batch_id.slice(-8)}`,
    }),
  );
  await screen.findByRole("button", { name: "核对施工组织的完整前后稿" });
  expect(server.historyReads).toBe(1);
  expect(server.writes).toHaveLength(0);
  expect(sessionStorage.getItem(generationStorageKey(generationScope))).toBe(
    raw,
  );
});
it("does not send a paid request if saving its recovery record fails", async () => {
  const server = await setup();
  mount();
  await fillForm();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前编辑并按预算生成 2 章候选" }),
  );
  await screen.findByText(/浏览器未能保存批次恢复记录/);
  expect(server.writes).toHaveLength(0);
});
it("keeps the recovery request when a validated ACK arrives after unmount", async () => {
  const server = await setup();
  let finish!: (value: Response) => void;
  server.onWrite = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  const page = mount();
  await fillForm();
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前编辑并按预算生成 2 章候选" }),
  );
  await waitFor(() => expect(server.writes).toHaveLength(1));
  const original = readGenerationRecovery(generationScope);
  page.unmount();
  await act(async () =>
    finish(await server.accept("create", server.writes[0].options)),
  );
  expect(readGenerationRecovery(generationScope)).toEqual(original);
});
it("labels closed published candidates as applied or not applied instead of offering a ready result", async () => {
  const server = await setup();
  seed(server);
  mount();
  await reviewFirst();
  await userEvent.click(
    screen.getByRole("button", { name: "一次应用已核对的 1 章并结束本批" }),
  );
  await screen.findByText("已确认应用");
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("质量保障的编写状态")).getByText(
        "未应用（已关闭）",
      ),
    ).toBeInTheDocument(),
  );
  expect(
    within(screen.getByLabelText("施工组织的编写状态")).getByText("已应用"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /一次应用已核对的/ }),
  ).not.toBeInTheDocument();
});
