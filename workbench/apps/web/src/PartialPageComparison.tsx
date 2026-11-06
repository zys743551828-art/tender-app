import { useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import type { Selection } from "./PartialPageSelection";

type Candidate = {
  id: string;
  document_version_id: string;
  filename: string;
  purpose: "technical_reference" | "requirement_reference";
  first_page: number;
  last_page: number;
};
type Side = {
  selection: Selection;
  evidence: {
    selection_id: string;
    proof_digest: string;
    items: { id: string; physical_page: number; quote: string }[];
    model_execution_allowed: false;
    formal_qualification: false;
  };
};
type Comparison = {
  requirement: Side;
  technical: Side;
  coverage: "partial";
  overall_result: "unknown";
  model_execution_allowed: false;
  formal_qualification: false;
};

function consistent(side: Side, id: string) {
  const expected = new Map(
    side.selection.proof.manifest.selected_blocks.map((block) => [
      block.id,
      block.physical_page,
    ]),
  );
  return (
    side.selection.id === id &&
    side.selection.current_material &&
    side.evidence.selection_id === id &&
    side.evidence.proof_digest === side.selection.proof.digest &&
    side.evidence.model_execution_allowed === false &&
    side.evidence.formal_qualification === false &&
    side.evidence.items.length ===
      side.selection.proof.manifest.selected_blocks.length &&
    new Set(side.evidence.items.map((item) => item.id)).size ===
      side.evidence.items.length &&
    side.evidence.items.every(
      (item) => expected.get(item.id) === item.physical_page,
    )
  );
}

export function PartialPageComparison({
  path,
  selection,
}: {
  path: string;
  selection: Selection;
}) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [other, setOther] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);

  async function loadCandidates() {
    setBusy(true);
    setError(null);
    setComparison(null);
    setOther("");
    try {
      const value = (
        await api<{ items: Candidate[]; has_more: boolean }>(
          `${path}/candidates`,
        )
      ).data;
      setCandidates(
        value.items.filter(
          (item) =>
            item.id !== selection.id &&
            item.purpose !== selection.proof.manifest.purpose,
        ),
      );
      setLoaded(true);
      if (value.has_more)
        setError(new Error("只显示最近 100 条范围记录，较早记录未列出。"));
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  async function compare() {
    if (!candidates.some((item) => item.id === other)) return;
    setBusy(true);
    setError(null);
    setComparison(null);
    try {
      const requirement =
        selection.proof.manifest.purpose === "requirement_reference"
          ? selection.id
          : other;
      const technical =
        selection.proof.manifest.purpose === "technical_reference"
          ? selection.id
          : other;
      const value = (
        await api<Comparison>(`${path}/${requirement}/compare/${technical}`)
      ).data;
      if (
        value.coverage !== "partial" ||
        value.overall_result !== "unknown" ||
        value.model_execution_allowed !== false ||
        value.formal_qualification !== false ||
        !consistent(value.requirement, requirement) ||
        !consistent(value.technical, technical) ||
        (selection.id === requirement ? value.requirement : value.technical)
          .selection.proof.digest !== selection.proof.digest ||
        value.requirement.selection.proof.manifest.purpose !==
          "requirement_reference" ||
        value.technical.selection.proof.manifest.purpose !==
          "technical_reference"
      )
        throw new Error("对照范围或依据已变化，请重新核对。");
      setComparison(value);
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <button
        type="button"
        disabled={busy || !selection.current_material}
        onClick={() => void loadCandidates()}
      >
        选择另一份已确认范围进行人工对照
      </button>
      <ErrorNotice error={error} />
      {loaded && candidates.length === 0 && (
        <p>没有可选择的另一用途范围；请先在对应原件中确认范围。</p>
      )}
      {candidates.length > 0 && (
        <div>
          <label>
            另一范围
            <select
              value={other}
              onChange={(event) => {
                setOther(event.target.value);
                setComparison(null);
              }}
            >
              <option value="">请选择</option>
              {candidates.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.purpose === "requirement_reference"
                    ? "要求参考"
                    : "技术参考"}{" "}
                  · {item.filename} · {item.document_version_id.slice(0, 8)} ·
                  第 {item.first_page}–{item.last_page} 页
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || !other}
            onClick={() => void compare()}
          >
            打开范围对照
          </button>
        </div>
      )}
      {comparison && (
        <section aria-label="人工范围对照">
          <strong>人工范围对照 · 整体覆盖未知</strong>
          <p>
            只展示两次确认范围内的解析依据。来源有效性、原件字节及 OCR
            内容仍需核对；此处不生成判定或正式资格。
          </p>
          {([comparison.requirement, comparison.technical] as const).map(
            (side, index) => (
              <details key={side.selection.id}>
                <summary>
                  {index === 0 ? "要求参考" : "技术参考"} · 第{" "}
                  {side.selection.proof.manifest.selection.first_page}–
                  {side.selection.proof.manifest.selection.last_page} 页
                </summary>
                <p>
                  有缺口页：
                  {side.selection.proof.manifest.selected_pages
                    .filter(
                      (item) => item.quality !== "usable" || item.gaps.length,
                    )
                    .map((item) => item.physical_page)
                    .join("、") || "未报告"}
                  ；未选范围：
                  {side.selection.proof.manifest.omitted_ranges
                    .map((item) => `${item.first_page}–${item.last_page}`)
                    .join("、") || "无"}
                </p>
                {side.evidence.items.map((item) => (
                  <p key={item.id}>
                    第 {item.physical_page} 页：{item.quote}
                  </p>
                ))}
              </details>
            ),
          )}
        </section>
      )}
    </div>
  );
}
