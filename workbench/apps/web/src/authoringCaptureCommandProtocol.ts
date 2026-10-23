import { ApiError, type ApiResult } from "./api";
import type { PackageAuthoringInputRequest } from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalSame as same } from "./historicalImportProtocol";
import {
  validateAuthoringInput,
  validateAuthoringInputRequest,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";
import { recordedCommandStorageKey } from "./recordedCommandStorage";

export type CaptureCommandScope = { memberId: string; bidId: string };
export type CaptureRequest = {
  method: "POST";
  path: string;
  etag: "";
  key: string;
  body: PackageAuthoringInputRequest;
};
export type CaptureRecovery = {
  version: 1;
  scope: CaptureCommandScope;
  state: "pending" | "rejected";
  request: CaptureRequest;
  request_digest: string;
};
export const captureRequestPath = (bid: string) =>
  `/bids/${bid}/authoring/package-inputs`;
export function captureCommandKey(scope: CaptureCommandScope) {
  if (!uuid(scope.memberId) || !uuid(scope.bidId))
    throw new Error("保存范围缺少明确成员和项目身份。");
  return recordedCommandStorageKey(
    "authoring-package-capture",
    scope.memberId,
    scope.bidId,
  );
}
export function readCaptureRecovery(
  raw: string,
  scope: CaptureCommandScope,
): CaptureRecovery {
  try {
    if (new TextEncoder().encode(raw).length > 2 * 1024 * 1024)
      throw new Error();
    const value: unknown = JSON.parse(raw);
    if (
      !object(value) ||
      !exactKeys(value, [
        "version",
        "scope",
        "state",
        "request",
        "request_digest",
      ]) ||
      value.version !== 1 ||
      !same(value.scope, scope) ||
      !["pending", "rejected"].includes(String(value.state)) ||
      !sha(value.request_digest) ||
      !object(value.request)
    )
      throw new Error();
    const request = value.request;
    if (
      !exactKeys(request, ["method", "path", "etag", "key", "body"]) ||
      request.method !== "POST" ||
      request.path !== captureRequestPath(scope.bidId) ||
      request.etag !== "" ||
      !uuid(request.key)
    )
      throw new Error();
    validateAuthoringInputRequest(request.body);
    captureCommandKey(scope);
    return value as unknown as CaptureRecovery;
  } catch {
    throw new Error(
      "采集保存的恢复记录损坏或成员、项目、原请求不符；已暂停新保存，请保留记录并核对已保存目录。",
    );
  }
}
export async function verifyCaptureRecovery(value: CaptureRecovery) {
  readCaptureRecovery(JSON.stringify(value), value.scope);
  if (
    (await jsonDigest({ scope: value.scope, request: value.request })) !==
    value.request_digest
  )
    throw new Error("采集原请求摘要不符，未发送或清除恢复记录。");
  return value;
}
export async function validateCaptureAck(
  result: ApiResult<unknown>,
  recovery: CaptureRecovery,
): Promise<VerifiedAuthoringInput> {
  await verifyCaptureRecovery(recovery);
  const input = await validateAuthoringInput(result.data, recovery.scope.bidId);
  if (
    result.etag !== null ||
    input.manifest.actor_id !== recovery.scope.memberId ||
    !same(input.manifest.selection, recovery.request.body)
  )
    throw new Error(
      "保存回执没有绑定本成员的完整原请求；记录保留，可继续恢复原请求。",
    );
  return input;
}
/** These named pre-write stale observations are the only definitive rejection cases.
 * Authentication, integrity, idempotency, unknown 4xx and transport failures keep the key. */
export function captureDefinitelyRejected(error: unknown) {
  return (
    error instanceof ApiError &&
    !error.retryable &&
    error.status === 409 &&
    [
      "AUTHORING_PACKAGE_DRAFT_CHANGED",
      "AUTHORING_PACKAGE_SECTION_CHANGED",
      "AUTHORING_PACKAGE_FACT_HEAD_CHANGED",
      "AUTHORING_PACKAGE_INVENTORY_CHANGED",
      "AUTHORING_PACKAGE_RULES_CHANGED",
      "AUTHORING_PACKAGE_IDENTITY_CHANGED",
      "PROJECT_WORK_CLOSED",
    ].includes(error.code)
  );
}
