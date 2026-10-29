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
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringWordImport } from "./AuthoringWordImport";
import type { ApiResult } from "./api";
import type {
  AuthoringWordImportCandidate,
  AuthoringWordImportCapabilities,
  DraftView,
} from "./contracts";
import {
  readWordImportRecovery,
  storeWordImportRecovery,
  wordImportPath,
  wordImportStorageKey,
} from "./authoringWordImportRecovery";
import {
  importCandidate,
  importCandidateWithImage,
  importCapabilities,
  importHead,
  importImageBytes,
  importId,
  importOriginal,
  importResolution,
  importScope,
} from "./authoringWordImportFixtures.test-support";

const base = `/api/v1${wordImportPath(importScope)}`;
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function setup(initial = importCandidate()) {
  const server = {
    candidate: initial,
    capabilities: structuredClone(
      importCapabilities,
    ) as AuthoringWordImportCapabilities,
    prepares: [] as RequestInit[],
    resolves: [] as RequestInit[],
    onPrepare: null as null | ((options: RequestInit) => Promise<Response>),
    onResolve: null as null | ((options: RequestInit) => Promise<Response>),
    onImage: null as null | (() => Promise<Response>),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/authoring/word-import-capabilities")
        return response(server.capabilities);
      if (url.startsWith(`/api/v1/bids/${importScope.bidId}/word-originals`))
        return response({
          items: [importOriginal],
          has_more: false,
          next_after: null,
        });
      if (url === base && options?.method === "POST") {
        server.prepares.push(options);
        if (server.onPrepare) return server.onPrepare(options);
        const body = JSON.parse(String(options.body));
        server.candidate = {
          ...server.candidate,
          reason: body.reason,
          preparation: {
            ...server.candidate.preparation,
            request: body,
            idempotency_key: new Headers(options.headers).get(
              "Idempotency-Key",
            )!,
            if_match: new Headers(options.headers).get("If-Match"),
          },
        };
        return response(server.candidate);
      }
      if (url === `${base}/${server.candidate.candidate_id}/resolve`) {
        server.resolves.push(options!);
        if (server.onResolve) return server.onResolve(options!);
        const result = importResolution(server.candidate, options!);
        server.candidate = {
          ...server.candidate,
          state: result.state,
          resolution: result,
          can_apply: false,
        };
        return response(result);
      }
      if (url === `${base}/${server.candidate.candidate_id}`)
        return response(server.candidate);
      if (
        url.includes(`${base}/${server.candidate.candidate_id}/images/`) &&
        server.onImage
      )
        return server.onImage();
      if (url === base || url.startsWith(base + "?cursor="))
        return response({
          bid_id: importScope.bidId,
          draft_id: importScope.draftId,
          items: [server.candidate],
          has_more: false,
          next_cursor: null,
        });
      throw new Error(`unexpected test route ${url}`);
    }),
  );
  return server;
}
function mount(
  overrides: Partial<React.ComponentProps<typeof AuthoringWordImport>> = {},
) {
  const props = {
    ...importScope,
    draftRevision: 7,
    disabled: false,
    prepare: vi.fn(async () => structuredClone(importHead)),
    onChanged: vi.fn(async () => undefined),
    onBusy: vi.fn(),
    ...overrides,
  };
  return { ...render(<AuthoringWordImport {...props} />), props };
}
async function fillOriginal() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "选择已保存的Word原件" }),
  );
  await screen.findByRole("option", { name: /合成施工方案/ });
  await user.selectOptions(
    screen.getByRole("combobox", { name: "选择本项目的确切Word版本" }),
    importOriginal.id,
  );
  await user.type(
    screen.getByRole("textbox", { name: "创建候选的理由" }),
    "核对本次原件后追加",
  );
  return user;
}
async function createCandidate() {
  const user = await fillOriginal();
  await user.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  await screen.findByRole("heading", { name: importOriginal.original_name });
  return user;
}
async function acknowledge(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("checkbox", { name: /^确认损失：/ }));
  await user.type(
    screen.getByRole("textbox", { name: "本次处理理由" }),
    "已核对结构及全部损失，明确追加",
  );
}
function remember(candidate: AuthoringWordImportCandidate) {
  storeWordImportRecovery({
    version: 1,
    scope: importScope,
    pending: null,
    lastCandidateId: candidate.candidate_id,
  });
}
beforeEach(() => {
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("先等待当前编辑保存确认，再固定原件创建候选；层级和合并表格预览不写草稿", async () => {
  const server = setup();
  let release: ((value: ApiResult<DraftView>) => void) | undefined;
  const prepare = vi.fn(
    () =>
      new Promise<ApiResult<DraftView>>((resolve) => {
        release = resolve;
      }),
  );
  const view = mount({ prepare });
  const user = await fillOriginal();
  await user.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  expect(prepare).toHaveBeenCalledTimes(1);
  expect(server.prepares).toHaveLength(0);
  await act(async () => release!(structuredClone(importHead)));
  await screen.findByRole("heading", { name: importOriginal.original_name });
  const request = server.prepares[0];
  expect(new Headers(request.headers).get("If-Match")).toBe(importHead.etag);
  expect(JSON.parse(String(request.body))).toEqual({
    source_document_version_id: importOriginal.id,
    source_digest: importOriginal.source_sha256,
    source_byte_size: importOriginal.byte_size,
    base_draft_revision: 7,
    method_digest: importCapabilities.method_digest,
    reason: "核对本次原件后追加",
  });
  expect(
    within(screen.getByRole("list", { name: "拟追加章节层级" })).getByText(
      "第2层子章节 · 进度安排",
    ),
  ).toBeVisible();
  expect(
    screen.getByRole("columnheader", { name: "合并表头" }),
  ).toHaveAttribute("colspan", "2");
  expect(screen.getByRole("cell", { name: "120天" })).toBeVisible();
  expect(server.resolves).toHaveLength(0);
  expect(view.props.onChanged).not.toHaveBeenCalled();
  expect(importHead.data.sections[0].title).toBe("原有方案");
});

it("每项损失明确确认后才追加；回执绑定原候选、原请求与下一草稿修订", async () => {
  const server = setup();
  const view = mount();
  const user = await createCandidate();
  const append = screen.getByRole("button", { name: "明确追加这些新章节" });
  expect(append).toBeDisabled();
  await user.type(
    screen.getByRole("textbox", { name: "本次处理理由" }),
    "明确追加新章节",
  );
  expect(append).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /^确认损失：/ }));
  await user.click(append);
  await screen.findByText(/已追加 2 个章节，生成草稿修订 8/);
  expect(view.props.prepare).toHaveBeenCalledTimes(2);
  expect(view.props.onChanged).toHaveBeenCalledTimes(1);
  expect(server.resolves).toHaveLength(1);
  expect(JSON.parse(String(server.resolves[0].body))).toEqual({
    decision: "append",
    candidate_digest: server.candidate.candidate_digest,
    acknowledged_issue_ids: ["f".repeat(64)],
    reason: "明确追加新章节",
  });
  expect(readWordImportRecovery(importScope).pending).toBeNull();
});

it("阻断项不能靠确认警告放行；拒绝候选保留历史且不刷新或改写草稿", async () => {
  const value = importCandidate();
  value.issues.push({
    id: "7".repeat(64),
    code: "TRACKED_CHANGES_UNSUPPORTED",
    severity: "blocker",
    source_path: "word/document.xml",
    message: "原稿包含未处理修订",
  });
  value.blocker_count = 1;
  value.state = "blocked";
  value.can_apply = false;
  const server = setup(value);
  const view = mount();
  const user = await createCandidate();
  expect(screen.getByText("无法追加：原稿包含未处理修订")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "明确追加这些新章节" }),
  ).toBeDisabled();
  await user.type(
    screen.getByRole("textbox", { name: "本次处理理由" }),
    "先处理修订后重新上传",
  );
  await user.click(
    screen.getByRole("button", { name: "拒绝此候选并保留历史" }),
  );
  await screen.findByText(/此候选已明确拒绝，草稿未改变/);
  expect(view.props.prepare).toHaveBeenCalledTimes(1);
  expect(view.props.onChanged).not.toHaveBeenCalled();
  expect(JSON.parse(String(server.resolves[0].body)).decision).toBe("reject");
});

it("追加ACK丢失后刷新，在项目禁写或能力关闭时仍按原键原体原ETag恢复", async () => {
  const server = setup();
  let lost = true;
  let receipt: ReturnType<typeof importResolution>;
  server.onResolve = async (options) => {
    if (lost) {
      lost = false;
      receipt = importResolution(server.candidate, options);
      server.candidate = {
        ...server.candidate,
        state: "applied",
        resolution: receipt,
        can_apply: false,
      };
      throw new TypeError("lost response");
    }
    return response(receipt);
  };
  const first = mount();
  const user = await createCandidate();
  await acknowledge(user);
  await user.click(screen.getByRole("button", { name: "明确追加这些新章节" }));
  await screen.findByRole("button", { name: "恢复原导入请求结果" });
  const stored = readWordImportRecovery(importScope).pending;
  expect(stored?.kind).toBe("resolve");
  first.unmount();
  server.capabilities = {
    ...server.capabilities,
    enabled: false,
    unavailable_reason: { code: "NOT_CONFIGURED", message: "新导入暂不可用" },
  };
  const second = mount({ disabled: true, draftRevision: 8 });
  await user.click(
    await screen.findByRole("button", { name: "恢复原导入请求结果" }),
  );
  await waitFor(() =>
    expect(readWordImportRecovery(importScope).pending).toBeNull(),
  );
  expect(server.resolves).toHaveLength(2);
  for (const header of ["Idempotency-Key", "If-Match"])
    expect(new Headers(server.resolves[1].headers).get(header)).toBe(
      new Headers(server.resolves[0].headers).get(header),
    );
  expect(server.resolves[1].body).toBe(server.resolves[0].body);
  expect(second.props.prepare).not.toHaveBeenCalled();
  expect(second.props.onChanged).toHaveBeenCalledTimes(1);
});

it("另一成员的成功ACK不能清除原请求或显示本次追加成功", async () => {
  const server = setup();
  server.onResolve = async (options) => {
    const value = importResolution(server.candidate, options);
    value.command.actor_id = importId(99);
    return response(value);
  };
  const view = mount();
  const user = await createCandidate();
  await acknowledge(user);
  await user.click(screen.getByRole("button", { name: "明确追加这些新章节" }));
  await screen.findByText(/回执身份无法核对/);
  expect(readWordImportRecovery(importScope).pending?.kind).toBe("resolve");
  expect(view.props.onChanged).not.toHaveBeenCalled();
  expect(screen.queryByText(/已追加 2 个章节/)).not.toBeInTheDocument();
});

it("服务端CAS拒绝保留候选和用户确认，不会换新head自动重发", async () => {
  const server = setup();
  server.onResolve = async () =>
    response(
      { code: "AUTHORING_WORD_IMPORT_STALE", message: "草稿已被另一请求修改" },
      412,
    );
  const view = mount();
  const user = await createCandidate();
  await acknowledge(user);
  await user.click(screen.getByRole("button", { name: "明确追加这些新章节" }));
  await screen.findByText("草稿已被另一请求修改");
  expect(readWordImportRecovery(importScope).pending).toBeNull();
  expect(readWordImportRecovery(importScope).lastCandidateId).toBe(
    server.candidate.candidate_id,
  );
  expect(screen.getByRole("checkbox", { name: /^确认损失：/ })).toBeChecked();
  expect(server.resolves).toHaveLength(1);
  view.rerender(<AuthoringWordImport {...view.props} draftRevision={8} />);
  expect(
    screen.getByRole("button", { name: "明确追加这些新章节" }),
  ).toBeDisabled();
  expect(view.props.onChanged).not.toHaveBeenCalled();
});

it("尚未解决本地编辑恢复时，保存队列返回null，不能创建候选", async () => {
  const server = setup();
  mount({ prepare: vi.fn(async () => null) });
  const user = await fillOriginal();
  await user.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  expect(server.prepares).toHaveLength(0);
  expect(screen.getByRole("textbox", { name: "创建候选的理由" })).toHaveValue(
    "核对本次原件后追加",
  );
});

it("无法保存恢复记录时不发送创建请求", async () => {
  const server = setup();
  mount();
  const user = await fillOriginal();
  const original = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (key === wordImportStorageKey(importScope))
      throw new DOMException("full", "QuotaExceededError");
    return original.call(this, key, value);
  });
  await user.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  await screen.findByText(/未能保存Word导入恢复记录/);
  expect(server.prepares).toHaveLength(0);
});

it("损坏恢复记录保持原样，仍允许只读查看服务器候选历史", async () => {
  setup();
  sessionStorage.setItem(wordImportStorageKey(importScope), "{damaged");
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "查看导入历史" }));
  await user.click(await screen.findByRole("button", { name: "查看此候选" }));
  await screen.findByRole("heading", { name: importOriginal.original_name });
  expect(
    screen.getByRole("button", { name: "明确追加这些新章节" }),
  ).toBeDisabled();
  expect(sessionStorage.getItem(wordImportStorageKey(importScope))).toBe(
    "{damaged",
  );
});

it("创建候选时离开页面，迟到ACK不丢弃可恢复的原请求", async () => {
  const server = setup();
  let release: ((value: Response) => void) | undefined;
  server.onPrepare = (options) => {
    const body = JSON.parse(String(options.body));
    server.candidate = {
      ...server.candidate,
      reason: body.reason,
      preparation: {
        ...server.candidate.preparation,
        request: body,
        idempotency_key: new Headers(options.headers).get("Idempotency-Key")!,
        if_match: new Headers(options.headers).get("If-Match"),
      },
    };
    return new Promise<Response>((resolve) => {
      release = resolve;
    });
  };
  const view = mount();
  const user = await fillOriginal();
  await user.click(
    screen.getByRole("button", { name: "保存当前编辑并生成导入候选" }),
  );
  await waitFor(() => expect(server.prepares).toHaveLength(1));
  const before = readWordImportRecovery(importScope).pending;
  view.unmount();
  await act(async () => release!(response(server.candidate)));
  expect(readWordImportRecovery(importScope).pending).toEqual(before);
});

it("读取候选历史不触发导入或追加，原稿表格仍以真实单元格预览", async () => {
  const server = setup();
  remember(server.candidate);
  const view = mount();
  await screen.findByRole("table", { name: "原稿进度表" });
  expect(server.prepares).toHaveLength(0);
  expect(server.resolves).toHaveLength(0);
  expect(view.props.prepare).not.toHaveBeenCalled();
});

it("重新打开已追加历史时，逐项确认来自保存回执且保持只读", async () => {
  const server = setup();
  const result = importResolution(server.candidate, {
    headers: {
      "Idempotency-Key": importId(51),
      "If-Match": server.candidate.base_draft_etag,
    },
    body: JSON.stringify({
      decision: "append",
      candidate_digest: server.candidate.candidate_digest,
      acknowledged_issue_ids: server.candidate.issues.map((issue) => issue.id),
      reason: "已核对后明确追加",
    }),
  });
  server.candidate = {
    ...server.candidate,
    state: "applied",
    can_apply: false,
    resolution: result,
  };
  remember(server.candidate);
  mount({ draftRevision: 8 });
  const checkbox = await screen.findByRole("checkbox", { name: /^确认损失：/ });
  expect(checkbox).toBeChecked();
  expect(checkbox).toBeDisabled();
  expect(server.prepares).toHaveLength(0);
  expect(server.resolves).toHaveLength(0);
});

function imageUrls() {
  const create = vi.fn(() => "blob:word-import-preview");
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  return { create, revoke };
}
function imageResponse(bytes = importImageBytes) {
  return new Response(bytes, {
    headers: {
      "Content-Type": "image/png",
      "Content-Length": String(bytes.length),
    },
  });
}
function loadedImage(image: HTMLElement) {
  Object.defineProperty(image, "naturalWidth", {
    value: 2,
    configurable: true,
  });
  Object.defineProperty(image, "naturalHeight", {
    value: 2,
    configurable: true,
  });
  fireEvent.load(image);
}

it("候选图片核对实际PNG字节和尺寸后才允许追加，离开时回收Blob URL", async () => {
  const server = setup(importCandidateWithImage());
  server.onImage = async () => imageResponse();
  const urls = imageUrls();
  remember(server.candidate);
  const view = mount();
  const image = await screen.findByRole("img", { name: "合成示意图" });
  expect(image).toHaveAttribute("src", "blob:word-import-preview");
  const user = userEvent.setup();
  await acknowledge(user);
  expect(
    screen.getByRole("button", { name: "明确追加这些新章节" }),
  ).toBeDisabled();
  loadedImage(image);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "明确追加这些新章节" }),
    ).toBeEnabled(),
  );
  expect(urls.create).toHaveBeenCalledTimes(1);
  expect(server.resolves).toHaveLength(0);
  view.unmount();
  expect(urls.revoke).toHaveBeenCalledWith("blob:word-import-preview");
});

it("长度相同但SHA错误的图片不会显示或允许追加，明确重读后才恢复", async () => {
  const server = setup(importCandidateWithImage());
  const wrong = importImageBytes.slice();
  wrong[wrong.length - 1] ^= 1;
  server.onImage = async () => imageResponse(wrong);
  const urls = imageUrls();
  remember(server.candidate);
  mount();
  await screen.findByText(/图片摘要与候选不一致/);
  expect(urls.create).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await acknowledge(user);
  expect(
    screen.getByRole("button", { name: "明确追加这些新章节" }),
  ).toBeDisabled();
  server.onImage = async () => imageResponse();
  await user.click(screen.getByRole("button", { name: "重新读取此图片" }));
  loadedImage(await screen.findByRole("img", { name: "合成示意图" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "明确追加这些新章节" }),
    ).toBeEnabled(),
  );
});

it("图片读取期间离开页面，迟到字节不会创建未清理的Blob URL", async () => {
  const server = setup(importCandidateWithImage());
  let release: ((value: Response) => void) | undefined;
  server.onImage = () =>
    new Promise<Response>((resolve) => {
      release = resolve;
    });
  const urls = imageUrls();
  remember(server.candidate);
  const view = mount();
  await screen.findByText("正在读取并核对图片：合成示意图");
  view.unmount();
  await act(async () => {
    release!(imageResponse());
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  expect(urls.create).not.toHaveBeenCalled();
});
