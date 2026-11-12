import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringPanel } from "./AuthoringPanel";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
import type { SectionView, DraftView } from "./contracts";
import { setAuth } from "./api";
afterEach(() => vi.restoreAllMocks());

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAuth({
    member: {
      id: native.member_id,
      display_name: "合成目录编制验收",
      active: true,
    },
    csrf_token: "synthetic-not-a-credential",
    expires_at: "2099-01-01T00:00:00Z",
  });
  vi.spyOn(window, "scrollBy").mockImplementation(() => {});
  const createRange = document.createRange.bind(document);
  vi.spyOn(document, "createRange").mockImplementation(() => {
    const range = createRange();
    range.getClientRects = () => [] as unknown as DOMRectList;
    range.getBoundingClientRect = () => new DOMRect(0, 0, 1, 1);
    return range;
  });
  const previous = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("authoring-columns")
        ? {
            width: 1100,
            height: 800,
            left: 0,
            right: 1100,
            top: 200,
            bottom: 1000,
            x: 0,
            y: 200,
            toJSON: () => ({}),
          }
        : previous.call(this);
    },
  );
});
function response(data: unknown, etag: string, status = 200) {
  const result = new Response(JSON.stringify(data), {
    status,
    headers: { ETag: etag },
  });
  result.json = async () => structuredClone(data);
  return result;
}
import native from "./test-fixtures/authoring-exact-text-edit-http.json";
import { jsonDigest } from "./editorSchema";
type Mode =
  | "success"
  | "head-failure"
  | "qualification-failure"
  | "unknown"
  | "invalid"
  | "conflict";
async function setup(mode: Mode = "success") {
  const ordinary = authoringLayoutFixture(),
    scope = {
      memberId: native.member_id,
      bidId: native.bid_id,
      draftId: native.parent_status.draft_id,
    };
  const status = structuredClone(native.parent_status),
    section = structuredClone(native.parent_section) as SectionView;
  const draft: DraftView = {
    id: scope.draftId,
    bid_id: scope.bidId,
    revision: 2,
    snapshot_id: status.snapshot_id,
    sections: [
      {
        id: section.id,
        title: String(section.content.attrs.title),
        ordinal: 0,
        revision: 2,
        rule_ids: [],
        save_state: "saved",
      },
    ],
  };
  Object.assign(ordinary.state.draft, draft);
  ordinary.state.sections.splice(0, ordinary.state.sections.length, section);
  let applied = false,
    failHead = false,
    failedHeads = 0,
    failedQualifications = 0;
  const snapshots = new Map<string, unknown>();
  async function capture() {
    const extension = {
      protocol: "authoring-exact-snapshot/1",
      sections: structuredClone(status.exact_sections),
    };
    snapshots.set(status.snapshot_id, {
      snapshot_id: status.snapshot_id,
      snapshot_digest: status.snapshot_digest,
      title: "SYNTHETIC exact text",
      sections: [structuredClone(section.content)],
      authoring_exact_sections: {
        ...extension,
        digest: await jsonDigest(extension),
      },
    });
  }
  await capture();
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), window.location.href).pathname,
        tag = `"draft:${scope.draftId}:${ordinary.state.draft.revision}"`;
      if (
        (init?.method ?? "GET") === "GET" &&
        path.endsWith(`/drafts/${scope.draftId}`) &&
        failHead
      ) {
        failHead = false;
        failedHeads++;
        throw new TypeError("SYNTHETIC head read failed");
      }
      if (
        applied &&
        mode === "qualification-failure" &&
        path.endsWith(`/authoring/drafts/${scope.draftId}/exact-qualification`)
      ) {
        failedQualifications++;
        throw new TypeError("SYNTHETIC qualification read failed");
      }
      if (path.endsWith("/authoring/exact-text-edit-capabilities"))
        return response(native.capabilities, tag);
      if (
        path.endsWith(`/authoring/drafts/${scope.draftId}/exact-qualification`)
      )
        return response(status, tag);
      if (path.includes("/draft-snapshots/"))
        return response(snapshots.get(path.split("/").at(-1)!), tag);
      if (path.endsWith("/exact-qualification"))
        return response(
          path.includes(native.ack.section_revision_id)
            ? native.ack.qualification
            : native.parent_qualification,
          tag,
        );
      if (init?.method === "POST") {
        writes.push(init);
        expect(JSON.parse(String(init.body))).toEqual(native.request);
        expect(new Headers(init.headers).get("If-Match")).toBe(
          native.request_etag,
        );
        if (applied) return response(native.ack, native.ack_etag);
        if (mode === "conflict")
          return response(
            {
              code: "DRAFT_REVISION_CONFLICT",
              message: "SYNTHETIC exact text conflict",
              retryable: false,
            },
            tag,
            412,
          );
        const editedNode = section.content.content[0];
        if (editedNode.type !== "paragraph")
          throw new Error(
            "Synthetic native text fixture must target a paragraph",
          );
        expect(editedNode.attrs.id).toBe(native.request.node_id);
        editedNode.content = [
          { type: "text", text: native.request.replacement_text },
        ];
        section.revision = 3;
        ordinary.state.draft.revision = 3;
        ordinary.state.draft.snapshot_id = native.ack.snapshot_id;
        ordinary.state.draft.sections[0].revision = 3;
        Object.assign(status, {
          draft_revision: 3,
          snapshot_id: native.ack.snapshot_id,
          snapshot_digest: native.ack.snapshot_digest,
        });
        Object.assign(status.exact_sections[0], {
          section_revision: 3,
          section_revision_id: native.ack.section_revision_id,
          section_digest: native.ack.section_digest,
          qualification_id: native.ack.qualification.manifest.id,
          qualification_digest: native.ack.qualification.digest,
        });
        await capture();
        applied = true;
        failHead = mode === "head-failure";
        if (mode === "unknown") throw new TypeError("SYNTHETIC lost exact ACK");
        if (mode === "invalid")
          return response(
            { ...native.ack, section_digest: "0".repeat(64) },
            native.ack_etag,
          );
        return response(native.ack, native.ack_etag);
      }
      expect(init?.method ?? "GET").toBe("GET");
      const translated = path
        .replace(scope.bidId, layoutScope.bidId)
        .replace(scope.draftId, layoutScope.draftId);
      const r = await ordinary.fetcher(translated, init),
        value = await r.json();
      if (path.endsWith("/authoring/capabilities"))
        value.schema_digest = section.schema_digest;
      return response(value, tag, r.status);
    }),
  );
  render(
    <AuthoringPanel
      {...scope}
      projectTitle="SYNTHETIC fixed-source text editing"
      onOpenDraft={vi.fn()}
    />,
  );
  const begin = await screen.findByRole("button", {
    name: "修改本章固定来源文字",
  });
  await waitFor(() => expect(begin).toBeEnabled());
  return {
    ordinary,
    section,
    status,
    writes,
    begin,
    counts: () => ({ failedHeads, failedQualifications }),
  };
}
async function submit(begin: HTMLElement) {
  await userEvent.click(begin);
  fireEvent.change(screen.getByLabelText("修改后的文字"), {
    target: { value: native.request.replacement_text },
  });
  fireEvent.change(screen.getByLabelText("修订说明"), {
    target: { value: native.request.reason },
  });
  const edit = within(screen.getByRole("region", { name: "固定来源文字修订" }));
  await userEvent.click(edit.getByRole("checkbox"));
  await userEvent.click(edit.getByRole("button", { name: "确认保存人工修订" }));
}
it.each([
  "success",
  "head-failure",
  "unknown",
  "invalid",
  "conflict",
  "qualification-failure",
] as const)(
  "refreshes readonly exact text only from a verified %s outcome",
  async (mode) => {
    const f = await setup(mode),
      body = screen.getByLabelText("章节正文"),
      original = body.textContent;
    expect(body).toHaveAttribute("contenteditable", "false");
    await submit(f.begin);
    if (mode === "unknown" || mode === "invalid") {
      const retry = await screen.findByRole("button", {
        name: "查询并重试原文字修订",
      });
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      await waitFor(() => expect(f.writes).toHaveLength(1));
      await waitFor(() => expect(retry).toBeEnabled());
      await userEvent.click(retry);
      await waitFor(() => expect(f.writes).toHaveLength(2));
      expect(f.writes[1].body).toBe(f.writes[0].body);
      for (const h of ["If-Match", "Idempotency-Key"])
        expect(new Headers(f.writes[1].headers).get(h)).toBe(
          new Headers(f.writes[0].headers).get(h),
        );
    } else if (mode === "head-failure") {
      const retry = await screen.findByRole("button", {
        name: "核对并重新读取已保存正文",
      });
      expect(f.counts().failedHeads).toBe(1);
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(body).toHaveAttribute("contenteditable", "false");
      await userEvent.click(retry);
      expect(f.writes).toHaveLength(1);
    } else if (mode === "conflict") {
      await screen.findByText("SYNTHETIC exact text conflict");
      expect(screen.getByLabelText("章节正文")).toBe(body);
      expect(body.textContent).toBe(original);
      expect(f.ordinary.state.draft.revision).toBe(2);
      expect(f.writes).toHaveLength(1);
      expect(screen.getByLabelText("修改后的文字")).toHaveValue(
        native.request.replacement_text,
      );
      return;
    } else if (mode === "qualification-failure") {
      await waitFor(() =>
        expect(f.counts().failedQualifications).toBeGreaterThan(0),
      );
      await waitFor(() =>
        expect(screen.getAllByRole("alert").length).toBeGreaterThan(0),
      );
      expect(screen.getByLabelText("章节正文")).toHaveAttribute(
        "contenteditable",
        "false",
      );
      expect(
        screen.getByRole("button", { name: "保存确认后生成文件" }),
      ).toBeDisabled();
      return;
    }
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "修改本章固定来源文字" }),
      ).toBeEnabled(),
    );
    expect(f.ordinary.state.draft.revision).toBe(3);
    expect(f.section.revision).toBe(3);
    expect(screen.getByLabelText("章节正文")).toHaveTextContent(
      native.request.replacement_text,
    );
    expect(screen.getByLabelText("章节正文")).not.toHaveTextContent(
      native.parent_section.content.content[0].content[0].text,
    );
    expect(screen.getByLabelText("章节正文")).toHaveAttribute(
      "contenteditable",
      "false",
    );
    expect(
      within(screen.getByRole("region", { name: "正文编写" })).getByLabelText(
        "章节名称",
      ),
    ).toBeDisabled();
    expect(f.section.content.attrs.source_refs).toEqual(
      native.parent_section.content.attrs.source_refs,
    );
    expect(f.section.content.attrs.rule_ids).toEqual(
      native.parent_section.content.attrs.rule_ids,
    );
  },
);
