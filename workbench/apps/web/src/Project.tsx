import { DocumentRelationNotice } from "./DocumentRelationNotice";
import { sameUploadFormat, uploadMediaType } from "./uploadFormats";
import { WordOriginals } from "./WordOriginals";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";
import {
  api,
  ApiError,
  commandKey,
  fileSha256,
  parseNames,
  roleNames,
  sizeLabel,
} from "./api";
import type {
  Accepted,
  Bid,
  DocumentView,
  MaterialView,
  Operation,
  UploadBatchView,
  UploadBindingView,
  UploadGrant,
  UploadRequest,
  UploadTarget,
  UploadView,
  UploadLayoutView,
} from "./contracts";
import { Badge, ErrorNotice, Icon, Loading } from "./components";
import { Evidence } from "./Evidence";
import { HistoryPanel } from "./HistoryPanel";
import { rememberOperation } from "./operationStorage";
import {
  finishObservedUpload,
  observedUpload,
  pendingUploadCompletion,
  replayUploadCompletion,
  transferUpload,
} from "./uploadTransport";
import { UploadStatus } from "./UploadStatus";
import { UploadBatchDiscovery } from "./UploadBatchDiscovery";
import { BidPackages } from "./BidPackages";

type DraftFile = {
  key: string;
  file: File;
  role: UploadRequest["role"] | null;
  target: string;
  state: string;
  error?: unknown;
  grant?: UploadGrant;
  digest?: string;
  completeKey?: string;
  uploadKey: string;
  declaredSource?: string;
};
const uploadNames: Record<string, string> = {
  authorized: "等待上传",
  uploaded: "原件已收到",
  verifying: "正在核验原件",
  verified: "原件已核验，待入库",
  quarantined: "核验未通过",
  expired: "上传已过期",
  aborted: "上传已取消",
};
const operationNames: Record<string, string> = {
  queued: "等待处理",
  running: "正在处理",
  cancel_requested: "正在取消",
  succeeded: "处理已完成",
  failed: "处理失败",
  cancelled: "已取消",
};
function batchStorageKey(id: string) {
  return `tender:batch:${id}`;
}

export function Project({
  id,
  memberId = "current",
  onBack,
  navigation,
  reviewNotice,
}: {
  id: string;
  memberId?: string;
  onBack: () => void;
  navigation?: ReactNode;
  reviewNotice?: ReactNode;
}) {
  const [bid, setBid] = useState<Bid | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [materials, setMaterials] = useState<MaterialView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [batchId, setBatchId] = useState<string | null>(() =>
    localStorage.getItem(batchStorageKey(id)),
  );
  const [batch, setBatch] = useState<UploadBatchView | null>(null);
  const [files, setFiles] = useState<DraftFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [partial, setPartial] = useState(false);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [selected, setSelected] = useState<DocumentView | null>(null);
  const [historyHead, setHistoryHead] = useState<DocumentView | null>(null);
  const closeEvidence = useCallback(() => setSelected(null), []);
  const [conflict, setConflict] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const active = useRef(true);
  const uploadGeneration = useRef(0);
  const transport = useRef<AbortController | null>(null);
  const readGeneration = useRef(0);
  const batchGeneration = useRef(0);
  const invalidateTransfers = useCallback(() => {
    uploadGeneration.current++;
    readGeneration.current++;
    batchGeneration.current++;
    transport.current?.abort();
  }, []);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      invalidateTransfers();
    };
  }, [invalidateTransfers]);
  const pendingCommit = useRef<{
    signature: string;
    etag: string | null;
    key: string;
  } | null>(null);
  const load = useCallback(async () => {
    const generation = ++readGeneration.current;
    const [project, view] = await Promise.all([
      api<Bid>(`/bids/${id}`),
      api<MaterialView>(`/bids/${id}/materials`),
    ]);
    if (!active.current || generation !== readGeneration.current) return;
    setBid(project.data);
    setEtag(project.etag);
    setMaterials(view.data);
  }, [id]);
  const refreshBatch = useCallback(async () => {
    if (!batchId) return;
    const generation = ++batchGeneration.current;
    const { data } = await api<UploadBatchView>(
      `/bids/${id}/upload-batches/${batchId}`,
    );
    if (active.current && generation === batchGeneration.current)
      setBatch(data);
  }, [id, batchId]);
  useEffect(() => {
    void load().catch(setError);
  }, [load]);
  useEffect(() => {
    let active = true;
    const poll = async () => {
      if (!active) return;
      try {
        await refreshBatch();
        await load();
      } catch (e) {
        if (active) setError(e);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [load, refreshBatch]);
  useEffect(() => {
    if (
      !operation ||
      !["queued", "running", "cancel_requested"].includes(operation.state)
    )
      return;
    const timer = window.setInterval(() => {
      void api<Operation>(`/operations/${operation.id}`)
        .then(({ data }) => setOperation(data))
        .catch(setError);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [operation]);
  function patchFile(key: string, patch: Partial<DraftFile>) {
    if (!active.current) return;
    setFiles((old) =>
      old.map((file) => (file.key === key ? { ...file, ...patch } : file)),
    );
  }
  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const added = Array.from(event.target.files ?? []).map(
      (file): DraftFile => ({
        key: crypto.randomUUID(),
        uploadKey: crypto.randomUUID(),
        file,
        role: "tender",
        target: "",
        state: "待上传",
      }),
    );
    setFiles((old) => [...old, ...added]);
    event.target.value = "";
  }
  async function upload() {
    if (transport.current && !transport.current.signal.aborted) return;
    const generation = ++uploadGeneration.current;
    const controller = new AbortController();
    transport.current = controller;
    const currentRun = () =>
      active.current && uploadGeneration.current === generation;
    setBusy(true);
    setError(null);
    try {
      let currentBatch = batch?.state === "committed" ? null : batchId;
      for (const item of files.filter((file) => file.state !== "已提交核验")) {
        if (!currentRun()) return;
        try {
          uploadMediaType(item.file.name);
          if (item.file.size === 0 || item.file.size > 100 * 1024 * 1024)
            throw new Error("单文件需大于0且不超过100 MiB，请拆分后上传。");
          patchFile(item.key, { state: "正在核对文件…", error: undefined });
          const digest = item.digest ?? (await fileSha256(item.file));
          if (!currentRun()) return;
          patchFile(item.key, { digest });
          if (!currentBatch) {
            const { data } = await api<UploadBatchView>(
              `/bids/${id}/upload-batches`,
              {
                method: "POST",
                body: {},
                key: commandKey(`batch:create:${id}`, { after: batchId }),
              },
            );
            if (!currentRun()) return;
            currentBatch = data.id;
            setBatchId(data.id);
            setBatch(data);
            localStorage.setItem(batchStorageKey(id), data.id);
          }
          const targetDoc = materials?.documents.find(
            (document) => document.file_id === item.target,
          );
          const target: UploadTarget = targetDoc
            ? {
                kind: "new_version",
                file_id: targetDoc.file_id,
                expected_file_revision: targetDoc.file_head_revision,
              }
            : { kind: "new_file" };
          if (!item.grant && !item.role)
            throw new Error(
              "新上传需明确资料用途；已建上传的用途与目标保持固定。",
            );
          const request: UploadRequest | null = item.grant
            ? null
            : {
                batch_id: currentBatch,
                role: item.role!,
                filename: item.file.name,
                byte_size: item.file.size,
                declared_sha256: digest,
                target,
                ...(item.declaredSource
                  ? { declared_source_document_version_id: item.declaredSource }
                  : {}),
              };
          const grant =
            item.grant ??
            (
              await api<UploadGrant>(`/bids/${id}/uploads`, {
                method: "POST",
                body: request,
                key: item.uploadKey,
              })
            ).data;
          const completeKey = item.completeKey ?? crypto.randomUUID();
          if (!currentRun()) return;
          sessionStorage.setItem(
            `tender:upload:${grant.upload_id}`,
            JSON.stringify({
              digest,
              role: item.role,
              target: item.target,
              uploadKey: item.uploadKey,
              completeKey,
              filename: item.file.name,
              declaredSource: item.declaredSource,
              byteSize: item.file.size,
              cachedGrant: { ...grant, upload_url: null, parts: [] },
            }),
          );
          patchFile(item.key, { grant, completeKey, state: "正在上传原件…" });
          const data = await transferUpload({
            file: item.file,
            initialGrant: grant,
            digest,
            key: completeKey,
            signal: controller.signal,
            isCurrent: currentRun,
            onProgress: (progress) => {
              const label =
                progress.phase === "completing"
                  ? "正在提交完整原件核验…"
                  : progress.mode === "multipart"
                    ? `分片传输：服务端已收到 ${progress.receivedParts}/${progress.totalParts} 片`
                    : progress.phase === "transferring"
                      ? "正在传输原件…"
                      : "正在核对已收到的原件…";
              if (currentRun()) patchFile(item.key, { state: label });
            },
          });
          if (!currentRun()) return;
          setOperation(data.operation);
          rememberOperation(id, data.operation.id);
          patchFile(item.key, { state: "已提交核验", error: undefined });
        } catch (e) {
          if (!currentRun()) return;
          patchFile(item.key, { state: "此文件未完成", error: e });
        }
      }
      await refreshBatch();
    } catch (e) {
      if (currentRun()) setError(e);
    } finally {
      if (currentRun()) {
        setBusy(false);
        transport.current = null;
      }
    }
  }
  async function resumeUpload(upload: UploadView, file: File) {
    setBusy(true);
    setError(null);
    try {
      const saved = JSON.parse(
        sessionStorage.getItem(`tender:upload:${upload.id}`) ?? "null",
      ) as {
        digest: string;
        role: UploadRequest["role"] | null;
        target: string;
        uploadKey: string;
        declaredSource?: string;
        completeKey: string;
        filename: string;
        byteSize: number;
        cachedGrant?: UploadGrant;
      } | null;
      let layout: UploadLayoutView | null = null;
      try {
        layout = (await api<UploadLayoutView>(`/uploads/${upload.id}/layout`))
          .data;
        if (layout.upload_id !== upload.id || layout.bid_id !== id)
          throw new Error(
            "传输布局与当前项目或文件身份不一致，未接续其他原件。",
          );
      } catch (failure) {
        if (
          !(
            failure instanceof ApiError &&
            failure.code === "SERVICE_VERSION_NOT_READY" &&
            saved?.cachedGrant
          )
        )
          throw failure;
      }
      const digest = await fileSha256(file);
      if (!active.current) return;
      if (
        file.size !== (layout?.byte_size ?? saved?.byteSize) ||
        digest !== (layout?.declared_sha256 ?? saved?.digest)
      )
        throw new Error(
          "所选文件与本次上传的原件大小或完整摘要不同。请选择原文件；修改稿请作为新版本上传。",
        );
      const completeKey = saved?.completeKey ?? crypto.randomUUID();
      if (pendingUploadCompletion(upload.id)) {
        const accepted = await replayUploadCompletion(upload.id);
        if (!active.current) return;
        setOperation(accepted.operation);
        rememberOperation(id, accepted.operation.id);
        await refreshBatch();
        return;
      }
      let grant = saved?.cachedGrant;
      if (layout) {
        const current = await observedUpload(upload.id);
        if (!active.current) return;
        if (current.view.state !== "authorized") {
          await refreshBatch();
          return;
        }
        const present = new Set(
          current.parts.completed_parts.map((part) => part.part_number),
        );
        const missing = Array.from(
          { length: layout.part_count },
          (_, index) => index + 1,
        ).filter((number) => !present.has(number));
        if (!missing.length) {
          const accepted = await finishObservedUpload(layout, completeKey);
          if (!active.current) return;
          setOperation(accepted.operation);
          rememberOperation(id, accepted.operation.id);
          await refreshBatch();
          return;
        }
        grant = (
          await api<UploadGrant>(`/uploads/${upload.id}/authorizations`, {
            method: "POST",
            etag: current.etag,
            body: { part_numbers: missing.slice(0, 128) },
          })
        ).data;
      }
      if (!active.current) return;
      if (!grant || grant.upload_id !== upload.id)
        throw new Error(
          "本次传输授权尚不能恢复。已收到的内容保留，请查询当前状态后重试。",
        );
      const restored: DraftFile = {
        key: crypto.randomUUID(),
        file,
        role: saved?.role ?? null,
        target: saved?.target ?? "",
        declaredSource: saved?.declaredSource,
        uploadKey: saved?.uploadKey ?? crypto.randomUUID(),
        completeKey,
        digest,
        grant,
        state: "待接续上传",
      };
      setFiles((old) => [
        ...old.filter((item) => item.grant?.upload_id !== upload.id),
        restored,
      ]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function commit() {
    if (!batch) return;
    setBusy(true);
    setError(null);
    setConflict(false);
    const verified = batch.uploads.filter(
      (upload) => upload.state === "verified",
    );
    const body = {
      accepted_upload_ids: verified.map((upload) => upload.id),
      accepted_binding_ids: verified.map((upload) => upload.binding_id),
      explicit_partial_acceptance: partial,
    };
    const signature = JSON.stringify(body);
    if (pendingCommit.current?.signature !== signature) {
      pendingCommit.current = {
        signature,
        etag,
        key: commandKey(`batch:commit:${batch.id}`, { body, etag }),
      };
    }
    try {
      const { data } = await api<Accepted>(
        `/bids/${id}/upload-batches/${batch.id}/commit`,
        {
          method: "POST",
          etag: pendingCommit.current.etag,
          body,
          key: pendingCommit.current.key,
        },
      );
      setOperation(data.operation);
      rememberOperation(id, data.operation.id);
      setFiles([]);
      await refreshBatch();
      await load();
      setPartial(false);
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.status === 412) {
        pendingCommit.current = null;
        setConflict(true);
      }
    } finally {
      setBusy(false);
    }
  }
  const verified =
    batch?.uploads.filter((upload) => upload.state === "verified") ?? [];
  const incomplete = batch
    ? batch.uploads.length !== verified.length ||
      files.some((file) => file.state !== "已提交核验")
    : false;
  const documents = materials?.documents ?? [];
  const heads = documents.filter(
    (document) => document.id === document.file_head_version_id,
  );
  if (!bid && !error) return <Loading text="正在打开项目…" />;
  return (
    <div className="page-content project-page">
      <button className="back-link" onClick={onBack}>
        <Icon name="back" />
        返回项目列表
      </button>
      <div className="page-heading">
        <div>
          <span className="eyebrow">项目工作区</span>
          <h1>{bid?.title ?? "项目读取失败"}</h1>
          <div className="project-meta">
            <Badge>
              {bid
                ? {
                    preparation: "准备资料",
                    working: "工作中",
                    submitted: "已登记提交",
                    closed: "已结项",
                    terminated: "已终止",
                  }[bid.phase]
                : "正在读取"}
            </Badge>
            {bid && <span>资料包 {bid.material_revision}</span>}
            <span>原件、版本与解析范围分别记录</span>
          </div>
        </div>
        <button
          className="button primary"
          onClick={() => {
            sectionRef.current?.scrollIntoView({ behavior: "smooth" });
            inputRef.current?.click();
          }}
        >
          <Icon name="upload" />
          上传资料
        </button>
      </div>
      <ErrorNotice
        error={error}
        onRetry={() => {
          setError(null);
          void load().catch(setError);
          void refreshBatch().catch(setError);
        }}
      />
      {navigation ?? (
        <div className="project-tabs" aria-label="项目工作区">
          <span className="project-tab active">项目资料</span>
          <span className="tab-description">
            从PDF原件开始，完成资料入库与范围核对
          </span>
        </div>
      )}
      <section className="next-step">
        <div className="next-step-icon">
          <Icon name="arrow" />
        </div>
        <div>
          <span className="eyebrow">资料处理下一步</span>
          <h2>
            {batch && batch.state !== "committed"
              ? "完成本批资料核验并确认入库"
              : documents.length
                ? "核对各份文件的解析范围"
                : "上传招标资料和投标正文"}
          </h2>
          <p>
            {documents.length
              ? "文本解析与规则评审分别记录。请核对实际解析缺口，风险结论以对应评审轮次为准。"
              : "可直接上传已有PDF，不需要先设置目录、模板或企业知识。"}
          </p>
        </div>
      </section>
      <section className="panel upload-panel" ref={sectionRef}>
        <div className="section-heading">
          <div>
            <h2>添加项目资料</h2>
            <p className="muted">
              先选择文件，再核对用途。单文件不超过100 MiB，原件保存在私有存储。
            </p>
          </div>
          <Badge>PDF 快速路径</Badge>
        </div>
        <UploadBatchDiscovery
          key={id}
          bidId={id}
          currentId={batchId}
          disabled={busy}
          hasUnsentFiles={files.some((file) => !file.grant)}
          onSelect={(selectedBatch) => {
            if (busy || selectedBatch.bid_id !== id) return;
            invalidateTransfers();
            transport.current = null;
            setBatchId(selectedBatch.id);
            setBatch(selectedBatch);
            setFiles([]);
            setPartial(false);
            setOperation(null);
            setError(null);
            setConflict(false);
            pendingCommit.current = null;
            localStorage.setItem(batchStorageKey(id), selectedBatch.id);
          }}
        />
        <label className="file-drop" htmlFor="project-files">
          <span className="upload-icon">
            <Icon name="upload" />
          </span>
          <strong>选择需要上传的资料</strong>
          <span>支持PDF与DOCX；Word原件保存、转换和对应检查分别显示</span>
          <input
            ref={inputRef}
            id="project-files"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            multiple
            onChange={chooseFiles}
            disabled={busy}
          />
        </label>
        {files.length > 0 && (
          <div className="draft-files">
            {files.map((item) => (
              <div className="draft-file" key={item.key}>
                <div className="file-summary">
                  <Icon name="file" />
                  <div>
                    <strong>{item.file.name}</strong>
                    <small>
                      {sizeLabel(item.file.size)} · {item.state}
                    </small>
                  </div>
                </div>
                {item.role === null ? (
                  <p className="small-note">
                    沿用本次上传已固定的资料用途与入库目标，只接续原件传输。
                  </p>
                ) : (
                  <>
                    <label>
                      资料用途
                      <select
                        aria-label={`${item.file.name}的资料用途`}
                        value={item.role}
                        disabled={busy || !!item.grant || !!item.declaredSource}
                        onChange={(event) =>
                          patchFile(item.key, {
                            role: event.target.value as UploadRequest["role"],
                            target: "",
                          })
                        }
                      >
                        {Object.entries(roleNames)
                          .filter(
                            ([role]) =>
                              role !== "official_result" ||
                              item.role === "official_result",
                          )
                          .map(([role, name]) => (
                            <option key={role} value={role}>
                              {name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      文件身份
                      <select
                        aria-label={`${item.file.name}的文件身份`}
                        value={item.target}
                        disabled={busy || !!item.grant || !!item.declaredSource}
                        onChange={(event) =>
                          patchFile(item.key, { target: event.target.value })
                        }
                      >
                        <option value="">作为独立文件</option>
                        {heads
                          .filter(
                            (document) =>
                              document.role === item.role &&
                              sameUploadFormat(
                                document.filename,
                                item.file.name,
                              ) &&
                              !item.declaredSource,
                          )
                          .map((document) => (
                            <option
                              key={document.file_id}
                              value={document.file_id}
                            >
                              {document.filename} · 新版本
                            </option>
                          ))}
                      </select>
                    </label>
                  </>
                )}
                {item.declaredSource && (
                  <p className="notice warning">
                    此PDF由你声明对应指定Word修改稿，作为独立PDF保存。对应关系尚未核验，不继承Word检查资格。
                  </p>
                )}
                {!item.grant && (
                  <button
                    className="text-button"
                    disabled={busy}
                    aria-label={`移除${item.file.name}`}
                    onClick={() =>
                      setFiles((old) =>
                        old.filter((file) => file.key !== item.key),
                      )
                    }
                  >
                    移除
                  </button>
                )}
                <div className="draft-error">
                  <ErrorNotice error={item.error} />
                </div>
              </div>
            ))}
            <div className="upload-actions">
              <span className="muted">
                同名文件不自动覆盖。需要替换时请选择对应文件的新版本。
              </span>
              <button
                className="button primary"
                disabled={
                  busy || files.every((file) => file.state === "已提交核验")
                }
                onClick={() => void upload()}
              >
                {busy
                  ? "正在处理…"
                  : files.some((file) => file.error)
                    ? "重试未完成的文件"
                    : "上传并核验原件"}
                <Icon name="arrow" />
              </button>
            </div>
          </div>
        )}
      </section>
      {batch && (
        <section className="panel batch-panel">
          <div className="section-heading">
            <div>
              <h2>
                {batch.state === "committed"
                  ? "本批资料已入库"
                  : "本批资料核验"}
              </h2>
              <p className="muted">
                传输完成后由服务端核对原件。核验通过不表示已完成评审。
              </p>
            </div>
            <Badge tone={batch.state === "committed" ? "success" : "warning"}>
              {batch.state === "committed" ? "已入库" : "待确认"}
            </Badge>
          </div>
          {batch.uploads.map((upload) => (
            <div className="batch-file" key={upload.id}>
              <div className="file-summary">
                <Icon name="file" />
                <div>
                  <strong>{upload.filename}</strong>
                  <small>
                    {batch.state === "committed" && upload.state === "verified"
                      ? "已核验并入库"
                      : uploadNames[upload.state]}
                    {upload.error_code ? ` · ${upload.error_code}` : ""}
                  </small>
                </div>
              </div>
              {(["authorized", "uploaded"].includes(upload.state) ||
                !!pendingUploadCompletion(upload.id)) &&
                batch.state !== "committed" && (
                  <UploadStatus
                    uploadId={upload.id}
                    hasLocalFile={files.some(
                      (file) => file.grant?.upload_id === upload.id,
                    )}
                    disabled={busy}
                    onWorking={setBusy}
                    onAccepted={(accepted) => {
                      if (!active.current || accepted.operation.bid_id !== id)
                        return;
                      setOperation(accepted.operation);
                      rememberOperation(id, accepted.operation.id);
                      void refreshBatch().catch(setError);
                    }}
                  />
                )}
              {upload.state === "authorized" && batch.state !== "committed" && (
                <label className="resume-file">
                  接续此文件
                  <input
                    aria-label={`重新选择${upload.filename}的原文件以接续上传`}
                    type="file"
                    accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    disabled={busy}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void resumeUpload(upload, file);
                      event.target.value = "";
                    }}
                  />
                </label>
              )}
              {upload.word_pdf_declaration && (
                <div className="notice warning">
                  <p>
                    此PDF由用户声明对应指定Word修改稿，用途固定为
                    {roleNames[upload.word_pdf_declaration.role]}
                    ，作为独立文件保存。对应关系尚未核验，不是受控转换。
                  </p>
                  <a
                    href={`/bids/${id}/materials#word-original-${upload.word_pdf_declaration.source_document_version_id}`}
                  >
                    查看对应Word原件与转换状态
                  </a>
                </div>
              )}
              {upload.state === "verified" && batch.state !== "committed" && (
                <BindingRecovery
                  uploadId={upload.id}
                  documents={
                    upload.word_pdf_declaration
                      ? []
                      : heads.filter((d) =>
                          sameUploadFormat(d.filename, upload.filename),
                        )
                  }
                  onUpdated={() => void refreshBatch().catch(setError)}
                />
              )}
            </div>
          ))}
          {batch.uploads.length === 0 && (
            <p className="muted">尚未收到本批文件。请继续上传已选资料。</p>
          )}
          {batch.state !== "committed" && verified.length > 0 && (
            <div className="batch-confirm">
              {incomplete && (
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={partial}
                    onChange={(event) => setPartial(event.target.checked)}
                  />
                  我确认仅将已核验的 {verified.length}{" "}
                  份资料入库；其余文件尚未入库
                </label>
              )}
              {conflict && (
                <div className="notice warning">
                  <div>
                    <strong>资料版本已变化，请重新核对</strong>
                    <p>
                      原件已保留。先刷新资料包；若目标文件已更新，请展开该文件的“调整入库目标”，选择新版本目标并说明原因。
                    </p>
                    <button
                      className="button secondary"
                      onClick={() => {
                        void load()
                          .then(() => {
                            setConflict(false);
                            setError(null);
                          })
                          .catch(setError);
                      }}
                    >
                      刷新并查看当前资料
                    </button>
                  </div>
                </div>
              )}
              <button
                className="button primary"
                disabled={busy || conflict || (incomplete && !partial)}
                onClick={() => void commit()}
              >
                {busy ? "正在确认…" : `确认 ${verified.length} 份资料入库`}
              </button>
            </div>
          )}
        </section>
      )}
      {operation && (
        <div className="operation-status" role="status">
          <Icon name="clock" />
          <span>
            {operationNames[operation.state]} ·{" "}
            {operation.kind === "parse_document" ? "资料解析" : "资料处理"}
            {["queued", "running"].includes(operation.state)
              ? "，可离开页面，稍后继续查看。"
              : "，文件状态以各份资料记录为准。"}
          </span>
        </div>
      )}
      <section className="panel materials-panel">
        <div className="section-heading">
          <div>
            <h2>
              已入库资料 <span className="count">{documents.length}</span>
            </h2>
            <p className="muted">
              查看每一个版本的原件与解析依据，不以文件名判断同稿关系。
            </p>
          </div>
        </div>
        {materials?.conflicts.map((message, index) => (
          <div className="notice warning" key={index}>
            {message}
          </div>
        ))}
        {!materials && <Loading />}
        {materials && documents.length === 0 && (
          <div className="small-empty">
            已核验文件经确认入库后，会在这里显示。
          </div>
        )}
        {documents.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件／版本</th>
                  <th>用途</th>
                  <th>解析范围</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <div className="file-summary">
                        <span className="document-icon">
                          <Icon name="file" />
                        </span>
                        <div>
                          <strong>{document.filename}</strong>
                          <small>
                            版本 {document.file_revision} ·{" "}
                            {sizeLabel(document.byte_size)}
                            {document.id !== document.file_head_version_id
                              ? " · 历史版本"
                              : " · 当前版本"}
                          </small>
                          <DocumentRelationNotice document={document} />
                        </div>
                      </div>
                    </td>
                    <td>{roleNames[document.role]}</td>
                    <td>
                      <Badge
                        tone={
                          !document.media_type.includes("word") &&
                          document.parse_coverage === "complete"
                            ? "success"
                            : "warning"
                        }
                      >
                        {document.media_type.includes("word")
                          ? "Word对应检查未完成"
                          : parseNames[document.parse_coverage]}
                      </Badge>
                      {document.media_type.includes("word") && (
                        <small className="word-warning">
                          Word原件已保存／本次对应检查未完成
                        </small>
                      )}
                    </td>
                    <td>
                      <div className="document-actions">
                        {document.media_type.includes("word") && (
                          <a
                            className="text-button"
                            href={`#word-original-${document.id}`}
                          >
                            查看Word转换与对应PDF
                          </a>
                        )}
                        <button
                          className="text-button"
                          onClick={() => setSelected(document)}
                        >
                          查看原件与依据
                          <Icon name="arrow" />
                        </button>
                        {document.previous_version_id && (
                          <button
                            className="text-button"
                            onClick={() =>
                              setHistoryHead((current) =>
                                current?.id === document.id ? null : document,
                              )
                            }
                            aria-expanded={historyHead?.id === document.id}
                          >
                            查看历史版本
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <BidPackages
        bidId={id}
        memberId={memberId}
        disabled={
          busy ||
          !!bid?.archived_at ||
          bid?.phase === "closed" ||
          bid?.phase === "terminated"
        }
      />
      <WordOriginals
        bidId={id}
        memberId={memberId}
        disabled={busy}
        onPdf={(file, context) => {
          if (context.bid_id !== id || busy) return;
          setFiles((old) => [
            ...old,
            {
              key: crypto.randomUUID(),
              uploadKey: crypto.randomUUID(),
              file,
              role: context.role,
              target: "",
              state: "待上传",
              declaredSource: context.declared_source_document_version_id,
            },
          ]);
          sectionRef.current?.scrollIntoView({ block: "start" });
        }}
      />
      {historyHead && (
        <HistoryPanel
          key={historyHead.id}
          head={historyHead}
          onOpen={setSelected}
          onClose={() => setHistoryHead(null)}
        />
      )}
      {reviewNotice ?? (
        <div className="notice neutral">
          <div>
            <strong>评审与评分尚未就绪</strong>
            <p>
              当前提供资料入库和PDF文本解析。核心规则核对、响应矩阵、完整评审、正式技术评分和提交检查尚未开放；文本解析完成不代表没有否决风险。
            </p>
          </div>
        </div>
      )}
      {selected && <Evidence document={selected} onClose={closeEvidence} />}
    </div>
  );
}

export function BindingRecovery({
  uploadId,
  documents,
  onUpdated,
}: {
  uploadId: string;
  documents: DocumentView[];
  onUpdated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{
    signature: string;
    etag: string | null;
    key: string;
  } | null>(null);
  async function rebind() {
    setBusy(true);
    setError(null);
    try {
      const { data: currentUpload, etag } = await api<UploadView>(
        `/uploads/${uploadId}`,
      );
      if (currentUpload.id !== uploadId || !etag)
        throw new Error(
          "当前上传身份或保存令牌无法核对，原件保留，请重试读取。",
        );
      if (currentUpload.word_pdf_declaration === undefined)
        throw new Error(
          "服务器尚未提供本次上传的对应稿约束，请刷新或等待服务版本就绪。已核验原件保留。",
        );
      if (currentUpload.word_pdf_declaration && target) {
        setTarget("");
        onUpdated();
        throw new Error(
          "此PDF对应指定Word修改稿，只能作为独立文件。已清除旧版本目标，原因保留，请核对后确认独立文件。",
        );
      }

      const document = documents.find((item) => item.file_id === target);
      const body = {
        target: document
          ? {
              kind: "new_version",
              file_id: document.file_id,
              expected_file_revision: document.file_head_revision,
            }
          : { kind: "new_file" },
        reason: reason.trim(),
      };
      const signature = JSON.stringify(body);
      if (pending.current?.signature !== signature)
        pending.current = {
          signature,
          etag,
          key: commandKey(`upload:binding:${uploadId}`, { body, etag }),
        };
      await api<UploadBindingView>(`/uploads/${uploadId}/bindings`, {
        method: "POST",
        etag: pending.current.etag,
        body,
        key: pending.current.key,
      });
      onUpdated();
      pending.current = null;
      setOpen(false);
      setReason("");
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.status === 412) pending.current = null;
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="binding-recovery">
      <button
        className="text-button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        调整入库目标
      </button>
      {open && (
        <div className="binding-fields">
          <p className="muted">
            复用已核验原件，不需要重新上传。只在确认新目标后建立新的绑定记录。
          </p>
          <label>
            入库目标
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              <option value="">作为独立文件</option>
              {documents.map((document) => (
                <option key={document.file_id} value={document.file_id}>
                  {document.filename} · 当前版本 {document.file_head_revision}{" "}
                  后的新版本
                </option>
              ))}
            </select>
          </label>
          <label>
            调整原因
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={1000}
              required
            />
          </label>
          <ErrorNotice error={error} />
          <button
            className="button secondary"
            disabled={busy || !reason.trim()}
            onClick={() => void rebind()}
          >
            {busy ? "正在保存…" : "确认新的入库目标"}
          </button>
        </div>
      )}
    </div>
  );
}
