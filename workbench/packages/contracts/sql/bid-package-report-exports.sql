-- Immutable derived report copies. They never adopt a submission body or modify a human decision.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_report_exports (
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 run_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 operation_id uuid NOT NULL UNIQUE,
 input_manifest jsonb NOT NULL,
 input_digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,run_id) REFERENCES bid_package_review_runs(bid_id,id),
 FOREIGN KEY(bid_id,operation_id) REFERENCES operations(bid_id,id),
 UNIQUE(bid_id,id,operation_id),
 CHECK(encode(sha256(convert_to(package_canonical_json(input_manifest),'UTF8')),'hex')=input_digest)
);
CREATE INDEX bid_package_report_directory ON bid_package_report_exports(bid_id,run_id,created_at,id);
CREATE INDEX bid_package_report_exact_input ON bid_package_report_exports(bid_id,input_digest,created_at,id);
CREATE TABLE bid_package_report_artifacts (
 export_id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 operation_id uuid NOT NULL UNIQUE,
 document_version_id uuid NOT NULL UNIQUE,
 blob_digest sha256 NOT NULL,
 gaps jsonb NOT NULL CHECK(jsonb_typeof(gaps)='array'),
 conversion_chain jsonb NOT NULL CHECK(jsonb_typeof(conversion_chain)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,export_id,operation_id) REFERENCES bid_package_report_exports(bid_id,id,operation_id),
 FOREIGN KEY(bid_id,document_version_id) REFERENCES document_versions(bid_id,id)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_report_exports
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_report_artifacts
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION bid_package_report_export_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE source_run design.bid_package_review_runs; source_result design.bid_package_review_results;
 op design.operations; m jsonb; ctx jsonb; human jsonb; expected_items jsonb; expected_ack jsonb;
 expected_payload jsonb; expected_body jsonb; k text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_report_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO source_run FROM design.bid_package_review_runs WHERE bid_id=NEW.bid_id AND id=NEW.run_id;
 SELECT * INTO source_result FROM design.bid_package_review_results WHERE bid_id=NEW.bid_id AND run_id=NEW.run_id;
 SELECT * INTO op FROM design.operations WHERE bid_id=NEW.bid_id AND id=NEW.operation_id;
 m:=NEW.input_manifest; ctx:=m->'context'; human:=ctx->'human_decisions';
 IF source_run.id IS NULL OR source_result.run_id IS NULL
 OR NOT EXISTS(SELECT 1 FROM design.operations original WHERE original.id=source_run.operation_id AND original.state='succeeded')
 OR NOT design.package_json_keys(m,ARRAY['version','context','context_digest','format','artifact_kind','formal_scoring_eligible','submission_eligible'])
 OR NOT design.package_json_keys(ctx,ARRAY['scope','frozen_input_id','execution_input_id','run_id','input_digest','result_digest','human_decisions','method','formal_scoring_eligible','submission_eligible'])
 OR m->>'version' IS DISTINCT FROM 'package-review-report-input/1'
 OR m->>'artifact_kind' IS DISTINCT FROM 'review_report'
 OR jsonb_typeof(m->'format') IS DISTINCT FROM 'string' OR m->>'format' NOT IN('docx','pdf')
 OR m->>'context_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(ctx),'UTF8')),'hex')
 OR ctx->'scope' IS DISTINCT FROM source_run.input_manifest->'scope'
 OR ctx->>'frozen_input_id' IS DISTINCT FROM source_run.input_manifest#>>'{frozen_input,id}'
 OR ctx->>'execution_input_id' IS DISTINCT FROM source_run.execution_input_id::text
 OR ctx->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR ctx->>'input_digest' IS DISTINCT FROM source_run.input_digest
 OR ctx->>'result_digest' IS DISTINCT FROM source_result.digest
 OR NOT design.package_json_keys(ctx->'method',ARRAY['version','writer_digest','reporter_digest','pdf_renderer'])
 OR ctx#>>'{method,version}' IS DISTINCT FROM 'package-review-report/1'
 OR (ctx#>>'{method,writer_digest}') IS NULL OR (ctx#>>'{method,writer_digest}') !~ '^[a-f0-9]{64}$'
 OR (ctx#>>'{method,reporter_digest}') IS NULL OR (ctx#>>'{method,reporter_digest}') !~ '^[a-f0-9]{64}$'
 OR (m->>'format'='pdf' AND jsonb_typeof(ctx#>'{method,pdf_renderer}') IS DISTINCT FROM 'object') THEN
  RAISE EXCEPTION 'package_report_input_binding' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['formal_scoring_eligible','submission_eligible'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb OR ctx->k IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'package_report_never_submission' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT jsonb_agg(jsonb_build_object('requirement_id',row->'requirement_id',
 'row_digest',encode(sha256(convert_to(design.package_canonical_json(row),'UTF8')),'hex'),
 'current',CASE WHEN d.id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object(
 'id',d.id,'digest',d.digest,'sequence_no',d.sequence_no,'actor_id',d.actor_id,
 'created_at',d.manifest->'created_at','state',d.manifest->'state','reason',d.manifest->'reason') END)
 ORDER BY row->>'requirement_id') INTO expected_items
 FROM jsonb_array_elements(source_result.manifest->'matrix') row
 LEFT JOIN design.bid_package_review_decision_heads h ON h.bid_id=NEW.bid_id AND h.run_id=NEW.run_id
 AND h.requirement_id::text=row->>'requirement_id'
 LEFT JOIN design.bid_package_review_decisions d ON d.id=h.decision_id AND d.digest=h.digest
 AND d.bid_id=h.bid_id AND d.run_id=h.run_id AND d.requirement_id=h.requirement_id AND d.sequence_no=h.sequence_no;
 IF human IS DISTINCT FROM jsonb_build_object('scope',ctx->'scope','frozen_input_id',ctx->'frozen_input_id',
 'execution_input_id',ctx->'execution_input_id','run_id',NEW.run_id,'result_digest',source_result.digest,'items',expected_items) THEN
  RAISE EXCEPTION 'package_report_human_snapshot' USING ERRCODE='23514'; END IF;
 IF op.id IS NULL OR op.command_id IS DISTINCT FROM NEW.command_id OR op.kind IS DISTINCT FROM 'package-scope-report'
 OR op.handler_version IS DISTINCT FROM 'package-report/1' OR op.state IS DISTINCT FROM 'queued'
 OR op.input_digest IS DISTINCT FROM NEW.input_digest
 OR (SELECT count(*) FROM design.operation_steps s WHERE s.operation_id=op.id)<>1
 OR NOT EXISTS(SELECT 1 FROM design.operation_steps s WHERE s.operation_id=op.id AND s.step_key='render-package-report'
 AND s.input_digest=NEW.input_digest AND s.handler_version='package-report/1' AND s.required AND cardinality(s.depends_on)=0)
 OR NOT EXISTS(SELECT 1 FROM design.outbox x WHERE x.operation_id=op.id AND x.topic='tender.task.export.v1'
 AND x.payload->>'payload_ref'=NEW.id::text AND x.payload->>'handler_version'='package-report/1'
 AND x.payload->>'step_key'='render-package-report' AND x.payload->>'input_digest'=NEW.input_digest) THEN
  RAISE EXCEPTION 'package_report_atomic_job' USING ERRCODE='23514'; END IF;
 expected_body:=jsonb_build_object('scope',ctx->'scope','frozen_input_id',ctx->'frozen_input_id',
 'execution_input_id',ctx->'execution_input_id','run_id',NEW.run_id,'input_digest',ctx->'input_digest',
 'result_digest',ctx->'result_digest','id',NEW.id,'actor_id',NEW.actor_id,
 'created_at',to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
 'context_digest',m->'context_digest','report_input_digest',NEW.input_digest,'format',m->'format','artifact_kind','review_report',
 'operation',jsonb_build_object('id',op.id,'kind',op.kind,'state',op.state,'input_digest',op.input_digest,
 'handler_version',op.handler_version,'error_code',NULL,
 'created_at',to_char(op.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'finished_at',NULL),
 'result',NULL,'formal_scoring_eligible',false,'submission_eligible',false);
 SELECT c.response INTO expected_ack FROM design.commands c WHERE c.id=NEW.command_id
 AND c.actor_id=NEW.actor_id AND c.command_kind='package-scope-report-start' AND c.target_id=NEW.run_id
 AND c.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',
 jsonb_build_object('context_digest',m->'context_digest','format',m->'format'),'if_match',NULL)),'UTF8')),'hex');
 IF expected_ack IS DISTINCT FROM jsonb_build_object('status',202,'headers','{}'::jsonb,'body',expected_body) THEN
  RAISE EXCEPTION 'package_report_command_ack' USING ERRCODE='23514'; END IF;
 expected_payload:=jsonb_build_object('export_id',NEW.id,'run_id',NEW.run_id,'operation_id',NEW.operation_id,
 'report_input_digest',NEW.input_digest,'context_digest',m->'context_digest','format',m->'format');
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.actor_id=NEW.actor_id
 AND a.bid_id=NEW.bid_id AND a.event_type='package.scope_report.started' AND a.payload=expected_payload) THEN
  RAISE EXCEPTION 'package_report_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER package_report_export_complete AFTER INSERT ON bid_package_report_exports
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_package_report_export_guard();

CREATE FUNCTION bid_package_report_artifact_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE r design.bid_package_report_exports; v design.document_versions; b design.blobs; output jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_report_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO r FROM design.bid_package_report_exports WHERE bid_id=NEW.bid_id AND id=NEW.export_id AND operation_id=NEW.operation_id;
 SELECT * INTO v FROM design.document_versions WHERE bid_id=NEW.bid_id AND id=NEW.document_version_id;
 SELECT * INTO b FROM design.blobs WHERE id=v.blob_id;
 IF r.id IS NULL OR v.id IS NULL OR v.artifact_kind IS DISTINCT FROM 'review_report'
 OR v.created_by IS DISTINCT FROM r.actor_id OR b.digest IS DISTINCT FROM NEW.blob_digest OR b.byte_size<1
 OR b.media_type IS DISTINCT FROM (CASE WHEN r.input_manifest->>'format'='pdf' THEN 'application/pdf'
 ELSE 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' END)
 OR jsonb_array_length(NEW.gaps)>100
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.gaps) g WHERE jsonb_typeof(g)<>'string' OR length(g#>>'{}')>200)
 OR NOT EXISTS(SELECT 1 FROM design.operations o WHERE o.id=NEW.operation_id AND o.bid_id=NEW.bid_id
 AND o.kind='package-scope-report' AND o.handler_version='package-report/1' AND o.input_digest=r.input_digest AND o.state='succeeded') THEN
  RAISE EXCEPTION 'package_report_artifact_binding' USING ERRCODE='23514'; END IF;
 SELECT s.output INTO output FROM design.step_receipts s WHERE s.operation_id=NEW.operation_id
 AND s.step_key='render-package-report' AND s.input_digest=r.input_digest AND s.state='succeeded';
 IF output IS NULL OR output->>'export_id' IS DISTINCT FROM NEW.export_id::text
 OR output->>'document_version_id' IS DISTINCT FROM NEW.document_version_id::text
 OR output->>'blob_digest' IS DISTINCT FROM NEW.blob_digest
 OR output->>'report_input_digest' IS DISTINCT FROM r.input_digest
 OR NOT EXISTS(SELECT 1 FROM design.effect_receipts e WHERE e.operation_id=NEW.operation_id
 AND e.effect_key='render-package-report' AND e.result=output) THEN
  RAISE EXCEPTION 'package_report_publish_receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER package_report_artifact_complete AFTER INSERT ON bid_package_report_artifacts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_package_report_artifact_guard();
REVOKE ALL ON FUNCTION bid_package_report_export_guard(),bid_package_report_artifact_guard() FROM PUBLIC;
COMMIT;
