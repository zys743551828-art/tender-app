import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { SectionEditor, type SectionEditorHandle } from "./SectionEditor";
import { authoringStorageKey } from "./editorStorage";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
function setup({ pending = true, rejected = false } = {}) {
  const fixture = authoringLayoutFixture(),
    section = fixture.state.sections[0],
    key = authoringStorageKey(
      layoutScope.memberId,
      layoutScope.bidId,
      `${layoutScope.draftId}:${section.id}`,
    );
  const content = structuredClone(section.content);
  content.attrs.title = "保留的本地章节名称";
  const original = {
    body: {
      base_draft_revision: 1,
      changes: [
        {
          section_id: section.id,
          base_section_revision: 1,
          schema_digest: section.schema_digest,
          content,
        },
      ],
    },
    etag: '"draft:1"',
    key: "20000000-0000-4000-8000-000000000099",
  };
  sessionStorage.setItem(
    key,
    JSON.stringify({
      sectionId: section.id,
      value: content,
      draftRevision: 1,
      sectionRevision: 1,
      schemaDigest: section.schema_digest,
      etag: original.etag,
      pending: pending ? original : null,
    }),
  );
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (options?.method === "PATCH") {
        writes.push(options);
        if (rejected)
          return new Response(
            JSON.stringify({
              code: "EXACT_REVISION_EDIT_UNAVAILABLE",
              message: "固定来源稿件不可普通编辑",
              details: null,
              request_id: "synthetic-rejection",
              retryable: false,
            }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          );
      }
      return fixture.fetcher(input, options);
    }),
  );
  const ref = createRef<SectionEditorHandle>();
  render(
    <SectionEditor
      {...layoutScope}
      ref={ref}
      draft={fixture.state.draft}
      etag={original.etag}
      capabilities={{
        schema_digest: section.schema_digest,
        schema: { version: 1, nodes: [], marks: [], metadata: [] },
        default_template_version_id: "template",
        formats: ["docx"],
        supports_external_docx_import: false,
        supported_nodes: [],
        unsupported: [],
      }}
      disabled={false}
      readOnly
      onSaved={vi.fn()}
    />,
  );
  return { fixture, original, key, writes, ref };
}
it("allows only an original pending save to be replayed in an exact read-only draft, retaining its body, ETag and key", async () => {
  const f = setup();
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原章节保存请求" }),
  );
  await screen.findByText(/已保存 · 章节修订 2/);
  expect(f.writes).toHaveLength(1);
  expect(JSON.parse(f.writes[0].body as string)).toEqual(f.original.body);
  expect(new Headers(f.writes[0].headers).get("If-Match")).toBe(
    f.original.etag,
  );
  expect(new Headers(f.writes[0].headers).get("Idempotency-Key")).toBe(
    f.original.key,
  );
  expect(screen.getByLabelText("章节名称")).toBeDisabled();
  expect(sessionStorage.getItem(f.key)).toBeNull();
  await act(async () => {
    expect(await f.ref.current!.flush()).toBe(true);
  });
  expect(f.writes).toHaveLength(1);
});
it("retains unsent local content without turning its restoration into a new PATCH on a read-only draft", async () => {
  const f = setup({ pending: false });
  const restore = await screen.findByRole("button", {
    name: "恢复本地内容并继续保存",
  });
  expect(restore).toBeDisabled();
  expect(sessionStorage.getItem(f.key)).toContain("保留的本地章节名称");
  await act(async () => {
    expect(await f.ref.current!.flush(true)).toBe(false);
  });
  expect(f.writes).toHaveLength(0);
});
it("does not create a replacement PATCH after the original pending save is definitively rejected", async () => {
  const f = setup({ rejected: true });
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原章节保存请求" }),
  );
  await screen.findByText(/固定来源稿件不可普通编辑/);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "重试保存" })).toBeDisabled(),
  );
  expect(JSON.parse(sessionStorage.getItem(f.key)!).pending).toBeNull();
  await act(async () => {
    expect(await f.ref.current!.flush()).toBe(false);
  });
  expect(f.writes).toHaveLength(1);
  expect(sessionStorage.getItem(f.key)).toContain("保留的本地章节名称");
});
