import { useState, type ReactNode } from "react";
import { supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type { BidPackageStoredView } from "./contracts";
import {
  TechnicalDraftContext,
  verifyTechnicalHandoff,
} from "./technicalAuthoringHandoff";
import { useResource } from "./useResource";

export function PackageTechnicalDraftHandoff({
  packageView,
  children,
  disabled = false,
}: {
  packageView: BidPackageStoredView;
  children: ReactNode;
  disabled?: boolean;
}) {
  const m = packageView.manifest;
  const path = `/bids/${m.scope.bid_id}/packages/${m.package_id}/revisions/${m.revision_id}/technical-authoring-handoff`;
  const [read, setRead] = useState(false);
  const supported = supportsApi("GET", path);
  const resource = useResource<unknown>(
    read && supported && !disabled ? path : null,
  );
  const verified =
    read && !disabled && !resource.loading && !resource.error
      ? verifyTechnicalHandoff(resource.data, packageView)
      : null;
  const focus = verified?.record
    ? { ...verified, record: verified.record }
    : null;
  return (
    <TechnicalDraftContext.Provider value={focus}>
      {supported && (
        <section
          className="package-review__human-controls"
          aria-label="技术稿内部审阅进度"
        >
          <h4>技术稿内部审阅进度</h4>
          <p className="small-note">
            读取本修订的直接采用回执。不会取最新修订、发起核查、批准或提交文件。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={disabled || resource.loading}
            onClick={() => (read ? void resource.reload() : setRead(true))}
          >
            {resource.loading
              ? "正在核对本修订…"
              : read
                ? "重新核对技术稿交接"
                : "读取技术稿交接"}
          </button>
          {resource.error != null && (
            <ErrorNotice
              error={resource.error}
              onRetry={() => void resource.reload()}
            />
          )}
          {resource.data !== undefined &&
            !resource.loading &&
            !resource.error &&
            !verified && (
              <p role="alert">
                交接响应与本修订的文件身份不符，未展示其他记录。
              </p>
            )}
          {verified && (
            <div role="status" className="small-note">
              <p>
                {verified.revision_status === "historical"
                  ? "这不是当前包修订。只显示历史记录，不继承到新修订。"
                  : "读取时是当前包修订；不代表来源和文件仍符合现行要求。"}
              </p>
              {focus ? (
                <>
                  <p>
                    {focus.record.format === "docx" ? "Word" : "PDF"}{" "}
                    已生成，并明确采用到第 {m.revision} 版。{" "}
                    {focus.record.parse_run_id
                      ? "回执可对应本修订冻结的解析。"
                      : "采用时未冻结解析与页范围，逐条审阅仍待准备。"}
                  </p>
                  <details>
                    <summary>核对本次文件与草稿快照身份</summary>
                    <p>
                      构建编号：<code>{focus.record.build_id}</code>
                    </p>
                    <p>
                      文件版本：<code>{focus.record.document_version_id}</code>
                    </p>
                    <p>
                      采用时记录的文件 SHA-256：
                      <code>{focus.record.artifact_sha256}</code>
                    </p>
                    <p>
                      草稿快照：<code>{focus.record.snapshot_id}</code>
                    </p>
                    <p>
                      草稿快照摘要：<code>{focus.record.snapshot_digest}</code>
                    </p>
                  </details>
                  <p>
                    继续在下方选择本修订的要求清单。已读回执不代表机器检查或独立批准。
                  </p>
                </>
              ) : (
                <p>
                  未找到这版直接采用的生成技术稿回执；不沿用其他修订的记录。
                </p>
              )}
              <p>正式独立审批与候选件下载尚未开放。</p>
            </div>
          )}
        </section>
      )}
      {children}
    </TechnicalDraftContext.Provider>
  );
}
