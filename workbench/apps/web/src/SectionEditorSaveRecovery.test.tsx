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
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
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

async function recoveryChoice(invalid = false) {
  const fixture = authoringLayoutFixture();
  const section = fixture.state.sections[0];
  const key = authoringStorageKey(
    layoutScope.memberId,
    layoutScope.bidId,
    `${layoutScope.draftId}:${section.id}`,
  );
  const local = structuredClone(section.content);
  local.attrs.title = "SYNTHETIC recovered latest choice";
  sessionStorage.setItem(
    key,
    JSON.stringify({
      sectionId: section.id,
      value: invalid
        ? {
            ...local,
            content: [
              { type: "unsupported", attrs: { id: "bad" }, content: [] },
            ],
          }
        : local,
      draftRevision: 1,
      sectionRevision: 1,
      schemaDigest: section.schema_digest,
      etag: '"draft:1"',
      pending: null,
    }),
  );
  // These tests control request order, not native Body-stream scheduling.
  // Keep both readHead bodies as microtask-only promises so act can drain
  // the complete stale chain before the final negative assertions.
  function choiceResponse(value: unknown, etag?: string) {
    const result = response(value, etag);
    result.json = async () => structuredClone(value);
    return result;
  }
  const reads: {
    finish: (value: Response) => void;
    fail: (error: Error) => void;
  }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (
        String(input) ===
          `/api/v1/bids/${layoutScope.bidId}/drafts/${layoutScope.draftId}` &&
        (!options?.method || options.method === "GET")
      ) {
        return new Promise<Response>((finish, fail) => {
          reads.push({ finish, fail });
        });
      }
      if (
        String(input) === `/api/v1/sections/${section.id}` &&
        (!options?.method || options.method === "GET")
      ) {
        return choiceResponse(structuredClone(fixture.state.sections[0]));
      }
      return fixture.fetcher(input, options);
    }),
  );
  const onSaved = vi.fn();
  const view = render(
    <SectionEditor
      {...layoutScope}
      draft={fixture.state.draft}
      etag={'"draft:1"'}
      capabilities={{ ...capabilities, schema_digest: section.schema_digest }}
      disabled={false}
      onSaved={onSaved}
    />,
  );
  await screen.findByRole("button", { name: "恢复本地内容并继续保存" });
  return {
    fixture,
    key,
    local,
    view,
    onSaved,
    reads: () => reads.length,
    finish: (index = 0) =>
      reads[index].finish(
        choiceResponse(structuredClone(fixture.state.draft), '"draft:1"'),
      ),
    fail: (error: Error, index = 0) => reads[index].fail(error),
  };
}

it.each(["success", "error"])(
  "does not let an older remote choice %s replace the newer local recovery",
  async (kind) => {
    const f = await recoveryChoice();
    fireEvent.click(
      screen.getByRole("button", { name: "忽略本地内容，使用服务器稿" }),
    );
    expect(f.reads()).toBe(1);
    fireEvent.click(
      screen.getByRole("button", { name: "恢复本地内容并继续保存" }),
    );
    expect(screen.getByRole("textbox", { name: "章节名称" })).toHaveValue(
      f.local.attrs.title,
    );
    await act(async () => {
      if (kind === "success") f.finish();
      else f.fail(new Error("old remote read failed"));
    });
    expect(screen.getByRole("textbox", { name: "章节名称" })).toHaveValue(
      f.local.attrs.title,
    );
    expect(screen.queryByText(/暂时无法连接服务/)).not.toBeInTheDocument();
    expect(sessionStorage.getItem(f.key)).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "立即保存" }));
    await screen.findByText(/已保存 · 章节修订 2/);
    expect(f.fixture.state.sections[0].content.attrs.title).toBe(
      f.local.attrs.title,
    );
    expect(sessionStorage.getItem(f.key)).toBeNull();
  },
);

it("does not discard the recovery copy when an ignored remote read finishes after unmount", async () => {
  const f = await recoveryChoice();
  fireEvent.click(
    screen.getByRole("button", { name: "忽略本地内容，使用服务器稿" }),
  );
  f.view.unmount();
  await act(async () => {
    f.finish();
  });
  expect(sessionStorage.getItem(f.key)).not.toBeNull();
  expect(f.onSaved).not.toHaveBeenCalled();
});

it.each(["old-first", "new-first"])(
  "only the latest remote choice can discard the local recovery copy: %s",
  async (order) => {
    const f = await recoveryChoice();
    const remote = screen.getByRole("button", {
      name: "忽略本地内容，使用服务器稿",
    });
    fireEvent.click(remote);
    fireEvent.click(remote);
    expect(f.reads()).toBe(2);
    if (order === "old-first") {
      await act(async () => {
        f.finish(0);
      });
      expect(sessionStorage.getItem(f.key)).not.toBeNull();
      expect(
        screen.getByRole("button", { name: "恢复本地内容并继续保存" }),
      ).toBeInTheDocument();
      expect(f.onSaved).not.toHaveBeenCalled();
      await act(async () => {
        f.finish(1);
      });
    } else {
      await act(async () => {
        f.finish(1);
      });
      // Establish the complete newer readHead choice, not just fetch delivery,
      // before releasing the stale read.
      await waitFor(() => {
        expect(f.onSaved).toHaveBeenCalledTimes(1);
        expect(sessionStorage.getItem(f.key)).toBeNull();
        expect(
          screen.queryByRole("button", { name: "恢复本地内容并继续保存" }),
        ).not.toBeInTheDocument();
      });
      await act(async () => {
        f.finish(0);
      });
    }
    await waitFor(() => {
      expect(f.onSaved).toHaveBeenCalledTimes(1);
      expect(sessionStorage.getItem(f.key)).toBeNull();
    });
    expect(
      screen.queryByRole("button", { name: "恢复本地内容并继续保存" }),
    ).not.toBeInTheDocument();
    expect(f.onSaved).toHaveBeenCalledTimes(1);
    expect(f.fixture.state.appliedSaves).toBe(0);
  },
);

it("a failed newer local recovery still revokes the earlier remote discard choice", async () => {
  const f = await recoveryChoice(true);
  fireEvent.click(
    screen.getByRole("button", { name: "忽略本地内容，使用服务器稿" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "恢复本地内容并继续保存" }),
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  await act(async () => {
    f.finish();
  });
  expect(sessionStorage.getItem(f.key)).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "恢复本地内容并继续保存" }),
  ).toBeInTheDocument();
  expect(f.onSaved).not.toHaveBeenCalled();
  expect(f.fixture.state.appliedSaves).toBe(0);
});
