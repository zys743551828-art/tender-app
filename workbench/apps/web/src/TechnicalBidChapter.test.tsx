import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { TechnicalBidChapter } from "./TechnicalBidChapter";
import type { DraftView } from "./contracts";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import {
  matchesFixedAuthoringChapter,
  validateAuthoringInput,
} from "./packageAuthoringInputProtocol";

const f = captureFixture();
const ref = f.request.target_section;
const draft: DraftView = {
  id: ref.draft_id,
  bid_id: f.bidId,
  revision: ref.base_draft_revision,
  snapshot_id: ref.snapshot_id,
  sections: [
    {
      id: ref.section_id,
      title: "合成施工进度章节",
      revision: ref.base_section_revision,
      ordinal: 0,
      rule_ids: [],
      save_state: "saved",
    },
  ],
};
const props = {
  bidId: f.bidId,
  memberId: f.memberId,
  draft,
  sectionId: ref.section_id,
  disabled: false,
  onPreparing: vi.fn(),
};

function protectTransport() {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    expect(path).toBe("/api/v1/bids/" + f.bidId);
    expect(init?.method).toBe("GET");
    return new Response(JSON.stringify({ id: f.bidId }), {
      status: 200,
      headers: { ETag: '"bid:' + f.bidId + ":" + "a".repeat(64) + '"' },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

it("prepares only the current saved snapshot, without sending any model or template request", async () => {
  const transport = protectTransport();
  const prepare = vi
    .fn()
    .mockResolvedValue({ data: draft, etag: '"draft-head"' });
  const user = userEvent.setup();
  const result = render(<TechnicalBidChapter {...props} prepare={prepare} />);
  expect(transport).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  expect(
    await screen.findByRole("region", { name: "固定整包编写模板编辑" }),
  ).toBeInTheDocument();
  expect(prepare).toHaveBeenCalledOnce();
  expect(transport).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("button", { name: "保存固定整包编写模板，不运行" }),
  ).toBeDisabled();

  result.rerender(
    <TechnicalBidChapter
      {...props}
      draft={{ ...draft, revision: draft.revision + 1 }}
      prepare={prepare}
    />,
  );
  expect(await screen.findByText(/草稿或章节已变化/)).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "固定整包编写要求" }),
  ).toBeDisabled();
});

it("preserves the editor boundary when no trusted save receipt is returned", async () => {
  const transport = protectTransport();
  const prepare = vi.fn().mockResolvedValue(null);
  const user = userEvent.setup();
  render(<TechnicalBidChapter {...props} prepare={prepare} />);
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  await waitFor(() =>
    expect(screen.getByText(/未核对本章已保存版本/)).toBeInTheDocument(),
  );
  expect(transport).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("region", { name: "固定整包编写模板编辑" }),
  ).not.toBeInTheDocument();
});

it("rejects a stored input from another revision, chapter, or snapshot even in same project", async () => {
  const verified = await validateAuthoringInput(f.saved, f.bidId);
  expect(matchesFixedAuthoringChapter(verified, ref)).toBe(true);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      section_id: crypto.randomUUID(),
    }),
  ).toBe(false);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      snapshot_id: crypto.randomUUID(),
    }),
  ).toBe(false);
  expect(
    matchesFixedAuthoringChapter(verified, {
      ...ref,
      base_draft_revision: ref.base_draft_revision + 1,
    }),
  ).toBe(false);
});

it("does not start any reads from a malformed saved chapter or snapshot identity", async () => {
  const transport = protectTransport();
  const user = userEvent.setup();
  render(
    <TechnicalBidChapter
      {...props}
      prepare={vi.fn().mockResolvedValue({
        data: { ...draft, snapshot_id: "../../other-resource" },
        etag: '"synthetic-draft"',
      })}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "准备生成本章技术标候选" }),
  );
  expect(await screen.findByText(/未核对本章已保存版本/)).toBeInTheDocument();
  expect(transport).not.toHaveBeenCalled();
});
