import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AssistantActionCard } from "./AssistantActionCard";
import { AssistantSourcePicker } from "./AssistantSourcePicker";
import type { SelectedAssistantSource } from "./assistantState";
import { setAuth } from "./api";
import {
  assistantReviewFixture,
  assistantReviewOldVersion,
  assistantReviewReference,
  assistantReviewScope,
} from "./assistantReviewFixtures.test-support";

beforeEach(() => {
  sessionStorage.clear();
  setAuth({
    member: {
      id: assistantReviewScope.memberId,
      display_name: "合成账号",
      active: true,
    },
    csrf_token: "synthetic-not-a-credential",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => vi.unstubAllGlobals());
function card() {
  return (
    <AssistantActionCard
      id={assistantReviewScope.actionId}
      memberId={assistantReviewScope.memberId}
    />
  );
}
function selected(
  version = assistantReviewOldVersion,
): SelectedAssistantSource {
  return {
    title: "进度条款原件",
    bidId: assistantReviewScope.bidId,
    reference: { ...assistantReviewReference, version },
  };
}

it("具体增删保留未变化的中间段落，不把格式切分当作换行", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  vi.stubGlobal("fetch", fixture.fetcher);
  const { container } = render(card());
  await user.click(await screen.findByText("查看具体文字增删"));
  const original = await screen.findByLabelText("修改前全文");
  expect(original.textContent).toBe(fixture.expectedBefore);
  expect(screen.getByLabelText("拟修改后全文").textContent).toBe(
    fixture.expectedAfter,
  );
  const removed = [
    ...container.querySelectorAll("mark.text-change-preview__removed"),
  ]
    .map((node) => node.textContent)
    .join("");
  const added = [
    ...container.querySelectorAll("mark.text-change-preview__added"),
  ]
    .map((node) => node.textContent)
    .join("");
  expect(removed).toContain("30");
  expect(added).toContain("45");
  expect(removed).not.toContain("保留完整核对内容");
  expect(added).not.toContain("保留完整核对内容");
  expect(
    screen.queryByText("变化较多，已按区块标示；两侧保留全文。"),
  ).not.toBeInTheDocument();
  expect(fixture.state.writes).toEqual([]);
});

it("长提议保留完整文字、相邻格式片段和软换行；只在明确采纳时写一次", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture({ long: true });
  vi.stubGlobal("fetch", fixture.fetcher);
  const { container } = render(card());
  await screen.findByText("查看具体文字增删");
  expect(screen.queryByLabelText("修改前全文")).not.toBeInTheDocument();
  await user.click(screen.getByText("查看具体文字增删"));
  expect((await screen.findByLabelText("修改前全文")).textContent).toBe(
    fixture.expectedBefore,
  );
  expect(screen.getByLabelText("拟修改后全文").textContent).toBe(
    fixture.expectedAfter,
  );
  expect(
    container.querySelectorAll("mark.text-change-preview__removed").length,
  ).toBeGreaterThan(0);
  expect(
    container.querySelectorAll("mark.text-change-preview__added").length,
  ).toBeGreaterThan(0);
  await user.click(screen.getByText("查看完整原稿与格式"));
  const original = await screen.findByRole("region", {
    name: "完整原稿滚动区域",
  });
  expect(original.querySelector("strong")?.textContent).toBe("进度");
  expect(original.querySelector("br")).not.toBeNull();
  expect(original.querySelector("ol li")?.textContent).toBe("保留清单第一项。");
  expect(original.textContent).toContain("原稿尾段：保留现场核验。");
  await user.click(screen.getByText("查看完整拟稿与格式"));
  expect(
    (await screen.findByRole("region", { name: "完整拟稿滚动区域" }))
      .textContent,
  ).toContain("拟稿尾段：明确增派人员。");
  expect(fixture.state.writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "应用这份正文修改" }));
  await screen.findByText("已执行并留存结果");
  expect(fixture.state.applied).toBe(1);
  expect(fixture.state.writes).toHaveLength(1);
  expect(fixture.state.writes[0]).toMatchObject({
    body: { decision: "confirm" },
    etag: '"action:1"',
  });
  expect(fixture.state.writes[0].key).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "应用这份正文修改" }),
  ).not.toBeInTheDocument();
  expect(fixture.state.unexpected).toEqual([]);
});

it.each(["stale", "expired", "rejected"] as const)(
  "%s 历史卡能核对全文，不提供重新采纳",
  async (state) => {
    const user = userEvent.setup();
    const fixture = assistantReviewFixture();
    fixture.state.action.state = state;
    vi.stubGlobal("fetch", fixture.fetcher);
    render(card());
    await user.click(await screen.findByText("查看具体文字增删"));
    expect((await screen.findByLabelText("拟修改后全文")).textContent).toBe(
      fixture.expectedAfter,
    );
    expect(
      screen.queryByRole("button", { name: "应用这份正文修改" }),
    ).not.toBeInTheDocument();
    expect(fixture.state.writes).toEqual([]);
  },
);

it("展开期间来源失效后，明确确认仍采用服务端未执行结果", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  fixture.state.resolveMode = "withdrawn";
  vi.stubGlobal("fetch", fixture.fetcher);
  render(card());
  await user.click(await screen.findByText("查看具体文字增删"));
  await screen.findByLabelText("拟修改后全文");
  expect(fixture.state.writes).toEqual([]);
  await user.click(screen.getByRole("button", { name: "应用这份正文修改" }));
  await screen.findByText("依据已变化，未执行");
  expect(
    screen.getByText("此提议没有执行业务效果；保留真实处理结果。"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "应用这份正文修改" }),
  ).not.toBeInTheDocument();
  expect(fixture.state.applied).toBe(0);
  expect(fixture.state.writes).toHaveLength(1);
});

it("预览不会清除失 ACK 的原操作；重新打开后沿原键体和条件恢复", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  fixture.state.resolveMode = "lost_ack";
  vi.stubGlobal("fetch", fixture.fetcher);
  const view = render(card());
  await user.click(
    await screen.findByRole("button", { name: "应用这份正文修改" }),
  );
  await screen.findByRole("button", { name: "恢复原操作结果" });
  const first = structuredClone(fixture.state.writes[0]);
  await user.click(screen.getByText("查看具体文字增删"));
  await screen.findByLabelText("拟修改后全文");
  expect(fixture.state.writes).toHaveLength(1);
  view.unmount();
  render(card());
  await screen.findByText("已执行并留存结果");
  expect(
    screen.queryByRole("button", { name: "应用这份正文修改" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "恢复原操作结果" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "恢复原操作结果" }),
    ).not.toBeInTheDocument(),
  );
  expect(fixture.state.writes).toHaveLength(2);
  expect(fixture.state.writes[1]).toEqual(first);
  expect(fixture.state.applied).toBe(1);
});

it("来源详情与勾选分开，原版本保留；只有明确选择才换服务器版本", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  vi.stubGlobal("fetch", fixture.fetcher);
  const changed = vi.fn();
  render(
    <AssistantSourcePicker
      bidId={assistantReviewScope.bidId}
      selected={[selected()]}
      onChange={changed}
      disabled={false}
    />,
  );
  const option = await screen.findByRole("checkbox", { name: /进度条款原件/ });
  await waitFor(() => expect(option).toBeEnabled());
  await user.click(screen.getByText("核对已选来源：进度条款原件 · 物理页 1"));
  const saved = screen.getByRole("region", { name: "已选来源版本核对" });
  expect(within(saved).getByText(assistantReviewOldVersion)).toBeVisible();
  expect(
    within(saved).getByText(assistantReviewReference.version),
  ).toBeVisible();
  expect(within(saved).getByText(/当前目录提供了不同版本/)).toBeVisible();
  const candidate = option.closest(".assistant-source-option") as HTMLElement;
  await user.click(within(candidate).getByText("核对来源版本与用途"));
  expect(within(candidate).getByText("固定版本凭据")).toBeVisible();
  expect(changed).not.toHaveBeenCalled();
  expect(option).not.toBeChecked();
  await user.click(option);
  expect(changed).toHaveBeenCalledExactlyOnceWith([
    {
      title: "进度条款原件",
      bidId: assistantReviewScope.bidId,
      reference: assistantReviewReference,
    },
  ]);
  expect(fixture.state.writes).toEqual([]);
});

it("撤回候选不可选；同名但无引用的目录不能冒认已选来源已撤回", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  fixture.state.sources.items = [
    {
      title: "进度条款原件",
      reference: null,
      available: false,
      reasons: ["SOURCE_WITHDRAWN"],
      bid_id: assistantReviewScope.bidId,
      formal_scoring_input: false,
    },
  ];
  vi.stubGlobal("fetch", fixture.fetcher);
  const changed = vi.fn();
  render(
    <AssistantSourcePicker
      bidId={assistantReviewScope.bidId}
      selected={[selected()]}
      onChange={changed}
      disabled={false}
    />,
  );
  const option = await screen.findByRole("checkbox", { name: /进度条款原件/ });
  expect(option).toBeDisabled();
  await user.click(screen.getByText("核对已选来源：进度条款原件 · 物理页 1"));
  const saved = screen.getByRole("region", { name: "已选来源版本核对" });
  expect(
    within(saved).getByText(/当前目录尚未核对到这个精确来源/),
  ).toBeVisible();
  expect(within(saved).getByText(assistantReviewOldVersion)).toBeVisible();
  await user.click(screen.getByText("核对来源版本与用途"));
  expect(screen.getByText("服务器未提供可用版本凭据")).toBeVisible();
  expect(screen.getByText("来源已撤回。")).toBeVisible();
  expect(changed).not.toHaveBeenCalled();
});

it("目录刷新失败保留已选版本但不显示旧可用性，也不允许选取旧目录", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  vi.stubGlobal("fetch", fixture.fetcher);
  const changed = vi.fn();
  render(
    <AssistantSourcePicker
      bidId={assistantReviewScope.bidId}
      selected={[selected(assistantReviewReference.version)]}
      onChange={changed}
      disabled={false}
    />,
  );
  const option = await screen.findByRole("checkbox", { name: /进度条款原件/ });
  await waitFor(() => expect(option).toBeEnabled());
  await user.click(screen.getByText("核对已选来源：进度条款原件 · 物理页 1"));
  const saved = screen.getByRole("region", { name: "已选来源版本核对" });
  expect(within(saved).getByText(/本次目录读取时可选择/)).toBeVisible();
  fixture.state.sourceReadFailure = true;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await screen.findByText("合成目录暂时无法读取。");
  expect(option).toBeDisabled();
  expect(
    within(saved).getByText(/当前目录尚未核对到这个精确来源/),
  ).toBeVisible();
  expect(
    within(saved).queryByText(/本次目录读取时可选择/),
  ).not.toBeInTheDocument();
  expect(
    within(saved).getByText(assistantReviewReference.version),
  ).toBeVisible();
  expect(changed).not.toHaveBeenCalled();
});

it("不同版本的不可用原因不冒充原选择版本的状态", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  fixture.state.sources.items[0].available = false;
  fixture.state.sources.items[0].reasons = ["SOURCE_WITHDRAWN"];
  vi.stubGlobal("fetch", fixture.fetcher);
  const changed = vi.fn();
  render(
    <AssistantSourcePicker
      bidId={assistantReviewScope.bidId}
      selected={[selected()]}
      onChange={changed}
      disabled={false}
    />,
  );
  await screen.findByRole("checkbox", { name: /进度条款原件/ });
  await user.click(screen.getByText("核对已选来源：进度条款原件 · 物理页 1"));
  const saved = screen.getByRole("region", { name: "已选来源版本核对" });
  expect(within(saved).getByText(/当前目录提供了不同版本/)).toBeVisible();
  expect(within(saved).getByText(/以下原因属于本次目录所列版本/)).toBeVisible();
  expect(within(saved).getByText(assistantReviewOldVersion)).toBeVisible();
  expect(
    within(saved).getByText(assistantReviewReference.version),
  ).toBeVisible();
  expect(
    within(saved).queryByText(/本次目录标明来源不可选择/),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /进度条款原件/ })).toBeDisabled();
  expect(changed).not.toHaveBeenCalled();
});

it("物理页和知识查证记录属于精确身份；锁定选择期间仍可查看详情", async () => {
  const user = userEvent.setup();
  const fixture = assistantReviewFixture();
  const page2 = {
    ...selected(),
    reference: {
      ...assistantReviewReference,
      physical_page: 2,
      version: assistantReviewOldVersion,
    },
  };
  const knowledge: SelectedAssistantSource = {
    title: "已选知识参考",
    bidId: assistantReviewScope.bidId,
    reference: {
      kind: "knowledge_unit",
      id: "knowledge-unit",
      version: "knowledge-version",
      trace_id: "explicit-trace",
    },
  };
  vi.stubGlobal("fetch", fixture.fetcher);
  const changed = vi.fn();
  render(
    <AssistantSourcePicker
      bidId={assistantReviewScope.bidId}
      selected={[page2, knowledge]}
      onChange={changed}
      disabled
    />,
  );
  const pageSummary = await screen.findByText(
    "核对已选来源：进度条款原件 · 物理页 2",
  );
  await user.click(pageSummary);
  expect(
    within(pageSummary.closest("details")!).getByText(
      /当前目录尚未核对到这个精确来源/,
    ),
  ).toBeVisible();
  await user.click(screen.getByText("核对已选来源：已选知识参考"));
  expect(screen.getByText("explicit-trace")).toBeVisible();
  expect(screen.getByText("knowledge-version")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: /进度条款原件/ })).toBeDisabled();
  expect(changed).not.toHaveBeenCalled();
  expect(fixture.state.writes).toEqual([]);
});
