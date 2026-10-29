import type {
  PricePoint,
  PricingFrozenResult,
  PricingFormulaManifest,
  PricingRequest,
} from "./contracts";
import { Badge } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";

export function PricingResults({
  result,
  input,
  formula,
  stale = false,
}: {
  result: PricingFrozenResult;
  input: PricingRequest;
  formula: PricingFormulaManifest;
  stale?: boolean;
}) {
  return (
    <div className={`pricing-results ${stale ? "stale-result" : ""}`}>
      {stale && (
        <div className="notice warning" role="status">
          情景输入或依据已变化，以下保留上次结果，待更新。不能按旧曲线保存当前输入。
        </div>
      )}
      <div className="pricing-score">
        <div>
          <span>本方情景价格分</span>
          <strong>
            {result.price_score === null ? "未知" : result.price_score}
            <small> / {result.maximum}</small>
          </strong>
        </div>
        <Badge tone={result.eligible ? "" : "warning"}>
          {result.eligible ? "符合本公式价格区间" : "超出本公式价格区间"}
        </Badge>
      </div>
      <p className="small-note">
        本方 {result.candidate_price} {formula.amount_unit} ·{" "}
        {formula.currency === "CNY" ? "人民币" : "币种未知"}
        。价格区间判断仅属于本公式，不表示整体投标资格。
      </p>
      {result.notes.map((note, index) => (
        <p className="small-note" key={index}>
          {note}
        </p>
      ))}
      <p>
        本情景基准价 {result.baseline_price ?? "未知"} · 数值有效报价假设数{" "}
        {result.valid_price_count}（包含符合区间的本方报价）
      </p>
      <details>
        <summary>查看本情景计算步骤与假设</summary>
        <ol>
          {result.calculation_steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
        <p>
          对手报价仅为用户情景假设：
          {input.competitor_price_assumptions.length
            ? input.competitor_price_assumptions.join("、")
            : "未提供；不表示实际没有对手"}
          。
        </p>
        {result.assumptions.map((note, index) => (
          <p key={index}>{note}</p>
        ))}
        {result.excluded_competitor_assumptions.map((item, index) => (
          <p key={index}>
            对手假设第{item.index + 1}项 {item.price}：{item.reason}
          </p>
        ))}
      </details>
      <p className="small-note">{result.technical_exchange_note}</p>
      <EvidenceLinks
        ids={result.formula_evidence_ids}
        label="核对本次公式原页"
      />
      {result.curve.length > 0 && (
        <>
          <h3>候选价格曲线</h3>
          <PriceCurve points={result.curve} maximum={result.maximum} />
        </>
      )}
      {result.candidates.length > 0 && (
        <PointList points={result.candidates} label="补充候选比较" />
      )}
      {result.curve.length > 0 && (
        <details>
          <summary>查看曲线每点的独立基准价与步骤</summary>
          <PointList points={result.curve} label="曲线逐点数据" />
        </details>
      )}
    </div>
  );
}

function PointList({ points, label }: { points: PricePoint[]; label: string }) {
  return (
    <div className="pricing-points" aria-label={label}>
      {points.map((point, index) => (
        <article key={`${point.price}:${index}`}>
          <div className="section-heading">
            <strong>候选 {point.price}</strong>
            <span>价格分 {point.score === null ? "未知" : point.score}</span>
          </div>
          <p className="small-note">
            {point.eligible ? "符合本公式价格区间" : "超出本公式价格区间"} ·
            基准价 {point.baseline_price ?? "未知"} · 有效假设数{" "}
            {point.valid_price_count}
          </p>
          {point.notes.map((note, i) => (
            <p className="small-note" key={i}>
              {note}
            </p>
          ))}
          <details>
            <summary>此候选独立计算步骤</summary>
            <ol>
              {point.calculation_steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </details>
        </article>
      ))}
    </div>
  );
}

function PriceCurve({
  points,
  maximum,
}: {
  points: PricePoint[];
  maximum: string;
}) {
  const prices = points.map((point) => Number(point.price));
  const minimum = Math.min(...prices),
    range = Math.max(...prices) - minimum;
  const max = Number(maximum) || 1;
  const segments: string[][] = [];
  let segment: string[] = [];
  for (const point of points) {
    if (point.score === null) {
      if (segment.length) segments.push(segment);
      segment = [];
      continue;
    }
    segment.push(
      `${35 + ((Number(point.price) - minimum) / (range || 1)) * 510},${170 - (Number(point.score) / max) * 145}`,
    );
  }
  if (segment.length) segments.push(segment);
  return (
    <figure className="pricing-curve">
      <svg
        viewBox="0 0 580 205"
        role="img"
        aria-label="情景价格分曲线，未知点断开，非中标概率或最优报价"
      >
        <path d="M35 20V170H550" fill="none" stroke="var(--border-strong)" />
        {segments.map((coordinates, index) => (
          <g key={index}>
            <polyline
              points={coordinates.join(" ")}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="2"
            />
            {coordinates.map((coordinate, i) => {
              const [cx, cy] = coordinate.split(",");
              return (
                <circle key={i} cx={cx} cy={cy} r="2.5" fill="var(--primary)" />
              );
            })}
          </g>
        ))}
        <text x="4" y="24" fontSize="11">
          {maximum}
        </text>
        <text x="16" y="174" fontSize="11">
          0
        </text>
        <text x="35" y="193" fontSize="11">
          {points[0]?.price}
        </text>
        <text x="545" y="193" textAnchor="end" fontSize="11">
          {points.at(-1)?.price}
        </text>
      </svg>
      <figcaption className="small-note">
        每个点独立计算基准价；未知点断开，不按零分绘制。仅为用户情景，不提供最优报价或中标概率。
      </figcaption>
    </figure>
  );
}
