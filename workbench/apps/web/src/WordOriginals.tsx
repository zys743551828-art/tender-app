import { useState, useEffect, useRef } from "react";
import type {
  Accepted,
  WordOriginalPage,
  WordOriginalView,
  WordMaterialAdoptionView,
} from "./contracts";
import { api } from "./api";
import { ArtifactActions } from "./ArtifactActions";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import { wordMediaType } from "./uploadFormats";

type PdfContext = WordOriginalView["primary_action"]["context"];
export function WordOriginals({
  bidId,
  memberId,
  disabled,
  onPdf,
}: {
  bidId: string;
  memberId: string;
  disabled: boolean;
  onPdf: (file: File, context: PdfContext) => void;
}) {
  const page = useResource<WordOriginalPage>(
    `/bids/${bidId}/word-originals`,
    4000,
  );
  const [more, setMore] = useState<WordOriginalPage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const items = [
    ...new Map(
      [...(page.data?.items ?? []), ...more.flatMap((p) => p.items)].map(
        (v) => [v.id, v],
      ),
    ).values(),
  ];
  const [selectedWord, setSelectedWord] = useState(() =>
    window.location.hash.startsWith("#word-original-")
      ? window.location.hash.slice(15)
      : "",
  );
  const specific = useResource<WordOriginalView>(
    selectedWord
      ? `/bids/${bidId}/word-originals/${encodeURIComponent(selectedWord)}`
      : null,
  );
  const visible = [
    ...new Map(
      [...items, ...(specific.data ? [specific.data] : [])].map((v) => [
        v.id,
        v,
      ]),
    ).values(),
  ];
  const positioned = useRef("");
  useEffect(() => {
    function changed() {
      const hash = window.location.hash;
      setSelectedWord(hash.startsWith("#word-original-") ? hash.slice(15) : "");
      positioned.current = "";
    }
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    if (!selectedWord || positioned.current === selectedWord) return;
    const element = window.document.getElementById(
      `word-original-${selectedWord}`,
    );
    if (element) {
      positioned.current = selectedWord;
      element.focus({ preventScroll: true });
      element.scrollIntoView?.({ block: "start" });
    }
  }, [selectedWord, page.data, specific.data]);
  const last = more.at(-1) ?? page.data;
  async function next() {
    if (!last?.next_after || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<WordOriginalPage>(
        `/bids/${bidId}/word-originals?after=${encodeURIComponent(last.next_after)}`,
      );
      setMore((old) => [...old, r.data]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (page.unavailable) return null;
  return (
    <section className="panel word-originals" aria-label="Word原件与对应PDF">
      <div className="section-heading">
        <div>
          <h2>Word原件与对应PDF</h2>
          <p className="small-note">
            保存原件、受控转换、当前采用和对应检查是不同状态。转换不代表Word交付或评审已通过。
          </p>
        </div>
        <Badge>原件保留</Badge>
      </div>
      <ResourceState
        {...page}
        hasData={!!page.data}
        onRetry={() => void page.reload()}
      />
      <ErrorNotice error={error} />
      {page.data && !items.length && (
        <p className="small-empty">
          尚无已保存的Word原件。已有PDF可继续直接上传。
        </p>
      )}
      <ResourceState
        {...specific}
        hasData={!!specific.data}
        onRetry={() => void specific.reload()}
      />
      {visible.map((item) => (
        <WordCard
          key={item.id}
          initial={item}
          bidId={bidId}
          memberId={memberId}
          disabled={disabled}
          onPdf={onPdf}
        />
      ))}
      {last?.has_more && (
        <button
          className="text-button"
          disabled={busy}
          onClick={() => void next()}
        >
          加载更多Word原件
        </button>
      )}
    </section>
  );
}
export function WordCard({
  initial,
  bidId,
  memberId = "test",
  disabled,
  onPdf,
}: {
  initial: WordOriginalView;
  bidId: string;
  memberId?: string;
  disabled: boolean;
  onPdf: (file: File, context: PdfContext) => void;
}) {
  const path = `/bids/${bidId}/word-originals/${initial.id}`;
  const view = useResource<WordOriginalView>(path, 4000);
  const adoption = useResource<WordMaterialAdoptionView>(
    `/bids/${bidId}/word-materials/${initial.id}`,
    4000,
  );
  const cmd = useRecordedCommand(
    `word-retry:${memberId}:${bidId}:${initial.id}`,
  );
  const [error, setError] = useState<unknown>(null);
  const word = view.data ?? initial;
  if (
    word.id !== initial.id ||
    word.bid_id !== bidId ||
    word.original_saved !== true
  )
    return (
      <p role="alert" className="notice error">
        原件身份不一致，未显示其他项目Word。
      </p>
    );
  const conversion = word.conversion;
  const missingResult = conversion.gaps.includes(
    "WORD_CONVERSION_RESULT_MISSING",
  );
  const complete =
    conversion.state === "succeeded" &&
    conversion.coverage === "complete" &&
    conversion.controlled_render_verified;
  async function retry(recover = false) {
    const r = recover
      ? await cmd.retry<Accepted>()
      : await cmd.run<Accepted>(
          path + "/retry-conversion",
          {},
          view.etag ?? "",
        );
    if (r) void view.reload();
  }
  return (
    <article id={`word-original-${word.id}`} className="word-original-card">
      <h3>{word.original_name}</h3>
      {adoption.data?.bid_id === bidId &&
        adoption.data.source_document_version_id === word.id &&
        typeof adoption.data.source_is_file_head === "boolean" && (
          <Badge>
            {adoption.data.source_is_file_head
              ? "该Word文件的最新版本"
              : "Word历史原件"}
          </Badge>
        )}
      <p className={complete ? "notice" : "notice warning"}>
        {complete
          ? "Word原件已保存／受控转换已完成"
          : "Word原件已保存／本次对应检查未完成"}
      </p>
      <details>
        <summary>核对该Word原件身份与处理说明</summary>
        <p>{word.message}</p>
        <p className="identity-ref">原件SHA-256：{word.source_sha256}</p>
        <p>原件字节数：{word.byte_size}</p>
      </details>
      <Badge>
        {conversion.state === "pending"
          ? "等待转换"
          : conversion.state === "running"
            ? "正在转换"
            : complete
              ? "已生成对应PDF"
              : conversion.coverage === "partial"
                ? "转换范围不完整"
                : conversion.state === "cancelling"
                  ? "正在取消转换"
                  : conversion.state === "cancelled"
                    ? "转换已取消"
                    : "转换未完成"}
      </Badge>
      <p className="small-note">{word.delivery_check_message}</p>
      {!conversion.conversion_attempted && (
        <p className="small-note">
          尚未实际运行转换，请按下列范围提示继续；Word原件仍保留。
        </p>
      )}
      {conversion.gaps.map((g, i) => (
        <p className="notice warning" key={i}>
          {g === "WORD_CONVERSION_RESULT_MISSING"
            ? "本次转换未返回可用的PDF。Word原件仍保留，可重试转换或上传对应PDF。"
            : g}
        </p>
      ))}
      {(conversion.error_code || missingResult) && (
        <details>
          <summary>查看转换状态详情</summary>
          <code>
            {conversion.error_code ?? "WORD_CONVERSION_RESULT_MISSING"}
          </code>
        </details>
      )}
      <ResourceState
        {...view}
        hasData={!!view.data}
        onRetry={() => void view.reload()}
      />
      <ResourceState
        {...adoption}
        hasData={!!adoption.data}
        onRetry={() => void adoption.reload()}
      />
      {adoption.data?.source_document_version_id === word.id &&
        adoption.data.bid_id === bidId && (
          <p className="small-note">
            {adoption.data.adoption_state === "adopted" &&
            adoption.data.is_current_converted_pdf
              ? "对应PDF已作为当前材料采用；实际检查状态请回工作台核对。"
              : adoption.data.adoption_state === "adopted"
                ? "此转换PDF已入库，但当前采用已有变化；历史产物保留，未切换当前稿。"
                : adoption.data.adoption_state === "needs_selection"
                  ? "当前材料或稿件已变化，此转换仅留历史，未替换当前稿。"
                  : adoption.data.adoption_state === "pending"
                    ? "等待协调当前材料，尚未宣称采用。"
                    : "此Word未选为当前材料；转换产物保留供查看。"}
          </p>
        )}
      <ArtifactActions
        bidId={bidId}
        documentId={word.id}
        isPdf={false}
        downloadLabel="下载Word资料原件"
        expectedMediaType={wordMediaType}
      />
      {word.converted_pdf_action && (
        <ArtifactActions
          bidId={bidId}
          documentId={word.converted_pdf_action.document_version_id}
          isPdf
          downloadLabel="下载此Word转换的PDF"
          previewNotice="这是指定Word原件的转换PDF。是否采用以当前材料状态为准；转换不授予Word检查或评审资格。"
        />
      )}
      <div className="review-shortcuts">
        <label className="resume-file">
          上传此修改稿的PDF
          <input
            type="file"
            accept=".pdf,application/pdf"
            disabled={disabled}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              if (!/\.pdf$/i.test(file.name)) {
                setError(
                  new Error("请选择对应修改稿的PDF；Word原件无需重传。"),
                );
                return;
              }
              const c = word.primary_action.context;
              if (
                c.bid_id !== bidId ||
                c.declared_source_document_version_id !== word.id
              ) {
                setError(new Error("对应原件身份不一致，未加入上传。"));
                return;
              }
              setError(null);
              onPdf(file, c);
            }}
          />
        </label>
        {conversion.retryable && (
          <button
            className="button secondary"
            disabled={disabled || cmd.busy || !view.etag || !!cmd.pending}
            onClick={() => void retry()}
          >
            重试此原件的转换
          </button>
        )}
      </div>
      {cmd.pending && (
        <button
          className="button secondary"
          disabled={cmd.busy}
          onClick={() => void retry(true)}
        >
          恢复原转换受理结果
        </button>
      )}
      <ErrorNotice error={error ?? cmd.error} />
      {cmd.conflict && (
        <button className="text-button" onClick={() => void view.reload()}>
          读取最新转换状态，保留原件后重试
        </button>
      )}
    </article>
  );
}
