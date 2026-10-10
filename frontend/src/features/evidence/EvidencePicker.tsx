import { useState } from 'react';
import { parseEvidenceIds } from '../facts/validate';
import { EvidenceSearch } from './search';
import { Button } from '../../components/ui/button';

/**
 * 证据选择器：检索证据并勾选，勾选结果写入“证据 ID”文本（仍可手填原始 ID）。
 * value 是文本框里的原始字符串，选择只增删对应的 ID，不改动用户手填的其他内容。
 */
export function EvidencePicker({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ids = parseEvidenceIds(value);
  const toggle = (id: string, on: boolean) => {
    const next = on ? [...ids, id] : ids.filter((x) => x !== id);
    onChange([...new Set(next)].join(', '));
  };
  return (
    <div className="mb-4">
      <Button
        size="sm"
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
        }}
      >
        {open ? '收起证据检索' : '从检索结果中选择证据'}
      </Button>
      {open ? (
        <div className="mt-3 rounded-md border border-border p-3">
          <EvidenceSearch
            projectId={projectId}
            compact
            renderAction={(h) => (
              <label className="inline-flex items-center gap-1.5 text-[13px]">
                <input
                  type="checkbox"
                  checked={ids.includes(h.evidence.evidence_id)}
                  onChange={(e) => {
                    toggle(h.evidence.evidence_id, e.target.checked);
                  }}
                />{' '}
                选用这条证据
              </label>
            )}
          />
        </div>
      ) : null}
    </div>
  );
}
