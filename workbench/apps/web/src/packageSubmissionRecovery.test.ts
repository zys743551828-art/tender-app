import { beforeEach, expect, it } from "vitest";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  packageSubmissionStorageKey,
  readPackageSubmissionRecovery,
  writePackageSubmissionRecovery,
  type PackageSubmissionRecovery,
} from "./packageSubmissionRecovery";
import {
  submissionFixture,
  submissionScope,
  submissionEtag,
  submissionId as id,
} from "./packageSubmissionFixtures.test-support";
beforeEach(() => sessionStorage.clear());
it("原body/key/tag跨刷新保留且按成员清理", async () => {
  const f = await submissionFixture(),
    record = {
      version: 1 as const,
      scope: submissionScope,
      pending: {
        key: "a".repeat(32),
        body: f.body,
        etag: submissionEtag(),
        supersedesId: null,
      },
      lastId: null,
    };
  writePackageSubmissionRecovery(record);
  expect(readPackageSubmissionRecovery(submissionScope)).toEqual(record);
  expect(
    readPackageSubmissionRecovery({ ...submissionScope, memberId: id(998) })
      .pending,
  ).toBeNull();
  clearRecordedCommands(id(998));
  expect(
    sessionStorage.getItem(packageSubmissionStorageKey(submissionScope)),
  ).toBeNull();
});
it("损坏或换项目的恢复记录不能被当作没有待办", async () => {
  const f = await submissionFixture(),
    record: PackageSubmissionRecovery = {
      version: 1,
      scope: submissionScope,
      pending: {
        key: id(77),
        body: f.body,
        etag: submissionEtag(),
        supersedesId: id(120),
      },
      lastId: null,
    };
  sessionStorage.setItem(
    packageSubmissionStorageKey(submissionScope),
    JSON.stringify(record),
  );
  expect(() => readPackageSubmissionRecovery(submissionScope)).toThrow();
  record.pending!.supersedesId = null;
  record.scope = { ...submissionScope, bidId: id(999) };
  sessionStorage.setItem(
    packageSubmissionStorageKey(submissionScope),
    JSON.stringify(record),
  );
  expect(() => readPackageSubmissionRecovery(submissionScope)).toThrow();
});
it("更正请求保留旧头版本，不接受另一个修订", async () => {
  const f = await submissionFixture(false, {
      id: id(120),
      revision: 3,
      subject_kind: "single_body",
    }),
    record = {
      version: 1 as const,
      scope: submissionScope,
      pending: {
        key: id(77),
        body: f.body,
        etag: submissionEtag(),
        supersedesId: id(120),
      },
      lastId: null,
    };
  writePackageSubmissionRecovery(record);
  expect(
    readPackageSubmissionRecovery(submissionScope).pending?.body.expected_head,
  ).toEqual({ id: id(120), revision: 3 });
  record.pending.body.expected_head!.id = id(121);
  writePackageSubmissionRecovery(record);
  expect(() => readPackageSubmissionRecovery(submissionScope)).toThrow();
});
