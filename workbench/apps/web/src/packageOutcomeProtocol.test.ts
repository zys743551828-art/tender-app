import { expect, it } from "vitest";
import { ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import {
  outcomeFixture,
  outcomeId as id,
  outcomeVerificationAck,
} from "./packageOutcomeFixtures.test-support";
import {
  definitiveOutcomeFailure,
  makeOutcomeRequest,
  outcomeHeadEtag,
  outcomeInstant,
  outcomeVerificationEtag,
  validateOutcomeAck,
  validateOutcomeContext,
  validateOutcomeDetail,
  validateOutcomePage,
  validOutcomeVerification,
  validPendingOutcome,
  type PendingPackageOutcome,
} from "./packageOutcomeProtocol";

it("真实零分、未知和小数精度分别保留，拒绝越界分数与无时区时间", async () => {
  const f = await outcomeFixture();
  const draft = {
    scoreKind: "technical_total" as const,
    value: "0.00",
    maximum: "100.000",
    sourceId: f.body.source_version_id,
    known: f.body.known_at,
  };
  expect(makeOutcomeRequest(f.submission, draft)).toMatchObject({
    value: "0.00",
    maximum: "100.000",
    known_at: f.body.known_at,
  });
  expect(
    makeOutcomeRequest(f.submission, { ...draft, scoreKind: "unknown" }),
  ).toMatchObject({ value: null, maximum: null });
  for (const change of [
    { value: "100.0000000000000000001" },
    { value: "-1" },
    { maximum: "0" },
    { maximum: "" },
    { known: "2025-06-02T10:30:00" },
    { known: "2025-02-30T10:30:00Z" },
    { known: "9999-01-01T00:00:00Z" },
  ])
    expect(() =>
      makeOutcomeRequest(f.submission, { ...draft, ...change }),
    ).toThrow();
  expect(outcomeInstant("2025-06-02T10:30:00.123456+08:00")).toBe(
    outcomeInstant("2025-06-02T02:30:00.123456Z"),
  );
  expect(outcomeInstant("2025-06-02T02:30:00.123457Z")).not.toBe(
    outcomeInstant(f.body.known_at),
  );
});

it("上下文始终绑定原整包与身份，不采用另一个实交或改写的展示身份", async () => {
  const f = await outcomeFixture();
  expect(validateOutcomeContext(f.context, f.submission)).toEqual(f.context);
  for (const change of [
    { submission_id: id(999) },
    { body_version_id: id(999) },
    { formal_sample_eligible: true },
    { identity: { ...f.context.identity, revision_id: id(999) } },
    { authority: { ...f.context.authority, revision_id: id(999) } },
    { display: { ...f.context.display, bidder_name: "不同投标人" } },
    {
      package_binding: { ...f.context.package_binding, digest: "0".repeat(64) },
    },
  ])
    expect(() =>
      validateOutcomeContext({ ...f.context, ...change }, f.submission),
    ).toThrow();
});

it("目录拒绝跨项目、重复头和丢失当前成绩，不把最后一条猜作当前", async () => {
  const f = await outcomeFixture();
  expect(validateOutcomePage(f.page, f.scope.bidId)).toEqual(f.page);
  for (const page of [
    { ...f.page, heads: [...f.page.heads, ...f.page.heads] },
    { ...f.page, items: [{ ...f.view, bid_id: id(999) }] },
    { ...f.page, items: [] },
    { ...f.page, heads: [{ ...f.page.heads[0], outcome_id: id(999) }] },
  ])
    expect(() => validateOutcomePage(page, f.scope.bidId)).toThrow();
});

it("登记回执允许数据库等值小数和带时区微秒，拒绝替换来源、实交或自动核验", async () => {
  const f = await outcomeFixture();
  const p: PendingPackageOutcome = {
    kind: "register",
    key: id(700),
    baseId: null,
    etag: null,
    body: f.body,
  };
  const tag = outcomeHeadEtag(f.submission.id, 1);
  expect(validPendingOutcome(p, f.scope, f.submission)).toBe(true);
  await expect(
    validateOutcomeAck(
      {
        ...f.view,
        value: "0",
        maximum: "100",
        known_at: "2025-06-02T02:30:00.123456Z",
      },
      tag,
      p,
      f.scope,
      f.submission,
    ),
  ).resolves.toBeDefined();
  for (const change of [
    { submission_id: id(999) },
    { source_version_id: id(999) },
    { verification: "verified" },
    { value: null },
    { known_at: "2025-06-02T02:30:00.123457Z" },
    { supersedes_id: id(999) },
  ])
    await expect(
      validateOutcomeAck(
        { ...f.view, ...change },
        tag,
        p,
        f.scope,
        f.submission,
      ),
    ).rejects.toThrow();
  await expect(
    validateOutcomeAck(
      f.view,
      outcomeHeadEtag(f.submission.id, 2),
      p,
      f.scope,
      f.submission,
    ),
  ).rejects.toThrow();
});

it("成绩更正只追加到读取的同一实交头，不能混用核验ETag", async () => {
  const f = await outcomeFixture();
  const p: PendingPackageOutcome = {
    kind: "correct",
    key: id(700),
    baseId: f.view.id,
    etag: outcomeHeadEtag(f.submission.id, 1),
    body: { ...f.body, value: "10.5" },
  };
  const ack = { ...f.view, ...p.body, id: id(701), supersedes_id: f.view.id };
  await expect(
    validateOutcomeAck(
      ack,
      outcomeHeadEtag(f.submission.id, 2),
      p,
      f.scope,
      f.submission,
    ),
  ).resolves.toEqual(ack);
  expect(
    validPendingOutcome(
      { ...p, etag: outcomeVerificationEtag(f.view.id, 1) },
      f.scope,
      f.submission,
    ),
  ).toBe(false);
  expect(
    validPendingOutcome(
      {
        ...p,
        etag: outcomeHeadEtag(f.submission.id, Number.MAX_SAFE_INTEGER + 1),
      },
      f.scope,
      f.submission,
    ),
  ).toBe(false);
  await expect(
    validateOutcomeAck(
      { ...ack, supersedes_id: null },
      outcomeHeadEtag(f.submission.id, 2),
      p,
      f.scope,
      f.submission,
    ),
  ).rejects.toThrow();
});

it("没有原依据包时只接受待核验等意见，选择引文不授予正式样本资格", async () => {
  const f = await outcomeFixture(false);
  expect(
    validOutcomeVerification(
      f.verification,
      f.submission,
      f.body.source_version_id,
    ),
  ).toBe(false);
  expect(
    validOutcomeVerification(
      { ...f.verification, state: "pending" },
      f.submission,
      f.body.source_version_id,
    ),
  ).toBe(true);
  const valid = await outcomeFixture();
  expect(
    validOutcomeVerification(
      valid.verification,
      valid.submission,
      valid.body.source_version_id,
    ),
  ).toBe(true);
  expect(
    validOutcomeVerification(
      {
        ...valid.verification,
        evidence_refs: [
          ...valid.verification.evidence_refs,
          ...valid.verification.evidence_refs,
        ],
      },
      valid.submission,
      valid.body.source_version_id,
    ),
  ).toBe(false);
  expect(
    validOutcomeVerification(
      {
        ...valid.verification,
        evidence_refs: [
          {
            ...valid.verification.evidence_refs[0],
            document_version_id: id(999),
          },
        ],
      },
      valid.submission,
      valid.body.source_version_id,
    ),
  ).toBe(false);
});

it("核验ACK绑定原请求、原成绩、精确依据和逐字引用摘要", async () => {
  const f = await outcomeFixture(),
    ack = await outcomeVerificationAck(f);
  const p: PendingPackageOutcome = {
    kind: "verify",
    key: id(700),
    baseId: f.view.id,
    baseRevision: 0,
    etag: outcomeVerificationEtag(f.view.id, 0),
    score: { ...f.body, supersedes_id: null },
    body: f.verification,
  };
  const tag = outcomeVerificationEtag(f.view.id, 1);
  await expect(
    validateOutcomeAck(ack, tag, p, f.scope, f.submission),
  ).resolves.toEqual(ack);
  const wrong = structuredClone(ack);
  if (
    !wrong.verification_details ||
    !("subject_kind" in wrong.verification_details)
  )
    throw new Error();
  wrong.verification_details.authority_proof!.snapshot.binding_digest =
    "0".repeat(64);
  wrong.verification_details.authority_proof!.digest = await jsonDigest(
    wrong.verification_details.authority_proof!.snapshot,
  );
  await expect(
    validateOutcomeAck(wrong, tag, p, f.scope, f.submission),
  ).rejects.toThrow();
  const quote = structuredClone(ack);
  if (
    !quote.verification_details ||
    !("subject_kind" in quote.verification_details)
  )
    throw new Error();
  const evidence = quote.verification_details.official_source_proof!.snapshot
    .evidence as { quote_digest: string }[];
  evidence[0].quote_digest = "a".repeat(64);
  quote.verification_details.official_source_proof!.digest = await jsonDigest(
    quote.verification_details.official_source_proof!.snapshot,
  );
  await expect(
    validateOutcomeAck(quote, tag, p, f.scope, f.submission),
  ).rejects.toThrow();
  await expect(
    validateOutcomeAck({ ...ack, value: "1" }, tag, p, f.scope, f.submission),
  ).rejects.toThrow();
  await expect(
    validateOutcomeAck(
      ack,
      tag,
      { ...p, body: { ...p.body, reason: "另一个意见" } },
      f.scope,
      f.submission,
    ),
  ).rejects.toThrow();
});

it("来源撤回保持历史核验但当前不可用，拒绝给不可用理由同时展示可用", async () => {
  const f = await outcomeFixture(),
    ack = await outcomeVerificationAck(f);
  const detail = {
    ...f.detail,
    ...ack,
    package_association: {
      ...f.detail.package_association!,
      available: false,
      reasons: ["package_outcome_source_no_longer_effective"],
    },
  };
  const tag = outcomeVerificationEtag(detail.id, 1),
    head = outcomeHeadEtag(f.submission.id, 1);
  await expect(
    validateOutcomeDetail(detail, f.submission, detail.id, tag, head),
  ).resolves.toMatchObject({
    verification: "verified",
    package_association: { available: false },
  });
  await expect(
    validateOutcomeDetail(
      {
        ...detail,
        package_association: { ...detail.package_association, available: true },
      },
      f.submission,
      detail.id,
      tag,
      head,
    ),
  ).rejects.toThrow();
  await expect(
    validateOutcomeDetail(
      {
        ...detail,
        package_association: {
          ...detail.package_association,
          formal_sample_eligible: true,
        },
      },
      f.submission,
      detail.id,
      tag,
      head,
    ),
  ).rejects.toThrow();
  await expect(
    validateOutcomeDetail(
      detail,
      f.submission,
      detail.id,
      outcomeHeadEtag(f.submission.id, 1),
      head,
    ),
  ).rejects.toThrow();
});

it("仅已知回滚错误可解除待恢复，网络和未知服务错误保留原请求", () => {
  expect(
    definitiveOutcomeFailure(new ApiError("changed", 412, "REVISION_CONFLICT")),
  ).toBe(true);
  expect(
    definitiveOutcomeFailure(
      new ApiError("source", 409, "PACKAGE_OUTCOME_SOURCE_INVALID"),
    ),
  ).toBe(true);
  for (const error of [
    new ApiError("unknown", 422, "PACKAGE_OUTCOME_FUTURE_FAILURE"),
    new ApiError("invalid", 422, "INVALID_REQUEST"),
    new ApiError("network", 0, "NETWORK_ERROR"),
    new ApiError("lost", 500, "PACKAGE_OUTCOME_SOURCE_INVALID"),
    new ApiError("session", 401, "AUTH_REQUIRED"),
    new Error("wrong acknowledgement"),
  ])
    expect(definitiveOutcomeFailure(error)).toBe(false);
});
