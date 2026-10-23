import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { TaskDraftPanel } from "./TaskDraftPanel";
import { packageAuthoringFixture } from "./packageAuthoringFixtures.test-support";

const f = packageAuthoringFixture().draft,
  flow = f.task_draft_flow,
  bidId = f.bid.id,
  draftId = flow.created.body.id,
  memberId = f.member_id,
  base = `/api/v1/bids/${bidId}`,
  draftPath = `${base}/task-definition-drafts/${draftId}`;

function json(body: unknown, etag?: string, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
type Step = "created" | "revised" | "saved";
function transport(lost?: Step, damagedCreate = false) {
  let current: typeof flow.final | null = null;
  const sent: { path: string; init: RequestInit }[] = [],
    unexpected: string[] = [],
    attempts: Record<Step, number> = { created: 0, revised: 0, saved: 0 };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, window.location.href),
        path = url.pathname,
        method = init.method ?? "GET";
      if (method === "GET") {
        if (path === "/api/v1/task-kinds") return json(f.kinds);
        if (path === "/api/v1/assistant/sources")
          return json({ items: [], has_more: false, next_cursor: null });
        if (path === `${base}/task-definition-drafts`)
          return json({
            items: current ? [current.body] : [],
            has_more: false,
            next_cursor: null,
          });
        if (path === draftPath && current)
          return json(current.body, current.etag);
        if (path === `${base}/authoring/package-inputs`)
          return json(f.input_page);
        if (path === `${base}/authoring/package-inputs/${f.input.manifest.id}`)
          return json(f.input);
        if (path === `${base}/task-definitions/${f.template.id}`)
          return json(f.template, f.template_etag);
        if (path === `${base}/task-definitions/${f.template.id}/runs`)
          return json({ items: [], has_more: false, next_cursor: null });
        if (path === `${base}/task-definitions/${f.template.id}/schedules`)
          return json({ items: [], has_more: false, next_cursor: null });
      } else {
        sent.push({ path, init });
        const step: Step | null =
          path === `${base}/task-definition-drafts` && method === "POST"
            ? "created"
            : path === draftPath && method === "PUT"
              ? "revised"
              : path === `${draftPath}/save` && method === "POST"
                ? "saved"
                : null;
        if (step) {
          const expected = flow[step];
          expect(JSON.parse(String(init.body))).toEqual(expected.request);
          expect(new Headers(init.headers).get("If-Match")).toBe(
            expected.if_match,
          );
          attempts[step] += 1;
          current = step === "saved" ? flow.final : flow[step];
          if (lost === step && attempts[step] === 1)
            throw new TypeError(
              "Synthetic transport lost an accepted native ACK",
            );
          const body =
            attempts[step] > 1 ? expected.replay_body : expected.body;
          if (step === "created" && damagedCreate && attempts.created === 1) {
            const changed = structuredClone(flow.created.body);
            changed.interpretation.source_selection = {
              mode: "current_project",
              version_ids: [],
            };
            return json(changed, expected.etag, expected.status);
          }
          return json(body, expected.etag, expected.status);
        }
      }
      unexpected.push(`${method} ${path}`);
      return json({ code: "UNEXPECTED_REQUEST" }, undefined, 404);
    }),
  );
  return { sent, unexpected, attempts };
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", `/bids/${bidId}/tasks`);
  setAuth({
    member: { id: memberId, display_name: "合成草案验收", active: true },
    csrf_token: "synthetic-only",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function panel(onSaved = vi.fn()) {
  return render(
    <TaskDraftPanel
      bidId={bidId}
      memberId={memberId}
      bidEtag={f.bid_etag}
      onSaved={onSaved}
    />,
  );
}
async function create() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", {
      name: "用自然语言拟定任务草案／恢复已有草案",
    }),
  );
  await user.selectOptions(
    screen.getByLabelText("任务草案来源"),
    "package-authoring",
  );
  await user.click(screen.getByRole("button", { name: "读取固定输入目录" }));
  await user.click(
    await screen.findByRole("button", { name: /选择这份编写输入/ }),
  );
  await user.type(
    screen.getByLabelText("想反复完成什么工作"),
    flow.created.request.request,
  );
  const generate = screen.getByRole("button", {
    name: "生成可编辑草案，不保存模板",
  });
  await waitFor(() => expect(generate).toBeEnabled());
  await user.click(generate);
}
async function revise(andSaveTemplate: boolean) {
  const user = userEvent.setup();
  const name = await screen.findByLabelText("固定整包编写模板名称"),
    instructions = screen.getByLabelText("固定整包编写要求");
  await user.clear(name);
  await user.type(name, flow.revised.request.name);
  await user.clear(instructions);
  await user.type(instructions, flow.revised.request.instructions);
  const save = screen.getByRole("button", {
    name: andSaveTemplate
      ? "保存为固定整包编写模板，不运行"
      : "只保存可编辑草案",
  });
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
}

it("uses the native private create, revise, template-save and final-read bodies without starting a model job", async () => {
  const calls = transport(),
    onSaved = vi.fn();
  panel(onSaved);
  await create();
  await revise(true);
  await screen.findByText(/此草案已一次保存为以下模板/);
  expect(onSaved).toHaveBeenCalledTimes(1);
  expect(calls.attempts).toEqual({ created: 1, revised: 1, saved: 1 });
  expect(calls.unexpected).toEqual([]);
  expect(calls.sent.map(({ path }) => path)).toEqual([
    `${base}/task-definition-drafts`,
    draftPath,
    `${draftPath}/save`,
  ]);
});

it.each([false, true])(
  "recovers the original create ACK after remount without selecting another input (malformed=%s)",
  async (damaged) => {
    const calls = transport(damaged ? undefined : "created", damaged),
      first = panel();
    await create();
    await screen.findByRole("button", { name: "恢复原草案受理结果" });
    first.unmount();
    panel();
    await userEvent.click(
      screen.getByRole("button", {
        name: "用自然语言拟定任务草案／恢复已有草案",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "恢复原草案受理结果" }),
    );
    await screen.findByRole("heading", { name: "我的可编辑任务草案 · 修订1" });
    expect(calls.sent[1]).toEqual(calls.sent[0]);
    expect(calls.attempts).toEqual({ created: 2, revised: 0, saved: 0 });
    expect(calls.unexpected).toEqual([]);
  },
);

it("recovers a lost revise ACK with its original draft-only intent and never saves a template", async () => {
  const calls = transport("revised"),
    first = panel();
  await create();
  await revise(false);
  await screen.findByRole("button", {
    name: "恢复原草案更新结果（保留原保存意图）",
  });
  first.unmount();
  panel();
  await userEvent.click(
    await screen.findByRole("button", {
      name: "恢复原草案更新结果（保留原保存意图）",
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", {
        name: "恢复原草案更新结果（保留原保存意图）",
      }),
    ).not.toBeInTheDocument(),
  );
  expect(calls.sent[2]).toEqual(calls.sent[1]);
  expect(calls.attempts).toEqual({ created: 1, revised: 2, saved: 0 });
  expect(calls.unexpected).toEqual([]);
});

it("recovers a lost template-save ACK from the original revision after the current draft has advanced", async () => {
  const calls = transport("saved"),
    first = panel();
  await create();
  await revise(true);
  await screen.findByRole("button", { name: "恢复同一次模板保存结果" });
  first.unmount();
  panel();
  await screen.findByText(/此草案已一次保存为以下模板/);
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复同一次模板保存结果" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "恢复同一次模板保存结果" }),
    ).not.toBeInTheDocument(),
  );
  expect(calls.sent[3]).toEqual(calls.sent[2]);
  expect(calls.attempts).toEqual({ created: 1, revised: 1, saved: 2 });
  expect(calls.unexpected).toEqual([]);
});
