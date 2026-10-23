import { expect, it } from "vitest";
import { ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import {
  definitelyRejectedPackageSubmission,
  submissionTime,
  validatePackageSubmission,
  validatePackageSubmissionAck,
  validatePackageSubmissionPreview,
  validateSubmissionRun,
  validPackageSubmissionSelection,
  validateSubmissionRunTargets,
} from "./packageSubmissionProtocol";
import {
  submissionFixture,
  submissionReceipt,
  submissionScope,
  submissionEtag,
  submissionId as id,
  submissionRunFixture,
} from "./packageSubmissionFixtures.test-support";

it("明确空关联的包选择有效，范围或核查不能脱离清单", async () => {
  const f = await submissionFixture();
  expect(validPackageSubmissionSelection(f.body.selection)).toBe(true);
  expect(
    validPackageSubmissionSelection({
      ...f.body.selection,
      coverage: { id: id(9), digest: "a".repeat(64) },
    }),
  ).toBe(false);
  expect(
    validPackageSubmissionSelection({
      ...f.body.selection,
      revision_id: "latest",
    }),
  ).toBe(false);
});
it("带时区时间保留微秒并拒绝未来、无时区与错误日历", () => {
  expect(submissionTime("2025-01-02T10:30:00.1234+08:00")).toBe(
    "2025-01-02T10:30:00.1234+08:00",
  );
  expect(() => submissionTime("2025-01-02T10:30:00")).toThrow();
  expect(() => submissionTime("2025-02-30T10:30:00Z")).toThrow();
  expect(() => submissionTime("2025-01-02T10:30:00.1234567Z")).toThrow();
  expect(() => submissionTime("9999-01-01T00:00:00Z")).toThrow();
});
it("只读预览核对整包内容摘要、精确清单与四门，不接受伪造放行", async () => {
  const f = await submissionFixture(true);
  await expect(
    validatePackageSubmissionPreview(
      f.preview,
      f.body.selection,
      submissionScope.bidId,
    ),
  ).resolves.toEqual(f.preview);
  const wrong = structuredClone(f.preview);
  wrong.selection.target.manifest.members[0].document_version_id = id(999);
  await expect(
    validatePackageSubmissionPreview(
      wrong,
      f.body.selection,
      submissionScope.bidId,
    ),
  ).rejects.toThrow();
  const grant = structuredClone(f.preview);
  Object.assign(grant.gate.manifest, { allowed: true });
  grant.gate.digest = await jsonDigest(grant.gate.manifest);
  await expect(
    validatePackageSubmissionPreview(
      grant,
      f.body.selection,
      submissionScope.bidId,
    ),
  ).rejects.toThrow();
});
it("回执绑定原body、作用域、成员、键与强条件，历史不会当成ACK", async () => {
  const f = await submissionFixture(),
    pending = {
      key: id(77),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: null,
    };
  const ack = await submissionReceipt(f, pending);
  await expect(
    validatePackageSubmissionAck(
      ack,
      submissionEtag(2),
      submissionScope,
      pending,
    ),
  ).resolves.toEqual(ack.submission);
  for (const mutate of [
    (v: typeof ack) => {
      v.command.actor_id = id(99);
    },
    (v: typeof ack) => {
      v.command.idempotency_key = id(99);
    },
    (v: typeof ack) => {
      v.command.request_digest = "a".repeat(64);
    },
    (v: typeof ack) => {
      v.command.request.explanation = "不同正文";
    },
  ]) {
    const bad = structuredClone(ack);
    mutate(bad);
    await expect(
      validatePackageSubmissionAck(
        bad,
        submissionEtag(2),
        submissionScope,
        pending,
      ),
    ).rejects.toThrow();
  }
  await expect(
    validatePackageSubmissionAck(ack, undefined, submissionScope, pending),
  ).rejects.toThrow();
  await expect(
    validatePackageSubmissionAck(
      ack,
      `"bid:${id(99)}:${"2".repeat(64)}"`,
      submissionScope,
      pending,
    ),
  ).rejects.toThrow();
});
it("追加更正回执绑定统一头和旧记录，旧正文头不能被静默替换", async () => {
  const f = await submissionFixture(false, {
    id: id(120),
    revision: 4,
    subject_kind: "single_body",
  });
  const p = {
      key: id(77),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: id(120),
    },
    ack = await submissionReceipt(f, p);
  await expect(
    validatePackageSubmissionAck(ack, submissionEtag(2), submissionScope, p),
  ).resolves.toEqual(ack.submission);
  const bad = structuredClone(ack);
  bad.submission.package_binding.manifest.head_revision = 8;
  bad.submission.package_binding.digest = await jsonDigest(
    bad.submission.package_binding.manifest,
  );
  await expect(
    validatePackageSubmissionAck(bad, submissionEtag(2), submissionScope, p),
  ).rejects.toThrow();
});
it("重算绑定摘要也不能隐藏缺少原件或把字节核验混成检查放行", async () => {
  const f = await submissionFixture(true),
    ack = await submissionReceipt(f, {
      key: id(77),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: null,
    });
  await expect(
    validatePackageSubmission(ack.submission, submissionScope.bidId),
  ).resolves.toBe(ack.submission);
  const bad = structuredClone(ack.submission);
  bad.package_binding.manifest.originals.pop();
  bad.package_binding.digest = await jsonDigest(bad.package_binding.manifest);
  await expect(
    validatePackageSubmission(bad, submissionScope.bidId),
  ).rejects.toThrow();
  const gate = structuredClone(ack.submission);
  Object.assign(
    gate.package_binding.manifest.gate.manifest.gates.current_input,
    { original_verification: "verified" },
  );
  gate.package_binding.manifest.gate.digest = await jsonDigest(
    gate.package_binding.manifest.gate.manifest,
  );
  gate.package_binding.digest = await jsonDigest(gate.package_binding.manifest);
  await expect(
    validatePackageSubmission(gate, submissionScope.bidId),
  ).rejects.toThrow();
  const identity = structuredClone(ack.submission);
  identity.package_binding.manifest.recorded_identity.bidder_name =
    "其他登记主体";
  identity.package_binding.digest = await jsonDigest(
    identity.package_binding.manifest,
  );
  await expect(
    validatePackageSubmission(identity, submissionScope.bidId),
  ).rejects.toThrow();
});
it("核查目录只发现身份，读取确切运行并核对原frozen/prepared与结果", async () => {
  const f = await submissionFixture(true),
    { run, target } = submissionRunFixture(f);
  const page = {
    bid_id: submissionScope.bidId,
    items: [target],
    next_offset: null,
    reference_only: true as const,
    changes_frozen_result: false as const,
    formal_score_allowed: false as const,
  };
  expect(validateSubmissionRunTargets(page, submissionScope.bidId)).toBe(page);
  await expect(
    validateSubmissionRun(run, target, submissionScope.bidId),
  ).resolves.toBe(run);
  await expect(
    validateSubmissionRun(
      { ...run, execution_input_id: id(999) },
      target,
      submissionScope.bidId,
    ),
  ).rejects.toThrow();
  await expect(
    validateSubmissionRun(
      run,
      { ...target, inventory_id: id(999) },
      submissionScope.bidId,
    ),
  ).rejects.toThrow();
  expect(() =>
    validateSubmissionRunTargets(
      { ...page, next_offset: 1 },
      submissionScope.bidId,
      1,
    ),
  ).toThrow();
});
it("只清确切提交前业务拒绝，通用错误、存储故障和不匹配ACK仍保原请求", () => {
  for (const [code, status] of [
    ["PACKAGE_SUBMISSION_HEAD_CONFLICT", 412],
    ["PACKAGE_SUBMISSION_ORIGINAL_CHANGED", 409],
    ["PACKAGE_SUBMISSION_FUTURE_TIME", 422],
    ["REVISION_CONFLICT", 412],
  ] as const)
    expect(
      definitelyRejectedPackageSubmission(new ApiError(code, status, code)),
    ).toBe(true);
  for (const [code, status] of [
    ["PACKAGE_SUBMISSION_INVALID", 422],
    ["PACKAGE_SUBMISSION_SCOPE_MISMATCH", 422],
    ["IDEMPOTENCY_CONFLICT", 409],
    ["COMMAND_INCOMPLETE", 409],
    ["ORIGINAL_NOT_AVAILABLE", 503],
    ["FORBIDDEN", 403],
    ["REQUEST_FAILED", 412],
  ] as const)
    expect(
      definitelyRejectedPackageSubmission(new ApiError(code, status, code)),
    ).toBe(false);
});
