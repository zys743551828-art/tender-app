import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { HistoricalImports } from "./HistoricalImports";
import type {
  HistoricalImportBatch,
  HistoricalImportReceipt,
  HistoricalImportRequest,
} from "./contracts";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  historicalImportEtag,
  historicalImportPath,
  type HistoricalPending,
} from "./historicalImportProtocol";
import {
  historicalStorageKey,
  readHistoricalRecovery,
  writeHistoricalRecovery,
} from "./historicalImportRecovery";
import {
  importConfirmed,
  importFixture,
  importId,
  importMember,
  importReceipt,
} from "./historicalImportFixtures.test-support";

const response = (body: unknown, status = 200, etag?: string) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
type Write = { path: string; body: unknown; headers: Headers };
async function setup(count = 2) {
  const f = await importFixture(count);
  const server = {
    ...f,
    current: structuredClone(f.batch),
    rows: f.body.records.map(
      (record, index): HistoricalImportBatch["records"][number] => ({
        batch_id: f.batch.id,
        external_record_id: record.external_record_id,
        source_digest: String((index % 9) + 1).repeat(64),
        state: "pending" as HistoricalImportBatch["records"][number]["state"],
        bid_id: record.bid_id,
        errors: [] as string[],
      }),
    ),
    writes: [] as Write[],
    reads: [] as string[],
    failLast: false,
    onPreview: null as ((write: Write) => Promise<Response>) | null,
    onConfirm: null as ((write: Write) => Promise<Response>) | null,
    onRead: null as ((path: string) => Response | null) | null,
  };
  const receipts = new Map<string, HistoricalImportReceipt>();
  const tag = () =>
    historicalImportEtag(server.current.id, server.current.revision);
  async function acceptPreview(write: Write) {
    const key = write.headers.get("Idempotency-Key")!;
    if (receipts.has(key)) {
      const prior = receipts.get(key)!;
      return response(
        prior,
        201,
        historicalImportEtag(prior.id, prior.revision),
      );
    }
    const pending: HistoricalPending = {
      kind: "preview",
      key,
      body: write.body as HistoricalImportRequest,
      etag: null,
    };
    const receipt = await importReceipt(server.current, pending);
    receipts.set(key, receipt);
    return response(receipt, 201, tag());
  }
  async function acceptConfirm(write: Write) {
    const key = write.headers.get("Idempotency-Key")!;
    if (receipts.has(key)) {
      const prior = receipts.get(key)!;
      return response(
        prior,
        200,
        historicalImportEtag(prior.id, prior.revision),
      );
    }
    const pending: HistoricalPending = {
      kind: "confirm",
      key,
      body: {},
      etag: write.headers.get("If-Match")!,
      batchId: server.current.id,
      baseRevision: server.current.revision,
      manifestBlobId: server.current.manifest_blob_id,
      manifestDigest: server.source.manifest_digest,
    };
    server.current = importConfirmed(server.current, server.failLast);
    server.rows = server.current.records;
    const receipt = await importReceipt(server.current, pending);
    receipts.set(key, receipt);
    return response(receipt, 200, tag());
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const path = String(input);
      if (options?.method === "POST") {
        const write = {
          path,
          body: JSON.parse(String(options.body)),
          headers: new Headers(options.headers),
        };
        server.writes.push(write);
        if (path === "/api/v1/research/import-previews")
          return server.onPreview
            ? server.onPreview(write)
            : acceptPreview(write);
        if (path === `/api/v1${historicalImportPath(f.batch.id)}/confirm`)
          return server.onConfirm
            ? server.onConfirm(write)
            : acceptConfirm(write);
        throw new Error(`Unexpected POST ${path}`);
      }
      server.reads.push(path);
      const overridden = server.onRead?.(path);
      if (overridden) return overridden;
      if (path.startsWith(`/api/v1${historicalImportPath(f.batch.id)}?`)) {
        const offset = Number(
          new URL(path, "http://example.test").searchParams.get("offset") ?? 0,
        );
        return response(
          {
            ...server.current,
            records: server.rows.slice(offset, offset + 100),
            next_offset:
              offset + 100 < server.rows.length ? offset + 100 : null,
          },
          200,
          tag(),
        );
      }
      if (path === `/api/v1${historicalImportPath(f.batch.id)}/source`)
        return response(server.source);
      if (path.startsWith("/api/v1/research/imports?"))
        return response({
          items: [
            {
              id: server.current.id,
              mode: server.current.mode,
              revision: server.current.revision,
              created_by: importMember,
              created_at: "2026-10-21T01:00:00.123456Z",
              counts: server.current.counts,
            },
          ],
          next_offset: null,
        });
      throw new Error(`Unexpected GET ${path}`);
    }),
  );
  return { server, acceptPreview, acceptConfirm };
}
function mount() {
  const onImported = vi.fn();
  return {
    ...render(
      <HistoricalImports memberId={importMember} onImported={onImported} />,
    ),
    onImported,
  };
}
async function open(user: ReturnType<typeof userEvent.setup>) {
  const button = screen.queryByRole("button", { name: "打开历史导入" });
  if (button) await user.click(button);
}
async function prepare(
  user: ReturnType<typeof userEvent.setup>,
  body: HistoricalImportRequest,
) {
  await open(user);
  fireEvent.change(
    screen.getByRole("textbox", { name: "清单 JSON（可修正后重新校验）" }),
    { target: { value: JSON.stringify(body) } },
  );
  await user.click(screen.getByRole("button", { name: "校验本地清单" }));
}
async function create(
  user: ReturnType<typeof userEvent.setup>,
  body: HistoricalImportRequest,
) {
  await prepare(user, body);
  await user.click(
    screen.getByRole("button", {
      name: `创建并保存导入预检查（${body.records.length} 条）`,
    }),
  );
  await screen.findByText(/已保存预检查，尚未登记实交与成绩/);
}
async function sourceAndAgree(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("button", { name: "读取并核对本批原始清单" }),
  );
  await screen.findByText(/已核对确切原始清单/);
  await user.click(screen.getByRole("checkbox", { name: /我已核对全部/ }));
}
const confirmButton = () =>
  screen.getByRole("button", { name: "确认登记本批可处理的历史实交与成绩" });
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it("keeps local checks unsaved, persists a preview explicitly, then confirms only the exact original manifest with empty body and strong ETag", async () => {
  const { server } = await setup(),
    user = userEvent.setup(),
    mounted = mount();
  await prepare(user, server.body);
  expect(server.writes).toHaveLength(0);
  await user.click(
    screen.getByRole("button", { name: "创建并保存导入预检查（2 条）" }),
  );
  await screen.findByText(/已保存预检查，尚未登记实交与成绩/);
  expect(confirmButton()).toBeDisabled();
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].body).toEqual(server.body);
  await sourceAndAgree(user);
  expect(confirmButton()).toBeEnabled();
  await user.click(confirmButton());
  await waitFor(() => expect(mounted.onImported).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(readHistoricalRecovery(importMember).pending).toBeNull(),
  );
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1].body).toEqual({});
  expect(server.writes[1].headers.get("If-Match")).toBe(server.etag);
  expect(
    server.reads.filter((path) => path.endsWith("?limit=100")).length,
  ).toBeGreaterThanOrEqual(2);
  expect(
    await screen.findByText(/本批已确认：2 条已登记或复用，0 条冲突或失败/),
  ).toBeVisible();
});
it("restores a lost preview ACK after remount using the same canonical body and key; reading history does not clear pending", async () => {
  const { server, acceptPreview } = await setup(),
    user = userEvent.setup();
  server.onPreview = async (write) => {
    await acceptPreview(write);
    throw new TypeError("ACK lost");
  };
  const first = mount();
  await prepare(user, server.body);
  await user.click(
    screen.getByRole("button", { name: "创建并保存导入预检查（2 条）" }),
  );
  await screen.findByText("预检查保存结果尚未核对");
  const pending = readHistoricalRecovery(importMember).pending;
  expect(pending?.kind).toBe("preview");
  first.unmount();
  server.onPreview = acceptPreview;
  mount();
  await user.click(screen.getByRole("button", { name: "读取导入批次目录" }));
  await screen.findByRole("button", { name: /待确认预检查 · 2 条/ });
  expect(readHistoricalRecovery(importMember).pending).toEqual(pending);
  await user.click(screen.getByRole("button", { name: "恢复原预检查请求" }));
  await screen.findByText(/已保存 2 条预检查记录/);
  expect(server.writes[1].body).toEqual(server.writes[0].body);
  expect(server.writes[1].headers.get("Idempotency-Key")).toBe(
    server.writes[0].headers.get("Idempotency-Key"),
  );
  expect(readHistoricalRecovery(importMember).pending).toBeNull();
});
it("restores a committed confirm after current batch changed and retains its original empty body, key and ETag", async () => {
  const { server, acceptConfirm } = await setup(),
    user = userEvent.setup(),
    first = mount();
  await create(user, server.body);
  await sourceAndAgree(user);
  server.onConfirm = async (write) => {
    await acceptConfirm(write);
    throw new TypeError("ACK lost");
  };
  await user.click(confirmButton());
  await screen.findByText("导入确认结果尚未核对");
  const saved = readHistoricalRecovery(importMember).pending;
  first.unmount();
  server.onConfirm = acceptConfirm;
  const second = mount();
  await screen.findByText(/已确认导入，逐项结果已保留/);
  expect(readHistoricalRecovery(importMember).pending).toEqual(saved);
  await user.click(screen.getByRole("button", { name: "恢复原确认请求" }));
  await waitFor(() => expect(second.onImported).toHaveBeenCalledOnce());
  expect(server.writes[2].body).toEqual({});
  expect(server.writes[2].headers.get("Idempotency-Key")).toBe(
    server.writes[1].headers.get("Idempotency-Key"),
  );
  expect(server.writes[2].headers.get("If-Match")).toBe(server.etag);
});
it.each(["wrong_actor", "wrong_digest", "generic_conflict"])(
  "keeps the exact original preview pending for %s",
  async (kind) => {
    const { server, acceptPreview } = await setup(),
      user = userEvent.setup();
    server.onPreview = async (write) => {
      if (kind === "generic_conflict")
        return response(
          { message: "原命令未能核对", code: "IDEMPOTENCY_CONFLICT" },
          409,
        );
      const reply = await acceptPreview(write),
        body = (await reply.json()) as HistoricalImportReceipt;
      if (kind === "wrong_actor") body.command.actor_id = importId(99);
      else body.command.request_digest = "f".repeat(64);
      return response(body, 201, server.etag);
    };
    mount();
    await prepare(user, server.body);
    await user.click(
      screen.getByRole("button", { name: "创建并保存导入预检查（2 条）" }),
    );
    await screen.findByRole("button", { name: "恢复原预检查请求" });
    await screen.findByRole("alert");
    expect(readHistoricalRecovery(importMember).pending?.kind).toBe("preview");
    expect(server.writes).toHaveLength(1);
    expect(screen.getByRole("button", { name: "校验本地清单" })).toBeDisabled();
  },
);
it("does not POST when recovery storage fails", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount();
  await prepare(user, server.body);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  await user.click(
    screen.getByRole("button", { name: "创建并保存导入预检查（2 条）" }),
  );
  await screen.findByText(/浏览器无法保存导入恢复记录/);
  expect(server.writes).toHaveLength(0);
});
it("prepares only explicitly selected failed records for correction, preserving zero/unknown and leaving imported rows and old batch untouched", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  server.failLast = true;
  mount();
  await create(user, server.body);
  await sourceAndAgree(user);
  await user.click(confirmButton());
  await screen.findByText(/本批已确认：1 条已登记或复用，1 条冲突或失败/);
  await screen.findByText(/已确认导入，逐项结果已保留/);
  await user.click(
    screen.getByRole("button", { name: "读取并核对本批原始清单" }),
  );
  await screen.findByText(/已核对确切原始清单/);
  expect(
    screen.getByText("原件字节与登记摘要不符，本项未导入。"),
  ).toBeVisible();
  const choice = screen.getByRole("checkbox", {
    name: /仅选择异常项 历史-0002/,
  });
  expect(
    screen.queryByRole("checkbox", { name: /仅选择异常项 历史-0001/ }),
  ).not.toBeInTheDocument();
  await user.click(choice);
  await user.click(
    screen.getByRole("button", { name: "准备所选 1 条异常项的新清单" }),
  );
  const raw = (
    screen.getByRole("textbox", {
      name: "清单 JSON（可修正后重新校验）",
    }) as HTMLTextAreaElement
  ).value;
  expect(JSON.parse(raw)).toEqual({ records: [server.body.records[1]] });
  expect(JSON.parse(raw).records[0].value).toBeNull();
  expect(server.writes).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: "创建并保存导入预检查（1 条）" }),
  ).not.toBeInTheDocument();
});
it("rejects a changed head before confirmation without sending a new command or silently adopting it", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount();
  await create(user, server.body);
  await sourceAndAgree(user);
  server.current = importConfirmed(server.current);
  server.rows = server.current.records;
  await user.click(confirmButton());
  await screen.findByText(/这份预检查已变化/);
  expect(server.writes).toHaveLength(1);
  expect(confirmButton()).toBeDisabled();
  expect(readHistoricalRecovery(importMember).pending).toBeNull();
});
it("requires all record pages and rejects mixed revisions while keeping confirmation disabled", async () => {
  const { server } = await setup(101),
    user = userEvent.setup();
  writeHistoricalRecovery({
    version: 1,
    memberId: importMember,
    pending: null,
    lastBatchId: server.batch.id,
  });
  mount();
  await open(user);
  await screen.findByText(/已保存预检查/);
  await user.click(
    screen.getByRole("button", { name: "读取并核对本批原始清单" }),
  );
  await screen.findByText(/已核对确切原始清单/);
  expect(screen.getByRole("checkbox", { name: /我已核对全部/ })).toBeDisabled();
  server.onRead = (path) =>
    path.includes("offset=100")
      ? response(
          {
            ...server.current,
            revision: 2,
            records: server.rows.slice(100),
            next_offset: null,
          },
          200,
          historicalImportEtag(server.batch.id, 2),
        )
      : null;
  await user.click(
    screen.getByRole("button", { name: /读取并核对全部 101 条记录/ }),
  );
  await screen.findByText(/批次在读取期间已变化/);
  expect(confirmButton()).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});
it("keeps a source digest mismatch from authorizing a confirm or retry", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount();
  await create(user, server.body);
  server.source.manifest_digest = "f".repeat(64);
  await user.click(
    screen.getByRole("button", { name: "读取并核对本批原始清单" }),
  );
  await screen.findByRole("alert");
  expect(confirmButton()).toBeDisabled();
  expect(server.writes).toHaveLength(1);
});
it("releases only a definitive confirm rejection, then requires fresh source review and explicit agreement", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount();
  await create(user, server.body);
  await sourceAndAgree(user);
  server.onConfirm = async () =>
    response({ code: "REVISION_CONFLICT", message: "批次并发更新" }, 412);
  await user.click(confirmButton());
  await screen.findByText("批次并发更新");
  await waitFor(() =>
    expect(readHistoricalRecovery(importMember).pending).toBeNull(),
  );
  expect(confirmButton()).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: /我已核对全部/ }),
  ).not.toBeChecked();
  expect(server.writes).toHaveLength(2);
});
it("does not recreate cleared recovery from a late ACK after logout/unmount", async () => {
  const { server, acceptPreview } = await setup(),
    user = userEvent.setup();
  let release!: (value: Response) => void;
  let original: Response | null = null;
  server.onPreview = async (write) => {
    original = await acceptPreview(write);
    return new Promise<Response>((resolve) => {
      release = resolve;
    });
  };
  const mounted = mount();
  await prepare(user, server.body);
  await user.click(
    screen.getByRole("button", { name: "创建并保存导入预检查（2 条）" }),
  );
  await waitFor(() => expect(original).not.toBeNull());
  mounted.unmount();
  clearRecordedCommands();
  await act(async () => {
    release(original!);
    await Promise.resolve();
  });
  expect(sessionStorage.getItem(historicalStorageKey(importMember))).toBeNull();
});
it("reads a JSON file locally, rejects lossy timestamps, and never saves merely by selecting a file", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount();
  await open(user);
  const raw = {
    records: [
      {
        ...server.body.records[0],
        submitted_at: "2025-01-01T09:00:00.1234567+08:00",
      },
    ],
  };
  await user.upload(
    screen.getByLabelText("选择 JSON 清单"),
    new File([JSON.stringify(raw)], "history.json", {
      type: "application/json",
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "校验本地清单" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "校验本地清单" }));
  await screen.findByText(/不会截断微秒/);
  expect(server.writes).toHaveLength(0);
});
