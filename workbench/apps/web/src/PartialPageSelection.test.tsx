import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { DocumentEvidenceView, DocumentView } from "./contracts";
import { PartialPageSelection } from "./PartialPageSelection";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  api: mocks.api,
  commandKey: () => "stable-key",
}));
const document = {
  id: "document",
  bid_id: "bid",
  sha256: "a".repeat(64),
} as DocumentView;
const evidence = {
  document_version_id: "document",
  parse_run_id: "parse",
  coverage: "partial",
  gaps: ["OCR"],
  items: [
    {
      id: "selected",
      physical_page: 65,
      quote: "所选原文",
      document_version_id: "document",
      parse_run_id: "parse",
    },
    {
      id: "outside",
      physical_page: 1,
      quote: "范围外原文",
      document_version_id: "document",
      parse_run_id: "parse",
    },
  ],
} as DocumentEvidenceView;
const record = {
  id: "selection",
  current_material: true,
  source_effectivity: "not_verified",
  model_execution_allowed: false,
  formal_qualification: false,
  proof: {
    digest: "d".repeat(64),
    manifest: {
      source: {
        document_version_id: "document",
        parse_run_id: "parse",
        file_digest: "a".repeat(64),
      },
      purpose: "technical_reference",
      coverage: "partial",
      selection: { first_page: 65, last_page: 65 },
      selected_pages: [
        { physical_page: 65, quality: "partial", gaps: ["OCR_LOW_CONFIDENCE"] },
      ],
      selected_blocks: [{ id: "selected", physical_page: 65 }],
      omitted_ranges: [
        { first_page: 1, last_page: 64 },
        { first_page: 66, last_page: 123 },
      ],
    },
  },
};

beforeEach(() => {
  mocks.api.mockReset();
});

it("requires explicit confirmation and shows only the selected evidence with its original page", async () => {
  const onPage = vi.fn();
  mocks.api.mockResolvedValue({ data: record });
  render(
    <PartialPageSelection
      document={document}
      evidence={evidence}
      page={65}
      pageCount={123}
      onPage={onPage}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  const submit = screen.getByRole("button", { name: "确认并保存页范围" });
  expect(submit).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(submit);
  expect(await screen.findByText("人工确认记录 · 部分覆盖")).toBeVisible();
  expect(mocks.api).toHaveBeenCalledTimes(2);
  await user.click(screen.getByText("查看缺口原因与核查建议"));
  expect(screen.getByText(/部分 OCR 文字置信度偏低/)).toBeVisible();
  await user.click(screen.getByText("查看缺口原因与核查建议"));
  expect(screen.getByText(/部分 OCR 文字置信度偏低/)).not.toBeVisible();
  await user.click(screen.getByText("查看所选范围的解析依据"));
  const status = screen.getByRole("status");
  mocks.api.mockResolvedValueOnce({
    data: {
      selection_id: record.id,
      proof_digest: record.proof.digest,
      model_execution_allowed: false,
      formal_qualification: false,
      items: [
        {
          id: "selected",
          physical_page: 65,
          quote: "所选原文",
          source_status: "candidate",
        },
      ],
    },
  });
  await user.click(
    within(status).getByRole("button", { name: "读取所选范围证据" }),
  );
  expect(await within(status).findByText("所选原文")).toBeVisible();
  expect(within(status).queryByText("范围外原文")).not.toBeInTheDocument();
  expect(
    within(status).queryByRole("button", { name: "第 1 物理页" }),
  ).not.toBeInTheDocument();
  await user.click(
    within(status).getByRole("button", { name: "第 65 物理页" }),
  );
  expect(onPage).toHaveBeenCalledWith(65);
});

it("refuses a rechecked record bound to another parse", async () => {
  const foreign = structuredClone(record);
  foreign.proof.manifest.source.parse_run_id = "other";
  mocks.api
    .mockResolvedValueOnce({ data: record })
    .mockResolvedValueOnce({ data: foreign });
  render(
    <PartialPageSelection
      document={document}
      evidence={evidence}
      page={65}
      pageCount={123}
      onPage={vi.fn()}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "确认并保存页范围" }));
  expect(
    await screen.findByText("已保存记录与复核依据不一致，请重新读取。"),
  ).toBeVisible();
  expect(screen.queryByText("人工确认记录 · 部分覆盖")).not.toBeInTheDocument();
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
const historyItems = ["old-range", "new-range"].map((id) => ({
  id,
  confirmed_by: "actor",
  created_at: "2026-11-12T00:00:00Z",
}));
function range(id: string, page: number) {
  const item = structuredClone(record);
  item.id = id;
  item.proof.digest = id + "-digest";
  item.proof.manifest.selection = { first_page: page, last_page: page };
  item.proof.manifest.selected_pages = [
    { physical_page: page, quality: "partial", gaps: ["OCR_LOW_CONFIDENCE"] },
  ];
  item.proof.manifest.selected_blocks = [
    { id: id + "-block", physical_page: page },
  ];
  return item;
}
function scoped(item: ReturnType<typeof range>) {
  return {
    data: {
      selection_id: item.id,
      proof_digest: item.proof.digest,
      model_execution_allowed: false,
      formal_qualification: false,
      items: [
        {
          id: item.id + "-block",
          physical_page: item.proof.manifest.selection.first_page,
          quote: item.id + "-text",
          source_status: "candidate",
        },
      ],
    },
  };
}
function panel() {
  return (
    <PartialPageSelection
      document={document}
      evidence={evidence}
      page={65}
      pageCount={123}
      onPage={vi.fn()}
    />
  );
}
async function history() {
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  await user.click(screen.getByRole("button", { name: "查看历史范围" }));
  return user;
}
it.each(["result", "error"])(
  "ignores late scope evidence %s after navigating to another history record",
  async (kind) => {
    const old = range("old-range", 65),
      newer = range("new-range", 66);
    const pending = deferred<ReturnType<typeof scoped>>();
    mocks.api
      .mockResolvedValueOnce({ data: { items: historyItems, has_more: false } })
      .mockResolvedValueOnce({ data: old })
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce({ data: newer });
    render(panel());
    const user = await history();
    await user.click(screen.getByRole("button", { name: /old-rang/ }));
    await screen.findByText("人工确认记录 · 部分覆盖");
    await user.click(screen.getByText("查看所选范围的解析依据"));
    await user.click(screen.getByRole("button", { name: "读取所选范围证据" }));
    await user.click(screen.getByRole("button", { name: /new-rang/ }));
    await screen.findByRole("button", { name: "第 66 物理页" });
    await act(async () => {
      if (kind === "result") pending.resolve(scoped(old));
      else pending.reject(new Error("old evidence failed"));
    });
    expect(screen.queryByText("old-range-text")).not.toBeInTheDocument();
    expect(screen.queryByText("old evidence failed")).not.toBeInTheDocument();
    mocks.api.mockResolvedValueOnce(scoped(newer));
    await user.click(screen.getByRole("button", { name: "读取所选范围证据" }));
    expect(await screen.findByText("new-range-text")).toBeInTheDocument();
  },
);
it("does not request a recheck after a saved record arrives after unmount", async () => {
  const pending = deferred<{ data: typeof record }>();
  mocks.api.mockReturnValueOnce(pending.promise);
  const view = render(panel());
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "确认并保存页范围" }));
  view.unmount();
  await act(async () => {
    pending.resolve({ data: record });
  });
  expect(mocks.api).toHaveBeenCalledTimes(1);
});

it("keeps the latest historical selection when the older response finishes last", async () => {
  const pending = deferred<{ data: ReturnType<typeof range> }>();
  mocks.api
    .mockResolvedValueOnce({ data: { items: historyItems, has_more: false } })
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce({ data: range("new-range", 66) });
  render(panel());
  const user = await history();
  await user.click(screen.getByRole("button", { name: /old-rang/ }));
  await user.click(screen.getByRole("button", { name: /new-rang/ }));
  await screen.findByRole("button", { name: "第 66 物理页" });
  await act(async () => {
    pending.resolve({ data: range("old-range", 65) });
  });
  expect(
    screen.getByRole("button", { name: "第 66 物理页" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "第 65 物理页" }),
  ).not.toBeInTheDocument();
});
it.each(["project", "document", "digest", "parse"])(
  "resets history and ignores pending data after %s changes",
  async (change) => {
    const pending = deferred<{
      data: { items: typeof historyItems; has_more: boolean };
    }>();
    mocks.api.mockReturnValueOnce(pending.promise);
    const view = render(panel());
    await history();
    const doc =
      change === "project"
        ? { ...document, bid_id: "new-bid" }
        : change === "document"
          ? { ...document, id: "new-document" }
          : change === "digest"
            ? { ...document, sha256: "b".repeat(64) }
            : document;
    const parsed =
      change === "parse"
        ? { ...evidence, parse_run_id: "new-parse" }
        : evidence;
    view.rerender(
      <PartialPageSelection
        document={doc}
        evidence={parsed}
        page={66}
        pageCount={123}
        onPage={vi.fn()}
      />,
    );
    await act(async () => {
      pending.resolve({ data: { items: historyItems, has_more: false } });
    });
    expect(
      screen.queryByRole("button", { name: /old-rang/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("人工确认记录 · 部分覆盖"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("人工确认部分页范围"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "查看历史范围" })).toBeEnabled();
    expect(screen.getByLabelText("起始物理页")).toHaveValue(66);
  },
);
it("suppresses synchronous duplicate saves in StrictMode and permits a later deliberate save", async () => {
  const pending = deferred<{ data: typeof record }>();
  mocks.api
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue({ data: record });
  render(<StrictMode>{panel()}</StrictMode>);
  const user = userEvent.setup();
  await user.click(screen.getByText("人工确认部分页范围"));
  await user.click(screen.getByRole("checkbox"));
  const save = screen.getByRole("button", { name: "确认并保存页范围" });
  act(() => {
    save.click();
    save.click();
  });
  expect(mocks.api).toHaveBeenCalledTimes(1);
  await act(async () => {
    pending.resolve({ data: record });
  });
  await screen.findByText("人工确认记录 · 部分覆盖");
  expect(mocks.api).toHaveBeenCalledTimes(2);
  await user.click(save);
  expect(mocks.api).toHaveBeenCalledTimes(4);
});
it("allows history navigation without pretending an already-sent save was cancelled", async () => {
  const pending = deferred<{ data: typeof record }>();
  mocks.api
    .mockResolvedValueOnce({ data: { items: historyItems, has_more: false } })
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce({ data: range("new-range", 66) });
  render(panel());
  const user = await history();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "确认并保存页范围" }));
  await user.click(screen.getByRole("button", { name: /new-rang/ }));
  await screen.findByRole("button", { name: "第 66 物理页" });
  await act(async () => {
    pending.resolve({ data: record });
  });
  expect(mocks.api).toHaveBeenCalledTimes(3);
  expect(
    screen.getByRole("button", { name: "第 66 物理页" }),
  ).toBeInTheDocument();
});

it("rejects another historical selection even when it belongs to the same document and parse", async () => {
  mocks.api
    .mockResolvedValueOnce({ data: { items: historyItems, has_more: false } })
    .mockResolvedValueOnce({ data: range("new-range", 66) });
  render(panel());
  const user = await history();
  await user.click(screen.getByRole("button", { name: /old-rang/ }));
  expect(
    await screen.findByText(
      "历史记录对应的原件或解析版本不同，请先打开对应版本。",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("人工确认记录 · 部分覆盖")).not.toBeInTheDocument();
});
