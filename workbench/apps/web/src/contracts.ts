// Generated from packages/contracts/fusion-implemented.openapi.json. Run python scripts/generate-contracts.py.

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
  source_selection?: SourceSelection;
  trigger?: Trigger;
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
    | "blocked"
    | "superseded"
    | "unknown"
    | "reconciliation_required";
  stage: "preparation" | "review" | "execution";
  frozen_manifest: { [key: string]: unknown };
  result: { [key: string]: unknown } | null;
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
  source_selection?: SourceSelection;
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

export type SubmissionView = {
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
  target_kind: "project" | "section" | "operation" | "review";
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
  verification_details: ResearchOutcomeVerification | null;
  current: boolean;
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
  before: AuthoringDocument;
  after: AuthoringDocument;
  expires_in_seconds: number;
};

export type AuthoringSnapshot = {
  snapshot_id: string;
  snapshot_digest: string;
  title: string;
  sections: AuthoringDocument[];
  authoring_structure?: AuthoringStructureExtension;
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
  content: AuthoringDocument;
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
  | {
      draft_id: string;
      draft_revision: number;
      template_version_id: string;
      formats: ("docx" | "pdf")[];
      follow_up: "none" | "review";
    }
  | AuthoringStructuredBuildRequest;

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
  follow_up: BuildFollowUpView;
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

export type AuthoringJsonValue =
  | null
  | boolean
  | number
  | string
  | AuthoringJsonValue[]
  | { [key: string]: AuthoringJsonValue };

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

export type Trigger = {
  mode?: "manual" | "material_updated" | "schedule";
  cron?: string | null;
  timezone?: string;
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
  source_selection: SourceSelection;
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

export type SubmissionDocumentView = {
  document_version_id: string;
  original_name: string;
  artifact_kind: string;
  digest: string;
  byte_size: number;
  media_type: string;
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

export type PricingApplicability = {
  applicable: boolean;
  reasons: string[];
};

export type PricingFormulaManifest = {
  schema: "pricing-formula/1";
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
  };
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
  target_kind: "project" | "section" | "operation" | "review";
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
  verification_details: ResearchOutcomeVerification | null;
};

export type ResearchOutcomeVerification = {
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
  content: AuthoringDocument;
};

export type AuthoringStructuredBuildRequest = {
  draft_id: string;
  draft_revision: number;
  directory_template_version_id: string;
  style_template_version_id: string;
  formats: ("docx" | "pdf")[];
  follow_up: "none" | "review";
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

export type PackageInputDependencies_Manifest = {
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
  run_current_once_ref: string;
  definition_version_id: string;
  next_fire_at: string;
  missed: MissedTaskSchedule | null;
  automatic_catchup_runs: 0;
};

export type TaskDraftUnresolvedField = {
  field: string;
  reason: string;
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

export type PackageDependencyPlan_Assessment_View = {
  manifest: PackageDependencyPlan_Assessment_Manifest;
  digest: PackageDependencyPlan_Assessment_Digest;
};

export type PackageDependencyPlan_Usage_View = {
  manifest: PackageDependencyPlan_Usage_Manifest;
  digest: PackageDependencyPlan_Usage_Digest;
};

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
  resolution: "skipped_run_current_once_available";
};

export type PackageDependencyPlan_Assessment_Manifest = {
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

export type PackageDependencyPlan_Usage_Id = string;

export const implementedOperations: readonly string[] = [
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
  "GET /api/v1/research/capabilities",
  "GET /api/v1/history",
  "POST /api/v1/research/import-previews",
  "GET /api/v1/research/imports/{batch_id}",
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
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts",
  "GET /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/coverage-attempts/{attempt_id}",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/review-input-preview",
  "POST /api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/review-original-verification",
  "GET /api/v1/bids/{bid_id}/package-documents",
  "GET /api/v1/bids/{bid_id}/package-documents/{document_version_id}/parses",
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
  "GET /api/v1/bids/{bid_id}/submission-gate",
  "POST /api/v1/bids/{bid_id}/submissions",
  "GET /api/v1/bids/{bid_id}/submissions",
  "POST /api/v1/bids/{bid_id}/submission-facts",
  "POST /api/v1/submissions/{submission_id}/corrections",
  "GET /api/v1/submissions/{submission_id}",
  "GET /api/v1/bids/{bid_id}/submission-documents",
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
  "GET /api/v1/bids/{bid_id}/task-schedule-recoveries",
  "GET /api/v1/task-kinds",
  "GET /api/v1/bids/{bid_id}/word-originals",
  "GET /api/v1/bids/{bid_id}/word-originals/{version_id}",
  "POST /api/v1/bids/{bid_id}/word-originals/{version_id}/retry-conversion",
  "GET /api/v1/bids/{bid_id}/word-materials/{version_id}",
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
