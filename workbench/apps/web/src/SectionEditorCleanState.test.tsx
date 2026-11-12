import { createRef, useEffect } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SectionEditor, type SectionEditorHandle } from "./SectionEditor";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
const extension = vi.hoisted(() => ({ busy: false, reported: vi.fn() }));
vi.mock("./AuthoringPatchPreview", () => ({
  AuthoringPatchPreview: ({
    setBusy,
  }: {
    setBusy: (busy: boolean) => void;
  }) => {
    useEffect(() => {
      setBusy(extension.busy);
      extension.reported(extension.busy);
      return () => setBusy(false);
    }, [setBusy]);
    return null;
  },
}));
vi.mock("./AuthoringHistory", () => ({ AuthoringHistory: () => null }));
beforeEach(() => {
  sessionStorage.clear();
  extension.busy = false;
  extension.reported.mockClear();
});
function setup() {
  const fixture = authoringLayoutFixture(),
    ref = createRef<SectionEditorHandle>();
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  const view = render(
    <SectionEditor
      ref={ref}
      bidId={layoutScope.bidId}
      memberId={layoutScope.memberId}
      draft={fixture.state.draft}
      etag={'"draft:1"'}
      sectionId={fixture.state.sections[0].id}
      capabilities={fixture.capabilities}
      disabled={false}
      onSaved={vi.fn()}
    />,
  );
  return { fixture, ref, ...view };
}
it("does not certify a clean saved editor or prepare a structure while chapter work is in flight", async () => {
  extension.busy = true;
  const f = setup();
  await screen.findByRole("textbox", { name: "章节正文" });
  await waitFor(() => expect(extension.reported).toHaveBeenCalledWith(true));
  expect(f.ref.current?.isSavedAndClean?.()).toBe(false);
  await act(async () => expect(await f.ref.current!.flush(true)).toBe(false));
  await screen.findByText(
    "当前章节操作尚未完成，请等待后再变更目录或生成版本。",
  );
  expect(f.fixture.state.writes).toEqual([]);
});
it("only reports clean after the actual queued save ACK and never after unmount", async () => {
  const f = setup();
  await screen.findByRole("textbox", { name: "章节正文" });
  await waitFor(() => expect(f.ref.current?.isSavedAndClean?.()).toBe(true));
  fireEvent.change(screen.getByLabelText("章节名称"), {
    target: { value: "等待确认的合成改稿" },
  });
  expect(f.ref.current?.isSavedAndClean?.()).toBe(false);
  await act(async () => expect(await f.ref.current!.flush(true)).toBe(true));
  await waitFor(() => expect(f.ref.current?.isSavedAndClean?.()).toBe(true));
  expect(f.fixture.state.appliedSaves).toBe(1);
  const old = f.ref.current!;
  f.unmount();
  expect(old.isSavedAndClean?.()).toBe(false);
});
