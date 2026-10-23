import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import native from "./test-fixtures/authoring-exact-build-http.json";
import type {
  Accepted,
  AuthoringCapabilities,
  AuthoringOutputAdopted,
  AuthoringRichCapabilities,
  DraftView,
} from "./contracts";
import {
  matchBuildAck,
  validBuildRequest,
  validBuildView,
} from "./authoringBuildRecovery";
import {
  validateAdoption,
  validAdoptionBody,
} from "./authoringAdoptionProtocol";
import {
  readExactCapabilities,
  readExactDraftStatus,
} from "./authoringExactProtocol";
import { AuthoringBuilds } from "./AuthoringBuilds";

const reads = native.reads as Record<
  string,
  { status: number; etag: string | null; body: unknown }
>;
const base = `/api/v1/bids/${native.bid_id}`,
  draftPath = `${base}/drafts/${native.saved.draft_id}`;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
it("accepts unchanged native exact build, independent Word/PDF and explicit package-adoption identities", async () => {
  const build: unknown = native.build;
  if (
    !validBuildView(build, native.bid_id, native.saved.draft_id) ||
    !validBuildRequest(native.build_request, native.saved.draft_id) ||
    !validAdoptionBody(native.adoption_request)
  )
    throw new Error("native fixture contract failed");
  expect(
    readExactCapabilities(
      reads["/api/v1/authoring/exact-revision-capabilities"].body,
    ).build_available,
  ).toBe(true);
  const status = readExactDraftStatus(
    reads[
      `${base}/authoring/drafts/${native.saved.draft_id}/exact-qualification`
    ].body,
    native.bid_id,
    native.saved.draft_id,
  );
  expect(status.build_available).toBe(true);
  expect(status.snapshot_id).toBe(native.saved.snapshot_id);
  expect(
    matchBuildAck(
      native.build_ack as Accepted,
      build,
      native.bid_id,
      native.saved.draft_id,
      {
        key: "synthetic-recovery-key",
        body: native.build_request,
        snapshotId: native.saved.snapshot_id,
      },
    ),
  ).toBe(true);
  expect(build.outputs.map((output) => [output.format, output.state])).toEqual([
    ["docx", "succeeded"],
    ["pdf", "failed"],
  ]);
  const pending = {
    version: 1 as const,
    scope: {
      bidId: native.bid_id,
      memberId: native.member_id,
      buildId: build.id,
      documentId: native.adoption_request.member.document_version_id,
    },
    key: "synthetic-recovery-key",
    base: null,
    body: native.adoption_request,
  };
  expect(
    await validateAdoption(
      native.adoption_ack as AuthoringOutputAdopted,
      pending,
      build,
      native.adoption_etag,
    ),
  ).toEqual(native.adoption_ack);
  expect(native.adoption_ack.current_body_changed).toBe(false);
  expect(native.adoption_ack.automatically_started_review).toBe(false);
});

it("sends the native plain build request for an exact snapshot without frozen structure instead of inventing dual-template or pagination inputs", async () => {
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      let value: unknown,
        etag: string | null = null;
      if (options?.method === "POST") {
        writes.push(options);
        value = native.build_ack;
      } else if (url.startsWith(base + "/builds?"))
        value = { items: [], next_cursor: null, has_more: false };
      else if (url === `/api/v1/builds/${native.build.id}`)
        value = native.build;
      else if (url === `/api/v1/operations/${native.build.operation_id}`)
        value = { ...native.build_ack.operation, state: "succeeded" };
      else if (reads[url]) {
        value = reads[url].body;
        etag = reads[url].etag;
      } else throw new Error(`unexpected native UI read ${url}`);
      return new Response(JSON.stringify(value), {
        headers: {
          "Content-Type": "application/json",
          ...(etag ? { ETag: etag } : {}),
        },
      });
    }),
  );
  render(
    <AuthoringBuilds
      bidId={native.bid_id}
      memberId={native.member_id}
      draftId={native.saved.draft_id}
      capabilities={
        reads["/api/v1/authoring/capabilities"].body as AuthoringCapabilities
      }
      richCapabilities={
        reads["/api/v1/authoring/rich-capabilities"]
          .body as AuthoringRichCapabilities
      }
      fixedRevision={native.saved}
      disabled={false}
      prepare={async () => ({
        data: reads[draftPath].body as DraftView,
        etag: reads[draftPath].etag,
      })}
      setBusy={vi.fn()}
    />,
  );
  await screen.findByText("内置正文版式");
  expect(screen.queryByLabelText("章页排版")).toBeNull();
  const submit = screen.getByRole("button", { name: "保存确认后生成文件" });
  await waitFor(() => expect(submit).toBeEnabled());
  await userEvent.click(submit);
  await screen.findByText("此格式生成成功");
  await screen.findByText("此格式生成失败");
  expect(writes).toHaveLength(1);
  expect(JSON.parse(writes[0].body as string)).toEqual(native.build_request);
});
