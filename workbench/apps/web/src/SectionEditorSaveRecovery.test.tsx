import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SectionEditor } from "./SectionEditor";
import { authoringStorageKey } from "./editorStorage";
import type {
  AuthoringCapabilities,
  AuthoringRichCapabilities,
  SectionView,
} from "./contracts";

const capabilities: AuthoringCapabilities = {
  schema_digest: "a".repeat(64),
  schema: { version: 1, nodes: [], marks: [], metadata: [] },
  default_template_version_id: "template",
  formats: ["docx", "pdf"],
  supports_external_docx_import: false,
  supported_nodes: [],
  unsupported: [],
};
const rich: AuthoringRichCapabilities = {
  schema_digest: "b".repeat(64),
  schema: {},
  build_schema_digest: "c".repeat(64),
  image_upload_max_bytes: 8388608,
  renderer_configured: false,
  runtime_verified_by_this_read: false,
  table_pdf_geometry: "unverified",
  pagination_modes: [],
};
function response(value: unknown, etag?: string) {
  return new Response(JSON.stringify(value), {
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

async function setup(deferred = false) {
  let section = {
    id: "section",
    draft_id: "draft",
    revision: 1,
    schema_digest: capabilities.schema_digest,
    writing_plan_id: null,
    content: {
      type: "doc",
      attrs: {
        title: "SYNTHETIC original",
        ordinal: 0,
        rule_ids: [],
        source_refs: [],
      },
      content: [
        {
          type: "paragraph",
          attrs: { id: "00000000-0000-4000-8000-000000000001" },
          content: [{ type: "text", text: "Unchanged body" }],
        },
      ],
    },
  } as SectionView;
  const writes: Record<string, unknown>[] = [],
    releases: (() => void)[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/sections/section") return response(section);
      if (
        url === "/api/v1/bids/bid/drafts/draft" &&
        options?.method === "PATCH"
      ) {
        const body = JSON.parse(options.body as string);
        writes.push(body);
        const revision = writes.length + 1;
        const finish = () => {
          section = { ...section, revision, content: body.changes[0].content };
          return response(
            {
              draft_id: "draft",
              draft_revision: revision,
              snapshot_id: `snapshot-${revision}`,
              snapshot_digest: "d".repeat(64),
            },
            `"draft-${revision}"`,
          );
        };
        return deferred
          ? new Promise<Response>((resolve) =>
              releases.push(() => resolve(finish())),
            )
          : finish();
      }
      throw new Error(`Unexpected ${url}`);
    }),
  );
  const props = {
    bidId: "bid",
    memberId: "member",
    draft: {
      id: "draft",
      bid_id: "bid",
      revision: 1,
      snapshot_id: "snapshot-1",
      sections: [],
    },
    etag: '"draft-1"',
    sectionId: "section",
    capabilities,
    disabled: false,
    onSaved: vi.fn(),
  };
  const view = render(<SectionEditor {...props} />);
  const title = await screen.findByRole("textbox", { name: "章节名称" });
  // Real capability requests can finish after the ordinary section editor mounts.
  view.rerender(<SectionEditor {...props} richCapabilities={rich} />);
  return {
    title,
    writes,
    releases,
    key: authoringStorageKey("member", "bid", "draft:section"),
  };
}

it("clears an acknowledged identical local document after rich capabilities arrive later", async () => {
  const f = await setup();
  fireEvent.change(f.title, {
    target: { value: "SYNTHETIC acknowledged title" },
  });
  await userEvent.click(screen.getByRole("button", { name: "立即保存" }));
  await screen.findByText(/已保存 · 章节修订 2/);
  expect(f.writes).toHaveLength(1);
  expect(sessionStorage.getItem(f.key)).toBeNull();
});

it("retains newer local document attributes until their own ACK rather than comparing body text", async () => {
  const f = await setup(true);
  fireEvent.change(f.title, { target: { value: "SYNTHETIC first title" } });
  await userEvent.click(screen.getByRole("button", { name: "立即保存" }));
  await waitFor(() => expect(f.writes).toHaveLength(1));
  // Body text is deliberately identical; only a full document comparison detects this change.
  fireEvent.change(f.title, {
    target: { value: "SYNTHETIC newer local title" },
  });
  await act(async () => f.releases[0]());
  await waitFor(() => expect(f.writes).toHaveLength(2));
  expect(JSON.parse(sessionStorage.getItem(f.key)!).value.attrs.title).toBe(
    "SYNTHETIC newer local title",
  );
  await act(async () => f.releases[1]());
  await screen.findByText(/已保存 · 章节修订 3/);
  expect(sessionStorage.getItem(f.key)).toBeNull();
});
