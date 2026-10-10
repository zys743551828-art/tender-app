import type { Fact } from '../../api/types';
import { confirmationLabel } from '../../lib/labels';

/** 从当前事实集里勾选事实；只有“已确认”的事实可选（不会引入未确认的参数）。 */
export function FactPicker({
  facts,
  selected,
  onChange,
  legend = '允许使用的事实',
}: {
  facts: Fact[];
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
  legend?: string;
}) {
  return (
    <fieldset className="mb-4 rounded-md border border-border px-3.5 pt-2 pb-3 [&_legend]:px-1 [&_legend]:text-[13px] [&_legend]:font-medium [&_label]:flex [&_label]:items-center [&_label]:gap-2 [&_label]:py-1 [&_label]:text-[13px]">
      <legend>{legend}</legend>
      {facts.map((f) => (
        <label key={f.fact_id}>
          <input
            type="checkbox"
            checked={selected.has(f.fact_id)}
            disabled={f.confirmation !== 'confirmed'}
            onChange={(e) => {
              const n = new Set(selected);
              if (e.target.checked) n.add(f.fact_id);
              else n.delete(f.fact_id);
              onChange(n);
            }}
          />
          <span>
            {f.name}：{f.statement}
            {f.confirmation !== 'confirmed' ? `（${confirmationLabel(f.confirmation)}）` : ''}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
