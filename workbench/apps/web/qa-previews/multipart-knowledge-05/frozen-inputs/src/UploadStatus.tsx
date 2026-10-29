import { useEffect, useRef, useState } from "react";
import type { Accepted, UploadPartsView, UploadLayoutView } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { api, ApiError, commandKey } from "./api";
import {
  observedUpload,
  pendingUploadCompletion,
  replayUploadCompletion,
  rebaseUploadCompletion,
  finishObservedUpload,
} from "./uploadTransport";

export function UploadStatus({
  uploadId,
  hasLocalFile,
  disabled,
  onWorking,
  onAccepted,
}: {
  uploadId: string;
  hasLocalFile: boolean;
  disabled: boolean;
  onWorking: (busy: boolean) => void;
  onAccepted: (accepted: Accepted) => void;
}) {
  const [open, setOpen] = useState(false);
  const [parts, setParts] = useState<UploadPartsView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [layout, setLayout] = useState<UploadLayoutView | null>(null);
  const [reading, setReading] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [errorAction, setErrorAction] = useState<
    "inspect" | "replay" | "finish"
  >("inspect");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const pending = pendingUploadCompletion(uploadId);
  async function inspect() {
    if (reading) return;
    setOpen(true);
    setErrorAction("inspect");
    setReading(true);
    setError(null);
    try {
      const state = await observedUpload(uploadId);
      if (active.current) setParts(state.parts);
      try {
        const result = await api<UploadLayoutView>(
          `/uploads/${uploadId}/layout`,
        );
        if (result.data.upload_id !== uploadId)
          throw new Error("布局与上传身份不一致，未声明完成。");
        if (active.current) setLayout(result.data);
      } catch (failure) {
        if (
          !(
            failure instanceof ApiError &&
            failure.code === "SERVICE_VERSION_NOT_READY"
          )
        )
          throw failure;
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setReading(false);
    }
  }
  const allReceived =
    !!layout &&
    !!parts &&
    layout.part_count === parts.completed_parts.length &&
    parts.completed_parts.reduce((sum, part) => sum + part.byte_size, 0) ===
      layout.byte_size;
  async function finish() {
    if (!layout || disabled || replaying) return;
    setReplaying(true);
    setErrorAction("finish");
    onWorking(true);
    setError(null);
    try {
      const result = await finishObservedUpload(
        layout,
        commandKey(`observed-complete:${uploadId}`, {
          sha: layout.declared_sha256,
          size: layout.byte_size,
        }),
      );
      onAccepted(result);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      onWorking(false);
      if (active.current) setReplaying(false);
    }
  }
  async function replay(rebase = false) {
    if (disabled || replaying) return;
    setReplaying(true);
    setOpen(true);
    setErrorAction("replay");
    onWorking(true);
    setError(null);
    try {
      const result = await (rebase
        ? rebaseUploadCompletion(uploadId)
        : replayUploadCompletion(uploadId));
      onAccepted(result);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      onWorking(false);
      if (active.current) setReplaying(false);
    }
  }
  return (
    <div className="upload-recovery-status">
      <div className="review-shortcuts">
        <button
          className="text-button"
          disabled={reading || replaying}
          onClick={() => void inspect()}
        >
          {reading ? "正在查询存储已收到内容…" : "查询已收到的传输状态"}
        </button>
        {pending && (
          <button
            className="button secondary"
            disabled={disabled || replaying}
            onClick={() => void replay()}
          >
            {replaying ? "正在核对原完成请求…" : "核对上传完成受理结果"}
          </button>
        )}
      </div>
      {pending && (
        <p className="small-note">
          原件完整清单已提交，但受理响应尚未确认。此处会重放原请求，不新建上传，也不改用新稿。
        </p>
      )}
      {open && (
        <>
          <ErrorNotice
            error={error}
            onRetry={() => {
              if (errorAction === "inspect") void inspect();
              else if (errorAction === "finish") void finish();
              else void replay();
            }}
          />
          {error instanceof ApiError && error.status === 412 && pending && (
            <div className="notice warning">
              <div>
                <p>
                  原完成声明已被旧状态拒绝，已收到的分片保留。可以读取当前服务器回执并按新基准重新核对完成，不重传整批。
                </p>
                <button
                  className="button secondary"
                  disabled={disabled || replaying}
                  onClick={() => void replay(true)}
                >
                  按当前回执重新核对完成
                </button>
              </div>
            </div>
          )}
          {parts && (
            <div className="transfer-observation">
              <Badge>
                {parts.mode === "multipart" ? "分片传输" : "单文件传输"}
              </Badge>
              <p className="small-note">
                存储已收到 {parts.completed_parts.length}{" "}
                {parts.mode === "multipart" ? "片" : "份文件"}
                {layout
                  ? `／共${layout.part_count}${parts.mode === "multipart" ? "片" : "份"}`
                  : ""}
                ，合计{" "}
                {parts.completed_parts
                  .reduce((sum, part) => sum + part.byte_size, 0)
                  .toLocaleString("zh-CN")}{" "}
                字节。这是传输观测，不表示原件已通过完整摘要核验或已入库。
              </p>
              {parts.completed_parts.length > 0 && (
                <p className="small-note">
                  已收到片号：
                  {parts.completed_parts
                    .map((part) => part.part_number)
                    .join("、")}
                </p>
              )}
            </div>
          )}
          {allReceived && !pending && layout?.state === "authorized" && (
            <button
              className="button secondary"
              disabled={disabled || replaying}
              onClick={() => void finish()}
            >
              按完整已收内容提交原件核验
            </button>
          )}
          {!hasLocalFile && (
            <p className="small-note">
              {allReceived
                ? "完整内容已经收到，可以直接按服务器原声明提交核验；核验通过与入库仍分别记录。"
                : "本页尚未选择此原文件。已收到的内容会保留；补传前需重新选择原文件，核对大小及完整SHA摘要后只补缺片。"}
            </p>
          )}
        </>
      )}
    </div>
  );
}
