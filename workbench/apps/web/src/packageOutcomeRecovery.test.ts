import { beforeEach, expect, it } from "vitest";
import {
  outcomeFixture,
  outcomeId as id,
} from "./packageOutcomeFixtures.test-support";
import {
  packageOutcomeStorageKey,
  readOutcomeRecovery,
  writeOutcomeRecovery,
} from "./packageOutcomeRecovery";
import { clearRecordedCommands } from "./recordedCommandStorage";
import type { PendingPackageOutcome } from "./packageOutcomeProtocol";
beforeEach(() => sessionStorage.clear());

it("原命令完整保留且绑定成员、实交及不可变包摘要，损坏记录不静默重置", async () => {
  const f = await outcomeFixture();
  const p: PendingPackageOutcome = {
    kind: "register",
    key: id(700),
    baseId: null,
    etag: null,
    body: f.body,
  };
  writeOutcomeRecovery(f.scope, p);
  expect(readOutcomeRecovery(f.scope, f.submission)).toEqual(p);
  expect(() =>
    readOutcomeRecovery(
      { ...f.scope, bindingDigest: "0".repeat(64) },
      f.submission,
    ),
  ).toThrow();
  sessionStorage.setItem(packageOutcomeStorageKey(f.scope), "{broken");
  expect(() => readOutcomeRecovery(f.scope, f.submission)).toThrow();
});

it("退出只清理已登记的成员业务恢复，保留其它成员与无关存储", async () => {
  const f = await outcomeFixture();
  const p: PendingPackageOutcome = {
    kind: "register",
    key: id(700),
    baseId: null,
    etag: null,
    body: f.body,
  };
  const other = { ...f.scope, memberId: id(888) };
  writeOutcomeRecovery(f.scope, p);
  writeOutcomeRecovery(other, p);
  sessionStorage.setItem("unrelated", "keep");
  clearRecordedCommands(other.memberId);
  expect(readOutcomeRecovery(f.scope, f.submission)).toBeNull();
  expect(readOutcomeRecovery(other, f.submission)).toEqual(p);
  expect(sessionStorage.getItem("unrelated")).toBe("keep");
  clearRecordedCommands();
  expect(readOutcomeRecovery(other, f.submission)).toBeNull();
});
