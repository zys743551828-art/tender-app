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
import { afterEach, expect, it, vi } from "vitest";
import { AuthoringHistory } from "./AuthoringHistory";
import { setAuth, supportsApi } from "./api";
import { historicalSectionPath } from "./authoringHistoryProtocol";
import {
  historyFixture,
  historyJson,
  historyLongText,
  historyScope,
} from "./authoringHistoryFixtures.test-support";
import { importId } from "./authoringWordImportFixtures.test-support";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

async function setup(options: { image?: boolean; long?: boolean } = {}) {
  const f = await historyFixture(options);
  const fetch = vi.fn(f.fetcher);
  vi.stubGlobal("fetch", fetch);
  const OriginalURL = globalThis.URL;
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends OriginalURL {
      static createObjectURL = vi.fn(() => "blob:synthetic-history");
      static revokeObjectURL = revoke;
    },
  );
  setAuth({
    member: {
      id: historyScope.memberId,
      display_name: "合成验收成员",
      active: true,
    },
    csrf_token: "synthetic-not-a-credential",
    expires_at: "2099-01-01T00:00:00Z",
  });
  const props = {
    bidId: historyScope.bidId,
    sectionId: historyScope.sectionId,
    disabled: false,
    getHead: () => f.state.head,
    flush: vi.fn(async () => f.state.flushAllowed),
    setBusy: vi.fn(),
    refresh: vi.fn(async () => {
      f.state.refreshes++;
    }),
  };
  const show = () => render(<AuthoringHistory {...props} />);
  return { ...f, fetch, props, show, revoke };
}
async function open(revision = 2) {
  const user = userEvent.setup();
  await user.click(screen.getByText("查看章节历史修订"));
  await user.click(
    await screen.findByRole("button", {
      name: new RegExp(`^章节修订 ${revision}\\b`),
    }),
  );
  return user;
}
async function ready() {
  const button = await screen.findByRole("button", {
    name: "恢复此历史正文为新修订",
  });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
function loadImage(element: HTMLElement) {
  Object.defineProperty(element, "naturalWidth", {
    configurable: true,
    value: 2,
  });
  Object.defineProperty(element, "naturalHeight", {
    configurable: true,
    value: 2,
  });
  fireEvent.load(element);
}

it("真实操作目录包含精确 GET；只在明确选修订后请求，完整长稿/合并表格与比较不写入", async () => {
  const f = await setup({ long: true });
  const path = historicalSectionPath({
    ...historyScope,
    revision: 2,
    digest: f.state.history.digest,
  });
  expect(supportsApi("GET", path)).toBe(true);
  f.show();
  expect(f.fetch).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(screen.getByText("查看章节历史修订"));
  await screen.findByRole("button", { name: /^章节修订 2\b/ });
  expect(f.state.calls.map((call) => call.path)).toEqual([
    `/api/v1/sections/${historyScope.sectionId}/revisions`,
  ]);
  await user.click(screen.getByRole("button", { name: /^章节修订 2\b/ }));
  await ready();
  const body = screen.getByRole("region", { name: "拟恢复的完整历史正文" });
  expect(body.textContent).toContain(historyLongText);
  expect(
    within(body).getByRole("columnheader", { name: "合并表头" }),
  ).toHaveAttribute("colspan", "2");
  expect(f.state.calls.at(-1)?.path).toBe(`/api/v1${path}`);
  await user.click(screen.getByText("与当前已保存正文比较"));
  expect(
    await screen.findByRole("region", { name: "完整当前已保存正文" }),
  ).toHaveTextContent("当前已保存正文");
  expect(screen.getByText("拟恢复的历史正文 · 尚未恢复")).toBeInTheDocument();
  expect(f.state.writes).toHaveLength(0);
  expect(f.props.flush).not.toHaveBeenCalled();
});

it("图片核验及浏览器解码完成前禁用恢复，旧版本绑定不换当前图片", async () => {
  const f = await setup({ image: true });
  const view = f.show();
  await open();
  const image = await screen.findByRole("img", { name: "合成示意图" });
  expect(
    screen.getByRole("button", { name: "恢复此历史正文为新修订" }),
  ).toBeDisabled();
  loadImage(image);
  await ready();
  expect(screen.getByText(/历史版本；当前图片头已变化/)).toBeInTheDocument();
  expect(f.state.writes).toHaveLength(0);
  view.unmount();
  expect(f.revoke).toHaveBeenCalledWith("blob:synthetic-history");
});

it.each(["version", "bytes"])(
  "二次图片元数据不能覆盖所选历史的原绑定：%s",
  async (damage) => {
    const f = await setup({ image: true });
    if (damage === "version") f.state.image.digest = "f".repeat(64);
    else f.state.imageProof.output_digest = "f".repeat(64);
    f.show();
    await open();
    await screen.findByText(/图片的项目、历史版本或规范字节证明不一致/);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "恢复此历史正文为新修订" }),
    ).toBeDisabled();
    expect(
      f.state.calls.some((call) => call.path.endsWith("/bytes/normalized")),
    ).toBe(false);
    expect(f.state.writes).toHaveLength(0);
  },
);

it("显式恢复先保存本地稿，使用 flush 后最新 CAS；成功追加并保留旧版本目录", async () => {
  const f = await setup();
  f.props.flush.mockImplementation(async () => {
    f.state.head = {
      ...f.state.head,
      draft: { ...f.state.head.draft, revision: 5 },
      section: { ...f.state.head.section, revision: 4 },
      etag: '"draft-5"',
    };
    expect(f.state.writes).toHaveLength(0);
    return true;
  });
  f.show();
  const user = await open();
  await user.click(await ready());
  await screen.findByText("已追加草稿修订 6，其他历史仍保留。");
  expect(f.state.writes).toHaveLength(1);
  expect(f.state.writes[0].body).toEqual({
    revision: 2,
    base_draft_revision: 5,
    base_section_revision: 4,
  });
  expect(f.state.writes[0].headers["if-match"]).toBe('"draft-5"');
  expect(f.state.writes[0].headers["idempotency-key"]).toMatch(
    /^[0-9a-f-]{36}$/,
  );
  expect(f.props.refresh).toHaveBeenCalledTimes(1);
  expect(f.props.setBusy.mock.calls).toEqual([[true], [false]]);
  expect(
    await screen.findByRole("button", { name: /^章节修订 2\b/ }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "拟恢复的完整历史正文" }),
  ).not.toBeInTheDocument();
});

it("未决草稿未保存时停止恢复，重复点击也不会绕过 flush", async () => {
  const f = await setup();
  let finish: (allowed: boolean) => void = () => {};
  f.props.flush.mockImplementation(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  f.show();
  const user = await open();
  const button = await ready();
  await user.dblClick(button);
  expect(f.props.flush).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "正在核验来源并追加修订…" }),
  ).toBeDisabled();
  await act(async () => {
    finish(false);
  });
  await ready();
  expect(f.state.writes).toHaveLength(0);
  expect(
    screen.getByRole("region", { name: "拟恢复的完整历史正文" }),
  ).toHaveTextContent("所选历史正文完整保留");
});

it.each(["source_stale", "conflict"] as const)(
  "服务器拒绝 %s 保留原选择与完整历史，不显示恢复成功",
  async (mode) => {
    const f = await setup();
    f.state.restoreMode = mode;
    f.show();
    const user = await open();
    await user.click(await ready());
    await screen.findByText(
      mode === "source_stale"
        ? "历史来源已撤回，不能恢复为当前正文。"
        : "当前草稿已有新版本，请核对后重试。",
    );
    await ready();
    expect(
      screen.getByRole("region", { name: "拟恢复的完整历史正文" }),
    ).toHaveTextContent("所选历史正文完整保留");
    expect(screen.queryByText(/已追加草稿修订/)).not.toBeInTheDocument();
    expect(f.props.refresh).not.toHaveBeenCalled();
  },
);

it("网络不确定后保留既有原请求键和正文，显式重试才再次发送", async () => {
  const f = await setup();
  f.state.restoreMode = "network_once";
  f.show();
  const user = await open();
  await user.click(await ready());
  await screen.findByText(/暂时无法连接服务/);
  expect(f.state.writes).toHaveLength(1);
  await user.click(await ready());
  await screen.findByText("已追加草稿修订 4，其他历史仍保留。");
  expect(f.state.writes).toHaveLength(2);
  expect(f.state.writes[1].headers["idempotency-key"]).toBe(
    f.state.writes[0].headers["idempotency-key"],
  );
  expect(f.state.writes[1].headers["if-match"]).toBe(
    f.state.writes[0].headers["if-match"],
  );
  expect(f.state.writes[1].body).toEqual(f.state.writes[0].body);
});

it("先选修订 1 后选 2，迟到的 1 不覆盖正文或恢复目标", async () => {
  const f = await setup();
  let finish: (response: Response) => void = () => {};
  f.fetch.mockImplementation((input, init) =>
    String(input).includes("/revisions/1?")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : f.fetcher(input, init),
  );
  f.show();
  const user = await open(1);
  await user.click(screen.getByRole("button", { name: /^章节修订 2\b/ }));
  await ready();
  await act(async () => {
    finish(historyJson(f.state.versions.get(1)));
  });
  expect(screen.queryByText("更早一版的明确正文。")).not.toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "拟恢复的完整历史正文" }),
  ).toHaveTextContent("所选历史正文完整保留");
  await user.click(await ready());
  await screen.findByText("已追加草稿修订 4，其他历史仍保留。");
  expect(f.state.writes[0].body).toMatchObject({ revision: 2 });
});

it("flush 中切到其他章节，不把旧恢复请求发送到新范围", async () => {
  const f = await setup();
  let finish: (allowed: boolean) => void = () => {};
  f.props.flush.mockImplementation(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  const view = f.show();
  const user = await open();
  await user.click(await ready());
  const sectionId = importId(991);
  f.state.head = {
    ...f.state.head,
    section: { ...f.state.head.section, id: sectionId },
  };
  f.fetch.mockImplementation((input, init) =>
    String(input) === `/api/v1/sections/${sectionId}/revisions`
      ? Promise.resolve(historyJson({ items: [], next_cursor: null }))
      : f.fetcher(input, init),
  );
  view.rerender(<AuthoringHistory {...f.props} sectionId={sectionId} />);
  await act(async () => {
    finish(true);
  });
  expect(f.state.writes).toHaveLength(0);
  expect(
    screen.queryByRole("region", { name: "拟恢复的完整历史正文" }),
  ).not.toBeInTheDocument();
});

it("历史分页迟到后不进入另一章节目录", async () => {
  const f = await setup();
  f.state.page = { items: [f.entry(f.state.versions.get(3)!)], next_cursor: 3 };
  let finish: (response: Response) => void = () => {};
  f.fetch.mockImplementation((input, init) =>
    String(input).includes("?before=")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : f.fetcher(input, init),
  );
  const view = f.show();
  const user = userEvent.setup();
  await user.click(screen.getByText("查看章节历史修订"));
  await user.click(await screen.findByRole("button", { name: "加载更早修订" }));
  const sectionId = importId(992);
  f.state.head = {
    ...f.state.head,
    section: { ...f.state.head.section, id: sectionId },
  };
  f.fetch.mockImplementation((input, init) =>
    String(input) === `/api/v1/sections/${sectionId}/revisions`
      ? Promise.resolve(historyJson({ items: [], next_cursor: null }))
      : f.fetcher(input, init),
  );
  view.rerender(<AuthoringHistory {...f.props} sectionId={sectionId} />);
  await act(async () => {
    finish(
      historyJson({ items: [f.entry(f.state.history)], next_cursor: null }),
    );
  });
  expect(
    screen.queryByRole("button", { name: /^章节修订 2\b/ }),
  ).not.toBeInTheDocument();
  expect(f.state.writes).toHaveLength(0);
});

it("错误范围的历史回包不可预览或恢复", async () => {
  const f = await setup();
  f.state.history.bid_id = importId(999);
  f.show();
  await open();
  await screen.findByText(/历史章节的项目、原修订、完整正文或图片绑定无法核验/);
  expect(
    screen.queryByRole("region", { name: "拟恢复的完整历史正文" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "恢复此历史正文为新修订" }),
  ).not.toBeInTheDocument();
  expect(f.state.writes).toHaveLength(0);
});
