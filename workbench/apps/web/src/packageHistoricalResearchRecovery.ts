import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  historySame,
  validateHistoryPending,
  type HistoryPending,
} from "./packageHistoricalResearchProtocol";

function workspaceParts(memberId: string, workspace: string) {
  if (!executionId(memberId))
    throw new Error("历史研究恢复记录缺少有效成员身份。");
  if (workspace === "research") return null;
  const parts = workspace.split(":");
  if (
    parts.length !== 3 ||
    parts[0] !== "admission" ||
    !executionId(parts[1]) ||
    !executionId(parts[2])
  )
    throw new Error("历史准入恢复位置无法核对。");
  return { bidId: parts[1], scopeId: parts[2] };
}
export function historyRecoveryKey(memberId: string, workspace = "research") {
  workspaceParts(memberId, workspace);
  return recordedCommandStorageKey(
    "package-historical-research",
    memberId,
    workspace,
  );
}
function scoped(memberId: string, workspace: string, raw: unknown) {
  const parts = workspaceParts(memberId, workspace),
    pending = validateHistoryPending(raw);
  if (
    parts
      ? pending.kind !== "admission" ||
        pending.expected.bidId !== parts.bidId ||
        pending.expected.scopeId !== parts.scopeId
      : pending.kind === "admission"
  )
    throw new Error("历史研究原请求与当前工作面不符，不能换用另一个请求恢复。");
  return pending;
}
export function readHistoryRecovery(
  memberId: string,
  workspace = "research",
): HistoryPending | null {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(historyRecoveryKey(memberId, workspace));
  } catch {
    throw new Error(
      "浏览器不能读取历史研究恢复记录；请保留页面，暂不能另发新请求。",
    );
  }
  if (raw === null) return null;
  try {
    if (raw.length > 2 * 1024 * 1024) throw new Error();
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "memberId", "workspace", "pending"]) ||
      value.version !== 1 ||
      value.memberId !== memberId ||
      value.workspace !== workspace
    )
      throw new Error();
    return scoped(memberId, workspace, value.pending);
  } catch {
    throw new Error(
      "本地历史研究恢复记录损坏或身份不符。请保留原记录，当前不能另发新请求。",
    );
  }
}
export function writeHistoryRecovery(
  memberId: string,
  workspace: string,
  pending: HistoryPending | null,
) {
  const key = historyRecoveryKey(memberId, workspace);
  if (pending !== null) {
    scoped(memberId, workspace, pending);
    const previous = readHistoryRecovery(memberId, workspace);
    if (previous !== null && !historySame(previous, pending))
      throw new Error(
        "上次历史研究请求尚未取得确认，不能用新的正文、条件或幂等键覆盖；请先恢复原操作。",
      );
  }
  try {
    if (pending === null) sessionStorage.removeItem(key);
    else {
      const text = JSON.stringify({ version: 1, memberId, workspace, pending });
      if (text.length > 2 * 1024 * 1024) throw new Error();
      sessionStorage.setItem(key, text);
    }
  } catch {
    throw new Error(
      "浏览器未能保存历史研究原请求。请保留页面并释放此站点存储空间，再恢复原操作。",
    );
  }
}
