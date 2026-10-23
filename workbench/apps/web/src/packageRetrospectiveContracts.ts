// Generated from packages/contracts/package_retrospectives_api.py.
// Run python apps/web/scripts/generate-retrospective-contracts.py from workbench.

export type PackageRetrospectiveSelection = {
  submission_id: string;
  outcome_id: string | null;
  outcome_missing_reason: string | null;
  business_result_id: string | null;
  business_result_missing_reason: string | null;
  baseline_run_id: string | null;
  submitted_run_id: string | null;
  reviews_missing_reason: string | null;
};

export type PackageRetrospectiveNotes = {
  observations: string;
  hypotheses: string;
  next_actions: string;
  additional_missing_materials: string;
};

export type PackageRetrospectiveRequest = {
  selection: {
    submission_id: string;
    outcome_id: string | null;
    outcome_missing_reason: string | null;
    business_result_id: string | null;
    business_result_missing_reason: string | null;
    baseline_run_id: string | null;
    submitted_run_id: string | null;
    reviews_missing_reason: string | null;
  };
  preview_digest: string;
  title: string;
  notes: {
    observations: string;
    hypotheses: string;
    next_actions: string;
    additional_missing_materials: string;
  };
};

export type PackageRetrospectiveKnowledgeRequest = {
  retrospective_digest: string;
  reason: string;
};

export type PackageRetrospectivePreview = {
  manifest: {
    version: "package-retrospective-preview/1";
    bid_id: string;
    selection: {
      submission_id: string;
      outcome_id: string | null;
      outcome_missing_reason: string | null;
      business_result_id: string | null;
      business_result_missing_reason: string | null;
      baseline_run_id: string | null;
      submitted_run_id: string | null;
      reviews_missing_reason: string | null;
    };
    submission: {
      id: string;
      package_id: string;
      revision_id: string;
      package_digest: string;
      binding_digest: string;
      identity: HistoricalBidIdentitySnapshot;
      kind: "standard" | "offline_fact";
      submitted_at: string;
      recorded_at: string;
      current: boolean;
      registration_risk_digest: string;
      registration_assessed_at: string;
      risk_resolution_assessed: false;
    };
    outcome: {
      id: string;
      submission_id: string;
      score_kind: "technical_total" | "overall_total" | "unknown";
      value: string | null;
      maximum: string | null;
      source_version_id: string;
      known_at: string;
      supersedes_id: string | null;
      verification: "pending" | "verified" | "conflict" | "rejected";
      verification_revision: number;
      verification_id: string | null;
      verification_details_digest: string | null;
      aggregation: string | null;
      published_at: string | null;
      evidence_refs: {
        document_version_id: string;
        evidence_id: string;
        physical_page: number;
        quote: string;
      }[];
      current: boolean;
      association_reasons: string[];
    } | null;
    business_result: {
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
    } | null;
    comparison: {
      manifest: PackageReviewComparisonManifest;
      digest: string;
    } | null;
    source_ids: string[];
    source_snapshot: {
      source_id: string;
      ancestor_id: string;
      document_version_id: string | null;
      document_bid_id: string | null;
      kind:
        | "document"
        | "knowledge"
        | "summary"
        | "feature"
        | "label"
        | "model";
      policy_class:
        | "prebid_content"
        | "official_label"
        | "post_outcome"
        | "derived_mixed";
      known_at: string;
      digest: string;
      revision: number | null;
      status: null | "candidate" | "published" | "withdrawn";
      valid_from: string | null;
      valid_until: string | null;
    }[];
    documents: {
      id: string;
      original_name: string;
      digest: string;
      byte_size: number;
    }[];
    gaps: {
      code: string;
      message: string;
    }[];
    timing: "post_outcome_retrospective";
    official_deduction_reasons_inferred: false;
    risk_resolution_assessed: false;
    formal_sample_eligible: false;
    model_qualification_granted: false;
    knowledge_published: false;
  };
  digest: string;
};

export type PackageRetrospectiveView = {
  manifest: {
    version: "package-retrospective/1";
    id: string;
    bid_id: string;
    actor_id: string;
    command_id: string;
    created_at: string;
    state: "pending_review";
    title: string;
    notes: {
      observations: string;
      hypotheses: string;
      next_actions: string;
      additional_missing_materials: string;
    };
    preview: {
      manifest: {
        version: "package-retrospective-preview/1";
        bid_id: string;
        selection: {
          submission_id: string;
          outcome_id: string | null;
          outcome_missing_reason: string | null;
          business_result_id: string | null;
          business_result_missing_reason: string | null;
          baseline_run_id: string | null;
          submitted_run_id: string | null;
          reviews_missing_reason: string | null;
        };
        submission: {
          id: string;
          package_id: string;
          revision_id: string;
          package_digest: string;
          binding_digest: string;
          identity: HistoricalBidIdentitySnapshot;
          kind: "standard" | "offline_fact";
          submitted_at: string;
          recorded_at: string;
          current: boolean;
          registration_risk_digest: string;
          registration_assessed_at: string;
          risk_resolution_assessed: false;
        };
        outcome: {
          id: string;
          submission_id: string;
          score_kind: "technical_total" | "overall_total" | "unknown";
          value: string | null;
          maximum: string | null;
          source_version_id: string;
          known_at: string;
          supersedes_id: string | null;
          verification: "pending" | "verified" | "conflict" | "rejected";
          verification_revision: number;
          verification_id: string | null;
          verification_details_digest: string | null;
          aggregation: string | null;
          published_at: string | null;
          evidence_refs: {
            document_version_id: string;
            evidence_id: string;
            physical_page: number;
            quote: string;
          }[];
          current: boolean;
          association_reasons: string[];
        } | null;
        business_result: {
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
        } | null;
        comparison: {
          manifest: PackageReviewComparisonManifest;
          digest: string;
        } | null;
        source_ids: string[];
        source_snapshot: {
          source_id: string;
          ancestor_id: string;
          document_version_id: string | null;
          document_bid_id: string | null;
          kind:
            | "document"
            | "knowledge"
            | "summary"
            | "feature"
            | "label"
            | "model";
          policy_class:
            | "prebid_content"
            | "official_label"
            | "post_outcome"
            | "derived_mixed";
          known_at: string;
          digest: string;
          revision: number | null;
          status: null | "candidate" | "published" | "withdrawn";
          valid_from: string | null;
          valid_until: string | null;
        }[];
        documents: {
          id: string;
          original_name: string;
          digest: string;
          byte_size: number;
        }[];
        gaps: {
          code: string;
          message: string;
        }[];
        timing: "post_outcome_retrospective";
        official_deduction_reasons_inferred: false;
        risk_resolution_assessed: false;
        formal_sample_eligible: false;
        model_qualification_granted: false;
        knowledge_published: false;
      };
      digest: string;
    };
    official_deduction_reasons_inferred: false;
    risk_resolution_assessed: false;
    formal_sample_eligible: false;
    model_qualification_granted: false;
    knowledge_published: false;
  };
  digest: string;
};

export type PackageRetrospectiveOrigin = {
  retrospective_id: string;
  retrospective_digest: string;
  preview_digest: string;
  source_id: string;
};

export type PackageRetrospectiveKnowledgeLink = {
  retrospective_id: string;
  retrospective_digest: string;
  knowledge_id: string;
  knowledge_version_id: string;
  source_id: string;
  created_at: string;
  actor_id: string;
  reason: string;
  policy_class: "derived_mixed";
  knowledge_published: false;
  formal_sample_eligible: false;
};

export type PackageRetrospectiveCurrent = {
  unchanged: boolean;
  issues: {
    code: string;
    message: string;
  }[];
};

export type PackageRetrospectiveApplied = {
  retrospective: {
    manifest: {
      version: "package-retrospective/1";
      id: string;
      bid_id: string;
      actor_id: string;
      command_id: string;
      created_at: string;
      state: "pending_review";
      title: string;
      notes: {
        observations: string;
        hypotheses: string;
        next_actions: string;
        additional_missing_materials: string;
      };
      preview: {
        manifest: {
          version: "package-retrospective-preview/1";
          bid_id: string;
          selection: {
            submission_id: string;
            outcome_id: string | null;
            outcome_missing_reason: string | null;
            business_result_id: string | null;
            business_result_missing_reason: string | null;
            baseline_run_id: string | null;
            submitted_run_id: string | null;
            reviews_missing_reason: string | null;
          };
          submission: {
            id: string;
            package_id: string;
            revision_id: string;
            package_digest: string;
            binding_digest: string;
            identity: HistoricalBidIdentitySnapshot;
            kind: "standard" | "offline_fact";
            submitted_at: string;
            recorded_at: string;
            current: boolean;
            registration_risk_digest: string;
            registration_assessed_at: string;
            risk_resolution_assessed: false;
          };
          outcome: {
            id: string;
            submission_id: string;
            score_kind: "technical_total" | "overall_total" | "unknown";
            value: string | null;
            maximum: string | null;
            source_version_id: string;
            known_at: string;
            supersedes_id: string | null;
            verification: "pending" | "verified" | "conflict" | "rejected";
            verification_revision: number;
            verification_id: string | null;
            verification_details_digest: string | null;
            aggregation: string | null;
            published_at: string | null;
            evidence_refs: {
              document_version_id: string;
              evidence_id: string;
              physical_page: number;
              quote: string;
            }[];
            current: boolean;
            association_reasons: string[];
          } | null;
          business_result: {
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
          } | null;
          comparison: {
            manifest: PackageReviewComparisonManifest;
            digest: string;
          } | null;
          source_ids: string[];
          source_snapshot: {
            source_id: string;
            ancestor_id: string;
            document_version_id: string | null;
            document_bid_id: string | null;
            kind:
              | "document"
              | "knowledge"
              | "summary"
              | "feature"
              | "label"
              | "model";
            policy_class:
              | "prebid_content"
              | "official_label"
              | "post_outcome"
              | "derived_mixed";
            known_at: string;
            digest: string;
            revision: number | null;
            status: null | "candidate" | "published" | "withdrawn";
            valid_from: string | null;
            valid_until: string | null;
          }[];
          documents: {
            id: string;
            original_name: string;
            digest: string;
            byte_size: number;
          }[];
          gaps: {
            code: string;
            message: string;
          }[];
          timing: "post_outcome_retrospective";
          official_deduction_reasons_inferred: false;
          risk_resolution_assessed: false;
          formal_sample_eligible: false;
          model_qualification_granted: false;
          knowledge_published: false;
        };
        digest: string;
      };
      official_deduction_reasons_inferred: false;
      risk_resolution_assessed: false;
      formal_sample_eligible: false;
      model_qualification_granted: false;
      knowledge_published: false;
    };
    digest: string;
  };
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request:
      | {
          selection: {
            submission_id: string;
            outcome_id: string | null;
            outcome_missing_reason: string | null;
            business_result_id: string | null;
            business_result_missing_reason: string | null;
            baseline_run_id: string | null;
            submitted_run_id: string | null;
            reviews_missing_reason: string | null;
          };
          preview_digest: string;
          title: string;
          notes: {
            observations: string;
            hypotheses: string;
            next_actions: string;
            additional_missing_materials: string;
          };
        }
      | {
          retrospective_digest: string;
          reason: string;
        };
    if_match: string;
  };
};

export type PackageRetrospectiveKnowledgeApplied = {
  link: {
    retrospective_id: string;
    retrospective_digest: string;
    knowledge_id: string;
    knowledge_version_id: string;
    source_id: string;
    created_at: string;
    actor_id: string;
    reason: string;
    policy_class: "derived_mixed";
    knowledge_published: false;
    formal_sample_eligible: false;
  };
  command: {
    command_id: string;
    actor_id: string;
    idempotency_key: string;
    request_digest: string;
    request:
      | {
          selection: {
            submission_id: string;
            outcome_id: string | null;
            outcome_missing_reason: string | null;
            business_result_id: string | null;
            business_result_missing_reason: string | null;
            baseline_run_id: string | null;
            submitted_run_id: string | null;
            reviews_missing_reason: string | null;
          };
          preview_digest: string;
          title: string;
          notes: {
            observations: string;
            hypotheses: string;
            next_actions: string;
            additional_missing_materials: string;
          };
        }
      | {
          retrospective_digest: string;
          reason: string;
        };
    if_match: string;
  };
};

export type PackageRetrospectiveDetail = {
  retrospective: {
    manifest: {
      version: "package-retrospective/1";
      id: string;
      bid_id: string;
      actor_id: string;
      command_id: string;
      created_at: string;
      state: "pending_review";
      title: string;
      notes: {
        observations: string;
        hypotheses: string;
        next_actions: string;
        additional_missing_materials: string;
      };
      preview: {
        manifest: {
          version: "package-retrospective-preview/1";
          bid_id: string;
          selection: {
            submission_id: string;
            outcome_id: string | null;
            outcome_missing_reason: string | null;
            business_result_id: string | null;
            business_result_missing_reason: string | null;
            baseline_run_id: string | null;
            submitted_run_id: string | null;
            reviews_missing_reason: string | null;
          };
          submission: {
            id: string;
            package_id: string;
            revision_id: string;
            package_digest: string;
            binding_digest: string;
            identity: HistoricalBidIdentitySnapshot;
            kind: "standard" | "offline_fact";
            submitted_at: string;
            recorded_at: string;
            current: boolean;
            registration_risk_digest: string;
            registration_assessed_at: string;
            risk_resolution_assessed: false;
          };
          outcome: {
            id: string;
            submission_id: string;
            score_kind: "technical_total" | "overall_total" | "unknown";
            value: string | null;
            maximum: string | null;
            source_version_id: string;
            known_at: string;
            supersedes_id: string | null;
            verification: "pending" | "verified" | "conflict" | "rejected";
            verification_revision: number;
            verification_id: string | null;
            verification_details_digest: string | null;
            aggregation: string | null;
            published_at: string | null;
            evidence_refs: {
              document_version_id: string;
              evidence_id: string;
              physical_page: number;
              quote: string;
            }[];
            current: boolean;
            association_reasons: string[];
          } | null;
          business_result: {
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
          } | null;
          comparison: {
            manifest: PackageReviewComparisonManifest;
            digest: string;
          } | null;
          source_ids: string[];
          source_snapshot: {
            source_id: string;
            ancestor_id: string;
            document_version_id: string | null;
            document_bid_id: string | null;
            kind:
              | "document"
              | "knowledge"
              | "summary"
              | "feature"
              | "label"
              | "model";
            policy_class:
              | "prebid_content"
              | "official_label"
              | "post_outcome"
              | "derived_mixed";
            known_at: string;
            digest: string;
            revision: number | null;
            status: null | "candidate" | "published" | "withdrawn";
            valid_from: string | null;
            valid_until: string | null;
          }[];
          documents: {
            id: string;
            original_name: string;
            digest: string;
            byte_size: number;
          }[];
          gaps: {
            code: string;
            message: string;
          }[];
          timing: "post_outcome_retrospective";
          official_deduction_reasons_inferred: false;
          risk_resolution_assessed: false;
          formal_sample_eligible: false;
          model_qualification_granted: false;
          knowledge_published: false;
        };
        digest: string;
      };
      official_deduction_reasons_inferred: false;
      risk_resolution_assessed: false;
      formal_sample_eligible: false;
      model_qualification_granted: false;
      knowledge_published: false;
    };
    digest: string;
  };
  current: {
    unchanged: boolean;
    issues: {
      code: string;
      message: string;
    }[];
  };
  knowledge_link: {
    retrospective_id: string;
    retrospective_digest: string;
    knowledge_id: string;
    knowledge_version_id: string;
    source_id: string;
    created_at: string;
    actor_id: string;
    reason: string;
    policy_class: "derived_mixed";
    knowledge_published: false;
    formal_sample_eligible: false;
  } | null;
};

export type PackageRetrospectivePage = {
  bid_id: string;
  items: {
    id: string;
    title: string;
    submission_id: string;
    created_at: string;
    digest: string;
  }[];
  next_offset: number | null;
};

export type PackageRetrospectiveChoices = {
  bid_id: string;
  kind: "submissions" | "outcomes" | "business_results" | "runs";
  submission_id: string | null;
  items: {
    id: string;
    label: string;
    current: boolean | null;
    package_id: string | null;
    revision_id: string | null;
  }[];
  next_offset: number | null;
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

export type PackageReviewComparisonManifest = {
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
  items: PackageReviewComparisonRow[];
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
