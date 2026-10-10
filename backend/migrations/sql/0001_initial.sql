-- PostgreSQL 16 业务主库 DDL（系统架构与数据契约 第 5 节）；迁移由 Alembic 维护，与 contracts/schema.sql 逐字一致。
-- 运行态分库：LangGraph 检查点与 MLflow 元数据各用独立数据库，不进入本文件；Milvus 向量是可重建派生索引，不在此保存事实。
-- 原件、证据、输入、审核、发布及结果版本追加保存（触发器强制）；可变指针单列。
-- 时间一律 TIMESTAMPTZ；分数、金额用 NUMERIC 且拒绝 NaN；JSON 用 JSONB。
CREATE TABLE members (
 id TEXT PRIMARY KEY, display_name TEXT NOT NULL, active BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE projects (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, tender_number TEXT, lot TEXT,
 round INTEGER NOT NULL DEFAULT 1 CHECK(round>=1), region TEXT, engineering_type TEXT,
 deadline TIMESTAMPTZ, state TEXT NOT NULL CHECK(state IN ('materials_pending','ready_to_analyze','analyzing','analysis_failed','issues_open','ready_to_submit','submitted','archived','cancelled','failed_tender')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1), owner_id TEXT NOT NULL REFERENCES members(id), created_at TIMESTAMPTZ NOT NULL,
 -- 项目级功能开关（键与默认值见 schemas.ProjectSettings；缺省的键取默认值）
 settings_json JSONB NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(settings_json)='object'),
 -- 关闭“自动开始评审”时，人要求开始评审的时间；非空表示有一轮待开始，冻结输入时清空
 analysis_requested_at TIMESTAMPTZ
);
CREATE TABLE artifacts (
 id TEXT PRIMARY KEY, sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'), object_key TEXT NOT NULL UNIQUE,
 byte_size BIGINT NOT NULL CHECK(byte_size>=0), media_type TEXT NOT NULL, contract_version TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, status TEXT NOT NULL CHECK(status IN ('staged','committed','quarantined'))
);
CREATE TABLE files (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), role TEXT NOT NULL CHECK(role IN ('tender','supplement','drawing','boq','body','submission','official_result','other')),
 created_at TIMESTAMPTZ NOT NULL, UNIQUE(id,project_id)
);
CREATE TABLE file_versions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_id TEXT NOT NULL, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 original_name TEXT NOT NULL, obtained_at TIMESTAMPTZ NOT NULL, document_date TEXT,
 association_status TEXT NOT NULL CHECK(association_status IN ('pending','confirmed','conflict')),
 supersedes TEXT, created_by TEXT NOT NULL REFERENCES members(id),
 UNIQUE(id,project_id), FOREIGN KEY(file_id,project_id) REFERENCES files(id,project_id),
 FOREIGN KEY(supersedes,project_id) REFERENCES file_versions(id,project_id)
);
CREATE TABLE parses (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_version_id TEXT NOT NULL,
 parser_version TEXT NOT NULL, page_count INTEGER CHECK(page_count>=0),
 coverage TEXT NOT NULL CHECK(coverage IN ('complete','partial','failed')), gaps_json JSONB NOT NULL,
 artifact_id TEXT REFERENCES artifacts(id), created_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(file_version_id,project_id) REFERENCES file_versions(id,project_id)
);
CREATE TABLE evidence (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_version_id TEXT NOT NULL,
 parse_id TEXT NOT NULL REFERENCES parses(id), physical_page INTEGER NOT NULL CHECK(physical_page>=1), printed_page TEXT,
 quote TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('text','table','visual_observation')),
 -- 证据块在该次解析中的顺序（跨页递增）；同一资料版本内按它读出即文档顺序
 seq INTEGER NOT NULL CHECK(seq>=0),
 bbox_json JSONB, semantic_review TEXT NOT NULL CHECK(semantic_review IN ('pending','supported','unsupported')),
 UNIQUE(id,project_id), FOREIGN KEY(file_version_id,project_id) REFERENCES file_versions(id,project_id)
);
CREATE TABLE rule_packages (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL CHECK(revision>=1),
 status TEXT NOT NULL CHECK(status IN ('candidate','conflict','confirmed')), artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 source_versions_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 -- 从评标办法中提取的投标条件（技术分满分、评标价规则），每项带 evidence_ids 与逐字原文 quote；没有提取到的项不出现
 terms_json JSONB NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(terms_json)='object'),
 UNIQUE(id,project_id)
);
CREATE TABLE rule_items (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, package_id TEXT NOT NULL, kind TEXT NOT NULL,
 statement TEXT NOT NULL, conditions_json JSONB NOT NULL, exceptions_json JSONB NOT NULL,
 evidence_ids_json JSONB NOT NULL,
 max_points NUMERIC CHECK(max_points>0 AND max_points<>'NaN'),  -- 评分条款的满分分值；其他性质为空
 carried_from_rule_id TEXT REFERENCES rule_items(id),  -- 重新提取时沿用了上一版规则包中同一条款的人工决定，指向那条旧规则
 FOREIGN KEY(package_id,project_id) REFERENCES rule_packages(id,project_id)
);
CREATE TABLE fact_sets (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 created_at TIMESTAMPTZ NOT NULL, UNIQUE(id,project_id)
);
CREATE TABLE fact_items (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, fact_set_id TEXT NOT NULL, name TEXT NOT NULL,
 value_decimal NUMERIC CHECK(value_decimal<>'NaN'), unit TEXT, subject TEXT NOT NULL, scope TEXT NOT NULL,
 confirmation TEXT NOT NULL CHECK(confirmation IN ('pending','confirmed','rejected')), evidence_ids_json JSONB NOT NULL, statement TEXT NOT NULL,
 FOREIGN KEY(fact_set_id,project_id) REFERENCES fact_sets(id,project_id)
);
CREATE TABLE input_snapshots (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), body_version_id TEXT NOT NULL,
 rule_set_id TEXT NOT NULL, fact_set_id TEXT, as_of TIMESTAMPTZ NOT NULL, contract_version TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'), manifest_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 UNIQUE(id,project_id), FOREIGN KEY(body_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(rule_set_id,project_id) REFERENCES rule_packages(id,project_id), FOREIGN KEY(fact_set_id,project_id) REFERENCES fact_sets(id,project_id)
);
CREATE TABLE snapshot_files (
 snapshot_id TEXT NOT NULL, project_id TEXT NOT NULL, file_version_id TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,file_version_id), FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id),
 FOREIGN KEY(file_version_id,project_id) REFERENCES file_versions(id,project_id)
);
CREATE TABLE reviews (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), object_kind TEXT NOT NULL,
 object_id TEXT NOT NULL, object_version TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES members(id), reviewed_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE findings (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, run_id TEXT NOT NULL,
 rule_id TEXT REFERENCES rule_items(id),
 -- 来源与分类：规则核对（source=rule，必带规则与规则依据状态）或确定性检测（一致性、范围残留）；分类决定报告里的归属
 source TEXT NOT NULL CHECK(source IN ('rule','consistency','scope')),
 category TEXT NOT NULL CHECK(category IN ('disqualification','response','consistency','scope','improvement')),
 rule_basis TEXT CHECK(rule_basis IN ('confirmed','unconfirmed')),
 -- 去重键 = 规则 + 性质 + 排序后的证据 ID；同一快照里相同去重键只保留首次产生的问题（重跑诊断不会产生重复问题，也不会覆盖已有的人工复核）
 dedupe_key TEXT NOT NULL,
 nature TEXT NOT NULL CHECK(nature IN ('fact_conflict','needs_confirmation','suggestion')), impact TEXT NOT NULL CHECK(impact IN ('qualification','technical','delivery')),
 severity TEXT NOT NULL CHECK(severity IN ('critical','normal','improvement')), statement TEXT NOT NULL,
 evidence_ids_json JSONB NOT NULL, required_facts_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, UNIQUE(id,project_id), UNIQUE(snapshot_id,dedupe_key), FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id),
 CHECK((source='rule')=(rule_id IS NOT NULL)), CHECK((source='rule')=(rule_basis IS NOT NULL))
);
CREATE TABLE finding_states (
 finding_id TEXT PRIMARY KEY REFERENCES findings(id), state TEXT NOT NULL CHECK(state IN ('candidate','confirmed','rejected','deferred','revision_pending','recheck_pending','resolved')),
 revision INTEGER NOT NULL CHECK(revision>=1), last_review_id TEXT REFERENCES reviews(id)
);
CREATE TABLE revisions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, base_version_id TEXT NOT NULL, target_version_id TEXT,
 finding_ids_json JSONB NOT NULL, allowed_fact_ids_json JSONB NOT NULL,
 diff_artifact_id TEXT NOT NULL REFERENCES artifacts(id), created_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(base_version_id,project_id) REFERENCES file_versions(id,project_id), FOREIGN KEY(target_version_id,project_id) REFERENCES file_versions(id,project_id)
);
CREATE TABLE submissions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body_version_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 submitted_at TIMESTAMPTZ NOT NULL, confirmation_review_id TEXT NOT NULL REFERENCES reviews(id), receipt_artifact_id TEXT REFERENCES artifacts(id),
 supersedes TEXT, UNIQUE(id,project_id), FOREIGN KEY(body_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id), FOREIGN KEY(supersedes,project_id) REFERENCES submissions(id,project_id)
);
CREATE TABLE outcomes (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, submission_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('user_reported','official')), verification_status TEXT NOT NULL CHECK(verification_status IN ('pending','verified','conflict')),
 target TEXT NOT NULL CHECK(target IN ('technical_total','composite_total','no_score')), value_decimal NUMERIC CHECK(value_decimal<>'NaN'), maximum_decimal NUMERIC CHECK(maximum_decimal<>'NaN'),
 aggregation TEXT, stage_result TEXT NOT NULL, source_artifact_id TEXT REFERENCES artifacts(id), source_page INTEGER CHECK(source_page>=1),
 published_at TIMESTAMPTZ, known_at TIMESTAMPTZ NOT NULL, verified_by TEXT REFERENCES members(id), supersedes TEXT,
 UNIQUE(id,project_id), FOREIGN KEY(submission_id,project_id) REFERENCES submissions(id,project_id),
 FOREIGN KEY(supersedes,project_id) REFERENCES outcomes(id,project_id),
 CHECK(verification_status!='verified' OR (source_kind='official' AND source_artifact_id IS NOT NULL AND verified_by IS NOT NULL)),
 CHECK(target!='no_score' OR (value_decimal IS NULL AND maximum_decimal IS NULL))
);
CREATE TABLE dataset_snapshots (
 id TEXT PRIMARY KEY, purpose TEXT NOT NULL, protocol_version TEXT NOT NULL, manifest_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 member_count INTEGER NOT NULL CHECK(member_count>=0), grouping TEXT NOT NULL, time_cutoff TIMESTAMPTZ NOT NULL, parent_id TEXT REFERENCES dataset_snapshots(id), created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE dataset_members (
 dataset_id TEXT NOT NULL REFERENCES dataset_snapshots(id), project_id TEXT NOT NULL, submission_id TEXT NOT NULL, outcome_id TEXT,
 split TEXT NOT NULL CHECK(split IN ('train','calibration','test','excluded')), group_id TEXT NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(dataset_id,submission_id), FOREIGN KEY(submission_id,project_id) REFERENCES submissions(id,project_id), FOREIGN KEY(outcome_id,project_id) REFERENCES outcomes(id,project_id)
);
CREATE TABLE experiments (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset_snapshots(id), protocol_version TEXT NOT NULL, strategy TEXT NOT NULL,
 code_sha256 TEXT NOT NULL, config_artifact_id TEXT NOT NULL REFERENCES artifacts(id), status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','not_evaluable')), report_artifact_id TEXT REFERENCES artifacts(id), started_at TIMESTAMPTZ,
 mlflow_run_id TEXT
);
CREATE TABLE model_bundles (
 id TEXT PRIMARY KEY, target TEXT NOT NULL, contract_version TEXT NOT NULL, components_json JSONB NOT NULL,
 experiment_id TEXT NOT NULL REFERENCES experiments(id), artifact_id TEXT NOT NULL REFERENCES artifacts(id), registered_at TIMESTAMPTZ NOT NULL,
 mlflow_model_name TEXT, mlflow_model_version TEXT,
 CHECK((mlflow_model_name IS NULL)=(mlflow_model_version IS NULL))
);
CREATE TABLE validations (
 id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL REFERENCES model_bundles(id), dataset_id TEXT REFERENCES dataset_snapshots(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('contract','research','engineering_assist','technical_total_business')),
 status TEXT NOT NULL CHECK(status IN ('passed','failed','not_evaluable')), scope TEXT NOT NULL,
 policy_artifact_id TEXT REFERENCES artifacts(id), report_artifact_id TEXT NOT NULL REFERENCES artifacts(id), reviewer_id TEXT NOT NULL REFERENCES members(id), validated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE releases (
 id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL REFERENCES model_bundles(id), validation_id TEXT NOT NULL REFERENCES validations(id),
 environment TEXT NOT NULL CHECK(environment IN ('research','shadow','business')), scope TEXT NOT NULL, previous_release_id TEXT REFERENCES releases(id),
 actor_id TEXT NOT NULL REFERENCES members(id), released_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE release_routes (
 target TEXT NOT NULL, environment TEXT NOT NULL, scope_key TEXT NOT NULL, release_id TEXT NOT NULL REFERENCES releases(id),
 revision INTEGER NOT NULL CHECK(revision>=1), PRIMARY KEY(target,environment,scope_key)
);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, snapshot_id TEXT, bundle_id TEXT REFERENCES model_bundles(id),
 kind TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('research','shadow','business')), state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_input','succeeded','failed','cancel_requested','cancelled')),
 stage TEXT NOT NULL, idempotency_key TEXT NOT NULL, input_sha256 TEXT NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'), input_json JSONB NOT NULL DEFAULT '{}'::jsonb, attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0),
 job_class TEXT NOT NULL CHECK(job_class IN ('parse','ai','experiment','export')), max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts BETWEEN 1 AND 10),
 worker_id TEXT, lease_token_hash TEXT, lease_until TIMESTAMPTZ, dispatched_at TIMESTAMPTZ, dispatch_count INTEGER NOT NULL DEFAULT 0 CHECK(dispatch_count>=0),
 output_artifact_id TEXT REFERENCES artifacts(id), error_code TEXT, coverage_json JSONB, created_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ,
 CHECK(kind IN ('parse','rules','diagnosis','revision','recheck','prediction','experiment','export')),
 CHECK(job_class=CASE WHEN kind IN ('parse','rules') THEN 'parse' WHEN kind IN ('diagnosis','revision','recheck','prediction') THEN 'ai' WHEN kind='experiment' THEN 'experiment' ELSE 'export' END),
 CHECK(state!='running' OR (worker_id IS NOT NULL AND lease_token_hash IS NOT NULL AND lease_until IS NOT NULL)),
 -- 解析与规则提取的输入是资料版本（input_json），没有快照；诊断、改稿、复检要快照但使用内置方法，不要方法包；其余必须两者都有。
 CHECK(kind IN ('parse','rules') OR (snapshot_id IS NOT NULL AND (bundle_id IS NOT NULL OR kind IN ('diagnosis','revision','recheck','prediction')))),
 UNIQUE(project_id,idempotency_key), UNIQUE(id,project_id), FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id)
);
-- 响应矩阵：每次诊断对每条规则的判定（满足／违反／无法判断／检查失败）；满足必须有正文依据，由程序校验后写入
CREATE TABLE rule_verdicts (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, run_id TEXT NOT NULL, rule_id TEXT NOT NULL REFERENCES rule_items(id),
 verdict TEXT NOT NULL CHECK(verdict IN ('satisfied','violated','unclear','failed')), rule_basis TEXT NOT NULL CHECK(rule_basis IN ('confirmed','unconfirmed')),
 body_evidence_ids_json JSONB NOT NULL, note TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 UNIQUE(run_id,rule_id), CHECK(verdict<>'satisfied' OR jsonb_array_length(body_evidence_ids_json)>0),
 FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id), FOREIGN KEY(run_id,project_id) REFERENCES jobs(id,project_id)
);
CREATE TABLE predictions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, bundle_id TEXT REFERENCES model_bundles(id), run_id TEXT NOT NULL,
 target TEXT NOT NULL CHECK(target='technical_total'), status TEXT NOT NULL CHECK(status IN ('candidate','abstained','failed')),
 purpose TEXT NOT NULL, estimated_decimal NUMERIC CHECK(estimated_decimal<>'NaN'), low_decimal NUMERIC CHECK(low_decimal<>'NaN'), high_decimal NUMERIC CHECK(high_decimal<>'NaN'),
 maximum_decimal NUMERIC CHECK(maximum_decimal<>'NaN'), validation_status TEXT NOT NULL CHECK(validation_status IN ('not_validated','validated_in_scope','out_of_scope')),
 validation_id TEXT REFERENCES validations(id), reason TEXT NOT NULL, detail_artifact_id TEXT REFERENCES artifacts(id), created_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(snapshot_id,project_id) REFERENCES input_snapshots(id,project_id), FOREIGN KEY(run_id,project_id) REFERENCES jobs(id,project_id),
 UNIQUE(id,project_id),
 CHECK(status='candidate' OR (estimated_decimal IS NULL AND low_decimal IS NULL AND high_decimal IS NULL)),
 CHECK(status<>'candidate' OR (estimated_decimal IS NOT NULL AND low_decimal IS NOT NULL AND high_decimal IS NOT NULL AND maximum_decimal IS NOT NULL
       AND low_decimal>=0 AND low_decimal<=estimated_decimal AND estimated_decimal<=high_decimal AND high_decimal<=maximum_decimal)),
 CHECK(purpose!='business' OR (validation_status='validated_in_scope' AND validation_id IS NOT NULL))
);
-- 报价方案：评标价规则参数、竞争对手报价估计、候选报价；每次保存追加一个版本
CREATE TABLE price_plans (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), actor_id TEXT NOT NULL REFERENCES members(id),
 params_json JSONB NOT NULL CHECK(jsonb_typeof(params_json)='object'), competitor_prices_json JSONB NOT NULL CHECK(jsonb_typeof(competitor_prices_json)='array'),
 candidate_prices_json JSONB NOT NULL CHECK(jsonb_typeof(candidate_prices_json)='array'), note TEXT NOT NULL, supersedes TEXT,
 created_at TIMESTAMPTZ NOT NULL, UNIQUE(id,project_id), FOREIGN KEY(supersedes,project_id) REFERENCES price_plans(id,project_id)
);
CREATE TABLE job_events (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), attempt INTEGER NOT NULL, kind TEXT NOT NULL,
 artifact_id TEXT REFERENCES artifacts(id), details_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE audit_events (
 id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), actor_id TEXT, action TEXT NOT NULL,
 object_kind TEXT NOT NULL, object_id TEXT NOT NULL, request_id TEXT NOT NULL, details_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE feedback (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, outcome_id TEXT NOT NULL, prediction_id TEXT REFERENCES predictions(id),
 kind TEXT NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(outcome_id,project_id) REFERENCES outcomes(id,project_id)
);
CREATE INDEX idx_projects_state_deadline ON projects(state,deadline);
CREATE INDEX idx_file_versions_project_file ON file_versions(project_id,file_id,obtained_at);
CREATE INDEX idx_jobs_dispatch ON jobs(dispatched_at NULLS FIRST,created_at) WHERE state='queued';
CREATE INDEX idx_jobs_lease ON jobs(lease_until) WHERE state='running';
CREATE INDEX idx_findings_project_snapshot ON findings(project_id,snapshot_id);
CREATE INDEX idx_rule_verdicts_snapshot ON rule_verdicts(project_id,snapshot_id,run_id);
CREATE INDEX idx_price_plans_project ON price_plans(project_id,created_at);
CREATE INDEX idx_outcomes_project_submission ON outcomes(project_id,submission_id,known_at);
CREATE INDEX idx_predictions_project_snapshot ON predictions(project_id,snapshot_id,created_at);
CREATE INDEX idx_job_events_job ON job_events(job_id,created_at);
CREATE INDEX idx_reviews_object ON reviews(project_id,object_kind,object_id,reviewed_at);
CREATE TABLE upload_sessions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), actor_id TEXT NOT NULL REFERENCES members(id),
 role TEXT NOT NULL, original_name TEXT NOT NULL, expected_sha256 TEXT NOT NULL, expected_bytes BIGINT NOT NULL CHECK(expected_bytes>0 AND expected_bytes<=104857600),
 expires_at TIMESTAMPTZ NOT NULL, state TEXT NOT NULL CHECK(state IN ('open','completed','failed','expired')), version_id TEXT REFERENCES file_versions(id),
 idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, media_type TEXT NOT NULL,
 version_of_file_id TEXT REFERENCES files(id), duplicate BOOLEAN NOT NULL DEFAULT false,
 staging_key TEXT NOT NULL UNIQUE, oss_upload_id TEXT NOT NULL, part_bytes INTEGER NOT NULL CHECK(part_bytes>=102400), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(project_id,actor_id,idempotency_key),
 CHECK(expected_sha256 ~ '^[0-9a-f]{64}$'), CHECK(state!='completed' OR version_id IS NOT NULL)
);
CREATE TABLE idempotency_keys (
 member_id TEXT NOT NULL REFERENCES members(id), idem_key TEXT NOT NULL CHECK(length(idem_key) BETWEEN 8 AND 128), operation TEXT NOT NULL,
 request_hash TEXT NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'), response_status INTEGER NOT NULL, response_json JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(member_id, idem_key, operation)
);
CREATE INDEX idx_idempotency_created ON idempotency_keys(created_at);
CREATE TABLE upload_parts (
 upload_id TEXT NOT NULL REFERENCES upload_sessions(id), part_number INTEGER NOT NULL CHECK(part_number BETWEEN 1 AND 10000),
 etag TEXT NOT NULL, byte_size BIGINT NOT NULL CHECK(byte_size>0), reported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(upload_id,part_number)
);
CREATE TABLE identities (
 id TEXT PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id), provider TEXT NOT NULL CHECK(provider='local'),
 subject TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ,
 UNIQUE(provider,subject)
);
CREATE TABLE auth_sessions (
 id TEXT PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'), member_id TEXT NOT NULL REFERENCES members(id), csrf_hash TEXT NOT NULL CHECK(csrf_hash ~ '^[0-9a-f]{64}$'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
 CHECK(expires_at>created_at)
);
CREATE TABLE outbox_events (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
 topic TEXT NOT NULL CHECK(topic IN ('job.parse','job.ai','job.experiment','job.export','domain.events')),
 message_key TEXT NOT NULL, payload_json JSONB NOT NULL CHECK(jsonb_typeof(payload_json)='object'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), published_at TIMESTAMPTZ, publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK(publish_attempts>=0), last_error TEXT
);
CREATE TABLE processed_messages (
 consumer TEXT NOT NULL, event_id UUID NOT NULL, processed_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(consumer,event_id)
);
CREATE TABLE index_builds (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), parse_id TEXT NOT NULL REFERENCES parses(id),
 collection TEXT NOT NULL, dense_model TEXT, analyzer_version TEXT NOT NULL, params_json JSONB NOT NULL CHECK(jsonb_typeof(params_json)='object'),
 state TEXT NOT NULL CHECK(state IN ('building','ready','failed','retired')), chunk_count INTEGER CHECK(chunk_count>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ, error_code TEXT,
 UNIQUE(parse_id,collection,dense_model,analyzer_version)
);
CREATE INDEX idx_outbox_unpublished ON outbox_events(id) WHERE published_at IS NULL;
CREATE INDEX idx_auth_sessions_member ON auth_sessions(member_id,expires_at);
CREATE INDEX idx_upload_sessions_open ON upload_sessions(expires_at) WHERE state='open';
CREATE INDEX idx_identities_member ON identities(member_id);
CREATE INDEX idx_index_builds_project ON index_builds(project_id,state);

-- 追加保存：禁止 UPDATE、DELETE、TRUNCATE；更正只能追加新版本。
CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'append_only:%',TG_TABLE_NAME USING ERRCODE='integrity_constraint_violation'; END $$;
CREATE TRIGGER immutable_file_versions BEFORE UPDATE OR DELETE ON file_versions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_file_versions_truncate BEFORE TRUNCATE ON file_versions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_parses BEFORE UPDATE OR DELETE ON parses FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_parses_truncate BEFORE TRUNCATE ON parses FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON evidence FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_evidence_truncate BEFORE TRUNCATE ON evidence FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_packages BEFORE UPDATE OR DELETE ON rule_packages FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_packages_truncate BEFORE TRUNCATE ON rule_packages FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_items BEFORE UPDATE OR DELETE ON rule_items FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_items_truncate BEFORE TRUNCATE ON rule_items FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_fact_sets BEFORE UPDATE OR DELETE ON fact_sets FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_fact_sets_truncate BEFORE TRUNCATE ON fact_sets FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_fact_items BEFORE UPDATE OR DELETE ON fact_items FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_fact_items_truncate BEFORE TRUNCATE ON fact_items FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_input_snapshots BEFORE UPDATE OR DELETE ON input_snapshots FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_input_snapshots_truncate BEFORE TRUNCATE ON input_snapshots FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_snapshot_files BEFORE UPDATE OR DELETE ON snapshot_files FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_snapshot_files_truncate BEFORE TRUNCATE ON snapshot_files FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_reviews BEFORE UPDATE OR DELETE ON reviews FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_reviews_truncate BEFORE TRUNCATE ON reviews FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_findings BEFORE UPDATE OR DELETE ON findings FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_findings_truncate BEFORE TRUNCATE ON findings FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_revisions BEFORE UPDATE OR DELETE ON revisions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_revisions_truncate BEFORE TRUNCATE ON revisions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_submissions BEFORE UPDATE OR DELETE ON submissions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_submissions_truncate BEFORE TRUNCATE ON submissions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_outcomes BEFORE UPDATE OR DELETE ON outcomes FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_outcomes_truncate BEFORE TRUNCATE ON outcomes FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_dataset_snapshots BEFORE UPDATE OR DELETE ON dataset_snapshots FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_dataset_snapshots_truncate BEFORE TRUNCATE ON dataset_snapshots FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_dataset_members BEFORE UPDATE OR DELETE ON dataset_members FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_dataset_members_truncate BEFORE TRUNCATE ON dataset_members FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_model_bundles BEFORE UPDATE OR DELETE ON model_bundles FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_model_bundles_truncate BEFORE TRUNCATE ON model_bundles FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_validations BEFORE UPDATE OR DELETE ON validations FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_validations_truncate BEFORE TRUNCATE ON validations FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_releases BEFORE UPDATE OR DELETE ON releases FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_releases_truncate BEFORE TRUNCATE ON releases FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_predictions BEFORE UPDATE OR DELETE ON predictions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_predictions_truncate BEFORE TRUNCATE ON predictions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_job_events BEFORE UPDATE OR DELETE ON job_events FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_job_events_truncate BEFORE TRUNCATE ON job_events FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_audit_events BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_audit_events_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_verdicts BEFORE UPDATE OR DELETE ON rule_verdicts FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_rule_verdicts_truncate BEFORE TRUNCATE ON rule_verdicts FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_price_plans BEFORE UPDATE OR DELETE ON price_plans FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_price_plans_truncate BEFORE TRUNCATE ON price_plans FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_feedback BEFORE UPDATE OR DELETE ON feedback FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_feedback_truncate BEFORE TRUNCATE ON feedback FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- 产物字节身份不可变；状态只能 staged→committed/quarantined，committed→quarantined，不删除。
CREATE FUNCTION guard_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'append_only:artifacts' USING ERRCODE='integrity_constraint_violation'; END IF;
 IF NEW.id<>OLD.id OR NEW.sha256<>OLD.sha256 OR NEW.object_key<>OLD.object_key OR NEW.byte_size<>OLD.byte_size OR NEW.media_type<>OLD.media_type OR NEW.contract_version<>OLD.contract_version OR NEW.created_at<>OLD.created_at
 THEN RAISE EXCEPTION 'immutable_artifact_identity' USING ERRCODE='integrity_constraint_violation'; END IF;
 IF NOT (OLD.status=NEW.status OR (OLD.status='staged' AND NEW.status IN ('committed','quarantined')) OR (OLD.status='committed' AND NEW.status='quarantined'))
 THEN RAISE EXCEPTION 'invalid_artifact_transition:%->%',OLD.status,NEW.status USING ERRCODE='integrity_constraint_violation'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER artifacts_guard BEFORE UPDATE OR DELETE ON artifacts FOR EACH ROW EXECUTE FUNCTION guard_artifact();
CREATE TRIGGER artifacts_no_truncate BEFORE TRUNCATE ON artifacts FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();

-- 发布必须引用同一方法包且通过的验证；业务环境另要求业务用途验证。
CREATE FUNCTION check_release_validation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM validations v WHERE v.id=NEW.validation_id AND v.bundle_id=NEW.bundle_id AND v.status='passed'
   AND (NEW.environment<>'business' OR v.purpose IN ('engineering_assist','technical_total_business')))
 THEN RAISE EXCEPTION 'release_validation_mismatch' USING ERRCODE='integrity_constraint_violation'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER release_validation_match BEFORE INSERT ON releases FOR EACH ROW EXECUTE FUNCTION check_release_validation();

-- 任务状态只能前进；终态不可回到运行态（重试由新 attempt 经 queued 显式表达，仅限 failed→queued）。
CREATE FUNCTION guard_job_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id<>OLD.id OR NEW.project_id<>OLD.project_id OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id OR NEW.bundle_id IS DISTINCT FROM OLD.bundle_id OR NEW.kind<>OLD.kind OR NEW.purpose<>OLD.purpose
    OR NEW.input_sha256<>OLD.input_sha256 OR NEW.input_json IS DISTINCT FROM OLD.input_json OR NEW.idempotency_key<>OLD.idempotency_key
 THEN RAISE EXCEPTION 'immutable_job_input' USING ERRCODE='integrity_constraint_violation'; END IF;
 IF OLD.state IN ('succeeded','cancelled') AND NEW.state<>OLD.state THEN RAISE EXCEPTION 'terminal_job_state' USING ERRCODE='integrity_constraint_violation'; END IF;
 IF NEW.attempt<OLD.attempt THEN RAISE EXCEPTION 'attempt_regressed' USING ERRCODE='integrity_constraint_violation'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER jobs_guard BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION guard_job_state();

-- 数据库角色（NOLOGIN 模板；部署时 GRANT 给具体登录账号）。API 与 worker 分权，worker 不读身份、会话、上传与成员表。
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_api') THEN CREATE ROLE app_api NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='app_worker') THEN CREATE ROLE app_worker NOLOGIN; END IF;
END $$;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA public TO app_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_api;
GRANT SELECT ON projects,artifacts,files,file_versions,parses,evidence,rule_packages,rule_items,fact_sets,fact_items,input_snapshots,snapshot_files,reviews,findings,finding_states,rule_verdicts,revisions,dataset_snapshots,dataset_members,experiments,model_bundles,validations,releases,release_routes,jobs,predictions,job_events,index_builds TO app_worker;
GRANT INSERT ON artifacts,parses,evidence,rule_packages,rule_items,reviews,findings,finding_states,rule_verdicts,predictions,job_events,index_builds,outbox_events,processed_messages,revisions TO app_worker;
-- 自动流水线由 worker 在任务完成后推进：冻结输入、派发下一步任务并留审计
GRANT INSERT ON jobs,input_snapshots,snapshot_files,audit_events TO app_worker;
GRANT UPDATE (state,revision,analysis_requested_at) ON projects TO app_worker;  -- 自动评审推进项目状态、用掉“开始评审”的要求
GRANT DELETE ON idempotency_keys TO app_api;  -- 仅用于过期清理
GRANT DELETE ON release_routes TO app_api;  -- 撤下发布路由（运维命令），预测回到未校准
GRANT UPDATE (status) ON artifacts TO app_worker;
GRANT UPDATE (state,stage,worker_id,lease_token_hash,lease_until,attempt,dispatched_at,dispatch_count,output_artifact_id,error_code,coverage_json,finished_at) ON jobs TO app_worker;
GRANT UPDATE (state,chunk_count,finished_at,error_code) ON index_builds TO app_worker;
GRANT UPDATE (published_at,publish_attempts,last_error) ON outbox_events TO app_worker;
GRANT SELECT ON outbox_events,processed_messages TO app_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_worker;
