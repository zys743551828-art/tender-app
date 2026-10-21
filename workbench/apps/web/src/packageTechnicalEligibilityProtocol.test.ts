import { describe, expect, it } from "vitest";
import type { PackageTechnicalScopeView } from "./contracts";
import { jsonDigest } from "./editorSchema";
import raw from "./test-fixtures/technical-eligibility-http.json";
import scaled from "./test-fixtures/technical-scale-http.json";
import { validateTechnicalEligibility } from "./packageTechnicalEligibilityProtocol";

const scope = raw.scope as unknown as PackageTechnicalScopeView;
const current = { purpose: "current_prebid", scaleId: null } as const;
const historical = {
  purpose: "historical_backtest",
  scaleId: null,
  submissionId: raw.sampleRequest.submission_id,
  outcomeId: raw.sampleRequest.outcome_id,
} as const;

async function tag(value: Record<string, unknown>, id = scope.manifest.id) {
  const stable = Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "observed_at"),
  );
  return `"package-technical-eligibility:${id}:${await jsonDigest(stable)}"`;
}

describe("exact technical eligibility protocol using real PG HTTP receipts", () => {
  it("accepts exact current and historical receipts without promoting an official zero", async () => {
    const scoring = await validateTechnicalEligibility(
      raw.scoringContext,
      raw.scoringEtag,
      scope,
      current,
    );
    const sample = await validateTechnicalEligibility(
      raw.sampleContext,
      raw.sampleEtag,
      scope,
      historical,
    );
    expect(scoring.numeric_prediction).toBeNull();
    expect(sample.purpose).toBe("historical_backtest");
    if (sample.purpose !== "historical_backtest") throw new Error("wrong mode");
    expect(sample.official_result.technical_value).toBe("0");
    expect(sample.training_eligible).toBe(false);
    expect(sample.sample_created).toBe(false);
  });

  it("accepts authority-bound maximum while keeping aggregation and numeric prediction unavailable", async () => {
    const result = await validateTechnicalEligibility(
      scaled.scoringContext,
      scaled.scoringEtag,
      scaled.scope as unknown as PackageTechnicalScopeView,
      { ...current, scaleId: scaled.scale.id },
    );
    expect(result.denominator.technical_maximum).toBe("60.00");
    expect(result.denominator.aggregation_usable).toBe(false);
    expect(result.numeric_prediction).toBeNull();
  });

  it("rejects another selected scale and a changed quoted block even with a new digest", async () => {
    await expect(
      validateTechnicalEligibility(raw.scoringContext, raw.scoringEtag, scope, {
        ...current,
        scaleId: scaled.scale.id,
      }),
    ).rejects.toThrow("不一致");
    const changed = structuredClone(scaled.scoringContext);
    changed.denominator.evidence_refs[0].quote = "技术总分满分为100分。";
    await expect(
      validateTechnicalEligibility(
        changed,
        await tag(changed, scaled.scope.manifest.id),
        scaled.scope as unknown as PackageTechnicalScopeView,
        { ...current, scaleId: scaled.scale.id },
      ),
    ).rejects.toThrow("不一致");
  });

  it("rejects hidden eligibility, predictions, leaked current labels and altered historical time", async () => {
    for (const patch of [
      { formal_scoring_eligible: true },
      { numeric_prediction: "42" },
      { official_result: raw.sampleContext.official_result },
    ]) {
      const changed = { ...structuredClone(raw.scoringContext), ...patch };
      await expect(
        validateTechnicalEligibility(
          changed,
          await tag(changed),
          scope,
          current,
        ),
      ).rejects.toThrow("不一致");
    }
    const changed = structuredClone(raw.sampleContext);
    changed.timing.scope_frozen_at = "2025-01-01T00:00:00Z";
    await expect(
      validateTechnicalEligibility(
        changed,
        await tag(changed),
        scope,
        historical,
      ),
    ).rejects.toThrow("不一致");
  });
});
