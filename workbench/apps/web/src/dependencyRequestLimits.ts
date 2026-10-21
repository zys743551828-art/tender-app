import type {
  CheckPackageInputDependencies,
  SavePackageDependencyPlan,
} from "./contracts";

export const MAX_DEPENDENCY_DECLARATIONS = 10000;
export const MAX_DEPENDENCY_BODY_BYTES = 4 * 1024 * 1024;
const MAX_DEPENDENCY_RECOVERY_BYTES = 5 * 1024 * 1024;

/** Sending policy only: historical body/receipt integrity has no new byte cap. */
export function assertDependencyRequestFits(
  body: CheckPackageInputDependencies | SavePackageDependencyPlan,
  recover = false,
) {
  const size = new TextEncoder().encode(JSON.stringify(body)).byteLength;
  const maximum = recover
    ? MAX_DEPENDENCY_RECOVERY_BYTES
    : MAX_DEPENDENCY_BODY_BYTES;
  if (size > maximum)
    throw new Error(
      recover
        ? "原保存请求超过 5 MiB，未发送恢复请求；原请求仍保留，请通过已保存计划核对原回执。"
        : "本轮请求超过 4 MiB，未发送。请缩短标注说明后重试；本轮草稿仍保留。",
    );
}
