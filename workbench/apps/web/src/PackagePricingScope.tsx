import { useState } from "react";
import type { PackagePricingBinding } from "./packagePricing";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useCursorList } from "./useCursorList";

type PackagePage = {
  items: { id: string; revision_id: string; revision: number; kind: string }[];
  next_cursor: string | null;
};

export function PackagePricingScope({
  bidId,
  onSelect,
}: {
  bidId: string;
  onSelect: (binding: PackagePricingBinding) => void;
}) {
  const own = useCursorList<PackagePage>(
    `/bids/${bidId}/packages?kind=bid&limit=20`,
    (item) => item.id,
  );
  const authority = useCursorList<PackagePage>(
    `/bids/${bidId}/packages?kind=authority&limit=20`,
    (item) => item.id,
  );
  const [ownChoice, setOwnChoice] = useState("");
  const [authorityChoice, setAuthorityChoice] = useState("");
  const target = own.items.find(
    (item) => `${item.id}:${item.revision_id}` === ownChoice,
  );
  const rules = authority.items.find(
    (item) => `${item.id}:${item.revision_id}` === authorityChoice,
  );
  return (
    <section className="panel">
      <h2>选择本次整包报价范围</h2>
      <p>
        分别选择投标包和招标补遗包的确切修订。报价公式、试算与已保存方案都会保留这份选择；包更新后需要重新核对。
      </p>
      <ResourceState
        {...own}
        hasData={!!own.data}
        onRetry={() => void own.reload()}
      />
      <ResourceState
        {...authority}
        hasData={!!authority.data}
        onRetry={() => void authority.reload()}
      />
      <ErrorNotice error={own.moreError ?? authority.moreError} />
      <label>
        本次投标包
        <select
          value={ownChoice}
          onChange={(event) => setOwnChoice(event.target.value)}
        >
          <option value="">明确选择投标包</option>
          {own.items.map((item) => (
            <option key={item.id} value={`${item.id}:${item.revision_id}`}>
              投标包 · 第 {item.revision} 版 · {item.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {own.hasMore && (
        <button
          className="text-button"
          disabled={own.moreBusy}
          onClick={() => void own.more()}
        >
          加载更多投标包
        </button>
      )}
      <label>
        本次招标与补遗包
        <select
          value={authorityChoice}
          onChange={(event) => setAuthorityChoice(event.target.value)}
        >
          <option value="">明确选择招标与补遗包</option>
          {authority.items.map((item) => (
            <option key={item.id} value={`${item.id}:${item.revision_id}`}>
              招标补遗包 · 第 {item.revision} 版 · {item.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {authority.hasMore && (
        <button
          className="text-button"
          disabled={authority.moreBusy}
          onClick={() => void authority.more()}
        >
          加载更多招标补遗包
        </button>
      )}
      <button
        className="button primary"
        disabled={!target || !rules || !!own.error || !!authority.error}
        onClick={() => {
          if (target && rules)
            onSelect({
              package_id: target.id,
              revision_id: target.revision_id,
              authority_package_id: rules.id,
              authority_revision_id: rules.revision_id,
            });
        }}
      >
        使用这两份修订继续报价
      </button>
      {own.data && !own.items.length && (
        <p className="small-empty">请先在项目资料中建立投标包。</p>
      )}
      {authority.data && !authority.items.length && (
        <p className="small-empty">
          请先在项目资料中建立包含招标文件与补遗的依据包。
        </p>
      )}
    </section>
  );
}
