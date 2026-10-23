import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PackageOfficialOutcomes } from "./PackageOfficialOutcomes";
import type {
  OutcomeRequest,
  PackageOutcomeVerificationRequest,
  ResearchOutcomeDetail,
  ResearchOutcomePage,
  ResearchOutcomeView,
} from "./contracts";
import {
  outcomeFixture,
  outcomeId as id,
  outcomeVerificationAck,
  type OutcomeFixture,
} from "./packageOutcomeFixtures.test-support";
import {
  outcomeHeadEtag,
  outcomeVerificationEtag,
} from "./packageOutcomeProtocol";
import {
  packageOutcomeStorageKey,
  readOutcomeRecovery,
} from "./packageOutcomeRecovery";
import { clearRecordedCommands } from "./recordedCommandStorage";

const response = (
  value: unknown,
  status = 200,
  headers: Record<string, string> = {},
) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
type Write = {
  path: string;
  body: OutcomeRequest | PackageOutcomeVerificationRequest;
  headers: Headers;
};
async function setup(
  initial: "empty" | "pending" = "pending",
  fixture?: OutcomeFixture,
) {
  const f = fixture ?? (await outcomeFixture());
  const server = {
    f,
    context: structuredClone(f.context),
    page: structuredClone(
      initial === "empty" ? { items: [], heads: [] } : f.page,
    ) as ResearchOutcomePage,
    details: new Map<string, ResearchOutcomeDetail>(
      initial === "empty" ? [] : [[f.view.id, structuredClone(f.detail)]],
    ),
    evidence: structuredClone(f.evidence),
    reads: [] as string[],
    writes: [] as Write[],
    onWrite: null as ((w: Write) => Promise<Response>) | null,
    onRead: null as ((path: string) => Response | null) | null,
  };
  const receipts = new Map<
    string,
    { view: ResearchOutcomeView; etag: string }
  >();
  function saveView(view: ResearchOutcomeView, revision: number) {
    server.page.items = [
      ...server.page.items.filter((v) => v.id !== view.id),
      view,
    ];
    server.page.heads = [
      {
        bid_id: f.scope.bidId,
        submission_id: f.submission.id,
        outcome_id: view.id,
        revision,
      },
    ];
    for (const [recordId, detail] of server.details) {
      if (recordId !== view.id)
        server.details.set(recordId, {
          ...detail,
          current: false,
          package_association: {
            ...f.detail.package_association!,
            available: false,
            reasons: ["package_outcome_not_current"],
          },
        });
    }
    server.details.set(view.id, {
      ...view,
      current: true,
      package_association: {
        ...f.detail.package_association!,
        available: view.verification === "verified",
        reasons:
          view.verification === "verified"
            ? []
            : ["package_outcome_verification_unproven"],
      },
    });
  }
  async function accept(w: Write) {
    const key = w.headers.get("Idempotency-Key")!;
    const old = receipts.get(key);
    if (old) return response(old.view, 200, { ETag: old.etag });
    let view: ResearchOutcomeView, etag: string;
    if (w.path.endsWith("/verification")) {
      const target = server.page.items.find(
        (v) => w.path === `/api/v1/outcomes/${v.id}/verification`,
      )!;
      view = await outcomeVerificationAck(
        f,
        w.body as PackageOutcomeVerificationRequest,
        target,
      );
      etag = outcomeVerificationEtag(view.id, view.verification_revision);
      saveView(view, server.page.heads[0].revision);
    } else {
      const previous = w.path.endsWith("/corrections")
        ? w.path.split("/").at(-2)!
        : null;
      view = {
        ...f.view,
        ...(w.body as OutcomeRequest),
        id: id(610 + receipts.size),
        supersedes_id: previous,
        verification: "pending",
        verification_revision: 0,
        verification_details: null,
      };
      const revision = (server.page.heads[0]?.revision ?? 0) + 1;
      etag = outcomeHeadEtag(f.submission.id, revision);
      saveView(view, revision);
    }
    receipts.set(key, { view, etag });
    return response(view, 200, { ETag: etag });
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST") {
        const w: Write = {
          path,
          body: JSON.parse(String(init.body)),
          headers: new Headers(init.headers),
        };
        server.writes.push(w);
        return server.onWrite ? server.onWrite(w) : accept(w);
      }
      server.reads.push(path);
      const overridden = server.onRead?.(path);
      if (overridden) return overridden;
      if (
        path ===
        `/api/v1/bids/${f.scope.bidId}/outcome-context?submission_id=${f.submission.id}`
      )
        return response(server.context);
      if (path === `/api/v1/bids/${f.scope.bidId}/outcomes`)
        return response(server.page);
      if (path === `/api/v1/documents/${f.body.source_version_id}/evidence`)
        return response(server.evidence);
      const detail = [...server.details.values()].find(
        (v) => path === `/api/v1/outcomes/${v.id}`,
      );
      if (detail)
        return response(detail, 200, {
          ETag: outcomeVerificationEtag(
            detail.id,
            detail.verification_revision,
          ),
          "Outcome-Head-ETag": outcomeHeadEtag(
            f.submission.id,
            server.page.heads[0].revision,
          ),
        });
      throw new Error(`Unexpected outcome read: ${path}`);
    }),
  );
  return { f, server, accept, saveView };
}
function component(f: OutcomeFixture, memberId = f.scope.memberId) {
  return (
    <PackageOfficialOutcomes
      bidId={f.scope.bidId}
      memberId={memberId}
      submission={f.submission}
    />
  );
}
async function open() {
  await userEvent.click(
    screen.getByRole("button", { name: "登记／核验此整包的官方成绩" }),
  );
  await screen.findByRole("heading", { name: "官方成绩与原页核验" });
}
async function register(f: OutcomeFixture, unknown = false) {
  await userEvent.click(
    await screen.findByRole("button", { name: /^登记官方成绩$/ }),
  );
  const form = await screen.findByRole("form", { name: "登记整包官方成绩" });
  if (unknown)
    fireEvent.change(within(form).getByLabelText("成绩口径"), {
      target: { value: "unknown" },
    });
  else {
    fireEvent.change(within(form).getByLabelText("得分"), {
      target: { value: f.body.value },
    });
    fireEvent.change(within(form).getByLabelText("满分"), {
      target: { value: f.body.maximum },
    });
  }
  fireEvent.change(within(form).getByLabelText("官方成绩来源原件"), {
    target: { value: f.body.source_version_id },
  });
  fireEvent.change(within(form).getByLabelText("成绩取得时间（含时区）"), {
    target: { value: f.body.known_at },
  });
  return form;
}
async function verify(f: OutcomeFixture, positive = true) {
  await userEvent.click(
    await screen.findByRole("button", { name: "核验这一版官方成绩" }),
  );
  const form = await screen.findByRole("form", { name: "核验整包官方成绩" });
  fireEvent.change(within(form).getByLabelText("核验说明"), {
    target: { value: f.verification.reason },
  });
  if (positive) {
    fireEvent.change(within(form).getByLabelText("核验结论"), {
      target: { value: "verified" },
    });
    fireEvent.change(within(form).getByLabelText("成绩公布时间（含时区）"), {
      target: { value: f.verification.published_at },
    });
    fireEvent.change(within(form).getByLabelText("成绩聚合方式"), {
      target: { value: f.verification.aggregation },
    });
    await userEvent.click(
      await within(form).findByRole("checkbox", { name: /物理页 2/ }),
    );
    await userEvent.click(
      within(form).getByRole("checkbox", { name: /我已逐项核对原实交身份/ }),
    );
  }
  return form;
}
beforeEach(() => {
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("registers a real decimal zero with the exact submission/source, without reading or writing another package", async () => {
  const { f, server } = await setup("empty");
  render(component(f));
  await open();
  expect(server.writes).toHaveLength(0);
  const form = await register(f);
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].body).toEqual(f.body);
  expect(server.writes[0].path).toBe(`/api/v1/bids/${f.scope.bidId}/outcomes`);
  expect(server.writes[0].headers.get("If-Match")).toBeNull();
  expect(
    await screen.findByText("0.00", { selector: ".outcome-value" }),
  ).toBeVisible();
  expect(readOutcomeRecovery(f.scope, f.submission)).toBeNull();
  expect(
    server.reads.every(
      (p) => !p.includes("current-material") && !p.includes("latest"),
    ),
  ).toBe(true);
});

it("keeps unknown results null rather than turning missing scores into zero", async () => {
  const { f, server } = await setup("empty");
  render(component(f));
  await open();
  const form = await register(f, true);
  expect(within(form).getByLabelText("得分")).toBeDisabled();
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes[0].body).toMatchObject({
    score_kind: "unknown",
    value: null,
    maximum: null,
  });
  expect(
    await screen.findByText("未知", { selector: ".outcome-value" }),
  ).toBeVisible();
});

it("appends a correction against the selected native head and retains the original result", async () => {
  const { f, server } = await setup();
  render(component(f));
  await open();
  await userEvent.click(
    await screen.findByRole("button", { name: "追加更正官方成绩" }),
  );
  const form = await screen.findByRole("form", { name: "更正整包官方成绩" });
  expect(within(form).getByLabelText("得分")).toHaveValue("0.00");
  fireEvent.change(within(form).getByLabelText("得分"), {
    target: { value: "9.500" },
  });
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes[0].path).toBe(
    `/api/v1/outcomes/${f.view.id}/corrections`,
  );
  expect(server.writes[0].headers.get("If-Match")).toBe(
    outcomeHeadEtag(f.submission.id, 1),
  );
  expect(server.page.items).toHaveLength(2);
  expect(server.page.items.find((v) => v.id === f.view.id)?.value).toBe("0.00");
  expect(server.page.items.find((v) => v.id !== f.view.id)?.supersedes_id).toBe(
    f.view.id,
  );
});

it("verifies exact original package authority and physical-page quotes without granting formal sample eligibility", async () => {
  const { f, server } = await setup();
  render(component(f));
  await open();
  const form = await verify(f);
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes[0].path).toBe(
    `/api/v1/outcomes/${f.view.id}/verification`,
  );
  expect(server.writes[0].headers.get("If-Match")).toBe(
    outcomeVerificationEtag(f.view.id, 0),
  );
  expect(server.writes[0].body).toEqual(f.verification);
  expect(server.reads).toContain(
    `/api/v1/documents/${f.body.source_version_id}/evidence`,
  );
  expect(
    await screen.findByText("这条官方成绩关联目前仍有有效依据。", {
      exact: false,
    }),
  ).toBeVisible();
  expect(screen.getByText(/核验通过也不会将成绩加入训练样本/)).toBeVisible();
});

it("does not offer positive verification when original authority was absent, but permits a pending opinion", async () => {
  const { f, server } = await setup("pending", await outcomeFixture(false));
  render(component(f));
  await open();
  const form = await verify(f, false);
  expect(
    within(form).getByRole("option", { name: "确认已核验" }),
  ).toBeDisabled();
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes[0].body).toMatchObject({
    state: "pending",
    authority: null,
    evidence_refs: [],
  });
});

it("requires an explicit contiguous excerpt from a long original block and blocks rewritten quotations", async () => {
  const { f, server } = await setup();
  const excerpt = f.evidence.items[0].quote;
  server.evidence.items[0].quote =
    "前序公示原文。".repeat(700) + excerpt + "后续说明。".repeat(200);
  render(component(f));
  await open();
  const form = await verify(f);
  const quote = within(form).getByLabelText(
    "物理页 2 的逐字摘录（最多 4000 字）",
    { exact: false },
  );
  expect(quote).toHaveValue("");
  expect(within(form).getByText(/系统不会自动截断或改写原文/)).toBeVisible();
  fireEvent.change(quote, {
    target: { value: "这一段不在原页中，不能把改写作为官方引文。" },
  });
  expect(
    within(form).getByRole("checkbox", { name: /我已逐项核对原实交身份/ }),
  ).not.toBeChecked();
  await userEvent.click(
    within(form).getByRole("checkbox", { name: /我已逐项核对原实交身份/ }),
  );
  fireEvent.submit(form);
  expect(
    await screen.findByText(/所选摘录必须逐字来自这一份成绩原件的对应原页/),
  ).toBeVisible();
  expect(server.writes).toHaveLength(0);
  fireEvent.change(quote, { target: { value: excerpt } });
  await userEvent.click(
    within(form).getByRole("checkbox", { name: /我已逐项核对原实交身份/ }),
  );
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes).toHaveLength(1);
  expect(
    (server.writes[0].body as PackageOutcomeVerificationRequest).evidence_refs,
  ).toEqual(f.verification.evidence_refs);
});

it("rejects a mismatched evidence response and never substitutes other-source quotes", async () => {
  const { f, server } = await setup();
  server.evidence.document_version_id = id(799);
  render(component(f));
  await open();
  await userEvent.click(
    await screen.findByRole("button", { name: "核验这一版官方成绩" }),
  );
  const form = await screen.findByRole("form", { name: "核验整包官方成绩" });
  expect(await screen.findByText(/引文响应与成绩来源身份不一致/)).toBeVisible();
  expect(
    within(form).queryByRole("checkbox", { name: /物理页/ }),
  ).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("核验结论"), {
    target: { value: "verified" },
  });
  fireEvent.change(within(form).getByLabelText("核验说明"), {
    target: { value: "需要原页，不能替代。" },
  });
  fireEvent.submit(form);
  expect(
    await screen.findByText(/确认核验还需要原提交绑定的依据包/),
  ).toBeVisible();
  expect(server.writes).toHaveLength(0);
});

it("restores a lost correction ACK after remount using exactly the original body, key and head tag even after history changes", async () => {
  const { f, server, accept } = await setup();
  server.onWrite = async (w) => {
    await accept(w);
    throw new Error("lost committed ACK");
  };
  const mounted = render(component(f));
  await open();
  await userEvent.click(
    await screen.findByRole("button", { name: "追加更正官方成绩" }),
  );
  const form = await screen.findByRole("form", { name: "更正整包官方成绩" });
  fireEvent.change(within(form).getByLabelText("得分"), {
    target: { value: "12.3400" },
  });
  fireEvent.submit(form);
  await screen.findByRole("button", { name: "恢复原成绩操作" });
  const saved = readOutcomeRecovery(f.scope, f.submission)!;
  expect(saved.kind).toBe("correct");
  expect(server.page.heads[0].revision).toBe(2);
  mounted.unmount();
  server.onWrite = null;
  render(component(f));
  await open();
  await screen.findByText("12.3400", { selector: ".outcome-value" });
  expect(readOutcomeRecovery(f.scope, f.submission)).toEqual(saved);
  await userEvent.click(screen.getByRole("button", { name: "恢复原成绩操作" }));
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1].body).toEqual(server.writes[0].body);
  expect(server.writes[1].headers.get("Idempotency-Key")).toBe(saved.key);
  expect(server.writes[1].headers.get("If-Match")).toBe(saved.etag);
  expect(readOutcomeRecovery(f.scope, f.submission)).toBeNull();
});

it("restores a lost verification ACK with the original evidence and revision after verified history is visible", async () => {
  const { f, server, accept } = await setup();
  server.onWrite = async (w) => {
    await accept(w);
    throw new Error("lost verification ACK");
  };
  const mounted = render(component(f));
  await open();
  fireEvent.submit(await verify(f));
  await screen.findByRole("button", { name: "恢复原成绩操作" });
  const saved = readOutcomeRecovery(f.scope, f.submission)!;
  expect(saved.kind).toBe("verify");
  mounted.unmount();
  server.onWrite = null;
  render(component(f));
  await open();
  await screen.findByText("已记录核验通过", { selector: ".badge" });
  expect(readOutcomeRecovery(f.scope, f.submission)).toEqual(saved);
  await userEvent.click(screen.getByRole("button", { name: "恢复原成绩操作" }));
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1].body).toEqual(saved.body);
  expect(server.writes[1].headers.get("If-Match")).toBe(
    outcomeVerificationEtag(f.view.id, 0),
  );
  expect(server.writes[1].headers.get("Idempotency-Key")).toBe(saved.key);
  expect(readOutcomeRecovery(f.scope, f.submission)).toBeNull();
});

it.each(["wrong scope", "wrong ETag", "unknown 422"])(
  "keeps the original recovery record for %s",
  async (fault) => {
    const { f, server } = await setup("empty");
    server.onWrite = async (w) =>
      fault === "unknown 422"
        ? response(
            {
              code: "PACKAGE_OUTCOME_UNRECOGNIZED",
              message: "Uncertain new contract error",
            },
            422,
          )
        : response(
            {
              ...f.view,
              ...(w.body as OutcomeRequest),
              ...(fault === "wrong scope" ? { submission_id: id(777) } : {}),
            },
            200,
            {
              ETag: outcomeHeadEtag(
                f.submission.id,
                fault === "wrong ETag" ? 2 : 1,
              ),
            },
          );
    render(component(f));
    await open();
    fireEvent.submit(await register(f));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "恢复原成绩操作" }),
      ).toBeEnabled(),
    );
    expect(readOutcomeRecovery(f.scope, f.submission)?.body).toEqual(f.body);
    expect(screen.queryByText(/已取得原操作回执/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存成绩登记" })).toBeDisabled();
  },
);

it("preserves all verification inputs on an explicit 412 and requires a fresh read and explicit version adoption", async () => {
  const { f, server } = await setup();
  server.onWrite = async () =>
    response(
      {
        code: "REVISION_CONFLICT",
        message: "The verification version changed",
      },
      412,
    );
  render(component(f));
  await open();
  const form = await verify(f);
  fireEvent.submit(form);
  const adopt = await screen.findByRole("button", {
    name: "采用已核对版本，保留当前输入",
  });
  expect(adopt).toBeDisabled();
  expect(readOutcomeRecovery(f.scope, f.submission)).toBeNull();
  expect(within(form).getByLabelText("核验说明")).toHaveValue(
    f.verification.reason,
  );
  expect(
    within(form).getByRole("button", { name: "保存这一版核验意见" }),
  ).toBeDisabled();
  const latest = await outcomeVerificationAck(f, {
    ...f.verification,
    state: "pending",
    aggregation: "",
    published_at: null,
    evidence_refs: [],
    reason: "另一操作仅登记待核验意见",
  });
  server.page.items = [latest];
  server.details.set(latest.id, { ...f.detail, ...latest });
  await userEvent.click(
    screen.getByRole("button", { name: "重新读取并核对当前记录" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByText("正在读取原提交身份、成绩头与来源状态…"),
    ).not.toBeInTheDocument(),
  );
  expect(
    within(form).getByRole("button", { name: "保存这一版核验意见" }),
  ).toBeDisabled();
  await userEvent.click(adopt);
  expect(within(form).getByLabelText("成绩公布时间（含时区）")).toHaveValue(
    f.verification.published_at,
  );
  expect(
    within(form).getByRole("checkbox", { name: /物理页 2/ }),
  ).toBeChecked();
  server.onWrite = null;
  fireEvent.submit(form);
  await screen.findByText(/已取得原操作回执/);
  expect(server.writes).toHaveLength(2);
  expect(server.writes[1].body).toEqual(server.writes[0].body);
  expect(server.writes[1].headers.get("If-Match")).toBe(
    outcomeVerificationEtag(f.view.id, 1),
  );
  expect(server.writes[1].headers.get("Idempotency-Key")).not.toBe(
    server.writes[0].headers.get("Idempotency-Key"),
  );
});

it("does not silently rebase edits onto a different current outcome", async () => {
  const { f, server, saveView } = await setup();
  render(component(f));
  await open();
  await userEvent.click(
    await screen.findByRole("button", { name: "追加更正官方成绩" }),
  );
  const form = await screen.findByRole("form", { name: "更正整包官方成绩" });
  fireEvent.change(within(form).getByLabelText("得分"), {
    target: { value: "15.00" },
  });
  saveView(
    { ...f.view, id: id(800), value: "19", supersedes_id: f.view.id },
    2,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "重新读取并核对当前记录" }),
  );
  const adopt = await screen.findByRole("button", {
    name: "采用已核对版本，保留当前输入",
  });
  expect(adopt).toBeDisabled();
  expect(within(form).getByLabelText("得分")).toHaveValue("15.00");
  expect(
    within(form).getByRole("button", { name: "保存成绩更正" }),
  ).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});

it("retains historical verified state when an official source is withdrawn while clearly marking current association unavailable", async () => {
  const { f, server } = await setup();
  const verified = await outcomeVerificationAck(f);
  server.page.items = [verified];
  server.details.set(verified.id, {
    ...f.detail,
    ...verified,
    package_association: {
      ...f.detail.package_association!,
      available: false,
      reasons: ["package_outcome_source_no_longer_effective"],
    },
  });
  server.evidence.items[0].source_status = "withdrawn";
  render(component(f));
  await open();
  expect(
    await screen.findByText("已记录核验通过", { selector: ".badge" }),
  ).toBeVisible();
  expect(
    screen.getByText(/当前关联不可用：官方结果来源已撤回或不再生效/),
  ).toBeVisible();
  expect(screen.getByText(/核验历史不会因来源后续变化被改写/)).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "核验这一版官方成绩" }),
  );
  expect(
    await screen.findByRole("checkbox", { name: /物理页 2/ }),
  ).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});

it("makes no write when browser recovery storage is full and preserves input for another attempt", async () => {
  const { f, server } = await setup("empty");
  render(component(f));
  await open();
  const form = await register(f);
  const original = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (key === packageOutcomeStorageKey(f.scope))
      throw new DOMException("full", "QuotaExceededError");
    original.call(this, key, value);
  });
  fireEvent.submit(form);
  expect(
    await screen.findByText(/浏览器无法更新成绩操作恢复记录/),
  ).toBeVisible();
  expect(server.writes).toHaveLength(0);
  expect(within(form).getByLabelText("得分")).toHaveValue("0.00");
  expect(within(form).getByLabelText("成绩取得时间（含时区）")).toHaveValue(
    f.body.known_at,
  );
});

it("blocks new writes for damaged recovery while still allowing exact server history to be read", async () => {
  const { f, server } = await setup();
  sessionStorage.setItem(packageOutcomeStorageKey(f.scope), "broken");
  render(component(f));
  await open();
  expect(
    await screen.findByText(/成绩操作恢复记录损坏或实交身份不符/),
  ).toBeVisible();
  expect(
    await screen.findByText("0.00", { selector: ".outcome-value" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "追加更正官方成绩" }),
  ).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});

it("ignores a late ACK after unmount/account cleanup and does not recreate another member's pending command", async () => {
  const { f, server, accept } = await setup("empty");
  let finish!: (value: Response) => void;
  server.onWrite = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  const mounted = render(component(f));
  await open();
  fireEvent.submit(await register(f));
  await waitFor(() => expect(server.writes).toHaveLength(1));
  expect(readOutcomeRecovery(f.scope, f.submission)).not.toBeNull();
  mounted.unmount();
  clearRecordedCommands(id(990));
  render(component(f, id(990)));
  await open();
  await screen.findByRole("button", { name: /^登记官方成绩$/ });
  await act(async () => {
    finish(await accept(server.writes[0]));
  });
  expect(sessionStorage.getItem(packageOutcomeStorageKey(f.scope))).toBeNull();
  expect(
    sessionStorage.getItem(
      packageOutcomeStorageKey({ ...f.scope, memberId: id(990) }),
    ),
  ).toBeNull();
  expect(screen.queryByText(/已取得原操作回执/)).not.toBeInTheDocument();
  expect(server.writes).toHaveLength(1);
});
