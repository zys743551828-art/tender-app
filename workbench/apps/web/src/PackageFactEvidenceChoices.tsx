import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import PackageEvidencePicker from "./PackageEvidencePicker";
import { memberships, packageCategoryNames } from "./packageEvidenceDirectory";
import type { EvidenceEntry } from "./packageEvidenceDirectory";
import type {
  BidPackageStoredView,
  DocumentView,
  EvidenceView,
  PackageFactSourcePackage,
} from "./contracts";
import type { FactChangeScope } from "./factChangeProtocol";
import { frozenManifestDigest } from "./packageFrozenInput";
import { executionId } from "./executionInputValidation";

export type FactEvidenceChoice = {
  id: string;
  documentId: string;
  parseId: string;
  page: number;
  label: string;
  frozenParseMember: boolean;
  quote?: string;
};
type Props = {
  scope: FactChangeScope;
  packages: PackageFactSourcePackage[];
  selected: FactEvidenceChoice[];
  disabled: boolean;
  onPick: (value: FactEvidenceChoice) => void;
  onRemove: (id: string) => void;
};
export default function PackageFactEvidenceChoices({
  scope,
  packages,
  selected,
  disabled,
  onPick,
  onRemove,
}: Props) {
  const [role, setRole] = useState<"target" | "authority">("target"),
    [view, setView] = useState<BidPackageStoredView | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState<string | null>(null);
  const active = useRef(false),
    ticket = useRef(0),
    locked = useRef(disabled),
    cache = useRef(new Map<string, Promise<BidPackageStoredView>>());
  locked.current = disabled;
  useEffect(() => {
    const request = ticket;
    request.current++;
    active.current = true;
    return () => {
      active.current = false;
      request.current++;
    };
  }, []);
  async function source(ref: PackageFactSourcePackage) {
    const key = `${ref.revision_id}:${ref.digest}`;
    let promise = cache.current.get(key);
    if (!promise) {
      promise = (async () => {
        const { data } = await api<BidPackageStoredView>(
          `/bids/${scope.bidId}/packages/${ref.package_id}/revisions/${ref.revision_id}`,
        );
        if (
          data?.manifest?.scope?.bid_id !== scope.bidId ||
          data.manifest.package_id !== ref.package_id ||
          data.manifest.revision_id !== ref.revision_id ||
          data.manifest.kind !==
            (ref.role === "target" ? "bid" : "authority") ||
          data.digest !== ref.digest ||
          !Array.isArray(data.manifest.members) ||
          (await frozenManifestDigest(data.manifest)) !== ref.digest
        )
          throw new Error("来源包与冻结记录引用不一致，未改取当前包。");
        return data;
      })();
      cache.current.set(key, promise);
      promise.catch(() => cache.current.delete(key));
    }
    return promise;
  }
  const refsKey = JSON.stringify(packages);
  useEffect(() => {
    const ref = packages.find((x) => x.role === role);
    let current = true;
    setView(null);
    setError(null);
    if (ref)
      void source(ref)
        .then((value) => {
          if (current && active.current) setView(value);
        })
        .catch((failure) => {
          if (current && active.current) setError(failure);
        });
    return () => {
      current = false;
    };
    // Both descriptors are immutable references captured for this frozen input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, refsKey]);
  async function read(
    meta: {
      id: string;
      document_version_id: string;
      parse_run_id: string;
      physical_page: number;
      part_ids?: string[];
    },
    from?: BidPackageStoredView,
  ) {
    if (locked.current || busy) return;
    if (
      ![meta.id, meta.document_version_id, meta.parse_run_id].every(executionId)
    ) {
      setError(new Error("原页依据编号不符合协议，未发送读取请求。"));
      return;
    }
    const current = ++ticket.current;
    setBusy(meta.id);
    setError(null);
    try {
      const candidates = from
        ? [from]
        : await Promise.all(packages.map(source));
      const matched = candidates
        .flatMap((v) => v.manifest.members.map((member) => ({ v, member })))
        .find(
          (x) =>
            x.member.document_version_id === meta.document_version_id &&
            x.member.parse.status === "frozen" &&
            x.member.parse.parse_run_id === meta.parse_run_id,
        );
      if (!matched) throw new Error("原依据不属于冻结文件及解析，请重新选择。");
      const { data: evidence } = await api<EvidenceView>(
        `/evidence/${meta.id}`,
      );
      if (
        evidence.id !== meta.id ||
        evidence.document_version_id !== meta.document_version_id ||
        evidence.parse_run_id !== meta.parse_run_id ||
        evidence.physical_page !== meta.physical_page ||
        evidence.source_status !== "published" ||
        typeof evidence.quote !== "string" ||
        (meta.part_ids &&
          [...meta.part_ids].sort().join("\0") !==
            memberships(matched.v, evidence).sort().join("\0"))
      )
        throw new Error("原句身份、范围或来源效力不符，未采用该依据。");
      const { data: document } = await api<DocumentView>(
        `/documents/${meta.document_version_id}`,
      );
      if (
        document.id !== meta.document_version_id ||
        document.bid_id !== scope.bidId ||
        typeof document.filename !== "string" ||
        document.sha256 !== matched.member.file_digest
      )
        throw new Error("来源文件身份或原件摘要不一致。");
      if (active.current && ticket.current === current && !locked.current)
        onPick({
          id: meta.id,
          documentId: meta.document_version_id,
          parseId: meta.parse_run_id,
          page: meta.physical_page,
          label: `${document.filename} · 第 ${meta.physical_page} 页`,
          frozenParseMember: true,
          quote: evidence.quote,
        });
    } catch (failure) {
      if (active.current && ticket.current === current) setError(failure);
    } finally {
      if (active.current && ticket.current === current) setBusy(null);
    }
  }
  function row(entry: EvidenceEntry, index: number) {
    const titles = view?.manifest.members
      .flatMap((m) =>
        m.parts
          .filter((p) => entry.part_ids.includes(p.part_id))
          .map((p) => packageCategoryNames[p.category] ?? p.category),
      )
      .join("、");
    return (
      <div className="package-fact-change__evidence-row" key={entry.id}>
        <span>
          {titles || "冻结文件"} · 第 {entry.physical_page} 页
        </span>
        <button
          className="button secondary"
          type="button"
          disabled={disabled || !!busy || !view}
          onClick={() => void read(entry, view!)}
        >
          {busy === entry.id
            ? "正在读取原句…"
            : `读取并采用第 ${index + 1} 条原句`}
        </button>
      </div>
    );
  }
  return (
    <section
      className="package-fact-change__evidence"
      aria-label="事实原页依据"
    >
      <h6>原页依据</h6>
      <label>
        依据来源
        <select
          value={role}
          disabled={disabled || !!busy}
          onChange={(e) => setRole(e.target.value as typeof role)}
        >
          <option value="target">本方标书</option>
          <option value="authority">招标及补遗</option>
        </select>
      </label>
      {error != null && <ErrorNotice error={error} />}
      {view &&
        supportsApi(
          "GET",
          `/bids/${scope.bidId}/packages/${view.manifest.package_id}/revisions/${view.manifest.revision_id}/evidence`,
        ) && (
          <PackageEvidencePicker
            key={`${view.manifest.revision_id}:${view.digest}`}
            bidId={scope.bidId}
            view={view}
            disabled={disabled || !!busy}
            buttonClassName="button secondary"
            label={`浏览${role === "target" ? "本方标书" : "招标及补遗"}冻结原页`}
            renderEntry={row}
          />
        )}
      {!view && error == null && <p>正在读取准确来源包…</p>}
      {!selected.length && <p>从冻结原页选择依据，再核对事实内容。</p>}
      <ul>
        {selected.map((choice, index) => (
          <li key={choice.id}>
            <div>
              <strong>{choice.label}</strong>
              {!choice.frozenParseMember && (
                <p>此依据未匹配本次冻结输入，请移除并重新选择。</p>
              )}
            </div>
            {choice.frozenParseMember && (
              <button
                className="button secondary"
                type="button"
                disabled={disabled || !!busy}
                onClick={() =>
                  void read({
                    id: choice.id,
                    document_version_id: choice.documentId,
                    parse_run_id: choice.parseId,
                    physical_page: choice.page,
                  })
                }
              >
                {busy === choice.id
                  ? "正在读取原句…"
                  : `读取原依据 ${index + 1}`}
              </button>
            )}
            <button
              type="button"
              className="text-button"
              disabled={disabled || !!busy}
              onClick={() => onRemove(choice.id)}
            >
              移除此依据
            </button>
            {choice.quote !== undefined && (
              <blockquote>
                {Array.from(choice.quote).slice(0, 4000).join("")}
                {Array.from(choice.quote).length > 4000 && (
                  <span>（原句预览已截断，可打开原页核对全文。）</span>
                )}
              </blockquote>
            )}
            <EvidenceLinks ids={[choice.id]} label="查看依据原页" />
          </li>
        ))}
      </ul>
    </section>
  );
}
