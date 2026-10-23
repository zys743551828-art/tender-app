import { useCallback } from "react";
import type {
  WorkContextBuildSelection,
  WorkContextRelationPage,
  AuthoringWorkContext,
} from "./contracts";
import { ErrorNotice, Loading } from "./components";
import { validateWorkContextRelations } from "./workContextDirectoryProtocol";
import { useWorkContextDirectory } from "./useWorkContextDirectory";
import type { PackageNavigationTarget } from "./packageNavigation";

export function WorkContextBuildRelations({
  selection,
  outputs,
  onOpenPackage,
}: {
  selection: WorkContextBuildSelection;
  outputs: NonNullable<AuthoringWorkContext["build"]>["outputs"];
  onOpenPackage: (target: PackageNavigationTarget) => void;
}) {
  const validate = useCallback(
    (v: unknown) => validateWorkContextRelations(v, selection, outputs),
    [selection, outputs],
  );
  const { page, items, error, busy, load } = useWorkContextDirectory<
    WorkContextRelationPage["items"][number],
    WorkContextRelationPage
  >(
    `/bids/${selection.bid_id}/work-contexts/build/${selection.build_id}/relations?target=package_revision&limit=20`,
    validate,
  );
  return (
    <section className="work-context-original" aria-label="生成文件的入包关系">
      <div className="section-heading">
        <h3>生成文件的入包关系</h3>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void load()}
        >
          重读关联
        </button>
      </div>
      <p className="small-note">
        每条关系依据原生入包凭据或确切输出成员证明。当前可用性需要在目标包工作面重新核对。
      </p>
      {busy && <Loading text="正在核对原生入包关系…" />}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void load()} />
      )}
      {error != null && page && (
        <p className="notice warning">
          本次关联未能更新，下面保留上次读取的记录。
        </p>
      )}
      {page && !items.length && <p>尚未找到这次生成文件的已证明入包关系。</p>}
      <ul className="work-context-choice-list">
        {items.map((r) => (
          <li key={r.id}>
            <div>
              <strong>
                {r.kind === "adopted_into"
                  ? "已通过入包操作采用"
                  : "包修订包含此确切输出"}{" "}
                · 包修订 {r.package_revision_number}
              </strong>
              <p>
                {r.output.format.toUpperCase()} ·{" "}
                {r.current_package_head.status === "changed"
                  ? "目标包已有后续修订"
                  : "这是明确的历史包修订"}
              </p>
            </div>
            <button
              type="button"
              className="button secondary"
              onClick={() =>
                onOpenPackage({
                  packageId: r.package_revision.package_id,
                  revisionId: r.package_revision.revision_id,
                  inventoryId: null,
                })
              }
            >
              打开这版包
            </button>
            <details>
              <summary>关联证明与固定身份</summary>
              <pre>{JSON.stringify(r, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ul>
      {page?.has_more && (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void load(true)}
        >
          显示更多关联
        </button>
      )}
    </section>
  );
}
