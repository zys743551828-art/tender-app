import { useState } from "react";
import { supportsApi } from "./api";
import type { UploadBatchView } from "./contracts";
import type { UploadBatchPage } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";

const states: Record<UploadBatchView["state"], string> = {
  open: "待上传或待确认",
  verifying: "正在核验",
  committed: "已入库",
  failed: "处理失败",
};
export function UploadBatchDiscovery({
  bidId,
  currentId,
  disabled,
  hasUnsentFiles,
  onSelect,
}: {
  bidId: string;
  currentId: string | null;
  disabled: boolean;
  hasUnsentFiles: boolean;
  onSelect: (batch: UploadBatchView) => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<UploadBatchView["state"]>("open");
  const path = `/bids/${bidId}/upload-batches`;
  const batches = useDirectory<UploadBatchPage>(
    open ? `${path}?state=${state}&limit=20` : null,
  );
  if (!supportsApi("GET", path)) return null;
  return (
    <div className="upload-batch-discovery">
      <button
        className="text-button"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((old) => !old)}
      >
        {open ? "收起其他批次" : "查找本项目已保存的上传批次"}
      </button>
      {open && (
        <>
          <p className="small-note">
            更换浏览器也可从项目已保存批次接续；核验与入库分别确认。切换批次会收起已授权原件的本地选择，服务器已收到的内容保留，补传可重新选择原文件。
          </p>
          <label>
            批次状态
            <select
              aria-label="查找批次状态"
              value={state}
              disabled={disabled}
              onChange={(event) =>
                setState(event.target.value as UploadBatchView["state"])
              }
            >
              {Object.entries(states).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <ResourceState
            {...batches}
            hasData={!!batches.data}
            onRetry={() => void batches.reload()}
          />
          {hasUnsentFiles && (
            <p className="notice warning">
              有尚未开始传输的本地文件，请先上传或移除这些选择，再切换批次。
            </p>
          )}
          {batches.data && !batches.items.length && (
            <p className="small-empty">
              当前状态没有可读批次；不会创建替代批次或假装已完成。
            </p>
          )}
          <div className="batch-choices">
            {batches.items.map((batch) =>
              batch.bid_id === bidId ? (
                <article key={batch.id}>
                  <div>
                    <Badge>{states[batch.state]}</Badge>
                    <strong>
                      {batch.uploads.length}份原件 · 批次 {batch.id.slice(0, 8)}
                    </strong>
                    <p className="small-note">
                      {batch.uploads.length
                        ? batch.uploads
                            .map((upload) => upload.filename)
                            .join("、")
                        : "尚未添加原件"}
                    </p>
                    <p className="small-note">
                      已核验
                      {
                        batch.uploads.filter(
                          (upload) => upload.state === "verified",
                        ).length
                      }
                      份；待接续
                      {
                        batch.uploads.filter(
                          (upload) => upload.state === "authorized",
                        ).length
                      }
                      份
                    </p>
                  </div>
                  <button
                    className="button secondary"
                    disabled={
                      disabled || hasUnsentFiles || currentId === batch.id
                    }
                    onClick={() => onSelect(batch)}
                  >
                    {currentId === batch.id
                      ? "当前查看批次"
                      : batch.state === "committed"
                        ? "查看此批入库记录"
                        : "切换到此批次继续核对"}
                  </button>
                </article>
              ) : (
                <p className="notice error" key={batch.id}>
                  批次项目身份不一致，未提供接续。
                </p>
              ),
            )}
          </div>
          {batches.hasMore && (
            <button
              className="text-button"
              disabled={batches.moreBusy}
              onClick={() => void batches.loadMore()}
            >
              {batches.moreBusy ? "正在读取批次…" : "加载更多批次"}
            </button>
          )}
          <ErrorNotice
            error={batches.moreError}
            onRetry={() => void batches.loadMore()}
          />
        </>
      )}
    </div>
  );
}
