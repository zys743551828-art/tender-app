import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import {
  exactAuthoringFixture,
  exactId,
} from "./authoringExactFixtures.test-support";
import { jsonDigest } from "./editorSchema";
import { HistoricalCandidateSources } from "./HistoricalCandidateSources";
import {
  candidateParseSourceId,
  checkedHistoricalSources,
  historicalSourcesPath,
} from "./historicalCandidateSources";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
vi.mock("./PdfPreview", () => ({
  PdfPreview: ({
    page,
    expectedSha256,
  }: {
    page: number;
    expectedSha256?: string;
  }) => (
    <canvas
      role="img"
      aria-label={`固定原页 ${page} · 摘要 ${expectedSha256}`}
    />
  ),
}));
const mocked = vi.mocked(api);

beforeEach(() => {
  mocked.mockReset();
});

async function fixture(withCitations = true) {
  const f = await exactAuthoringFixture();
  const action = structuredClone(f.executed);
  const [prior] = action.preview.before.content;
  const [after] = action.preview.after.content;
  const entries = await Promise.all(
    (["authority", "target"] as const).map(async (role, index) => {
      const parse = exactId(8000 + index);
      return {
        evidence_id: exactId(8005 + index),
        document_version_id: exactId(8010 + index),
        parse_run_id: parse,
        physical_page: index + 2,
        source_id: await candidateParseSourceId(parse),
        source_revision: index + 1,
        evidence_digest: "f".repeat(64),
        memberships: [
          {
            role,
            package_id: exactId(8020 + index),
            revision_id: exactId(8030 + index),
            manifest_digest: "a".repeat(64),
          },
        ],
      };
    }),
  );
  // The chapter already had its target document citation. Only the model's
  // actual ordered evidence IDs are eligible, even for a pre-existing ref.
  const sourceRef = ({
    evidence_id,
    document_version_id,
    source_id,
    source_revision,
  }: (typeof entries)[number]) => ({
    evidence_id,
    document_version_id,
    source_id,
    source_revision,
  });
  action.preview.before.attrs.source_refs = [sourceRef(entries[1])];
  action.preview.after.attrs.source_refs = entries.map(sourceRef);
  const qualification = structuredClone(f.qualification);
  const manifest = qualification.manifest;
  const node = {
    node_id: prior.attrs.id,
    node_type: "paragraph",
    before_digest: await jsonDigest(prior),
    after_digest: await jsonDigest(after),
  };
  const selected = withCitations ? entries.slice(0, 1) : [];
  manifest.origin.candidate_digest = await jsonDigest({
    protocol: "package-authoring-candidate/1",
    input: manifest.input,
    node_id: node.node_id,
    before_digest: node.before_digest,
    replacement_text:
      after.content?.[0]?.type === "text" ? after.content[0].text : "",
    evidence_ids: selected.map((item) => item.evidence_id),
  });
  qualification.digest = await jsonDigest(manifest);
  const proof = { action, saved: f.saved, qualification };
  const base = {
    protocol: "authoring-historical-candidate-trace/1",
    bid_id: action.target_bid_id,
    action_id: action.action_id,
    action_digest: action.request_digest,
    candidate_digest: manifest.origin.candidate_digest,
    snapshot_id: f.saved.snapshot_id,
    snapshot_digest: f.saved.snapshot_digest,
    section_revision_id: manifest.section_revision_id,
    qualification_digest: qualification.digest,
    node,
    citations: selected,
    historic_only: true,
    original_bytes_reverified: false,
    current_effectivity_verified: false,
    content_correctness_certified: false,
    publication_authorized: false,
  };
  return { proof, base, entries, path: historicalSourcesPath(proof) };
}

async function envelope<T>(data: T) {
  return { ...data, trace_digest: await jsonDigest(data) };
}

it("only loads the exact original trace on demand, then opens the verified physical page", async () => {
  const { proof, base, path, entries } = await fixture();
  const record = await envelope(base);
  const [source] = entries;
  mocked.mockImplementation(async (url) => {
    if (url === path) return { data: record, etag: null };
    if (url === `/evidence/${source.evidence_id}`)
      return {
        data: {
          id: source.evidence_id,
          document_version_id: source.document_version_id,
          parse_run_id: source.parse_run_id,
          physical_page: source.physical_page,
          source_status: "withdrawn",
          quote: "已撤回合成原页文本",
        },
        etag: null,
      };
    if (url === `/documents/${source.document_version_id}`)
      return {
        data: {
          id: source.document_version_id,
          filename: "合成原件.pdf",
          role: "tender",
          file_revision: 2,
          bid_id: proof.action.target_bid_id,
          media_type: "application/pdf",
          sha256: "a".repeat(64),
        },
        etag: null,
      };
    if (url === `/artifacts/${source.document_version_id}/download`)
      return {
        data: {
          artifact_id: source.document_version_id,
          download_url: "http://fixture.test/historical.pdf",
        },
        etag: null,
      };
    if (url === `/documents/${source.document_version_id}/evidence`)
      return {
        data: {
          document_version_id: source.document_version_id,
          items: [{ ...source, quote: "不属于历史引用的最新版解析" }],
        },
        etag: null,
      };
    throw new Error(`Unexpected historical request: ${url}`);
  });
  const user = userEvent.setup();
  render(<HistoricalCandidateSources proof={proof} />);
  expect(mocked).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "查看本次候选引用的原页" }),
  );
  expect(await screen.findByText("原候选引用 1 条")).toBeVisible();
  expect(screen.getByText("原物理页 2 · 依据包")).toBeVisible();
  expect(screen.queryByText(/工作投标包/)).toBeNull();
  expect(screen.getByText(/没有重新核验原件字节或当前效力/)).toBeVisible();
  expect(mocked.mock.calls).toEqual([[path]]);
  await user.click(screen.getByRole("button", { name: "查看引用原页（1）" }));
  expect(
    await screen.findByRole("button", { name: "打开物理页 2 · 文件版本 2" }),
  ).toBeVisible();
  expect(screen.getByText("来源已撤回")).toBeVisible();
  const open = screen.getByRole("button", {
    name: "打开物理页 2 · 文件版本 2",
  });
  await user.click(open);
  expect(
    await screen.findByRole("img", {
      name: `固定原页 2 · 摘要 ${"a".repeat(64)}`,
    }),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "当时解析的引用摘录" }),
  ).toBeVisible();
  expect(screen.getByText(`固定解析 ${source.parse_run_id}`)).toBeVisible();
  expect(screen.getAllByText("已撤回合成原页文本")).toHaveLength(2);
  expect(screen.queryByText("不属于历史引用的最新版解析")).toBeNull();
  expect(screen.queryByRole("button", { name: "解析文本" })).toBeNull();
  expect(screen.queryByText(/人工确认部分页范围|确认并保存页范围/)).toBeNull();
  expect(screen.queryByRole("button", { name: "下载资料原件" })).toBeNull();
  expect(mocked.mock.calls.map(([url]) => url)).toEqual([
    path,
    `/evidence/${source.evidence_id}`,
    `/documents/${source.document_version_id}`,
    `/artifacts/${source.document_version_id}/download`,
  ]);
  await user.click(screen.getByRole("button", { name: "关闭原件" }));
  expect(open).toHaveFocus();

  expect(
    mocked.mock.calls.every(
      ([, options]) => !options?.method || options.method === "GET",
    ),
  ).toBe(true);
});

it.each(["wrong physical page", "wrong parse"] as const)(
  "does not read or open a substituted live source: %s",
  async (scenario) => {
    const { proof, base, path, entries } = await fixture();
    const record = await envelope(base);
    const [source] = entries;
    mocked.mockImplementation(async (url) => {
      if (url === path) return { data: record, etag: null };
      if (url === `/evidence/${source.evidence_id}`)
        return {
          data: {
            id: source.evidence_id,
            document_version_id: source.document_version_id,
            parse_run_id:
              scenario === "wrong parse" ? exactId(9999) : source.parse_run_id,
            physical_page:
              scenario === "wrong physical page" ? 1 : source.physical_page,
          },
          etag: null,
        };
      throw new Error("Wrong scope must not read a document");
    });
    const user = userEvent.setup();
    render(<HistoricalCandidateSources proof={proof} />);
    await user.click(
      screen.getByRole("button", { name: "查看本次候选引用的原页" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "查看引用原页（1）" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /未打开其他原件|不打开其他原件/,
    );
    expect(screen.queryByRole("button", { name: /打开物理页/ })).toBeNull();
    expect(mocked.mock.calls.map(([url]) => url)).toEqual([
      path,
      `/evidence/${source.evidence_id}`,
    ]);
  },
);

it("rejects a valid-looking foreign result, inherited evidence, or substituted frozen parse", async () => {
  const { proof, base, entries } = await fixture();
  for (const other of [
    { ...base, snapshot_id: exactId(9999) },
    { ...base, citations: [entries[1]] },
    { ...base, citations: [{ ...entries[0], parse_run_id: exactId(9998) }] },
    { ...base, citations: [] },
    { ...base, content_correctness_certified: true },
    { ...base, node: { ...base.node, before_digest: "f".repeat(64) } },
  ]) {
    await expect(
      checkedHistoricalSources(await envelope(other), proof),
    ).rejects.toThrow("固定身份不一致");
  }
  expect(mocked).not.toHaveBeenCalled();
});

it("when the real candidate cited nothing, says so after retrying the same read", async () => {
  const { proof, base, path } = await fixture(false);
  const record = await envelope(base);
  mocked.mockRejectedValueOnce(
    new ApiError("暂不可读", 503, "SYNTHETIC_TIMEOUT"),
  );
  mocked.mockResolvedValueOnce({ data: record, etag: null });
  const user = userEvent.setup();
  render(<HistoricalCandidateSources proof={proof} />);
  await user.click(
    screen.getByRole("button", { name: "查看本次候选引用的原页" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("暂不可读");
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(
    await screen.findByText(
      "此候选没有登记引用。章节已有引用不代替本次候选的引用。",
    ),
  ).toBeVisible();
  expect(mocked.mock.calls).toEqual([[path], [path]]);
});
