import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageRuleCorrections } from "./PackageRuleCorrections";
import { correctionEvidenceTextDigest } from "./packageRuleCorrectionProtocol";
import type {
  ApplyPackageRuleCorrection,
  PackageRuleCorrectionAppliedView,
  PackageRuleCorrectionRequest,
} from "./contracts";
import {
  correctionBase,
  correctionEvidencePath,
  correctionInventoryPath,
  correctionPath,
  correctionStorageKey,
  readCorrectionRecovery,
  writeCorrectionRecovery,
  type PendingCorrection,
} from "./packageRuleCorrectionRecovery";
import {
  correctionApplied,
  correctionFixture,
  correctionId,
  correctionPackage,
  correctionPreview,
  correctionRule,
  correctionScope,
  omitCorrectionFixture,
} from "./packageRuleCorrectionFixtures.test-support";

const response = (body: unknown, status = 200, etag?: string) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
async function setup() {
  const fixture = await correctionFixture();
  const server = {
    ...fixture,
    head: fixture.inventory.manifest.id,
    evidence: structuredClone(fixture.evidence),
    last: null as PackageRuleCorrectionAppliedView | null,
    writes: [] as { kind: "preview" | "apply"; options: RequestInit }[],
    reads: [] as string[],
    onApply: null as ((options: RequestInit) => Promise<Response>) | null,
    onPreview: null as
      | ((body: PackageRuleCorrectionRequest) => Promise<Response>)
      | null,
  };
  const base = `/api/v1${correctionPath(correctionScope, fixture.inventory.manifest.id)}`;
  const evidence = `/api/v1${correctionEvidencePath(correctionScope, fixture.inventory.manifest.id)}`;
  async function accept(options: RequestInit) {
    const body = JSON.parse(String(options.body)) as ApplyPackageRuleCorrection;
    const preview = await correctionPreview(
      server.inventory,
      body.request,
      server.evidence,
    );
    const pending: PendingCorrection = {
      body,
      key: new Headers(options.headers).get("Idempotency-Key")!,
      etag: new Headers(options.headers).get("If-Match")!,
      base: correctionBase(server.inventory),
    };
    server.last = await correctionApplied(server.inventory, preview, pending);
    server.head = server.last.inventory.manifest.id;
    return response(
      server.last,
      201,
      `"requirement-inventory:${correctionScope.revisionId}:${server.last.inventory.digest}"`,
    );
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      const path = String(input);
      if (options?.method === "POST") {
        if (path === `${base}/preview`) {
          server.writes.push({ kind: "preview", options });
          const body = JSON.parse(
            String(options.body),
          ) as PackageRuleCorrectionRequest;
          return server.onPreview
            ? server.onPreview(body)
            : response(
                await correctionPreview(
                  server.inventory,
                  body,
                  server.evidence,
                ),
              );
        }
        if (path === base) {
          server.writes.push({ kind: "apply", options });
          return server.onApply ? server.onApply(options) : accept(options);
        }
        throw new Error(`Unexpected POST ${path}`);
      }
      server.reads.push(path);
      if (
        path === `/api/v1${correctionInventoryPath(correctionScope)}?limit=20`
      )
        return response(
          {
            current_inventory_id: server.head,
            items: [
              {
                id: server.head,
                digest: server.inventory.digest,
                created_at: "2026-10-21T00:00:00Z",
              },
            ],
            has_more: false,
            next_cursor: null,
          },
          200,
          server.head === server.inventory.manifest.id
            ? server.etag
            : '"changed-head"',
        );
      if (
        path ===
        `/api/v1${correctionInventoryPath(correctionScope)}/${server.inventory.manifest.id}`
      )
        return response(server.inventory, 200, server.etag);
      if (path === `${evidence}?limit=20`) return response(server.page);
      if (path === `${evidence}/${server.evidence.evidence.evidence_id}`)
        return response(server.evidence);
      if (path === `${base}?limit=20`) {
        const m = server.last?.correction.manifest;
        return response({
          scope: server.page.scope,
          items: m
            ? [
                {
                  id: m.id,
                  digest: server.last!.correction.digest,
                  created_at: m.created_at,
                  actor_id: m.actor_id,
                  base_inventory_id: server.inventory.manifest.id,
                  result_inventory_id: m.result.inventory_id,
                  added: m.request.changes.filter((item) => item.op === "add")
                    .length,
                  replaced: m.request.changes.filter(
                    (item) => item.op === "replace",
                  ).length,
                  withdrawn: m.request.changes.filter(
                    (item) => item.op === "withdraw",
                  ).length,
                },
              ]
            : [],
          has_more: false,
          next_cursor: null,
        });
      }
      if (
        server.last &&
        path === `${base}/${server.last.correction.manifest.id}`
      )
        return response(
          server.last,
          200,
          `"requirement-inventory:${correctionScope.revisionId}:${server.last.inventory.digest}"`,
        );
      throw new Error(`Unexpected GET ${path}`);
    }),
  );
  return { server, accept };
}
type Props = ComponentProps<typeof PackageRuleCorrections>;
function mount(
  server: Awaited<ReturnType<typeof setup>>["server"],
  overrides: Partial<Props> = {},
) {
  const props: Props = {
    bidId: correctionScope.bidId,
    memberId: correctionScope.memberId,
    packageView: correctionPackage,
    inventory: server.inventory,
    inventoryEtag: server.etag,
    currentInventoryId: server.inventory.manifest.id,
    currentKnown: true,
    onPendingChange: vi.fn(),
    onApplied: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  };
  return { ...render(<PackageRuleCorrections {...props} />), props };
}
async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "打开规则修订" }));
  await user.click(screen.getByRole("button", { name: "增加一项条款修订" }));
}
async function addQuote(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "选择冻结原页依据" }));
  await user.click(
    await screen.findByRole("button", { name: /依据 1 · 招标原件 · 物理页 3/ }),
  );
  await user.click(
    await screen.findByRole("button", { name: "填入这段完整原文" }),
  );
  await user.click(screen.getByRole("button", { name: "采用这段逐字引用" }));
}
async function queueAdd(user: ReturnType<typeof userEvent.setup>) {
  await openEditor(user);
  fireEvent.change(screen.getByLabelText("条款解释"), {
    target: { value: "安全保障须列明责任人" },
  });
  fireEvent.change(screen.getByLabelText("适用范围"), {
    target: { value: "一标段" },
  });
  await user.click(screen.getByRole("button", { name: "添加条件" }));
  fireEvent.change(screen.getByLabelText("条件 1（逐字原文）"), {
    target: { value: "仅本标段适用" },
  });
  await user.click(screen.getByRole("button", { name: "添加例外" }));
  fireEvent.change(screen.getByLabelText("例外 1（逐字原文）"), {
    target: { value: "除正式补遗另有说明" },
  });
  await addQuote(user);
  await user.click(screen.getByRole("button", { name: "加入本次修订" }));
  fireEvent.change(screen.getByLabelText("本次修订理由"), {
    target: { value: "核对冻结招标原页，补齐安全保障责任" },
  });
}
async function previewAndConfirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "预览本次修订" }));
  const region = await screen.findByRole("region", {
    name: "规则修订结果预览",
  });
  expect(within(region).getByRole("heading", { name: "修订前" })).toBeVisible();
  expect(within(region).getByRole("heading", { name: "修订后" })).toBeVisible();
  await user.click(
    screen.getByRole("checkbox", { name: /我已核对全部前后差异/ }),
  );
}
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it("keeps preview separate from save and submits exact frozen-source content only after explicit confirmation", async () => {
  const { server } = await setup(),
    user = userEvent.setup(),
    { props } = mount(server, { onDirtyChange: vi.fn() });
  expect(server.writes).toHaveLength(0);
  await queueAdd(user);
  expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
  await previewAndConfirm(user);
  expect(server.writes.map((item) => item.kind)).toEqual(["preview"]);
  expect(screen.getByText(/解析仍有缺口/)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await waitFor(() =>
    expect(props.onApplied).toHaveBeenCalledWith(correctionId(101)),
  );
  const applied = server.writes.find((item) => item.kind === "apply")!;
  const body = JSON.parse(
    String(applied.options.body),
  ) as ApplyPackageRuleCorrection;
  expect(body.request.changes).toEqual([{ op: "add", rule: correctionRule() }]);
  expect(new Headers(applied.options.headers).get("If-Match")).toBe(
    server.etag,
  );
  expect(readCorrectionRecovery(correctionScope).pending).toBeNull();
  expect(props.onPendingChange).toHaveBeenCalledWith(true);
  await waitFor(() =>
    expect(props.onPendingChange).toHaveBeenLastCalledWith(false),
  );
  expect(props.onDirtyChange).toHaveBeenLastCalledWith(false);
});
it("reports an unfinished inner editor until the member explicitly cancels it", async () => {
  const { server } = await setup(),
    user = userEvent.setup(),
    onDirtyChange = vi.fn();
  mount(server, { onDirtyChange });
  await openEditor(user);
  fireEvent.change(screen.getByLabelText("条款解释"), {
    target: { value: "尚未加入预览的合成解释" },
  });
  expect(onDirtyChange).toHaveBeenLastCalledWith(true);
  await user.click(screen.getByRole("button", { name: "取消本项编辑" }));
  expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  expect(server.writes).toHaveLength(0);
});
it("recovers a lost successful ACK with the identical body/key/etag after remount, even if the current inventory changed", async () => {
  const { server, accept } = await setup(),
    user = userEvent.setup(),
    first = mount(server);
  server.onApply = async (options) => {
    await accept(options);
    throw new Error("lost acknowledgement");
  };
  await queueAdd(user);
  await previewAndConfirm(user);
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await screen.findByRole("button", { name: "恢复原规则修订" });
  const original = server.writes.find((item) => item.kind === "apply")!.options;
  expect(readCorrectionRecovery(correctionScope).pending).not.toBeNull();
  first.unmount();
  server.onApply = async () =>
    response(
      server.last,
      201,
      `"requirement-inventory:${correctionScope.revisionId}:${server.last!.inventory.digest}"`,
    );
  const second = mount(server, {
    inventory: null,
    currentInventoryId: correctionId(101),
    disabled: true,
  });
  await user.click(screen.getByRole("button", { name: "恢复原规则修订" }));
  await waitFor(() =>
    expect(second.props.onApplied).toHaveBeenCalledWith(correctionId(101)),
  );
  const replay = server.writes.filter((item) => item.kind === "apply")[1]
    .options;
  expect(replay.body).toBe(original.body);
  expect(new Headers(replay.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(new Headers(replay.headers).get("If-Match")).toBe(
    new Headers(original.headers).get("If-Match"),
  );
});
it("retains a mismatched ACK and locks new corrections instead of reporting success", async () => {
  const { server, accept } = await setup(),
    user = userEvent.setup(),
    { props } = mount(server);
  server.onApply = async (options) => {
    const original = await accept(options);
    const body = (await original.json()) as PackageRuleCorrectionAppliedView;
    body.command.idempotency_key = correctionId(999);
    return response(body, 201, original.headers.get("ETag")!);
  };
  await queueAdd(user);
  await previewAndConfirm(user);
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await screen.findByRole("button", { name: "恢复原规则修订" });
  expect(props.onApplied).not.toHaveBeenCalled();
  expect(readCorrectionRecovery(correctionScope).pending).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "增加一项条款修订" }),
  ).toBeDisabled();
});
it("checks the current head again after preview and preserves the proposal if another writer won", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount(server);
  await queueAdd(user);
  await previewAndConfirm(user);
  server.head = correctionId(999);
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await screen.findByText(/当前清单已变化/);
  expect(server.writes.filter((item) => item.kind === "apply")).toHaveLength(0);
  expect(
    screen.getByRole("region", { name: "规则修订结果预览" }),
  ).toBeVisible();
  expect(readCorrectionRecovery(correctionScope).pending).toBeNull();
});
it("rejects an evidence detail from a different parse before allowing it to become a quote", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  server.evidence.evidence.parse_run_id = correctionId(999);
  mount(server);
  await openEditor(user);
  await user.click(screen.getByRole("button", { name: "选择冻结原页依据" }));
  await user.click(
    await screen.findByRole("button", { name: /依据 1 · 招标原件/ }),
  );
  await screen.findByText(/原页来源、摘要或操作回执无法核对/);
  expect(
    screen.queryByRole("button", { name: "采用这段逐字引用" }),
  ).not.toBeInTheDocument();
  expect(server.writes).toHaveLength(0);
});
it("does not send apply if browser recovery storage is unavailable", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount(server);
  await queueAdd(user);
  await previewAndConfirm(user);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await screen.findByText(/浏览器未能保存规则修订恢复记录/);
  expect(server.writes.filter((item) => item.kind === "apply")).toHaveLength(0);
});
it("requires an exact extraction baseline and does not offer legacy/current-material substitution", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  const common = omitCorrectionFixture(
    server.inventory.manifest as Extract<
      typeof server.inventory.manifest,
      { version: "bid-package-requirements/2" }
    >,
    [
      "extraction_input_digest",
      "extraction_result_digest",
      "extraction_result_id",
      "extraction_range_status",
      "extraction_coverage",
      "extraction_quality_status",
    ],
  );
  mount(server, {
    inventory: {
      digest: server.inventory.digest,
      manifest: {
        ...common,
        version: "bid-package-requirements/1",
        extraction_binding: "unproven_legacy_rule_set",
      },
    },
  });
  await user.click(screen.getByRole("button", { name: "打开规则修订" }));
  expect(screen.getByText(/尚未绑定可核对的精确抽取结果/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "增加一项条款修订" }),
  ).not.toBeInTheDocument();
  expect(server.writes).toHaveLength(0);
  expect(server.reads).toHaveLength(0);
});
it("blocks corrupt recovery instead of silently replacing the original request", async () => {
  const { server } = await setup();
  sessionStorage.setItem(correctionStorageKey(correctionScope), "broken");
  const { props } = mount(server);
  expect(
    screen.getByRole("button", { name: "增加一项条款修订" }),
  ).toBeDisabled();
  await waitFor(() =>
    expect(props.onPendingChange).toHaveBeenLastCalledWith(true),
  );
  expect(server.writes).toHaveLength(0);
});
it("reads saved full before/after history without creating a preview or applying a command", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  const preview = await correctionPreview(
    server.inventory,
    server.request,
    server.evidence,
  );
  server.last = await correctionApplied(server.inventory, preview);
  mount(server);
  await user.click(screen.getByRole("button", { name: "打开规则修订" }));
  await user.click(screen.getByRole("button", { name: "读取修订历史" }));
  await user.click(await screen.findByRole("button", { name: /读取修订 1/ }));
  const detail = await screen.findByRole("region", {
    name: "已保存的规则修订记录",
  });
  expect(
    within(detail).getByRole("heading", { name: "历史原条款" }),
  ).toBeVisible();
  expect(
    within(detail).getByText("安全保障须列明责任人", { exact: true }),
  ).toBeVisible();
  expect(server.writes).toHaveLength(0);
});
it("keeps the persisted command unresolved when its late ACK arrives after unmount", async () => {
  const { server, accept } = await setup(),
    user = userEvent.setup();
  let release: (() => void) | null = null;
  server.onApply = async (options) => {
    const result = await accept(options);
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    return result;
  };
  const page = mount(server);
  await queueAdd(user);
  await previewAndConfirm(user);
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await waitFor(() => expect(release).not.toBeNull());
  page.unmount();
  await act(async () => {
    release!();
  });
  expect(readCorrectionRecovery(correctionScope).pending).not.toBeNull();
  expect(page.props.onApplied).not.toHaveBeenCalled();
});
it("uses the original pending request despite a later authorization failure", async () => {
  const { server } = await setup();
  const preview = await correctionPreview(
    server.inventory,
    server.request,
    server.evidence,
  );
  const pending: PendingCorrection = {
    key: correctionId(777),
    etag: server.etag,
    base: correctionBase(server.inventory),
    body: { request: server.request, preview_digest: preview.digest },
  };
  writeCorrectionRecovery({
    version: 1,
    scope: correctionScope,
    pending,
    last: null,
  });
  server.onApply = async () =>
    response({ code: "FORBIDDEN", message: "需要恢复授权" }, 403);
  mount(server);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "恢复原规则修订" }));
  await screen.findByText("需要恢复授权");
  expect(readCorrectionRecovery(correctionScope).pending).toEqual(pending);
});
it("previews a scoring replacement and evidenced withdrawal together without flattening exceptions or inheriting the replaced check plan", async () => {
  const { server } = await setup(),
    user = userEvent.setup(),
    { props } = mount(server);
  await openEditor(user);
  await user.selectOptions(screen.getByLabelText("修订方式"), "replace");
  await user.selectOptions(
    screen.getByLabelText("确切旧条款"),
    correctionId(60),
  );
  await user.selectOptions(screen.getByLabelText("条款性质"), "scoring");
  fireEvent.change(screen.getByLabelText("条款满分（精确十进制）"), {
    target: { value: "12.50" },
  });
  await user.click(screen.getByRole("button", { name: "添加评分分档" }));
  fireEvent.change(screen.getByLabelText("分档名称"), {
    target: { value: "优良" },
  });
  fireEvent.change(screen.getByLabelText("分档分值（精确十进制）"), {
    target: { value: "10.25" },
  });
  fireEvent.change(screen.getByLabelText("分档要求（逐字原文）"), {
    target: { value: "优良方案" },
  });
  await addQuote(user);
  await user.click(
    screen.getByRole("checkbox", { name: "招标原件 · 物理页 3" }),
  );
  await user.click(screen.getByRole("button", { name: "加入本次修订" }));
  await user.click(screen.getByRole("button", { name: "增加一项条款修订" }));
  await user.selectOptions(screen.getByLabelText("修订方式"), "withdraw");
  const firstOption = within(screen.getByLabelText("确切旧条款")).getByRole(
    "option",
    { name: /须提交施工方案/ },
  );
  expect(firstOption).toBeDisabled();
  await user.selectOptions(
    screen.getByLabelText("确切旧条款"),
    correctionId(61),
  );
  await addQuote(user);
  await user.click(screen.getByRole("button", { name: "加入本次修订" }));
  fireEvent.change(screen.getByLabelText("本次修订理由"), {
    target: { value: "核对评分档次与补遗取消保证金要求" },
  });
  await user.click(screen.getByRole("button", { name: "预览本次修订" }));
  const preview = await screen.findByRole("region", {
    name: "规则修订结果预览",
  });
  expect(
    within(preview).getByRole("table", { name: "完整评分分档" }),
  ).toBeVisible();
  expect(within(preview).getByText("12.50")).toBeVisible();
  expect(within(preview).getByText("10.25")).toBeVisible();
  expect(within(preview).getAllByText("除正式补遗另有说明").length).toBe(4);
  expect(within(preview).getByText(/已撤销，保留历史/)).toBeVisible();
  await user.click(
    screen.getByRole("checkbox", { name: /我已核对全部前后差异/ }),
  );
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await waitFor(() => expect(props.onApplied).toHaveBeenCalled());
  expect(
    server.last!.inventory.manifest.requirements[0].annotation.mapped,
  ).toBe(false);
  expect(
    server.last!.inventory.manifest.requirements[1].rule_snapshot
      .provenance_status,
  ).toBe("superseded");
  expect(
    server.last!.inventory.manifest.requirements[2].rule_snapshot.statement,
  ).toBe("未选商务条件保持原样");
});
it("does not silently accept a condition absent from selected original quotes", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  mount(server);
  await openEditor(user);
  fireEvent.change(screen.getByLabelText("条款解释"), {
    target: { value: "人工解释" },
  });
  fireEvent.change(screen.getByLabelText("适用范围"), {
    target: { value: "一标段" },
  });
  await user.click(screen.getByRole("button", { name: "添加条件" }));
  fireEvent.change(screen.getByLabelText("条件 1（逐字原文）"), {
    target: { value: "新增未经原文支持的条件" },
  });
  await addQuote(user);
  await user.click(screen.getByRole("button", { name: "加入本次修订" }));
  expect(
    screen.getByText("每项条件和例外都必须逐字包含在采用的引用中。"),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "预览本次修订" })).toBeDisabled();
  expect(server.writes).toHaveLength(0);
});
it("preserves embedded newlines as one condition rather than silently splitting the legal condition", async () => {
  const { server } = await setup(),
    user = userEvent.setup();
  const condition = "第一行限定条件\n第二行仍属于同一条件";
  server.evidence.evidence.text_content += `\n${condition}`;
  server.evidence.evidence.evidence_digest = await correctionEvidenceTextDigest(
    server.evidence.evidence.text_content,
  );
  server.page.items[0].evidence_digest =
    server.evidence.evidence.evidence_digest;
  mount(server);
  await openEditor(user);
  fireEvent.change(screen.getByLabelText("条款解释"), {
    target: { value: "安全保障须列明责任人" },
  });
  fireEvent.change(screen.getByLabelText("适用范围"), {
    target: { value: "一标段" },
  });
  await user.click(screen.getByRole("button", { name: "添加条件" }));
  fireEvent.change(screen.getByLabelText("条件 1（逐字原文）"), {
    target: { value: condition },
  });
  await addQuote(user);
  await user.click(screen.getByRole("button", { name: "加入本次修订" }));
  fireEvent.change(screen.getByLabelText("本次修订理由"), {
    target: { value: "保留多行原条件" },
  });
  await user.click(screen.getByRole("button", { name: "预览本次修订" }));
  await screen.findByRole("region", { name: "规则修订结果预览" });
  const request = JSON.parse(
    String(server.writes[0].options.body),
  ) as PackageRuleCorrectionRequest;
  expect(
    request.changes[0].op === "add" && request.changes[0].rule.conditions,
  ).toEqual([condition]);
});
it("releases only a proven CAS rejection and keeps the preview and entered proposal for review", async () => {
  const { server } = await setup(),
    user = userEvent.setup(),
    { props } = mount(server);
  server.onApply = async () =>
    response({ code: "REVISION_CONFLICT", message: "原清单版本冲突" }, 412);
  await queueAdd(user);
  await previewAndConfirm(user);
  await user.click(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  );
  await screen.findByText("原清单版本冲突");
  expect(readCorrectionRecovery(correctionScope).pending).toBeNull();
  expect(props.onRefresh).toHaveBeenCalledOnce();
  expect(props.onApplied).not.toHaveBeenCalled();
  expect(
    screen.getByRole("region", { name: "规则修订结果预览" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "确认修订并生成新清单" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("本次修订理由")).toHaveValue(
    "核对冻结招标原页，补齐安全保障责任",
  );
  expect(server.writes.filter((item) => item.kind === "apply")).toHaveLength(1);
});
