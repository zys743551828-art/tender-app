import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { PackageRetrospectives } from "./PackageRetrospectives";
import {
  retrospectiveFixture,
  retrospectiveAckFor,
  retrospectiveKnowledgeAckFor,
  retrospectiveDraftKey,
  retrospectiveScope,
} from "./packageRetrospectiveFixtures.test-support";
import { retrospectiveBase } from "./packageRetrospectiveProtocol";
import type {
  PackageRetrospectiveRequest,
  PackageRetrospectiveKnowledgeRequest,
} from "./packageRetrospectiveContracts";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));
const mocked = vi.mocked(api);
let f = retrospectiveFixture();
let frozen = f.saved.retrospective;
let publishedToHistory = false;
let linked: typeof f.detail.knowledge_link = null;
const other = "00000000-0000-0000-0000-000000000099";

beforeEach(() => {
  sessionStorage.clear();
  f = retrospectiveFixture();
  frozen = f.saved.retrospective;
  publishedToHistory = false;
  linked = null;
  mocked.mockReset();
  mocked.mockImplementation(async (path, options) => {
    const url = new URL(path, "http://synthetic.test"),
      base = retrospectiveBase(f.bid_id);
    if (url.pathname === base + "/choices") {
      const kind = url.searchParams.get("kind") as keyof typeof f.choices;
      const selected = url.searchParams.get("submission_id");
      const data = structuredClone(f.choices[kind]);
      if (kind === "submissions")
        data.items.push({
          ...data.items[0],
          id: other,
          label: "另一条合成实交",
          current: false,
        });
      else if (selected !== f.selection.submission_id) {
        data.submission_id = selected;
        data.items = [];
      }
      return { data, etag: null };
    }
    if (url.pathname === base + "/preview")
      return { data: f.preview, etag: f.preview_etag };
    if (url.pathname === base && options?.method === "POST") {
      const result = await retrospectiveAckFor(
        f,
        options.body as PackageRetrospectiveRequest,
        options.key!,
        options.etag!,
      );
      frozen = result.data.retrospective;
      publishedToHistory = true;
      return result;
    }
    if (url.pathname === base)
      return {
        data: {
          bid_id: f.bid_id,
          items: publishedToHistory
            ? [
                {
                  id: frozen.manifest.id,
                  title: frozen.manifest.title,
                  submission_id: f.selection.submission_id,
                  created_at: frozen.manifest.created_at,
                  digest: frozen.digest,
                },
              ]
            : [],
          next_offset: null,
        },
        etag: null,
      };
    if (url.pathname.endsWith("/knowledge-candidate")) {
      const result = await retrospectiveKnowledgeAckFor(
        f,
        frozen,
        options!.body as PackageRetrospectiveKnowledgeRequest,
        options!.key!,
        options!.etag!,
      );
      linked = result.data.link;
      return result;
    }
    if (url.pathname === base + "/" + frozen.manifest.id)
      return {
        data: {
          retrospective: frozen,
          current: { unchanged: true, issues: [] },
          knowledge_link: linked,
        },
        etag: f.saved_etag,
      };
    throw new Error("Unexpected synthetic retrospective path: " + path);
  });
});

function mount(onKnowledgeCreated = vi.fn()) {
  return render(
    <PackageRetrospectives
      bidId={f.bid_id}
      memberId={f.member_id}
      onKnowledgeCreated={onKnowledgeCreated}
    />,
  );
}
async function choose() {
  await screen.findByRole("option", { name: /补录实交/ });
  fireEvent.change(screen.getByLabelText("本次复盘的实际提交"), {
    target: { value: f.selection.submission_id },
  });
  await screen.findByRole("option", { name: /技术总分 0/ });
}
async function fill() {
  await choose();
  fireEvent.change(screen.getByLabelText("官方成绩记录"), {
    target: { value: f.selection.outcome_id },
  });
  fireEvent.change(screen.getByLabelText("业务阶段待补原因"), {
    target: { value: f.selection.business_result_missing_reason },
  });
  fireEvent.click(screen.getByText("选择两轮已完成核查"));
  fireEvent.change(screen.getByLabelText("基线侧核查"), {
    target: { value: f.selection.baseline_run_id },
  });
  fireEvent.change(screen.getByLabelText("实交侧核查"), {
    target: { value: f.selection.submitted_run_id },
  });
  fireEvent.change(screen.getByLabelText("复盘标题"), {
    target: { value: f.request.title },
  });
  fireEvent.change(screen.getByLabelText("成员记录的观察（待核）"), {
    target: { value: f.request.notes.observations },
  });
  fireEvent.change(screen.getByLabelText("下一步核对和整改"), {
    target: { value: f.request.notes.next_actions },
  });
}
async function preview() {
  fireEvent.click(screen.getByRole("button", { name: "核对复盘依据" }));
  await screen.findByRole("region", { name: "复盘依据快照" });
}
const mutations = () =>
  mocked.mock.calls.filter(([, options]) => options?.method === "POST");

it("requires explicit actual submission, evidence preview, immutable save and a separate knowledge-candidate action", async () => {
  const open = vi.fn();
  mount(open);
  await screen.findByRole("option", { name: /补录实交/ });
  expect(screen.queryByLabelText("复盘标题")).toBeNull();
  expect(mutations()).toHaveLength(0);
  await fill();
  expect(
    screen.getByRole("button", { name: "保存不可变待核复盘" }),
  ).toBeDisabled();
  await preview();
  expect(
    within(screen.getByRole("region", { name: "复盘依据快照" })).getByText("0"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "保存不可变待核复盘" }));
  await screen.findByText("待人工核对");
  expect(mutations().map(([path]) => path)).toEqual([
    retrospectiveBase(f.bid_id) + "/preview",
    retrospectiveBase(f.bid_id),
  ]);
  expect(open).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("建立候选的原因"), {
    target: { value: f.candidate_request.reason },
  });
  fireEvent.click(screen.getByRole("button", { name: "明确建立企业知识候选" }));
  await screen.findByText(
    "已建立企业知识候选。正式发布状态请在企业知识中核对。",
  );
  expect(
    mutations().some(([path]) =>
      /\/publish|sample-admission|models/.test(path),
    ),
  ).toBe(false);
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "打开企业知识候选" }));
  expect(open).toHaveBeenCalledExactlyOnceWith(f.candidate.link.knowledge_id);
});

it("retains a bad acknowledgement's exact command across refresh and another submission, then recovers the same key", async () => {
  const ordinary = mocked.getMockImplementation()!;
  let bad = true;
  mocked.mockImplementation(async (path, options) => {
    const result = await ordinary(path, options);
    if (
      path === retrospectiveBase(f.bid_id) &&
      options?.method === "POST" &&
      bad
    ) {
      const changed = structuredClone(result) as {
        data: typeof f.saved;
        etag: string;
      };
      changed.data.command.idempotency_key = "unrelated-ack";
      return changed;
    }
    return result;
  });
  const first = mount();
  await fill();
  await preview();
  fireEvent.click(screen.getByRole("button", { name: "保存不可变待核复盘" }));
  await screen.findByText(/复盘所选实交、结果、核查或保存回执不一致/);
  const recordKey = `tender:command-record:${retrospectiveScope(f)}`;
  const original = sessionStorage.getItem(recordKey)!;
  expect(original).toContain(f.request.title);
  first.unmount();
  mount();
  await screen.findByRole("button", { name: "恢复原复盘保存结果" });
  expect(screen.getByLabelText("复盘标题")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("本次复盘的实际提交"), {
    target: { value: other },
  });
  expect(screen.getByLabelText("复盘标题")).toHaveValue("");
  expect(
    screen.queryByRole("button", { name: "恢复原复盘保存结果" }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("本次复盘的实际提交"), {
    target: { value: f.selection.submission_id },
  });
  expect(screen.getByLabelText("复盘标题")).toHaveValue(f.request.title);
  expect(sessionStorage.getItem(recordKey)).toBe(original);
  bad = false;
  fireEvent.click(screen.getByRole("button", { name: "恢复原复盘保存结果" }));
  await screen.findByText("待人工核对");
  expect(sessionStorage.getItem(recordKey)).toBeNull();
  const saves = mutations().filter(
    ([path]) => path === retrospectiveBase(f.bid_id),
  );
  expect(saves).toHaveLength(2);
  expect(saves[1][1]).toEqual(saves[0][1]);
});

it("keeps the original draft while ignoring a preview arriving after another submission was chosen", async () => {
  const ordinary = mocked.getMockImplementation()!;
  let finish!: (result: { data: typeof f.preview; etag: string }) => void;
  mocked.mockImplementation((path, options) =>
    path.endsWith("/preview")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : ordinary(path, options),
  );
  mount();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "核对复盘依据" }));
  fireEvent.change(screen.getByLabelText("本次复盘的实际提交"), {
    target: { value: other },
  });
  await act(async () => finish({ data: f.preview, etag: f.preview_etag }));
  expect(screen.queryByRole("region", { name: "复盘依据快照" })).toBeNull();
  expect(screen.getByLabelText("复盘标题")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("本次复盘的实际提交"), {
    target: { value: f.selection.submission_id },
  });
  expect(screen.getByLabelText("复盘标题")).toHaveValue(f.request.title);
  expect(screen.getByLabelText("成员记录的观察（待核）")).toHaveValue(
    f.request.notes.observations,
  );
  expect(screen.queryByRole("region", { name: "复盘依据快照" })).toBeNull();
  expect(sessionStorage.getItem(retrospectiveDraftKey(f))).toContain(
    f.request.title,
  );
});

it("keeps text after a definitive source conflict and requires a fresh preview before another save", async () => {
  const ordinary = mocked.getMockImplementation()!;
  let conflict = true;
  mocked.mockImplementation(async (path, options) => {
    if (
      conflict &&
      path === retrospectiveBase(f.bid_id) &&
      options?.method === "POST"
    )
      throw new ApiError(
        "所选依据已变化",
        412,
        "PACKAGE_RETROSPECTIVE_PREVIEW_CHANGED",
      );
    return ordinary(path, options);
  });
  mount();
  await fill();
  await preview();
  fireEvent.click(screen.getByRole("button", { name: "保存不可变待核复盘" }));
  await screen.findByText("所选依据已变化");
  expect(screen.getByLabelText("复盘标题")).toHaveValue(f.request.title);
  expect(
    screen.getByRole("button", { name: "保存不可变待核复盘" }),
  ).toBeDisabled();
  expect(
    sessionStorage.getItem(`tender:command-record:${retrospectiveScope(f)}`),
  ).toBeNull();
  conflict = false;
  fireEvent.click(screen.getByRole("button", { name: "核对复盘依据" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "保存不可变待核复盘" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "保存不可变待核复盘" }));
  await screen.findByText("待人工核对");
  const saves = mutations().filter(
    ([path]) => path === retrospectiveBase(f.bid_id),
  );
  expect(saves[1][1]!.key).not.toBe(saves[0][1]!.key);
});
