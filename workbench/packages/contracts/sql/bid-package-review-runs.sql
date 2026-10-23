-- Explicit declared-scope execution; historical preparation/readiness records remain immutable.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_review_runs(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 execution_input_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 operation_id uuid NOT NULL UNIQUE,
 input_manifest jsonb NOT NULL,
 input_digest sha256 NOT NULL,
 execution_key sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(bid_id,execution_input_id) REFERENCES bid_package_execution_inputs(bid_id,id),
 FOREIGN KEY(bid_id,operation_id) REFERENCES operations(bid_id,id),
 UNIQUE(bid_id,id), UNIQUE(bid_id,id,operation_id), UNIQUE(bid_id,input_digest),
 UNIQUE(bid_id,execution_key),
 CHECK(encode(sha256(convert_to(package_canonical_json(input_manifest),'UTF8')),'hex')=input_digest)
);
CREATE INDEX bid_package_review_run_history ON bid_package_review_runs(bid_id,execution_input_id,created_at,id);
-- The worker can verify a saved dependency-plan ACK without reading unrelated commands.
CREATE VIEW bid_package_dependency_plan_command_receipts AS
 SELECT c.id,c.actor_id,c.command_kind,c.target_id,c.request_digest,c.response
 FROM commands c JOIN bid_package_dependency_plans p ON p.command_id=c.id
 WHERE c.command_kind='package-dependency-plan-save';
CREATE TABLE bid_package_review_results(
 run_id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 operation_id uuid NOT NULL UNIQUE,
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(bid_id,run_id,operation_id) REFERENCES bid_package_review_runs(bid_id,id,operation_id),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_review_runs
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_review_results
 FOR EACH ROW EXECUTE FUNCTION append_only();

-- Same semantics as packages/domain/package_scope_review_identity.py. Receipt IDs
-- remain in input_manifest; saving equivalent preparation/plan/declaration receipts
-- does not constitute a new paid execution. This function does not admit live use.
CREATE FUNCTION bid_scope_review_execution_key(input_value jsonb) RETURNS design.sha256
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,design AS $$
DECLARE original_binding jsonb; scope_refs jsonb; reference_row jsonb; scope_manifest jsonb;
 scope_binding jsonb; projected_scopes jsonb:='[]'::jsonb; semantic_key jsonb;
 wanted_fact_items jsonb; wanted_item_digest text; selected_total integer;
BEGIN
 original_binding:=input_value#>'{execution_input,identity,binding}';
 scope_refs:=input_value#>'{fact_admission,fact_declarations}';
 IF jsonb_typeof(original_binding) IS DISTINCT FROM 'object'
 OR jsonb_typeof(scope_refs) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'package_review_execution_key_shape' USING ERRCODE='23514'; END IF;
 SELECT p.manifest#>'{usage,manifest,selected}' INTO wanted_fact_items
 FROM design.bid_package_dependency_plans p
 WHERE p.bid_id=(input_value#>>'{scope,bid_id}')::uuid
 AND p.execution_input_id=(input_value#>>'{execution_input,id}')::uuid
 AND p.id=(input_value#>>'{dependency_plan,id}')::uuid
 AND p.digest=input_value#>>'{dependency_plan,digest}';
 IF jsonb_typeof(wanted_fact_items) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'package_review_execution_key_plan' USING ERRCODE='23514'; END IF;
 selected_total:=jsonb_array_length(scope_refs);
 IF selected_total<>jsonb_array_length(wanted_fact_items)
 OR selected_total<>(SELECT count(DISTINCT x->>'fact_id') FROM jsonb_array_elements(scope_refs) x)
 OR selected_total<>(SELECT count(DISTINCT x->>'declaration_id') FROM jsonb_array_elements(scope_refs) x)
 OR (selected_total=0) IS DISTINCT FROM
 (input_value->>'selected_facts_digest'=encode(sha256(convert_to('[]','UTF8')),'hex')) THEN
  RAISE EXCEPTION 'package_review_execution_key_facts' USING ERRCODE='23514'; END IF;
 FOR reference_row IN SELECT x FROM jsonb_array_elements(scope_refs) x ORDER BY x->>'fact_id' LOOP
  IF NOT design.package_json_keys(reference_row,ARRAY['fact_id','declaration_id','declaration_digest']) THEN
   RAISE EXCEPTION 'package_review_execution_key_reference' USING ERRCODE='23514'; END IF;
  SELECT s.manifest INTO scope_manifest FROM design.bid_package_fact_scopes s
  WHERE s.bid_id=(input_value#>>'{scope,bid_id}')::uuid
  AND s.execution_input_id=(input_value#>>'{execution_input,id}')::uuid
  AND s.fact_id=(reference_row->>'fact_id')::uuid
  AND s.id=(reference_row->>'declaration_id')::uuid
  AND s.digest=reference_row->>'declaration_digest';
  scope_binding:=scope_manifest->'binding';
  SELECT x->>'fact_item_digest' INTO wanted_item_digest
  FROM jsonb_array_elements(wanted_fact_items) x WHERE x->>'fact_id'=reference_row->>'fact_id';
  IF scope_manifest IS NULL OR scope_manifest->>'action' IS DISTINCT FROM 'bind'
  OR scope_binding->>'fact_id' IS DISTINCT FROM reference_row->>'fact_id'
  OR scope_binding->>'execution_input_id' IS DISTINCT FROM input_value#>>'{execution_input,id}'
  OR scope_binding->>'execution_input_digest' IS DISTINCT FROM input_value#>>'{execution_input,digest}'
  OR scope_binding-ARRAY['execution_input_id','execution_input_digest','facts_digest','fact_set_id','fact_id','fact_item_digest','proof_digest']
   IS DISTINCT FROM original_binding
  OR wanted_item_digest IS NULL OR scope_binding->>'fact_item_digest' IS DISTINCT FROM wanted_item_digest THEN
   RAISE EXCEPTION 'package_review_execution_key_declaration' USING ERRCODE='23514'; END IF;
  projected_scopes:=projected_scopes||jsonb_build_array(jsonb_build_object(
   'fact_id',reference_row->'fact_id','action',scope_manifest->'action','subject',scope_manifest->'subject',
   'binding',scope_binding-ARRAY['execution_input_id','execution_input_digest']));
 END LOOP;
 semantic_key:=jsonb_build_object(
  'version','package-scope-review-dedup/1','purpose',input_value->'purpose',
  'original_binding',original_binding,'model_input_digest',input_value->'model_input_digest',
  'method_digest',input_value#>'{executor_method,digest}',
  'selected_facts_digest',input_value->'selected_facts_digest',
  'fact_admission_policy_digest',input_value#>'{fact_admission,policy_digest}',
  'fact_scope_bindings',projected_scopes,'rerun',input_value#>'{execution_input,identity,rerun}');
 RETURN encode(sha256(convert_to(design.package_canonical_json(semantic_key),'UTF8')),'hex')::design.sha256;
END $$;

CREATE FUNCTION bid_scope_review_run_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE p design.bid_package_execution_inputs; f design.bid_package_review_inputs;
 d design.bid_package_dependency_plans; o design.operations; m jsonb; ack jsonb; body jsonb; k text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_review_run_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO p FROM design.bid_package_execution_inputs WHERE bid_id=NEW.bid_id AND id=NEW.execution_input_id;
 SELECT * INTO f FROM design.bid_package_review_inputs WHERE bid_id=NEW.bid_id AND id=p.frozen_input_id;
 m:=NEW.input_manifest;
 SELECT * INTO d FROM design.bid_package_dependency_plans
 WHERE bid_id=NEW.bid_id AND execution_input_id=NEW.execution_input_id AND id=(m#>>'{dependency_plan,id}')::uuid;
 SELECT * INTO o FROM design.operations WHERE bid_id=NEW.bid_id AND id=NEW.operation_id;
 IF p.id IS NULL OR f.id IS NULL OR d.id IS NULL OR o.id IS NULL THEN
  RAISE EXCEPTION 'package_review_run_parent' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m,ARRAY['version','purpose','scope','frozen_input','execution_input','dependency_plan','usage_digest','selected_facts_digest','fact_admission','inventory_proof_digest','executor_method','model_input_digest','limitations'])
 OR m->>'version' IS DISTINCT FROM 'package-scope-review-input/1'
 OR m->>'purpose' IS DISTINCT FROM 'prebid_compliance'
 OR NOT design.package_json_keys(m->'scope',ARRAY['bid_id','package_id','revision_id','inventory_id'])
 OR m->'execution_input' IS DISTINCT FROM jsonb_build_object('id',p.id,'digest',p.digest,'identity',p.manifest->'identity')
 OR m->'frozen_input' IS DISTINCT FROM jsonb_build_object('id',f.id,'digest',f.digest,'input_digest',f.manifest->'input_digest','evidence_digest',f.manifest->'evidence_digest')
 OR m->'dependency_plan' IS DISTINCT FROM jsonb_build_object('id',d.id,'digest',d.digest)
 OR m->>'usage_digest' IS DISTINCT FROM d.manifest#>>'{usage,digest}'
 OR m->>'selected_facts_digest' IS DISTINCT FROM d.manifest#>>'{usage,manifest,selected_facts_digest}'
 OR m->'limitations' IS DISTINCT FROM '["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"]'::jsonb THEN
  RAISE EXCEPTION 'package_review_run_binding' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['bid_id','package_id','revision_id','inventory_id'] LOOP
  IF m->'scope'->k IS DISTINCT FROM p.manifest->k THEN
   RAISE EXCEPTION 'package_review_run_scope' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT design.package_json_keys(m->'fact_admission',ARRAY['content_digest','proofs_digest','policy_digest','fact_declarations'])
 OR jsonb_typeof(m#>'{fact_admission,fact_declarations}') IS DISTINCT FROM 'array'
 OR NOT design.package_json_keys(m->'executor_method',ARRAY['profile','digest'])
 OR m#>>'{executor_method,profile,engine}' IS DISTINCT FROM 'package-review/1'
 OR m#>>'{executor_method,profile,purpose}' IS DISTINCT FROM 'prebid_compliance'
 OR m#>'{executor_method,profile,formal_scoring_eligible}' IS DISTINCT FROM 'false'::jsonb
 OR m#>'{executor_method,profile,submission_eligible}' IS DISTINCT FROM 'false'::jsonb
 OR m#>>'{executor_method,digest}' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(m#>'{executor_method,profile}'),'UTF8')),'hex')
 OR d.manifest#>>'{assessment,manifest,dependency_review_status}' IS DISTINCT FROM 'declared' THEN
  RAISE EXCEPTION 'package_review_run_method' USING ERRCODE='23514'; END IF;
 IF NEW.execution_key IS DISTINCT FROM design.bid_scope_review_execution_key(m) THEN
  RAISE EXCEPTION 'package_review_execution_key_mismatch' USING ERRCODE='23514'; END IF;
 IF o.command_id IS DISTINCT FROM NEW.command_id OR o.kind IS DISTINCT FROM 'package-scope-review'
 OR o.handler_version IS DISTINCT FROM 'package-review/1' OR o.input_digest IS DISTINCT FROM NEW.input_digest
 OR o.state IS DISTINCT FROM 'queued' THEN
  RAISE EXCEPTION 'package_review_run_operation' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM design.operation_steps s WHERE s.operation_id=o.id)<>1
 OR NOT EXISTS(SELECT 1 FROM design.operation_steps s WHERE s.operation_id=o.id
 AND s.step_key='scope-judgment' AND s.input_digest=NEW.input_digest AND s.handler_version='package-review/1'
 AND s.required AND s.depends_on=ARRAY[]::text[] AND s.dispatch_generation=1)
 OR NOT EXISTS(SELECT 1 FROM design.outbox x WHERE x.operation_id=o.id AND x.topic='tender.task.review.v1'
 AND x.deduplication_key=o.id::text||':scope-judgment:1'
 AND x.payload->>'operation_id'=o.id::text AND x.payload->>'bid_id'=NEW.bid_id::text
 AND x.payload->>'payload_ref'=NEW.id::text AND x.payload->>'step_key'='scope-judgment'
 AND x.payload->>'input_digest'=NEW.input_digest AND x.payload->>'handler_version'='package-review/1') THEN
  RAISE EXCEPTION 'package_review_run_dispatch' USING ERRCODE='23514'; END IF;
 body:=jsonb_build_object('execution_input_digest',p.digest,'dependency_plan_id',d.id,'dependency_plan_digest',d.digest);
 SELECT c.response INTO ack FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id
 AND c.command_kind='package-scope-review-start' AND c.target_id=p.id
 AND c.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',body,'if_match',NULL)),'UTF8')),'hex');
 IF ack IS NULL OR ack->>'status' IS DISTINCT FROM '202' OR ack->'headers' IS DISTINCT FROM '{}'::jsonb
 OR ack#>>'{body,kind}' IS DISTINCT FROM 'package_review_run'
 OR ack#>>'{body,id}' IS DISTINCT FROM NEW.id::text OR ack#>>'{body,actor_id}' IS DISTINCT FROM NEW.actor_id::text
 OR ack#>>'{body,input_digest}' IS DISTINCT FROM NEW.input_digest
 OR ack#>>'{body,execution_input_id}' IS DISTINCT FROM p.id::text
 OR ack#>>'{body,execution_input_digest}' IS DISTINCT FROM p.digest
 OR ack#>>'{body,dependency_plan_id}' IS DISTINCT FROM d.id::text
 OR ack#>>'{body,dependency_plan_digest}' IS DISTINCT FROM d.digest
 OR ack#>'{body,scope}' IS DISTINCT FROM m->'scope'
 OR ack#>>'{body,operation,id}' IS DISTINCT FROM o.id::text
 OR ack#>>'{body,operation,state}' IS DISTINCT FROM 'queued'
 OR ack#>'{body,result}' IS DISTINCT FROM 'null'::jsonb THEN
  RAISE EXCEPTION 'package_review_run_ack' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id
 AND a.actor_id=NEW.actor_id AND a.bid_id=NEW.bid_id AND a.event_type='package.scope_review.started'
 AND a.payload=jsonb_build_object('run_id',NEW.id,'operation_id',o.id,'input_digest',NEW.input_digest,'execution_input_id',p.id,'dependency_plan_id',d.id)) THEN
  RAISE EXCEPTION 'package_review_run_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER package_review_run_complete AFTER INSERT ON bid_package_review_runs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_scope_review_run_guard();

CREATE FUNCTION bid_scope_review_result_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE r design.bid_package_review_runs; o design.operations; m jsonb; i jsonb; root jsonb; expected jsonb; k text; total integer;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_review_result_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO r FROM design.bid_package_review_runs WHERE bid_id=NEW.bid_id AND id=NEW.run_id AND operation_id=NEW.operation_id;
 SELECT * INTO o FROM design.operations WHERE bid_id=NEW.bid_id AND id=NEW.operation_id;
 m:=NEW.manifest; i:=r.input_manifest;
 SELECT f.evidence_text::jsonb INTO root FROM design.bid_package_review_inputs f
 WHERE f.bid_id=NEW.bid_id AND f.id=(i#>>'{frozen_input,id}')::uuid;
 IF r.id IS NULL OR o.id IS NULL OR o.kind IS DISTINCT FROM 'package-scope-review'
 OR o.handler_version IS DISTINCT FROM 'package-review/1' OR o.input_digest IS DISTINCT FROM r.input_digest
 OR o.state IS DISTINCT FROM 'succeeded' THEN
  RAISE EXCEPTION 'package_review_result_operation' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m,ARRAY['version','kind','purpose','run_id','bid_id','input_digest','execution_input_id','execution_input_digest','execution_digest','dependency_plan_id','dependency_plan_digest','method_digest','scope','submitted_documents','requirement_count','matrix_coverage','overall_coverage','quality_status','inventory_complete','formal_scoring_eligible','submission_eligible','limitations','counts','matrix'])
 OR m->>'version' IS DISTINCT FROM 'package-scope-review-result/1'
 OR m->>'kind' IS DISTINCT FROM 'declared_package_scope_review' OR m->>'purpose' IS DISTINCT FROM 'prebid_compliance'
 OR m->>'run_id' IS DISTINCT FROM NEW.run_id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'input_digest' IS DISTINCT FROM r.input_digest OR m->'scope' IS DISTINCT FROM i->'scope'
 OR m->>'execution_input_id' IS DISTINCT FROM i#>>'{execution_input,id}'
 OR m->>'execution_input_digest' IS DISTINCT FROM i#>>'{execution_input,digest}'
 OR m->>'execution_digest' IS DISTINCT FROM i#>>'{execution_input,identity,execution_digest}'
 OR m->>'dependency_plan_id' IS DISTINCT FROM i#>>'{dependency_plan,id}'
 OR m->>'dependency_plan_digest' IS DISTINCT FROM i#>>'{dependency_plan,digest}'
 OR m->>'method_digest' IS DISTINCT FROM i#>>'{executor_method,digest}' THEN
  RAISE EXCEPTION 'package_review_result_binding' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['inventory_complete','formal_scoring_eligible','submission_eligible'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'package_review_result_never_qualified' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF m->>'overall_coverage' IS DISTINCT FROM 'partial' OR m->>'quality_status' IS DISTINCT FROM 'not_measured'
 OR NOT (m->'limitations' @> '["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"]'::jsonb)
 OR jsonb_typeof(m->'matrix') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'package_review_result_coverage' USING ERRCODE='23514'; END IF;
 total:=jsonb_array_length(m->'matrix');
 IF total NOT BETWEEN 1 AND 400 OR (m->>'requirement_count')::integer IS DISTINCT FROM total
 OR total<>(SELECT count(DISTINCT x->>'requirement_id') FROM jsonb_array_elements(m->'matrix') x)
 OR NOT design.package_json_keys(m->'counts',ARRAY['satisfied','violated','not_found','unable_to_judge','not_applicable']) THEN
  RAISE EXCEPTION 'package_review_result_matrix' USING ERRCODE='23514'; END IF;
 IF total IS DISTINCT FROM jsonb_array_length(root#>'{selection,inventory,manifest,requirements}')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(m->'matrix') x WHERE
 x->>'verdict' IS NULL OR x->>'verdict' NOT IN('satisfied','violated','not_found','unable_to_judge','not_applicable')
 OR x->>'human_review_state' IS DISTINCT FROM 'unreviewed'
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(root#>'{selection,inventory,manifest,requirements}') original
 WHERE x->>'requirement_id'=original->>'rule_id'
 AND x->>'requirement_digest'=original->>'requirement_digest'
 AND x->>'rule_digest'=original->>'rule_digest'
 AND x->>'rule_kind'=original#>>'{rule_snapshot,kind}'
 AND x->>'requirement_statement'=original#>>'{rule_snapshot,statement}'
 AND x->>'applicability'=original#>>'{requirement,applicability}'
 AND x->'target_part_ids'=original#>'{requirement,target_part_ids}'))
 OR m->>'matrix_coverage' IS DISTINCT FROM (CASE WHEN EXISTS(
 SELECT 1 FROM jsonb_array_elements(m->'matrix') x WHERE x->>'verdict'='unable_to_judge') THEN 'partial' ELSE 'complete' END) THEN
  RAISE EXCEPTION 'package_review_result_inventory' USING ERRCODE='23514'; END IF;
 SELECT jsonb_agg(jsonb_build_object('package_role',d->'package_role','member_id',d->'member_id',
 'document_version_id',d->'document_version_id','parse_run_id',d->'parse_id','file_digest',d->'digest',
 'page_count',d->'page_count','parts',member->'parts','evidence_count',jsonb_array_length(d->'blocks')) ORDER BY ord)
 INTO expected FROM jsonb_array_elements(root->'documents') WITH ORDINALITY docs(d,ord)
 JOIN LATERAL jsonb_array_elements(root->'selection'->(d->>'package_role')->'manifest'->'members') member
 ON member->>'member_id'=d->>'member_id';
 IF m->'submitted_documents' IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'package_review_result_documents' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['satisfied','violated','not_found','unable_to_judge','not_applicable'] LOOP
  IF (m->'counts'->>k)::integer IS DISTINCT FROM (SELECT count(*) FROM jsonb_array_elements(m->'matrix') x WHERE x->>'verdict'=k) THEN
   RAISE EXCEPTION 'package_review_result_counts' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM design.step_receipts s WHERE s.operation_id=o.id AND s.step_key='scope-judgment'
 AND s.input_digest=r.input_digest AND s.state='succeeded')
 OR NOT EXISTS(SELECT 1 FROM design.effect_receipts e WHERE e.operation_id=o.id AND e.effect_key='scope-judgment'
 AND e.result->>'result_ref'=r.id::text AND e.result->>'result_digest'=NEW.digest
 AND e.result->>'input_digest'=r.input_digest AND e.result->>'method_digest'=m->>'method_digest') THEN
  RAISE EXCEPTION 'package_review_result_publication' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM generate_series(1,(total+99)/100) n WHERE NOT EXISTS(
 SELECT 1 FROM design.model_calls c WHERE c.operation_id=NEW.operation_id
 AND c.logical_call_key='package-scope-judgment-'||n::text AND c.attempt_no=1 AND c.state='succeeded')) THEN
  RAISE EXCEPTION 'package_review_result_model_receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER package_review_result_complete AFTER INSERT ON bid_package_review_results
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_scope_review_result_guard();
REVOKE ALL ON FUNCTION bid_scope_review_execution_key(jsonb),bid_scope_review_run_guard(),bid_scope_review_result_guard() FROM PUBLIC;
COMMIT;
