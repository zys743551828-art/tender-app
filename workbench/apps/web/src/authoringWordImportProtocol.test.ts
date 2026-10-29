import { describe, expect, it } from "vitest";
import type { AuthoringWordImportCandidate } from "./contracts";
import {
  importCandidate,
  importCandidateWithImage,
  importId,
  importResolution,
  importScope,
} from "./authoringWordImportFixtures.test-support";
import {
  validateWordImportCandidate,
  validateWordImportResult,
  wordImportSectionOrder,
} from "./authoringWordImportProtocol";

it("候选保持根与子章节层级、表格和候选图片，且不占用原章节身份", () => {
  const candidate = importCandidateWithImage();
  expect(validateWordImportCandidate(candidate, importScope)).toBe(candidate);
  expect(
    wordImportSectionOrder(candidate).map(({ section, depth }) => [
      section.title,
      depth,
    ]),
  ).toEqual([
    ["施工组织", 0],
    ["进度安排", 1],
  ]);
});

describe("拒绝无法证明来源或结构的候选", () => {
  const invalid: [string, (value: AuthoringWordImportCandidate) => void][] = [
    [
      "另一原件摘要",
      (value) => {
        value.source.digest = "0".repeat(64);
      },
    ],
    [
      "复用旧章节ID",
      (value) => {
        value.sections[0].section_id = value.existing_sections[0].section_id;
      },
    ],
    [
      "直接挂到旧章节",
      (value) => {
        value.sections[0].parent_id = value.existing_sections[0].section_id;
      },
    ],
    [
      "父子循环",
      (value) => {
        value.sections[0].parent_key = value.sections[1].key;
        value.sections[0].parent_id = value.sections[1].section_id;
      },
    ],
    [
      "映射到错误章节中的节点",
      (value) => {
        value.mapping[0].section_key = value.sections[1].key;
      },
    ],
  ];
  it.each(invalid)("%s", (_label, change) => {
    const candidate = importCandidate();
    change(candidate);
    expect(() => validateWordImportCandidate(candidate, importScope)).toThrow(
      /无法核对/,
    );
  });
});

function append(candidate: AuthoringWordImportCandidate) {
  return importResolution(candidate, {
    headers: {
      "Idempotency-Key": importId(50),
      "If-Match": candidate.base_draft_etag,
    },
    body: JSON.stringify({
      decision: "append",
      candidate_digest: candidate.candidate_digest,
      acknowledged_issue_ids: candidate.issues.map((issue) => issue.id),
      reason: "已逐项核对并明确追加",
    }),
  });
}

it("成功回执不能遗漏损失确认或替换创建章节身份", () => {
  const candidate = importCandidate();
  const result = append(candidate);
  expect(validateWordImportResult(result, importScope, candidate)).toBe(result);
  result.command.request.acknowledged_issue_ids = [];
  expect(() =>
    validateWordImportResult(result, importScope, candidate),
  ).toThrow(/无法核对/);
  const another = append(candidate);
  another.created_section_ids[0] = candidate.existing_sections[0].section_id;
  expect(() =>
    validateWordImportResult(another, importScope, candidate),
  ).toThrow(/无法核对/);
});

it("历史状态须与实际处理回执一致，不能把拒绝历史标为已追加", () => {
  const candidate = importCandidate();
  candidate.state = "rejected";
  candidate.can_apply = false;
  candidate.resolution = append(candidate);
  expect(() => validateWordImportCandidate(candidate, importScope)).toThrow(
    /无法核对/,
  );
});
