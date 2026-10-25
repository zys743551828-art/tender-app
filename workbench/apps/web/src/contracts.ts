// Generated from packages/contracts/fusion-implemented.openapi.json.gz. Run python scripts/generate-contracts.py.

export type PackageNextActions = {
  version: "package-next-actions/1";
  binding: {
    scope: {
      bid_id: string;
      package_id: string;
      revision_id: string;
      inventory_id: string;
    };
    run_id: string;
    input_digest: string;
    result_digest: string | null;
    frozen_input_id: string;
    execution_input_id: string;
    dependency_plan_id: string;
    frozen_input_digest: string;
    execution_input_digest: string;
    dependency_plan_digest: string;
    method_digest: string;
  };
  method_digest: string;
  confirmation_digest: string;
  basis_digest: string;
  basis_status: "matched" | "changed" | "unknown" | "archived";
  basis_issues: {
    dimension: string;
    status: "changed" | "unknown";
    message: string;
  }[];
  observation_digest: string;
  observed_at: string;
  current_scope_counts: {
    critical: number;
    suggestions: number;
    pending_critical_rules: number;
  } | null;
  historical_scope_counts: {
    critical: number;
    suggestions: number;
  } | null;
  primary: {
    level: number;
    key:
      | "inspect_changed_basis"
      | "inspect_unknown_basis"
      | "view_archived_run"
      | "inspect_failed_run"
      | "observe_run"
      | "inspect_coverage_gaps"
      | "inspect_critical_risks"
      | "confirm_critical_rules"
      | "inspect_scoring_scope"
      | "inspect_advisories"
      | "inspect_package_limitations";
    title: string;
    requirement_ids: string[];
    item_count: number | null;
  };
  other_actions: {
    level: number;
    key:
      | "inspect_changed_basis"
      | "inspect_unknown_basis"
      | "view_archived_run"
      | "inspect_failed_run"
      | "observe_run"
      | "inspect_coverage_gaps"
      | "inspect_critical_risks"
      | "confirm_critical_rules"
      | "inspect_scoring_scope"
      | "inspect_advisories"
      | "inspect_package_limitations";
    title: string;
    requirement_ids: string[];
    item_count: number | null;
  }[];
  remaining_critical_count: number | null;
  remaining_suggestion_count: number | null;
  action_mode: "navigation_only";
  perspective: "selected_declared_scope";
  original_bytes_reverified: false;
  inventory_complete: false;
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type ProjectWorkSummary = {
  bid_id: string;
  phase: "preparation" | "working" | "submitted" | "closed" | "terminated";
  archived_at: string | null;
  package_counts: {
    authority: number;
    bid: number;
  };
  head_members: {
    total: number;
    parse_not_frozen: number;
  };
  next_action: {
    action:
      | "view_history"
      | "assemble_packages"
      | "inspect_package_parses"
      | "choose_package_revision";
    reason: string;
    target_url: string;
    blocked: boolean;
  };
  action_scope: "package_directory";
  risk_status: "not_evaluated";
  critical_risk_count: null;
  other_risk_count: null;
  prediction_status: "not_evaluated";
  predicted_score: null;
  inventory_complete: false;
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type ProjectWorkSummaryBatch = {
  version: "project-work-summary/1";
  observed_at: string;
  items: ProjectWorkSummary[];
};

export type PackageHistoricalAdmissionContext = {
  schema: "package-historical-admission-context/1";
  schema_configured: boolean;
  scope_id: string;
  submission_id: string;
  outcome_id: string;
  context_digest: string | null;
  official_technical_value: string | null;
  official_maximum: string | null;
  historical_as_of: string | null;
  scope_frozen_at: string | null;
  label_known_at: string | null;
  proofs: {
    id: string;
    origin: "synthetic" | "external_evidence";
    adapter_id: string;
    verified_at: string;
    context_digest: string;
  }[];
  blockers: {
    code: string;
    message: string;
  }[];
  observed_at: string;
  research_only: true;
  formal_eligibility: "unavailable";
  strict_prebid_eligible: false;
  online_metrics_eligible: false;
  formal_sample_created: false;
};

export type PackageHistoricalAdmission = {
  schema: "package-historical-research-admission/1";
  id: string;
  proof_id: string;
  bid_id: string;
  scope_id: string;
  submission_id: string;
  outcome_id: string;
  scope_digest: string;
  submission_binding_digest: string;
  context_digest: string;
  proof_digest: string;
  digest: string;
  origin: "synthetic" | "external_evidence";
  state: "mechanism_candidate" | "retrospective_candidate";
  historical_as_of: string;
  scope_frozen_at: string;
  label_known_at: string;
  evidence_verified_at: string;
  admitted_at: string;
  official_technical_value: string;
  technical_maximum: string;
  aggregation: "published_final_technical_total";
  training_selected: false;
  research_only: true;
  formal_eligibility: "unavailable";
  strict_prebid_eligible: false;
  online_metrics_eligible: false;
  formal_sample_created: false;
};

export type PackageHistoricalAdmissionView = {
  admission: {
    schema: "package-historical-research-admission/1";
    id: string;
    proof_id: string;
    bid_id: string;
    scope_id: string;
    submission_id: string;
    outcome_id: string;
    scope_digest: string;
    submission_binding_digest: string;
    context_digest: string;
    proof_digest: string;
    digest: string;
    origin: "synthetic" | "external_evidence";
    state: "mechanism_candidate" | "retrospective_candidate";
    historical_as_of: string;
    scope_frozen_at: string;
    label_known_at: string;
    evidence_verified_at: string;
    admitted_at: string;
    official_technical_value: string;
    technical_maximum: string;
    aggregation: "published_final_technical_total";
    training_selected: false;
    research_only: true;
    formal_eligibility: "unavailable";
    strict_prebid_eligible: false;
    online_metrics_eligible: false;
    formal_sample_created: false;
  };
  current: boolean;
};

export type PackageHistoricalProtocol = {
  id: string;
  document: {
    schema: "package-history-cpu-protocol/1";
    method: {
      version: "package-history-project-baselines/1";
      purpose: "retrospective_research";
      features: "not_required_by_constant_baselines";
      provider_requests: 0;
      digest: string;
      sources: {
        "packages/model_governance/package_history_cpu.py": string;
        "packages/model_governance/common.py": string;
        "packages/model_governance/evaluation.py": string;
        "packages/model_governance/statistics.py": string;
      };
    };
    families: ["mean", "median"];
    selection_metric: "project_mae";
    tie_order: ["mean", "median"];
    refit_with_development: false;
    interval_levels: [0.8, 0.9];
    group_spanning_policy: "exclude";
    seed: number;
    bootstrap_iterations: number;
  };
  digest: string;
  research_only: true;
  formal_eligibility: "unavailable";
};

export type PackageHistoricalProtocolTemplate = {
  schema_configured: boolean;
  document: {
    schema: "package-history-cpu-protocol/1";
    method: {
      version: "package-history-project-baselines/1";
      purpose: "retrospective_research";
      features: "not_required_by_constant_baselines";
      provider_requests: 0;
      digest: string;
      sources: {
        "packages/model_governance/package_history_cpu.py": string;
        "packages/model_governance/common.py": string;
        "packages/model_governance/evaluation.py": string;
        "packages/model_governance/statistics.py": string;
      };
    };
    families: ["mean", "median"];
    selection_metric: "project_mae";
    tie_order: ["mean", "median"];
    refit_with_development: false;
    interval_levels: [0.8, 0.9];
    group_spanning_policy: "exclude";
    seed: number;
    bootstrap_iterations: number;
  };
  method_digest: string;
  signed_proof_public_upload: false;
  feature_calibration_available: false;
  research_only: true;
  formal_eligibility: "unavailable";
};

export type PackageHistoricalCohort = {
  schema: "package-history-cohort/1";
  id: string;
  protocol_id: string;
  protocol_digest: string;
  origin: "synthetic" | "external_evidence";
  timing: {
    mode: "retrospective_submission_time_holdout";
    historical_as_of: "per_exact_actual_submission";
    submission_split_at: string;
    label_available_as_of: string;
    training_frozen_at: string;
    group_spanning_policy: "exclude";
    prediction_timing: "retrospective";
  };
  members: {
    admission_id: string;
    proof_id: string;
    submission_id: string;
    group_id: string;
    closure_ids: string[];
    requested_purpose: "fit" | "development" | "calibration" | "final";
    purpose: "fit" | "development" | "calibration" | "final" | "excluded";
    exclusion_reason:
      | "group_spans_submission_split"
      | "label_after_available_cutoff"
      | null;
    submitted_at: string;
    label_known_at: string;
  }[];
  membership_digest: string;
  digest: string;
  research_only: true;
  formal_eligibility: "unavailable";
  strict_prebid_eligible: false;
  online_metrics_eligible: false;
  formal_sample_created: false;
};

export type PackageHistoricalCohortView = {
  cohort: {
    schema: "package-history-cohort/1";
    id: string;
    protocol_id: string;
    protocol_digest: string;
    origin: "synthetic" | "external_evidence";
    timing: {
      mode: "retrospective_submission_time_holdout";
      historical_as_of: "per_exact_actual_submission";
      submission_split_at: string;
      label_available_as_of: string;
      training_frozen_at: string;
      group_spanning_policy: "exclude";
      prediction_timing: "retrospective";
    };
    members: {
      admission_id: string;
      proof_id: string;
      submission_id: string;
      group_id: string;
      closure_ids: string[];
      requested_purpose: "fit" | "development" | "calibration" | "final";
      purpose: "fit" | "development" | "calibration" | "final" | "excluded";
      exclusion_reason:
        | "group_spans_submission_split"
        | "label_after_available_cutoff"
        | null;
      submitted_at: string;
      label_known_at: string;
    }[];
    membership_digest: string;
    digest: string;
    research_only: true;
    formal_eligibility: "unavailable";
    strict_prebid_eligible: false;
    online_metrics_eligible: false;
    formal_sample_created: false;
  };
  current: boolean;
};

export type PackageHistoricalJob = {
  job_id: string;
  cohort_id: string;
  kind: "train" | "evaluate";
  state: "queued" | "running" | "paused" | "succeeded" | "failed" | "cancelled";
  generation: number;
  research_only: true;
  formal_eligibility: "unavailable";
};

export type PackageHistoricalJobView = {
  job_id: string;
  cohort_id: string;
  kind: "train" | "evaluate";
  state: "queued" | "running" | "paused" | "succeeded" | "failed" | "cancelled";
  generation: number;
  research_only: true;
  formal_eligibility: "unavailable";
  current: boolean;
  result:
    | (
        | {
            schema: "package-history-training-result/1";
            origin: "synthetic" | "external_evidence";
            cohort_id: string;
            protocol_digest: string;
            training_export_digest: string;
            membership_digest: string;
            model_digest: string;
            model: {
              schema: "package-history-constant-model/1";
              method_digest: string;
              family: "mean" | "median";
              constant: string;
              training_export_digest: string;
            };
            baselines: {
              mean: string;
              median: string;
            };
            selection: {
              development_project_mae: {
                mean: string;
                median: string;
              };
              selected: "mean" | "median";
              refit_with_development: false;
            };
            intervals: {
              "0.8": {
                radius: string | null;
                groups: number;
                rank: number;
                unavailable_reason:
                  | "insufficient_independent_calibration_groups"
                  | null;
              };
              "0.9": {
                radius: string | null;
                groups: number;
                rank: number;
                unavailable_reason:
                  | "insufficient_independent_calibration_groups"
                  | null;
              };
            };
            research_only: true;
            formal_eligibility: "unavailable";
            provider_requests: 0;
            paid_calls: 0;
          }
        | {
            schema: "package-history-independent-evaluation/1";
            origin: "synthetic" | "external_evidence";
            cohort_id: string;
            protocol_digest: string;
            model_digest: string;
            membership_digest: string;
            predictions_digest: string;
            labels_digest: string;
            timing: {
              mode: "retrospective_submission_time_holdout";
              historical_as_of: "per_exact_actual_submission";
              submission_split_at: string;
              label_available_as_of: string;
              training_frozen_at: string;
              group_spanning_policy: "exclude";
              prediction_timing: "retrospective";
            };
            selection_denominator: {
              selected_submissions: number;
              excluded_submissions: number;
              final_side_candidates: number;
            };
            report: {
              denominator: number;
              independent_groups: number;
              projects: number;
              counts: {
                succeeded: number;
                failed: number;
                rejected: number;
                unlabeled: number;
              };
              success_coverage: string | null;
              sample_mae: string | null;
              project_mae: string | null;
              original_scale_project_mae: string | null;
              p90_absolute_error: string | null;
              project_within_three: string | null;
              project_bias: string | null;
              intervals: {
                "0.8":
                  | {
                      coverage: string;
                      width: string;
                    }
                  | {
                      coverage: null;
                      width: null;
                      reason: "interval_or_labeled_predictions_unavailable";
                    };
                "0.9":
                  | {
                      coverage: string;
                      width: string;
                    }
                  | {
                      coverage: null;
                      width: null;
                      reason: "interval_or_labeled_predictions_unavailable";
                    };
              };
              paired_baselines: {
                mean?:
                  | {
                      gain: string;
                      paired_count: number;
                      group_bootstrap_gain_95: string[] | null;
                    }
                  | {
                      gain: null;
                      reason: "paired_baseline_missing";
                    };
                median?:
                  | {
                      gain: string;
                      paired_count: number;
                      group_bootstrap_gain_95: string[] | null;
                    }
                  | {
                      gain: null;
                      reason: "paired_baseline_missing";
                    };
              };
              group_bootstrap_project_mae_95: string[] | null;
              stability_range_p90: null;
              strata: {
                method: {
                  [key: string]: {
                    count: number;
                    project_mae: string | null;
                  };
                };
                maximum: {
                  [key: string]: {
                    count: number;
                    project_mae: string | null;
                  };
                };
                engineering_type: {
                  [key: string]: {
                    count: number;
                    project_mae: string | null;
                  };
                };
              };
              unavailable_statistics: [
                "ranking_without_ranking_labels",
                "shortlist_probability_without_labels",
                "judge_disagreement_without_judge_labels",
                "whole_round_stability_without_independent_repeat_predictions",
              ];
            };
            official_source_subset: {
              scope: "verified_official_associations_with_evidence_backed_admission";
              origin: "synthetic" | "external_evidence";
              report: {
                denominator: number;
                independent_groups: number;
                projects: number;
                counts: {
                  succeeded: number;
                  failed: number;
                  rejected: number;
                  unlabeled: number;
                };
                success_coverage: string | null;
                sample_mae: string | null;
                project_mae: string | null;
                original_scale_project_mae: string | null;
                p90_absolute_error: string | null;
                project_within_three: string | null;
                project_bias: string | null;
                intervals: {
                  "0.8":
                    | {
                        coverage: string;
                        width: string;
                      }
                    | {
                        coverage: null;
                        width: null;
                        reason: "interval_or_labeled_predictions_unavailable";
                      };
                  "0.9":
                    | {
                        coverage: string;
                        width: string;
                      }
                    | {
                        coverage: null;
                        width: null;
                        reason: "interval_or_labeled_predictions_unavailable";
                      };
                };
                paired_baselines: {
                  mean?:
                    | {
                        gain: string;
                        paired_count: number;
                        group_bootstrap_gain_95: string[] | null;
                      }
                    | {
                        gain: null;
                        reason: "paired_baseline_missing";
                      };
                  median?:
                    | {
                        gain: string;
                        paired_count: number;
                        group_bootstrap_gain_95: string[] | null;
                      }
                    | {
                        gain: null;
                        reason: "paired_baseline_missing";
                      };
                };
                group_bootstrap_project_mae_95: string[] | null;
                stability_range_p90: null;
                strata: {
                  method: {
                    [key: string]: {
                      count: number;
                      project_mae: string | null;
                    };
                  };
                  maximum: {
                    [key: string]: {
                      count: number;
                      project_mae: string | null;
                    };
                  };
                  engineering_type: {
                    [key: string]: {
                      count: number;
                      project_mae: string | null;
                    };
                  };
                };
                unavailable_statistics: [
                  "ranking_without_ranking_labels",
                  "shortlist_probability_without_labels",
                  "judge_disagreement_without_judge_labels",
                  "whole_round_stability_without_independent_repeat_predictions",
                ];
              };
            };
            research_only: true;
            formal_eligibility: "unavailable";
            acceptance_decision: "unavailable";
            missing_acceptance: [
              "real_independent_quality_validation",
              "complete_package_three_judgment_features",
              "preexposure_business_certification",
              "independent_repeat_stability",
              "observation_and_release_authority",
            ];
            provider_requests: 0;
            paid_calls: 0;
          }
      )
    | null;
  result_digest: string | null;
};

export type PackageHistoryAdmissionRequest = {
  submission_id: string;
  outcome_id: string;
  proof_id: string;
  context_digest: string;
  reason: string;
};

export type PackageHistoryProtocolRequest = {
  method_digest: string;
  seed: number;
  bootstrap_iterations: number;
  reason: string;
};

export type PackageHistoryCohortRequest = {
  protocol_id: string;
  submission_split_at: string;
  label_available_as_of: string;
  selections: PackageHistorySelection[];
  reason: string;
};

export type PackageHistoryJobRequest = {
  kind: "train" | "evaluate";
  reason: string;
};

export type PackageHistoryJobControl = {
  action: "pause" | "resume" | "cancel";
  generation: number;
  reason: string;
};

export type PackageHistoryAdmissionDirectory =
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "admissions";
      status: "observed";
      schema_configured: true;
      items: {
        id: string;
        created_at: string;
        current_status: "not_rechecked";
        kind: "admission";
        bid_id: string;
        scope_id: string;
        submission_id: string;
        outcome_id: string;
        digest: string;
        origin: "synthetic" | "external_evidence";
        state: "mechanism_candidate" | "retrospective_candidate";
        historical_as_of: string;
        label_known_at: string;
      }[];
      total: number;
      observation_digest: string;
      complete_observation: true;
      has_more: boolean;
      next_cursor: string | null;
    }
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "admissions";
      status: "unavailable";
      schema_configured: false;
      items: [];
      total: null;
      observation_digest: null;
      complete_observation: false;
      has_more: null;
      next_cursor: null;
    };

export type PackageHistoryProtocolDirectory =
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "protocols";
      status: "observed";
      schema_configured: true;
      items: {
        id: string;
        created_at: string;
        current_status: "not_rechecked";
        kind: "protocol";
        digest: string;
        document: {
          schema: "package-history-cpu-protocol/1";
          method: {
            version: "package-history-project-baselines/1";
            purpose: "retrospective_research";
            features: "not_required_by_constant_baselines";
            provider_requests: 0;
            digest: string;
            sources: {
              "packages/model_governance/package_history_cpu.py": string;
              "packages/model_governance/common.py": string;
              "packages/model_governance/evaluation.py": string;
              "packages/model_governance/statistics.py": string;
            };
          };
          families: ["mean", "median"];
          selection_metric: "project_mae";
          tie_order: ["mean", "median"];
          refit_with_development: false;
          interval_levels: [0.8, 0.9];
          group_spanning_policy: "exclude";
          seed: number;
          bootstrap_iterations: number;
        };
      }[];
      total: number;
      observation_digest: string;
      complete_observation: true;
      has_more: boolean;
      next_cursor: string | null;
    }
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "protocols";
      status: "unavailable";
      schema_configured: false;
      items: [];
      total: null;
      observation_digest: null;
      complete_observation: false;
      has_more: null;
      next_cursor: null;
    };

export type PackageHistoryCohortDirectory =
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "cohorts";
      status: "observed";
      schema_configured: true;
      items: {
        id: string;
        created_at: string;
        current_status: "not_rechecked";
        kind: "cohort";
        protocol_id: string;
        digest: string;
        membership_digest: string;
        origin: "synthetic" | "external_evidence";
        submission_split_at: string;
        label_available_as_of: string;
        member_count: number;
      }[];
      total: number;
      observation_digest: string;
      complete_observation: true;
      has_more: boolean;
      next_cursor: string | null;
    }
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "cohorts";
      status: "unavailable";
      schema_configured: false;
      items: [];
      total: null;
      observation_digest: null;
      complete_observation: false;
      has_more: null;
      next_cursor: null;
    };

export type PackageHistoryJobDirectory =
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "jobs";
      status: "observed";
      schema_configured: true;
      items: {
        id: string;
        created_at: string;
        current_status: "not_rechecked";
        kind: "job";
        cohort_id: string;
        job_kind: "train" | "evaluate";
        state:
          | "queued"
          | "running"
          | "paused"
          | "succeeded"
          | "failed"
          | "cancelled";
        generation: number;
        result_available: boolean;
        result_digest: string | null;
      }[];
      total: number;
      observation_digest: string;
      complete_observation: true;
      has_more: boolean;
      next_cursor: string | null;
    }
  | {
      version: "package-history-directory/1";
      filters: {
        bid_id: string | null;
        scope_id: string | null;
        protocol_id: string | null;
        cohort_id: string | null;
      };
      observed_at: string;
      currentness_rechecked: false;
      research_only: true;
      formal_eligibility: "unavailable";
      qualification_granted: false;
      kind: "jobs";
      status: "unavailable";
      schema_configured: false;
      items: [];
      total: null;
      observation_digest: null;
      complete_observation: false;
      has_more: null;
      next_cursor: null;
    };

export type AuthoringHistoricalSectionView = {
  version: "authoring-historical-section/1";
  bid_id: string;
  draft_id: string;
  section_id: string;
  section_revision_id: string;
  revision: number;
  schema_digest: string;
  digest: string;
  content: AuthoringHistoryAuthoringRichDocument;
  created_by: string;
  created_at: string;
  images: {
    asset_id: string;
    asset_revision: number;
    asset_version_id: string;
    version_digest: string;
    normalized_sha256: string;
    media_type: "image/png";
  }[];
  read_only: true;
  source_qualification_assessed: false;
  restoration_authorized: false;
};

export type AuthoringExactRevisionCapabilities = {
  protocol: "authoring-exact-revision-capabilities/1";
  apply_available: boolean;
  build_available: boolean;
  ordinary_edit_available: false;
  supported_content: "plain_text_stable_node";
  blocking_reasons: string[];
};

export type AuthoringExactDraftStatus = {
  protocol: "authoring-exact-draft-status/1";
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  exact_sections: AuthoringExactSectionBinding[];
  ordinary_edit_available: boolean;
  build_available: boolean;
  blocking_reasons: string[];
};

export type AuthoringExactRevisionView = {
  manifest: AuthoringExactRevisionManifest;
  digest: string;
};

export type AuthoringExactManualRevisionView = {
  manifest: AuthoringExactManualRevisionManifest;
  digest: string;
};

export type AuthoringExactTextEditCapabilities = {
  protocol: "authoring-exact-text-edit-capabilities/1";
  available: boolean;
  supported_content: "plain_text_stable_node";
  preserves_source_refs: true;
  preserves_rule_ids: true;
  ordinary_edit_available: false;
  blocking_reasons: string[];
};

export type AuthoringExactTextEditRequest = {
  base_draft_revision: number;
  section_revision_id: string;
  node_id: string;
  before_node_digest: string;
  replacement_text: string;
  reason: string;
};

export type AuthoringExactTextEditResult = {
  protocol: "authoring-exact-text-edit-result/1";
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  parent_section_revision_id: string;
  section_revision_id: string;
  section_digest: string;
  qualification: AuthoringExactManualRevisionView;
};

export type AuthoringExactSectionBinding = {
  section_id: string;
  section_revision_id: string;
  section_revision: number;
  section_digest: string;
  qualification_id: string;
  qualification_digest: string;
  authoring_input_id: string;
  authoring_input_digest: string;
  source_scope: "exact_package_context";
};

export type PackageAuthoringNodeCatalog = {
  protocol: "package-authoring-node-catalog/1";
  bid_id: string;
  target: {
    draft_id: string;
    snapshot_id: string;
    snapshot_digest: string;
    base_draft_revision: number;
    section_id: string;
    section_revision_id: string;
    base_section_revision: number;
    section_digest: string;
    schema_digest: string;
  };
  section_title: string;
  section_content: AuthoringHistoryAuthoringRichDocument;
  nodes: {
    node_id: string;
    before_node_digest: string;
    node_type: "paragraph" | "heading";
    text: string;
  }[];
  unsupported_stable_node_count: number;
  current_draft_revision: number;
  section_heads: {
    section_id: string;
    selected_revision: number;
    head_revision: number;
  }[];
  whole_snapshot_plain: boolean;
  structure_supported: boolean;
  blocking_reasons: string[];
  observed_at: string;
  observation_digest: string;
  observation_only: true;
  admission_granted: false;
  original_bytes_reverified: false;
  save_recheck_required: true;
  formal_decisions_allowed: false;
};

export type PackageAuthoringFactSetPage = {
  protocol: "package-authoring-fact-set-page/1";
  bid_id: string;
  items: {
    fact_set_id: string;
    fact_set_digest: string;
    fact_count: number;
    is_current: boolean;
  }[];
  current_head: {
    fact_set_id: string;
    revision: number;
    fact_set_digest: string;
  } | null;
  blocking_reasons: string[];
  next_cursor: string | null;
  has_more: boolean;
  total_items: number;
  observed_at: string;
  observation_digest: string;
  observation_only: true;
  admission_granted: false;
  original_bytes_reverified: false;
  save_recheck_required: true;
  formal_decisions_allowed: false;
};

export type PackageAuthoringFactCatalog = {
  protocol: "package-authoring-fact-catalog/1";
  bid_id: string;
  selection: {
    fact_set_id: string;
    fact_set_digest: string;
    fact_head_revision: number;
    target: {
      package_id: string;
      revision_id: string;
      manifest_digest: string;
    };
    authority: {
      package_id: string;
      revision_id: string;
      manifest_digest: string;
    };
  };
  current_head: {
    fact_set_id: string;
    revision: number;
    fact_set_digest: string;
  } | null;
  head_matches: boolean;
  package_identity_matches: boolean;
  subject_choices: {
    kind: "engineering_project" | "lot" | "round" | "bidder";
    id: string;
  }[];
  identity_names: [
    "procurement_issuer_identifier",
    "procurement_project_identifier",
    "procurement_lot_identifier",
    "procurement_round_identifier",
    "bidder_identity_identifier",
  ];
  items: {
    fact_id: string;
    fact_item_digest: string;
    proof_digest: string;
    name: string;
    subject_text: string;
    scope_text: string;
    value_jsonb_text: string;
    unit: string | null;
    identity_name:
      | "procurement_issuer_identifier"
      | "procurement_project_identifier"
      | "procurement_lot_identifier"
      | "procurement_round_identifier"
      | "bidder_identity_identifier"
      | null;
    identity_value_usable: boolean;
    decision: {
      id: string;
      decision: "confirmed" | "rejected";
      decision_revision: number;
      object_id: string;
      actor_id: string;
      created_at: string;
      binding_verified: boolean;
      basis_verified: boolean;
      carryover_steps: number;
    } | null;
    evidence: {
      id: string;
      parse_id: string;
      document_version_id: string;
      physical_page: number;
      digest: string;
    }[];
    provenance_status: "verified" | "unproven";
    scope_binding: "selected_frozen_parse" | "unproven";
    facts_qualified: false;
    blocking_reasons: string[];
  }[];
  blocking_reasons: string[];
  next_cursor: string | null;
  has_more: boolean;
  total_items: number;
  observed_at: string;
  observation_digest: string;
  observation_only: true;
  admission_granted: false;
  original_bytes_reverified: false;
  save_recheck_required: true;
  formal_decisions_allowed: false;
};

export type PackageAuthoringSelection = {
  authoring_input_id: string;
  authoring_input_digest: string;
};

export type ExactPackageAuthoringSelection = {
  mode: "exact_package_authoring";
  input: PackageAuthoringSelection;
};

export type TaskPackageAuthoringResult = {
  schema: "task-package-authoring-result/1";
  job_id: string;
  job_input_digest: string;
  writing_plan_id: string;
  operation_id: string;
  job_ref: string;
  section_id: string;
  base_section_revision: number;
  authoring_input_id: string;
  authoring_input_digest: string;
  context_digest: string;
  publication_state: "pending" | "published" | "stale" | "failed";
  candidate_digest: string | null;
  action_id: string | null;
  action_ref: string | null;
  source_scope: "exact_package_context";
  automatic_apply: false;
  apply_available: false;
  build_available: false;
};

export type PackageTaskAuthoringCapabilities = {
  available: boolean;
  reason: string | null;
  input_mode: "exact_package_authoring";
  trigger: "manual";
  source_scope: "exact_package_context";
  automatic_input_selection: false;
  rerun_supported: false;
  apply_available: false;
  build_available: false;
};

export type PackageAuthoringInputRequest = {
  protocol: "package-authoring-input-request/1";
  purpose: "authoring";
  target_relation: "draft_using_package_context";
  package_context: PackageContext;
  target_section: SectionSelection;
  facts: FactSelection;
};

export type PackageAuthoringInputCapabilities = {
  protocol: "package-authoring-input-capabilities/1";
  capture_available: boolean;
  generation_available: false;
  publication_available: false;
  apply_available: false;
  build_available: false;
  automatic_input_selection: false;
  supported_target: "plain_text_stable_node";
  target_relation: "draft_using_package_context";
  context_limit_bytes: number;
  blocking_reasons: string[];
};

export type PackageAuthoringInputView = {
  manifest: { [key: string]: unknown };
  digest: string;
};

export type PackageAuthoringInputPage = {
  items: PackageAuthoringInputView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type PackageAuthoringInputContext = {
  input_id: string;
  input_digest: string;
  stored_context_digest: string;
  context: { [key: string]: unknown };
  redacted_fields: "documents[*].object_key"[];
  original_bytes_reverified: false;
};

export type PackageAuthoringInputCheck = {
  input_digest: string;
};

export type PackageAuthoringInputStatus = {
  protocol: "package-authoring-input-status/1";
  input_id: string;
  input_digest: string;
  current_input_matches: boolean;
  original_bytes_reverified: false;
  checked_at: string;
  generation_available: false;
  publication_available: false;
  apply_available: false;
  build_available: false;
  blocking_reasons: string[];
};

export type PackageAuthoringFactWithdrawal = {
  input_digest: string;
  fact_id: string;
  declaration_digest: string;
  reason: string;
};

export type PackageAuthoringFactScopeView = {
  manifest: { [key: string]: unknown };
  digest: string;
};

export type AuthoringWorkContext = {
  version: "authoring-work-context/1";
  selection:
    | {
        kind: "draft_snapshot";
        bid_id: string;
        draft_id: string;
        draft_revision: number;
        snapshot_id: string;
        snapshot_digest: string;
      }
    | {
        kind: "build";
        bid_id: string;
        build_id: string;
        draft_id: string;
        draft_revision: number;
        snapshot_id: string;
        snapshot_digest: string;
        build_input_id: string;
        input_digest: string;
        manifest_digest: string;
        writer_kind: string;
      };
  selection_digest: string;
  observed_at: string;
  observation_digest: string;
  snapshot: {
    bid_id: string;
    draft_id: string;
    draft_revision: number;
    snapshot_id: string;
    snapshot_digest: string;
    title: string;
    created_at: string;
    section_count: number;
  };
  document: {
    sections: {
      section_id: string;
      section_revision_id: string;
      section_revision: number;
      schema_digest: string;
      digest: string;
      ordinal: number;
      title: string;
      content: WorkContextReadOnlyAuthoringRichDocument;
    }[];
    outline:
      | {
          section_id: string;
          parent_id: string | null;
          ordinal: number;
          node_type: "chapter" | "appendix";
        }[]
      | null;
    images: {
      asset_id: string;
      asset_revision: number;
      asset_version_id: string;
      version_digest: string;
      normalized_sha256: string;
      media_type: "image/png";
    }[];
    editable: false;
  } | null;
  build: {
    operation_id: string;
    operation_state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    created_at: string;
    outputs: {
      format: "docx" | "pdf";
      requested: boolean;
      state: "pending" | "succeeded" | "failed" | "not_published";
      document: {
        document_version_id: string;
        sha256: string;
        byte_size: number;
        media_type:
          | "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          | "application/pdf";
        publication_proof_digest: string;
      } | null;
      gaps: string[];
    }[];
  } | null;
  current_observation: {
    draft_head: {
      status: "matched" | "changed" | "unknown" | "not_applicable";
      selected_digest: string | null;
      observed_digest: string | null;
      reason: string;
    };
    sources: {
      status: "matched" | "changed" | "unknown" | "not_applicable";
      selected_digest: string | null;
      observed_digest: string | null;
      reason: string;
    };
    assets: {
      status: "matched" | "changed" | "unknown" | "not_applicable";
      selected_digest: string | null;
      observed_digest: string | null;
      reason: string;
    };
  };
  summary: {
    perspective: "saved_authoring_history";
    whole_package_blocking_risk_count: null;
    whole_package_passed: null;
    formal_scoring: {
      status: "scope_not_selected";
      scope_id: null;
      numeric_prediction: null;
    };
    official_labels_read: false;
    primary_action: "open_selected_snapshot" | "view_selected_build";
    action_mode: "navigation_only";
  };
  native_targets: {
    draft_snapshot: {
      kind: "draft_snapshot";
      bid_id: string;
      draft_id: string;
      draft_revision: number;
      snapshot_id: string;
      snapshot_digest: string;
    };
    current_draft: {
      kind: "draft";
      bid_id: string;
      draft_id: string;
    };
    build: {
      kind: "build";
      bid_id: string;
      build_id: string;
      draft_id: string;
      draft_revision: number;
      snapshot_id: string;
      snapshot_digest: string;
      build_input_id: string;
      input_digest: string;
      manifest_digest: string;
      writer_kind: string;
    } | null;
    build_relations: {
      kind: "build_package_relations";
      bid_id: string;
      build_id: string;
    } | null;
  };
  original_bytes_reverified: false;
  qualification_assessed: false;
  limitations: string[];
};

export type WorkContextChoicePage = {
  version: "work-context-choice-page/1";
  bid_id: string;
  kind:
    | "draft_snapshot"
    | "build"
    | "package_review_run"
    | "package_submission";
  filters: {
    draft_id: string | null;
    package_id: string | null;
    revision_id: string | null;
  };
  observed_at: string;
  observation_digest: string;
  items: {
    kind:
      | "draft_snapshot"
      | "build"
      | "package_review_run"
      | "package_submission";
    id: string;
    label: string;
    created_at: string;
    status:
      | "saved"
      | "standard"
      | "offline_fact"
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    selection:
      | {
          kind: "draft_snapshot";
          bid_id: string;
          draft_id: string;
          draft_revision: number;
          snapshot_id: string;
          snapshot_digest: string;
        }
      | {
          kind: "build";
          bid_id: string;
          build_id: string;
          draft_id: string;
          draft_revision: number;
          snapshot_id: string;
          snapshot_digest: string;
          build_input_id: string;
          input_digest: string;
          manifest_digest: string;
          writer_kind: string;
        }
      | {
          kind: "package_review_run";
          bid_id: string;
          package_id: string;
          revision_id: string;
          package_digest: string;
          inventory_id: string;
          inventory_digest: string;
          frozen_input_id: string;
          frozen_input_digest: string;
          execution_input_id: string;
          execution_input_digest: string;
          dependency_plan_id: string;
          dependency_plan_digest: string;
          run_id: string;
          input_digest: string;
          method_digest: string;
          result_digest: string | null;
        }
      | {
          kind: "package_submission";
          bid_id: string;
          package_id: string;
          revision_id: string;
          package_digest: string;
          submission_id: string;
          package_binding_digest: string;
          inventory: {
            id: string;
            digest: string;
          } | null;
          review_run: {
            kind: "package_review_run";
            bid_id: string;
            package_id: string;
            revision_id: string;
            package_digest: string;
            inventory_id: string;
            inventory_digest: string;
            frozen_input_id: string;
            frozen_input_digest: string;
            execution_input_id: string;
            execution_input_digest: string;
            dependency_plan_id: string;
            dependency_plan_digest: string;
            run_id: string;
            input_digest: string;
            method_digest: string;
            result_digest: string | null;
          } | null;
        };
    selection_digest: string;
  }[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  complete_observation: true;
  directory_basis: "native_record_identity_and_state";
  selection_requires_resolution: true;
  qualification_assessed: false;
};

export type WorkContextAnySelection =
  | {
      kind: "draft_snapshot";
      bid_id: string;
      draft_id: string;
      draft_revision: number;
      snapshot_id: string;
      snapshot_digest: string;
    }
  | {
      kind: "build";
      bid_id: string;
      build_id: string;
      draft_id: string;
      draft_revision: number;
      snapshot_id: string;
      snapshot_digest: string;
      build_input_id: string;
      input_digest: string;
      manifest_digest: string;
      writer_kind: string;
    }
  | {
      kind: "package_review_run";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      inventory_id: string;
      inventory_digest: string;
      frozen_input_id: string;
      frozen_input_digest: string;
      execution_input_id: string;
      execution_input_digest: string;
      dependency_plan_id: string;
      dependency_plan_digest: string;
      run_id: string;
      input_digest: string;
      method_digest: string;
      result_digest: string | null;
    }
  | {
      kind: "package_submission";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      submission_id: string;
      package_binding_digest: string;
      inventory: {
        id: string;
        digest: string;
      } | null;
      review_run: {
        kind: "package_review_run";
        bid_id: string;
        package_id: string;
        revision_id: string;
        package_digest: string;
        inventory_id: string;
        inventory_digest: string;
        frozen_input_id: string;
        frozen_input_digest: string;
        execution_input_id: string;
        execution_input_digest: string;
        dependency_plan_id: string;
        dependency_plan_digest: string;
        run_id: string;
        input_digest: string;
        method_digest: string;
        result_digest: string | null;
      } | null;
    };

export type WorkContextDraftSelection = {
  kind: "draft_snapshot";
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
};

export type WorkContextBuildSelection = {
  kind: "build";
  bid_id: string;
  build_id: string;
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  build_input_id: string;
  input_digest: string;
  manifest_digest: string;
  writer_kind: string;
};

export type PackageWorkContext = {
  version: "package-work-context/1";
  selection: WorkContextSelection;
  selection_digest: string;
  observed_at: string;
  observation_digest: string;
  identity:
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        round_no: number;
        binding_status: "confirmed" | "pending";
        authority_id: string | null;
        digest: string;
        identity_version?: "bid-identity/1";
      }
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        lot_id: string | null;
        round_no: number;
        binding_status: "confirmed" | "pending";
        authority_id: string | null;
        digest: string;
        identity_version: "bid-identity/2";
      };
  state:
    | {
        kind: "package_review_run";
        operation_id: string;
        operation_state:
          | "queued"
          | "running"
          | "cancel_requested"
          | "succeeded"
          | "failed"
          | "cancelled";
        result_available: boolean;
      }
    | {
        kind: "package_submission";
        registration_kind: "standard" | "offline_fact";
        submitted_at: string;
        recorded_at: string;
        supersedes_id: string | null;
        gate_checked_at_registration: boolean;
        platform_submission_verified: false;
        pre_submission_system_check_verified: false;
      };
  current_observation: {
    identity: WorkContextDimensionObservation;
    package_head: WorkContextDimensionObservation;
    authority_head: WorkContextDimensionObservation;
    inventory_head: WorkContextDimensionObservation;
    rule_set_head: WorkContextDimensionObservation;
    sources: WorkContextDimensionObservation;
    selected_facts: WorkContextDimensionObservation;
    executor_method: WorkContextDimensionObservation;
    submission_head: WorkContextDimensionObservation;
    review_run_head: WorkContextDimensionObservation;
    bound_run_state: WorkContextDimensionObservation;
  };
  summary: WorkContextSummary;
  native_targets: WorkContextNativeTargets;
  original_bytes_reverified: false;
  limitations: string[];
};

export type WorkContextRelationPage = {
  version: "package-work-context-relations/1";
  seed: {
    bid_id: string;
    build_id: string;
    draft_id: string;
    draft_revision: number;
    snapshot_id: string;
    snapshot_digest: string;
    build_input_id: string;
    input_digest: string;
    manifest_digest: string;
    writer_kind: string;
  };
  target: "package_revision";
  observed_at: string;
  observation_digest: string;
  items: {
    id: string;
    kind: "adopted_into" | "contains_output";
    output: {
      document_version_id: string;
      format: "docx" | "pdf";
      sha256: string;
    };
    package_revision: {
      kind: "package_revision";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
    };
    package_revision_number: number;
    proof_digest: string;
    adoption_command_id: string | null;
    adopted_at: string | null;
    current_package_head: WorkContextDimensionObservation;
    current_source_basis: WorkContextDimensionObservation;
    qualification_assessed: false;
  }[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  complete_observation: true;
  original_bytes_reverified: false;
  qualification_assessed: false;
};

export type PricingRegisterPackageFormula = {
  title: string;
  formula: PricingFormulaParameters;
  amount_unit: "元" | "万元";
  currency: "CNY" | null;
  rounding_policy: "half_up_2dp" | "half_even_2dp";
  interpretation: PricingInterpretation;
  terms_complete_confirmed: true;
  matches_source_confirmed: true;
  evidence_quotes: PricingEvidenceQuote[];
  reason: string;
  package_binding: PricingPackagePricingBinding;
};

export type PricingPackagePricingBinding = {
  package_id: string;
  revision_id: string;
  authority_package_id: string;
  authority_revision_id: string;
};

export type PricingPackageSnapshot = {
  version: "package-pricing-authority/1";
  binding: PricingPackagePricingBinding;
  package_digest: string;
  authority_digest: string;
  identity_digest: string;
  source_heads_digest: string;
  rule_set_id: string | null;
  inventory_id: string | null;
  inventory_digest: string | null;
};

export type PricingPackageContext = {
  bid_id: string;
  material_snapshot_id: string | null;
  material_revision: number;
  scope: {
    bid_id: string;
    round_id: string;
    effective_documents: {
      role: "tender" | "supplement";
      document_version_id: string;
      digest: string;
    }[];
  };
  parses: {
    id: string;
    document_version_id: string;
  }[];
  source_heads: {
    id: string;
    digest: string;
    revision: number | null;
    status: string | null;
    valid_from: string | null;
    valid_until: string | null;
  }[];
  package_binding: PricingPackagePricingBinding;
  package_snapshot: {
    version: "package-pricing-authority/1";
    binding: PricingPackagePricingBinding;
    package_digest: string;
    authority_digest: string;
    identity_digest: string;
    source_heads_digest: string;
    rule_set_id: string | null;
    inventory_id: string | null;
    inventory_digest: string | null;
  };
};

export type PackageTechnicalScopeRequest = {
  purpose: "current_prebid";
  package_digest: string;
  authority_revision_id: string;
  authority_digest: string;
  inventory_id: string;
  inventory_digest: string;
  technical_part_ids: string[];
  rule_scopes: {
    rule_id: string;
    rule_digest: string;
    selection: "include" | "exclude" | "unclassified";
    part_ids: string[];
    reason: string;
  }[];
  reason: string;
};

export type FreezePackageTechnicalScope = {
  request: {
    purpose: "current_prebid";
    package_digest: string;
    authority_revision_id: string;
    authority_digest: string;
    inventory_id: string;
    inventory_digest: string;
    technical_part_ids: string[];
    rule_scopes: {
      rule_id: string;
      rule_digest: string;
      selection: "include" | "exclude" | "unclassified";
      part_ids: string[];
      reason: string;
    }[];
    reason: string;
  };
  preview_digest: string;
};

export type PackageTechnicalScopePreview = {
  manifest: {
    version: "package-technical-scope-preview/1";
    scope: {
      bid_id: string;
      package_id: string;
      revision_id: string;
      inventory_id: string;
    };
    basis: {
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      identity_digest: string;
    };
    method: {
      version: "package-technical-scope-policy/1";
      digest: string;
      sources: {
        "packages/domain/package_technical_scope.py": string;
        "packages/domain/bid_package_technical_scope_repository.py": string;
        "packages/domain/bid_package_technical_scope_service.py": string;
        "packages/contracts/package_technical_scope_api.py": string;
        "packages/contracts/sql/bid-package-technical-scopes.sql": string;
        "packages/domain/bid_package_review_documents.py": string;
        "packages/domain/bid_package_repository.py": string;
        "packages/rag/indexing.py": string;
      };
      limits: {
        members: 500;
        parts: 2000;
        rules: 1000;
        source_rows: 20000;
        blocks: 100000;
        pages: 100000;
        request_bytes: 1048576;
        snapshot_bytes: 33554432;
        original_bytes: 1073741824;
      };
    };
    request: {
      purpose: "current_prebid";
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      inventory_id: string;
      inventory_digest: string;
      technical_part_ids: string[];
      rule_scopes: {
        rule_id: string;
        rule_digest: string;
        selection: "include" | "exclude" | "unclassified";
        part_ids: string[];
        reason: string;
      }[];
      reason: string;
    };
    request_digest: string;
    context_digest: string;
    parts: {
      member_id: string;
      document_version_id: string;
      file_digest: string;
      part: {
        part_id: string;
        category: string;
        first_page: number;
        last_page: number;
        shared_attachment: boolean;
        heading_path: number[];
      };
      selected: boolean;
      read_physical_pages: number[];
      block_ids: string[];
      text_evidence_present: boolean;
      visual_coverage: "unproven";
    }[];
    rules: {
      rule_id: string;
      rule_digest: string;
      selection: "include" | "exclude" | "unclassified";
      part_ids: string[];
      reason: string;
      rule_snapshot: { [key: string]: unknown };
      requirement_digest: string;
      declared_target_part_ids: string[];
      source_evidence: {
        member_id: string;
        document_version_id: string;
        file_digest: string;
        parse_run_id: string;
        physical_page: number;
        evidence_id: string;
        evidence_digest: string;
        text_content: string;
        part_ids: string[];
      }[];
    }[];
    documents: {
      package_role: "target" | "authority";
      member_id: string;
      document_version_id: string;
      file_digest: string;
      byte_size: number;
      parse: {
        status: "frozen" | "not_frozen";
        parse_run_id: string | null;
        parser_digest: string | null;
        config_digest: string | null;
        evidence_digest: string | null;
        reason: string | null;
      };
      page_count: number | null;
      pages: {
        physical_page: number;
        quality: "usable" | "partial" | "failed";
        gaps: string[];
      }[];
      blocks: {
        id: string;
        physical_page: number;
        ordinal: number;
        kind: "text" | "table" | "visual_observation";
        text_content: string;
        digest: string;
        bbox_json: string | null;
        structure_json: string | null;
      }[];
    }[];
    source_snapshot: { [key: string]: unknown }[];
    coverage: {
      state: "partial" | "unknown";
      all_part_count: number;
      selected_part_count: number;
      all_scoring_rule_count: number;
      included_rule_count: number;
      frozen_parse_member_count: number;
      gaps: {
        id: string;
        code: string;
        subject: string | null;
        message: string;
      }[];
      visual_coverage: "unproven";
      required_range_completeness: "unproven";
    };
    timing: {
      purpose: "current_prebid";
      historical_as_of: null;
      submitted_at: null;
      label_known_at: null;
      training_frozen_at: null;
      submission_split_at: null;
      label_available_as_of: null;
      historical_qualification: "not_established";
    };
    original_bytes_verified: false;
    inventory_complete: false;
    scoring_ready: false;
    formal_scoring_eligible: false;
    model_execution_enabled: false;
    training_eligible: false;
  };
  digest: string;
};

export type PackageTechnicalScopeView = {
  manifest: {
    version: "package-technical-scope/1";
    id: string;
    actor_id: string;
    command_id: string;
    frozen_at: string;
    preview: {
      manifest: {
        version: "package-technical-scope-preview/1";
        scope: {
          bid_id: string;
          package_id: string;
          revision_id: string;
          inventory_id: string;
        };
        basis: {
          package_digest: string;
          authority_revision_id: string;
          authority_digest: string;
          inventory_digest: string;
          rule_set_id: string;
          rule_set_digest: string;
          identity_digest: string;
        };
        method: {
          version: "package-technical-scope-policy/1";
          digest: string;
          sources: {
            "packages/domain/package_technical_scope.py": string;
            "packages/domain/bid_package_technical_scope_repository.py": string;
            "packages/domain/bid_package_technical_scope_service.py": string;
            "packages/contracts/package_technical_scope_api.py": string;
            "packages/contracts/sql/bid-package-technical-scopes.sql": string;
            "packages/domain/bid_package_review_documents.py": string;
            "packages/domain/bid_package_repository.py": string;
            "packages/rag/indexing.py": string;
          };
          limits: {
            members: 500;
            parts: 2000;
            rules: 1000;
            source_rows: 20000;
            blocks: 100000;
            pages: 100000;
            request_bytes: 1048576;
            snapshot_bytes: 33554432;
            original_bytes: 1073741824;
          };
        };
        request: {
          purpose: "current_prebid";
          package_digest: string;
          authority_revision_id: string;
          authority_digest: string;
          inventory_id: string;
          inventory_digest: string;
          technical_part_ids: string[];
          rule_scopes: {
            rule_id: string;
            rule_digest: string;
            selection: "include" | "exclude" | "unclassified";
            part_ids: string[];
            reason: string;
          }[];
          reason: string;
        };
        request_digest: string;
        context_digest: string;
        parts: {
          member_id: string;
          document_version_id: string;
          file_digest: string;
          part: {
            part_id: string;
            category: string;
            first_page: number;
            last_page: number;
            shared_attachment: boolean;
            heading_path: number[];
          };
          selected: boolean;
          read_physical_pages: number[];
          block_ids: string[];
          text_evidence_present: boolean;
          visual_coverage: "unproven";
        }[];
        rules: {
          rule_id: string;
          rule_digest: string;
          selection: "include" | "exclude" | "unclassified";
          part_ids: string[];
          reason: string;
          rule_snapshot: { [key: string]: unknown };
          requirement_digest: string;
          declared_target_part_ids: string[];
          source_evidence: {
            member_id: string;
            document_version_id: string;
            file_digest: string;
            parse_run_id: string;
            physical_page: number;
            evidence_id: string;
            evidence_digest: string;
            text_content: string;
            part_ids: string[];
          }[];
        }[];
        documents: {
          package_role: "target" | "authority";
          member_id: string;
          document_version_id: string;
          file_digest: string;
          byte_size: number;
          parse: {
            status: "frozen" | "not_frozen";
            parse_run_id: string | null;
            parser_digest: string | null;
            config_digest: string | null;
            evidence_digest: string | null;
            reason: string | null;
          };
          page_count: number | null;
          pages: {
            physical_page: number;
            quality: "usable" | "partial" | "failed";
            gaps: string[];
          }[];
          blocks: {
            id: string;
            physical_page: number;
            ordinal: number;
            kind: "text" | "table" | "visual_observation";
            text_content: string;
            digest: string;
            bbox_json: string | null;
            structure_json: string | null;
          }[];
        }[];
        source_snapshot: { [key: string]: unknown }[];
        coverage: {
          state: "partial" | "unknown";
          all_part_count: number;
          selected_part_count: number;
          all_scoring_rule_count: number;
          included_rule_count: number;
          frozen_parse_member_count: number;
          gaps: {
            id: string;
            code: string;
            subject: string | null;
            message: string;
          }[];
          visual_coverage: "unproven";
          required_range_completeness: "unproven";
        };
        timing: {
          purpose: "current_prebid";
          historical_as_of: null;
          submitted_at: null;
          label_known_at: null;
          training_frozen_at: null;
          submission_split_at: null;
          label_available_as_of: null;
          historical_qualification: "not_established";
        };
        original_bytes_verified: false;
        inventory_complete: false;
        scoring_ready: false;
        formal_scoring_eligible: false;
        model_execution_enabled: false;
        training_eligible: false;
      };
      digest: string;
    };
    original_verification: {
      state: "verified_at_recording";
      verified_at: string;
      files: {
        document_version_id: string;
        digest: string;
        byte_size: number;
      }[];
    };
    inventory_complete: false;
    scoring_ready: false;
    formal_scoring_eligible: false;
    model_execution_enabled: false;
    training_eligible: false;
  };
  digest: string;
};

export type PackageTechnicalScopeApplied = {
  scope: {
    manifest: {
      version: "package-technical-scope/1";
      id: string;
      actor_id: string;
      command_id: string;
      frozen_at: string;
      preview: {
        manifest: {
          version: "package-technical-scope-preview/1";
          scope: {
            bid_id: string;
            package_id: string;
            revision_id: string;
            inventory_id: string;
          };
          basis: {
            package_digest: string;
            authority_revision_id: string;
            authority_digest: string;
            inventory_digest: string;
            rule_set_id: string;
            rule_set_digest: string;
            identity_digest: string;
          };
          method: {
            version: "package-technical-scope-policy/1";
            digest: string;
            sources: {
              "packages/domain/package_technical_scope.py": string;
              "packages/domain/bid_package_technical_scope_repository.py": string;
              "packages/domain/bid_package_technical_scope_service.py": string;
              "packages/contracts/package_technical_scope_api.py": string;
              "packages/contracts/sql/bid-package-technical-scopes.sql": string;
              "packages/domain/bid_package_review_documents.py": string;
              "packages/domain/bid_package_repository.py": string;
              "packages/rag/indexing.py": string;
            };
            limits: {
              members: 500;
              parts: 2000;
              rules: 1000;
              source_rows: 20000;
              blocks: 100000;
              pages: 100000;
              request_bytes: 1048576;
              snapshot_bytes: 33554432;
              original_bytes: 1073741824;
            };
          };
          request: {
            purpose: "current_prebid";
            package_digest: string;
            authority_revision_id: string;
            authority_digest: string;
            inventory_id: string;
            inventory_digest: string;
            technical_part_ids: string[];
            rule_scopes: {
              rule_id: string;
              rule_digest: string;
              selection: "include" | "exclude" | "unclassified";
              part_ids: string[];
              reason: string;
            }[];
            reason: string;
          };
          request_digest: string;
          context_digest: string;
          parts: {
            member_id: string;
            document_version_id: string;
            file_digest: string;
            part: {
              part_id: string;
              category: string;
              first_page: number;
              last_page: number;
              shared_attachment: boolean;
              heading_path: number[];
            };
            selected: boolean;
            read_physical_pages: number[];
            block_ids: string[];
            text_evidence_present: boolean;
            visual_coverage: "unproven";
          }[];
          rules: {
            rule_id: string;
            rule_digest: string;
            selection: "include" | "exclude" | "unclassified";
            part_ids: string[];
            reason: string;
            rule_snapshot: { [key: string]: unknown };
            requirement_digest: string;
            declared_target_part_ids: string[];
            source_evidence: {
              member_id: string;
              document_version_id: string;
              file_digest: string;
              parse_run_id: string;
              physical_page: number;
              evidence_id: string;
              evidence_digest: string;
              text_content: string;
              part_ids: string[];
            }[];
          }[];
          documents: {
            package_role: "target" | "authority";
            member_id: string;
            document_version_id: string;
            file_digest: string;
            byte_size: number;
            parse: {
              status: "frozen" | "not_frozen";
              parse_run_id: string | null;
              parser_digest: string | null;
              config_digest: string | null;
              evidence_digest: string | null;
              reason: string | null;
            };
            page_count: number | null;
            pages: {
              physical_page: number;
              quality: "usable" | "partial" | "failed";
              gaps: string[];
            }[];
            blocks: {
              id: string;
              physical_page: number;
              ordinal: number;
              kind: "text" | "table" | "visual_observation";
              text_content: string;
              digest: string;
              bbox_json: string | null;
              structure_json: string | null;
            }[];
          }[];
          source_snapshot: { [key: string]: unknown }[];
          coverage: {
            state: "partial" | "unknown";
            all_part_count: number;
            selected_part_count: number;
            all_scoring_rule_count: number;
            included_rule_count: number;
            frozen_parse_member_count: number;
            gaps: {
              id: string;
              code: string;
              subject: string | null;
              message: string;
            }[];
            visual_coverage: "unproven";
            required_range_completeness: "unproven";
          };
          timing: {
            purpose: "current_prebid";
            historical_as_of: null;
            submitted_at: null;
            label_known_at: null;
            training_frozen_at: null;
            submission_split_at: null;
            label_available_as_of: null;
            historical_qualification: "not_established";
          };
          original_bytes_verified: false;
          inventory_complete: false;
          scoring_ready: false;
          formal_scoring_eligible: false;
          model_execution_enabled: false;
          training_eligible: false;
        };
        digest: string;
      };
      original_verification: {
        state: "verified_at_recording";
        verified_at: string;
        files: {
          document_version_id: string;
          digest: string;
          byte_size: number;
        }[];
      };
      inventory_complete: false;
      scoring_ready: false;
      formal_scoring_eligible: false;
      model_execution_enabled: false;
      training_eligible: false;
    };
    digest: string;
  };
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      request: {
        purpose: "current_prebid";
        package_digest: string;
        authority_revision_id: string;
        authority_digest: string;
        inventory_id: string;
        inventory_digest: string;
        technical_part_ids: string[];
        rule_scopes: {
          rule_id: string;
          rule_digest: string;
          selection: "include" | "exclude" | "unclassified";
          part_ids: string[];
          reason: string;
        }[];
        reason: string;
      };
      preview_digest: string;
    };
    if_match: string;
  };
};

export type PackageTechnicalScopeContext = {
  target: BidPackageStoredView;
  authority: BidPackageStoredView;
  inventory: PackageRequirementInventoryView;
  method: {
    version: "package-technical-scope-policy/1";
    digest: string;
    sources: {
      "packages/domain/package_technical_scope.py": string;
      "packages/domain/bid_package_technical_scope_repository.py": string;
      "packages/domain/bid_package_technical_scope_service.py": string;
      "packages/contracts/package_technical_scope_api.py": string;
      "packages/contracts/sql/bid-package-technical-scopes.sql": string;
      "packages/domain/bid_package_review_documents.py": string;
      "packages/domain/bid_package_repository.py": string;
      "packages/rag/indexing.py": string;
    };
    limits: {
      members: 500;
      parts: 2000;
      rules: 1000;
      source_rows: 20000;
      blocks: 100000;
      pages: 100000;
      request_bytes: 1048576;
      snapshot_bytes: 33554432;
      original_bytes: 1073741824;
    };
  };
  context_digest: string;
  etag: string;
  can_freeze: boolean;
  blocking_reasons: {
    id: string;
    code: string;
    subject: string | null;
    message: string;
  }[];
  catalog_complete: true;
  timing: {
    purpose: "current_prebid";
    historical_as_of: null;
    submitted_at: null;
    label_known_at: null;
    training_frozen_at: null;
    submission_split_at: null;
    label_available_as_of: null;
    historical_qualification: "not_established";
  };
  inventory_complete: false;
  scoring_ready: false;
  formal_scoring_eligible: false;
  model_execution_enabled: false;
  training_eligible: false;
};

export type PackageTechnicalScopePage = {
  items: {
    id: string;
    digest: string;
    inventory_id: string;
    created_at: string;
    coverage_state: "partial" | "unknown";
    selected_part_count: number;
    included_rule_count: number;
    scoring_ready: false;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageTechnicalScoringContext = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
    scope_id: string;
    scope_digest: string;
  };
  basis: {
    package_digest: string;
    authority_revision_id: string;
    authority_digest: string;
    inventory_digest: string;
    rule_set_id: string;
    rule_set_digest: string;
    identity_digest: string;
  };
  observed_at: string;
  coverage: {
    state: "partial" | "unknown";
    all_part_count: number;
    selected_part_count: number;
    all_scoring_rule_count: number;
    included_rule_count: number;
    frozen_parse_member_count: number;
    gaps: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
    visual_coverage: "unproven";
    required_range_completeness: "unproven";
  };
  denominator: {
    state:
      | "unselected"
      | "not_configured"
      | "unavailable"
      | "mismatched"
      | "matched";
    scale_id: string | null;
    scale_digest: string | null;
    purpose: "current_prebid" | "historical_backtest";
    technical_maximum: string | null;
    scale_description: string | null;
    aggregation: {
      status: "unknown" | "unsupported";
      description: string;
    } | null;
    maximum_usable: boolean;
    aggregation_usable: false;
    evidence_refs: {
      id: string;
      document_version_id: string;
      parse_id: string;
      evidence_id: string;
      source_id: string;
      blob_digest: string;
      evidence_digest: string;
      physical_page: number;
      source_revision: number | null;
      quote: string;
      supported_fields: (
        | "technical_maximum"
        | "scale_description"
        | "aggregation"
      )[];
    }[];
    reasons: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
  };
  judgments: {
    required_valid_independent: 3;
    recorded_valid_independent: 0;
    producer_authority: "not_configured_for_exact_package";
    previous_answers_in_input: false;
    retries_count_as_independent: false;
    unknown_send_auto_retry: false;
    execution_enabled: false;
  };
  numeric_prediction: null;
  blockers: {
    id: string;
    code: string;
    subject: string | null;
    message: string;
  }[];
  inventory_complete: false;
  scoring_ready: false;
  formal_scoring_eligible: false;
  model_execution_enabled: false;
  training_eligible: false;
  version: "package-technical-scoring-context/1";
  purpose: "current_prebid";
  current_input: {
    state: "matched" | "changed" | "unavailable";
    stored_context_digest: string;
    current_context_digest: string | null;
    method_matches: boolean;
    original_bytes_reverified: false;
    reasons: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
  };
  official_label_access: "forbidden";
};

export type PackageTechnicalSampleContext = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
    scope_id: string;
    scope_digest: string;
  };
  basis: {
    package_digest: string;
    authority_revision_id: string;
    authority_digest: string;
    inventory_digest: string;
    rule_set_id: string;
    rule_set_digest: string;
    identity_digest: string;
  };
  observed_at: string;
  coverage: {
    state: "partial" | "unknown";
    all_part_count: number;
    selected_part_count: number;
    all_scoring_rule_count: number;
    included_rule_count: number;
    frozen_parse_member_count: number;
    gaps: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
    visual_coverage: "unproven";
    required_range_completeness: "unproven";
  };
  denominator: {
    state:
      | "unselected"
      | "not_configured"
      | "unavailable"
      | "mismatched"
      | "matched";
    scale_id: string | null;
    scale_digest: string | null;
    purpose: "current_prebid" | "historical_backtest";
    technical_maximum: string | null;
    scale_description: string | null;
    aggregation: {
      status: "unknown" | "unsupported";
      description: string;
    } | null;
    maximum_usable: boolean;
    aggregation_usable: false;
    evidence_refs: {
      id: string;
      document_version_id: string;
      parse_id: string;
      evidence_id: string;
      source_id: string;
      blob_digest: string;
      evidence_digest: string;
      physical_page: number;
      source_revision: number | null;
      quote: string;
      supported_fields: (
        | "technical_maximum"
        | "scale_description"
        | "aggregation"
      )[];
    }[];
    reasons: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
  };
  judgments: {
    required_valid_independent: 3;
    recorded_valid_independent: 0;
    producer_authority: "not_configured_for_exact_package";
    previous_answers_in_input: false;
    retries_count_as_independent: false;
    unknown_send_auto_retry: false;
    execution_enabled: false;
  };
  numeric_prediction: null;
  blockers: {
    id: string;
    code: string;
    subject: string | null;
    message: string;
  }[];
  inventory_complete: false;
  scoring_ready: false;
  formal_scoring_eligible: false;
  model_execution_enabled: false;
  training_eligible: false;
  version: "package-technical-sample-context/1";
  purpose: "historical_backtest";
  submission: {
    id: string;
    binding_digest: string;
    submitted_at: string;
    recorded_at: string;
    is_current_head: boolean;
    matches_scope: boolean;
    platform_submission_verified: false;
  };
  official_result: {
    outcome_id: string | null;
    score_kind: "technical_total" | "comprehensive_total" | "unknown" | null;
    technical_value: string | null;
    reported_maximum: string | null;
    label_known_at: string | null;
    current_association: boolean;
    reasons: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
  };
  timing: {
    scope_frozen_at: string;
    historical_as_of: string;
    submitted_at: string;
    label_known_at: string | null;
    training_frozen_at: null;
    submission_split_at: null;
    label_available_as_of: null;
    strict_timing_ready: false;
  };
  original_scope_precedes_submission: boolean;
  source_metadata_matches: boolean;
  sample_state: "pending";
  sample_created: false;
  official_label_access: "association_check_only";
};

export type PackageTechnicalExecutionContext = {
  version: "package-technical-execution-context/1";
  qualification: {
    scope: {
      bid_id: string;
      package_id: string;
      revision_id: string;
      inventory_id: string;
      scope_id: string;
      scope_digest: string;
    };
    basis: {
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      identity_digest: string;
    };
    observed_at: string;
    coverage: {
      state: "partial" | "unknown";
      all_part_count: number;
      selected_part_count: number;
      all_scoring_rule_count: number;
      included_rule_count: number;
      frozen_parse_member_count: number;
      gaps: {
        id: string;
        code: string;
        subject: string | null;
        message: string;
      }[];
      visual_coverage: "unproven";
      required_range_completeness: "unproven";
    };
    denominator: {
      state:
        | "unselected"
        | "not_configured"
        | "unavailable"
        | "mismatched"
        | "matched";
      scale_id: string | null;
      scale_digest: string | null;
      purpose: "current_prebid" | "historical_backtest";
      technical_maximum: string | null;
      scale_description: string | null;
      aggregation: {
        status: "unknown" | "unsupported";
        description: string;
      } | null;
      maximum_usable: boolean;
      aggregation_usable: false;
      evidence_refs: {
        id: string;
        document_version_id: string;
        parse_id: string;
        evidence_id: string;
        source_id: string;
        blob_digest: string;
        evidence_digest: string;
        physical_page: number;
        source_revision: number | null;
        quote: string;
        supported_fields: (
          | "technical_maximum"
          | "scale_description"
          | "aggregation"
        )[];
      }[];
      reasons: {
        id: string;
        code: string;
        subject: string | null;
        message: string;
      }[];
    };
    judgments: {
      required_valid_independent: 3;
      recorded_valid_independent: 0;
      producer_authority: "not_configured_for_exact_package";
      previous_answers_in_input: false;
      retries_count_as_independent: false;
      unknown_send_auto_retry: false;
      execution_enabled: false;
    };
    numeric_prediction: null;
    blockers: {
      id: string;
      code: string;
      subject: string | null;
      message: string;
    }[];
    inventory_complete: false;
    scoring_ready: false;
    formal_scoring_eligible: false;
    model_execution_enabled: false;
    training_eligible: false;
    version: "package-technical-scoring-context/1";
    purpose: "current_prebid";
    current_input: {
      state: "matched" | "changed" | "unavailable";
      stored_context_digest: string;
      current_context_digest: string | null;
      method_matches: boolean;
      original_bytes_reverified: false;
      reasons: {
        id: string;
        code: string;
        subject: string | null;
        message: string;
      }[];
    };
    official_label_access: "forbidden";
  };
  producer: {
    software_foundation: "not_installed" | "installed";
    real_provider_configured: false;
    formal_input_authority_configured: false;
    mechanism_test_publicly_available: false;
  };
  method: {
    schema: "package-technical-judgment-method/1";
    provider: "deepseek";
    model_alias: "deepseek-flash";
    immutable_weights_verified: false;
    input_protocol: "package-technical-judgment-input/1";
    output_protocol: "package-technical-judgments/1";
    transport_protocol: "controlled-score-response/1";
    thinking: "disabled";
    temperature: 0;
    context_tokens: 1000000;
    max_output_tokens: 4096;
    maximum_prompt_characters: 262144;
    prompt_digest: "b0f0dbab7ff8604813d50c9caf838f66c7d810f254b47773c68f5dda39a92eea";
    output_schema_digest: "c41b1c0d5685dcddc247f1c0343046c6c52a749b039440f312fb62be7065829c";
    valid_replicates_required: 3;
    retry_is_replicate: false;
    complete_package_snapshot_required: true;
    visual_interpretation_supported: false;
    formal_scoring_eligible: false;
    digest: "b278c1ce4785d51f483070c022d0041902115c0858eeed74b02d52c443089996";
  };
  execution_enabled: false;
  blockers: {
    id: string;
    code: string;
    subject: string | null;
    message: string;
  }[];
};

export type CreatePackageTechnicalExecution = {
  purpose: "current_prebid";
  scope_digest: string;
  method_digest: "b278c1ce4785d51f483070c022d0041902115c0858eeed74b02d52c443089996";
  scale_id: string | null;
  budget: string;
  reason: string;
};

export type KnowledgePackageReviewTargetPage = {
  bid_id: string;
  items: {
    id: string;
    target_kind: "package_review_run";
    created_at: string;
    input_digest: string;
    execution_input_id: string;
    state: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
    frozen_input_id: string;
    result_digest: string | null;
  }[];
  next_offset: number | null;
  reference_only: true;
  changes_frozen_result: false;
  formal_score_allowed: false;
};

export type HistoricalImportRequest = {
  records: HistoricalImportRecord[];
};

export type HistoricalImportBatch = {
  id: string;
  mode: "dry_run" | "confirmed_import";
  revision: number;
  manifest_blob_id: string;
  records: {
    batch_id: string;
    external_record_id: string;
    source_digest: string;
    state: "pending" | "imported" | "conflict" | "failed";
    bid_id: string | null;
    errors: string[];
  }[];
  next_offset: number | null;
  counts: {
    total: number;
    pending: number;
    imported: number;
    errors: number;
  };
  formal_sample_admission: "separate_verified_technical_label_check";
  standard_submission_gate_checked: false;
};

export type HistoricalImportReceipt = {
  id: string;
  mode: "dry_run" | "confirmed_import";
  revision: number;
  manifest_blob_id: string;
  records: {
    batch_id: string;
    external_record_id: string;
    source_digest: string;
    state: "pending" | "imported" | "conflict" | "failed";
    bid_id: string | null;
    errors: string[];
  }[];
  next_offset: number | null;
  counts: {
    total: number;
    pending: number;
    imported: number;
    errors: number;
  };
  formal_sample_admission: "separate_verified_technical_label_check";
  standard_submission_gate_checked: false;
  command: {
    command_id: string;
    actor_id: string;
    command_kind: "preview-historical-import" | "confirm-historical-import";
    target_id: string;
    idempotency_key: string;
    request_digest: string;
    if_match: string | null;
  };
};

export type HistoricalImportPage = {
  items: {
    id: string;
    mode: "dry_run" | "confirmed_import";
    revision: number;
    created_by: string;
    created_at: string | null;
    counts: {
      total: number;
      pending: number;
      imported: number;
      errors: number;
    };
  }[];
  next_offset: number | null;
};

export type HistoricalImportSource = {
  batch_id: string;
  manifest_blob_id: string;
  manifest_digest: string;
  request: HistoricalImportRequest;
  source_matches_saved_manifest: true;
};

export type PackageRuleCorrectionRequest = {
  base_inventory_digest: string;
  base_rule_set_digest: string;
  reason: string;
  changes: (
    | {
        op: "add";
        rule: PackageRuleCorrection_RuleAddition;
      }
    | {
        op: "replace";
        rule_id: string;
        rule_digest: string;
        rule: PackageRuleCorrection_RuleAddition;
      }
    | {
        op: "withdraw";
        rule_id: string;
        rule_digest: string;
        evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
      }
  )[];
};

export type ApplyPackageRuleCorrection = {
  request: {
    base_inventory_digest: string;
    base_rule_set_digest: string;
    reason: string;
    changes: (
      | {
          op: "add";
          rule: PackageRuleCorrection_RuleAddition;
        }
      | {
          op: "replace";
          rule_id: string;
          rule_digest: string;
          rule: PackageRuleCorrection_RuleAddition;
        }
      | {
          op: "withdraw";
          rule_id: string;
          rule_digest: string;
          evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
        }
    )[];
  };
  preview_digest: string;
};

export type PackageRuleCorrectionPreviewView = {
  manifest: {
    version: "package-rule-correction-preview/1";
    scope: {
      bid_id: string;
      package_id: string;
      revision_id: string;
      inventory_id: string;
    };
    base: {
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
    };
    authority: {
      revision_id: string;
      digest: string;
      identity_digest: string;
    };
    extraction_basis: {
      inventory_id: string;
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      extraction_result_id: string;
      extraction_input_digest: string;
      extraction_result_digest: string;
      extraction_range_status: "all_frozen_evidence_submitted";
      extraction_coverage: "complete" | "partial" | "conflict";
      extraction_quality_status: "not_measured";
    };
    previous: {
      id: string;
      digest: string;
    } | null;
    sequence_no: number;
    policy_digest: string;
    request: {
      base_inventory_digest: string;
      base_rule_set_digest: string;
      reason: string;
      changes: (
        | {
            op: "add";
            rule: PackageRuleCorrection_RuleAddition;
          }
        | {
            op: "replace";
            rule_id: string;
            rule_digest: string;
            rule: PackageRuleCorrection_RuleAddition;
          }
        | {
            op: "withdraw";
            rule_id: string;
            rule_digest: string;
            evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
          }
      )[];
    };
    request_digest: string;
    source_snapshot_digest: string;
    changes: {
      index: number;
      op: "add" | "replace" | "withdraw";
      rule_id: string | null;
      rule_digest: string | null;
      before: {
        kind: "disqualification" | "mandatory" | "scoring" | "advisory";
        statement: string;
        conditions: string[];
        exceptions: string[];
        max_points: string | null;
        evidence_ids: string[];
        bands: PackageRuleCorrection_RuleBand[];
        applicability_scope: { [key: string]: unknown };
        provenance_status: "effective" | "needs_revalidation" | "superseded";
      } | null;
      after: {
        kind: "disqualification" | "mandatory" | "scoring" | "advisory";
        statement: string;
        conditions: string[];
        exceptions: string[];
        max_points: string | null;
        evidence_ids: string[];
        bands: PackageRuleCorrection_RuleBand[];
        applicability_scope: { [key: string]: unknown };
        provenance_status: "effective" | "needs_revalidation" | "superseded";
      };
      quotes: {
        evidence_id: string;
        member_id: string;
        document_version_id: string;
        parse_run_id: string;
        physical_page: number;
        evidence_digest: string;
        part_ids: string[];
        quote: string;
      }[];
    }[];
    counts: {
      before: number;
      after: number;
      carried: number;
      added: number;
      replaced: number;
      withdrawn: number;
      active_after: number;
    };
    limitations: string[];
    inventory_complete: false;
    review_ready: false;
    original_bytes_verified: false;
  };
  digest: string;
};

export type PackageRuleCorrectionView = {
  manifest: {
    version: "package-rule-correction/1";
    id: string;
    scope: {
      bid_id: string;
      package_id: string;
      revision_id: string;
      inventory_id: string;
    };
    base: {
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
    };
    authority: {
      revision_id: string;
      digest: string;
      identity_digest: string;
    };
    extraction_basis: {
      inventory_id: string;
      inventory_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      extraction_result_id: string;
      extraction_input_digest: string;
      extraction_result_digest: string;
      extraction_range_status: "all_frozen_evidence_submitted";
      extraction_coverage: "complete" | "partial" | "conflict";
      extraction_quality_status: "not_measured";
    };
    previous: {
      id: string;
      digest: string;
    } | null;
    sequence_no: number;
    policy_digest: string;
    request: {
      base_inventory_digest: string;
      base_rule_set_digest: string;
      reason: string;
      changes: (
        | {
            op: "add";
            rule: PackageRuleCorrection_RuleAddition;
          }
        | {
            op: "replace";
            rule_id: string;
            rule_digest: string;
            rule: PackageRuleCorrection_RuleAddition;
          }
        | {
            op: "withdraw";
            rule_id: string;
            rule_digest: string;
            evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
          }
      )[];
    };
    request_digest: string;
    source_snapshot_digest: string;
    preview_digest: string;
    actor_id: string;
    command_id: string;
    created_at: string;
    result: {
      inventory_id: string;
      rule_set_id: string;
      rule_set_digest: string;
      rule_count: number;
      rules_digest: string;
    };
    mappings: {
      from_rule_id: string;
      from_rule_digest: string;
      to_rule_id: string;
      to_rule_digest: string;
      op: "carry" | "replace" | "withdraw";
      change_index: number | null;
    }[];
    additions: {
      change_index: number;
      to_rule_id: string;
      to_rule_digest: string;
    }[];
    decision_bindings: {
      rule_id: string;
      decision_id: string;
      decision_digest: string;
      mode: "carried" | "confirmed" | "rejected";
    }[];
  };
  digest: string;
};

export type PackageRuleCorrectionAppliedView = {
  correction: PackageRuleCorrectionView;
  inventory: PackageRequirementInventoryView;
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      request: {
        base_inventory_digest: string;
        base_rule_set_digest: string;
        reason: string;
        changes: (
          | {
              op: "add";
              rule: PackageRuleCorrection_RuleAddition;
            }
          | {
              op: "replace";
              rule_id: string;
              rule_digest: string;
              rule: PackageRuleCorrection_RuleAddition;
            }
          | {
              op: "withdraw";
              rule_id: string;
              rule_digest: string;
              evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
            }
        )[];
      };
      preview_digest: string;
    };
    if_match: string;
  };
};

export type PackageRuleCorrectionHistoryPage = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  items: {
    id: string;
    digest: string;
    created_at: string;
    actor_id: string;
    base_inventory_id: string;
    result_inventory_id: string;
    added: number;
    replaced: number;
    withdrawn: number;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageRuleCorrectionDetail = PackageRuleCorrectionAppliedView;

export type PackageRuleCorrectionEvidencePage = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  inventory_digest: string;
  authority: {
    revision_id: string;
    digest: string;
    identity_digest: string;
  };
  items: {
    evidence_id: string;
    member_id: string;
    document_version_id: string;
    parse_run_id: string;
    physical_page: number;
    evidence_digest: string;
    part_ids: string[];
    file_digest: string;
    ordinal: number;
    kind: "text" | "table" | "visual_observation";
    excerpt: string;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageRuleCorrectionEvidenceDetail = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  inventory_digest: string;
  authority: {
    revision_id: string;
    digest: string;
    identity_digest: string;
  };
  evidence: {
    evidence_id: string;
    member_id: string;
    document_version_id: string;
    parse_run_id: string;
    physical_page: number;
    evidence_digest: string;
    part_ids: string[];
    file_digest: string;
    ordinal: number;
    kind: "text" | "table" | "visual_observation";
    text_content: string;
  };
};

export type AuthoringGenerationBatchCreateRequest = {
  base_draft_revision: number;
  price_version_id: string;
  currency: "USD" | "CNY";
  amount_scale: 1000000000;
  total_limit_minor: number;
  sections: {
    section_id: string;
    base_section_revision: number;
    instruction: string;
    source_version_ids: string[];
    selected_node_ids: string[] | null;
    max_tokens: number;
    budget_limit_minor: number;
  }[];
  reason: string;
};

export type AuthoringGenerationBatchRetryRequest = {
  batch_digest: string;
  section_id: string;
  previous_attempt: number;
  previous_job_id: string;
  reason: string;
};

export type AuthoringGenerationBatchResolveRequest = {
  decision: "apply" | "reject";
  batch_digest: string;
  selections: {
    section_id: string;
    attempt: number;
    job_id: string;
    action_id: string;
    candidate_digest: string;
  }[];
  reason: string;
};

export type AuthoringGenerationBatchReceipt = {
  protocol: "authoring-generation-batch-command/1";
  bid_id: string;
  draft_id: string;
  batch_id: string;
  batch_digest: string;
  kind: "created" | "retried" | "applied" | "rejected";
  batch_state: "open" | "applied" | "rejected";
  created_job_ids: string[];
  applied_section_ids: string[];
  unselected_section_ids: string[];
  draft_revision: number | null;
  snapshot_id: string | null;
  snapshot_digest: string | null;
  recorded_at: string;
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request:
      | {
          base_draft_revision: number;
          price_version_id: string;
          currency: "USD" | "CNY";
          amount_scale: 1000000000;
          total_limit_minor: number;
          sections: {
            section_id: string;
            base_section_revision: number;
            instruction: string;
            source_version_ids: string[];
            selected_node_ids: string[] | null;
            max_tokens: number;
            budget_limit_minor: number;
          }[];
          reason: string;
        }
      | {
          batch_digest: string;
          section_id: string;
          previous_attempt: number;
          previous_job_id: string;
          reason: string;
        }
      | {
          decision: "apply" | "reject";
          batch_digest: string;
          selections: {
            section_id: string;
            attempt: number;
            job_id: string;
            action_id: string;
            candidate_digest: string;
          }[];
          reason: string;
        };
    if_match: string | null;
  };
};

export type AuthoringGenerationBatch = {
  batch_id: string;
  bid_id: string;
  draft_id: string;
  batch_digest: string;
  base_draft_revision: number;
  state: "open" | "applied" | "rejected";
  created_at: string;
  created_by: string;
  section_count: number;
  ready_count: number;
  failed_count: number;
  running_count: number;
  budget: {
    currency: "USD" | "CNY";
    amount_scale: 1000000000;
    limit_minor: number;
    charged_minor: number;
    reserved_minor: number;
    exposure_minor: number;
    remaining_minor: number;
    requires_reconciliation: boolean;
    over_limit: boolean;
    estimate_not_provider_spend_cap: true;
  };
  protocol: "authoring-generation-batch/1";
  generation_mode: "section_patch_set/1";
  base_snapshot_id: string;
  base_snapshot_digest: string;
  base_draft_etag: string;
  price: {
    price_version_id: string;
    version: string;
    provider: string;
    model: string;
    currency: "USD" | "CNY";
    amount_scale: 1000000000;
    input_upper: number;
    output_upper: number;
    input_per_million_minor: number;
    output_per_million_minor: number;
    valid_until: string;
    source_kind: string;
    source_uri: string;
    source_sha256: string;
  };
  reason: string;
  etag: string;
  sections: {
    section_id: string;
    base_section_revision: number;
    instruction: string;
    source_version_ids: string[];
    selected_node_ids: string[] | null;
    max_tokens: number;
    budget_limit_minor: number;
    title: string;
    ordinal: number;
    before_digest: string;
    current_attempt: number;
    budget: {
      currency: "USD" | "CNY";
      amount_scale: 1000000000;
      limit_minor: number;
      charged_minor: number;
      reserved_minor: number;
      exposure_minor: number;
      remaining_minor: number;
      requires_reconciliation: boolean;
      over_limit: boolean;
      estimate_not_provider_spend_cap: true;
    };
    attempts: {
      attempt: number;
      job_id: string;
      operation_id: string;
      writing_plan_id: string;
      created_at: string;
      created_by: string;
      state:
        | "queued"
        | "running"
        | "cancel_requested"
        | "succeeded"
        | "failed"
        | "cancelled";
      publication_state: "pending" | "published" | "stale" | "failed";
      action_id: string | null;
      candidate_digest: string | null;
      candidate_url: string | null;
      error_code: string | null;
      budget_state: "held" | "sent" | "unknown" | "settled" | "released";
      reserved_minor: number;
      charged_minor: number | null;
      requires_reconciliation: boolean;
      retry_allowed: boolean;
      retry_blocked_reason: {
        code: string;
        message: string;
      } | null;
    }[];
  }[];
  preparation: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      base_draft_revision: number;
      price_version_id: string;
      currency: "USD" | "CNY";
      amount_scale: 1000000000;
      total_limit_minor: number;
      sections: {
        section_id: string;
        base_section_revision: number;
        instruction: string;
        source_version_ids: string[];
        selected_node_ids: string[] | null;
        max_tokens: number;
        budget_limit_minor: number;
      }[];
      reason: string;
    };
    if_match: string | null;
  };
  resolution: {
    protocol: "authoring-generation-batch-command/1";
    bid_id: string;
    draft_id: string;
    batch_id: string;
    batch_digest: string;
    kind: "created" | "retried" | "applied" | "rejected";
    batch_state: "open" | "applied" | "rejected";
    created_job_ids: string[];
    applied_section_ids: string[];
    unselected_section_ids: string[];
    draft_revision: number | null;
    snapshot_id: string | null;
    snapshot_digest: string | null;
    recorded_at: string;
    command: {
      command_id: string;
      actor_id: string;
      idempotency_key: string;
      request_digest: string;
      request:
        | {
            base_draft_revision: number;
            price_version_id: string;
            currency: "USD" | "CNY";
            amount_scale: 1000000000;
            total_limit_minor: number;
            sections: {
              section_id: string;
              base_section_revision: number;
              instruction: string;
              source_version_ids: string[];
              selected_node_ids: string[] | null;
              max_tokens: number;
              budget_limit_minor: number;
            }[];
            reason: string;
          }
        | {
            batch_digest: string;
            section_id: string;
            previous_attempt: number;
            previous_job_id: string;
            reason: string;
          }
        | {
            decision: "apply" | "reject";
            batch_digest: string;
            selections: {
              section_id: string;
              attempt: number;
              job_id: string;
              action_id: string;
              candidate_digest: string;
            }[];
            reason: string;
          };
      if_match: string | null;
    };
  } | null;
  current_validity: "rechecked_on_retry_and_apply";
  requires_explicit_selection: true;
  atomic_apply: true;
};

export type AuthoringGenerationBatchPage = {
  bid_id: string;
  draft_id: string;
  items: {
    batch_id: string;
    bid_id: string;
    draft_id: string;
    batch_digest: string;
    base_draft_revision: number;
    state: "open" | "applied" | "rejected";
    created_at: string;
    created_by: string;
    section_count: number;
    ready_count: number;
    failed_count: number;
    running_count: number;
    budget: {
      currency: "USD" | "CNY";
      amount_scale: 1000000000;
      limit_minor: number;
      charged_minor: number;
      reserved_minor: number;
      exposure_minor: number;
      remaining_minor: number;
      requires_reconciliation: boolean;
      over_limit: boolean;
      estimate_not_provider_spend_cap: true;
    };
  }[];
  next_cursor: string | null;
  has_more: boolean;
};

export type AuthoringGenerationBatchCandidate = {
  protocol: "authoring-generation-candidate/1";
  generation_mode: "section_patch_set/1";
  bid_id: string;
  draft_id: string;
  batch_id: string;
  batch_digest: string;
  section_id: string;
  attempt: number;
  job_id: string;
  writing_plan_id: string;
  action_id: string;
  candidate_digest: string;
  base_draft_revision: number;
  base_section_revision: number;
  base_draft_etag: string;
  before_digest: string;
  after_digest: string;
  scope_digest: string;
  before: AuthoringGenerationJson;
  after: AuthoringGenerationJson;
  changes: {
    replaced_node_ids: string[];
    insertions: {
      after_node_id: string | null;
      node_ids: string[];
    }[];
    added_paragraphs: number;
  };
  created_at: string;
  expires_at: string;
  state: "pending" | "executed" | "rejected" | "expired" | "stale" | "failed";
  etag: string;
};

export type AuthoringGenerationBatchCapabilities = {
  enabled: boolean;
  unavailable_reason: {
    code: string;
    message: string;
  } | null;
  generation_mode: "section_patch_set/1";
  max_sections: number;
  max_attempts_per_section: number;
  max_frozen_bytes: number;
  max_instruction_chars: number;
  max_limit_minor: number;
  amount_scale: 1000000000;
  default_max_tokens: number;
  price: {
    price_version_id: string;
    version: string;
    provider: string;
    model: string;
    currency: "USD" | "CNY";
    amount_scale: 1000000000;
    input_upper: number;
    output_upper: number;
    input_per_million_minor: number;
    output_per_million_minor: number;
    valid_until: string;
    source_kind: string;
    source_uri: string;
    source_sha256: string;
  } | null;
  estimates: {
    max_tokens: number;
    reservation_minor: number;
  }[];
  requires_explicit_selection: true;
  atomic_apply: true;
  requires_verified_identity: true;
  automatic_retry_authorized: false;
};

export type AuthoringWordImportPrepareRequest = {
  source_document_version_id: string;
  source_digest: string;
  source_byte_size: number;
  base_draft_revision: number;
  method_digest: string;
  reason: string;
};

export type AuthoringWordImportResolveRequest = {
  decision: "append" | "reject";
  candidate_digest: string;
  acknowledged_issue_ids: string[];
  reason: string;
};

export type AuthoringWordImportCandidate = {
  candidate_id: string;
  bid_id: string;
  draft_id: string;
  candidate_digest: string;
  source: {
    document_version_id: string;
    digest: string;
    byte_size: number;
    media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    filename: string;
    role: string;
    file_id: string;
    file_revision: number;
    intake_digest: string;
  };
  base_draft_revision: number;
  method_digest: string;
  state: "ready" | "blocked" | "applied" | "rejected";
  created_at: string;
  created_by: string;
  section_count: number;
  image_count: number;
  warning_count: number;
  blocker_count: number;
  protocol: "authoring-word-import-candidate/1";
  base_snapshot_id: string;
  base_draft_etag: string;
  before_digest: string;
  existing_sections: {
    section_id: string;
    parent_id: string | null;
    ordinal: number;
    title: string;
  }[];
  method: AuthoringWordImportJson;
  sections: {
    key: string;
    parent_key: string | null;
    section_id: string;
    parent_id: string | null;
    ordinal: number;
    title: string;
    source_path: string;
    content: AuthoringWordImportJson;
  }[];
  mapping: {
    source_path: string;
    section_key: string;
    node_id: string;
    kind: string;
  }[];
  images: {
    key: string;
    source_part: string;
    source_digest: string;
    source_byte_size: number;
    source_media_type: "image/png" | "image/jpeg";
    media_type: "image/png";
    digest: string;
    byte_size: number;
    width_px: number;
    height_px: number;
  }[];
  issues: {
    id: string;
    code: string;
    severity: "warning" | "blocker";
    source_path: string;
    message: string;
  }[];
  can_apply: boolean;
  current_validity: "rechecked_on_append";
  append_only: true;
  reason: string;
  preparation: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      source_document_version_id: string;
      source_digest: string;
      source_byte_size: number;
      base_draft_revision: number;
      method_digest: string;
      reason: string;
    };
    if_match: string | null;
  };
  resolution: AuthoringWordImportResult | null;
};

export type AuthoringWordImportResult = {
  bid_id: string;
  draft_id: string;
  candidate_id: string;
  candidate_digest: string;
  decision: "append" | "reject";
  state: "applied" | "rejected";
  created_section_ids: string[];
  draft_revision: number | null;
  snapshot_id: string | null;
  snapshot_digest: string | null;
  resolved_at: string;
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      decision: "append" | "reject";
      candidate_digest: string;
      acknowledged_issue_ids: string[];
      reason: string;
    };
    if_match: string | null;
  };
};

export type AuthoringWordImportPage = {
  bid_id: string;
  draft_id: string;
  items: {
    candidate_id: string;
    bid_id: string;
    draft_id: string;
    candidate_digest: string;
    source: {
      document_version_id: string;
      digest: string;
      byte_size: number;
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
      filename: string;
      role: string;
      file_id: string;
      file_revision: number;
      intake_digest: string;
    };
    base_draft_revision: number;
    method_digest: string;
    state: "ready" | "blocked" | "applied" | "rejected";
    created_at: string;
    created_by: string;
    section_count: number;
    image_count: number;
    warning_count: number;
    blocker_count: number;
  }[];
  next_cursor: string | null;
  has_more: boolean;
};

export type AuthoringWordImportCapabilities = {
  enabled: boolean;
  unavailable_reason: {
    code: string;
    message: string;
  } | null;
  method_digest: string;
  method: AuthoringWordImportJson;
  supported: string[];
  limitations: string[];
  limits: {
    max_docx_bytes: number;
    max_candidate_bytes: number;
    max_sections: number;
    max_images: number;
  };
  append_only: true;
  requires_registered_original: true;
  requires_loss_acknowledgement: true;
};

export type DocumentParseContext = {
  context: {
    protocol: "document-parse-context/1";
    bid_id: string;
    document_version_id: string;
    document: {
      sha256: string;
      byte_size: number;
      media_type: "application/pdf";
      filename: string;
      file_id: string;
      file_revision: number;
      role: "body" | "tender" | "supplement" | "drawing" | "boq";
      artifact_kind: "source_original" | "bid_body";
      locator_digest: string;
    };
    qualification: {
      kind: "verified_upload" | "adopted_generated";
      identity_digest: string;
    };
    source: {
      root_id: string;
      state: "unregistered" | "published";
      authority_digest: string;
    };
    method: {
      protocol: "document-parse-method/1";
      mode: "physical_text_only" | "configured_local";
      parser_digest: string;
      config_digest: string;
      implementation_digest: string;
      max_bytes: 104857600;
      max_pages: 1000;
    };
    word_coverage_claimed: false;
    current_body_changed: false;
    automatically_started_review: false;
  };
  context_digest: string;
};

export type StartDocumentParse = {
  context_digest: string;
  reason: string;
};

export type DocumentParseView = {
  protocol: "document-parse-request/1";
  id: string;
  bid_id: string;
  document_version_id: string;
  actor_id: string;
  created_at: string;
  context: {
    protocol: "document-parse-context/1";
    bid_id: string;
    document_version_id: string;
    document: {
      sha256: string;
      byte_size: number;
      media_type: "application/pdf";
      filename: string;
      file_id: string;
      file_revision: number;
      role: "body" | "tender" | "supplement" | "drawing" | "boq";
      artifact_kind: "source_original" | "bid_body";
      locator_digest: string;
    };
    qualification: {
      kind: "verified_upload" | "adopted_generated";
      identity_digest: string;
    };
    source: {
      root_id: string;
      state: "unregistered" | "published";
      authority_digest: string;
    };
    method: {
      protocol: "document-parse-method/1";
      mode: "physical_text_only" | "configured_local";
      parser_digest: string;
      config_digest: string;
      implementation_digest: string;
      max_bytes: 104857600;
      max_pages: 1000;
    };
    word_coverage_claimed: false;
    current_body_changed: false;
    automatically_started_review: false;
  };
  context_digest: string;
  reason: string;
  operation: {
    id: string;
    kind: "parse-document";
    state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "cancelled"
      | "succeeded"
      | "failed";
    input_digest: string;
    handler_version: "document-parse/1";
    error_code: string | null;
    created_at: string;
    finished_at: string | null;
  };
  result: {
    parse_run_id: string;
    document_version_id: string;
    source_digest: string;
    parser_digest: string;
    config_digest: string;
    parsed_digest: string;
    coverage: "complete" | "partial" | "failed";
    page_count: number;
    evidence_count: number;
    gaps: string[];
    gap_count: number;
    word_coverage_claimed: false;
  } | null;
  current_body_changed: false;
  automatically_started_review: false;
};

export type DocumentParseStarted = {
  protocol: "document-parse-start/1";
  actor_id: string;
  command_id: string;
  request_digest: string;
  reused: boolean;
  request: DocumentParseView;
};

export type DocumentParsePage = {
  bid_id: string;
  document_version_id: string;
  items: DocumentParseView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type AdoptAuthoringOutput = {
  snapshot_id: string;
  snapshot_digest: string;
  package_id: string | null;
  member: {
    member_id: string;
    document_version_id: string;
    parse_run_id?: string;
    purposes: string[];
    parts: {
      part_id: string;
      category: string;
      first_page: number;
      last_page: number;
      shared_attachment: boolean;
      heading_path: number[];
    }[];
  };
  reason: string;
};

export type AuthoringOutputAdopted = {
  protocol: "authoring-output-adoption/1";
  bid_id: string;
  build_id: string;
  actor_id: string;
  command_id: string;
  request_digest: string;
  output: AuthoringOutputQualification;
  package: BidPackageStoredView;
  package_etag: string;
  automatically_started_review: false;
  current_body_changed: false;
};

export type AuthoringOutputQualification = {
  protocol: "authoring-build-output/1";
  bid_id: string;
  build_id: string;
  document_version_id: string;
  format: "docx" | "pdf";
  sha256: string;
  byte_size: number;
  build_identity: {
    draft_id: string;
    draft_revision: number;
    snapshot_id: string;
    snapshot_digest: string;
    build_input_id: string;
    input_digest: string;
    manifest_digest: string;
    writer_kind:
      | "strict_text/1"
      | "structured_text/1"
      | "generated_text/2"
      | "generated_rich/3";
  };
  word_document_version_id: string;
  word_sha256: string;
  word_pdf_relation: "verified" | "not_applicable";
  publication_receipt_digest: string;
  source_authority_digest: string;
  direct_source_ids: string[];
};

export type PackageReviewReportContext = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  input_digest: string;
  result_digest: string;
  human_decisions_digest: string;
  method_digest: string;
  context_digest: string;
  formats: ("docx" | "pdf")[];
  pdf_unavailable_code: string | null;
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type StartPackageReviewReport = {
  context_digest: string;
  format: "docx" | "pdf";
};

export type PackageReviewReportView = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  input_digest: string;
  result_digest: string;
  id: string;
  actor_id: string;
  created_at: string;
  context_digest: string;
  report_input_digest: string;
  format: "docx" | "pdf";
  artifact_kind: "review_report";
  operation: {
    id: string;
    kind: "package-scope-report";
    state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    input_digest: string;
    handler_version: "package-report/1";
    error_code: string | null;
    created_at: string;
    finished_at: string | null;
  };
  result: {
    document_version_id: string;
    blob_digest: string;
    byte_size: number;
    media_type:
      | "application/pdf"
      | "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    filename: string;
    gaps: string[];
  } | null;
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type PackageReviewReportPage = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  input_digest: string;
  result_digest: string;
  items: PackageReviewReportView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageReviewComparisonPage = {
  version: "package-review-comparison/1";
  kind: "declared_scope_review_comparison";
  bid_id: string;
  match_policy: "exact_requirement_id_and_definition_digests/1";
  left: PackageReviewComparisonRun;
  right: PackageReviewComparisonRun;
  input_changes: {
    run_input: boolean;
    scope: boolean;
    frozen_input: boolean;
    prepared_input: boolean;
    rerun_intent: boolean;
    requirements: boolean;
    submitted_documents: boolean;
    selected_facts: boolean;
    fact_admission: boolean;
    dependency_plan: boolean;
    inventory_proof: boolean;
    method: boolean;
    method_fields: (
      | "assessment"
      | "batch_limit"
      | "batch_rule_limit"
      | "endpoint"
      | "engine"
      | "formal_scoring_eligible"
      | "input_character_limit"
      | "input_scope"
      | "model"
      | "model_json_encoding"
      | "output_tokens_per_batch"
      | "purpose"
      | "semantic_quality"
      | "source_digest"
      | "submission_eligible"
    )[];
  };
  counts: {
    added: number;
    removed: number;
    changed: number;
    unchanged: number;
    machine_row_changed: number;
    verdict_changed: number;
  };
  overall_coverage: "partial";
  risk_resolution_assessed: false;
  inventory_complete: false;
  formal_scoring_eligible: false;
  submission_eligible: false;
  comparison_digest: string;
  items: PackageReviewComparisonRow[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageReviewComparisonRun = {
  id: string;
  actor_id: string;
  created_at: string;
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  frozen_input_digest: string;
  execution_input_id: string;
  execution_input_digest: string;
  execution_digest: string;
  input_digest: string;
  method_digest: string;
  dependency_plan_id: string;
  dependency_plan_digest: string;
  result_digest: string;
  requirement_count: number;
  matrix_coverage: "partial" | "complete";
  overall_coverage: "partial";
  human_heads_digest: string;
};

export type PackageReviewComparisonRow = {
  requirement_id: string;
  definition_change: "added" | "removed" | "changed" | "unchanged";
  machine_row_changed: boolean | null;
  verdict_transition: {
    from:
      | "satisfied"
      | "violated"
      | "not_found"
      | "unable_to_judge"
      | "not_applicable";
    to:
      | "satisfied"
      | "violated"
      | "not_found"
      | "unable_to_judge"
      | "not_applicable";
    changed: boolean;
  } | null;
  left: PackageReviewComparisonRowSide | null;
  right: PackageReviewComparisonRowSide | null;
  left_human: PackageReviewHumanDecisionSummary | null;
  right_human: PackageReviewHumanDecisionSummary | null;
};

export type PackageReviewComparisonRowSide = {
  row_digest: string;
  requirement_digest: PackageScopeReview_Digest;
  rule_digest: PackageScopeReview_Digest;
  rule_kind: "disqualification" | "mandatory" | "scoring" | "advisory";
  requirement_statement: string;
  applicability: "applicable" | "unknown" | "not_applicable";
  target_part_ids: string[];
  verdict:
    | "satisfied"
    | "violated"
    | "not_found"
    | "unable_to_judge"
    | "not_applicable";
  statement: string;
  limitations: string[];
};

export type StartPackageReviewRun = {
  execution_input_digest: string;
  dependency_plan_id: string;
  dependency_plan_digest: string;
};

export type PackageReviewRunInput = PackageScopeReview_Input;

export type PackageReviewRunInputView = {
  manifest: PackageReviewRunInput;
  digest: string;
};

export type PackageReviewRunView = {
  kind: "package_review_run";
  id: string;
  actor_id: string;
  created_at: string;
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  frozen_input_digest: string;
  execution_input_id: string;
  execution_input_digest: string;
  execution_digest: string;
  dependency_plan_id: string;
  dependency_plan_digest: string;
  input_digest: string;
  method_digest: string;
  operation: {
    id: string;
    kind: "package-scope-review";
    state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    input_digest: string;
    handler_version: "package-review/1";
    error_code: string | null;
    created_at: string;
    finished_at: string | null;
  };
  result: {
    manifest: PackageReviewResult;
    digest: string;
  } | null;
};

export type PackageReviewRunSummary = {
  kind: "package_review_run";
  id: string;
  actor_id: string;
  created_at: string;
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  frozen_input_digest: string;
  execution_input_id: string;
  execution_input_digest: string;
  execution_digest: string;
  dependency_plan_id: string;
  dependency_plan_digest: string;
  input_digest: string;
  method_digest: string;
  operation: {
    id: string;
    kind: "package-scope-review";
    state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    input_digest: string;
    handler_version: "package-review/1";
    error_code: string | null;
    created_at: string;
    finished_at: string | null;
  };
  result: {
    digest: string;
    requirement_count: number;
    matrix_coverage: "complete" | "partial";
    overall_coverage: "partial";
  } | null;
};

export type SavePackageReviewHumanDecision = {
  result_digest: string;
  row_digest: string;
  expected_head: {
    id: string;
    digest: string;
  } | null;
  state: "confirmed" | "rejected" | "needs_review";
  reason: string;
  selected_quotes: PackageScopeReview_Quote[];
};

export type PackageReviewHumanDecision = {
  version: "package-review-human-decision/1";
  id: string;
  actor_id: string;
  created_at: string;
  sequence_no: number;
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  requirement_id: string;
  input_digest: string;
  result_digest: string;
  row_digest: string;
  previous_head: {
    id: string;
    digest: string;
  } | null;
  state: "confirmed" | "rejected" | "needs_review";
  reason: string;
  selected_quotes: PackageScopeReview_Quote[];
  inventory_complete: false;
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type PackageReviewHumanDecisionView = {
  manifest: PackageReviewHumanDecision;
  digest: string;
};

export type PackageReviewHumanDecisionCurrent = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  result_digest: string;
  items: {
    requirement_id: string;
    row_digest: string;
    current: PackageReviewHumanDecisionSummary | null;
  }[];
};

export type PackageReviewHumanDecisionPage = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  run_id: string;
  result_digest: string;
  requirement_id: string;
  row_digest: string;
  items: PackageReviewHumanDecisionView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type AuthoringRichCapabilities = {
  schema_digest: string;
  schema: AuthoringJsonValue;
  build_schema_digest: string;
  image_upload_max_bytes: 8388608;
  renderer_configured: boolean;
  runtime_verified_by_this_read: false;
  table_pdf_geometry: "unverified";
  pagination_modes: {
    mode: "chapter_start_new_page" | "continuous";
    page_count_impact: string;
  }[];
};

export type AuthoringRichBuildRequest = {
  draft_id: string;
  draft_revision: number;
  directory_template_version_id: string;
  style_template_version_id: string;
  formats: ("docx" | "pdf")[];
  follow_up: "none" | "review";
  pagination_mode: "chapter_start_new_page" | "continuous";
};

export type AuthoringRichDocument = {
  type: "doc";
  attrs: {
    title: string;
    ordinal: number;
    rule_ids: string[];
    source_refs: AuthoringSourceReference[];
  };
  content: (AuthoringBlock | AuthoringRichTable | AuthoringRichImage)[];
};

export type AuthoringImageUpload = {
  title: string;
  reason: string;
  media_type: "image/png" | "image/jpeg";
  content_base64: string;
  source_refs: AuthoringSourceReference[];
};

export type AuthoringImageCreated = {
  id: string;
  bid_id: string;
  asset_id: string;
  revision: number;
  previous_revision: number | null;
  previous_version_id: string | null;
  state: "active" | "withdrawn";
  reason: string;
  original_blob_id: string;
  normalized_blob_id: string;
  original_media_type: "image/png" | "image/jpeg";
  width_px: number;
  height_px: number;
  normalization_proof: AuthoringJsonValue;
  source_refs: AuthoringSourceReference[];
  digest: string;
  created_by: string;
  created_at: string;
  title: string;
  head_revision: number;
  head_version_id: string;
  is_current: boolean;
  etag: string;
  upload_id: string;
};

export type AuthoringImageView = {
  id: string;
  bid_id: string;
  asset_id: string;
  revision: number;
  previous_revision: number | null;
  previous_version_id: string | null;
  state: "active" | "withdrawn";
  reason: string;
  original_blob_id: string;
  normalized_blob_id: string;
  original_media_type: "image/png" | "image/jpeg";
  width_px: number;
  height_px: number;
  normalization_proof: AuthoringJsonValue;
  source_refs: AuthoringSourceReference[];
  digest: string;
  created_by: string;
  created_at: string;
  title: string;
  head_revision: number;
  head_version_id: string;
  is_current: boolean;
  etag: string;
};

export type AuthoringImagePage = {
  items: AuthoringImageView[];
  next_cursor: string | null;
};

export type AuthoringImageUploadStatus = {
  upload_id: string;
  state: "prepared" | "unconfirmed" | "rejected" | "completed";
  asset_id: string | null;
  asset_version_id: string | null;
  error_code: string | null;
  automatic_retry: false;
  retry_requires_same_input: true;
  updated_at: string;
};

export type AuthoringBuildLayout = {
  scope: "navigation_only";
  pagination_mode: "chapter_start_new_page" | "continuous";
  state: "pending" | "partial" | "complete";
  fixed_point: boolean;
  page_count: number | null;
  iteration_count: number;
  entries: {
    section_id: string;
    start_page: number | null;
    end_page: number | null;
    printed_toc_page: number | null;
    gaps: string[];
  }[];
  gaps: string[];
};

export type PackageReviewRunPage = {
  scope: {
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  frozen_input_id: string;
  execution_input_id: string;
  execution_input_digest: string;
  items: PackageReviewRunSummary[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageReviewResult = PackageScopeReview_Result;

export type SavePackageDependencyPlan = PackageDependencyPlan_Save;

export type PackageDependencyPlanView = PackageDependencyPlan_View;

export type PackageDependencyPlanPage = {
  prepared: PackageDependencyPlan_Assessment_Prepared;
  items: PackageDependencyPlanSummary[];
  has_more: boolean;
  next_cursor: string | null;
  inventory_complete: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type CheckPackageInputDependencies = {
  execution_input_digest: string;
  purpose: "prebid_compliance";
  fact_ids: string[];
  dependencies: PackageInputDependencies_Dependency[];
};

export type PackageInputDependencyAssessment = PackageInputDependencies_View;

export type ConfirmPackageFact = PackageFactChange_ConfirmRequest;

export type WithdrawPackageFact = PackageFactChange_WithdrawRequest;

export type PackageFactChangeView = PackageFactChange_Record;

export type PackageCurrentFactPage = {
  version: "package-current-facts/1";
  kind: "current_package_facts";
  fact_count: number;
  items: PackageCurrentFactSummary[];
  has_more: boolean;
  next_cursor: string | null;
  binding: PackageFactChange_Binding;
  head: PackageFactChange_Head;
  checked_at: string;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  required_facts_assessment: "not_performed";
  source_packages: PackageFactSourcePackage[];
};

export type PackageCurrentFactDetail = {
  version: "package-current-fact/1";
  kind: "current_package_fact";
  summary: PackageCurrentFactSummary;
  editability: "editable" | "unsupported_or_oversized";
  editable_fact: PackageEditableFact | null;
  binding: PackageFactChange_Binding;
  head: PackageFactChange_Head;
  checked_at: string;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  required_facts_assessment: "not_performed";
  evidence_references: PackageFactEvidenceReference[];
  evidence_truncated: boolean;
};

export type PackagePreparedFactPage = {
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  frozen_input_id: string;
  execution_input_id: string;
  execution_input_digest: string;
  facts_digest: string;
  fact_set_id: string | null;
  fact_count: number;
  items: PackagePreparedFactSummary[];
  has_more: boolean;
  next_cursor: string | null;
};

export type ChangePackageFactScope = PackageFactScope_Change;

export type PackageFactScopeView = PackageFactScope_Record;

export type PackageFactScopeObservation = {
  kind: "fact_scope_observation";
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  frozen_input_id: string;
  execution_input_id: string;
  fact_id: string;
  execution_input_digest: string;
  prepared_context_digest: string;
  observed_context_digest: string | null;
  matches_prepared_input: boolean;
  provenance_status: "verified" | "unproven";
  subject_choices: {
    kind: "engineering_project" | "lot" | "round" | "bidder";
    id: PackageFactScope_Id;
    label: string;
  }[];
  head: PackageFactScope_Record | null;
  binding_status: "unproven" | "matches_current_input" | "withdrawn";
  observation_gap: string | null;
  checked_at: string;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type CheckPackageExecutionFacts = {
  execution_input_digest: string;
};

export type PackageExecutionFactCheck = {
  kind: "fact_validation_observation";
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  frozen_input_id: string;
  execution_input_id: string;
  execution_input_digest: string;
  prepared_context_digest: string;
  observed_context_digest: string;
  observed_facts_digest: string;
  matches_prepared_context: boolean;
  checked_at: string;
  fact_count: number;
  provenance_verified_count: number;
  fact_checks: PackageFactValidationItem[];
  blockers: "FACT_SET_EMPTY"[];
  facts_qualified: false;
  original_verification: "not_performed";
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type SavePackageExecutionInput = {
  frozen_digest: string;
  context_digest: string;
  rerun: PackageExecution_RerunIntent | null;
};

export type PackageExecutionInputView = {
  manifest: PackageExecutionInputManifest;
  digest: string;
};

export type CheckPackageReviewEligibility = {
  frozen_digest: string;
};

export type PackageReviewEligibilityObservation = {
  kind: "eligibility_observation";
  frozen_input_id: string;
  frozen_digest: string;
  input_digest: string;
  checked_at: string;
  current_context: PackageReviewExecutionContext;
  parse_evidence_status: "matched" | "mismatch";
  original_verification: "not_performed";
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  blockers: (
    | "PROJECT_WORK_CLOSED"
    | "PACKAGE_BIDDER_UNCONFIRMED"
    | "PACKAGE_REVIEW_IDENTITY_STALE"
    | "PACKAGE_REVIEW_PACKAGE_STALE"
    | "PACKAGE_REVIEW_INVENTORY_STALE"
    | "PACKAGE_REVIEW_RULE_SET_STALE"
    | "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_CHANGED"
    | "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE"
    | "PACKAGE_REVIEW_MEMBERS_UNPROVEN"
    | "PACKAGE_REVIEW_EVIDENCE_CHANGED"
    | "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP"
    | "PACKAGE_REVIEW_EXTRACTION_UNPROVEN"
    | "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN"
    | "PACKAGE_REVIEW_EXECUTOR_NOT_READY"
    | "PACKAGE_REVIEW_METHOD_CHANGED"
    | "PACKAGE_REVIEW_POLICY_CHANGED"
    | "PACKAGE_REVIEW_FACTS_CHANGED"
    | "PACKAGE_REVIEW_FACTS_UNPROVEN"
  )[];
};

export type PackageReviewFrozenInputPage = {
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  items: {
    id: string;
    digest: string;
    actor_id: string;
    frozen_at: string;
    input_digest: string;
    context_digest: string;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type FreezePackageReviewInput = {
  package_digest: string;
  inventory_digest: string;
  coverage_attempt_id: string | null;
  coverage_digest: string | null;
  input_digest: string;
  context_digest: string;
};

export type PackageReviewFrozenInputView = {
  manifest: PackageReviewFrozenInputManifest;
  digest: string;
};

export type PackageReviewOriginalVerification = {
  kind: "observation";
  execution_context: PackageReviewExecutionContext;
  input_digest: string;
  checked_at: string;
  originals_verified: true;
  review_ready: false;
  launch_available: false;
  blockers: (
    | "PROJECT_WORK_CLOSED"
    | "PACKAGE_BIDDER_UNCONFIRMED"
    | "PACKAGE_REVIEW_IDENTITY_STALE"
    | "PACKAGE_REVIEW_PACKAGE_STALE"
    | "PACKAGE_REVIEW_INVENTORY_STALE"
    | "PACKAGE_REVIEW_RULE_SET_STALE"
    | "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_CHANGED"
    | "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE"
    | "PACKAGE_REVIEW_MEMBERS_UNPROVEN"
    | "PACKAGE_REVIEW_EVIDENCE_CHANGED"
    | "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP"
    | "PACKAGE_REVIEW_EXTRACTION_UNPROVEN"
    | "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN"
    | "PACKAGE_REVIEW_EXECUTOR_NOT_READY"
  )[];
  originals: PackageReviewVerifiedOriginal[];
};

export type PackageReviewOriginalVerificationRequest = {
  package_digest: string;
  inventory_digest: string;
  coverage_attempt_id: string | null;
  coverage_digest: string | null;
  input_digest: string;
};

export type PackageReviewInputPreviewRequest = {
  package_digest: string;
  inventory_digest: string;
  coverage_attempt_id: string | null;
  coverage_digest: string | null;
};

export type PackageReviewInputManifest = {
  version: "bid-package-review-input/1";
  kind: "preview";
  bid_id: string;
  target: BidPackageStoredView;
  authority: BidPackageStoredView;
  inventory: PackageRequirementInventoryView;
  coverage: PackageCoverageAttemptView | null;
};

export type PackageReviewInputPreview = {
  manifest: PackageReviewInputManifest;
  digest: string;
  review_ready: false;
  launch_available: false;
  blockers: (
    | "PROJECT_WORK_CLOSED"
    | "PACKAGE_BIDDER_UNCONFIRMED"
    | "PACKAGE_REVIEW_IDENTITY_STALE"
    | "PACKAGE_REVIEW_PACKAGE_STALE"
    | "PACKAGE_REVIEW_INVENTORY_STALE"
    | "PACKAGE_REVIEW_RULE_SET_STALE"
    | "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_CHANGED"
    | "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE"
    | "PACKAGE_REVIEW_MEMBERS_UNPROVEN"
    | "PACKAGE_REVIEW_EVIDENCE_CHANGED"
    | "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP"
    | "PACKAGE_REVIEW_EXTRACTION_UNPROVEN"
    | "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN"
    | "PACKAGE_REVIEW_EXECUTOR_NOT_READY"
  )[];
  physical_page_gaps: {
    role: "target" | "authority";
    member_id: string;
    first_page: number;
    last_page: number;
  }[];
};

export type CreatePackageRequirementInventory = {
  authority_revision_id: string;
  rule_set_id: string;
  mappings: {
    rule_id: string;
    categories: string[];
    target_part_ids: string[];
    minimum_count: number | null;
    applicability: "applicable" | "unknown" | "not_applicable";
    applicability_evidence_ids: string[];
    valid_at: string | null;
    checks: string[];
    reason: string;
    basis_evidence_ids: string[];
  }[];
};

export type CreatePackageCoverageAttempt = {
  inventory_digest: string;
  package_digest: string;
  results: {
    rule_id: string;
    requirement_digest: string;
    state:
      | "not_provided"
      | "missing"
      | "pending_parse"
      | "parse_gap"
      | "unsupported"
      | "verified"
      | "not_applicable"
      | "conflict"
      | "unknown";
    inspected: {
      part_id: string;
      first_page: number;
      last_page: number;
    }[];
    evidence_ids: string[];
    reason: string;
    basis_type: "human_scope_declaration" | "human_observation";
  }[];
};

export type PackageRequirementInventoryManifest =
  | {
      version: "bid-package-requirements/1";
      id: string;
      bid_id: string;
      package_id: string;
      target_revision_id: string;
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      revision: number;
      predecessor_digest: string | null;
      identity_digest: string;
      source_snapshot: { [key: string]: unknown }[];
      requirements: {
        rule_id: string;
        rule_digest: string;
        rule_snapshot: { [key: string]: unknown };
        decision_id: string | null;
        decision_snapshot: { [key: string]: unknown } | null;
        requirement: BidPackage_requirement;
        requirement_digest: string;
        source_bound: boolean;
        annotation: {
          kind: "human_check_plan_declaration";
          mapped: boolean;
          reason: string | null;
          basis_evidence_ids: string[];
        };
      }[];
      inventory_complete: false;
      extraction_binding: "unproven_legacy_rule_set";
      review_ready: false;
      actor_id: string;
    }
  | {
      version: "bid-package-requirements/2";
      id: string;
      bid_id: string;
      package_id: string;
      target_revision_id: string;
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      revision: number;
      predecessor_digest: string | null;
      identity_digest: string;
      source_snapshot: { [key: string]: unknown }[];
      requirements: {
        rule_id: string;
        rule_digest: string;
        rule_snapshot: { [key: string]: unknown };
        decision_id: string | null;
        decision_snapshot: { [key: string]: unknown } | null;
        requirement: BidPackage_requirement;
        requirement_digest: string;
        source_bound: boolean;
        annotation: {
          kind: "human_check_plan_declaration";
          mapped: boolean;
          reason: string | null;
          basis_evidence_ids: string[];
        };
      }[];
      inventory_complete: false;
      extraction_binding: "exact_frozen_input_result";
      review_ready: false;
      actor_id: string;
      extraction_input_digest: string;
      extraction_result_digest: string;
      extraction_result_id: string;
      extraction_range_status: "all_frozen_evidence_submitted";
      extraction_coverage: "complete" | "partial" | "conflict";
      extraction_quality_status: "not_measured";
    }
  | {
      version: "bid-package-requirements/3";
      id: string;
      bid_id: string;
      package_id: string;
      target_revision_id: string;
      package_digest: string;
      authority_revision_id: string;
      authority_digest: string;
      rule_set_id: string;
      rule_set_digest: string;
      revision: number;
      predecessor_digest: string | null;
      identity_digest: string;
      source_snapshot: { [key: string]: unknown }[];
      requirements: {
        rule_id: string;
        rule_digest: string;
        rule_snapshot: { [key: string]: unknown };
        decision_id: string | null;
        decision_snapshot: { [key: string]: unknown } | null;
        requirement: BidPackage_requirement;
        requirement_digest: string;
        source_bound: boolean;
        annotation: {
          kind: "human_check_plan_declaration";
          mapped: boolean;
          reason: string | null;
          basis_evidence_ids: string[];
        };
      }[];
      inventory_complete: false;
      extraction_binding: "frozen_extraction_plus_human_derivation";
      review_ready: false;
      actor_id: string;
      extraction_basis: {
        inventory_id: string;
        inventory_digest: string;
        rule_set_id: string;
        rule_set_digest: string;
        extraction_result_id: string;
        extraction_input_digest: string;
        extraction_result_digest: string;
        extraction_range_status: "all_frozen_evidence_submitted";
        extraction_coverage: "complete" | "partial" | "conflict";
        extraction_quality_status: "not_measured";
      };
      human_derivation: {
        version: "package-rule-derivation/1";
        head_id: string;
        head_digest: string;
        length: number;
      };
    };

export type PackageCoverageAttemptManifest = {
  version: "bid-package-coverage/1";
  id: string;
  bid_id: string;
  inventory_id: string;
  inventory_digest: string;
  package_digest: string;
  actor_id: string;
  results: {
    coverage: BidPackage_coverage;
    basis_type: "human_scope_declaration" | "human_observation";
    evidence_ids: string[];
  }[];
  assessment: {
    package_digest: string;
    complete: false;
    requirement_inventory_complete: false;
    requirement_states: {
      [key: string]:
        | "not_provided"
        | "missing"
        | "pending_parse"
        | "parse_gap"
        | "unsupported"
        | "verified"
        | "not_applicable"
        | "conflict"
        | "unknown";
    };
    requirement_digests: { [key: string]: string };
    inspected_ranges: { [key: string]: unknown }[];
    member_gaps: { [key: string]: unknown }[];
  };
  review_ready: false;
};

export type PackageRequirementInventoryView = {
  manifest:
    | {
        version: "bid-package-requirements/1";
        id: string;
        bid_id: string;
        package_id: string;
        target_revision_id: string;
        package_digest: string;
        authority_revision_id: string;
        authority_digest: string;
        rule_set_id: string;
        rule_set_digest: string;
        revision: number;
        predecessor_digest: string | null;
        identity_digest: string;
        source_snapshot: { [key: string]: unknown }[];
        requirements: {
          rule_id: string;
          rule_digest: string;
          rule_snapshot: { [key: string]: unknown };
          decision_id: string | null;
          decision_snapshot: { [key: string]: unknown } | null;
          requirement: BidPackage_requirement;
          requirement_digest: string;
          source_bound: boolean;
          annotation: {
            kind: "human_check_plan_declaration";
            mapped: boolean;
            reason: string | null;
            basis_evidence_ids: string[];
          };
        }[];
        inventory_complete: false;
        extraction_binding: "unproven_legacy_rule_set";
        review_ready: false;
        actor_id: string;
      }
    | {
        version: "bid-package-requirements/2";
        id: string;
        bid_id: string;
        package_id: string;
        target_revision_id: string;
        package_digest: string;
        authority_revision_id: string;
        authority_digest: string;
        rule_set_id: string;
        rule_set_digest: string;
        revision: number;
        predecessor_digest: string | null;
        identity_digest: string;
        source_snapshot: { [key: string]: unknown }[];
        requirements: {
          rule_id: string;
          rule_digest: string;
          rule_snapshot: { [key: string]: unknown };
          decision_id: string | null;
          decision_snapshot: { [key: string]: unknown } | null;
          requirement: BidPackage_requirement;
          requirement_digest: string;
          source_bound: boolean;
          annotation: {
            kind: "human_check_plan_declaration";
            mapped: boolean;
            reason: string | null;
            basis_evidence_ids: string[];
          };
        }[];
        inventory_complete: false;
        extraction_binding: "exact_frozen_input_result";
        review_ready: false;
        actor_id: string;
        extraction_input_digest: string;
        extraction_result_digest: string;
        extraction_result_id: string;
        extraction_range_status: "all_frozen_evidence_submitted";
        extraction_coverage: "complete" | "partial" | "conflict";
        extraction_quality_status: "not_measured";
      }
    | {
        version: "bid-package-requirements/3";
        id: string;
        bid_id: string;
        package_id: string;
        target_revision_id: string;
        package_digest: string;
        authority_revision_id: string;
        authority_digest: string;
        rule_set_id: string;
        rule_set_digest: string;
        revision: number;
        predecessor_digest: string | null;
        identity_digest: string;
        source_snapshot: { [key: string]: unknown }[];
        requirements: {
          rule_id: string;
          rule_digest: string;
          rule_snapshot: { [key: string]: unknown };
          decision_id: string | null;
          decision_snapshot: { [key: string]: unknown } | null;
          requirement: BidPackage_requirement;
          requirement_digest: string;
          source_bound: boolean;
          annotation: {
            kind: "human_check_plan_declaration";
            mapped: boolean;
            reason: string | null;
            basis_evidence_ids: string[];
          };
        }[];
        inventory_complete: false;
        extraction_binding: "frozen_extraction_plus_human_derivation";
        review_ready: false;
        actor_id: string;
        extraction_basis: {
          inventory_id: string;
          inventory_digest: string;
          rule_set_id: string;
          rule_set_digest: string;
          extraction_result_id: string;
          extraction_input_digest: string;
          extraction_result_digest: string;
          extraction_range_status: "all_frozen_evidence_submitted";
          extraction_coverage: "complete" | "partial" | "conflict";
          extraction_quality_status: "not_measured";
        };
        human_derivation: {
          version: "package-rule-derivation/1";
          head_id: string;
          head_digest: string;
          length: number;
        };
      };
  digest: string;
};

export type PackageCoverageAttemptView = {
  manifest: {
    version: "bid-package-coverage/1";
    id: string;
    bid_id: string;
    inventory_id: string;
    inventory_digest: string;
    package_digest: string;
    actor_id: string;
    results: {
      coverage: BidPackage_coverage;
      basis_type: "human_scope_declaration" | "human_observation";
      evidence_ids: string[];
    }[];
    assessment: {
      package_digest: string;
      complete: false;
      requirement_inventory_complete: false;
      requirement_states: {
        [key: string]:
          | "not_provided"
          | "missing"
          | "pending_parse"
          | "parse_gap"
          | "unsupported"
          | "verified"
          | "not_applicable"
          | "conflict"
          | "unknown";
      };
      requirement_digests: { [key: string]: string };
      inspected_ranges: { [key: string]: unknown }[];
      member_gaps: { [key: string]: unknown }[];
    };
    review_ready: false;
  };
  digest: string;
};

export type PackageRequirementInventoryPage = {
  items: {
    id: string;
    digest: string;
    created_at: string;
  }[];
  has_more: boolean;
  next_cursor: string | null;
  current_inventory_id: string | null;
};

export type PackageRequirementHistoryPage = {
  items: {
    id: string;
    digest: string;
    created_at: string;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type CreateBidPackage = {
  kind: "authority" | "bid";
  members: {
    member_id: string;
    document_version_id: string;
    parse_run_id?: string;
    purposes: string[];
    parts: {
      part_id: string;
      category: string;
      first_page: number;
      last_page: number;
      shared_attachment: boolean;
      heading_path: number[];
    }[];
  }[];
};

export type AppendBidPackage = {
  members: {
    member_id: string;
    document_version_id: string;
    parse_run_id?: string;
    purposes: string[];
    parts: {
      part_id: string;
      category: string;
      first_page: number;
      last_page: number;
      shared_attachment: boolean;
      heading_path: number[];
    }[];
  }[];
};

export type BidPackageStoredView = {
  manifest: BidPackageManifest;
  digest: string;
  identity:
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        round_no: number;
        binding_status: "confirmed" | "pending";
        authority_id: string | null;
        digest: string;
        identity_version?: "bid-identity/1";
      }
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        lot_id: string | null;
        round_no: number;
        binding_status: "confirmed" | "pending";
        authority_id: string | null;
        digest: string;
        identity_version: "bid-identity/2";
      };
  storage_eligible: boolean;
  review_ready: false;
};

export type BidPackageManifest = {
  package_id: string;
  revision_id: string;
  revision: number;
  kind: "authority" | "bid";
  scope: BidPackage_scope;
  members: BidPackage_member[];
  predecessor_digest: string | null;
  identity_version: "bid-package/1";
};

export type BidPackageHeadPage = {
  items: BidPackageHead[];
  has_more: boolean;
  next_cursor: string | null;
};

export type BidPackageRevisionSummaryPage = {
  items: BidPackageRevisionSummary[];
  has_more: boolean;
  next_cursor: string | null;
};

export type BidPackageDocumentPage = {
  items: BidPackageDocument[];
  has_more: boolean;
  next_cursor: string | null;
};

export type BidPackageParsePage = {
  items: BidPackageParse[];
  has_more: boolean;
  next_cursor: string | null;
};

export type PackageEvidencePage = {
  revision_id: string;
  package_digest: string;
  items: {
    id: string;
    document_version_id: string;
    parse_run_id: string;
    physical_page: number;
    part_ids: string[];
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type AuthoringTemplateCreate = {
  name: string;
  kind: "outline" | "layout";
  config:
    | {
        schema_version: 1;
        nodes: {
          key: string;
          parent_key: string | null;
          ordinal: number;
          title: string;
          node_type: "chapter" | "appendix";
          goal?: string;
          planned_pages?: number | null;
        }[];
      }
    | {
        schema_version: 1;
        page: "A4";
        font: "Noto Sans CJK SC" | "Noto Serif CJK SC";
        font_size_halfpoints: number;
        margin_top_twips: number;
        margin_right_twips: number;
        margin_bottom_twips: number;
        margin_left_twips: number;
        paragraph_after_twips: number;
        cover_enabled: boolean;
        cover_title: string;
        header_text: string;
        footer_text: string;
        page_number: boolean;
        chapter_numbering: "decimal" | "none";
        toc_enabled: boolean;
      };
};

export type AuthoringTemplateVersion = {
  base_revision: number;
  name: string;
  config:
    | {
        schema_version: 1;
        nodes: {
          key: string;
          parent_key: string | null;
          ordinal: number;
          title: string;
          node_type: "chapter" | "appendix";
          goal?: string;
          planned_pages?: number | null;
        }[];
      }
    | {
        schema_version: 1;
        page: "A4";
        font: "Noto Sans CJK SC" | "Noto Serif CJK SC";
        font_size_halfpoints: number;
        margin_top_twips: number;
        margin_right_twips: number;
        margin_bottom_twips: number;
        margin_left_twips: number;
        paragraph_after_twips: number;
        cover_enabled: boolean;
        cover_title: string;
        header_text: string;
        footer_text: string;
        page_number: boolean;
        chapter_numbering: "decimal" | "none";
        toc_enabled: boolean;
      };
};

export type WordOriginalView = {
  id: string;
  bid_id: string;
  file_id: string;
  original_name: string;
  role: string;
  original_saved: true;
  source_sha256: string;
  byte_size: number;
  inspection: WordInspectionView;
  conversion: WordConversionView;
  message: string;
  delivery_check_message: "Word交付未获对应检查资格";
  review_qualification: "not_established_by_conversion";
  primary_action: {
    action: "upload_modified_pdf";
    label: "上传此修改稿的PDF";
    context: {
      bid_id: string;
      role:
        | "tender"
        | "supplement"
        | "drawing"
        | "boq"
        | "body"
        | "official_result"
        | "other";
      declared_source_document_version_id: string;
      target: {
        kind: "new_file";
      };
    };
  };
  converted_pdf_action: null | {
    action: "open_pdf";
    document_version_id: string;
  };
};

export type WordOriginalPage = {
  items: WordOriginalView[];
  has_more: boolean;
  next_after: string | null;
};

export type WordMaterialAdoptionView = {
  bid_id: string;
  source_document_version_id: string;
  file_id: string;
  source_is_file_head: boolean;
  selected_as_current_material: boolean;
  adoption_state: "not_selected" | "pending" | "adopted" | "needs_selection";
  adoption_reason: string | null;
  adopted_pdf_document_version_id: string | null;
  is_current_converted_pdf: boolean;
  current_body_version_id: string | null;
  material_revision: number;
};

export type AuthoringTreeView = {
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  structure_version_id: string | null;
  nodes: {
    section_id: string;
    parent_id: string | null;
    ordinal: number;
    node_type: "chapter" | "appendix";
    deleted: boolean;
    section_revision: number;
    plan_version_id: string | null;
    template_family_id: string | null;
    template_key: string | null;
    title: string;
    rule_ids: string[];
    source_refs: {
      source_id: string;
      source_revision: number;
      evidence_id: string;
      document_version_id: string;
    }[];
    plan: AuthoringPlanVersion | null;
    plan_content_basis_state: "none" | "current" | "section_changed";
    actual_page_range: null;
  }[];
  directory_template_version_id: string;
  style_template_version_id: string;
  metadata: { [key: string]: AuthoringJsonValue };
  page_budget: {
    planned_total: number;
    unknown_section_ids: string[];
    actual_total: null;
    actual_ranges_state: "unknown";
  };
};

export type AuthoringTreeChangeRequest = {
  base_draft_revision: number;
  changes: (
    | {
        op: "add";
        client_key: string;
        title: string;
        node_type: "chapter" | "appendix";
        parent:
          | {
              section_id: string;
            }
          | {
              client_key: string;
            }
          | null;
        ordinal: number;
      }
    | {
        op: "move";
        section_id: string;
        parent:
          | {
              section_id: string;
            }
          | {
              client_key: string;
            }
          | null;
        ordinal: number;
      }
    | {
        op: "rename";
        section_id: string;
        title: string;
      }
    | {
        op: "set_type";
        section_id: string;
        node_type: "chapter" | "appendix";
      }
    | {
        op: "delete";
        section_id: string;
      }
    | {
        op: "restore";
        section_id: string;
        parent:
          | {
              section_id: string;
            }
          | {
              client_key: string;
            }
          | null;
        ordinal: number;
        include_descendants?: boolean;
      }
    | {
        op: "copy";
        section_id: string;
        parent:
          | {
              section_id: string;
            }
          | {
              client_key: string;
            }
          | null;
        ordinal: number;
        client_key?: string;
      }
  )[];
};

export type AuthoringStructurePreview = {
  action_id: string;
  base_draft_revision: number;
  created_ids: { [key: string]: string };
  plan_suggestions: {
    [key: string]: {
      template_version_id: string;
      template_key: string;
      goal: string;
      planned_pages: number | null;
    };
  };
  before: AuthoringTreeNode[];
  after: AuthoringTreeNode[];
  before_sections: { [key: string]: AuthoringJsonValue };
  after_sections: { [key: string]: AuthoringJsonValue };
  directory_template_version_id: string;
  style_template_version_id: string;
  deletion_impact: {
    section_id: string;
    title: string;
    text_characters: number;
    rule_ids: string[];
    source_count: number;
    plan_version_id: string | null;
  }[];
  format_report: AuthoringJsonValue;
  expires_in_seconds: number;
};

export type AuthoringStructureResult =
  | {
      draft_id: string;
      draft_revision: number;
      snapshot_id: string;
      snapshot_digest: string;
      action_id: string;
      state: "applied";
    }
  | {
      action_id: string;
      state: "rejected";
    };

export type AuthoringStructureHistory = {
  items: {
    id: string;
    draft_revision: number;
    snapshot_id: string;
    digest: string;
    created_by: string;
    created_at: string;
  }[];
  next_cursor: number | null;
};

export type AuthoringStructureRestorePreview = {
  base_draft_revision: number;
  structure_version_id: string;
};

export type AuthoringPlanSave = {
  base_draft_revision: number;
  base_plan_revision: number;
  state: "not_started" | "drafting" | "needs_basis" | "ready";
  goal: string;
  key_points: string[];
  rule_ids: string[];
  source_refs: {
    source_id: string;
    source_revision: number;
    evidence_id: string;
    document_version_id: string;
  }[];
  pending_facts: string[];
  planned_pages: number | null;
  budget_basis: "manual" | "requirement" | "template";
  budget_rule_id: string | null;
  budget_note: string;
};

export type AuthoringPlanSaved = {
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  plan: AuthoringPlanVersion;
};

export type AuthoringTemplateCatalog = {
  items: AuthoringTemplateVersionView[];
  next_cursor: string | null;
  coverage: "partial";
  notice: string;
};

export type AuthoringTemplateVersionView = {
  id: string;
  family_id: string;
  revision: number;
  name: string;
  kind: "outline" | "layout";
  config:
    | {
        schema_version: 1;
        nodes: {
          key: string;
          parent_key: string | null;
          ordinal: number;
          title: string;
          node_type: "chapter" | "appendix";
          goal?: string;
          planned_pages?: number | null;
        }[];
      }
    | {
        schema_version: 1;
        page: "A4";
        font: "Noto Sans CJK SC" | "Noto Serif CJK SC";
        font_size_halfpoints: number;
        margin_top_twips: number;
        margin_right_twips: number;
        margin_bottom_twips: number;
        margin_left_twips: number;
        paragraph_after_twips: number;
        cover_enabled: boolean;
        cover_title: string;
        header_text: string;
        footer_text: string;
        page_number: boolean;
        chapter_numbering: "decimal" | "none";
        toc_enabled: boolean;
      };
  config_digest: string;
  schema_digest: string;
  previous_version_id: string | null;
  created_by: string;
  created_at: string;
  immutable: true;
  is_builtin: boolean;
};

export type AuthoringDirectoryApplyPreview = {
  base_draft_revision: number;
  directory_template_version_id: string;
  matches: {
    template_key: string;
    section_id: string;
  }[];
  delete_section_ids: string[];
};

export type AuthoringStyleApplyPreview = {
  base_draft_revision: number;
  style_template_version_id: string;
  format_bindings: (
    | {
        rule_id: string;
        field: "font";
        value: "Noto Sans CJK SC" | "Noto Serif CJK SC";
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "font_size_halfpoints";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "margin_top_twips";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "margin_right_twips";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "margin_bottom_twips";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "margin_left_twips";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "paragraph_after_twips";
        value: number;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "cover_enabled";
        value: boolean;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "cover_title";
        value: string;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "header_text";
        value: string;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "footer_text";
        value: string;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "page_number";
        value: boolean;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "chapter_numbering";
        value: "decimal" | "none";
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
    | {
        rule_id: string;
        field: "toc_enabled";
        value: boolean;
        source_refs: {
          source_id: string;
          source_revision: number;
          evidence_id: string;
          document_version_id: string;
        }[];
        reason: string;
      }
  )[];
  format_review_ack: string | null;
};

export type AuthoringStylePreview =
  | {
      action_id: string;
      base_draft_revision: number;
      created_ids: { [key: string]: string };
      plan_suggestions: {
        [key: string]: {
          template_version_id: string;
          template_key: string;
          goal: string;
          planned_pages: number | null;
        };
      };
      before: AuthoringTreeNode[];
      after: AuthoringTreeNode[];
      before_sections: { [key: string]: AuthoringJsonValue };
      after_sections: { [key: string]: AuthoringJsonValue };
      directory_template_version_id: string;
      style_template_version_id: string;
      deletion_impact: {
        section_id: string;
        title: string;
        text_characters: number;
        rule_ids: string[];
        source_count: number;
        plan_version_id: string | null;
      }[];
      format_report: AuthoringJsonValue;
      expires_in_seconds: number;
    }
  | {
      action_id: null;
      state: "requires_format_review";
      format_report: AuthoringJsonValue;
    };

export type WorkConversationView = {
  id: string;
  bid_id: string;
  state: "active" | "closed" | "hidden";
  revision: number;
  created_at: string;
  scope: "project";
  is_main: boolean;
  title: string;
  stream_id: string | null;
};

export type WorkConversationStateRequest = {
  state: "active" | "closed" | "hidden";
};

export type WorkMessageRequest = {
  client_message_id: string;
  text: string;
  source_version_ids: string[];
};

export type WorkMessageView = {
  id: string;
  bid_id: string;
  conversation_id: string;
  client_message_id: string | null;
  role: "user" | "assistant" | "tool";
  parts: (
    | {
        type: "text";
        text: string;
      }
    | {
        type: "source_reference";
        document_version_id: string;
        source_bid_id: string;
      }
    | AssistantAnswerPart
  )[];
  created_by: string;
  created_at: string;
  recorded: true;
  assistant_operation_id: string | null;
  formal_scoring_input: false;
  assistant_job_id?: string;
  assistant_operation_scope?: "project" | "global";
};

export type WorkMessagePage = {
  items: WorkMessageView[];
  has_more: boolean;
  before: string | null;
};

export type AssistantTurnRequest = {
  client_message_id: string;
  text: string;
  source_selection: {
    kind: "project" | "document" | "section" | "knowledge_unit";
    id: string;
    version: string;
    trace_id: string | null;
    physical_page?: number;
  }[];
  section_id?: string | null;
  max_tokens?: number;
  request_mode?: "new_question" | "retry" | "continue";
  related_job_id?: string | null;
  related_action_id?: string | null;
  target?:
    | {
        kind: "general";
        id: null;
      }
    | {
        kind: "project" | "finding" | "rule" | "section";
        id: string;
      }
    | null;
  intent_purpose?:
    | "general_reference"
    | "project_reference"
    | "finding_explanation"
    | "rule_explanation"
    | "section_reference"
    | "section_draft";
};

export type AssistantJob = {
  id: string;
  kind: "answer" | "authoring";
  scope: "project" | "global";
  bid_id: string | null;
  conversation_id: string | null;
  user_message_id: string | null;
  operation: AssistantExecution;
  cancel_requested: boolean;
  cancellation_terminal: boolean;
  model_call: {
    id: string;
    state: "reserved" | "succeeded" | "failed" | "unknown";
    billing_state: string | null;
  } | null;
  requires_billing_reconciliation: boolean;
  publication: {
    state: "published" | "stale" | "failed";
    project_message_id: string | null;
    global_message_id: string | null;
    action_id: string | null;
    error_code: string | null;
  } | null;
  candidate:
    | {
        answer: string;
        citations: {
          source_key: string;
          quote: string;
        }[];
        issue_suggestions: {
          statement: string;
          severity: "critical" | "major" | "minor" | "info";
          source_keys: string[];
          needs_basis: boolean;
        }[];
        tool_proposals: (
          | {
              tool: "review.request";
              target_bid_id: string;
              arguments: Record<string, never>;
            }
          | {
              tool: "authoring.generate";
              target_bid_id: string;
              arguments: {
                section_id: string;
                instruction: string;
              };
            }
          | {
              tool: "knowledge.candidate";
              target_bid_id: string;
              arguments: {
                title: string;
                content: string;
                scope: string;
                source_version_ids: string[];
              };
            }
        )[];
        gaps: string[];
      }
    | {
        node_id: string;
        before_digest: string;
        replacement: AuthoringNode;
        evidence_ids: string[];
      }
    | {
        node_id: string;
        before_digest: string;
        replacement_text: string;
        evidence_ids: string[];
        protocol: "package-authoring-candidate/1";
        input: {
          id: string;
          digest: string;
          context_digest: string;
        };
      }
    | null;
  formal_scoring_input: false;
  automatic_retry_authorized: false;
  logical_intent: AssistantLogicalIntent | null;
  budget: AssistantBudgetReservation | null;
};

export type AssistantJobPage = {
  items: AssistantJob[];
};

export type AssistantGlobalConversation = {
  id: string;
  bid_id: null;
  scope: "global";
  title: string;
  is_main: true;
  state: "active" | "closed" | "hidden";
  revision: number;
  stream_id: string;
  last_event_seq: number;
  created_at: string;
};

export type AssistantGlobalMessagePage = {
  items: AssistantGlobalMessage[];
  has_more: boolean;
  before: string | null;
};

export type AssistantGlobalEventPage = {
  stream_id: string;
  items: {
    seq: number;
    event_id: string;
    event_type: string;
    payload: { [key: string]: unknown };
    created_at: string;
  }[];
  next_cursor: number;
  head_cursor: number;
};

export type AssistantSourcePage = {
  items: {
    reference: AssistantSourceRef | null;
    title: string;
    available: boolean;
    reasons: string[];
    bid_id: string | null;
    formal_scoring_input: false;
  }[];
  coverage: "partial";
  notice: string;
};

export type AssistantAction = {
  action_id: string;
  job_id: string;
  target_bid_id: string;
  tool:
    | "review.request"
    | "authoring.generate"
    | "authoring.apply_patch"
    | "knowledge.candidate";
  state: "pending" | "executed" | "rejected" | "expired" | "stale" | "failed";
  revision: number;
  request_digest: string;
  base_revision: number;
  expires_at: string;
  preview:
    | {
        kind: "request_review";
        body_version_id: string;
        material_revision: number;
        effect: string;
      }
    | {
        kind: "generate_proposal";
        section_id: string;
        base_section_revision: number;
        instruction: string;
        effect: string;
      }
    | {
        kind: "knowledge_candidate";
        title: string;
        content: string;
        scope: string;
        source_version_ids: string[];
        effect: string;
      }
    | {
        kind: "authoring_patch";
        section_id: string;
        base_section_revision: number;
        before: AuthoringDocument;
        after: AuthoringDocument;
        effect: string;
      }
    | {
        kind: "package_authoring_patch";
        section_id: string;
        base_section_revision: number;
        before: AuthoringDocument;
        after: AuthoringDocument;
        authoring_input_id: string;
        authoring_input_digest: string;
        source_scope: "exact_package_context";
        apply_available: boolean;
        build_available: false;
        effect: string;
      };
  result:
    | {
        assistant_resolution: {
          action_id: string;
          state: "executed" | "rejected" | "expired" | "stale" | "failed";
          tool:
            | "review.request"
            | "authoring.generate"
            | "authoring.apply_patch"
            | "knowledge.candidate";
          target_bid_id: string;
          domain_result:
            | (
                | AssistantJob
                | KnowledgeView
                | DraftSaved
                | {
                    resource_id: string;
                    resource_kind: "pending_intent";
                    operation: Operation;
                    disposition: "created" | "pending_latest";
                    operation_url: string;
                  }
              )
            | null;
          error_code: string | null;
          http_status: number;
          business_effect_executed: boolean;
        };
      }
    | DraftSaved
    | null;
  resolved_by: string | null;
  error_code: string | null;
  formal_scoring_input: false;
};

export type AssistantActionResolveRequest = {
  decision: "confirm" | "reject";
};

export type AssistantSourceRef = {
  kind: "project" | "document" | "section" | "knowledge_unit";
  id: string;
  version: string;
  trace_id: string | null;
  physical_page?: number;
};

export type AssistantAnswerPart = {
  type: "assistant_reference_answer";
  job_id: string;
  citations: {
    source_key: string;
    quote: string;
    position: AssistantCitationPosition;
  }[];
  issue_suggestions: {
    statement: string;
    severity: "critical" | "major" | "minor" | "info";
    source_keys: string[];
    needs_basis: boolean;
    suggestion_id: string;
    record_kind: "assistant_suggestion";
    official_finding_id: null;
    resolved: false;
  }[];
  action_ids: string[];
  rejected_proposals: {
    tool:
      | "review.request"
      | "authoring.generate"
      | "authoring.apply_patch"
      | "knowledge.candidate";
    target_bid_id: string;
    error_code: string;
  }[];
  gaps: string[];
  formal_scoring_input: false;
  all_actions_require_explicit_button: true;
};

export type TemplateRequest = {
  name: string;
  task_kind:
    | "denial_check"
    | "scoring_review"
    | "supplement_impact"
    | "chapter_suggestion";
  instructions: string;
  section_id?: string | null;
  source_selection?:
    | SourceSelection
    | ExactPackageReviewSelection
    | ExactPackageTriggerSelection
    | ExactPackageAuthoringSelection;
  trigger?: Trigger;
};

export type ExactPackageTriggerSelection = {
  mode: "exact_package_trigger";
  input: PackageReviewSelection;
};

export type PackageTaskTriggerCapabilities = {
  available: boolean;
  reason: string | null;
  input_mode: "exact_package_trigger";
  triggers: ("material_updated" | "schedule")[];
  requires_independent_runner: true;
  automatic_input_selection: false;
  automatic_catchup_runs: 0;
};

export type PackageTriggerIntentView = {
  id: string;
  bid_id: string;
  definition_id: string;
  definition_version_id: string;
  trigger: "material_updated" | "schedule";
  trigger_event_id: string | null;
  scheduled_at: string | null;
  created_at: string;
  selection: PackageReviewSelection;
  input_digest: string;
  state: "pending" | "accepted" | "blocked" | "cancelled";
  error_code: string | null;
  run_id: string | null;
  run_ref: string | null;
  reused: boolean;
  automatic_input_selection: false;
};

export type PackageTriggerIntentPage = {
  items: PackageTriggerIntentView[];
  next_after: string | null;
};

export type TemplateView = {
  id: string;
  bid_id: string;
  revision: number;
  version_id: string;
  digest: string;
  purpose: "assist" | "compliance";
  paused: boolean;
  configuration: TemplateRequest;
  next_run_at: string | null;
  run_created: false;
  active_runs_cancelled: false;
};

export type TemplatePage = {
  items: TemplateView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type TemplateVersionView = {
  id: string;
  bid_id: string;
  definition_id: string;
  revision: number;
  instructions: string;
  config: TemplateSnapshotConfig;
  digest: string;
};

export type RunRequest = {
  rerun?: boolean;
};

export type TaskAuthoringResult = {
  schema: "task-authoring-result/1";
  job_id: string;
  job_input_digest: string;
  writing_plan_id: string;
  operation_id: string;
  job_ref: string;
  section_id: string;
  base_section_revision: number;
  publication_state: "pending" | "published" | "stale" | "failed";
  candidate_digest: string | null;
  action_id: string | null;
  action_ref: string | null;
  source_scope: "legacy_section_and_source_versions";
  automatic_apply: false;
};

export type RunView = {
  id: string;
  bid_id: string;
  definition_version_id: string;
  root_operation_id: string;
  final_operation_id: string | null;
  state:
    | "queued"
    | "running"
    | "cancel_requested"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "awaiting_review"
    | "awaiting_publication"
    | "blocked"
    | "superseded"
    | "unknown"
    | "reconciliation_required";
  stage: "preparation" | "review" | "execution";
  frozen_manifest: { [key: string]: unknown };
  result:
    | TaskAuthoringResult
    | TaskPackageAuthoringResult
    | { [key: string]: unknown }
    | null;
  error_code: string | null;
  formal_decisions_created: false;
  coverage: "registered_effectivity_only_semantic_unknown" | "not_formal_score";
};

export type RunPage = {
  items: RunView[];
  next_after: string | null;
};

export type PauseRequest = {
  paused: boolean;
};

export type TaskKindPage = {
  items: TaskKindView[];
  default_trigger: "manual";
  saving_preset_creates_run: false;
};

export type TaskNotificationPage = {
  items: TaskNotification[];
  next_after: string | null;
};

export type TaskScheduleRecoveryPage = {
  items: TaskScheduleRecovery[];
  next_after: string | null;
  run_current_once_supported: true;
};

export type TaskDraftRequest = {
  request: string;
  section_id?: string | null;
  source_selection?:
    | SourceSelection
    | ExactPackageReviewSelection
    | ExactPackageTriggerSelection
    | ExactPackageAuthoringSelection;
};

export type TaskDraftView = {
  id: string;
  bid_id: string;
  created_by: string;
  revision: number;
  created_at: string;
  updated_at: string;
  interpretation: TaskDraftInterpretation;
  configuration_digest: string;
  explicitly_edited: boolean;
  saved_template_id?: string | null;
};

export type TaskDraftPage = {
  items: TaskDraftView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type KnowledgeRetrievalRequest = {
  query: string;
  purpose: "assist" | "authoring" | "compliance" | "history";
  limit: number;
  knowledge_ids?: string[];
};

export type KnowledgeRetrievalResult = {
  trace_id: string;
  profile_id: string;
  policy_digest: string;
  coverage: "partial" | "unavailable";
  hits: KnowledgeRetrievalHit[];
  gaps: string[];
  route: string[];
};

export type KnowledgeRetrievalHistory = {
  retrieval: KnowledgeRetrievalResult;
  evaluated_at: string;
  current_reasons: string[];
  historical_bytes_preserved: true;
};

export type KnowledgeUnitReferenceRequest = {
  unit_id: string;
  quote: string;
  target_kind: "project" | "section" | "operation" | "review";
  target_object_id: string;
  applicability_reason: string;
};

export type KnowledgeUnitReference = {
  citation_id: string;
  trace_id: string;
  bid_id: string;
  unit_id: string;
  unit_kind: "knowledge_text" | "original_quote";
  knowledge_version_id: string;
  quote: string;
  unit_text: string;
  unit_span_start: number;
  unit_span_end: number;
  target_kind: "project" | "section" | "operation" | "review";
  target_object_id: string;
  applicability_reason: string;
  provenance: KnowledgeDerivedProvenance | KnowledgeQuoteProvenance;
  project_context: KnowledgeProjectContext;
  reference_only: true;
  project_fact_created: false;
};

export type KnowledgeUnitReferenceHistory = {
  reference: KnowledgeUnitReference;
  current_reasons: string[];
  historical_bytes_preserved: true;
};

export type KnowledgeIndexRequest = {
  knowledge_version_id: string;
};

export type KnowledgeIndexAccepted = {
  index_id: string;
  operation: {
    id: string;
    bid_id: string;
    kind: "index-knowledge";
    state:
      | "queued"
      | "running"
      | "cancel_requested"
      | "succeeded"
      | "failed"
      | "cancelled";
    input_digest: string;
    handler_version: "knowledge-index/1";
    result_ref: string | null;
  };
};

export type KnowledgeIndexPage = {
  items: {
    index_id: string;
    knowledge_version_id: string;
    profile_id: string;
    operation_id: string;
    state: "queued" | "ready" | "failed" | "superseded";
    expected_unit_count: number | null;
    published_unit_count: number;
    unit_manifest_digest: string | null;
    current_ready: boolean;
    desired: boolean;
    error_code: string | null;
  }[];
};

export type BusinessResultRequest = {
  submission_id: string;
  stage:
    | "pending"
    | "technical_shortlisted"
    | "not_shortlisted"
    | "rejected"
    | "candidate"
    | "awarded"
    | "not_awarded"
    | "cancelled"
    | "failed_tender";
  source_type: "user_reported" | "official";
  source_version_id: string | null;
  evidence_refs: {
    document_version_id: string;
    evidence_id: string;
    physical_page: number;
    quote: string;
  }[];
  announced_at: string | null;
  known_at: string;
  reason: string;
};

export type BusinessResultCorrectionRequest = {
  submission_id: string;
  stage:
    | "pending"
    | "technical_shortlisted"
    | "not_shortlisted"
    | "rejected"
    | "candidate"
    | "awarded"
    | "not_awarded"
    | "cancelled"
    | "failed_tender";
  source_type: "user_reported" | "official";
  source_version_id: string | null;
  evidence_refs: {
    document_version_id: string;
    evidence_id: string;
    physical_page: number;
    quote: string;
  }[];
  announced_at: string | null;
  known_at: string;
  reason: string;
  base_result_id: string;
  correction_reason: string;
};

export type BusinessResultVerificationRequest = {
  state: "pending" | "verified" | "conflict" | "rejected";
  reason: string;
  identity_confirmed?: boolean;
  evidence_refs?: {
    document_version_id: string;
    evidence_id: string;
    physical_page: number;
    quote: string;
  }[];
};

export type BusinessResultView = {
  submission_id: string;
  stage:
    | "pending"
    | "technical_shortlisted"
    | "not_shortlisted"
    | "rejected"
    | "candidate"
    | "awarded"
    | "not_awarded"
    | "cancelled"
    | "failed_tender";
  source_type: "user_reported" | "official";
  source_version_id: string | null;
  evidence_refs: {
    document_version_id: string;
    evidence_id: string;
    physical_page: number;
    quote: string;
  }[];
  announced_at: string | null;
  known_at: string;
  reason: string;
  id: string;
  bid_id: string;
  supersedes_id: string | null;
  correction_reason: string | null;
  created_by: string;
  created_at: string;
  verification: "pending" | "verified" | "conflict" | "rejected";
  verification_authority_id: string | null;
  verification_details: {
    state: "pending" | "verified" | "conflict" | "rejected";
    reason: string;
    identity_confirmed?: boolean;
    evidence_refs?: {
      document_version_id: string;
      evidence_id: string;
      physical_page: number;
      quote: string;
    }[];
  } | null;
  head_revision: number;
  head_authority_id: string | null;
  current: boolean;
  usable: boolean;
  unusable_reasons: string[];
};

export type BusinessResultPage = {
  bid_id: string;
  submission_id: string;
  current_result: {
    submission_id: string;
    stage:
      | "pending"
      | "technical_shortlisted"
      | "not_shortlisted"
      | "rejected"
      | "candidate"
      | "awarded"
      | "not_awarded"
      | "cancelled"
      | "failed_tender";
    source_type: "user_reported" | "official";
    source_version_id: string | null;
    evidence_refs: {
      document_version_id: string;
      evidence_id: string;
      physical_page: number;
      quote: string;
    }[];
    announced_at: string | null;
    known_at: string;
    reason: string;
    id: string;
    bid_id: string;
    supersedes_id: string | null;
    correction_reason: string | null;
    created_by: string;
    created_at: string;
    verification: "pending" | "verified" | "conflict" | "rejected";
    verification_authority_id: string | null;
    verification_details: {
      state: "pending" | "verified" | "conflict" | "rejected";
      reason: string;
      identity_confirmed?: boolean;
      evidence_refs?: {
        document_version_id: string;
        evidence_id: string;
        physical_page: number;
        quote: string;
      }[];
    } | null;
    head_revision: number;
    head_authority_id: string | null;
    current: boolean;
    usable: boolean;
    unusable_reasons: string[];
  } | null;
  head_revision: number;
  head_authority_id: string | null;
  items: {
    submission_id: string;
    stage:
      | "pending"
      | "technical_shortlisted"
      | "not_shortlisted"
      | "rejected"
      | "candidate"
      | "awarded"
      | "not_awarded"
      | "cancelled"
      | "failed_tender";
    source_type: "user_reported" | "official";
    source_version_id: string | null;
    evidence_refs: {
      document_version_id: string;
      evidence_id: string;
      physical_page: number;
      quote: string;
    }[];
    announced_at: string | null;
    known_at: string;
    reason: string;
    id: string;
    bid_id: string;
    supersedes_id: string | null;
    correction_reason: string | null;
    created_by: string;
    created_at: string;
    verification: "pending" | "verified" | "conflict" | "rejected";
    verification_authority_id: string | null;
    verification_details: {
      state: "pending" | "verified" | "conflict" | "rejected";
      reason: string;
      identity_confirmed?: boolean;
      evidence_refs?: {
        document_version_id: string;
        evidence_id: string;
        physical_page: number;
        quote: string;
      }[];
    } | null;
    head_revision: number;
    head_authority_id: string | null;
    current: boolean;
    usable: boolean;
    unusable_reasons: string[];
  }[];
  next_offset: number | null;
  total: number;
};

export type BusinessMetricsView = {
  scope: {
    period_from: string | null;
    period_to: string | null;
    as_of: string;
    bid_ids: string[] | null;
    statistical_unit: "engineering_lot_round_bidder_current_actual_submission";
    verification_scope: "ledger" | "verified_only";
    definition: "fr011-ledger/v1";
    observed_current_heads: number;
    effective_head_digest: string;
    head_authorities: {
      bid_id: string;
      submission_id: string;
      submission_revision: number;
      result_head: {
        result_id: string | null;
        revision: number;
        authority_id: string | null;
      };
      result_usable: boolean | null;
      result_exclusions: string[];
    }[];
    excluded_submission_counts: { [key: string]: number };
    identity_submission_conflicts: {
      unit: string[];
      submission_ids: string[];
    }[];
    scope_note: string;
  };
  effective_submissions: number;
  known_outcomes: number;
  unknown_outcomes: number;
  conflicted_outcomes: number;
  unusable_outcomes: number;
  stage_counts: { [key: string]: number };
  verification_counts: { [key: string]: number };
  excluded_result_counts: { [key: string]: number };
  shortlist_rate: {
    numerator: number;
    denominator: number;
    value: string | null;
  };
  win_rate: {
    numerator: number;
    denominator: number;
    value: string | null;
  };
  qualification: {
    identified: number | null;
    resolved: number | null;
    dismissed: number | null;
    open: number | null;
    open_at_submission: number | null;
    known_snapshot_submissions: number;
    unknown_snapshot_submissions: number;
    official_rejections: number;
    known_current_review_submissions: number;
    unknown_current_review_submissions: number;
    scope_note: string;
    official_rejection_causality: "not_inferred";
  };
  online_error: {
    prediction_pairs: number;
    needed_pairs: 20;
    online_error_state: "no_pairs" | "insufficient" | "sufficient";
    mae: string | null;
    bias: string | null;
    excluded_pair_counts: { [key: string]: number };
    scope_note: string;
  };
  model_qualification_granted: false;
};

export type UploadBatchPage = {
  items: UploadBatchView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type GateView = {
  allowed: boolean;
  bid_revision: number;
  body_version_id: string | null;
  blockers: {
    code: string;
    object_id: string;
    message: string;
  }[];
  review_id: string | null;
  material_revision: number;
  current_identity_digest: string;
  current_review_manifest_digest: string | null;
  pending_core_rule_ids: string[];
  blocking_finding_ids: string[];
  warnings: string[];
};

export type SubmissionRequest = {
  body_version_id: string;
  review_id: string;
  material_revision: number;
  submitted_at: string;
  evidence_ref: string;
};

export type OfflineSubmissionRequest = {
  actual_document_version_id: string;
  submitted_at: string;
  evidence_ref: string;
  explanation: string;
};

export type SubmissionView = SingleBodySubmissionView | PackageSubmissionView;

export type SingleBodySubmissionView = {
  id: string;
  bid_id: string;
  body_version_id: string;
  review_id: string | null;
  kind: "standard" | "offline_fact";
  submitted_at: string;
  recorded_by: string;
  gate_checked: boolean;
  evidence_ref: string | null;
  current: boolean;
  supersedes_id: string | null;
  identity:
    | (
        | {
            bidder_id: string;
            bidder_name: string;
            round_id: string;
            engineering_project_id: string;
            engineering_title: string;
            region: string | null;
            engineering_type: string | null;
            lot: string | null;
            round_no: number;
            binding_status: "confirmed" | "pending";
            authority_id: string | null;
            digest: string;
            identity_version?: "bid-identity/1";
          }
        | {
            bidder_id: string;
            bidder_name: string;
            round_id: string;
            engineering_project_id: string;
            engineering_title: string;
            region: string | null;
            engineering_type: string | null;
            lot: string | null;
            lot_id: string | null;
            round_no: number;
            binding_status: "confirmed" | "pending";
            authority_id: string | null;
            digest: string;
            identity_version: "bid-identity/2";
          }
      )
    | null;
  original_name: string;
  artifact_kind: string;
  checks_label: string;
  open_risk_snapshot: SubmissionRiskSnapshot | null;
  platform_submission_verified: false;
  explanation: string | null;
  correction_reason: string | null;
  subject_kind?: "single_body";
};

export type PackageSubmissionSelection = {
  package_id: string;
  revision_id: string;
  package_digest: string;
  inventory: {
    id: string;
    digest: string;
  } | null;
  coverage: {
    id: string;
    digest: string;
  } | null;
  review_run: {
    id: string;
    input_digest: string;
    result_digest: string | null;
  } | null;
};

export type PackageSubmissionRequest = {
  kind: "standard" | "offline_fact";
  selection: {
    package_id: string;
    revision_id: string;
    package_digest: string;
    inventory: {
      id: string;
      digest: string;
    } | null;
    coverage: {
      id: string;
      digest: string;
    } | null;
    review_run: {
      id: string;
      input_digest: string;
      result_digest: string | null;
    } | null;
  };
  input_digest: string;
  evidence: {
    document_version_id: string;
    digest: string;
    byte_size: number;
  };
  submitted_at: string;
  explanation: string;
  expected_head: {
    id: string;
    revision: number;
  } | null;
  correction_reason: string | null;
};

export type PackageSubmissionPreview = {
  selection: {
    target: BidPackageStoredView;
    authority: BidPackageStoredView | null;
    inventory: PackageRequirementInventoryView | null;
    coverage: PackageCoverageAttemptView | null;
  };
  selection_request: {
    package_id: string;
    revision_id: string;
    package_digest: string;
    inventory: {
      id: string;
      digest: string;
    } | null;
    coverage: {
      id: string;
      digest: string;
    } | null;
    review_run: {
      id: string;
      input_digest: string;
      result_digest: string | null;
    } | null;
  };
  gate: PackageSubmissionGateView;
  input_digest: string;
  bid_etag: string;
  current_submission_head: {
    id: string;
    revision: number;
    subject_kind: "single_body" | "bid_package";
  } | null;
};

export type PackageSubmissionBindingView = {
  manifest: {
    version: "package-submission-binding/1";
    submission_id: string;
    bid_id: string;
    subject: {
      kind: "bid_package";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
    };
    selection: {
      target: BidPackageStoredView;
      authority: BidPackageStoredView | null;
      inventory: PackageRequirementInventoryView | null;
      coverage: PackageCoverageAttemptView | null;
    };
    selection_request: {
      package_id: string;
      revision_id: string;
      package_digest: string;
      inventory: {
        id: string;
        digest: string;
      } | null;
      coverage: {
        id: string;
        digest: string;
      } | null;
      review_run: {
        id: string;
        input_digest: string;
        result_digest: string | null;
      } | null;
    };
    package_identity: HistoricalBidIdentitySnapshot;
    recorded_identity: BidIdentitySnapshot;
    submitted_at: string;
    recorded_at: string;
    assessed_at: string;
    actor_id: string;
    command_id: string;
    request: {
      kind: "standard" | "offline_fact";
      selection: {
        package_id: string;
        revision_id: string;
        package_digest: string;
        inventory: {
          id: string;
          digest: string;
        } | null;
        coverage: {
          id: string;
          digest: string;
        } | null;
        review_run: {
          id: string;
          input_digest: string;
          result_digest: string | null;
        } | null;
      };
      input_digest: string;
      evidence: {
        document_version_id: string;
        digest: string;
        byte_size: number;
      };
      submitted_at: string;
      explanation: string;
      expected_head: {
        id: string;
        revision: number;
      } | null;
      correction_reason: string | null;
    };
    request_digest: string;
    if_match: string;
    input_digest: string;
    context: { [key: string]: unknown };
    review_run: PackageReviewRunView | null;
    inventory_proof: { [key: string]: unknown } | null;
    gate: PackageSubmissionGateView;
    originals: {
      document_version_id: string;
      digest: string;
      byte_size: number;
      media_type: string;
      artifact_kind: string;
      original_name: string;
      roles: (
        | "target"
        | "authority"
        | "submission_attachment"
        | "source_ancestor"
      )[];
    }[];
    evidence: {
      document_version_id: string;
      digest: string;
      byte_size: number;
      media_type: string;
      artifact_kind: string;
      original_name: string;
      roles: (
        | "target"
        | "authority"
        | "submission_attachment"
        | "source_ancestor"
      )[];
    };
    attachment_sources: { [key: string]: unknown }[];
    supersedes_id: string | null;
    head_revision: number;
    platform_submission_verified: false;
    pre_submission_system_check_verified: false;
    original_bytes_verified: true;
  };
  digest: string;
};

export type PackageSubmissionView = {
  id: string;
  bid_id: string;
  subject_kind: "bid_package";
  body_version_id: null;
  review_id: null;
  kind: "standard" | "offline_fact";
  submitted_at: string;
  recorded_at: string;
  recorded_by: string;
  gate_checked: boolean;
  evidence_ref: string;
  current: boolean;
  supersedes_id: string | null;
  identity: HistoricalBidIdentitySnapshot;
  original_name: null;
  artifact_kind: null;
  checks_label: string;
  open_risk_snapshot: { [key: string]: unknown };
  platform_submission_verified: false;
  explanation: string;
  correction_reason: string | null;
  package_binding: PackageSubmissionBindingView;
};

export type PackageSubmissionAppliedView = {
  submission: {
    id: string;
    bid_id: string;
    subject_kind: "bid_package";
    body_version_id: null;
    review_id: null;
    kind: "standard" | "offline_fact";
    submitted_at: string;
    recorded_at: string;
    recorded_by: string;
    gate_checked: boolean;
    evidence_ref: string;
    current: boolean;
    supersedes_id: string | null;
    identity: HistoricalBidIdentitySnapshot;
    original_name: null;
    artifact_kind: null;
    checks_label: string;
    open_risk_snapshot: { [key: string]: unknown };
    platform_submission_verified: false;
    explanation: string;
    correction_reason: string | null;
    package_binding: PackageSubmissionBindingView;
  };
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request: {
      kind: "standard" | "offline_fact";
      selection: {
        package_id: string;
        revision_id: string;
        package_digest: string;
        inventory: {
          id: string;
          digest: string;
        } | null;
        coverage: {
          id: string;
          digest: string;
        } | null;
        review_run: {
          id: string;
          input_digest: string;
          result_digest: string | null;
        } | null;
      };
      input_digest: string;
      evidence: {
        document_version_id: string;
        digest: string;
        byte_size: number;
      };
      submitted_at: string;
      explanation: string;
      expected_head: {
        id: string;
        revision: number;
      } | null;
      correction_reason: string | null;
    };
    if_match: string;
  };
};

export type PackageSubmissionGateView = PackageSubmissionGate_View;

export type PackageOutcomeContext = {
  subject_kind: "bid_package";
  bid_id: string;
  submission_id: string;
  body_version_id: null;
  identity: {
    project_id: string;
    lot_id: string | null;
    round_id: string;
    bidder_id: string;
    package_id: string;
    revision_id: string;
    package_digest: string;
    binding_digest: string;
    identity_digest: string;
  };
  package_identity: HistoricalBidIdentitySnapshot;
  recorded_identity: BidIdentitySnapshot;
  package_binding: PackageSubmissionBindingView;
  authority: {
    package_id: string;
    revision_id: string;
    digest: string;
    identity_digest: string;
  } | null;
  display: {
    project_title: string;
    lot: string | null;
    round_no: number;
    bidder_name: string;
    body_filename: null;
  };
  submitted_at: string;
  kind: "standard" | "offline_fact";
  source_candidates: {
    id: string;
    original_name: string;
    obtained_at: string;
  }[];
  identity_ready: boolean;
  identity_status: "confirmed" | "unavailable" | "changed";
  identity_reason: string | null;
  verification_blockers: string[];
  verification_requires_source_evidence: true;
  formal_sample_eligible: false;
  formal_sample_blockers: "package_formal_sample_not_supported"[];
};

export type PackageOutcomeVerificationRequest = {
  version: "package-outcome-verification/1";
  subject_kind: "bid_package";
  state: "pending" | "verified" | "conflict" | "rejected";
  reason: string;
  identity: {
    project_id: string;
    lot_id: string | null;
    round_id: string;
    bidder_id: string;
    package_id: string;
    revision_id: string;
    package_digest: string;
    binding_digest: string;
    identity_digest: string;
  };
  authority: {
    package_id: string;
    revision_id: string;
    digest: string;
    identity_digest: string;
  } | null;
  aggregation: string;
  published_at: string | null;
  evidence_refs: {
    document_version_id: string;
    evidence_id: string;
    physical_page: number;
    quote: string;
  }[];
};

export type PackageOutcomeVerificationDetails = {
  version: "package-outcome-verification-record/1";
  subject_kind: "bid_package";
  request: {
    version: "package-outcome-verification/1";
    subject_kind: "bid_package";
    state: "pending" | "verified" | "conflict" | "rejected";
    reason: string;
    identity: {
      project_id: string;
      lot_id: string | null;
      round_id: string;
      bidder_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      binding_digest: string;
      identity_digest: string;
    };
    authority: {
      package_id: string;
      revision_id: string;
      digest: string;
      identity_digest: string;
    } | null;
    aggregation: string;
    published_at: string | null;
    evidence_refs: {
      document_version_id: string;
      evidence_id: string;
      physical_page: number;
      quote: string;
    }[];
  };
  package_identity: HistoricalBidIdentitySnapshot;
  binding_digest: string;
  checked_at: string;
  authority_proof: {
    digest: string;
    snapshot: { [key: string]: unknown };
  } | null;
  official_source_proof: {
    digest: string;
    snapshot: { [key: string]: unknown };
  } | null;
  verification_scope: "official_outcome_association";
  formal_sample_eligible: false;
  formal_sample_blockers: "package_formal_sample_not_supported"[];
};

export type OutcomeRequest = {
  submission_id: string;
  score_kind: "technical_total" | "comprehensive_total" | "unknown";
  value: string | null;
  maximum: string | null;
  source_version_id: string;
  known_at: string;
};

export type SubmissionPage = {
  items: SubmissionView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type SubmissionDocumentPage = {
  items: SubmissionDocumentView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type SubmissionCorrectionRequest =
  | {
      kind: "standard";
      submission: SubmissionRequest;
      reason: string;
    }
  | {
      kind: "offline_fact";
      submission: OfflineSubmissionRequest;
      reason: string;
    };

export type ReportContextView = {
  review_id: string;
  body_version_id: string;
  original_name: string;
  presentation_revision: number;
  source_impact_revision: number;
  context_digest: string;
  current: boolean;
  source_state: string;
  supported: {
    artifact_kind: "review_report" | "annotated_review_copy";
    format: "docx" | "pdf";
  }[];
};

export type ReportRequest = {
  artifact_kind: "review_report" | "annotated_review_copy";
  format: "docx" | "pdf";
  presentation_revision: number;
  source_impact_revision: number;
};

export type ReportExportPage = {
  items: ReportExportView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type ReportExportView = {
  id: string;
  review_id: string;
  operation_id: string;
  state:
    | "queued"
    | "running"
    | "cancel_requested"
    | "succeeded"
    | "failed"
    | "cancelled";
  artifact_kind: "review_report" | "annotated_review_copy";
  format: "docx" | "pdf";
  presentation_revision: number;
  source_impact_revision: number;
  document_version_id: string | null;
  gaps: string[];
  error_code: string | null;
};

export type PricingContext = {
  bid_id: string;
  material_snapshot_id: string | null;
  material_revision: number;
  scope: {
    bid_id: string;
    round_id: string;
    effective_documents: {
      role: "tender" | "supplement";
      document_version_id: string;
      digest: string;
    }[];
  };
  parses: {
    id: string;
    document_version_id: string;
  }[];
  source_heads: {
    id: string;
    digest: string;
    revision: number | null;
    status: string | null;
    valid_from: string | null;
    valid_until: string | null;
  }[];
};

export type PricingFormulaSourcePage = {
  items: {
    source_id: string;
    source_revision: number | null;
    document_version_id: string;
    parse_id: string;
    physical_page: number;
    evidence_id: string;
    filename: string;
    quote: string;
    source_registered: boolean;
  }[];
  next_cursor: string | null;
};

export type PricingRegisterFormula = {
  title: string;
  formula: PricingFormulaParameters;
  amount_unit: "元" | "万元";
  currency: "CNY" | null;
  rounding_policy: "half_up_2dp" | "half_even_2dp";
  interpretation: PricingInterpretation;
  terms_complete_confirmed: true;
  matches_source_confirmed: true;
  evidence_quotes: PricingEvidenceQuote[];
  reason: string;
};

export type PricingFormulaPage = {
  items: {
    formula_version_id: string;
    formula_digest: string;
    title: string;
    method: string;
    maximum: string;
    amount_unit: string;
    currency: string | null;
    rounding_policy: string;
    confirmed_at: string;
    confirmed_by: string;
    current_applicability: PricingApplicability;
    package_binding?: PricingPackagePricingBinding;
  }[];
  next_cursor: string | null;
};

export type PricingFormulaView = {
  formula_version_id: string;
  formula_digest: string;
  formula: PricingFormulaManifest;
  current_applicability: PricingApplicability;
};

export type PricingRequest = {
  formula_version_id: string;
  candidate_price: string;
  competitor_price_assumptions: string[];
  rounding_policy: "half_up_2dp" | "half_even_2dp";
  candidate_prices: string[];
  curve_range: PricingCurveRange | null;
  amount_unit: "元" | "万元";
  currency: "CNY" | null;
};

export type PricingSimulationView = {
  id: string;
  formula_version_id: string;
  formula_digest: string;
  input_digest: string;
  formula_evidence_ids: string[];
  price_score: string | null;
  eligible: boolean;
  notes: string[];
  candidate_price: string;
  maximum: string;
  baseline_price: string | null;
  valid_price_count: number;
  candidates: PricePoint[];
  curve: PricePoint[];
  calculation_steps: string[];
  assumptions: string[];
  technical_exchange_note: string;
  excluded_competitor_assumptions: {
    index: number;
    price: string;
    reason: string;
  }[];
  input: PricingRequest;
  formula_snapshot: PricingFormulaManifest;
  created_by: string;
  created_at: string;
  current_applicability: PricingApplicability;
};

export type PricingSavePlan = {
  simulation_id: string;
  reason: string;
};

export type PricingPlanView = {
  id: string;
  simulation_id: string;
  formula_version_id: string;
  formula_digest: string;
  input_digest: string;
  input: PricingRequest;
  formula_snapshot: PricingFormulaManifest;
  result: PricingFrozenResult;
  reason: string;
  created_by: string;
  created_at: string;
  current_applicability: PricingApplicability;
};

export type PricingPlanPage = {
  items: PricingPlanView[];
  next_cursor: string | null;
};

export type PricePoint = {
  price: string;
  score: string | null;
  eligible: boolean;
  notes: string[];
  baseline_price: string | null;
  valid_price_count: number;
  calculation_steps: string[];
};

export type UploadLayoutView = {
  upload_id: string;
  bid_id: string;
  mode: "single" | "multipart";
  part_size: number;
  part_count: number;
  byte_size: number;
  declared_sha256: string;
  revision: number;
  state:
    | "authorized"
    | "uploaded"
    | "verifying"
    | "verified"
    | "quarantined"
    | "expired"
    | "aborted";
  session_expires_at: string;
};

export type KnowledgeCandidate = {
  title: string;
  content: string;
  source_version_ids: string[];
  scope: string;
};

export type KnowledgeView = {
  id: string;
  version_id: string;
  revision: number;
  title: string;
  state: "candidate" | "published" | "withdrawn";
  content: string;
  categories: string[];
  source_ids: string[];
  source_impact: boolean;
  workflow:
    | "candidate"
    | "pending_confirmation"
    | "published"
    | "withdrawn"
    | "expired"
    | "superseded"
    | "source_invalid"
    | "not_yet_effective";
  version_no: number;
  knowledge_source_id: string;
  source_revision: number;
  published_version_id: string | null;
  published_workflow:
    | null
    | "candidate"
    | "pending_confirmation"
    | "published"
    | "withdrawn"
    | "expired"
    | "superseded"
    | "source_invalid"
    | "not_yet_effective";
  scope: string;
  applicability: KnowledgeApplicability | null;
  source_refs: KnowledgeSourcePosition[];
  provenance: {
    source_ref: KnowledgeSourcePosition;
    bid_id: string;
    original_name: string;
    digest: string;
    byte_size: number;
    bidder_id: string;
    original_project_title: string;
    original_bidder: string;
  }[];
  declared_source_version_ids: string[];
  created_by: string;
  created_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  reference_notice: string;
};

export type KnowledgePage = {
  items: KnowledgeView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type KnowledgeVersionRequest = {
  title: string;
  content: string;
  categories: (
    | "company_fact"
    | "method"
    | "standard"
    | "retrospective"
    | "chapter_reference"
  )[];
  scope: string;
  applicability: KnowledgeApplicability;
  source_refs: KnowledgeSourcePosition[];
};

export type KnowledgeVersionPage = {
  items: KnowledgeView[];
  next_cursor: number | null;
  has_more: boolean;
};

export type KnowledgeReferenceRequest = {
  bid_id: string;
  version_id: string;
  purpose: "assist" | "authoring" | "compliance" | "history";
  target_kind:
    | "project"
    | "section"
    | "operation"
    | "review"
    | "package_review_run";
  target_object_id: string;
  excerpt: string;
  applicability_reason: string;
};

export type KnowledgeReferenceHistory = {
  reference: KnowledgeReference;
  version_content: string;
  current_applicability_reasons: string[];
  historical_bytes_preserved: true;
};

export type KnowledgeImpact = {
  knowledge_id: string;
  version_id: string;
  workflow: string;
  groups: {
    working: {
      citation_id: string;
      bid_id: string;
      target_object_id: string;
      purpose: string;
      created_at: string;
      phase: string;
      archived_at: string | null;
      title: string;
    }[];
    submitted: {
      citation_id: string;
      bid_id: string;
      target_object_id: string;
      purpose: string;
      created_at: string;
      phase: string;
      archived_at: string | null;
      title: string;
    }[];
    archived: {
      citation_id: string;
      bid_id: string;
      target_object_id: string;
      purpose: string;
      created_at: string;
      phase: string;
      archived_at: string | null;
      title: string;
    }[];
    closed: {
      citation_id: string;
      bid_id: string;
      target_object_id: string;
      purpose: string;
      created_at: string;
      phase: string;
      archived_at: string | null;
      title: string;
    }[];
  };
  registered_research_model_derivations: {
    id: string;
    kind: string;
    digest: string;
  }[];
  requires_review: boolean;
  unknown_ranges: string[];
  historical_reports_rewritten: false;
};

export type KnowledgeSourcePositions = {
  items: {
    reference: KnowledgeSourcePosition;
    excerpt_truncated: boolean;
  }[];
  parse_id: string | null;
  physical_page: number;
  page_count: number;
  next_ordinal: number | null;
  has_more: boolean;
  readiness: "not_ready" | "readable_text_positions_only";
};

export type BiddingCompanyPage = {
  items: {
    id: string;
    name: string;
    registered: boolean;
    registration_id: string | null;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type DefaultBiddingCompanyView = {
  bidder: {
    id: string;
    name: string;
    registered: boolean;
    registration_id: string | null;
  } | null;
  authority_id: string | null;
};

export type EngineeringIdentityPage = {
  items: {
    id: string;
    title: string;
    region: string | null;
    engineering_type: string | null;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type EngineeringRoundPage = {
  items: {
    id: string;
    engineering_project_id: string;
    lot: string | null;
    lot_id: string | null;
    round_no: number;
    engineering_title: string;
    region: string | null;
    engineering_type: string | null;
  }[];
  has_more: boolean;
  next_cursor: string | null;
};

export type BidIdentityView = {
  identity: {
    bidder_id: string;
    bidder_name: string;
    round_id: string;
    engineering_project_id: string;
    engineering_title: string;
    region: string | null;
    engineering_type: string | null;
    lot: string | null;
    lot_id: string | null;
    round_no: number;
    binding_status: "confirmed" | "pending";
    authority_id: string | null;
    digest: string;
    identity_version: "bid-identity/2";
  };
  affected: {
    reviews: number;
    submissions: number;
    outcomes: number;
    samples: number;
    drafts: number;
    documents: number;
    facts: number;
    knowledge_citations: number;
  };
};

export type BidIdentityCorrection = {
  identity: {
    bidder_id: string;
    bidder_name: string;
    round_id: string;
    engineering_project_id: string;
    engineering_title: string;
    region: string | null;
    engineering_type: string | null;
    lot: string | null;
    lot_id: string | null;
    round_no: number;
    binding_status: "confirmed" | "pending";
    authority_id: string | null;
    digest: string;
    identity_version: "bid-identity/2";
  };
  affected: {
    reviews: number;
    submissions: number;
    outcomes: number;
    samples: number;
    drafts: number;
    documents: number;
    facts: number;
    knowledge_citations: number;
  };
  historical_records_rewritten: false;
  qualification_recheck_required: true;
};

export type CorrectBidIdentity = {
  bidder_id: string;
  round_id?: string;
  lot_id?: string;
  reason: string;
};

export type RegisterBidder = {
  name: string;
  reason: string;
  set_as_default?: boolean;
};

export type RegisteredBiddingCompanyView = {
  bidder: {
    id: string;
    name: string;
    registered: boolean;
    registration_id: string | null;
  };
  default: {
    bidder: {
      id: string;
      name: string;
      registered: boolean;
      registration_id: string | null;
    } | null;
    authority_id: string | null;
  };
  qualification_verified: false;
};

export type SelectDefaultBidder = {
  bidder_id: string;
};

export type ResearchCapabilities = {
  historical_outcomes: boolean;
  official_zero_is_valid: boolean;
  unknown_is_not_zero: boolean;
  batch_dry_run: boolean;
  price: {
    available: boolean;
    digest: string | null;
    currency: string | null;
  };
  formal_prediction: {
    mode: "unavailable";
    reasons: string[];
  };
  model_training: "awaiting_verified_real_labels";
  model_release: "unavailable";
  requires_full_chapters: true;
  judgments_per_item: 3;
  source_authority_configured: boolean;
};

export type ResearchHistoryPage = {
  items: {
    id: string;
    title: string;
    created_at: string;
    submission_count: number;
    outcome_count: number;
    admitted_samples: number;
  }[];
  next_offset: number | null;
  read_only: true;
};

export type ResearchOutcomePage = {
  items: ResearchOutcomeView[];
  heads: {
    submission_id: string;
    bid_id: string;
    outcome_id: string;
    revision: number;
  }[];
};

export type ResearchOutcomeDetail = {
  id: string;
  bid_id: string;
  submission_id: string;
  score_kind: "technical_total" | "comprehensive_total" | "unknown";
  value: string | null;
  maximum: string | null;
  verification: "pending" | "verified" | "conflict" | "rejected";
  source_version_id: string;
  known_at: string;
  verification_revision: number;
  supersedes_id: string | null;
  verification_details:
    | SingleBodyOutcomeVerification
    | PackageOutcomeVerificationDetails
    | null;
  current: boolean;
  package_association?: {
    available: boolean;
    reasons: string[];
    checked_at: string;
    scope: "official_outcome_association";
    formal_sample_eligible: false;
  };
};

export type ResearchSamplePage = {
  items: ResearchListedSample[];
  next_offset: number | null;
  formal_model_eligible: false;
};

export type ResearchGroupingView = {
  sample_id: string;
  source_group_id: string;
  revision: number;
  metadata: {
    template_key: string | null;
    near_duplicate_key: string | null;
    reviewed: boolean;
    reason: string;
  };
  related_sample_ids: string[];
  eligible_label_pair: boolean;
};

export type ResearchGroupingRequest = {
  template_key: string | null;
  near_duplicate_key: string | null;
  reviewed: boolean;
  reason: string;
};

export type AuthoringDocument = {
  type: "doc";
  attrs: {
    title: string;
    ordinal: number;
    rule_ids: string[];
    source_refs: AuthoringSourceReference[];
  };
  content: AuthoringBlock[];
};

export type AuthoringNode =
  | AuthoringBreak
  | AuthoringText
  | AuthoringParagraph
  | AuthoringHeading
  | AuthoringBulletList
  | AuthoringOrderedList
  | AuthoringListItem;

export type AuthoringCapabilities = {
  schema_digest: string;
  schema: {
    version: number;
    nodes: string[];
    marks: string[];
    metadata: string[];
  };
  default_template_version_id: string;
  formats: ("docx" | "pdf")[];
  supports_external_docx_import: boolean;
  supported_nodes: string[];
  unsupported: string[];
};

export type AuthoringDraftPage = {
  items: {
    id: string;
    revision: number;
    title: string;
    snapshot_id: string;
  }[];
  next_cursor: string | null;
};

export type AuthoringRevisionPage = {
  items: {
    revision: number;
    created_at: string;
    digest: string;
    created_by: string;
  }[];
  next_cursor: number | null;
};

export type AuthoringPreviewRequest = {
  base_section_revision: number;
  node_id: string;
  before_digest: string;
  replacement: AuthoringNode;
  source_refs: AuthoringSourceReference[];
};

export type AuthoringPreview = {
  action_id: string;
  base_draft_revision: number;
  before: AuthoringDocument | AuthoringRichDocument;
  after: AuthoringDocument | AuthoringRichDocument;
  expires_in_seconds: number;
};

export type AuthoringSnapshot = {
  snapshot_id: string;
  snapshot_digest: string;
  title: string;
  sections: (AuthoringDocument | AuthoringRichDocument)[];
  authoring_exact_sections?: AuthoringExactSnapshotExtension;
  authoring_structure?: AuthoringStructureExtension;
  authoring_images?: AuthoringJsonValue;
};

export type AuthoringSectionAdded = {
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  section_id: string;
};

export type EvidenceAuthoringReferenceView = {
  evidence_id: string;
  bid_id: string;
  parse_run_id: string;
  document_version_id: string;
  physical_page: number;
  authoring_reference: AuthoringSourceReference | null;
  reasons: string[];
};

export type CreateDraftRequest = {
  title: string;
  outline_template_version_id: string | null;
};

export type DraftView = {
  id: string;
  bid_id: string;
  revision: number;
  snapshot_id: string;
  sections: SectionSummary[];
};

export type SectionView = {
  id: string;
  draft_id: string;
  revision: number;
  schema_digest: string;
  content: AuthoringDocument | AuthoringRichDocument;
  writing_plan_id: string | null;
};

export type SaveDraft = {
  base_draft_revision: number;
  changes: SectionChange[];
};

export type DraftSaved = {
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
};

export type BuildRequest =
  | (
      | {
          draft_id: string;
          draft_revision: number;
          template_version_id: string;
          formats: ("docx" | "pdf")[];
          follow_up: "none" | "review";
        }
      | AuthoringStructuredBuildRequest
    )
  | AuthoringRichBuildRequest;

export type BuildView = {
  id: string;
  draft_snapshot_id: string;
  operation_id: string;
  outputs: {
    format: "docx" | "pdf";
    state: "pending" | "succeeded" | "failed";
    document_version_id: string | null;
    gaps: string[];
  }[];
  identity: AuthoringBuildIdentity;
  follow_up: BuildFollowUpView;
  layout?: AuthoringBuildLayout | null;
};

export type BuildPage = {
  items: BuildView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type BatchRuleConfirmation = {
  base_rule_set_id: string;
  rule_ids: string[];
  reason: string;
};

export type RuleDecisionRequest = {
  decision: "confirmed" | "rejected" | "deferred";
  reason: string;
  evidence_ids: string[];
};

export type FactDecisionRequest = {
  decision: "confirmed" | "rejected";
  reason: string;
  evidence_ids: string[];
};

export type FindingDecisionRequest = {
  decision: "confirm" | "dismiss" | "defer" | "reopen";
  reason: string;
  evidence_ids: string[];
};

export type RestoreAuthoringSection = {
  revision: number;
  base_draft_revision: number;
  base_section_revision: number;
};

export type RetrievalRequest = {
  query: string;
  context: "assistant" | "authoring" | "body_evidence" | "history";
  bid_id: string | null;
  limit: number;
};

export type RetrievalResult = {
  trace_id: string;
  policy_digest: string;
  hits: RetrievalHit[];
  coverage: "available" | "partial" | "unavailable";
  gaps: string[];
};

export type RetrievalHit = {
  chunk_id: string;
  source_version_id: string;
  parse_run_id: string;
  physical_page: number;
  citation_id: string;
  excerpt: string;
  embedding_profile_id: string;
  rank: number;
};

export type ReviewStateView = {
  bid_id: string;
  revision: number;
  current_body_id: string | null;
  material_revision: number;
  current_material_snapshot_id: string | null;
  current_rule_set_id: string | null;
  request: ReviewIntentView | null;
  current_review: ReviewView | null;
};

export type ReviewPage = {
  items: ReviewView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type ReviewManifest = {
  bid_id: string;
  body_version_id: string;
  material_snapshot_id: string;
  material_revision: number;
  rule_set_id: string;
  fact_set_id: string | null;
  parse_run_ids: string[];
  method_digest: string;
  policy_digest: string;
  purpose: "compliance_and_scoring";
  source_refs: SourceRef[];
  content_checks: {
    consistency: boolean;
    scope_residue: boolean;
  };
  frozen_at: string;
  as_of: string;
  evaluation_context_digest: string;
  evidence_manifest_digest: string;
};

export type ReviewView = {
  id: string;
  bid_id: string;
  operation_id: string;
  input_digest: string;
  core_coverage: "pending" | "complete" | "partial" | "failed";
  risk_count: number | null;
  current: boolean;
  prediction: PredictionView;
  next_action: NextAction;
  source_impact_revision: number;
  manifest_digest: string;
  coverage_layers: ReviewCoverage;
};

export type RuleSetView = {
  id: string;
  bid_id: string;
  material_revision: number;
  coverage: "complete" | "partial" | "conflict";
  rules: RuleView[];
  revision: number;
};

export type FactSetView = {
  id: string | null;
  bid_id: string;
  facts: FactView[];
  revision: number;
};

export type FindingPage = {
  items: FindingView[];
  next_cursor: string | null;
  has_more: boolean;
};

export type MatrixView = {
  review_id: string;
  coverage: "pending" | "complete" | "partial" | "failed";
  rows: MatrixRow[];
  coverage_layers: ReviewCoverage;
};

export type SettingsView = {
  bid_id: string;
  revision: number;
  settings: ProjectSettings;
};

export type DecisionRequest = {
  decision: string;
  reason: string;
  evidence_ids: string[];
};

export type BatchRuleConfirmationRequest = {
  items: RuleConfirmationItem[];
};

export type BatchRuleConfirmationView = {
  rule_set_id: string;
  revision: number;
  items: RuleConfirmationResult[];
};

export type FactChangeRequest = {
  fact: FactInput;
  replaces_fact_id: string | null;
};

export type Cancellation = {
  reason: string;
  cancel_pending_same_input: boolean;
};

export type DiagnosticPage = {
  items: ValidationDiagnostic[];
  next_cursor: string | null;
};

export type ReviewRequest = {
  body_version_id: string;
  material_revision: number;
  trigger: "manual" | "automatic" | "build_follow_up";
  rerun_nonce?: string | null;
};

export type RuleSetCorrectionRequest = {
  base_rule_set_id: string;
  reason: string;
  additions: RuleAddition[];
};

export type DocumentEvidenceView = {
  document_version_id: string;
  parse_run_id: string | null;
  coverage: "pending" | "complete" | "partial" | "failed";
  gaps: string[];
  items: EvidenceView[];
};

export type DownloadGrant = {
  artifact_id: string;
  download_url: string;
  expires_at: string;
  filename: string;
  artifact_kind: string;
  presentation_revision: number | null;
};

export type EvidenceView = {
  id: string;
  document_version_id: string;
  parse_run_id: string;
  physical_page: number;
  printed_label: string | null;
  kind: "text" | "table" | "visual_observation";
  quote: string;
  bbox: number[] | null;
  page_width: number;
  page_height: number;
  rotation: 0 | 90 | 180 | 270;
  source_status: "published" | "withdrawn" | "candidate";
};

export type AuthView = {
  member: MemberView;
  csrf_token: string;
  expires_at: string;
};

export type Bid = {
  id: string;
  title: string;
  revision: number;
  material_revision: number;
  presentation_revision: number;
  phase: "preparation" | "working" | "submitted" | "closed" | "terminated";
  archived_at: string | null;
  current_body_id: string | null;
  current_review_id: string | null;
  stream_id: string;
  next_action: NextAction;
  identity: BidIdentitySnapshot;
};

export type BidPage = {
  items: Bid[];
  next_cursor: string | null;
  has_more: boolean;
};

export type CreateBid = {
  title: string;
  engineering_project_id?: string;
  round_id?: string;
  bidder_id?: string;
  lot?: string;
  region?: string;
  engineering_type?: string;
  deadline?: string | null;
  lot_id?: string;
};

export type UploadGrant = {
  upload_id: string;
  object_ref: string;
  file_id: string;
  mode: "single" | "multipart";
  upload_url: string | null;
  part_size: number;
  part_count: number;
  parts: UploadPartGrant[];
  expires_at: string;
  session_expires_at: string;
  revision: number;
};

export type UploadPartsView = {
  upload_id: string;
  revision: number;
  mode: "single" | "multipart";
  completed_parts: UploadPartReceipt[];
  session_expires_at: string;
};

export type RefreshUploadRequest = {
  part_numbers: number[];
};

export type UploadRequest = {
  batch_id: string;
  role:
    | "tender"
    | "supplement"
    | "drawing"
    | "boq"
    | "body"
    | "official_result"
    | "other";
  filename: string;
  byte_size: number;
  declared_sha256: string;
  target: UploadTarget;
  declared_source_document_version_id?: string | null;
};

export type UploadView = {
  id: string;
  bid_id: string;
  batch_id: string;
  filename: string;
  state:
    | "authorized"
    | "uploaded"
    | "verifying"
    | "verified"
    | "quarantined"
    | "expired"
    | "aborted";
  document_version_id: string | null;
  error_code: string | null;
  file_id: string;
  revision: number;
  session_expires_at: string;
  binding_id: string;
  verified_retain_until: string | null;
  word_pdf_declaration?: WordPdfDeclarationView | null;
};

export type UploadBatchView = {
  id: string;
  bid_id: string;
  revision: number;
  state: "open" | "verifying" | "committed" | "failed";
  uploads: UploadView[];
};

export type UploadBindingView = {
  id: string;
  upload_id: string;
  bid_id: string;
  file_id: string;
  expected_file_revision: number;
  previous_binding_id: string | null;
  upload_revision: number;
  verified_retain_until: string;
};

export type UploadBindingRequest = {
  target: UploadTarget;
  reason: string;
};

export type BatchCommit = {
  accepted_upload_ids: string[];
  explicit_partial_acceptance: boolean;
  accepted_binding_ids: string[];
};

export type MaterialView = {
  bid_id: string;
  material_revision: number;
  snapshot_id: string | null;
  documents: DocumentView[];
  conflicts: string[];
};

export type DocumentView = {
  id: string;
  bid_id: string;
  filename: string;
  role:
    | "tender"
    | "supplement"
    | "drawing"
    | "boq"
    | "body"
    | "official_result"
    | "other";
  artifact_kind:
    | "bid_body"
    | "review_report"
    | "annotated_review_copy"
    | "source_original"
    | "research_artifact";
  sha256: string;
  byte_size: number;
  media_type: string;
  obtained_at: string;
  parse_coverage: "pending" | "complete" | "partial" | "failed";
  file_id: string;
  file_revision: number;
  previous_version_id: string | null;
  file_head_revision: number;
  file_head_version_id: string;
  source_relation: DocumentRelation | null;
};

export type Accepted = {
  resource_id: string;
  operation: Operation;
  disposition: "created" | "reused" | "pending_latest";
  resource_kind:
    | "review"
    | "build"
    | "proposal"
    | "upload"
    | "import"
    | "task"
    | "message"
    | "report"
    | "pending_intent"
    | "action"
    | "comparison"
    | "experiment"
    | "index"
    | "ingestion";
  operation_url: string;
};

export type Operation = {
  id: string;
  bid_id: string;
  kind: string;
  state:
    | "queued"
    | "running"
    | "cancel_requested"
    | "succeeded"
    | "failed"
    | "cancelled";
  input_digest: string;
  handler_version: string;
  result_ref: string | null;
};

export type UploadComplete = {
  parts: UploadPartReceipt[];
  declared_sha256: string;
};

export type UploadTarget =
  | {
      kind: "new_file";
    }
  | {
      kind: "new_version";
      file_id: string;
      expected_file_revision: number;
    };

export type PackageHistorySelection = {
  admission_id: string;
  purpose: "fit" | "development" | "calibration" | "final";
};

export type AuthoringHistoryAuthoringRichDocument = {
  type: "doc";
  attrs: {
    title: string;
    ordinal: number;
    rule_ids: string[];
    source_refs: AuthoringHistoryAuthoringSourceReference[];
  };
  content: (
    | AuthoringHistoryAuthoringBlock
    | AuthoringHistoryAuthoringRichTable
    | AuthoringHistoryAuthoringRichImage
  )[];
};

export type AuthoringExactRevisionManifest = {
  protocol: "authoring-exact-revision/1";
  id: string;
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  section_id: string;
  section_revision_id: string;
  section_revision: number;
  section_digest: string;
  schema_digest: string;
  parent_section_revision_id: string;
  parent_section_revision: number;
  parent_section_digest: string;
  input: AuthoringExactInputIdentity;
  origin: AuthoringExactRevisionOrigin;
  source_scope: "exact_package_context";
  source_refs_digest: string;
  rule_ids_digest: string;
  method: AuthoringExactRevisionMethod;
  method_digest: string;
  candidate_adopted: true;
  content_correctness_certified: false;
};

export type AuthoringExactManualRevisionManifest = {
  protocol: "authoring-exact-manual-revision/1";
  id: string;
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  section_id: string;
  section_revision_id: string;
  section_revision: number;
  section_digest: string;
  schema_digest: string;
  parent_section_revision_id: string;
  parent_section_revision: number;
  parent_section_digest: string;
  input: AuthoringExactInputIdentity;
  origin: AuthoringExactTextEditOrigin;
  source_scope: "exact_package_context";
  source_refs_digest: string;
  rule_ids_digest: string;
  method: AuthoringExactTextEditMethod;
  method_digest: string;
  candidate_adopted: false;
  content_correctness_certified: false;
};

export type PackageContext = {
  target: PackageReference;
  authority: PackageReference;
  inventory: InventoryReference;
};

export type SectionSelection = {
  draft_id: string;
  snapshot_id: string;
  snapshot_digest: string;
  base_draft_revision: number;
  section_id: string;
  section_revision_id: string;
  base_section_revision: number;
  section_digest: string;
  schema_digest: string;
  node_id: string;
  before_node_digest: string;
};

export type FactSelection = {
  fact_set_id: string;
  fact_head_revision: number;
  identity_fact_ids: string[];
  uses: FactUse[];
};

export type WorkContextReadOnlyAuthoringRichDocument = {
  type: "doc";
  attrs: {
    title: string;
    ordinal: number;
    rule_ids: string[];
    source_refs: WorkContextReadOnlyAuthoringSourceReference[];
  };
  content: (
    | WorkContextReadOnlyAuthoringBlock
    | WorkContextReadOnlyAuthoringRichTable
    | WorkContextReadOnlyAuthoringRichImage
  )[];
};

export type WorkContextSelection =
  | {
      kind: "package_review_run";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      inventory_id: string;
      inventory_digest: string;
      frozen_input_id: string;
      frozen_input_digest: string;
      execution_input_id: string;
      execution_input_digest: string;
      dependency_plan_id: string;
      dependency_plan_digest: string;
      run_id: string;
      input_digest: string;
      method_digest: string;
      result_digest: string | null;
    }
  | {
      kind: "package_submission";
      bid_id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      submission_id: string;
      package_binding_digest: string;
      inventory: {
        id: string;
        digest: string;
      } | null;
      review_run: {
        kind: "package_review_run";
        bid_id: string;
        package_id: string;
        revision_id: string;
        package_digest: string;
        inventory_id: string;
        inventory_digest: string;
        frozen_input_id: string;
        frozen_input_digest: string;
        execution_input_id: string;
        execution_input_digest: string;
        dependency_plan_id: string;
        dependency_plan_digest: string;
        run_id: string;
        input_digest: string;
        method_digest: string;
        result_digest: string | null;
      } | null;
    };

export type WorkContextDimensionObservation = {
  status: "matched" | "changed" | "unknown" | "not_applicable";
  selected_digest: string | null;
  observed_digest: string | null;
  reason: string;
};

export type WorkContextSummary = {
  perspective: "declared_scope_history" | "submission_history";
  review_status:
    | "result_available"
    | "run_unfinished"
    | "bound_result_missing"
    | "not_selected";
  review: WorkContextReviewSummary | null;
  whole_package_blocking_risk_count: null;
  whole_package_passed: null;
  formal_scoring: {
    status: "scope_not_selected";
    scope_id: null;
    numeric_prediction: null;
  };
  official_labels_read: false;
  primary_action:
    | "open_selected_review"
    | "view_selected_operation"
    | "inspect_changed_basis"
    | "open_selected_submission";
  action_mode: "navigation_only";
};

export type WorkContextNativeTargets = {
  package_revision: {
    kind: "package_revision";
    bid_id: string;
    package_id: string;
    revision_id: string;
    package_digest: string;
  };
  authority_revision: {
    kind: "package_revision";
    bid_id: string;
    package_id: string;
    revision_id: string;
    package_digest: string;
  } | null;
  package_review_run: {
    kind: "package_review_run";
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
    frozen_input_id: string;
    execution_input_id: string;
    run_id: string;
    input_digest: string;
    result_digest: string | null;
  } | null;
  package_submission: {
    kind: "package_submission";
    bid_id: string;
    submission_id: string;
    package_binding_digest: string;
  } | null;
};

export type PricingFormulaParameters = {
  method: "lowest_valid_ratio" | "mean_valid_deviation";
  maximum: string;
  minimum_price: string | null;
  maximum_price: string | null;
  minimum_valid_bids: number;
  above_coefficient: string;
  below_coefficient: string;
};

export type PricingInterpretation = {
  baseline_set: "own_and_all_numerically_eligible_assumptions";
  exclusions: "none";
  random_parameters: "none";
  intermediate_rounding: "none";
  clamping: "zero_to_maximum";
};

export type PricingEvidenceQuote = {
  source_id: string;
  source_revision: number;
  document_version_id: string;
  parse_id: string;
  physical_page: number;
  evidence_id: string;
  quote: string;
  supported_fields: string[];
};

export type HistoricalImportRecord = {
  external_record_id: string;
  bid_id: string;
  actual_document_version_id: string;
  submitted_at: string;
  evidence_ref: string;
  explanation: string;
  score_kind: "technical_total" | "comprehensive_total" | "unknown";
  value: string | null;
  maximum: string | null;
  source_version_id: string | null;
  known_at: string | null;
};

export type PackageRuleCorrection_RuleAddition = {
  kind: "disqualification" | "mandatory" | "scoring" | "advisory";
  statement: string;
  conditions: string[];
  exceptions: string[];
  scope: PackageRuleCorrection_RuleScope;
  maximum: string | null;
  bands: PackageRuleCorrection_RuleBand[];
  evidence_quotes: PackageRuleCorrection_RuleEvidenceQuote[];
};

export type PackageRuleCorrection_RuleEvidenceQuote = {
  evidence_id: string;
  quote: string;
};

export type PackageRuleCorrection_RuleBand = {
  label: string;
  description: string;
  points: string;
  evidence_ids: string[];
};

export type AuthoringGenerationJson =
  | null
  | boolean
  | number
  | string
  | AuthoringGenerationJson[]
  | { [key: string]: AuthoringGenerationJson };

export type AuthoringWordImportJson =
  | null
  | boolean
  | number
  | string
  | AuthoringWordImportJson[]
  | { [key: string]: AuthoringWordImportJson };

export type PackageReviewHumanDecisionSummary = {
  id: string;
  digest: string;
  sequence_no: number;
  actor_id: string;
  created_at: string;
  state: "confirmed" | "rejected" | "needs_review";
  reason: string;
};

export type PackageScopeReview_Digest = string;

export type PackageScopeReview_Input = {
  version: "package-scope-review-input/1";
  purpose: "prebid_compliance";
  scope: PackageScopeReview_Scope;
  frozen_input: {
    id: PackageScopeReview_Id;
    digest: PackageScopeReview_Digest;
    input_digest: PackageScopeReview_Digest;
    evidence_digest: PackageScopeReview_Digest;
  };
  execution_input: {
    id: PackageScopeReview_Id;
    digest: PackageScopeReview_Digest;
    identity: PackageScopeReview_Identity;
  };
  dependency_plan: {
    id: PackageScopeReview_Id;
    digest: PackageScopeReview_Digest;
  };
  usage_digest: PackageScopeReview_Digest;
  selected_facts_digest: PackageScopeReview_Digest;
  fact_admission: {
    content_digest: PackageScopeReview_Digest;
    proofs_digest: PackageScopeReview_Digest;
    policy_digest: PackageScopeReview_Digest;
    fact_declarations: {
      fact_id: PackageScopeReview_Id;
      declaration_id: PackageScopeReview_Id;
      declaration_digest: PackageScopeReview_Digest;
    }[];
  };
  inventory_proof_digest: PackageScopeReview_Digest;
  executor_method: {
    profile: PackageScopeReview_MethodProfile;
    digest: PackageScopeReview_Digest;
  };
  model_input_digest: PackageScopeReview_Digest;
  limitations: "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"[];
};

export type PackageScopeReview_Quote = {
  member_id: string;
  evidence_id: PackageScopeReview_Id;
  quote: string;
  package_role: "target" | "authority";
  document_version_id: PackageScopeReview_Id;
  parse_run_id: PackageScopeReview_Id;
  physical_page: number;
  part_ids: string[];
  evidence_digest: PackageScopeReview_Digest;
};

export type AuthoringJsonValue =
  | null
  | boolean
  | number
  | string
  | AuthoringJsonValue[]
  | { [key: string]: AuthoringJsonValue };

export type AuthoringSourceReference = {
  source_id: string;
  source_revision: number;
  evidence_id: string;
  document_version_id: string;
};

export type AuthoringBlock =
  | AuthoringParagraph
  | AuthoringHeading
  | AuthoringBulletList
  | AuthoringOrderedList;

export type AuthoringRichTable = {
  type: "table";
  attrs: {
    id: string;
    column_widths_twips: number[];
    caption: string;
  };
  content: AuthoringRichRow[];
};

export type AuthoringRichImage = {
  type: "image";
  attrs: {
    id: string;
    asset_id: string;
    asset_revision: number;
    asset_version_id: string;
    width_twips: number;
    height_twips: number;
    alt: string;
    caption: string;
  };
};

export type PackageScopeReview_Result = {
  version: "package-scope-review-result/1";
  kind: "declared_package_scope_review";
  purpose: "prebid_compliance";
  run_id: PackageScopeReview_Id;
  bid_id: PackageScopeReview_Id;
  input_digest: PackageScopeReview_Digest;
  execution_input_id: PackageScopeReview_Id;
  execution_input_digest: PackageScopeReview_Digest;
  execution_digest: PackageScopeReview_Digest;
  dependency_plan_id: PackageScopeReview_Id;
  dependency_plan_digest: PackageScopeReview_Digest;
  method_digest: PackageScopeReview_Digest;
  scope: PackageScopeReview_Scope;
  submitted_documents: PackageScopeReview_SubmittedDocument[];
  requirement_count: number;
  matrix_coverage: "complete" | "partial";
  overall_coverage: "partial";
  quality_status: "not_measured";
  inventory_complete: false;
  formal_scoring_eligible: false;
  submission_eligible: false;
  limitations: string[];
  counts: {
    satisfied: number;
    violated: number;
    not_found: number;
    unable_to_judge: number;
    not_applicable: number;
  };
  matrix: PackageScopeReview_MatrixRow[];
};

export type PackageDependencyPlan_Save = {
  execution_input_digest: PackageDependencyPlan_Assessment_Digest;
  purpose: "prebid_compliance";
  fact_ids: PackageDependencyPlan_Assessment_Id[];
  dependencies: PackageDependencyPlan_Assessment_Dependency[];
  assessment_digest: PackageDependencyPlan_Assessment_Digest;
  reason: string;
};

export type PackageDependencyPlan_View = {
  manifest: PackageDependencyPlan_Manifest;
  digest: PackageDependencyPlan_Assessment_Digest;
};

export type PackageDependencyPlan_Assessment_Prepared = {
  bid_id: PackageDependencyPlan_Assessment_Id;
  package_id: PackageDependencyPlan_Assessment_Id;
  revision_id: PackageDependencyPlan_Assessment_Id;
  inventory_id: PackageDependencyPlan_Assessment_Id;
  frozen_input_id: PackageDependencyPlan_Assessment_Id;
  execution_input_id: PackageDependencyPlan_Assessment_Id;
  execution_input_digest: PackageDependencyPlan_Assessment_Digest;
};

export type PackageDependencyPlanSummary = {
  id: string;
  digest: string;
  actor_id: string;
  saved_at: string;
  reason: string;
  assessment_digest: string;
  required_facts_assessment:
    | "unknown"
    | "missing"
    | "selected_unvalidated"
    | "not_used";
  dependency_review_status: "incomplete" | "declared";
  selected_fact_count: number;
  requirement_count: number;
};

export type PackageInputDependencies_Dependency = {
  requirement_id: PackageInputDependencies_Id;
  requirement_digest: PackageInputDependencies_Digest;
  state: "unknown" | "not_needed" | "required";
  fact_ids: PackageInputDependencies_Id[];
  evidence_ids: PackageInputDependencies_Id[];
  reason: string;
};

export type PackageInputDependencies_View = {
  manifest: PackageInputDependencies_Manifest;
  digest: PackageInputDependencies_Digest;
};

export type PackageFactChange_ConfirmRequest = {
  frozen_digest: PackageFactChange_Digest;
  expected_head: PackageFactChange_Head;
  replaces_fact_id: PackageFactChange_Id | null;
  fact: PackageFactChange_Fact;
  confirmation: "confirmed";
};

export type PackageFactChange_WithdrawRequest = {
  frozen_digest: PackageFactChange_Digest;
  expected_head: PackageFactChange_Head;
  fact_id: PackageFactChange_Id;
  reason: string;
};

export type PackageFactChange_Record = {
  manifest: PackageFactChange_Manifest | PackageFactChange_ManifestV2;
  digest: PackageFactChange_Digest;
};

export type PackageCurrentFactSummary = {
  fact_id: string;
  fact_item_digest: string;
  name: string;
  subject: string;
  scope: string;
  value_preview: string;
  unit: string | null;
  preview_truncated: boolean;
  confirmation_recorded: "pending" | "confirmed" | "rejected";
  decision_id: string | null;
  frozen_evidence_status: "selected_parse" | "unproven";
};

export type PackageFactChange_Binding = {
  bid_id: PackageFactChange_Id;
  package_id: PackageFactChange_Id;
  revision_id: PackageFactChange_Id;
  inventory_id: PackageFactChange_Id;
  frozen_input_id: PackageFactChange_Id;
  frozen_digest: PackageFactChange_Digest;
};

export type PackageFactChange_Head = {
  id: PackageFactChange_Id | null;
  revision: number;
};

export type PackageFactSourcePackage = {
  role: "target" | "authority";
  package_id: string;
  revision_id: string;
  digest: string;
};

export type PackageEditableFact = {
  subject: string;
  scope: string;
  name: string;
  value: string | boolean | null;
  unit: string | null;
  evidence_ids: string[];
};

export type PackageFactEvidenceReference = {
  id: string;
  parse_id: string;
  document_version_id: string;
  physical_page: number;
  digest: string;
  frozen_parse_member: boolean;
};

export type PackagePreparedFactSummary = {
  fact_id: string;
  fact_item_digest: string;
  name: string;
  subject: string;
  scope: string;
  value_preview: string;
  unit: string | null;
  preview_truncated: boolean;
};

export type PackageFactScope_Change = {
  execution_input_digest: PackageFactScope_Digest;
  fact_id: PackageFactScope_Id;
  action: "bind" | "withdraw";
  subject: PackageFactScope_Subject | null;
  reason: string;
  previous_digest: PackageFactScope_Digest | null;
};

export type PackageFactScope_Record = {
  manifest: PackageFactScope_Manifest;
  digest: PackageFactScope_Digest;
};

export type PackageFactScope_Id = string;

export type PackageFactValidationItem = {
  fact_id: string;
  provenance_status: "verified" | "unproven";
  scope_binding: "unproven";
  facts_qualified: false;
  blockers: (
    | "FACT_DECISION_UNCONFIRMED"
    | "FACT_DECISION_BINDING_UNPROVEN"
    | "FACT_DECISION_BASIS_UNPROVEN"
    | "FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT"
    | "FACT_EVIDENCE_QUALITY_UNPROVEN"
    | "FACT_SOURCE_BINDING_UNPROVEN"
    | "FACT_SOURCE_NOT_EFFECTIVE"
    | "FACT_SCOPE_MAPPING_REQUIRED"
  )[];
};

export type PackageExecution_RerunIntent = {
  nonce: PackageExecution_Id;
  reason: string;
};

export type PackageExecutionInputManifest = {
  version: "package-review-execution-input/1";
  kind: "prepared_input";
  id: string;
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  frozen_input_id: string;
  actor_id: string;
  command_id: string;
  identity: PackageExecution_Identity;
  execution_context: PackageReviewExecutionContext;
  snapshot_digest: string;
  originals_verified_at: string;
  saved_at: string;
  blockers: (
    | "PROJECT_WORK_CLOSED"
    | "PACKAGE_BIDDER_UNCONFIRMED"
    | "PACKAGE_REVIEW_IDENTITY_STALE"
    | "PACKAGE_REVIEW_PACKAGE_STALE"
    | "PACKAGE_REVIEW_INVENTORY_STALE"
    | "PACKAGE_REVIEW_RULE_SET_STALE"
    | "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_CHANGED"
    | "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE"
    | "PACKAGE_REVIEW_MEMBERS_UNPROVEN"
    | "PACKAGE_REVIEW_EVIDENCE_CHANGED"
    | "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP"
    | "PACKAGE_REVIEW_EXTRACTION_UNPROVEN"
    | "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN"
    | "PACKAGE_REVIEW_EXECUTOR_NOT_READY"
    | "PACKAGE_REVIEW_METHOD_CHANGED"
    | "PACKAGE_REVIEW_POLICY_CHANGED"
    | "PACKAGE_REVIEW_FACTS_CHANGED"
    | "PACKAGE_REVIEW_FACTS_UNPROVEN"
  )[];
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type PackageReviewExecutionContext = {
  version: "package-review-context/1";
  kind: "candidate";
  input_digest: string;
  semantic_digest: string;
  snapshot_digest: string;
  method_digest: string;
  policy_digest: string;
  facts_digest: string;
  sources_digest: string;
  as_of: string;
  purpose: "prebid_compliance";
  fact_set_id: string | null;
  fact_count: number;
  confirmed_fact_count: number;
  facts_binding: "empty" | "unproven";
  executor_available: false;
  formal_scoring_eligible: false;
};

export type PackageReviewFrozenInputManifest = {
  version: "package-review-frozen-input/1";
  kind: "frozen_input";
  id: string;
  bid_id: string;
  package_id: string;
  revision_id: string;
  inventory_id: string;
  actor_id: string;
  command_id: string;
  input_digest: string;
  context_digest: string;
  evidence_digest: string;
  execution_context: PackageReviewExecutionContext;
  as_of: string;
  frozen_at: string;
  blockers: (
    | "PROJECT_WORK_CLOSED"
    | "PACKAGE_BIDDER_UNCONFIRMED"
    | "PACKAGE_REVIEW_IDENTITY_STALE"
    | "PACKAGE_REVIEW_PACKAGE_STALE"
    | "PACKAGE_REVIEW_INVENTORY_STALE"
    | "PACKAGE_REVIEW_RULE_SET_STALE"
    | "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_UNPROVEN"
    | "PACKAGE_REVIEW_SOURCE_CHANGED"
    | "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE"
    | "PACKAGE_REVIEW_MEMBERS_UNPROVEN"
    | "PACKAGE_REVIEW_EVIDENCE_CHANGED"
    | "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP"
    | "PACKAGE_REVIEW_EXTRACTION_UNPROVEN"
    | "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN"
    | "PACKAGE_REVIEW_EXECUTOR_NOT_READY"
  )[];
  review_ready: false;
  launch_available: false;
};

export type PackageReviewVerifiedOriginal = {
  role: "target" | "authority";
  member_id: string;
  document_version_id: string;
  parse_run_id: string;
  file_digest: string;
  byte_size: number;
};

export type BidPackage_requirement = {
  requirement_id: string;
  scope: BidPackage_scope;
  origin: "authority" | "company" | "manual";
  source_refs: string[];
  categories: string[];
  target_part_ids: string[];
  minimum_count: number | null;
  applicability: "applicable" | "unknown" | "not_applicable";
  applicability_evidence: string[];
  valid_at: string | null;
  conditions: string[];
  checks: string[];
  identity_version: "bid-requirement/1";
};

export type BidPackage_coverage = {
  requirement_id: string;
  package_digest: string;
  state:
    | "not_provided"
    | "missing"
    | "pending_parse"
    | "parse_gap"
    | "unsupported"
    | "verified"
    | "not_applicable"
    | "conflict"
    | "unknown";
  inspected: BidPackage_inspectedRange[];
  evidence_refs: string[];
  reason: string | null;
  requirement_digest: string;
};

export type BidPackage_scope = {
  engineering_project_id: string;
  lot_id: string;
  round_id: string;
  bid_id: string;
  bidder_id: string;
  bidder_status: "confirmed" | "pending";
};

export type BidPackage_member = {
  member_id: string;
  document_version_id: string;
  file_digest: string;
  source_kind: "authority" | "own";
  source_ref: string;
  scope: BidPackage_scope;
  purposes: string[];
  page_count: number | null;
  parse: BidPackage_parseIdentity;
  parts: BidPackage_part[];
};

export type BidPackageHead = {
  id: string;
  bid_id: string;
  kind: "authority" | "bid";
  revision_id: string;
  revision: number;
  digest: string;
};

export type BidPackageRevisionSummary = {
  id: string;
  package_id: string;
  revision: number;
  digest: string;
  created_at: string;
};

export type BidPackageDocument = {
  id: string;
  bid_id: string;
  file_id: string;
  file_revision: number;
  filename: string;
  role: "tender" | "supplement" | "drawing" | "boq" | "body";
  artifact_kind:
    | "bid_body"
    | "review_report"
    | "annotated_review_copy"
    | "source_original"
    | "research_artifact";
  sha256: string;
  verified_upload: boolean;
};

export type BidPackageParse = {
  id: string;
  document_version_id: string;
  coverage: "complete" | "partial" | "failed";
  page_count: number;
  gaps: unknown[];
  parser_digest: string;
  config_digest: string;
  created_at: string;
};

export type WordInspectionView = {
  schema: "word-intake-inspection/1";
  container_validated: true;
  entry_count: number;
  expanded_bytes: number;
  xml_part_count: number;
  active_content_gaps: string[];
  unsupported_layout_features: string[];
  requested_fonts: string[];
  conversion_eligible: boolean;
  text_digest: string;
};

export type WordConversionView = {
  state:
    | "pending"
    | "running"
    | "cancelling"
    | "cancelled"
    | "succeeded"
    | "failed";
  operation_id: string | null;
  conversion_attempted: boolean;
  coverage: "pending" | "complete" | "partial" | "failed";
  error_code: string | null;
  retryable: boolean;
  gaps: string[];
  pdf_document_version_id: string | null;
  controlled_render_verified: boolean;
};

export type AuthoringPlanVersion = {
  id: string;
  bid_id: string;
  draft_id: string;
  section_id: string;
  revision: number;
  base_section_revision: number;
  state: "not_started" | "drafting" | "needs_basis" | "ready";
  planned_pages: number | null;
  payload: { [key: string]: AuthoringJsonValue };
  digest: string;
  created_by: string;
  created_at: string;
};

export type AuthoringTreeNode = {
  section_id: string;
  parent_id: string | null;
  ordinal: number;
  node_type: "chapter" | "appendix";
  deleted: boolean;
  section_revision: number;
  plan_version_id: string | null;
  template_family_id: string | null;
  template_key: string | null;
};

export type AssistantExecution = {
  id: string;
  state:
    | "queued"
    | "running"
    | "cancel_requested"
    | "succeeded"
    | "failed"
    | "cancelled";
  cancel_requested_at: string | null;
  handler_version: string;
  scope: "project" | "global";
  bid_id: string | null;
  error_code?: string | null;
};

export type AssistantLogicalIntent = {
  id: string;
  request_mode: "new_question";
  normalized_question: string;
  coarse_key: string;
  anti_resend_key: string;
  price_version_id: string;
  origin_action_id: string | null;
  target: {
    kind: "general" | "project" | "finding" | "rule" | "section";
    id: string | null;
    purpose:
      | "general_reference"
      | "project_reference"
      | "finding_explanation"
      | "rule_explanation"
      | "section_reference"
      | "section_draft";
    bid_id: string | null;
    canonical_project_key: string | null;
  };
};

export type AssistantBudgetReservation = {
  job_id: string;
  intent_id: string;
  actor_id: string;
  coarse_key: string;
  price_id: string;
  member_budget_id: string;
  project_budget_id: string | null;
  global_budget_id: string;
  currency: "CNY" | "USD";
  reserved_minor: number;
  input_upper: number;
  output_upper: number;
  state: "held" | "sent" | "unknown" | "settled" | "released";
  requires_manual_reconciliation: boolean;
  charged_minor: number | null;
  project_call_id: string | null;
  global_call_id: string | null;
  dispatched_at: string | null;
  settled_at: string | null;
  created_at: string;
  price_version: string;
  amount_scale: 1000000000;
  source_kind: "official_tariff_and_context_limit" | "explicit_mock_fixture";
  input_per_million_minor: number;
  output_per_million_minor: number;
  estimate_not_provider_spend_cap: true;
  unknown_hold_released_automatically: false;
};

export type AssistantGlobalMessage = {
  id: string;
  bid_id: null;
  conversation_id: string;
  client_message_id: string | null;
  role: "user" | "assistant" | "tool";
  parts: (
    | {
        type: "text";
        text: string;
      }
    | {
        type: "source_reference";
        document_version_id: string;
        source_bid_id: string;
      }
    | AssistantAnswerPart
  )[];
  created_by: string;
  created_at: string;
  recorded: true;
  assistant_operation_id: string | null;
  formal_scoring_input: false;
  assistant_job_id?: string;
  assistant_operation_scope?: "project" | "global";
  scope: "global";
};

export type AssistantCitationPosition = {
  kind:
    | "structured_project_memory"
    | "original_document"
    | "draft_section"
    | "knowledge_retrieval_unit";
  bid_id: string;
  source_key: string;
  version: string;
  document_version_id: string | null;
  parse_id: string | null;
  physical_pages: number[];
  evidence_ids: string[];
  section_id: string | null;
  section_revision: number | null;
  knowledge_trace_id: string | null;
  knowledge_unit_id: string | null;
  verbatim_original: boolean;
  knowledge_provenance:
    | KnowledgeDerivedProvenance
    | KnowledgeQuoteProvenance
    | null;
};

export type SourceSelection = {
  mode?: "current_project" | "selected_versions";
  version_ids?: string[];
};

export type ExactPackageReviewSelection = {
  mode: "exact_package_review";
  input: PackageReviewSelection;
};

export type Trigger = {
  mode?: "manual" | "material_updated" | "schedule";
  cron?: string | null;
  timezone?: string;
};

export type PackageReviewSelection = {
  package_id: string;
  revision_id: string;
  inventory_id: string;
  frozen_input_id: string;
  frozen_input_digest: string;
  execution_input_id: string;
  execution_input_digest: string;
  dependency_plan_id: string;
  dependency_plan_digest: string;
  method_digest: string;
};

export type TemplateSnapshotConfig = {
  schema: "task-template/1";
  definition: TemplateRequest;
  paused: boolean;
  formal_decisions_allowed: false;
};

export type TaskKindView = {
  task_kind:
    | "denial_check"
    | "scoring_review"
    | "supplement_impact"
    | "chapter_suggestion";
  name: string;
  purpose: "compliance" | "assist";
  execution:
    | "unavailable"
    | "partial"
    | "existing_review_control_plane"
    | "existing_authoring_proposal_queue";
  reason?: string | null;
  formal_scoring_eligible?: false | null;
  coverage?: "registered_effectivity_only" | null;
  semantic_impact_coverage?: "unknown" | null;
  formal_decisions_allowed?: false | null;
  automatic_apply?: false | null;
  exact_package_manual?: PackageTaskManualCapabilities | null;
  exact_package_triggers?: PackageTaskTriggerCapabilities | null;
  exact_package_authoring?: PackageTaskAuthoringCapabilities | null;
};

export type TaskNotification = {
  id: string;
  payload: TaskNotificationPayload;
  created_at: string;
};

export type TaskScheduleRecovery = {
  id: string;
  payload: TaskScheduleRecoveryPayload;
  created_at: string;
};

export type TaskDraftInterpretation = {
  interpreter?: "bounded-zh-task-draft/1";
  raw_request: string;
  name: string;
  task_kind:
    | "denial_check"
    | "scoring_review"
    | "supplement_impact"
    | "chapter_suggestion"
    | null;
  instructions: string;
  section_id: string | null;
  source_selection:
    | SourceSelection
    | ExactPackageReviewSelection
    | ExactPackageTriggerSelection
    | ExactPackageAuthoringSelection;
  trigger: Trigger;
  target_description: string;
  output_description: string;
  unresolved: TaskDraftUnresolvedField[];
  ready_for_template_form: boolean;
  template_saved?: false;
  run_created?: false;
  formal_decisions_allowed?: false;
};

export type KnowledgeRetrievalHit = {
  unit_id: string;
  unit_source_id: string;
  unit_kind: "knowledge_text" | "original_quote";
  knowledge_id: string;
  knowledge_version_id: string;
  knowledge_source_id: string;
  index_id: string;
  text: string;
  span_start: number;
  span_end: number;
  offset_basis: "knowledge_content" | "approved_excerpt";
  provenance: KnowledgeDerivedProvenance | KnowledgeQuoteProvenance;
  rank: number;
  reference_only: true;
  project_fact_created: false;
};

export type KnowledgeDerivedProvenance = {
  kind: "derived_knowledge";
  offset_basis: "knowledge_content";
  approved_references: KnowledgeSourcePosition[];
  verbatim_original: false;
};

export type KnowledgeQuoteProvenance = {
  kind: "original_quote";
  offset_basis: "approved_excerpt";
  reference: KnowledgeSourcePosition;
  verbatim_original: true;
};

export type KnowledgeProjectContext = {
  bid_id: string;
  bid_revision: number;
  material_revision: number;
  settings_revision: number;
  phase: string;
  archived_at: string | null;
  fact_set_id: string | null;
  fact_revision: number;
  decision_heads_digest: string;
  identity:
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        lot_id: string | null;
        round_no: number;
        binding_status: "confirmed";
        authority_id: string;
        digest: string;
        identity_version: "bid-identity/2";
      }
    | {
        bidder_id: string;
        bidder_name: string;
        round_id: string;
        engineering_project_id: string;
        engineering_title: string;
        region: string | null;
        engineering_type: string | null;
        lot: string | null;
        round_no: number;
        binding_status: "confirmed";
        authority_id: string;
        digest: string;
        identity_version?: "bid-identity/1";
      };
};

export type SubmissionRiskSnapshot = {
  submission_id: string;
  review_id: string | null;
  manifest_digest: string | null;
  body_version_id: string;
  scope_issue_ids: string[];
  roots: {
    root_id: string;
    finding_id: string;
    state: string;
    decision_id: string | null;
    evidence_ids: string[];
  }[];
  identified: number | null;
  open: number | null;
  resolved: number | null;
  dismissed: number | null;
  assessment_as_of: string;
  frozen_at: string;
  basis: "reconstructed_from_audit" | "unknown";
  scope_definition: "disqualification_and_mandatory_root_findings";
  not_all_submission_blockers: true;
  observation_authority_id: string | null;
  scope_note: string;
};

export type HistoricalBidIdentitySnapshot =
  | {
      bidder_id: string;
      bidder_name: string;
      round_id: string;
      engineering_project_id: string;
      engineering_title: string;
      region: string | null;
      engineering_type: string | null;
      lot: string | null;
      round_no: number;
      binding_status: "confirmed" | "pending";
      authority_id: string | null;
      digest: string;
      identity_version?: "bid-identity/1";
    }
  | {
      bidder_id: string;
      bidder_name: string;
      round_id: string;
      engineering_project_id: string;
      engineering_title: string;
      region: string | null;
      engineering_type: string | null;
      lot: string | null;
      lot_id: string | null;
      round_no: number;
      binding_status: "confirmed" | "pending";
      authority_id: string | null;
      digest: string;
      identity_version: "bid-identity/2";
    };

export type BidIdentitySnapshot = {
  bidder_id: string;
  bidder_name: string;
  round_id: string;
  engineering_project_id: string;
  engineering_title: string;
  region: string | null;
  engineering_type: string | null;
  lot: string | null;
  lot_id: string | null;
  round_no: number;
  binding_status: "confirmed" | "pending";
  authority_id: string | null;
  digest: string;
  identity_version: "bid-identity/2";
};

export type PackageSubmissionGate_View = {
  manifest: PackageSubmissionGate_Manifest;
  digest: string;
};

export type SubmissionDocumentView = {
  document_version_id: string;
  original_name: string;
  artifact_kind: string;
  digest: string;
  byte_size: number;
  media_type: string;
};

export type PricingApplicability = {
  applicable: boolean;
  reasons: string[];
};

export type PricingFormulaManifest = {
  schema: "pricing-formula/1" | "pricing-formula/2";
  formula_version_id: string;
  bid_id: string;
  material_snapshot_id: string | null;
  material_revision: number;
  applicability_scope: {
    bid_id: string;
    round_id: string;
    effective_documents: {
      role: "tender" | "supplement";
      document_version_id: string;
      digest: string;
    }[];
  };
  title: string;
  formula: PricingFormulaParameters;
  amount_unit: "元" | "万元";
  currency: "CNY" | null;
  rounding_policy: "half_up_2dp" | "half_even_2dp";
  interpretation: PricingInterpretation;
  terms_complete_confirmed: true;
  matches_source_confirmed: true;
  evidence_quotes: PricingEvidenceQuote[];
  reason: string;
  confirmed_by: string;
  confirmed_at: string;
  calculator: {
    name: string;
    version: number;
    implementation_sha256: string;
  };
  source_authority: {
    scope: {
      bid_id: string;
      round_id: string;
      effective_documents: {
        role: "tender" | "supplement";
        document_version_id: string;
        digest: string;
      }[];
    };
    ancestor_heads: {
      source_id: string;
      id: string;
      document_version_id: string;
      kind: "document";
      policy_class: "prebid_content";
      known_at: string;
      digest: string;
      revision: number;
      status: "published" | "withdrawn" | "candidate";
      valid_from: string;
      valid_until: string | null;
      bid_id: string;
    }[];
    package_snapshot?: {
      version: "package-pricing-authority/1";
      binding: PricingPackagePricingBinding;
      package_digest: string;
      authority_digest: string;
      identity_digest: string;
      source_heads_digest: string;
      rule_set_id: string | null;
      inventory_id: string | null;
      inventory_digest: string | null;
    };
  };
  package_binding?: PricingPackagePricingBinding;
};

export type PricingCurveRange = {
  lower: string;
  upper: string;
  points: number;
};

export type PricingFrozenResult = {
  id: string;
  formula_version_id: string;
  formula_digest: string;
  input_digest: string;
  formula_evidence_ids: string[];
  price_score: string | null;
  eligible: boolean;
  notes: string[];
  candidate_price: string;
  maximum: string;
  baseline_price: string | null;
  valid_price_count: number;
  candidates: PricePoint[];
  curve: PricePoint[];
  calculation_steps: string[];
  assumptions: string[];
  technical_exchange_note: string;
  excluded_competitor_assumptions: {
    index: number;
    price: string;
    reason: string;
  }[];
};

export type KnowledgeApplicability = {
  bidder_ids: string[];
  bid_ids: string[];
  regions: string[];
  engineering_types: string[];
  conditions: {
    subject: string;
    scope: string;
    name: string;
    value: string | number | boolean;
    unit: string | null;
  }[];
  purposes: ("assist" | "authoring" | "compliance" | "history")[];
  validity_kind: "bounded" | "no_expiry_confirmed" | "unknown";
  valid_from: string;
  valid_until: string | null;
  validity_basis: string;
  specificity_note: string;
};

export type KnowledgeSourcePosition = {
  source_id: string;
  source_revision: number;
  document_version_id: string;
  parse_id: string;
  physical_page: number;
  evidence_id: string;
  excerpt: string;
};

export type KnowledgeReference = {
  knowledge_id: string;
  version_id: string;
  bid_id: string;
  citation_ids: string[];
  excerpt: string;
  purpose: "assist" | "authoring" | "compliance" | "history";
  target_kind:
    | "project"
    | "section"
    | "operation"
    | "review"
    | "package_review_run";
  target_object_id: string;
  applicability_reason: string;
  source_manifest: KnowledgeAuthority[];
  source_refs: KnowledgeSourcePosition[];
  reference_only: true;
  project_fact_created: false;
  evaluated_at: string;
  project_context?: KnowledgeProjectContext;
};

export type ResearchOutcomeView = {
  id: string;
  bid_id: string;
  submission_id: string;
  score_kind: "technical_total" | "comprehensive_total" | "unknown";
  value: string | null;
  maximum: string | null;
  verification: "pending" | "verified" | "conflict" | "rejected";
  source_version_id: string;
  known_at: string;
  verification_revision: number;
  supersedes_id: string | null;
  verification_details:
    | SingleBodyOutcomeVerification
    | PackageOutcomeVerificationDetails
    | null;
};

export type SingleBodyOutcomeVerification = {
  state: "pending" | "verified" | "conflict" | "rejected";
  reason: string;
  identity: { [key: string]: string };
  aggregation: string;
  published_at: string | null;
  evidence_ids: string[];
  material_snapshot_id: string | null;
  effective_material_confirmed: boolean;
};

export type ResearchListedSample = {
  id: string;
  bid_id: string;
  submission_id: string;
  outcome_id: string;
  source_group_id: string;
  known_at: string;
  admission: "pending" | "admitted" | "rejected";
  reasons: string[];
  current: boolean;
};

export type AuthoringBreak = {
  type: "hardBreak";
};

export type AuthoringText = {
  type: "text";
  text: string;
  marks?: {
    type: "bold" | "italic";
  }[];
};

export type AuthoringParagraph = {
  type: "paragraph";
  attrs: {
    id: string;
  };
  content: (AuthoringText | AuthoringBreak)[];
};

export type AuthoringHeading = {
  type: "heading";
  attrs: {
    id: string;
    level: number;
  };
  content: (AuthoringText | AuthoringBreak)[];
};

export type AuthoringBulletList = {
  type: "bulletList";
  attrs: {
    id: string;
  };
  content: AuthoringListItem[];
};

export type AuthoringOrderedList = {
  type: "orderedList";
  attrs: {
    id: string;
  };
  content: AuthoringListItem[];
};

export type AuthoringListItem = {
  type: "listItem";
  attrs: {
    id: string;
  };
  content: (AuthoringParagraph | AuthoringBulletList | AuthoringOrderedList)[];
};

export type AuthoringExactSnapshotExtension = {
  protocol: "authoring-exact-snapshot/1";
  sections: AuthoringExactSectionBinding[];
  digest: string;
};

export type AuthoringStructureExtension = {
  id: string;
  schema_digest: string;
  nodes: AuthoringTreeNode[];
  plans: { [key: string]: AuthoringPlanVersion };
  directory_template: AuthoringTemplateVersionView;
  style_template: AuthoringTemplateVersionView;
  metadata: { [key: string]: AuthoringJsonValue };
  digest: string;
};

export type SectionSummary = {
  id: string;
  title: string;
  revision: number;
  ordinal: number;
  rule_ids: string[];
  save_state: "saved";
};

export type SectionChange = {
  section_id: string;
  base_section_revision: number;
  schema_digest: string;
  content: AuthoringDocument | AuthoringRichDocument;
};

export type AuthoringStructuredBuildRequest = {
  draft_id: string;
  draft_revision: number;
  directory_template_version_id: string;
  style_template_version_id: string;
  formats: ("docx" | "pdf")[];
  follow_up: "none" | "review";
};

export type AuthoringBuildIdentity = {
  protocol: "authoring-build-identity/1";
  bid_id: string;
  draft_id: string;
  draft_revision: number;
  snapshot_id: string;
  snapshot_digest: string;
  build_input_id: string;
  input_digest: string;
  manifest_digest: string;
  writer_kind: string;
  request: BuildRequest;
};

export type BuildFollowUpView = {
  requested: boolean;
  state: "not_requested" | "pending" | "adopted" | "needs_selection" | "failed";
  adopted_document_version_id: string | null;
  parse_operation_id: string | null;
  request_id: string | null;
  review_id: string | null;
  reasons: string[];
};

export type ReviewIntentView = {
  request_id: string;
  trigger: "manual" | "automatic" | "build_follow_up";
  body_version_id: string;
  material_snapshot_id: string;
  material_revision: number;
  state:
    | "preparing"
    | "blocked"
    | "superseded"
    | "queued"
    | "running"
    | "cancel_requested"
    | "completed"
    | "cancelled";
  prepare_operation_id: string;
  review_id: string | null;
  error_code: string | null;
  gaps: string[];
  updated_at: string;
};

export type SourceRef = {
  id: string;
  digest: string;
  kind: "tender" | "supplement" | "body" | "prebid_fact";
  known_at: string;
  lineage_manifest_digest: string;
};

export type PredictionView = {
  review_id: string;
  mode: "hidden" | "partial" | "raw_uncalibrated" | "accepted" | "unavailable";
  maximum: string | null;
  reasons: string[];
  method_digest: string;
  value?: string;
  interval?: {
    lower: string;
    upper: string;
  };
};

export type NextAction = {
  action: string;
  reason: string;
  target_url: string;
  blocked: boolean;
};

export type ReviewCoverage = {
  source_scope: CoverageLayer;
  core_extraction: CoverageLayer;
  judgment: CoverageLayer;
  scoring: CoverageLayer;
  extraction_quality: "not_measured" | "measured";
  quality_report_id: string | null;
  human_confirmation_pending: number;
};

export type RuleView = {
  id: string;
  rule_set_id: string;
  kind: "disqualification" | "mandatory" | "scoring" | "advisory";
  statement: string;
  conditions: string[];
  exceptions: string[];
  maximum: string | null;
  evidence_ids: string[];
  confirmation: "pending" | "confirmed" | "rejected" | "deferred";
  decision_revision: number;
  carryover: RuleCarryoverView | null;
  scope: RuleScope;
  bands: RuleBand[];
  origin_kind: "model_extracted" | "human_added" | "carried_human";
  manual_origin_rule_id: string | null;
  provenance_status: "effective" | "needs_revalidation" | "superseded";
};

export type FactView = {
  id: string;
  subject: string;
  scope: string;
  name: string;
  value: string | boolean | null;
  unit: string | null;
  evidence_ids: string[];
  confirmation: "pending" | "confirmed" | "rejected";
  decision_revision: number;
  carryover: FactDecisionCarryover | null;
  decision: DecisionView | null;
  source_validity: "effective" | "needs_revalidation";
  source_issues: string[];
};

export type FindingView = {
  id: string;
  review_id: string;
  rule_id: string | null;
  category:
    | "disqualification"
    | "response"
    | "consistency"
    | "scope"
    | "improvement";
  severity: "critical" | "major" | "minor" | "info";
  verdict:
    | "satisfied"
    | "violated"
    | "not_found"
    | "unable_to_judge"
    | "not_applicable";
  statement: string;
  evidence_ids: string[];
  searched_ranges: string[];
  decision: DecisionView | null;
  decision_revision: number;
  origin_review_id: string;
  retained_known_critical: boolean;
  detection_run_state: "ran" | "not_run_this_round";
  lifecycle: "open" | "deferred" | "resolved_by_recheck" | "dismissed";
};

export type MatrixRow = {
  rule: RuleView;
  verdict:
    | "satisfied"
    | "violated"
    | "not_found"
    | "unable_to_judge"
    | "not_applicable"
    | null;
  finding_ids: string[];
  evidence_ids: string[];
  check_status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  error_code: string | null;
};

export type ProjectSettings = {
  auto_review: boolean;
  consistency: boolean;
  scope_residue: boolean;
  show_prediction: boolean;
  pricing: boolean;
  result_reminder: boolean;
  accept_rules_as_written: boolean;
};

export type RuleConfirmationItem = {
  rule_id: string;
  expected_decision_revision: number;
};

export type RuleConfirmationResult = {
  rule_id: string;
  status: "confirmed" | "skipped";
  decision_revision: number;
  decision_id: string | null;
};

export type FactInput = {
  subject: string;
  scope: string;
  name: string;
  value: string | boolean | null;
  unit: string | null;
  evidence_ids: string[];
  reason: string;
};

export type ValidationDiagnostic = {
  id: string;
  operation_id: string;
  step_key: string;
  code:
    | "quote_not_found"
    | "source_not_allowed"
    | "unsupported_quantity"
    | "unit_mismatch"
    | "scope_mismatch"
    | "invalid_structure"
    | "incomplete_range";
  field_path: string;
  evidence_ids: string[];
  action: "rejected" | "needs_review";
  message: string;
};

export type RuleAddition = {
  kind: "disqualification" | "mandatory" | "scoring" | "advisory";
  statement: string;
  conditions: string[];
  exceptions: string[];
  scope: RuleScope;
  maximum: string | null;
  bands: RuleBand[];
  evidence_quotes: RuleEvidenceQuote[];
};

export type MemberView = {
  id: string;
  display_name: string;
  active: boolean;
};

export type UploadPartGrant = {
  part_number: number;
  byte_offset: number;
  byte_size: number;
  url: string;
  expires_at: string;
};

export type UploadPartReceipt = {
  part_number: number;
  etag: string;
  byte_size: number;
};

export type WordPdfDeclarationView = {
  source_document_version_id: string;
  role:
    | "tender"
    | "supplement"
    | "drawing"
    | "boq"
    | "body"
    | "official_result"
    | "other";
  required_target_kind: "new_file";
  relation_kind: "user_declared_same_draft";
  verification_status: "unverified";
};

export type DocumentRelation = {
  source_document_version_id: string;
  kind: "user_declared_same_draft" | "controlled_render";
  verification: "unverified" | "verified" | "rejected";
  evidence_ids: string[];
};

export type AuthoringHistoryAuthoringSourceReference = {
  source_id: string;
  source_revision: number;
  evidence_id: string;
  document_version_id: string;
};

export type AuthoringHistoryAuthoringBlock =
  | AuthoringHistoryAuthoringParagraph
  | AuthoringHistoryAuthoringHeading
  | AuthoringHistoryAuthoringBulletList
  | AuthoringHistoryAuthoringOrderedList;

export type AuthoringHistoryAuthoringRichTable = {
  type: "table";
  attrs: {
    id: string;
    column_widths_twips: number[];
    caption: string;
  };
  content: AuthoringHistoryAuthoringRichRow[];
};

export type AuthoringHistoryAuthoringRichImage = {
  type: "image";
  attrs: {
    id: string;
    asset_id: string;
    asset_revision: number;
    asset_version_id: string;
    width_twips: number;
    height_twips: number;
    alt: string;
    caption: string;
  };
};

export type AuthoringExactInputIdentity = {
  id: string;
  digest: string;
  context_digest: string;
};

export type AuthoringExactRevisionOrigin = {
  kind: "model_candidate_adoption";
  job_id: string;
  job_input_digest: string;
  action_id: string;
  action_digest: string;
  candidate_digest: string;
  command_id: string;
  actor_id: string;
  before_action_digest: string;
};

export type AuthoringExactRevisionMethod = {
  protocol: "authoring-exact-adoption-policy/1";
  supported_content: "plain_text_stable_node";
  source_sha256: { [key: string]: string };
};

export type AuthoringExactTextEditOrigin = {
  kind: "manual_text_edit";
  parent_qualification_id: string;
  parent_qualification_digest: string;
  root_qualification_id: string;
  root_qualification_digest: string;
  command_id: string;
  actor_id: string;
  before_action_digest: string;
  node_id: string;
  before_node_digest: string;
  replacement_text_digest: string;
  reason: string;
};

export type AuthoringExactTextEditMethod = {
  protocol: "authoring-exact-text-edit-policy/1";
  supported_content: "plain_text_stable_node";
  source_sha256: { [key: string]: string };
};

export type PackageReference = {
  package_id: string;
  revision_id: string;
  manifest_digest: string;
};

export type InventoryReference = {
  id: string;
  digest: string;
  rule_set_id: string;
};

export type FactUse = {
  fact_id: string;
  fact_item_digest: string;
  subject: FactSubject;
  reason: string;
};

export type WorkContextReadOnlyAuthoringSourceReference = {
  source_id: string;
  source_revision: number;
  evidence_id: string;
  document_version_id: string;
};

export type WorkContextReadOnlyAuthoringBlock =
  | WorkContextReadOnlyAuthoringParagraph
  | WorkContextReadOnlyAuthoringHeading
  | WorkContextReadOnlyAuthoringBulletList
  | WorkContextReadOnlyAuthoringOrderedList;

export type WorkContextReadOnlyAuthoringRichTable = {
  type: "table";
  attrs: {
    id: string;
    column_widths_twips: number[];
    caption: string;
  };
  content: WorkContextReadOnlyAuthoringRichRow[];
};

export type WorkContextReadOnlyAuthoringRichImage = {
  type: "image";
  attrs: {
    id: string;
    asset_id: string;
    asset_revision: number;
    asset_version_id: string;
    width_twips: number;
    height_twips: number;
    alt: string;
    caption: string;
  };
};

export type WorkContextReviewSummary = {
  run_id: string;
  input_digest: string;
  result_digest: string;
  requirement_count: number;
  machine_counts: {
    satisfied: number;
    violated: number;
    not_found: number;
    unable_to_judge: number;
    not_applicable: number;
  };
  human_counts: {
    unreviewed: number;
    confirmed: number;
    rejected: number;
    needs_review: number;
  };
  human_heads_digest: string;
  human_basis: "current_heads_for_exact_result";
  matrix_coverage: "complete" | "partial";
  overall_coverage: "partial";
  inventory_complete: false;
  quality_status: "not_measured";
  risk_resolution_assessed: false;
};

export type PackageRuleCorrection_RuleScope = {
  bid_id: string;
  description: string;
};

export type PackageScopeReview_Scope = {
  bid_id: PackageScopeReview_Id;
  package_id: PackageScopeReview_Id;
  revision_id: PackageScopeReview_Id;
  inventory_id: PackageScopeReview_Id;
};

export type PackageScopeReview_Id = string;

export type PackageScopeReview_Identity = {
  version: "package-review-execution/1";
  kind: "identity";
  binding: PackageScopeReview_Binding;
  rerun: PackageScopeReview_RerunIntent | null;
  content_digest: PackageScopeReview_Digest;
  execution_digest: PackageScopeReview_Digest;
};

export type PackageScopeReview_MethodProfile = {
  engine: "package-review/1";
  purpose: "prebid_compliance";
  assessment: "declared_requirement_response";
  input_scope: "all_frozen_target_and_authority_members";
  model_json_encoding: "finite-json-numbers/1";
  model: "deepseek-flash" | "deepseek-v4-pro";
  endpoint: "https://api.deepseek.com" | "https://api.deepseek.com/v1";
  source_digest: PackageScopeReview_Digest;
  batch_rule_limit: 100;
  batch_limit: 4;
  output_tokens_per_batch: 8192;
  input_character_limit: 240000;
  semantic_quality: "not_measured";
  formal_scoring_eligible: false;
  submission_eligible: false;
};

export type AuthoringRichRow = {
  type: "tableRow";
  attrs: {
    id: string;
  };
  content: AuthoringRichCell[];
};

export type PackageScopeReview_SubmittedDocument = {
  package_role: "target" | "authority";
  member_id: string;
  document_version_id: PackageScopeReview_Id;
  parse_run_id: PackageScopeReview_Id;
  file_digest: PackageScopeReview_Digest;
  page_count: number;
  parts: PackageScopeReview_Part[];
  evidence_count: number;
};

export type PackageScopeReview_MatrixRow = {
  requirement_id: PackageScopeReview_Id;
  requirement_digest: PackageScopeReview_Digest;
  rule_digest: PackageScopeReview_Digest;
  rule_kind: "disqualification" | "mandatory" | "scoring" | "advisory";
  requirement_statement: string;
  applicability: "applicable" | "unknown" | "not_applicable";
  target_part_ids: string[];
  inspected_ranges: PackageScopeReview_InspectedRange[];
  verdict:
    | "satisfied"
    | "violated"
    | "not_found"
    | "unable_to_judge"
    | "not_applicable";
  statement: string;
  target_quotes: PackageScopeReview_Quote[];
  authority_quotes: PackageScopeReview_Quote[];
  used_fact_ids: PackageScopeReview_Id[];
  limitations: string[];
  human_review_state: "unreviewed";
};

export type PackageDependencyPlan_Assessment_Digest = string;

export type PackageDependencyPlan_Assessment_Id = string;

export type PackageDependencyPlan_Assessment_Dependency = {
  requirement_id: PackageDependencyPlan_Assessment_Id;
  requirement_digest: PackageDependencyPlan_Assessment_Digest;
  state: "unknown" | "not_needed" | "required";
  fact_ids: PackageDependencyPlan_Assessment_Id[];
  evidence_ids: PackageDependencyPlan_Assessment_Id[];
  reason: string;
};

export type PackageDependencyPlan_Manifest = {
  version: "package-dependency-plan/1";
  kind: "human_dependency_plan";
  id: PackageDependencyPlan_Assessment_Id;
  actor_id: PackageDependencyPlan_Assessment_Id;
  command_id: PackageDependencyPlan_Assessment_Id;
  saved_at: string;
  reason: string;
  request_digest: PackageDependencyPlan_Assessment_Digest;
  prepared: PackageDependencyPlan_Assessment_Prepared;
  assessment: PackageDependencyPlan_Assessment_View;
  usage: PackageDependencyPlan_Usage_View;
  inventory_complete: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type PackageInputDependencies_Id = string;

export type PackageInputDependencies_Digest = string;

export type PackageInputDependencies_Manifest =
  | PackageInputDependencies_ManifestV1
  | PackageInputDependencies_ManifestV2;

export type PackageFactChange_Digest = string;

export type PackageFactChange_Id = string;

export type PackageFactChange_Fact = {
  subject: string;
  scope: string;
  name: string;
  value: string | boolean | null;
  unit: string | null;
  evidence_ids: string[];
  reason: string;
};

export type PackageFactChange_Manifest = {
  version: "package-fact-change/1";
  kind: "package_fact_change";
  command_id: PackageFactChange_Id;
  actor_id: PackageFactChange_Id;
  action: "confirmed" | "withdrawn";
  recorded_at: string;
  reason: string;
  binding: PackageFactChange_Binding;
  previous_head: PackageFactChange_Head;
  head: PackageFactChange_Head;
  fact_id: PackageFactChange_Id;
  replaces_fact_id: PackageFactChange_Id | null;
  decision_id: PackageFactChange_Id | null;
  evidence_selection_digest: PackageFactChange_Digest | null;
  evidence_basis_digest: PackageFactChange_Digest | null;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type PackageFactChange_ManifestV2 = {
  version: "package-fact-change/2";
  kind: "package_fact_change";
  command_id: PackageFactChange_Id;
  actor_id: PackageFactChange_Id;
  action: "confirmed" | "withdrawn";
  recorded_at: string;
  reason: string;
  binding: PackageFactChange_Binding;
  previous_head: PackageFactChange_Head;
  head: PackageFactChange_Head;
  fact_id: PackageFactChange_Id;
  replaces_fact_id: PackageFactChange_Id | null;
  decision_id: PackageFactChange_Id | null;
  evidence_selection_digest: PackageFactChange_Digest | null;
  evidence_basis_digest: PackageFactChange_Digest | null;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  request_digest: PackageFactChange_Digest;
};

export type PackageFactScope_Digest = string;

export type PackageFactScope_Subject = {
  kind: "engineering_project" | "lot" | "round" | "bidder";
  id: PackageFactScope_Id;
};

export type PackageFactScope_Manifest = {
  version: "package-fact-scope/1";
  kind: "fact_scope_declaration";
  id: PackageFactScope_Id;
  actor_id: PackageFactScope_Id;
  command_id: PackageFactScope_Id;
  recorded_at: string;
  reason: string;
  action: "bind" | "withdraw";
  previous_digest: PackageFactScope_Digest | null;
  binding: PackageFactScope_ScopeBinding;
  subject: PackageFactScope_Subject;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type PackageExecution_Id = string;

export type PackageExecution_Identity = {
  version: "package-review-execution/1";
  kind: "identity";
  binding: PackageExecution_Binding;
  rerun: PackageExecution_RerunIntent | null;
  content_digest: PackageExecution_Digest;
  execution_digest: PackageExecution_Digest;
};

export type BidPackage_inspectedRange = {
  part_id: string;
  first_page: number;
  last_page: number;
};

export type BidPackage_parseIdentity = {
  status: "frozen" | "not_frozen";
  parse_run_id: string | null;
  parser_digest: string | null;
  config_digest: string | null;
  evidence_digest: string | null;
  reason: string | null;
};

export type BidPackage_part = {
  part_id: string;
  category: string;
  first_page: number;
  last_page: number;
  shared_attachment: boolean;
  heading_path: number[];
};

export type PackageTaskManualCapabilities = {
  available: boolean;
  reason: string | null;
  input_mode: "exact_package_review";
  method_digest: string;
  trigger: "manual";
  overall_coverage: "partial";
  formal_scoring_eligible: false;
  submission_eligible: false;
  automatic_input_selection: false;
};

export type TaskNotificationPayload = {
  key: string;
  run_id: string;
  state: string;
  error_code: string | null;
  run_ref: string;
};

export type TaskScheduleRecoveryPayload = {
  schedule_id: string;
  definition_id: string;
  run_current_once_ref: string | null;
  reconfirm_template_ref?: string | null;
  definition_version_id: string;
  next_fire_at: string;
  missed: MissedTaskSchedule | null;
  automatic_catchup_runs: 0;
};

export type TaskDraftUnresolvedField = {
  field: string;
  reason: string;
};

export type PackageSubmissionGate_Manifest = {
  version: "package-submission-gate/1";
  kind: "current_package_submission_observation";
  subject: {
    kind: "bid_package";
    bid_id: string;
    package_id: string;
    revision_id: string;
    package_digest: string;
    identity_digest: string;
  };
  selection: {
    digest: string;
    authority_revision_id: string | null;
    authority_digest: string | null;
    inventory_id: string | null;
    inventory_digest: string | null;
    coverage_attempt_id: string | null;
    coverage_digest: string | null;
    run_id: string | null;
    result_digest: string | null;
  };
  checked_at: string;
  policy_digest: string;
  gates: {
    current_input: PackageSubmissionGate_CurrentInput;
    core_coverage: PackageSubmissionGate_CoreCoverage;
    mandatory_confirmation: PackageSubmissionGate_MandatoryConfirmation;
    known_blocking_risks: PackageSubmissionGate_KnownBlockingRisks;
  };
  state: "blocked" | "unknown";
  allowed: false;
  inventory_complete: false;
  quality_status: "not_measured";
  formal_scoring_eligible: false;
  submission_eligible: false;
  publication_authorized: false;
  platform_submission_verified: false;
  limitations: string[];
};

export type KnowledgeAuthority = {
  source_id: string;
  ancestor_id: string;
  kind: "document" | "knowledge" | "summary" | "feature" | "label" | "model";
  policy_class:
    | "prebid_content"
    | "official_label"
    | "post_outcome"
    | "derived_mixed";
  known_at: string;
  digest: string;
  revision: number;
  status: "published";
  valid_from: string;
  valid_until: string | null;
};

export type CoverageLayer = {
  state: "pending" | "complete" | "partial" | "failed" | "not_run";
  planned: number;
  completed: number;
  denominator_basis: string;
  gaps: string[];
};

export type RuleCarryoverView = {
  from_rule_id: string;
  from_decision_id: string;
  equivalence_digest: string;
  adopted_at: string;
};

export type RuleScope = {
  bid_id: string;
  description: string;
};

export type RuleBand = {
  label: string;
  description: string;
  points: string;
  evidence_ids: string[];
};

export type FactDecisionCarryover = {
  from_fact_id: string;
  from_decision_id: string;
  equivalence_digest: string;
  adopted_at: string;
};

export type DecisionView = {
  id: string;
  object_id: string;
  object_revision: number;
  decision: string;
  reason: string;
  actor_id: string;
  created_at: string;
};

export type RuleEvidenceQuote = {
  evidence_id: string;
  quote: string;
};

export type AuthoringHistoryAuthoringParagraph = {
  type: "paragraph";
  attrs: {
    id: string;
  };
  content: (AuthoringHistoryAuthoringText | AuthoringHistoryAuthoringBreak)[];
};

export type AuthoringHistoryAuthoringHeading = {
  type: "heading";
  attrs: {
    id: string;
    level: number;
  };
  content: (AuthoringHistoryAuthoringText | AuthoringHistoryAuthoringBreak)[];
};

export type AuthoringHistoryAuthoringBulletList = {
  type: "bulletList";
  attrs: {
    id: string;
  };
  content: AuthoringHistoryAuthoringListItem[];
};

export type AuthoringHistoryAuthoringOrderedList = {
  type: "orderedList";
  attrs: {
    id: string;
  };
  content: AuthoringHistoryAuthoringListItem[];
};

export type AuthoringHistoryAuthoringRichRow = {
  type: "tableRow";
  attrs: {
    id: string;
  };
  content: AuthoringHistoryAuthoringRichCell[];
};

export type FactSubject = {
  kind: "engineering_project" | "lot" | "round" | "bidder";
  id: string;
};

export type WorkContextReadOnlyAuthoringParagraph = {
  type: "paragraph";
  attrs: {
    id: string;
  };
  content: (
    | WorkContextReadOnlyAuthoringText
    | WorkContextReadOnlyAuthoringBreak
  )[];
};

export type WorkContextReadOnlyAuthoringHeading = {
  type: "heading";
  attrs: {
    id: string;
    level: number;
  };
  content: (
    | WorkContextReadOnlyAuthoringText
    | WorkContextReadOnlyAuthoringBreak
  )[];
};

export type WorkContextReadOnlyAuthoringBulletList = {
  type: "bulletList";
  attrs: {
    id: string;
  };
  content: WorkContextReadOnlyAuthoringListItem[];
};

export type WorkContextReadOnlyAuthoringOrderedList = {
  type: "orderedList";
  attrs: {
    id: string;
  };
  content: WorkContextReadOnlyAuthoringListItem[];
};

export type WorkContextReadOnlyAuthoringRichRow = {
  type: "tableRow";
  attrs: {
    id: string;
  };
  content: WorkContextReadOnlyAuthoringRichCell[];
};

export type PackageScopeReview_Binding = {
  bid_id: PackageScopeReview_Id;
  package_id: PackageScopeReview_Id;
  revision_id: PackageScopeReview_Id;
  inventory_id: PackageScopeReview_Id;
  identity_digest: PackageScopeReview_Digest;
  frozen_input_id: PackageScopeReview_Id;
  frozen_digest: PackageScopeReview_Digest;
  input_digest: PackageScopeReview_Digest;
  evidence_digest: PackageScopeReview_Digest;
  context_digest: PackageScopeReview_Digest;
  method_digest: PackageScopeReview_Digest;
  policy_digest: PackageScopeReview_Digest;
  purpose: "prebid_compliance";
};

export type PackageScopeReview_RerunIntent = {
  nonce: PackageScopeReview_Id;
  reason: string;
};

export type AuthoringRichCell = {
  type: "tableCell";
  attrs: {
    id: string;
    colspan: number;
    rowspan: number;
    header: boolean;
  };
  content: (AuthoringParagraph | AuthoringBulletList | AuthoringOrderedList)[];
};

export type PackageScopeReview_Part = {
  part_id: string;
  category: string;
  first_page: number;
  last_page: number;
  shared_attachment: boolean;
  heading_path: number[];
};

export type PackageScopeReview_InspectedRange = {
  member_id: string;
  document_version_id: PackageScopeReview_Id;
  parse_run_id: PackageScopeReview_Id;
  part_id: string;
  category: string;
  first_page: number;
  last_page: number;
  shared_attachment: boolean;
  heading_path: number[];
};

export type PackageDependencyPlan_Assessment_View = {
  manifest: PackageDependencyPlan_Assessment_Manifest;
  digest: PackageDependencyPlan_Assessment_Digest;
};

export type PackageDependencyPlan_Usage_View = {
  manifest: PackageDependencyPlan_Usage_Manifest;
  digest: PackageDependencyPlan_Usage_Digest;
};

export type PackageInputDependencies_ManifestV1 = {
  version: "package-input-dependencies/1";
  kind: "input_dependency_assessment";
  purpose: "prebid_compliance";
  prepared: PackageInputDependencies_Prepared;
  frozen_digest: PackageInputDependencies_Digest;
  inventory_digest: PackageInputDependencies_Digest;
  usage_digest: PackageInputDependencies_Digest;
  selected_fact_count: number;
  requirement_count: number;
  dependency_review_status: "incomplete" | "declared";
  required_facts_assessment:
    | "unknown"
    | "missing"
    | "selected_unvalidated"
    | "not_used";
  requirements: PackageInputDependencies_RequirementAssessment[];
  inventory_status: "unproven" | "range_submitted_quality_unmeasured";
  declaration_kind: "human_dependency_annotation";
  inventory_complete: false;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  policy_digest: PackageInputDependencies_Digest;
};

export type PackageInputDependencies_ManifestV2 = {
  version: "package-input-dependencies/2";
  kind: "input_dependency_assessment";
  purpose: "prebid_compliance";
  prepared: PackageInputDependencies_Prepared;
  frozen_digest: PackageInputDependencies_Digest;
  inventory_digest: PackageInputDependencies_Digest;
  usage_digest: PackageInputDependencies_Digest;
  selected_fact_count: number;
  requirement_count: number;
  dependency_review_status: "incomplete" | "declared";
  required_facts_assessment:
    | "unknown"
    | "missing"
    | "selected_unvalidated"
    | "not_used";
  requirements: PackageInputDependencies_DerivedRequirementAssessment[];
  inventory_status: "human_derivation_range_quality_unmeasured";
  declaration_kind: "human_dependency_annotation";
  inventory_complete: false;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  policy_digest: PackageInputDependencies_Digest;
  rule_state_counts: {
    total: number;
    active: number;
    inactive: number;
    needs_revalidation: number;
  };
};

export type PackageFactScope_ScopeBinding = {
  bid_id: PackageFactScope_Id;
  package_id: PackageFactScope_Id;
  revision_id: PackageFactScope_Id;
  inventory_id: PackageFactScope_Id;
  identity_digest: PackageFactScope_Digest;
  frozen_input_id: PackageFactScope_Id;
  frozen_digest: PackageFactScope_Digest;
  input_digest: PackageFactScope_Digest;
  evidence_digest: PackageFactScope_Digest;
  context_digest: PackageFactScope_Digest;
  method_digest: PackageFactScope_Digest;
  policy_digest: PackageFactScope_Digest;
  purpose: "prebid_compliance";
  execution_input_id: PackageFactScope_Id;
  execution_input_digest: PackageFactScope_Digest;
  facts_digest: PackageFactScope_Digest;
  fact_set_id: PackageFactScope_Id;
  fact_id: PackageFactScope_Id;
  fact_item_digest: PackageFactScope_Digest;
  proof_digest: PackageFactScope_Digest;
};

export type PackageExecution_Binding = {
  bid_id: PackageExecution_Id;
  package_id: PackageExecution_Id;
  revision_id: PackageExecution_Id;
  inventory_id: PackageExecution_Id;
  identity_digest: PackageExecution_Digest;
  frozen_input_id: PackageExecution_Id;
  frozen_digest: PackageExecution_Digest;
  input_digest: PackageExecution_Digest;
  evidence_digest: PackageExecution_Digest;
  context_digest: PackageExecution_Digest;
  method_digest: PackageExecution_Digest;
  policy_digest: PackageExecution_Digest;
  purpose: "prebid_compliance";
};

export type PackageExecution_Digest = string;

export type MissedTaskSchedule = {
  from: string;
  through: string;
  count: null;
  count_status: "not_enumerated";
  resolution:
    | "skipped_run_current_once_available"
    | "skipped_reconfirm_exact_input";
};

export type PackageSubmissionGate_CurrentInput = {
  state: "blocked" | "unknown" | "pass";
  codes: string[];
  scope: "current_metadata_observation";
  observations_digest: string | null;
  current_identity_digest: string | null;
  original_verification: "not_performed" | "failed";
  member_count: number;
  physical_page_gaps: {
    role: "target" | "authority";
    member_id: string;
    first_page: number;
    last_page: number;
  }[];
};

export type PackageSubmissionGate_CoreCoverage = {
  state: "blocked" | "unknown" | "pass";
  codes: string[];
  scope: "known_inventory_core_rules";
  inventory_proof_digest: string | null;
  run_id: string | null;
  active_core_count: number;
  judged_core_count: number;
  unknown_core_count: number;
  unfavorable_core_count: number;
  human_declared_count: number;
  extraction_range_proven: boolean;
  inventory_complete: false;
  quality_status: "not_measured";
  overall_coverage: "partial" | "unknown";
};

export type PackageSubmissionGate_MandatoryConfirmation = {
  state: "blocked" | "unknown" | "pass";
  codes: string[];
  scope: "known_inventory_core_rules";
  core_rule_count: number;
  confirmed_count: number;
  pending_rule_ids: string[];
  inactive_rule_ids: string[];
  needs_revalidation_rule_ids: string[];
  decisions: {
    rule_id: string;
    rule_digest: string;
    decision_id: string | null;
    decision_digest: string | null;
    decision: string | null;
  }[];
};

export type PackageSubmissionGate_KnownBlockingRisks = {
  state: "blocked" | "unknown" | "pass";
  codes: string[];
  scope: "whole_bid_known_history";
  history_digest: string | null;
  history_complete: boolean;
  runs_read: number;
  result_rows_read: number;
  unknown_run_ids: string[];
  blocked_count: number;
  unknown_count: number;
  risks: (
    | {
        kind: "package_core_requirement";
        state: "blocked" | "unknown";
        scope: {
          bid_id: string;
          package_id: string;
          revision_id: string;
          inventory_id: string;
        };
        run_id: string;
        frozen_input_id: string;
        execution_input_id: string;
        result_digest: string;
        row_digest: string;
        requirement_id: string;
        rule_digest: string;
        rule_kind: "disqualification" | "mandatory";
        verdict: "violated" | "not_found" | "unable_to_judge";
        statement: string;
        human_decision: {
          id: string;
          digest: string;
          state: "confirmed" | "rejected" | "needs_review";
          reason: string;
        } | null;
        resolution: "no_verified_package_recheck_resolution";
      }
    | {
        kind: "legacy_finding";
        state: "blocked";
        finding: {
          id: string;
          bid_id: string;
          origin_id: string;
          review_id: string;
          rule_id: string | null;
          rule_kind:
            | "mandatory"
            | "disqualification"
            | "scoring"
            | "advisory"
            | null;
          severity: "critical" | "major" | "minor" | "info";
          category:
            | "disqualification"
            | "response"
            | "consistency"
            | "scope"
            | "improvement";
          verdict:
            | "satisfied"
            | "violated"
            | "not_found"
            | "unable_to_judge"
            | "not_applicable";
          lifecycle: "open" | "deferred" | "dismissed";
          statement: string;
        };
        finding_digest: string;
        resolution: "no_verified_recheck_resolution";
      }
  )[];
};

export type AuthoringHistoryAuthoringText = {
  type: "text";
  text: string;
  marks?: {
    type: "bold" | "italic";
  }[];
};

export type AuthoringHistoryAuthoringBreak = {
  type: "hardBreak";
};

export type AuthoringHistoryAuthoringListItem = {
  type: "listItem";
  attrs: {
    id: string;
  };
  content: (
    | AuthoringHistoryAuthoringParagraph
    | AuthoringHistoryAuthoringBulletList
    | AuthoringHistoryAuthoringOrderedList
  )[];
};

export type AuthoringHistoryAuthoringRichCell = {
  type: "tableCell";
  attrs: {
    id: string;
    colspan: number;
    rowspan: number;
    header: boolean;
  };
  content: (
    | AuthoringHistoryAuthoringParagraph
    | AuthoringHistoryAuthoringBulletList
    | AuthoringHistoryAuthoringOrderedList
  )[];
};

export type WorkContextReadOnlyAuthoringText = {
  type: "text";
  text: string;
  marks?: {
    type: "bold" | "italic";
  }[];
};

export type WorkContextReadOnlyAuthoringBreak = {
  type: "hardBreak";
};

export type WorkContextReadOnlyAuthoringListItem = {
  type: "listItem";
  attrs: {
    id: string;
  };
  content: (
    | WorkContextReadOnlyAuthoringParagraph
    | WorkContextReadOnlyAuthoringBulletList
    | WorkContextReadOnlyAuthoringOrderedList
  )[];
};

export type WorkContextReadOnlyAuthoringRichCell = {
  type: "tableCell";
  attrs: {
    id: string;
    colspan: number;
    rowspan: number;
    header: boolean;
  };
  content: (
    | WorkContextReadOnlyAuthoringParagraph
    | WorkContextReadOnlyAuthoringBulletList
    | WorkContextReadOnlyAuthoringOrderedList
  )[];
};

export type PackageDependencyPlan_Assessment_Manifest =
  | PackageDependencyPlan_Assessment_ManifestV1
  | PackageDependencyPlan_Assessment_ManifestV2;

export type PackageDependencyPlan_Usage_Manifest = {
  version: "package-fact-usage/1";
  kind: "fact_usage_selection";
  purpose: "prebid_compliance";
  prepared: PackageDependencyPlan_Usage_Prepared;
  identity_digest: PackageDependencyPlan_Usage_Digest;
  selected: PackageDependencyPlan_Usage_Selected[];
  selection_digest: PackageDependencyPlan_Usage_Digest;
  selected_facts_digest: PackageDependencyPlan_Usage_Digest;
  required_facts_assessment: "not_performed";
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
};

export type PackageDependencyPlan_Usage_Digest = string;

export type PackageInputDependencies_Prepared = {
  bid_id: PackageInputDependencies_Id;
  package_id: PackageInputDependencies_Id;
  revision_id: PackageInputDependencies_Id;
  inventory_id: PackageInputDependencies_Id;
  frozen_input_id: PackageInputDependencies_Id;
  execution_input_id: PackageInputDependencies_Id;
  execution_input_digest: PackageInputDependencies_Digest;
};

export type PackageInputDependencies_RequirementAssessment = {
  requirement_id: PackageInputDependencies_Id;
  requirement_digest: PackageInputDependencies_Digest;
  declaration: PackageInputDependencies_Dependency | null;
  fact_status: "unknown" | "missing" | "selected_unvalidated" | "not_used";
  unselected_fact_ids: PackageInputDependencies_Id[];
  coverage_state:
    | "not_provided"
    | "missing"
    | "pending_parse"
    | "parse_gap"
    | "unsupported"
    | "verified"
    | "not_applicable"
    | "conflict"
    | "unknown";
  source_bound: boolean;
  applicability: "applicable" | "unknown" | "not_applicable";
};

export type PackageInputDependencies_DerivedRequirementAssessment = {
  requirement_id: PackageInputDependencies_Id;
  requirement_digest: PackageInputDependencies_Digest;
  declaration: PackageInputDependencies_Dependency | null;
  fact_status: "unknown" | "missing" | "selected_unvalidated" | "not_used";
  unselected_fact_ids: PackageInputDependencies_Id[];
  coverage_state:
    | "not_provided"
    | "missing"
    | "pending_parse"
    | "parse_gap"
    | "unsupported"
    | "verified"
    | "not_applicable"
    | "conflict"
    | "unknown";
  source_bound: boolean;
  applicability: "applicable" | "unknown" | "not_applicable";
  rule_status: "active" | "inactive" | "needs_revalidation";
};

export type PackageDependencyPlan_Assessment_ManifestV1 = {
  version: "package-input-dependencies/1";
  kind: "input_dependency_assessment";
  purpose: "prebid_compliance";
  prepared: PackageDependencyPlan_Assessment_Prepared;
  frozen_digest: PackageDependencyPlan_Assessment_Digest;
  inventory_digest: PackageDependencyPlan_Assessment_Digest;
  usage_digest: PackageDependencyPlan_Assessment_Digest;
  selected_fact_count: number;
  requirement_count: number;
  dependency_review_status: "incomplete" | "declared";
  required_facts_assessment:
    | "unknown"
    | "missing"
    | "selected_unvalidated"
    | "not_used";
  requirements: PackageDependencyPlan_Assessment_RequirementAssessment[];
  inventory_status: "unproven" | "range_submitted_quality_unmeasured";
  declaration_kind: "human_dependency_annotation";
  inventory_complete: false;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  policy_digest: PackageDependencyPlan_Assessment_Digest;
};

export type PackageDependencyPlan_Assessment_ManifestV2 = {
  version: "package-input-dependencies/2";
  kind: "input_dependency_assessment";
  purpose: "prebid_compliance";
  prepared: PackageDependencyPlan_Assessment_Prepared;
  frozen_digest: PackageDependencyPlan_Assessment_Digest;
  inventory_digest: PackageDependencyPlan_Assessment_Digest;
  usage_digest: PackageDependencyPlan_Assessment_Digest;
  selected_fact_count: number;
  requirement_count: number;
  dependency_review_status: "incomplete" | "declared";
  required_facts_assessment:
    | "unknown"
    | "missing"
    | "selected_unvalidated"
    | "not_used";
  requirements: PackageDependencyPlan_Assessment_DerivedRequirementAssessment[];
  inventory_status: "human_derivation_range_quality_unmeasured";
  declaration_kind: "human_dependency_annotation";
  inventory_complete: false;
  original_bytes_verified: false;
  facts_qualified: false;
  review_ready: false;
  launch_available: false;
  publication_authorized: false;
  policy_digest: PackageDependencyPlan_Assessment_Digest;
  rule_state_counts: {
    total: number;
    active: number;
    inactive: number;
    needs_revalidation: number;
  };
};

export type PackageDependencyPlan_Usage_Prepared = {
  bid_id: PackageDependencyPlan_Usage_Id;
  package_id: PackageDependencyPlan_Usage_Id;
  revision_id: PackageDependencyPlan_Usage_Id;
  inventory_id: PackageDependencyPlan_Usage_Id;
  frozen_input_id: PackageDependencyPlan_Usage_Id;
  execution_input_id: PackageDependencyPlan_Usage_Id;
  execution_input_digest: PackageDependencyPlan_Usage_Digest;
};

export type PackageDependencyPlan_Usage_Selected = {
  fact_id: PackageDependencyPlan_Usage_Id;
  fact_item_digest: PackageDependencyPlan_Usage_Digest;
};

export type PackageDependencyPlan_Assessment_RequirementAssessment = {
  requirement_id: PackageDependencyPlan_Assessment_Id;
  requirement_digest: PackageDependencyPlan_Assessment_Digest;
  declaration: PackageDependencyPlan_Assessment_Dependency | null;
  fact_status: "unknown" | "missing" | "selected_unvalidated" | "not_used";
  unselected_fact_ids: PackageDependencyPlan_Assessment_Id[];
  coverage_state:
    | "not_provided"
    | "missing"
    | "pending_parse"
    | "parse_gap"
    | "unsupported"
    | "verified"
    | "not_applicable"
    | "conflict"
    | "unknown";
  source_bound: boolean;
  applicability: "applicable" | "unknown" | "not_applicable";
};

export type PackageDependencyPlan_Assessment_DerivedRequirementAssessment = {
  requirement_id: PackageDependencyPlan_Assessment_Id;
  requirement_digest: PackageDependencyPlan_Assessment_Digest;
  declaration: PackageDependencyPlan_Assessment_Dependency | null;
  fact_status: "unknown" | "missing" | "selected_unvalidated" | "not_used";
  unselected_fact_ids: PackageDependencyPlan_Assessment_Id[];
  coverage_state:
    | "not_provided"
    | "missing"
    | "pending_parse"
    | "parse_gap"
    | "unsupported"
    | "verified"
    | "not_applicable"
    | "conflict"
    | "unknown";
  source_bound: boolean;
  applicability: "applicable" | "unknown" | "not_applicable";
  rule_status: "active" | "inactive" | "needs_revalidation";
};

export type PackageDependencyPlan_Usage_Id = string;

export const implementedOperations: readonly string[] = [
  "GET /api/v1/project-work-summaries",
  "GET /api/v1/bids/{bid_id}/package-next-actions/{run_id}",
  "PUT /api/v1/object-transfers/uploads/{upload_id}",
  "GET /api/v1/object-transfers/versions/{version_id}",
  "POST /api/v1/retrievals",
  "GET /api/v1/reviews/{review_id}/content-checks",
  "POST /api/v1/bids/{bid_id}/reviews",
  "GET /api/v1/bids/{bid_id}/reviews",
  "GET /api/v1/bids/{bid_id}/review-state",
  "GET /api/v1/reviews/{review_id}",
  "GET /api/v1/reviews/{review_id}/manifest",
  "GET /api/v1/reviews/{review_id}/matrix",
  "GET /api/v1/reviews/{review_id}/findings",
  "GET /api/v1/bids/{bid_id}/rules",
  "GET /api/v1/rules/{rule_id}",
  "GET /api/v1/findings/{finding_id}",
  "GET /api/v1/evidence/{evidence_id}",
  "POST /api/v1/bids/{bid_id}/review-requests/{request_id}/cancel",
  "GET /api/v1/evidence/{evidence_id}/authoring-reference",
  "GET /api/v1/bids/{bid_id}/settings",
  "PATCH /api/v1/bids/{bid_id}/settings",
  "POST /api/v1/bids/{bid_id}/conversations/main",
  "GET /api/v1/bids/{bid_id}/conversations/main",
  "GET /api/v1/bids/{bid_id}/conversations/{conversation_id}",
  "POST /api/v1/bids/{bid_id}/conversations/{conversation_id}/state",
  "POST /api/v1/bids/{bid_id}/conversations/{conversation_id}/messages",
  "GET /api/v1/bids/{bid_id}/conversations/{conversation_id}/messages",
  "GET /api/v1/assistant/global-conversations/main",
  "POST /api/v1/assistant/global-conversations/main",
  "GET /api/v1/assistant/conversations",
  "POST /api/v1/assistant/global-conversations/{conversation_id}/state",
  "POST /api/v1/bids/{bid_id}/conversations/{conversation_id}/turns",
  "POST /api/v1/assistant/global-conversations/{conversation_id}/turns",
  "GET /api/v1/assistant/global-conversations/{conversation_id}/messages",
  "GET /api/v1/assistant/global-conversations/{conversation_id}/events",
  "GET /api/v1/assistant/sources",
  "GET /api/v1/assistant/jobs/{job_id}",
  "GET /api/v1/assistant/jobs",
  "POST /api/v1/assistant/jobs/{job_id}/cancel",
  "GET /api/v1/assistant/actions/{action_id}",
  "POST /api/v1/assistant/actions/{action_id}/resolve",
  "POST /api/v1/bids/{bid_id}/authoring/generations",
  "GET /api/v1/assistant/intent-capabilities",
  "GET /api/v1/assistant/intent-targets",
  "POST /api/v1/bids/{bid_id}/comparisons",
  "GET /api/v1/bids/{bid_id}/comparisons",
  "GET /api/v1/comparisons/{comparison_id}",
  "GET /api/v1/authoring/capabilities",
  "POST /api/v1/bids/{bid_id}/drafts",
  "GET /api/v1/bids/{bid_id}/drafts",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}",
  "PATCH /api/v1/bids/{bid_id}/drafts/{draft_id}",
  "GET /api/v1/sections/{section_id}",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/sections",
  "GET /api/v1/bids/{bid_id}/draft-snapshots/{snapshot_id}",
  "POST /api/v1/bids/{bid_id}/builds",
  "GET /api/v1/bids/{bid_id}/builds",
  "GET /api/v1/builds/{build_id}",
  "POST /api/v1/bids/{bid_id}/sections/{section_id}/patch-previews",
  "POST /api/v1/bids/{bid_id}/authoring-actions/{action_id}/apply",
  "GET /api/v1/sections/{section_id}/revisions",
  "POST /api/v1/bids/{bid_id}/sections/{section_id}/restore",
  "GET /api/v1/authoring/exact-revision-capabilities",
  "GET /api/v1/bids/{bid_id}/authoring/drafts/{draft_id}/exact-qualification",
  "GET /api/v1/bids/{bid_id}/authoring/section-revisions/{revision_id}/exact-qualification",
  "GET /api/v1/authoring/exact-text-edit-capabilities",
  "POST /api/v1/bids/{bid_id}/authoring/drafts/{draft_id}/exact-text-edits",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/sections/{section_id}/revisions/{revision}",
  "GET /api/v1/bids/{bid_id}/authoring/input-catalog/draft-snapshots/{snapshot_id}/sections/{section_id}/nodes",
  "GET /api/v1/bids/{bid_id}/authoring/input-catalog/fact-sets",
  "GET /api/v1/bids/{bid_id}/authoring/input-catalog/fact-sets/{fact_set_id}/facts",
  "POST /api/v1/bids/{bid_id}/builds/{build_id}/package-adoptions",
  "GET /api/v1/bids/{bid_id}/documents/{document_version_id}/parse-context",
  "POST /api/v1/bids/{bid_id}/documents/{document_version_id}/parse-requests",
  "GET /api/v1/bids/{bid_id}/documents/{document_version_id}/parse-requests",
  "GET /api/v1/bids/{bid_id}/documents/{document_version_id}/parse-requests/{request_id}",
  "GET /api/v1/research/capabilities",
  "GET /api/v1/history",
  "POST /api/v1/research/import-previews",
  "GET /api/v1/research/imports",
  "GET /api/v1/research/imports/{batch_id}",
  "GET /api/v1/research/imports/{batch_id}/source",
  "POST /api/v1/research/imports/{batch_id}/confirm",
  "GET /api/v1/bids/{bid_id}/outcomes",
  "POST /api/v1/bids/{bid_id}/outcomes",
  "GET /api/v1/bids/{bid_id}/outcome-context",
  "GET /api/v1/outcomes/{outcome_id}",
  "POST /api/v1/outcomes/{outcome_id}/corrections",
  "POST /api/v1/outcomes/{outcome_id}/verification",
  "POST /api/v1/bids/{bid_id}/submissions/{submission_id}/sample-admission",
  "GET /api/v1/research/samples",
  "GET /api/v1/research/samples/{sample_id}/grouping",
  "POST /api/v1/research/samples/{sample_id}/grouping",
  "POST /api/v1/research/datasets",
  "POST /api/v1/research/reviews/{review_id}/chapter-packages",
  "POST /api/v1/research/previews",
  "POST /api/v1/research/runs",
  "GET /api/v1/research/runs/{run_id}",
  "GET /api/v1/research/runs/{run_id}/items",
  "POST /api/v1/research/runs/{run_id}/resume",
  "POST /api/v1/research/runs/{run_id}/cancel",
  "GET /api/v1/streams/{stream_id}/events",
  "GET /api/v1/bids/{bid_id}/facts",
  "POST /api/v1/bids/{bid_id}/facts",
  "GET /api/v1/facts/{fact_id}",
  "POST /api/v1/facts/{fact_id}/decisions",
  "POST /api/v1/facts/{fact_id}/withdrawals",
  "POST /api/v1/rules/{rule_id}/decisions",
  "POST /api/v1/findings/{finding_id}/decisions",
  "POST /api/v1/bids/{bid_id}/rule-set-corrections",
  "POST /api/v1/bids/{bid_id}/rules/decisions",
  "POST /api/v1/knowledge",
  "GET /api/v1/knowledge",
  "GET /api/v1/knowledge/{knowledge_id}",
  "POST /api/v1/knowledge/{knowledge_id}/versions",
  "GET /api/v1/knowledge/{knowledge_id}/versions",
  "POST /api/v1/knowledge/{knowledge_id}/submit",
  "POST /api/v1/knowledge/{knowledge_id}/publish",
  "POST /api/v1/knowledge/{knowledge_id}/withdraw",
  "GET /api/v1/knowledge/{knowledge_id}/versions/{version_id}",
  "GET /api/v1/knowledge/{knowledge_id}/impacts",
  "POST /api/v1/knowledge/{knowledge_id}/references",
  "GET /api/v1/bids/{bid_id}/knowledge-reference-targets",
  "GET /api/v1/knowledge-references/{citation_id}",
  "GET /api/v1/knowledge/{knowledge_id}/source-positions",
  "POST /api/v1/bids/{bid_id}/knowledge-retrievals",
  "GET /api/v1/knowledge-retrievals/{trace_id}",
  "POST /api/v1/knowledge-retrievals/{trace_id}/references",
  "GET /api/v1/knowledge-unit-references/{citation_id}",
  "GET /api/v1/knowledge/{knowledge_id}/indexes",
  "POST /api/v1/knowledge/{knowledge_id}/indexes",
  "GET /api/v1/bids/{bid_id}/source-effectivity",
  "POST /api/v1/bids/{bid_id}/source-effectivity-decisions",
  "PUT /api/v1/object-transfers/multipart/{upload_id}/parts/{part_number}",
  "GET /api/v1/bids/{bid_id}/upload-batches",
  "POST /api/v1/bids/{bid_id}/upload-batches",
  "GET /api/v1/uploads/{upload_id}/layout",
  "GET /api/v1/identity/bidders",
  "POST /api/v1/identity/bidders",
  "GET /api/v1/identity/default-bidder",
  "PUT /api/v1/identity/default-bidder",
  "GET /api/v1/identity/engineering-projects",
  "POST /api/v1/identity/engineering-projects",
  "GET /api/v1/identity/rounds",
  "POST /api/v1/identity/rounds",
  "GET /api/v1/identity/lots",
  "POST /api/v1/identity/lots",
  "GET /api/v1/bids/{bid_id}/identity",
  "PUT /api/v1/bids/{bid_id}/identity",
  "POST /api/v1/bids/{bid_id}/packages",
  "GET /api/v1/bids/{bid_id}/packages",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/manifest",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/evidence",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-check",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-check",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-scope-declarations",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/fact-scope-declarations/{declaration_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/facts/{fact_id}/scope-declaration",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/facts",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/fact-confirmations",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/fact-withdrawals",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/fact-changes/{command_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/fact-context",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/facts/{fact_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-check",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-plans",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-plans",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-plans/{plan_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/input",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/human-decisions",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/requirements/{requirement_id}/human-decisions",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/requirements/{requirement_id}/human-decisions",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/report-context",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/report-exports",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/report-exports",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}/report-exports/{export_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts/{attempt_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/review-input-preview",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/review-original-verification",
  "GET /api/v1/bids/{bid_id}/package-review-comparisons",
  "GET /api/v1/bids/{bid_id}/package-documents",
  "GET /api/v1/bids/{bid_id}/package-documents/{document_version_id}/parses",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scope-context",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scope-previews",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/scoring-context",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/sample-context",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/execution-context",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/executions",
  "GET /api/v1/bids/{bid_id}/pricing-context",
  "GET /api/v1/bids/{bid_id}/pricing-formula-sources",
  "POST /api/v1/bids/{bid_id}/pricing-formulas",
  "GET /api/v1/bids/{bid_id}/pricing-formulas",
  "GET /api/v1/bids/{bid_id}/pricing-formulas/{formula_version_id}",
  "POST /api/v1/bids/{bid_id}/pricing-simulations",
  "GET /api/v1/bids/{bid_id}/pricing-simulations/{simulation_id}",
  "POST /api/v1/bids/{bid_id}/pricing-plans",
  "GET /api/v1/bids/{bid_id}/pricing-plans",
  "GET /api/v1/bids/{bid_id}/pricing-plans/{plan_id}",
  "GET /api/v1/bids/{bid_id}/package-pricing-context",
  "GET /api/v1/bids/{bid_id}/package-pricing-formula-sources",
  "POST /api/v1/bids/{bid_id}/package-pricing-formulas",
  "GET /api/v1/bids/{bid_id}/submission-gate",
  "POST /api/v1/bids/{bid_id}/submissions",
  "GET /api/v1/bids/{bid_id}/submissions",
  "POST /api/v1/bids/{bid_id}/submission-facts",
  "POST /api/v1/submissions/{submission_id}/corrections",
  "GET /api/v1/submissions/{submission_id}",
  "GET /api/v1/bids/{bid_id}/submission-documents",
  "GET /api/v1/bids/{bid_id}/package-retrospectives/choices",
  "POST /api/v1/bids/{bid_id}/package-retrospectives/preview",
  "POST /api/v1/bids/{bid_id}/package-retrospectives",
  "GET /api/v1/bids/{bid_id}/package-retrospectives",
  "GET /api/v1/bids/{bid_id}/package-retrospectives/{retrospective_id}",
  "POST /api/v1/bids/{bid_id}/package-retrospectives/{retrospective_id}/knowledge-candidate",
  "GET /api/v1/bids/{bid_id}/work-contexts/package_review_run/{run_id}",
  "GET /api/v1/bids/{bid_id}/work-contexts/package_submission/{submission_id}",
  "GET /api/v1/bids/{bid_id}/work-contexts/build/{build_id}/relations",
  "GET /api/v1/bids/{bid_id}/work-contexts/choices",
  "GET /api/v1/bids/{bid_id}/work-contexts/draft_snapshot/{snapshot_id}",
  "GET /api/v1/bids/{bid_id}/work-contexts/build/{build_id}",
  "GET /api/v1/authoring/package-input-capabilities",
  "POST /api/v1/bids/{bid_id}/authoring/package-inputs",
  "GET /api/v1/bids/{bid_id}/authoring/package-inputs",
  "GET /api/v1/bids/{bid_id}/authoring/package-inputs/{input_id}",
  "GET /api/v1/bids/{bid_id}/authoring/package-inputs/{input_id}/context",
  "POST /api/v1/bids/{bid_id}/authoring/package-inputs/{input_id}/check",
  "POST /api/v1/bids/{bid_id}/authoring/package-inputs/{input_id}/fact-withdrawals",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/historical-admission-context",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}/historical-admissions",
  "GET /api/v1/package-historical-research/admissions/{admission_id}",
  "GET /api/v1/package-historical-research/cpu-protocol-template",
  "POST /api/v1/package-historical-research/protocols",
  "GET /api/v1/package-historical-research/protocols",
  "POST /api/v1/package-historical-research/cohorts",
  "GET /api/v1/package-historical-research/cohorts",
  "GET /api/v1/package-historical-research/cohorts/{cohort_id}",
  "POST /api/v1/package-historical-research/cohorts/{cohort_id}/jobs",
  "GET /api/v1/package-historical-research/cohorts/{cohort_id}/jobs",
  "GET /api/v1/package-historical-research/jobs/{job_id}",
  "POST /api/v1/package-historical-research/jobs/{job_id}/control",
  "GET /api/v1/package-historical-research/admissions",
  "GET /api/v1/reviews/{review_id}/report-exports",
  "POST /api/v1/reviews/{review_id}/report-exports",
  "GET /api/v1/reviews/{review_id}/report-context",
  "GET /api/v1/report-exports/{report_id}",
  "GET /api/v1/bids/{bid_id}/submissions/{submission_id}/business-results",
  "POST /api/v1/bids/{bid_id}/submissions/{submission_id}/business-results",
  "GET /api/v1/business-results/{result_id}",
  "POST /api/v1/business-results/{result_id}/corrections",
  "POST /api/v1/business-results/{result_id}/verification-decisions",
  "GET /api/v1/metrics",
  "GET /api/v1/bids/{bid_id}/round-trends",
  "POST /api/v1/bids/{bid_id}/upload-batches/{batch_id}/retained-uploads",
  "GET /api/v1/bids/{bid_id}/task-definitions",
  "POST /api/v1/bids/{bid_id}/task-definitions",
  "GET /api/v1/bids/{bid_id}/task-definitions/{definition_id}",
  "PUT /api/v1/bids/{bid_id}/task-definitions/{definition_id}",
  "POST /api/v1/bids/{bid_id}/task-definitions/{definition_id}/pause",
  "GET /api/v1/bids/{bid_id}/task-definitions/{definition_id}/versions/{version_id}",
  "POST /api/v1/bids/{bid_id}/task-definitions/{definition_id}/runs",
  "GET /api/v1/bids/{bid_id}/task-runs/{run_id}",
  "GET /api/v1/bids/{bid_id}/task-runs",
  "GET /api/v1/bids/{bid_id}/task-notifications",
  "GET /api/v1/bids/{bid_id}/task-package-trigger-intents",
  "GET /api/v1/bids/{bid_id}/task-package-trigger-intents/{intent_id}",
  "POST /api/v1/bids/{bid_id}/task-package-trigger-intents/{intent_id}/cancel",
  "GET /api/v1/bids/{bid_id}/task-schedule-recoveries",
  "GET /api/v1/task-kinds",
  "GET /api/v1/bids/{bid_id}/word-originals",
  "GET /api/v1/bids/{bid_id}/word-originals/{version_id}",
  "POST /api/v1/bids/{bid_id}/word-originals/{version_id}/retry-conversion",
  "GET /api/v1/bids/{bid_id}/word-materials/{version_id}",
  "GET /api/v1/authoring/generation-batch-capabilities",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches/{batch_id}",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches/{batch_id}/candidates/{action_id}",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches/{batch_id}/retry",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches/{batch_id}/resolve",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/structure",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/structure/preview",
  "POST /api/v1/bids/{bid_id}/authoring-structure-actions/{action_id}/resolve",
  "PUT /api/v1/bids/{bid_id}/drafts/{draft_id}/sections/{section_id}/plan",
  "GET /api/v1/authoring/templates",
  "GET /api/v1/authoring/template-versions/{version_id}",
  "POST /api/v1/authoring/template-families",
  "POST /api/v1/authoring/template-families/{family_id}/versions",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/directory-template/preview",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/style-template/preview",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/structure/restore-preview",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/structure/history",
  "GET /api/v1/authoring/rich-capabilities",
  "POST /api/v1/bids/{bid_id}/authoring-images",
  "GET /api/v1/bids/{bid_id}/authoring-images",
  "GET /api/v1/bids/{bid_id}/authoring-image-uploads/{upload_id}",
  "GET /api/v1/bids/{bid_id}/authoring-images/{asset_id}",
  "GET /api/v1/bids/{bid_id}/authoring-images/{asset_id}/versions/{version_id}",
  "POST /api/v1/bids/{bid_id}/authoring-images/{asset_id}/withdraw",
  "GET /api/v1/bids/{bid_id}/authoring-images/{asset_id}/versions/{version_id}/bytes/{variant}",
  "GET /api/v1/authoring/word-import-capabilities",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports/{candidate_id}",
  "POST /api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports/{candidate_id}/resolve",
  "GET /api/v1/bids/{bid_id}/drafts/{draft_id}/word-imports/{candidate_id}/images/{image_key}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-corrections/preview",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-corrections",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-corrections",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-corrections/{correction_id}",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-correction-evidence",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/rule-correction-evidence/{evidence_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/submission-preview",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/submissions",
  "POST /api/v1/submissions/{submission_id}/package-corrections",
  "GET /api/v1/technical-scale-capabilities",
  "GET /api/v1/bids/{bid_id}/technical-scale-context",
  "POST /api/v1/bids/{bid_id}/technical-scales",
  "GET /api/v1/bids/{bid_id}/technical-scales",
  "GET /api/v1/technical-scales/{scale_id}",
  "POST /api/v1/technical-scales/{scale_id}/corrections",
  "POST /api/v1/technical-scales/{scale_id}/withdrawals",
  "GET /api/v1/bids/{bid_id}/lifecycle",
  "POST /api/v1/bids/{bid_id}/lifecycle",
  "GET /api/v1/bids/{bid_id}/upload-batches/{batch_id}/closure-state",
  "POST /api/v1/bids/{bid_id}/upload-batches/{batch_id}/close",
  "GET /api/v1/bids/{bid_id}/task-definition-drafts",
  "POST /api/v1/bids/{bid_id}/task-definition-drafts",
  "GET /api/v1/bids/{bid_id}/task-definition-drafts/{draft_id}",
  "PUT /api/v1/bids/{bid_id}/task-definition-drafts/{draft_id}",
  "POST /api/v1/bids/{bid_id}/task-definition-drafts/{draft_id}/save",
  "GET /api/v1/model-governance/capabilities",
  "POST /api/v1/model-governance/training-protocols",
  "GET /api/v1/model-governance/training-protocols/{protocol_id}",
  "POST /api/v1/model-governance/cohort-previews",
  "POST /api/v1/model-governance/cohorts",
  "GET /api/v1/model-governance/cohorts/{cohort_id}",
  "POST /api/v1/model-governance/training-jobs",
  "GET /api/v1/model-governance/jobs/{job_id}",
  "POST /api/v1/model-governance/evaluations",
  "GET /api/v1/historical-proof/capabilities",
  "GET /api/v1/historical-proof/submissions/{submission_id}/context",
  "POST /api/v1/historical-proof/subjects",
  "POST /api/v1/historical-proof/source-claims",
  "GET /api/v1/historical-proof/subjects/{subject_id}",
  "GET /api/v1/historical-proof/source-claims/{claim_id}",
  "POST /api/v1/historical-proof/subjects/{subject_id}/confirm",
  "POST /api/v1/historical-proof/source-claims/{claim_id}/confirm",
  "GET /api/v1/historical-inputs/capabilities",
  "GET /api/v1/historical-inputs/submissions/{submission_id}/context",
  "GET /api/v1/historical-inputs/{input_id}",
  "POST /api/v1/historical-inputs",
  "GET /api/v1/model-registry/capabilities",
  "GET /api/v1/model-registry/training-jobs/{training_job_id}/model-preview",
  "POST /api/v1/model-registry/models",
  "GET /api/v1/model-registry/models/{model_id}",
  "GET /api/v1/model-registry/routes/{lane}/{route_key}",
  "POST /api/v1/model-registry/routes/{lane}/{route_key}/changes",
  "GET /api/v1/scoring-capabilities",
  "GET /api/v1/bids/{bid_id}/score-context",
  "POST /api/v1/bids/{bid_id}/score-inputs",
  "GET /api/v1/score-inputs/{input_id}",
  "POST /api/v1/score-inputs/{input_id}/jobs",
  "GET /api/v1/score-jobs/{job_id}",
  "POST /api/v1/score-jobs/{job_id}/state",
  "GET /api/v1/score-jobs/{job_id}/result",
  "GET /api/v1/score-jobs/{job_id}/shadow-context",
  "POST /api/v1/score-jobs/{job_id}/shadows",
  "GET /api/v1/score-shadows/{shadow_id}",
  "GET /health/live",
  "GET /health/ready",
  "POST /api/v1/auth/login",
  "GET /api/v1/auth/session",
  "POST /api/v1/auth/logout",
  "POST /api/v1/bids",
  "GET /api/v1/bids",
  "GET /api/v1/bids/{bid_id}",
  "GET /api/v1/bids/{bid_id}/upload-batches/{batch_id}",
  "POST /api/v1/bids/{bid_id}/uploads",
  "GET /api/v1/uploads/{upload_id}",
  "POST /api/v1/uploads/{upload_id}/complete",
  "POST /api/v1/uploads/{upload_id}/bindings",
  "POST /api/v1/bids/{bid_id}/upload-batches/{batch_id}/commit",
  "GET /api/v1/bids/{bid_id}/materials",
  "GET /api/v1/operations/{operation_id}",
  "POST /api/v1/operations/{operation_id}/cancel",
  "GET /api/v1/documents/{document_version_id}",
  "GET /api/v1/documents/{document_version_id}/evidence",
  "GET /api/v1/artifacts/{artifact_id}/download",
  "GET /api/v1/uploads/{upload_id}/parts",
  "POST /api/v1/uploads/{upload_id}/authorizations",
  "POST /api/v1/uploads/{upload_id}/abort",
];

export const ruleConfirmationLimit: number = 500;

export const taskTemplatesContractReady: boolean = true;
