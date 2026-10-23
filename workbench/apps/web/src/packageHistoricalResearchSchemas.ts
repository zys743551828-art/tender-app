// Generated from packages/contracts/fusion-implemented.openapi.json.gz. Run python scripts/generate-contracts.py.
export const historySchemas: Record<string, unknown> = {
  PackageHistoricalAdmissionContext: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema: {
        const: "package-historical-admission-context/1",
      },
      schema_configured: {
        type: "boolean",
      },
      scope_id: {
        type: "string",
        format: "uuid",
      },
      submission_id: {
        type: "string",
        format: "uuid",
      },
      outcome_id: {
        type: "string",
        format: "uuid",
      },
      context_digest: {
        anyOf: [
          {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          {
            type: "null",
          },
        ],
      },
      official_technical_value: {
        anyOf: [
          {
            type: "string",
            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
          },
          {
            type: "null",
          },
        ],
      },
      official_maximum: {
        anyOf: [
          {
            type: "string",
            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
          },
          {
            type: "null",
          },
        ],
      },
      historical_as_of: {
        anyOf: [
          {
            type: "string",
            format: "date-time",
          },
          {
            type: "null",
          },
        ],
      },
      scope_frozen_at: {
        anyOf: [
          {
            type: "string",
            format: "date-time",
          },
          {
            type: "null",
          },
        ],
      },
      label_known_at: {
        anyOf: [
          {
            type: "string",
            format: "date-time",
          },
          {
            type: "null",
          },
        ],
      },
      proofs: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          properties: {
            id: {
              type: "string",
              format: "uuid",
            },
            origin: {
              enum: ["synthetic", "external_evidence"],
            },
            adapter_id: {
              type: "string",
              format: "uuid",
            },
            verified_at: {
              type: "string",
              format: "date-time",
            },
            context_digest: {
              type: "string",
              pattern: "^[a-f0-9]{64}$",
            },
          },
          required: [
            "id",
            "origin",
            "adapter_id",
            "verified_at",
            "context_digest",
          ],
        },
      },
      blockers: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          properties: {
            code: {
              type: "string",
            },
            message: {
              type: "string",
            },
          },
          required: ["code", "message"],
        },
      },
      observed_at: {
        type: "string",
        format: "date-time",
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
      strict_prebid_eligible: {
        const: false,
      },
      online_metrics_eligible: {
        const: false,
      },
      formal_sample_created: {
        const: false,
      },
    },
    required: [
      "schema",
      "schema_configured",
      "scope_id",
      "submission_id",
      "outcome_id",
      "context_digest",
      "official_technical_value",
      "official_maximum",
      "historical_as_of",
      "scope_frozen_at",
      "label_known_at",
      "proofs",
      "blockers",
      "observed_at",
      "research_only",
      "formal_eligibility",
      "strict_prebid_eligible",
      "online_metrics_eligible",
      "formal_sample_created",
    ],
  },
  PackageHistoricalAdmission: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema: {
        const: "package-historical-research-admission/1",
      },
      id: {
        type: "string",
        format: "uuid",
      },
      proof_id: {
        type: "string",
        format: "uuid",
      },
      bid_id: {
        type: "string",
        format: "uuid",
      },
      scope_id: {
        type: "string",
        format: "uuid",
      },
      submission_id: {
        type: "string",
        format: "uuid",
      },
      outcome_id: {
        type: "string",
        format: "uuid",
      },
      scope_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      submission_binding_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      context_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      proof_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      origin: {
        enum: ["synthetic", "external_evidence"],
      },
      state: {
        enum: ["mechanism_candidate", "retrospective_candidate"],
      },
      historical_as_of: {
        type: "string",
        format: "date-time",
      },
      scope_frozen_at: {
        type: "string",
        format: "date-time",
      },
      label_known_at: {
        type: "string",
        format: "date-time",
      },
      evidence_verified_at: {
        type: "string",
        format: "date-time",
      },
      admitted_at: {
        type: "string",
        format: "date-time",
      },
      official_technical_value: {
        type: "string",
        pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
      },
      technical_maximum: {
        type: "string",
        pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
      },
      aggregation: {
        const: "published_final_technical_total",
      },
      training_selected: {
        const: false,
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
      strict_prebid_eligible: {
        const: false,
      },
      online_metrics_eligible: {
        const: false,
      },
      formal_sample_created: {
        const: false,
      },
    },
    required: [
      "schema",
      "id",
      "proof_id",
      "bid_id",
      "scope_id",
      "submission_id",
      "outcome_id",
      "scope_digest",
      "submission_binding_digest",
      "context_digest",
      "proof_digest",
      "digest",
      "origin",
      "state",
      "historical_as_of",
      "scope_frozen_at",
      "label_known_at",
      "evidence_verified_at",
      "admitted_at",
      "official_technical_value",
      "technical_maximum",
      "aggregation",
      "training_selected",
      "research_only",
      "formal_eligibility",
      "strict_prebid_eligible",
      "online_metrics_eligible",
      "formal_sample_created",
    ],
  },
  PackageHistoricalAdmissionView: {
    type: "object",
    additionalProperties: false,
    properties: {
      admission: {
        type: "object",
        additionalProperties: false,
        properties: {
          schema: {
            const: "package-historical-research-admission/1",
          },
          id: {
            type: "string",
            format: "uuid",
          },
          proof_id: {
            type: "string",
            format: "uuid",
          },
          bid_id: {
            type: "string",
            format: "uuid",
          },
          scope_id: {
            type: "string",
            format: "uuid",
          },
          submission_id: {
            type: "string",
            format: "uuid",
          },
          outcome_id: {
            type: "string",
            format: "uuid",
          },
          scope_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          submission_binding_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          context_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          proof_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          origin: {
            enum: ["synthetic", "external_evidence"],
          },
          state: {
            enum: ["mechanism_candidate", "retrospective_candidate"],
          },
          historical_as_of: {
            type: "string",
            format: "date-time",
          },
          scope_frozen_at: {
            type: "string",
            format: "date-time",
          },
          label_known_at: {
            type: "string",
            format: "date-time",
          },
          evidence_verified_at: {
            type: "string",
            format: "date-time",
          },
          admitted_at: {
            type: "string",
            format: "date-time",
          },
          official_technical_value: {
            type: "string",
            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
          },
          technical_maximum: {
            type: "string",
            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
          },
          aggregation: {
            const: "published_final_technical_total",
          },
          training_selected: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          strict_prebid_eligible: {
            const: false,
          },
          online_metrics_eligible: {
            const: false,
          },
          formal_sample_created: {
            const: false,
          },
        },
        required: [
          "schema",
          "id",
          "proof_id",
          "bid_id",
          "scope_id",
          "submission_id",
          "outcome_id",
          "scope_digest",
          "submission_binding_digest",
          "context_digest",
          "proof_digest",
          "digest",
          "origin",
          "state",
          "historical_as_of",
          "scope_frozen_at",
          "label_known_at",
          "evidence_verified_at",
          "admitted_at",
          "official_technical_value",
          "technical_maximum",
          "aggregation",
          "training_selected",
          "research_only",
          "formal_eligibility",
          "strict_prebid_eligible",
          "online_metrics_eligible",
          "formal_sample_created",
        ],
      },
      current: {
        type: "boolean",
      },
    },
    required: ["admission", "current"],
  },
  PackageHistoricalProtocol: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: {
        type: "string",
        format: "uuid",
      },
      document: {
        type: "object",
        additionalProperties: false,
        properties: {
          schema: {
            const: "package-history-cpu-protocol/1",
          },
          method: {
            type: "object",
            additionalProperties: false,
            properties: {
              version: {
                const: "package-history-project-baselines/1",
              },
              purpose: {
                const: "retrospective_research",
              },
              features: {
                const: "not_required_by_constant_baselines",
              },
              provider_requests: {
                const: 0,
              },
              digest: {
                type: "string",
                pattern: "^[a-f0-9]{64}$",
              },
              sources: {
                type: "object",
                additionalProperties: false,
                properties: {
                  "packages/model_governance/package_history_cpu.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/common.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/evaluation.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/statistics.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                },
                required: [
                  "packages/model_governance/package_history_cpu.py",
                  "packages/model_governance/common.py",
                  "packages/model_governance/evaluation.py",
                  "packages/model_governance/statistics.py",
                ],
              },
            },
            required: [
              "version",
              "purpose",
              "features",
              "provider_requests",
              "digest",
              "sources",
            ],
          },
          families: {
            const: ["mean", "median"],
          },
          selection_metric: {
            const: "project_mae",
          },
          tie_order: {
            const: ["mean", "median"],
          },
          refit_with_development: {
            const: false,
          },
          interval_levels: {
            const: [0.8, 0.9],
          },
          group_spanning_policy: {
            const: "exclude",
          },
          seed: {
            type: "integer",
            minimum: 0,
            maximum: 2147483647,
          },
          bootstrap_iterations: {
            type: "integer",
            minimum: 100,
            maximum: 10000,
          },
        },
        required: [
          "schema",
          "method",
          "families",
          "selection_metric",
          "tie_order",
          "refit_with_development",
          "interval_levels",
          "group_spanning_policy",
          "seed",
          "bootstrap_iterations",
        ],
      },
      digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
    },
    required: [
      "id",
      "document",
      "digest",
      "research_only",
      "formal_eligibility",
    ],
  },
  PackageHistoricalProtocolTemplate: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_configured: {
        type: "boolean",
      },
      document: {
        type: "object",
        additionalProperties: false,
        properties: {
          schema: {
            const: "package-history-cpu-protocol/1",
          },
          method: {
            type: "object",
            additionalProperties: false,
            properties: {
              version: {
                const: "package-history-project-baselines/1",
              },
              purpose: {
                const: "retrospective_research",
              },
              features: {
                const: "not_required_by_constant_baselines",
              },
              provider_requests: {
                const: 0,
              },
              digest: {
                type: "string",
                pattern: "^[a-f0-9]{64}$",
              },
              sources: {
                type: "object",
                additionalProperties: false,
                properties: {
                  "packages/model_governance/package_history_cpu.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/common.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/evaluation.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  "packages/model_governance/statistics.py": {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                },
                required: [
                  "packages/model_governance/package_history_cpu.py",
                  "packages/model_governance/common.py",
                  "packages/model_governance/evaluation.py",
                  "packages/model_governance/statistics.py",
                ],
              },
            },
            required: [
              "version",
              "purpose",
              "features",
              "provider_requests",
              "digest",
              "sources",
            ],
          },
          families: {
            const: ["mean", "median"],
          },
          selection_metric: {
            const: "project_mae",
          },
          tie_order: {
            const: ["mean", "median"],
          },
          refit_with_development: {
            const: false,
          },
          interval_levels: {
            const: [0.8, 0.9],
          },
          group_spanning_policy: {
            const: "exclude",
          },
          seed: {
            type: "integer",
            minimum: 0,
            maximum: 2147483647,
          },
          bootstrap_iterations: {
            type: "integer",
            minimum: 100,
            maximum: 10000,
          },
        },
        required: [
          "schema",
          "method",
          "families",
          "selection_metric",
          "tie_order",
          "refit_with_development",
          "interval_levels",
          "group_spanning_policy",
          "seed",
          "bootstrap_iterations",
        ],
      },
      method_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      signed_proof_public_upload: {
        const: false,
      },
      feature_calibration_available: {
        const: false,
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
    },
    required: [
      "schema_configured",
      "document",
      "method_digest",
      "signed_proof_public_upload",
      "feature_calibration_available",
      "research_only",
      "formal_eligibility",
    ],
  },
  PackageHistoricalCohort: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema: {
        const: "package-history-cohort/1",
      },
      id: {
        type: "string",
        format: "uuid",
      },
      protocol_id: {
        type: "string",
        format: "uuid",
      },
      protocol_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      origin: {
        enum: ["synthetic", "external_evidence"],
      },
      timing: {
        type: "object",
        additionalProperties: false,
        properties: {
          mode: {
            const: "retrospective_submission_time_holdout",
          },
          historical_as_of: {
            const: "per_exact_actual_submission",
          },
          submission_split_at: {
            type: "string",
            format: "date-time",
          },
          label_available_as_of: {
            type: "string",
            format: "date-time",
          },
          training_frozen_at: {
            type: "string",
            format: "date-time",
          },
          group_spanning_policy: {
            const: "exclude",
          },
          prediction_timing: {
            const: "retrospective",
          },
        },
        required: [
          "mode",
          "historical_as_of",
          "submission_split_at",
          "label_available_as_of",
          "training_frozen_at",
          "group_spanning_policy",
          "prediction_timing",
        ],
      },
      members: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          properties: {
            admission_id: {
              type: "string",
              format: "uuid",
            },
            proof_id: {
              type: "string",
              format: "uuid",
            },
            submission_id: {
              type: "string",
              format: "uuid",
            },
            group_id: {
              type: "string",
              format: "uuid",
            },
            closure_ids: {
              type: "array",
              items: {
                type: "string",
                format: "uuid",
              },
              minItems: 1,
            },
            requested_purpose: {
              enum: ["fit", "development", "calibration", "final"],
            },
            purpose: {
              enum: ["fit", "development", "calibration", "final", "excluded"],
            },
            exclusion_reason: {
              anyOf: [
                {
                  enum: [
                    "group_spans_submission_split",
                    "label_after_available_cutoff",
                  ],
                },
                {
                  type: "null",
                },
              ],
            },
            submitted_at: {
              type: "string",
              format: "date-time",
            },
            label_known_at: {
              type: "string",
              format: "date-time",
            },
          },
          required: [
            "admission_id",
            "proof_id",
            "submission_id",
            "group_id",
            "closure_ids",
            "requested_purpose",
            "purpose",
            "exclusion_reason",
            "submitted_at",
            "label_known_at",
          ],
        },
        minItems: 4,
        maxItems: 1000,
      },
      membership_digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      digest: {
        type: "string",
        pattern: "^[a-f0-9]{64}$",
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
      strict_prebid_eligible: {
        const: false,
      },
      online_metrics_eligible: {
        const: false,
      },
      formal_sample_created: {
        const: false,
      },
    },
    required: [
      "schema",
      "id",
      "protocol_id",
      "protocol_digest",
      "origin",
      "timing",
      "members",
      "membership_digest",
      "digest",
      "research_only",
      "formal_eligibility",
      "strict_prebid_eligible",
      "online_metrics_eligible",
      "formal_sample_created",
    ],
  },
  PackageHistoricalCohortView: {
    type: "object",
    additionalProperties: false,
    properties: {
      cohort: {
        type: "object",
        additionalProperties: false,
        properties: {
          schema: {
            const: "package-history-cohort/1",
          },
          id: {
            type: "string",
            format: "uuid",
          },
          protocol_id: {
            type: "string",
            format: "uuid",
          },
          protocol_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          origin: {
            enum: ["synthetic", "external_evidence"],
          },
          timing: {
            type: "object",
            additionalProperties: false,
            properties: {
              mode: {
                const: "retrospective_submission_time_holdout",
              },
              historical_as_of: {
                const: "per_exact_actual_submission",
              },
              submission_split_at: {
                type: "string",
                format: "date-time",
              },
              label_available_as_of: {
                type: "string",
                format: "date-time",
              },
              training_frozen_at: {
                type: "string",
                format: "date-time",
              },
              group_spanning_policy: {
                const: "exclude",
              },
              prediction_timing: {
                const: "retrospective",
              },
            },
            required: [
              "mode",
              "historical_as_of",
              "submission_split_at",
              "label_available_as_of",
              "training_frozen_at",
              "group_spanning_policy",
              "prediction_timing",
            ],
          },
          members: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                admission_id: {
                  type: "string",
                  format: "uuid",
                },
                proof_id: {
                  type: "string",
                  format: "uuid",
                },
                submission_id: {
                  type: "string",
                  format: "uuid",
                },
                group_id: {
                  type: "string",
                  format: "uuid",
                },
                closure_ids: {
                  type: "array",
                  items: {
                    type: "string",
                    format: "uuid",
                  },
                  minItems: 1,
                },
                requested_purpose: {
                  enum: ["fit", "development", "calibration", "final"],
                },
                purpose: {
                  enum: [
                    "fit",
                    "development",
                    "calibration",
                    "final",
                    "excluded",
                  ],
                },
                exclusion_reason: {
                  anyOf: [
                    {
                      enum: [
                        "group_spans_submission_split",
                        "label_after_available_cutoff",
                      ],
                    },
                    {
                      type: "null",
                    },
                  ],
                },
                submitted_at: {
                  type: "string",
                  format: "date-time",
                },
                label_known_at: {
                  type: "string",
                  format: "date-time",
                },
              },
              required: [
                "admission_id",
                "proof_id",
                "submission_id",
                "group_id",
                "closure_ids",
                "requested_purpose",
                "purpose",
                "exclusion_reason",
                "submitted_at",
                "label_known_at",
              ],
            },
            minItems: 4,
            maxItems: 1000,
          },
          membership_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          strict_prebid_eligible: {
            const: false,
          },
          online_metrics_eligible: {
            const: false,
          },
          formal_sample_created: {
            const: false,
          },
        },
        required: [
          "schema",
          "id",
          "protocol_id",
          "protocol_digest",
          "origin",
          "timing",
          "members",
          "membership_digest",
          "digest",
          "research_only",
          "formal_eligibility",
          "strict_prebid_eligible",
          "online_metrics_eligible",
          "formal_sample_created",
        ],
      },
      current: {
        type: "boolean",
      },
    },
    required: ["cohort", "current"],
  },
  PackageHistoricalJob: {
    type: "object",
    additionalProperties: false,
    properties: {
      job_id: {
        type: "string",
        format: "uuid",
      },
      cohort_id: {
        type: "string",
        format: "uuid",
      },
      kind: {
        enum: ["train", "evaluate"],
      },
      state: {
        enum: [
          "queued",
          "running",
          "paused",
          "succeeded",
          "failed",
          "cancelled",
        ],
      },
      generation: {
        type: "integer",
        minimum: 1,
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
    },
    required: [
      "job_id",
      "cohort_id",
      "kind",
      "state",
      "generation",
      "research_only",
      "formal_eligibility",
    ],
  },
  PackageHistoricalJobView: {
    type: "object",
    additionalProperties: false,
    properties: {
      job_id: {
        type: "string",
        format: "uuid",
      },
      cohort_id: {
        type: "string",
        format: "uuid",
      },
      kind: {
        enum: ["train", "evaluate"],
      },
      state: {
        enum: [
          "queued",
          "running",
          "paused",
          "succeeded",
          "failed",
          "cancelled",
        ],
      },
      generation: {
        type: "integer",
        minimum: 1,
      },
      research_only: {
        const: true,
      },
      formal_eligibility: {
        const: "unavailable",
      },
      current: {
        type: "boolean",
      },
      result: {
        anyOf: [
          {
            oneOf: [
              {
                type: "object",
                additionalProperties: false,
                properties: {
                  schema: {
                    const: "package-history-training-result/1",
                  },
                  origin: {
                    enum: ["synthetic", "external_evidence"],
                  },
                  cohort_id: {
                    type: "string",
                    format: "uuid",
                  },
                  protocol_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  training_export_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  membership_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  model_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  model: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      schema: {
                        const: "package-history-constant-model/1",
                      },
                      method_digest: {
                        type: "string",
                        pattern: "^[a-f0-9]{64}$",
                      },
                      family: {
                        enum: ["mean", "median"],
                      },
                      constant: {
                        type: "string",
                        pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                      },
                      training_export_digest: {
                        type: "string",
                        pattern: "^[a-f0-9]{64}$",
                      },
                    },
                    required: [
                      "schema",
                      "method_digest",
                      "family",
                      "constant",
                      "training_export_digest",
                    ],
                  },
                  baselines: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      mean: {
                        type: "string",
                        pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                      },
                      median: {
                        type: "string",
                        pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                      },
                    },
                    required: ["mean", "median"],
                  },
                  selection: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      development_project_mae: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          mean: {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          median: {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                        },
                        required: ["mean", "median"],
                      },
                      selected: {
                        enum: ["mean", "median"],
                      },
                      refit_with_development: {
                        const: false,
                      },
                    },
                    required: [
                      "development_project_mae",
                      "selected",
                      "refit_with_development",
                    ],
                  },
                  intervals: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      "0.8": {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          radius: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          groups: {
                            type: "integer",
                            minimum: 0,
                          },
                          rank: {
                            type: "integer",
                            minimum: 0,
                          },
                          unavailable_reason: {
                            anyOf: [
                              {
                                const:
                                  "insufficient_independent_calibration_groups",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                        },
                        required: [
                          "radius",
                          "groups",
                          "rank",
                          "unavailable_reason",
                        ],
                      },
                      "0.9": {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          radius: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          groups: {
                            type: "integer",
                            minimum: 0,
                          },
                          rank: {
                            type: "integer",
                            minimum: 0,
                          },
                          unavailable_reason: {
                            anyOf: [
                              {
                                const:
                                  "insufficient_independent_calibration_groups",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                        },
                        required: [
                          "radius",
                          "groups",
                          "rank",
                          "unavailable_reason",
                        ],
                      },
                    },
                    required: ["0.8", "0.9"],
                  },
                  research_only: {
                    const: true,
                  },
                  formal_eligibility: {
                    const: "unavailable",
                  },
                  provider_requests: {
                    const: 0,
                  },
                  paid_calls: {
                    const: 0,
                  },
                },
                required: [
                  "schema",
                  "origin",
                  "cohort_id",
                  "protocol_digest",
                  "training_export_digest",
                  "membership_digest",
                  "model_digest",
                  "model",
                  "baselines",
                  "selection",
                  "intervals",
                  "research_only",
                  "formal_eligibility",
                  "provider_requests",
                  "paid_calls",
                ],
              },
              {
                type: "object",
                additionalProperties: false,
                properties: {
                  schema: {
                    const: "package-history-independent-evaluation/1",
                  },
                  origin: {
                    enum: ["synthetic", "external_evidence"],
                  },
                  cohort_id: {
                    type: "string",
                    format: "uuid",
                  },
                  protocol_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  model_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  membership_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  predictions_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  labels_digest: {
                    type: "string",
                    pattern: "^[a-f0-9]{64}$",
                  },
                  timing: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      mode: {
                        const: "retrospective_submission_time_holdout",
                      },
                      historical_as_of: {
                        const: "per_exact_actual_submission",
                      },
                      submission_split_at: {
                        type: "string",
                        format: "date-time",
                      },
                      label_available_as_of: {
                        type: "string",
                        format: "date-time",
                      },
                      training_frozen_at: {
                        type: "string",
                        format: "date-time",
                      },
                      group_spanning_policy: {
                        const: "exclude",
                      },
                      prediction_timing: {
                        const: "retrospective",
                      },
                    },
                    required: [
                      "mode",
                      "historical_as_of",
                      "submission_split_at",
                      "label_available_as_of",
                      "training_frozen_at",
                      "group_spanning_policy",
                      "prediction_timing",
                    ],
                  },
                  selection_denominator: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      selected_submissions: {
                        type: "integer",
                        minimum: 0,
                      },
                      excluded_submissions: {
                        type: "integer",
                        minimum: 0,
                      },
                      final_side_candidates: {
                        type: "integer",
                        minimum: 0,
                      },
                    },
                    required: [
                      "selected_submissions",
                      "excluded_submissions",
                      "final_side_candidates",
                    ],
                  },
                  report: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      denominator: {
                        type: "integer",
                        minimum: 0,
                      },
                      independent_groups: {
                        type: "integer",
                        minimum: 0,
                      },
                      projects: {
                        type: "integer",
                        minimum: 0,
                      },
                      counts: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          succeeded: {
                            type: "integer",
                            minimum: 0,
                          },
                          failed: {
                            type: "integer",
                            minimum: 0,
                          },
                          rejected: {
                            type: "integer",
                            minimum: 0,
                          },
                          unlabeled: {
                            type: "integer",
                            minimum: 0,
                          },
                        },
                        required: [
                          "succeeded",
                          "failed",
                          "rejected",
                          "unlabeled",
                        ],
                      },
                      success_coverage: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      sample_mae: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      project_mae: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      original_scale_project_mae: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      p90_absolute_error: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      project_within_three: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      project_bias: {
                        anyOf: [
                          {
                            type: "string",
                            pattern: "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      intervals: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          "0.8": {
                            oneOf: [
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  coverage: {
                                    type: "string",
                                    pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                  width: {
                                    type: "string",
                                    pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                },
                                required: ["coverage", "width"],
                              },
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  coverage: {
                                    type: "null",
                                  },
                                  width: {
                                    type: "null",
                                  },
                                  reason: {
                                    const:
                                      "interval_or_labeled_predictions_unavailable",
                                  },
                                },
                                required: ["coverage", "width", "reason"],
                              },
                            ],
                          },
                          "0.9": {
                            oneOf: [
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  coverage: {
                                    type: "string",
                                    pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                  width: {
                                    type: "string",
                                    pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                },
                                required: ["coverage", "width"],
                              },
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  coverage: {
                                    type: "null",
                                  },
                                  width: {
                                    type: "null",
                                  },
                                  reason: {
                                    const:
                                      "interval_or_labeled_predictions_unavailable",
                                  },
                                },
                                required: ["coverage", "width", "reason"],
                              },
                            ],
                          },
                        },
                        required: ["0.8", "0.9"],
                      },
                      paired_baselines: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          mean: {
                            oneOf: [
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  gain: {
                                    type: "string",
                                    pattern: "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                  paired_count: {
                                    type: "integer",
                                    minimum: 0,
                                  },
                                  group_bootstrap_gain_95: {
                                    anyOf: [
                                      {
                                        type: "array",
                                        items: {
                                          type: "string",
                                          pattern:
                                            "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                        },
                                        minItems: 2,
                                        maxItems: 2,
                                      },
                                      {
                                        type: "null",
                                      },
                                    ],
                                  },
                                },
                                required: [
                                  "gain",
                                  "paired_count",
                                  "group_bootstrap_gain_95",
                                ],
                              },
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  gain: {
                                    type: "null",
                                  },
                                  reason: {
                                    const: "paired_baseline_missing",
                                  },
                                },
                                required: ["gain", "reason"],
                              },
                            ],
                          },
                          median: {
                            oneOf: [
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  gain: {
                                    type: "string",
                                    pattern: "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                  },
                                  paired_count: {
                                    type: "integer",
                                    minimum: 0,
                                  },
                                  group_bootstrap_gain_95: {
                                    anyOf: [
                                      {
                                        type: "array",
                                        items: {
                                          type: "string",
                                          pattern:
                                            "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                        },
                                        minItems: 2,
                                        maxItems: 2,
                                      },
                                      {
                                        type: "null",
                                      },
                                    ],
                                  },
                                },
                                required: [
                                  "gain",
                                  "paired_count",
                                  "group_bootstrap_gain_95",
                                ],
                              },
                              {
                                type: "object",
                                additionalProperties: false,
                                properties: {
                                  gain: {
                                    type: "null",
                                  },
                                  reason: {
                                    const: "paired_baseline_missing",
                                  },
                                },
                                required: ["gain", "reason"],
                              },
                            ],
                          },
                        },
                        required: [],
                      },
                      group_bootstrap_project_mae_95: {
                        anyOf: [
                          {
                            type: "array",
                            items: {
                              type: "string",
                              pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                            },
                            minItems: 2,
                            maxItems: 2,
                          },
                          {
                            type: "null",
                          },
                        ],
                      },
                      stability_range_p90: {
                        type: "null",
                      },
                      strata: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          method: {
                            type: "object",
                            additionalProperties: {
                              type: "object",
                              additionalProperties: false,
                              properties: {
                                count: {
                                  type: "integer",
                                  minimum: 0,
                                },
                                project_mae: {
                                  anyOf: [
                                    {
                                      type: "string",
                                      pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                    },
                                    {
                                      type: "null",
                                    },
                                  ],
                                },
                              },
                              required: ["count", "project_mae"],
                            },
                          },
                          maximum: {
                            type: "object",
                            additionalProperties: {
                              type: "object",
                              additionalProperties: false,
                              properties: {
                                count: {
                                  type: "integer",
                                  minimum: 0,
                                },
                                project_mae: {
                                  anyOf: [
                                    {
                                      type: "string",
                                      pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                    },
                                    {
                                      type: "null",
                                    },
                                  ],
                                },
                              },
                              required: ["count", "project_mae"],
                            },
                          },
                          engineering_type: {
                            type: "object",
                            additionalProperties: {
                              type: "object",
                              additionalProperties: false,
                              properties: {
                                count: {
                                  type: "integer",
                                  minimum: 0,
                                },
                                project_mae: {
                                  anyOf: [
                                    {
                                      type: "string",
                                      pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                    },
                                    {
                                      type: "null",
                                    },
                                  ],
                                },
                              },
                              required: ["count", "project_mae"],
                            },
                          },
                        },
                        required: ["method", "maximum", "engineering_type"],
                      },
                      unavailable_statistics: {
                        const: [
                          "ranking_without_ranking_labels",
                          "shortlist_probability_without_labels",
                          "judge_disagreement_without_judge_labels",
                          "whole_round_stability_without_independent_repeat_predictions",
                        ],
                      },
                    },
                    required: [
                      "denominator",
                      "independent_groups",
                      "projects",
                      "counts",
                      "success_coverage",
                      "sample_mae",
                      "project_mae",
                      "original_scale_project_mae",
                      "p90_absolute_error",
                      "project_within_three",
                      "project_bias",
                      "intervals",
                      "paired_baselines",
                      "group_bootstrap_project_mae_95",
                      "stability_range_p90",
                      "strata",
                      "unavailable_statistics",
                    ],
                  },
                  official_source_subset: {
                    type: "object",
                    additionalProperties: false,
                    properties: {
                      scope: {
                        const:
                          "verified_official_associations_with_evidence_backed_admission",
                      },
                      origin: {
                        enum: ["synthetic", "external_evidence"],
                      },
                      report: {
                        type: "object",
                        additionalProperties: false,
                        properties: {
                          denominator: {
                            type: "integer",
                            minimum: 0,
                          },
                          independent_groups: {
                            type: "integer",
                            minimum: 0,
                          },
                          projects: {
                            type: "integer",
                            minimum: 0,
                          },
                          counts: {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                              succeeded: {
                                type: "integer",
                                minimum: 0,
                              },
                              failed: {
                                type: "integer",
                                minimum: 0,
                              },
                              rejected: {
                                type: "integer",
                                minimum: 0,
                              },
                              unlabeled: {
                                type: "integer",
                                minimum: 0,
                              },
                            },
                            required: [
                              "succeeded",
                              "failed",
                              "rejected",
                              "unlabeled",
                            ],
                          },
                          success_coverage: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          sample_mae: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          project_mae: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          original_scale_project_mae: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          p90_absolute_error: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          project_within_three: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          project_bias: {
                            anyOf: [
                              {
                                type: "string",
                                pattern: "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          intervals: {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                              "0.8": {
                                oneOf: [
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      coverage: {
                                        type: "string",
                                        pattern:
                                          "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                      width: {
                                        type: "string",
                                        pattern:
                                          "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                    },
                                    required: ["coverage", "width"],
                                  },
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      coverage: {
                                        type: "null",
                                      },
                                      width: {
                                        type: "null",
                                      },
                                      reason: {
                                        const:
                                          "interval_or_labeled_predictions_unavailable",
                                      },
                                    },
                                    required: ["coverage", "width", "reason"],
                                  },
                                ],
                              },
                              "0.9": {
                                oneOf: [
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      coverage: {
                                        type: "string",
                                        pattern:
                                          "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                      width: {
                                        type: "string",
                                        pattern:
                                          "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                    },
                                    required: ["coverage", "width"],
                                  },
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      coverage: {
                                        type: "null",
                                      },
                                      width: {
                                        type: "null",
                                      },
                                      reason: {
                                        const:
                                          "interval_or_labeled_predictions_unavailable",
                                      },
                                    },
                                    required: ["coverage", "width", "reason"],
                                  },
                                ],
                              },
                            },
                            required: ["0.8", "0.9"],
                          },
                          paired_baselines: {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                              mean: {
                                oneOf: [
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      gain: {
                                        type: "string",
                                        pattern:
                                          "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                      paired_count: {
                                        type: "integer",
                                        minimum: 0,
                                      },
                                      group_bootstrap_gain_95: {
                                        anyOf: [
                                          {
                                            type: "array",
                                            items: {
                                              type: "string",
                                              pattern:
                                                "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                            },
                                            minItems: 2,
                                            maxItems: 2,
                                          },
                                          {
                                            type: "null",
                                          },
                                        ],
                                      },
                                    },
                                    required: [
                                      "gain",
                                      "paired_count",
                                      "group_bootstrap_gain_95",
                                    ],
                                  },
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      gain: {
                                        type: "null",
                                      },
                                      reason: {
                                        const: "paired_baseline_missing",
                                      },
                                    },
                                    required: ["gain", "reason"],
                                  },
                                ],
                              },
                              median: {
                                oneOf: [
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      gain: {
                                        type: "string",
                                        pattern:
                                          "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                      },
                                      paired_count: {
                                        type: "integer",
                                        minimum: 0,
                                      },
                                      group_bootstrap_gain_95: {
                                        anyOf: [
                                          {
                                            type: "array",
                                            items: {
                                              type: "string",
                                              pattern:
                                                "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                            },
                                            minItems: 2,
                                            maxItems: 2,
                                          },
                                          {
                                            type: "null",
                                          },
                                        ],
                                      },
                                    },
                                    required: [
                                      "gain",
                                      "paired_count",
                                      "group_bootstrap_gain_95",
                                    ],
                                  },
                                  {
                                    type: "object",
                                    additionalProperties: false,
                                    properties: {
                                      gain: {
                                        type: "null",
                                      },
                                      reason: {
                                        const: "paired_baseline_missing",
                                      },
                                    },
                                    required: ["gain", "reason"],
                                  },
                                ],
                              },
                            },
                            required: [],
                          },
                          group_bootstrap_project_mae_95: {
                            anyOf: [
                              {
                                type: "array",
                                items: {
                                  type: "string",
                                  pattern: "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                },
                                minItems: 2,
                                maxItems: 2,
                              },
                              {
                                type: "null",
                              },
                            ],
                          },
                          stability_range_p90: {
                            type: "null",
                          },
                          strata: {
                            type: "object",
                            additionalProperties: false,
                            properties: {
                              method: {
                                type: "object",
                                additionalProperties: {
                                  type: "object",
                                  additionalProperties: false,
                                  properties: {
                                    count: {
                                      type: "integer",
                                      minimum: 0,
                                    },
                                    project_mae: {
                                      anyOf: [
                                        {
                                          type: "string",
                                          pattern:
                                            "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                        },
                                        {
                                          type: "null",
                                        },
                                      ],
                                    },
                                  },
                                  required: ["count", "project_mae"],
                                },
                              },
                              maximum: {
                                type: "object",
                                additionalProperties: {
                                  type: "object",
                                  additionalProperties: false,
                                  properties: {
                                    count: {
                                      type: "integer",
                                      minimum: 0,
                                    },
                                    project_mae: {
                                      anyOf: [
                                        {
                                          type: "string",
                                          pattern:
                                            "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                        },
                                        {
                                          type: "null",
                                        },
                                      ],
                                    },
                                  },
                                  required: ["count", "project_mae"],
                                },
                              },
                              engineering_type: {
                                type: "object",
                                additionalProperties: {
                                  type: "object",
                                  additionalProperties: false,
                                  properties: {
                                    count: {
                                      type: "integer",
                                      minimum: 0,
                                    },
                                    project_mae: {
                                      anyOf: [
                                        {
                                          type: "string",
                                          pattern:
                                            "^(0|[1-9][0-9]*)(\\.[0-9]+)?$",
                                        },
                                        {
                                          type: "null",
                                        },
                                      ],
                                    },
                                  },
                                  required: ["count", "project_mae"],
                                },
                              },
                            },
                            required: ["method", "maximum", "engineering_type"],
                          },
                          unavailable_statistics: {
                            const: [
                              "ranking_without_ranking_labels",
                              "shortlist_probability_without_labels",
                              "judge_disagreement_without_judge_labels",
                              "whole_round_stability_without_independent_repeat_predictions",
                            ],
                          },
                        },
                        required: [
                          "denominator",
                          "independent_groups",
                          "projects",
                          "counts",
                          "success_coverage",
                          "sample_mae",
                          "project_mae",
                          "original_scale_project_mae",
                          "p90_absolute_error",
                          "project_within_three",
                          "project_bias",
                          "intervals",
                          "paired_baselines",
                          "group_bootstrap_project_mae_95",
                          "stability_range_p90",
                          "strata",
                          "unavailable_statistics",
                        ],
                      },
                    },
                    required: ["scope", "origin", "report"],
                  },
                  research_only: {
                    const: true,
                  },
                  formal_eligibility: {
                    const: "unavailable",
                  },
                  acceptance_decision: {
                    const: "unavailable",
                  },
                  missing_acceptance: {
                    const: [
                      "real_independent_quality_validation",
                      "complete_package_three_judgment_features",
                      "preexposure_business_certification",
                      "independent_repeat_stability",
                      "observation_and_release_authority",
                    ],
                  },
                  provider_requests: {
                    const: 0,
                  },
                  paid_calls: {
                    const: 0,
                  },
                },
                required: [
                  "schema",
                  "origin",
                  "cohort_id",
                  "protocol_digest",
                  "model_digest",
                  "membership_digest",
                  "predictions_digest",
                  "labels_digest",
                  "timing",
                  "selection_denominator",
                  "report",
                  "official_source_subset",
                  "research_only",
                  "formal_eligibility",
                  "acceptance_decision",
                  "missing_acceptance",
                  "provider_requests",
                  "paid_calls",
                ],
              },
            ],
          },
          {
            type: "null",
          },
        ],
      },
      result_digest: {
        anyOf: [
          {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          {
            type: "null",
          },
        ],
      },
    },
    required: [
      "job_id",
      "cohort_id",
      "kind",
      "state",
      "generation",
      "research_only",
      "formal_eligibility",
      "current",
      "result",
      "result_digest",
    ],
  },
  PackageHistoryAdmissionRequest: {
    additionalProperties: false,
    properties: {
      submission_id: {
        format: "uuid",
        title: "Submission Id",
        type: "string",
      },
      outcome_id: {
        format: "uuid",
        title: "Outcome Id",
        type: "string",
      },
      proof_id: {
        format: "uuid",
        title: "Proof Id",
        type: "string",
      },
      context_digest: {
        pattern: "^[a-f0-9]{64}$",
        title: "Context Digest",
        type: "string",
      },
      reason: {
        maxLength: 4000,
        minLength: 1,
        title: "Reason",
        type: "string",
      },
    },
    required: [
      "submission_id",
      "outcome_id",
      "proof_id",
      "context_digest",
      "reason",
    ],
    title: "PackageHistoryAdmissionRequest",
    type: "object",
  },
  PackageHistoryProtocolRequest: {
    additionalProperties: false,
    properties: {
      method_digest: {
        pattern: "^[a-f0-9]{64}$",
        title: "Method Digest",
        type: "string",
      },
      seed: {
        maximum: 2147483647,
        minimum: 0,
        title: "Seed",
        type: "integer",
      },
      bootstrap_iterations: {
        maximum: 10000,
        minimum: 100,
        title: "Bootstrap Iterations",
        type: "integer",
      },
      reason: {
        maxLength: 4000,
        minLength: 1,
        title: "Reason",
        type: "string",
      },
    },
    required: ["method_digest", "seed", "bootstrap_iterations", "reason"],
    title: "PackageHistoryProtocolRequest",
    type: "object",
  },
  PackageHistoryCohortRequest: {
    additionalProperties: false,
    properties: {
      protocol_id: {
        format: "uuid",
        title: "Protocol Id",
        type: "string",
      },
      submission_split_at: {
        format: "date-time",
        title: "Submission Split At",
        type: "string",
      },
      label_available_as_of: {
        format: "date-time",
        title: "Label Available As Of",
        type: "string",
      },
      selections: {
        items: {
          $ref: "#/components/schemas/PackageHistorySelection",
        },
        maxItems: 1000,
        minItems: 4,
        title: "Selections",
        type: "array",
      },
      reason: {
        maxLength: 4000,
        minLength: 1,
        title: "Reason",
        type: "string",
      },
    },
    required: [
      "protocol_id",
      "submission_split_at",
      "label_available_as_of",
      "selections",
      "reason",
    ],
    title: "PackageHistoryCohortRequest",
    type: "object",
  },
  PackageHistorySelection: {
    additionalProperties: false,
    properties: {
      admission_id: {
        format: "uuid",
        title: "Admission Id",
        type: "string",
      },
      purpose: {
        enum: ["fit", "development", "calibration", "final"],
        title: "Purpose",
        type: "string",
      },
    },
    required: ["admission_id", "purpose"],
    title: "PackageHistorySelection",
    type: "object",
  },
  PackageHistoryJobRequest: {
    additionalProperties: false,
    properties: {
      kind: {
        enum: ["train", "evaluate"],
        title: "Kind",
        type: "string",
      },
      reason: {
        maxLength: 4000,
        minLength: 1,
        title: "Reason",
        type: "string",
      },
    },
    required: ["kind", "reason"],
    title: "PackageHistoryJobRequest",
    type: "object",
  },
  PackageHistoryJobControl: {
    additionalProperties: false,
    properties: {
      action: {
        enum: ["pause", "resume", "cancel"],
        title: "Action",
        type: "string",
      },
      generation: {
        minimum: 1,
        title: "Generation",
        type: "integer",
      },
      reason: {
        maxLength: 4000,
        minLength: 1,
        title: "Reason",
        type: "string",
      },
    },
    required: ["action", "generation", "reason"],
    title: "PackageHistoryJobControl",
    type: "object",
  },
  PackageHistoryAdmissionDirectory: {
    oneOf: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "admissions",
          },
          status: {
            const: "observed",
          },
          schema_configured: {
            const: true,
          },
          items: {
            type: "array",
            maxItems: 50,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                id: {
                  type: "string",
                  format: "uuid",
                },
                created_at: {
                  type: "string",
                  format: "date-time",
                },
                current_status: {
                  const: "not_rechecked",
                },
                kind: {
                  const: "admission",
                },
                bid_id: {
                  type: "string",
                  format: "uuid",
                },
                scope_id: {
                  type: "string",
                  format: "uuid",
                },
                submission_id: {
                  type: "string",
                  format: "uuid",
                },
                outcome_id: {
                  type: "string",
                  format: "uuid",
                },
                digest: {
                  type: "string",
                  pattern: "^[a-f0-9]{64}$",
                },
                origin: {
                  enum: ["synthetic", "external_evidence"],
                },
                state: {
                  enum: ["mechanism_candidate", "retrospective_candidate"],
                },
                historical_as_of: {
                  type: "string",
                  format: "date-time",
                },
                label_known_at: {
                  type: "string",
                  format: "date-time",
                },
              },
              required: [
                "id",
                "created_at",
                "current_status",
                "kind",
                "bid_id",
                "scope_id",
                "submission_id",
                "outcome_id",
                "digest",
                "origin",
                "state",
                "historical_as_of",
                "label_known_at",
              ],
            },
          },
          total: {
            type: "integer",
            minimum: 0,
            maximum: 2000,
          },
          observation_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          complete_observation: {
            const: true,
          },
          has_more: {
            type: "boolean",
          },
          next_cursor: {
            anyOf: [
              {
                type: "string",
                minLength: 1,
                maxLength: 4096,
              },
              {
                type: "null",
              },
            ],
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "admissions",
          },
          status: {
            const: "unavailable",
          },
          schema_configured: {
            const: false,
          },
          items: {
            type: "array",
            maxItems: 0,
          },
          total: {
            type: "null",
          },
          observation_digest: {
            type: "null",
          },
          complete_observation: {
            const: false,
          },
          has_more: {
            type: "null",
          },
          next_cursor: {
            type: "null",
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
    ],
  },
  PackageHistoryProtocolDirectory: {
    oneOf: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "protocols",
          },
          status: {
            const: "observed",
          },
          schema_configured: {
            const: true,
          },
          items: {
            type: "array",
            maxItems: 50,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                id: {
                  type: "string",
                  format: "uuid",
                },
                created_at: {
                  type: "string",
                  format: "date-time",
                },
                current_status: {
                  const: "not_rechecked",
                },
                kind: {
                  const: "protocol",
                },
                digest: {
                  type: "string",
                  pattern: "^[a-f0-9]{64}$",
                },
                document: {
                  type: "object",
                  additionalProperties: false,
                  properties: {
                    schema: {
                      const: "package-history-cpu-protocol/1",
                    },
                    method: {
                      type: "object",
                      additionalProperties: false,
                      properties: {
                        version: {
                          const: "package-history-project-baselines/1",
                        },
                        purpose: {
                          const: "retrospective_research",
                        },
                        features: {
                          const: "not_required_by_constant_baselines",
                        },
                        provider_requests: {
                          const: 0,
                        },
                        digest: {
                          type: "string",
                          pattern: "^[a-f0-9]{64}$",
                        },
                        sources: {
                          type: "object",
                          additionalProperties: false,
                          properties: {
                            "packages/model_governance/package_history_cpu.py":
                              {
                                type: "string",
                                pattern: "^[a-f0-9]{64}$",
                              },
                            "packages/model_governance/common.py": {
                              type: "string",
                              pattern: "^[a-f0-9]{64}$",
                            },
                            "packages/model_governance/evaluation.py": {
                              type: "string",
                              pattern: "^[a-f0-9]{64}$",
                            },
                            "packages/model_governance/statistics.py": {
                              type: "string",
                              pattern: "^[a-f0-9]{64}$",
                            },
                          },
                          required: [
                            "packages/model_governance/package_history_cpu.py",
                            "packages/model_governance/common.py",
                            "packages/model_governance/evaluation.py",
                            "packages/model_governance/statistics.py",
                          ],
                        },
                      },
                      required: [
                        "version",
                        "purpose",
                        "features",
                        "provider_requests",
                        "digest",
                        "sources",
                      ],
                    },
                    families: {
                      const: ["mean", "median"],
                    },
                    selection_metric: {
                      const: "project_mae",
                    },
                    tie_order: {
                      const: ["mean", "median"],
                    },
                    refit_with_development: {
                      const: false,
                    },
                    interval_levels: {
                      const: [0.8, 0.9],
                    },
                    group_spanning_policy: {
                      const: "exclude",
                    },
                    seed: {
                      type: "integer",
                      minimum: 0,
                      maximum: 2147483647,
                    },
                    bootstrap_iterations: {
                      type: "integer",
                      minimum: 100,
                      maximum: 10000,
                    },
                  },
                  required: [
                    "schema",
                    "method",
                    "families",
                    "selection_metric",
                    "tie_order",
                    "refit_with_development",
                    "interval_levels",
                    "group_spanning_policy",
                    "seed",
                    "bootstrap_iterations",
                  ],
                },
              },
              required: [
                "id",
                "created_at",
                "current_status",
                "kind",
                "digest",
                "document",
              ],
            },
          },
          total: {
            type: "integer",
            minimum: 0,
            maximum: 2000,
          },
          observation_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          complete_observation: {
            const: true,
          },
          has_more: {
            type: "boolean",
          },
          next_cursor: {
            anyOf: [
              {
                type: "string",
                minLength: 1,
                maxLength: 4096,
              },
              {
                type: "null",
              },
            ],
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "protocols",
          },
          status: {
            const: "unavailable",
          },
          schema_configured: {
            const: false,
          },
          items: {
            type: "array",
            maxItems: 0,
          },
          total: {
            type: "null",
          },
          observation_digest: {
            type: "null",
          },
          complete_observation: {
            const: false,
          },
          has_more: {
            type: "null",
          },
          next_cursor: {
            type: "null",
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
    ],
  },
  PackageHistoryCohortDirectory: {
    oneOf: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "cohorts",
          },
          status: {
            const: "observed",
          },
          schema_configured: {
            const: true,
          },
          items: {
            type: "array",
            maxItems: 50,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                id: {
                  type: "string",
                  format: "uuid",
                },
                created_at: {
                  type: "string",
                  format: "date-time",
                },
                current_status: {
                  const: "not_rechecked",
                },
                kind: {
                  const: "cohort",
                },
                protocol_id: {
                  type: "string",
                  format: "uuid",
                },
                digest: {
                  type: "string",
                  pattern: "^[a-f0-9]{64}$",
                },
                membership_digest: {
                  type: "string",
                  pattern: "^[a-f0-9]{64}$",
                },
                origin: {
                  enum: ["synthetic", "external_evidence"],
                },
                submission_split_at: {
                  type: "string",
                  format: "date-time",
                },
                label_available_as_of: {
                  type: "string",
                  format: "date-time",
                },
                member_count: {
                  type: "integer",
                  minimum: 4,
                  maximum: 1000,
                },
              },
              required: [
                "id",
                "created_at",
                "current_status",
                "kind",
                "protocol_id",
                "digest",
                "membership_digest",
                "origin",
                "submission_split_at",
                "label_available_as_of",
                "member_count",
              ],
            },
          },
          total: {
            type: "integer",
            minimum: 0,
            maximum: 2000,
          },
          observation_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          complete_observation: {
            const: true,
          },
          has_more: {
            type: "boolean",
          },
          next_cursor: {
            anyOf: [
              {
                type: "string",
                minLength: 1,
                maxLength: 4096,
              },
              {
                type: "null",
              },
            ],
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "cohorts",
          },
          status: {
            const: "unavailable",
          },
          schema_configured: {
            const: false,
          },
          items: {
            type: "array",
            maxItems: 0,
          },
          total: {
            type: "null",
          },
          observation_digest: {
            type: "null",
          },
          complete_observation: {
            const: false,
          },
          has_more: {
            type: "null",
          },
          next_cursor: {
            type: "null",
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
    ],
  },
  PackageHistoryJobDirectory: {
    oneOf: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "jobs",
          },
          status: {
            const: "observed",
          },
          schema_configured: {
            const: true,
          },
          items: {
            type: "array",
            maxItems: 50,
            items: {
              type: "object",
              additionalProperties: false,
              properties: {
                id: {
                  type: "string",
                  format: "uuid",
                },
                created_at: {
                  type: "string",
                  format: "date-time",
                },
                current_status: {
                  const: "not_rechecked",
                },
                kind: {
                  const: "job",
                },
                cohort_id: {
                  type: "string",
                  format: "uuid",
                },
                job_kind: {
                  enum: ["train", "evaluate"],
                },
                state: {
                  enum: [
                    "queued",
                    "running",
                    "paused",
                    "succeeded",
                    "failed",
                    "cancelled",
                  ],
                },
                generation: {
                  type: "integer",
                  minimum: 1,
                },
                result_available: {
                  type: "boolean",
                },
                result_digest: {
                  anyOf: [
                    {
                      type: "string",
                      pattern: "^[a-f0-9]{64}$",
                    },
                    {
                      type: "null",
                    },
                  ],
                },
              },
              required: [
                "id",
                "created_at",
                "current_status",
                "kind",
                "cohort_id",
                "job_kind",
                "state",
                "generation",
                "result_available",
                "result_digest",
              ],
            },
          },
          total: {
            type: "integer",
            minimum: 0,
            maximum: 2000,
          },
          observation_digest: {
            type: "string",
            pattern: "^[a-f0-9]{64}$",
          },
          complete_observation: {
            const: true,
          },
          has_more: {
            type: "boolean",
          },
          next_cursor: {
            anyOf: [
              {
                type: "string",
                minLength: 1,
                maxLength: 4096,
              },
              {
                type: "null",
              },
            ],
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
      {
        type: "object",
        additionalProperties: false,
        properties: {
          version: {
            const: "package-history-directory/1",
          },
          filters: {
            type: "object",
            additionalProperties: false,
            properties: {
              bid_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              scope_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              protocol_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
              cohort_id: {
                anyOf: [
                  {
                    type: "string",
                    format: "uuid",
                  },
                  {
                    type: "null",
                  },
                ],
              },
            },
            required: ["bid_id", "scope_id", "protocol_id", "cohort_id"],
          },
          observed_at: {
            type: "string",
            format: "date-time",
          },
          currentness_rechecked: {
            const: false,
          },
          research_only: {
            const: true,
          },
          formal_eligibility: {
            const: "unavailable",
          },
          qualification_granted: {
            const: false,
          },
          kind: {
            const: "jobs",
          },
          status: {
            const: "unavailable",
          },
          schema_configured: {
            const: false,
          },
          items: {
            type: "array",
            maxItems: 0,
          },
          total: {
            type: "null",
          },
          observation_digest: {
            type: "null",
          },
          complete_observation: {
            const: false,
          },
          has_more: {
            type: "null",
          },
          next_cursor: {
            type: "null",
          },
        },
        required: [
          "version",
          "filters",
          "observed_at",
          "currentness_rechecked",
          "research_only",
          "formal_eligibility",
          "qualification_granted",
          "kind",
          "status",
          "schema_configured",
          "items",
          "total",
          "observation_digest",
          "complete_observation",
          "has_more",
          "next_cursor",
        ],
      },
    ],
  },
};
