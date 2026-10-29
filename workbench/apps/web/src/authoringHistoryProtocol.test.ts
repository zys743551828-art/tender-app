import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  historyFixture,
  historyLongText,
  historyScope,
} from "./authoringHistoryFixtures.test-support";
import {
  historicalSectionPath,
  readAuthoringRevisionPage,
  validateHistoricalSection,
} from "./authoringHistoryProtocol";

const selection = (digest: string) => ({
  ...historyScope,
  revision: 2,
  digest,
});

it("完整原稿、稀疏原 ordinal、合并表格和图片绑定通过，精确路径不推断最新修订", async () => {
  const f = await historyFixture({ long: true, image: true });
  const expected = selection(f.state.history.digest);
  const value = await validateHistoricalSection(f.state.history, expected);
  expect(value).toBe(f.state.history);
  expect(JSON.stringify(value.content)).toContain(historyLongText);
  expect(value.content.attrs.ordinal).toBe(7);
  expect(historicalSectionPath(expected)).toBe(
    `/bids/${historyScope.bidId}/drafts/${historyScope.draftId}/sections/${historyScope.sectionId}/revisions/2?expected_digest=${expected.digest}`,
  );
  expect(value.source_qualification_assessed).toBe(false);
  expect(value.restoration_authorized).toBe(false);
});

it.each([
  "bid_id",
  "draft_id",
  "section_id",
  "revision",
  "digest",
  "read_only",
  "source_qualification_assessed",
  "restoration_authorized",
  "extra",
  "created_at",
])("历史读取拒绝错误身份或资格：%s", async (field) => {
  const f = await historyFixture();
  const value = structuredClone(f.state.history) as unknown as Record<
    string,
    unknown
  >;
  if (field.endsWith("_id"))
    value[field] = "00000000-0000-4000-8000-999999999999";
  else if (field === "revision") value.revision = 3;
  else if (field === "digest") value.digest = "0".repeat(64);
  else if (field === "created_at") value.created_at = "not a saved time";
  else if (field === "extra") value.other = "must not leak";
  else value[field] = !value[field];
  await expect(
    validateHistoricalSection(value, selection(f.state.history.digest)),
  ).rejects.toThrow("历史章节");
});

it("正文被截断但保留旧摘要时拒绝；未知节点即使重新封摘要也拒绝", async () => {
  const f = await historyFixture();
  const truncated = structuredClone(f.state.history);
  truncated.content.content.pop();
  await expect(
    validateHistoricalSection(truncated, selection(f.state.history.digest)),
  ).rejects.toThrow();
  const unknown = structuredClone(f.state.history);
  (unknown.content.content[0] as { type: string }).type = "unknown";
  unknown.digest = await jsonDigest(unknown.content);
  await expect(
    validateHistoricalSection(unknown, selection(unknown.digest)),
  ).rejects.toThrow();
});

it.each([
  "missing",
  "extra",
  "wrong_asset",
  "wrong_revision",
  "duplicate",
  "unknown_key",
])("图片绑定必须与历史正文逐个吻合：%s", async (damage) => {
  const f = await historyFixture({ image: true });
  const value = structuredClone(f.state.history);
  if (damage === "missing") value.images = [];
  if (damage === "extra")
    value.images.push({
      ...value.images[0],
      asset_version_id: "00000000-0000-4000-8000-999999999999",
    });
  if (damage === "wrong_asset")
    value.images[0].asset_id = "00000000-0000-4000-8000-999999999999";
  if (damage === "wrong_revision") value.images[0].asset_revision = 2;
  if (damage === "duplicate") value.images.push({ ...value.images[0] });
  if (damage === "unknown_key")
    Object.assign(value.images[0], { object_key: "must not be public" });
  await expect(
    validateHistoricalSection(value, selection(value.digest)),
  ).rejects.toThrow();
});

it("历史目录接受字段顺序和安全整数上界，但拒绝重复、倒序、越过游标或注入字段", async () => {
  const f = await historyFixture(),
    page = f.defaultPage();
  expect(readAuthoringRevisionPage(page)).toEqual(page);
  const last = { ...page.items[0], revision: Number.MAX_SAFE_INTEGER };
  expect(
    readAuthoringRevisionPage({ items: [last], next_cursor: null }).items[0]
      .revision,
  ).toBe(Number.MAX_SAFE_INTEGER);
  expect(() =>
    readAuthoringRevisionPage({
      items: [page.items[0], page.items[0]],
      next_cursor: null,
    }),
  ).toThrow();
  expect(() =>
    readAuthoringRevisionPage({
      items: [...page.items].reverse(),
      next_cursor: null,
    }),
  ).toThrow();
  expect(() => readAuthoringRevisionPage(page, 3)).toThrow();
  expect(() =>
    readAuthoringRevisionPage({ ...page, next_cursor: 999 }),
  ).toThrow();
  expect(() => readAuthoringRevisionPage({ ...page, latest: true })).toThrow();
});
