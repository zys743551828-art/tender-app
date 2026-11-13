/** Explicit synthetic UI fixtures, not native database or DOCX acceptance. */
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import {
  verifyTextEditBase,
  type ExactTextEditBase,
} from "./authoringExactTextEditProtocol";
import { syntheticMultiTextEdit } from "./authoringMultiTextEdit.test-support";
import { syntheticMarkedTextEdit } from "./authoringMarkedTextEdit.test-support";
import type { AuthoringDocument } from "./contracts";
import { jsonDigest } from "./editorSchema";
import { ExactAuthoringTextEdit } from "./ExactAuthoringTextEdit";
import { exactTextEditStorageKey } from "./useExactAuthoringTextEdit";
import native from "./test-fixtures/authoring-exact-text-edit-http.json";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const scope = {
  memberId: native.member_id,
  bidId: native.bid_id,
  draftId: native.parent_status.draft_id,
};
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});

async function setup(
  kind: "single" | "multi" | "marked" = "single",
  options: { count?: number; original?: string } = {},
) {
  let base: ExactTextEditBase;
  let capabilities: unknown = native.capabilities;
  let markedCapabilities: unknown;
  if (kind === "single") {
    base = await verifyTextEditBase(
      structuredClone({
        status: native.parent_status,
        section: native.parent_section,
        qualification: native.parent_qualification,
      }),
      scope,
    );
  } else if (kind === "multi") {
    const fixture = await syntheticMultiTextEdit();
    base = fixture.pending.base;
    capabilities = fixture.capabilities;
  } else {
    const fixture = await syntheticMarkedTextEdit();
    base = fixture.pending.base;
    markedCapabilities = fixture.capabilities;
  }
  const content = base.section.content as AuthoringDocument;
  const first = content.content[0];
  if (first.type !== "paragraph" && first.type !== "heading")
    throw new Error("Synthetic paragraph missing");
  if (options.original !== undefined) {
    const leaf = first.content[0];
    if (leaf.type !== "text") throw new Error("Synthetic text missing");
    leaf.text = options.original;
  }
  if (options.count) {
    content.content = Array.from({ length: options.count }, (_, index) => {
      const node = structuredClone(first);
      node.attrs.id = `11111111-1111-4111-8111-${String(index + 1).padStart(12, "0")}`;
      node.content = [{ type: "text", text: `原节点 ${index + 1}` }];
      return node;
    });
  }
  base.qualification.manifest.section_digest = await jsonDigest(content);
  base.qualification.digest = await jsonDigest(base.qualification.manifest);
  Object.assign(base.status.exact_sections[0], {
    section_digest: base.qualification.manifest.section_digest,
    qualification_digest: base.qualification.digest,
  });
  base = await verifyTextEditBase(base, scope);
  let currentBase = base;
  const state = { conflict: false };
  mocked.mockImplementation(async (path, request) => {
    if (request?.method === "POST")
      throw state.conflict
        ? new ApiError("Synthetic conflict", 412, "DRAFT_REVISION_CONFLICT")
        : new ApiError("Synthetic unknown ACK", 0, "NETWORK_ERROR");
    if (path === "/authoring/exact-text-edit-capabilities")
      return { data: capabilities, etag: null };
    if (path === "/authoring/exact-marked-text-edit-capabilities") {
      if (!markedCapabilities)
        throw new Error("Synthetic marked capability absent");
      return { data: markedCapabilities, etag: null };
    }
    if (path.startsWith("/sections/"))
      return { data: currentBase.section, etag: null };
    if (path.endsWith("/exact-qualification"))
      return { data: currentBase.qualification, etag: null };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  const onSaved = vi.fn().mockResolvedValue(undefined);
  const onEditingChange = vi.fn();
  function component(value: ExactTextEditBase) {
    return (
      <ExactAuthoringTextEdit
        {...scope}
        sectionId={value.section.id}
        status={value.status}
        etag={`"draft:${scope.draftId}:${value.status.draft_revision}"`}
        disabled={false}
        onSaved={onSaved}
        onEditingChange={onEditingChange}
      />
    );
  }
  const view = render(component(base));
  const begin = await screen.findByRole("button", {
    name: kind === "marked" ? "保留格式修改本章文字" : "修改本章固定来源文字",
  });
  await waitFor(() => expect(begin).toBeEnabled());
  await userEvent.click(begin);
  return {
    base,
    view,
    state,
    onSaved,
    onEditingChange,
    update(value: ExactTextEditBase) {
      currentBase = value;
      view.rerender(component(value));
    },
  };
}

const posts = () =>
  mocked.mock.calls.filter(([, request]) => request?.method === "POST");
const preview = () => screen.getByRole("region", { name: "本次文字修改对照" });
function details(index = 0) {
  const element = preview().querySelectorAll("details")[index];
  if (!element) throw new Error("Expected synthetic preview");
  return element;
}
async function open(index = 0) {
  const element = details(index);
  await userEvent.click(element.querySelector("summary")!);
  await within(element).findByLabelText("拟修改后全文");
  return element;
}
function change(value: string) {
  fireEvent.change(screen.getByLabelText("修改后的文字"), {
    target: { value },
  });
}
async function confirm() {
  fireEvent.change(screen.getByLabelText("修订说明"), {
    target: { value: native.request.reason },
  });
  await userEvent.click(screen.getByRole("checkbox"));
}

it.each(["single", "marked"] as const)(
  "compares complete Unicode/HTML text without applying or changing confirmation (%s)",
  async (kind) => {
    const before = "工期30天 👩🏽‍💻 e\u0301 <img src=x onerror=alert(1)> 原文尾";
    const after = "工期45天 👨‍👩‍👧‍👦 e\u0301 <script>synthetic()</script> 新文尾";
    const f = await setup(kind, { original: before });
    const sourceBytes = JSON.stringify(f.base.section.content);
    change(after);
    await confirm();
    const save = screen.getByRole("button", { name: "确认保存人工修订" });
    expect(save).toBeEnabled();
    const item = await open();
    expect(within(item).getByLabelText("修改前全文").textContent).toBe(before);
    expect(within(item).getByLabelText("拟修改后全文").textContent).toBe(after);
    expect(item.querySelectorAll("mark").length).toBeGreaterThan(0);
    expect(item.querySelector("img, script")).toBeNull();
    await userEvent.click(within(item).getByRole("button", { name: "修改前" }));
    expect(item.querySelector(".text-change-preview")).toHaveAttribute(
      "data-side",
      "before",
    );
    await userEvent.click(
      within(item).getByRole("button", { name: "拟修改后" }),
    );
    await userEvent.click(item.querySelector("summary")!);
    await userEvent.click(item.querySelector("summary")!);
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(save).toBeEnabled();
    expect(screen.getByLabelText("修改后的文字")).toHaveValue(after);
    expect(JSON.stringify(f.base.section.content)).toBe(sourceBytes);
    expect(posts()).toHaveLength(0);
    expect(f.onSaved).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBeNull();
  },
);

it("retains both full sides for long changes and reports bounded block comparison", async () => {
  const before = "甲".repeat(1500) + "旧稿完整结尾";
  const after = "乙".repeat(1500) + "拟稿完整结尾";
  await setup("single", { original: before });
  change(after);
  const item = await open();
  expect(within(item).getByLabelText("修改前全文").textContent).toBe(before);
  expect(within(item).getByLabelText("拟修改后全文").textContent).toBe(after);
  expect(
    within(item).getByText("变化较多，已按区块标示；两侧保留全文。"),
  ).toBeInTheDocument();
  expect(posts()).toHaveLength(0);
});

it("uses each B6 node's own baseline, lazily previews, and keeps the exact atomic body", async () => {
  const f = await setup("multi");
  const content = f.base.section.content as AuthoringDocument;
  const ids = content.content.map((node) => node.attrs.id);
  const before = content.content.map((node) =>
    node.type === "paragraph" || node.type === "heading"
      ? node.content
          .map((leaf) => (leaf.type === "text" ? leaf.text : ""))
          .join("")
      : "",
  );
  change("第一个人工修改 👩🏽‍💻");
  await userEvent.selectOptions(
    screen.getByLabelText("修改段落或标题"),
    ids[1],
  );
  change("第二个人工修改 <b>保持字面</b>");
  expect(preview().querySelectorAll(".text-change-preview")).toHaveLength(0);
  const first = await open(0),
    second = await open(1);
  expect(within(first).getByLabelText("修改前全文").textContent).toBe(
    before[0],
  );
  expect(within(second).getByLabelText("修改前全文").textContent).toBe(
    before[1],
  );
  expect(within(first).getByLabelText("拟修改后全文").textContent).toBe(
    "第一个人工修改 👩🏽‍💻",
  );
  expect(within(second).getByLabelText("拟修改后全文").textContent).toBe(
    "第二个人工修改 <b>保持字面</b>",
  );
  await confirm();
  await userEvent.click(within(first).getByRole("button", { name: "修改前" }));
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(posts()).toHaveLength(0);
  await userEvent.click(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  );
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(posts()[0][1]?.body).toEqual({
    protocol: "authoring-exact-multi-text-edit/1",
    base_draft_revision: f.base.status.draft_revision,
    section_revision_id: f.base.qualification.manifest.section_revision_id,
    edits: await Promise.all(
      ids.map(async (id, index) => ({
        node_id: id,
        before_node_digest: await jsonDigest(content.content[index]),
        replacement_text: index
          ? "第二个人工修改 <b>保持字面</b>"
          : "第一个人工修改 👩🏽‍💻",
      })),
    ),
    reason: native.request.reason,
  });
  expect(posts()[0][1]?.etag).toBe(native.request_etag);
});

it("previews all twenty B6 nodes without truncating or lifting the twenty-node limit", async () => {
  await setup("multi", { count: 21 });
  const select = screen.getByLabelText("修改段落或标题") as HTMLSelectElement;
  for (let index = 0; index < 21; index++) {
    fireEvent.change(select, {
      target: { value: select.options[index].value },
    });
    change(`节点 ${index + 1} 新文字 <tag>${"界".repeat(40)}尾`);
    if (index === 19) {
      expect(preview().querySelectorAll("details")).toHaveLength(20);
      await confirm();
      expect(
        screen.getByRole("button", { name: "确认保存人工修订" }),
      ).toBeEnabled();
      for (let item = 0; item < 20; item++) {
        const element = await open(item);
        expect(within(element).getByLabelText("修改前全文").textContent).toBe(
          `原节点 ${item + 1}`,
        );
        expect(within(element).getByLabelText("拟修改后全文").textContent).toBe(
          `节点 ${item + 1} 新文字 <tag>${"界".repeat(40)}尾`,
        );
      }
    }
  }
  await userEvent.click(screen.getByRole("checkbox"));
  expect(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  ).toBeDisabled();
  expect(preview().querySelectorAll("details")).toHaveLength(21);
  expect(posts()).toHaveLength(0);
});

it.each(["single", "multi", "marked"] as const)(
  "preview navigation never rewrites unknown ACK key/body/ETag or retries implicitly (%s)",
  async (kind) => {
    await setup(kind);
    change(native.request.replacement_text);
    await confirm();
    const item = await open();
    await userEvent.click(
      screen.getByRole("button", { name: "确认保存人工修订" }),
    );
    const retry = await screen.findByRole("button", {
      name: "查询并重试原文字修订",
    });
    await waitFor(() => expect(retry).toBeEnabled());
    const original = posts()[0],
      raw = sessionStorage.getItem(exactTextEditStorageKey(scope));
    expect(raw).toBeTruthy();
    expect(item.querySelector("summary")).toHaveTextContent("原请求节点");
    await userEvent.click(within(item).getByRole("button", { name: "修改前" }));
    await userEvent.click(
      within(item).getByRole("button", { name: "拟修改后" }),
    );
    await userEvent.click(item.querySelector("summary")!);
    await userEvent.click(item.querySelector("summary")!);
    expect(posts()).toHaveLength(1);
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBe(raw);
    expect(screen.getByLabelText("修改后的文字")).toBeDisabled();
    await userEvent.click(retry);
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()[1]).toEqual(original);
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBe(raw);
  },
);

it("preserves the 412 manuscript and re-compares only after explicit verified rebase", async () => {
  const f = await setup();
  f.state.conflict = true;
  change("并发冲突中保留的人工稿 👩🏽‍💻");
  await confirm();
  const item = await open();
  const originalBefore = within(item).getByLabelText("修改前全文").textContent;
  await userEvent.click(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  );
  await screen.findByText("Synthetic conflict");
  expect(item.querySelector("summary")).toHaveTextContent("被拒绝请求节点");
  expect(within(item).getByLabelText("修改前全文").textContent).toBe(
    originalBefore,
  );
  expect(screen.getByLabelText("修改后的文字")).toHaveValue(
    "并发冲突中保留的人工稿 👩🏽‍💻",
  );
  const m = native.ack.qualification.manifest;
  const content = structuredClone(f.base.section.content) as AuthoringDocument;
  const node = content.content[0];
  if (node.type !== "paragraph" && node.type !== "heading")
    throw new Error("Synthetic paragraph missing");
  node.content = [{ type: "text", text: native.request.replacement_text }];
  const fresh = await verifyTextEditBase(
    {
      status: {
        ...f.base.status,
        draft_revision: native.ack.draft_revision,
        snapshot_id: native.ack.snapshot_id,
        snapshot_digest: native.ack.snapshot_digest,
        exact_sections: [
          {
            ...f.base.status.exact_sections[0],
            section_revision_id: m.section_revision_id,
            section_revision: m.section_revision,
            section_digest: m.section_digest,
            qualification_id: m.id,
            qualification_digest: native.ack.qualification.digest,
          },
        ],
      },
      section: { ...f.base.section, revision: m.section_revision, content },
      qualification: native.ack.qualification,
    },
    scope,
  );
  f.update(fresh);
  const rebase = screen.getByRole("button", {
    name: "按当前原稿重新核对保留文字",
  });
  await waitFor(() => expect(rebase).toBeEnabled());
  expect(within(item).getByLabelText("修改前全文").textContent).toBe(
    originalBefore,
  );
  expect(posts()).toHaveLength(1);
  await userEvent.click(rebase);
  await waitFor(() =>
    expect(screen.getByLabelText("修改后的文字")).toBeEnabled(),
  );
  expect(within(details()).getByLabelText("修改前全文").textContent).toBe(
    native.request.replacement_text,
  );
  expect(within(details()).getByLabelText("拟修改后全文").textContent).toBe(
    "并发冲突中保留的人工稿 👩🏽‍💻",
  );
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  ).toBeDisabled();
  expect(posts()).toHaveLength(1);
});

it("shows a removed B6 node's complete unverified manuscript after 412 rebase, without inventing a before side", async () => {
  const f = await setup("multi");
  f.state.conflict = true;
  const originalContent = f.base.section.content as AuthoringDocument;
  const removedId = originalContent.content[1].attrs.id;
  const retained =
    "被移除节点的人工拟稿 👩🏽‍💻 <script>保持字面</script>".repeat(40) + "完整结尾";
  change("第一节点的人工改动");
  await userEvent.selectOptions(
    screen.getByLabelText("修改段落或标题"),
    removedId,
  );
  change(retained);
  await confirm();
  const oldSecond = await open(1);
  expect(within(oldSecond).getByLabelText("拟修改后全文").textContent).toBe(
    retained,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  );
  await screen.findByText("Synthetic conflict");

  // An explicit synthetic newer candidate omits the node. This is a read-side
  // UI fixture, not a claim that B6 text edits may delete nodes or structures.
  const fresh = structuredClone(f.base);
  const content = fresh.section.content as AuthoringDocument;
  content.content = content.content.filter(
    (node) => node.attrs.id !== removedId,
  );
  fresh.section.revision++;
  fresh.status.draft_revision++;
  fresh.status.snapshot_id = crypto.randomUUID();
  fresh.status.snapshot_digest = await jsonDigest({
    synthetic: "newer candidate",
  });
  const manifest = fresh.qualification.manifest;
  Object.assign(manifest, {
    id: crypto.randomUUID(),
    draft_revision: fresh.status.draft_revision,
    section_revision_id: crypto.randomUUID(),
    section_revision: fresh.section.revision,
    section_digest: await jsonDigest(content),
    parent_section_revision_id:
      f.base.qualification.manifest.section_revision_id,
    parent_section_revision: f.base.section.revision,
    parent_section_digest: f.base.qualification.manifest.section_digest,
  });
  fresh.qualification.digest = await jsonDigest(manifest);
  Object.assign(fresh.status.exact_sections[0], {
    section_revision_id: manifest.section_revision_id,
    section_revision: manifest.section_revision,
    section_digest: manifest.section_digest,
    qualification_id: manifest.id,
    qualification_digest: fresh.qualification.digest,
  });
  f.update(await verifyTextEditBase(fresh, scope));
  const rebase = screen.getByRole("button", {
    name: "按当前原稿重新核对保留文字",
  });
  await waitFor(() => expect(rebase).toBeEnabled());
  await userEvent.click(rebase);
  await waitFor(() =>
    expect(screen.getByLabelText("修改后的文字")).toBeEnabled(),
  );
  const missing = details(1);
  const manuscript =
    await within(missing).findByLabelText("未核对的保留拟稿全文");
  expect(manuscript.textContent).toBe(retained);
  expect(manuscript).toHaveAttribute("tabindex", "0");
  expect(
    within(missing).getByRole("heading", {
      name: "未核对的保留拟稿 · 尚未重新确认",
    }),
  ).toBeInTheDocument();
  expect(within(missing).getByText(/不能核对修改前文字/)).toBeInTheDocument();
  expect(within(missing).queryByLabelText("修改前全文")).toBeNull();
  expect(missing.querySelector("mark, script")).toBeNull();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await userEvent.click(screen.getByRole("checkbox"));
  expect(
    screen.getByRole("button", { name: "确认保存人工修订" }),
  ).toBeDisabled();
  expect(posts()).toHaveLength(1);
  expect(f.onSaved).not.toHaveBeenCalled();
});
