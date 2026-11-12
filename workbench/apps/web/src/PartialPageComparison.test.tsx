import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { expect, it, vi } from "vitest";
import { PartialPageComparison } from "./PartialPageComparison";
import type { Selection } from "./PartialPageSelection";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: mocks.api,
}));
vi.mock("./PartialScopeObservations", () => ({
  PartialScopeObservations: () => null,
}));
const selection = (
  id: string,
  purpose: "technical_reference" | "requirement_reference",
) =>
  ({
    id,
    current_material: true,
    source_effectivity: "not_verified",
    model_execution_allowed: false,
    formal_qualification: false,
    proof: {
      digest: id + "-digest",
      manifest: {
        purpose,
        coverage: "partial",
        source: {
          document_version_id: id + "-doc",
          parse_run_id: id + "-parse",
          file_digest: "a".repeat(64),
        },
        selection: { first_page: 2, last_page: 2 },
        selected_pages: [
          { physical_page: 2, quality: "partial", gaps: ["OCR"] },
        ],
        selected_blocks: [{ id: id + "-block", physical_page: 2 }],
        omitted_ranges: [{ first_page: 1, last_page: 1 }],
      },
    },
  }) as Selection;
const requirement = selection("requirement", "requirement_reference");
const technical = selection("technical", "technical_reference");
const side = (item: Selection) => ({
  selection: item,
  evidence: {
    selection_id: item.id,
    proof_digest: item.proof.digest,
    items: [
      { id: item.id + "-block", physical_page: 2, quote: item.id + "-text" },
    ],
    model_execution_allowed: false,
    formal_qualification: false,
  },
});

it("compares only confirmed scopes and keeps whole-document coverage unknown", async () => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValueOnce({
    data: {
      has_more: false,
      items: [
        {
          id: "technical",
          document_version_id: "technical-doc",
          filename: "技术材料.pdf",
          purpose: "technical_reference",
          first_page: 2,
          last_page: 2,
        },
        {
          id: "wrong",
          document_version_id: "wrong-doc",
          filename: "不适用.pdf",
          purpose: "requirement_reference",
          first_page: 1,
          last_page: 1,
        },
      ],
    },
  });
  mocks.api.mockResolvedValueOnce({
    data: {
      requirement: side(requirement),
      technical: side(technical),
      coverage: "partial",
      overall_result: "unknown",
      model_execution_allowed: false,
      formal_qualification: false,
    },
  });
  render(
    <PartialPageComparison
      path="/bids/bid/partial-page-selections"
      selection={requirement}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
  );
  const select = await screen.findByLabelText("另一范围");
  expect(within(select).getByText(/技术材料.pdf/)).toBeInTheDocument();
  expect(within(select).queryByText(/wrong-doc/)).not.toBeInTheDocument();
  await user.selectOptions(select, "technical");
  await user.click(screen.getByRole("button", { name: "打开范围对照" }));
  const comparison = await screen.findByRole("region", {
    name: "人工范围对照",
  });
  expect(
    within(comparison).getByText("人工范围对照 · 整体覆盖未知"),
  ).toBeVisible();
  await user.click(within(comparison).getByText(/要求参考 · 第/));
  expect(within(comparison).getByText(/requirement-text/)).toBeVisible();
  expect(within(comparison).queryByText(/范围外/)).not.toBeInTheDocument();
});

it("rejects a response that claims formal qualification", async () => {
  mocks.api.mockReset();
  mocks.api.mockResolvedValueOnce({
    data: {
      has_more: false,
      items: [
        {
          id: "technical",
          document_version_id: "technical-doc",
          filename: "技术材料.pdf",
          purpose: "technical_reference",
          first_page: 2,
          last_page: 2,
        },
      ],
    },
  });
  mocks.api.mockResolvedValueOnce({
    data: {
      requirement: side(requirement),
      technical: side(technical),
      coverage: "partial",
      overall_result: "unknown",
      model_execution_allowed: false,
      formal_qualification: true,
    },
  });
  render(
    <PartialPageComparison
      path="/bids/bid/partial-page-selections"
      selection={requirement}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
  );
  await user.selectOptions(
    await screen.findByLabelText("另一范围"),
    "technical",
  );
  await user.click(screen.getByRole("button", { name: "打开范围对照" }));
  expect(
    await screen.findByText("对照范围或依据已变化，请重新核对。"),
  ).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "人工范围对照" }),
  ).not.toBeInTheDocument();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const comparisonData = (tech: Selection) => ({
  data: {
    requirement: side(requirement),
    technical: side(tech),
    coverage: "partial",
    overall_result: "unknown",
    model_execution_allowed: false,
    formal_qualification: false,
  },
});
const candidate = (id: string) => ({
  id,
  document_version_id: id + "-doc",
  filename: id + ".pdf",
  purpose: "technical_reference",
  first_page: 2,
  last_page: 2,
});

it.each(["result", "error"])(
  "ignores late comparison %s after the reviewer selects another scope",
  async (kind) => {
    const pending = deferred<ReturnType<typeof comparisonData>>();
    mocks.api
      .mockReset()
      .mockResolvedValueOnce({
        data: {
          items: [candidate("technical"), candidate("new-technical")],
          has_more: false,
        },
      })
      .mockReturnValueOnce(pending.promise);
    render(
      <PartialPageComparison
        path="/bids/bid/partial-page-selections"
        selection={requirement}
      />,
    );
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
    );
    const select = await screen.findByLabelText("另一范围");
    await user.selectOptions(select, "technical");
    await user.click(screen.getByRole("button", { name: "打开范围对照" }));
    await user.selectOptions(select, "new-technical");
    await act(async () => {
      if (kind === "result") pending.resolve(comparisonData(technical));
      else pending.reject(new Error("old comparison failed"));
    });
    expect(
      screen.queryByRole("region", { name: "人工范围对照" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("old comparison failed")).not.toBeInTheDocument();
    mocks.api.mockResolvedValueOnce(
      comparisonData(selection("new-technical", "technical_reference")),
    );
    await user.click(screen.getByRole("button", { name: "打开范围对照" }));
    const current = await screen.findByRole("region", { name: "人工范围对照" });
    expect(within(current).getByText(/new-technical-text/)).toBeInTheDocument();
    expect(
      within(current).queryByText(/^第 2 页：technical-text$/),
    ).not.toBeInTheDocument();
  },
);

it.each(["path", "selection", "digest", "material"])(
  "resets candidates and discards late responses when %s changes",
  async (change) => {
    const pending = deferred<{
      data: { items: ReturnType<typeof candidate>[]; has_more: boolean };
    }>();
    mocks.api.mockReset().mockReturnValueOnce(pending.promise);
    const path = "/bids/bid/partial-page-selections";
    const view = render(
      <PartialPageComparison path={path} selection={requirement} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
    );
    const newer =
      change === "selection"
        ? selection("new-requirement", "requirement_reference")
        : change === "digest"
          ? {
              ...requirement,
              proof: { ...requirement.proof, digest: "updated" },
            }
          : change === "material"
            ? { ...requirement, current_material: false }
            : requirement;
    view.rerender(
      <PartialPageComparison
        path={change === "path" ? "/bids/new/partial-page-selections" : path}
        selection={newer}
      />,
    );
    await act(async () => {
      pending.resolve({
        data: { items: [candidate("technical")], has_more: false },
      });
    });
    expect(screen.queryByLabelText("另一范围")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
    ).toBeEnabled();
  },
);

it("keeps a newer completed comparison when an earlier request finishes afterward", async () => {
  const pending = deferred<ReturnType<typeof comparisonData>>();
  mocks.api
    .mockReset()
    .mockResolvedValueOnce({
      data: {
        items: [candidate("technical"), candidate("new-technical")],
        has_more: false,
      },
    })
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce(
      comparisonData(selection("new-technical", "technical_reference")),
    );
  render(
    <PartialPageComparison
      path="/bids/bid/partial-page-selections"
      selection={requirement}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "选择另一份已确认范围进行人工对照" }),
  );
  const select = await screen.findByLabelText("另一范围");
  await user.selectOptions(select, "technical");
  await user.click(screen.getByRole("button", { name: "打开范围对照" }));
  await user.selectOptions(select, "new-technical");
  await user.click(screen.getByRole("button", { name: "打开范围对照" }));
  expect(await screen.findByText(/new-technical-text/)).toBeInTheDocument();
  await act(async () => {
    pending.resolve(comparisonData(technical));
  });
  expect(screen.getByText(/new-technical-text/)).toBeInTheDocument();
  expect(
    screen.queryByText(/^第 2 页：technical-text$/),
  ).not.toBeInTheDocument();
});

it("suppresses synchronous duplicate candidate requests and comparison requests", async () => {
  const list = deferred<{
    data: { items: ReturnType<typeof candidate>[]; has_more: boolean };
  }>();
  const pending = deferred<ReturnType<typeof comparisonData>>();
  mocks.api
    .mockReset()
    .mockReturnValueOnce(list.promise)
    .mockReturnValueOnce(pending.promise);
  const view = render(
    <StrictMode>
      <PartialPageComparison
        path="/bids/bid/partial-page-selections"
        selection={requirement}
      />
    </StrictMode>,
  );
  const load = screen.getByRole("button", {
    name: "选择另一份已确认范围进行人工对照",
  });
  act(() => {
    load.click();
    load.click();
  });
  expect(mocks.api).toHaveBeenCalledTimes(1);
  await act(async () => {
    list.resolve({
      data: { items: [candidate("technical")], has_more: false },
    });
  });
  fireEvent.change(screen.getByLabelText("另一范围"), {
    target: { value: "technical" },
  });
  const compare = screen.getByRole("button", { name: "打开范围对照" });
  act(() => {
    compare.click();
    compare.click();
  });
  expect(mocks.api).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(async () => {
    pending.resolve(comparisonData(technical));
  });
  expect(
    screen.queryByRole("region", { name: "人工范围对照" }),
  ).not.toBeInTheDocument();
});
