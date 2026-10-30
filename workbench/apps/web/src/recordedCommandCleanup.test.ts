import { beforeEach, expect, it } from "vitest";
import { clearRecordedCommands } from "./useRecordedCommand";
import { executionStorageKey } from "./executionInputRecovery";
import { factScopeStorageKey } from "./factScopeRecovery";
import { dependencyPlanStorageKey } from "./dependencyPlanRecovery";
import { factChangeStorageKey } from "./factChangeRecovery";
import { freezeStorageKey } from "./packageFrozenInput";

const scope = {
  memberId: "member-a",
  bidId: "bid",
  packageId: "package",
  revisionId: "revision",
  inventoryId: "inventory",
  frozenId: "frozen",
  frozenDigest: "a".repeat(64),
  inputDigest: "b".repeat(64),
  evidenceDigest: "c".repeat(64),
  preparedId: "prepared",
  preparedDigest: "d".repeat(64),
};
const recoveryKeys = [
  ["执行准备", executionStorageKey],
  ["事实范围", factScopeStorageKey],
  ["依赖计划", dependencyPlanStorageKey],
  ["事实确认", factChangeStorageKey],
  ["冻结输入", freezeStorageKey],
] as const;

beforeEach(() => sessionStorage.clear());

it.each(recoveryKeys)(
  "%s恢复记录在同账号登录时保留，切换或退出时清除",
  (_, key) => {
    const own = key(scope);
    const other = key({ ...scope, memberId: "member-b" });
    const pending = JSON.stringify({
      pending: { body: { reason: "待确认的业务理由" } },
    });
    sessionStorage.setItem(own, pending);
    sessionStorage.setItem(other, pending);

    clearRecordedCommands(scope.memberId);
    expect(sessionStorage.getItem(own)).toBe(pending);
    expect(sessionStorage.getItem(other)).toBeNull();

    clearRecordedCommands();
    expect(sessionStorage.getItem(own)).toBeNull();
  },
);

it("退出同时清理新增操作的幂等键和损坏恢复记录，不依赖JSON可解析", () => {
  const keys = [
    executionStorageKey,
    factScopeStorageKey,
    dependencyPlanStorageKey,
  ].flatMap((key) => {
    const record = key(scope);
    return [
      record,
      record.replace("tender:command-record:", "tender:command:"),
    ];
  });
  for (const key of keys) sessionStorage.setItem(key, "{damaged");

  clearRecordedCommands();

  for (const key of keys) expect(sessionStorage.getItem(key)).toBeNull();
});

it("清理限定为已登记的成员命令，不删除偏好、未知命名空间或相似前缀", () => {
  const retained = [
    "tender:theme",
    "other-app:command-record:fact-scope:member-a:bid",
    "tender:command-record:unknown-kind:member-a:bid",
    "tender:command-record:fact-scope-extra:member-a:bid",
    "tender:command-record:fact-scope:member-a",
  ];
  for (const key of retained) sessionStorage.setItem(key, "keep");
  sessionStorage.setItem("tender:command:report:member-b:bid:review", "old");

  clearRecordedCommands();

  expect(
    sessionStorage.getItem("tender:command:report:member-b:bid:review"),
  ).toBeNull();
  for (const key of retained) expect(sessionStorage.getItem(key)).toBe("keep");
});

it("lifecycle recovery and idempotency keys follow the existing account cleanup policy", () => {
  const own = "tender:command-record:lifecycle:member-a:bid";
  const other = "tender:command-record:lifecycle:member-b:bid";
  const key = own.replace("command-record", "command");
  for (const name of [own, other, key])
    sessionStorage.setItem(name, "private reason");
  clearRecordedCommands("member-a");
  expect(sessionStorage.getItem(own)).toBe("private reason");
  expect(sessionStorage.getItem(key)).toBe("private reason");
  expect(sessionStorage.getItem(other)).toBeNull();
  clearRecordedCommands();
  expect(sessionStorage.getItem(own)).toBeNull();
  expect(sessionStorage.getItem(key)).toBeNull();
});
