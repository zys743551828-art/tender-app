// Generated from packages/contracts/implemented.openapi.json. Run python scripts/generate-contracts.py.

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
  identity: {
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
  } | null;
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
    round_no: number;
    binding_status: "confirmed" | "pending";
    authority_id: string | null;
    digest: string;
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
    round_no: number;
    binding_status: "confirmed" | "pending";
    authority_id: string | null;
    digest: string;
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

export type BuildRequest = {
  draft_id: string;
  draft_revision: number;
  template_version_id: string;
  formats: ("docx" | "pdf")[];
  follow_up: "none" | "review";
};

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
  identity: Record<string, string>;
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
  round_no: number;
  binding_status: "confirmed" | "pending";
  authority_id: string | null;
  digest: string;
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

export type DocumentRelation = {
  source_document_version_id: string;
  kind: "user_declared_same_draft" | "controlled_render";
  verification: "unverified" | "verified" | "rejected";
  evidence_ids: string[];
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
  identity: {
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
  };
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

export const implementedOperations: readonly string[] = [
  "PUT /api/v1/object-transfers/uploads/{upload_id}",
  "GET /api/v1/object-transfers/versions/{version_id}",
  "POST /api/v1/retrievals",
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
  "GET /api/v1/identity/rounds",
  "GET /api/v1/bids/{bid_id}/identity",
  "PUT /api/v1/bids/{bid_id}/identity",
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
