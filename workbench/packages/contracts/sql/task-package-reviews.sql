-- One task run binds one existing native package operation and its original commands.
SET search_path=design,public;

CREATE FUNCTION task_package_digest(value jsonb) RETURNS text LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
 SELECT encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex')
$$;

CREATE TABLE task_package_review_bindings(
 task_run_id uuid PRIMARY KEY REFERENCES task_runs(id),
 bid_id uuid NOT NULL REFERENCES bids(id),
 review_run_id uuid NOT NULL,
 start_command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 parent_command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest_digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,review_run_id) REFERENCES bid_package_review_runs(bid_id,id),
 UNIQUE(bid_id,task_run_id)
);
CREATE INDEX task_package_review_native_runs ON task_package_review_bindings(bid_id,review_run_id);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON task_package_review_bindings
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION task_package_binding_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE t design.task_runs; b design.task_package_review_bindings;
 v design.task_definition_versions; d design.task_definitions; r design.bid_package_review_runs;
 o design.operations; x design.bid_package_review_results;
 p design.commands; n design.commands; m jsonb; s jsonb; ctx jsonb; native_body jsonb;
 ack jsonb; native_ack jsonb; expected_result jsonb; operation_error text;
 task_id uuid; expected_ref text; expected_context jsonb;
BEGIN
 IF TG_TABLE_NAME='task_runs' THEN
  SELECT * INTO v FROM design.task_definition_versions
   WHERE id=NEW.definition_version_id AND bid_id=NEW.bid_id;
  SELECT * INTO o FROM design.operations WHERE id=NEW.operation_id AND bid_id=NEW.bid_id;
  IF NEW.frozen_manifest->>'schema' IS DISTINCT FROM 'task-package-run/1'
   AND NEW.frozen_manifest#>>'{configuration,source_selection,mode}' IS DISTINCT FROM 'exact_package_review'
   AND v.config#>>'{definition,source_selection,mode}' IS DISTINCT FROM 'exact_package_review'
   AND o.kind IS DISTINCT FROM 'package-scope-review'
  THEN RETURN NEW; END IF;
  task_id:=NEW.id;
 ELSE task_id:=NEW.task_run_id; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'task_package_requires_read_committed' USING ERRCODE='25001'; END IF;
 SELECT * INTO t FROM design.task_runs WHERE id=task_id;
 PERFORM design.lock_worker_bid(t.bid_id);
 SELECT * INTO b FROM design.task_package_review_bindings WHERE task_run_id=t.id;
 SELECT * INTO v FROM design.task_definition_versions WHERE id=t.definition_version_id AND bid_id=t.bid_id;
 SELECT * INTO d FROM design.task_definitions WHERE id=v.definition_id AND bid_id=t.bid_id;
 SELECT * INTO r FROM design.bid_package_review_runs WHERE id=b.review_run_id AND bid_id=t.bid_id;
 SELECT * INTO o FROM design.operations WHERE id=t.operation_id AND bid_id=t.bid_id;
 SELECT * INTO x FROM design.bid_package_review_results WHERE run_id=r.id AND bid_id=t.bid_id;
 SELECT * INTO p FROM design.commands WHERE id=b.parent_command_id;
 SELECT * INTO n FROM design.commands WHERE id=b.start_command_id;
 IF t.id IS NULL OR b.task_run_id IS NULL OR v.id IS NULL OR d.id IS NULL OR r.id IS NULL
 OR p.id IS NULL OR n.id IS NULL OR o.id IS NULL OR b.bid_id IS DISTINCT FROM t.bid_id
 OR t.operation_id IS DISTINCT FROM r.operation_id OR o.kind IS DISTINCT FROM 'package-scope-review'
 OR o.input_digest IS DISTINCT FROM r.input_digest OR o.handler_version IS DISTINCT FROM 'package-review/1' THEN
  RAISE EXCEPTION 'task_package_binding_parent' USING ERRCODE='23514'; END IF;
 m:=t.frozen_manifest; s:=m#>'{configuration,source_selection,input}'; ctx:=m->'context';
 IF octet_length(m::text)>131072
 OR NOT design.package_json_keys(m,ARRAY['schema','definition_id','definition_version_id','configuration_digest','configuration','task_kind','purpose','actor_id','request_id','context','input_digest','fee_scope','trigger','trigger_event_id','scheduled_at','accepted_at','formal_decisions_allowed','package_review'])
 OR m->>'schema' IS DISTINCT FROM 'task-package-run/1'
 OR m->>'definition_id' IS DISTINCT FROM d.id::text
 OR m->>'definition_version_id' IS DISTINCT FROM v.id::text
 OR m->>'configuration_digest' IS DISTINCT FROM v.digest::text
 OR v.digest IS DISTINCT FROM design.task_package_digest(v.config)::design.sha256
 OR m->'configuration' IS DISTINCT FROM v.config->'definition'
 OR v.config->>'schema' IS DISTINCT FROM 'task-template/1'
 OR v.config->'formal_decisions_allowed' IS DISTINCT FROM 'false'::jsonb
 OR d.revision IS DISTINCT FROM v.revision OR d.paused
 OR d.purpose IS DISTINCT FROM 'compliance' OR m->>'purpose' IS DISTINCT FROM 'compliance'
 OR m->>'task_kind' IS DISTINCT FROM 'denial_check'
 OR m#>>'{configuration,task_kind}' IS DISTINCT FROM 'denial_check'
 OR m#>'{configuration,section_id}' IS DISTINCT FROM 'null'::jsonb
 OR m#>>'{configuration,source_selection,mode}' IS DISTINCT FROM 'exact_package_review'
 OR NOT design.package_json_keys(m#>'{configuration,source_selection}',ARRAY['mode','input'])
 OR m#>>'{configuration,trigger,mode}' IS DISTINCT FROM 'manual'
 OR m->>'trigger' IS DISTINCT FROM 'manual'
 OR m->'trigger_event_id' IS DISTINCT FROM 'null'::jsonb
 OR m->'scheduled_at' IS DISTINCT FROM 'null'::jsonb
 OR m->'formal_decisions_allowed' IS DISTINCT FROM 'false'::jsonb
 OR b.manifest_digest IS DISTINCT FROM design.task_package_digest(m)::design.sha256 THEN
  RAISE EXCEPTION 'task_package_template_binding' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(s,ARRAY['package_id','revision_id','inventory_id','frozen_input_id','frozen_input_digest','execution_input_id','execution_input_digest','dependency_plan_id','dependency_plan_digest','method_digest'])
 OR s IS DISTINCT FROM jsonb_build_object(
  'package_id',r.input_manifest#>'{scope,package_id}','revision_id',r.input_manifest#>'{scope,revision_id}',
  'inventory_id',r.input_manifest#>'{scope,inventory_id}',
  'frozen_input_id',r.input_manifest#>'{frozen_input,id}','frozen_input_digest',r.input_manifest#>'{frozen_input,digest}',
  'execution_input_id',r.input_manifest#>'{execution_input,id}','execution_input_digest',r.input_manifest#>'{execution_input,digest}',
  'dependency_plan_id',r.input_manifest#>'{dependency_plan,id}','dependency_plan_digest',r.input_manifest#>'{dependency_plan,digest}',
  'method_digest',r.input_manifest#>'{executor_method,digest}') THEN
  RAISE EXCEPTION 'task_package_selection_binding' USING ERRCODE='23514'; END IF;
 expected_context:=jsonb_build_object(
  'subject',jsonb_build_object('kind','bid_package')||(r.input_manifest->'scope'),
  'selection',s,'review_input_digest',r.input_digest,'model_input_digest',r.input_manifest->'model_input_digest',
  'limitations',r.input_manifest->'limitations','overall_coverage','partial',
  'formal_scoring_eligible',false,'submission_eligible',false);
 IF ctx IS DISTINCT FROM expected_context
 OR m->>'input_digest' IS DISTINCT FROM design.task_package_digest(jsonb_build_object(
  'schema','task-package-run/1','definition_version_id',v.id,'configuration_digest',v.digest,'context',ctx))
 OR m->>'fee_scope' IS DISTINCT FROM design.task_package_digest(jsonb_build_object(
  'schema','task-package-fee-scope/1','bid_id',t.bid_id,'purpose','prebid_compliance',
  'model_input_digest',r.input_manifest->'model_input_digest')) THEN
  RAISE EXCEPTION 'task_package_context_binding' USING ERRCODE='23514'; END IF;
 expected_ref:=format('/api/v1/bids/%s/packages/%s/revisions/%s/requirement-inventories/%s/frozen-review-inputs/%s/execution-inputs/%s/review-runs/%s',
  t.bid_id,s->>'package_id',s->>'revision_id',s->>'inventory_id',s->>'frozen_input_id',s->>'execution_input_id',r.id);
 IF m->'package_review' IS DISTINCT FROM jsonb_build_object(
  'run_id',r.id,'operation_id',r.operation_id,'start_command_id',n.id,
  'input_digest',r.input_digest,'method_digest',s->'method_digest','run_ref',expected_ref) THEN
  RAISE EXCEPTION 'task_package_run_binding' USING ERRCODE='23514'; END IF;
 native_body:=jsonb_build_object('execution_input_digest',s->'execution_input_digest',
  'dependency_plan_id',s->'dependency_plan_id','dependency_plan_digest',s->'dependency_plan_digest');
 native_ack:=n.response->'body';
 operation_error:=NULL;
 IF o.state='failed' THEN
  SELECT coalesce((SELECT receipt.output->>'error_code' FROM design.step_receipts receipt
   WHERE receipt.operation_id=o.id AND receipt.step_key='scope-judgment' AND receipt.input_digest=o.input_digest),
   (SELECT a.payload->>'error_code' FROM design.audit_entries a WHERE a.bid_id=t.bid_id
    AND a.payload->>'operation_id'=o.id::text AND a.event_type='operation.work_closed'
    ORDER BY a.created_at DESC,a.id DESC LIMIT 1)) INTO operation_error;
 END IF;
 IF n.command_kind IS DISTINCT FROM 'package-scope-review-start'
 OR n.actor_id IS DISTINCT FROM p.actor_id OR n.target_id IS DISTINCT FROM r.execution_input_id
 OR n.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object('body',native_body,'if_match',NULL))::design.sha256
 OR n.response->>'status' IS DISTINCT FROM '202' OR n.response->'headers' IS DISTINCT FROM '{}'::jsonb
 OR (native_ack-'created_at'-'operation'-'result') IS DISTINCT FROM jsonb_build_object(
  'kind','package_review_run','id',r.id,'actor_id',r.actor_id,'scope',r.input_manifest->'scope',
  'frozen_input_id',s->'frozen_input_id','frozen_input_digest',s->'frozen_input_digest',
  'execution_input_id',s->'execution_input_id','execution_input_digest',s->'execution_input_digest',
  'execution_digest',r.input_manifest#>'{execution_input,identity,execution_digest}',
  'dependency_plan_id',s->'dependency_plan_id','dependency_plan_digest',s->'dependency_plan_digest',
  'input_digest',r.input_digest,'method_digest',s->'method_digest')
 OR (native_ack->>'created_at')::timestamptz IS DISTINCT FROM r.created_at
 OR ((native_ack->'operation')-'created_at'-'finished_at') IS DISTINCT FROM jsonb_build_object(
  'id',o.id,'kind',o.kind,'state',o.state,'input_digest',o.input_digest,
  'handler_version',o.handler_version,'error_code',operation_error)
 OR (native_ack#>>'{operation,created_at}')::timestamptz IS DISTINCT FROM o.created_at
 OR (CASE WHEN o.finished_at IS NULL THEN native_ack#>'{operation,finished_at}' IS DISTINCT FROM 'null'::jsonb
  ELSE (native_ack#>>'{operation,finished_at}')::timestamptz IS DISTINCT FROM o.finished_at END)
 OR native_ack->'result' IS DISTINCT FROM (CASE WHEN x.run_id IS NULL THEN 'null'::jsonb
  ELSE jsonb_build_object('manifest',x.manifest,'digest',x.digest) END)
 OR (o.state='succeeded') IS DISTINCT FROM (x.run_id IS NOT NULL)
 OR p.command_kind IS DISTINCT FROM 'task-run-manual' OR p.target_id IS DISTINCT FROM d.id
 OR m->>'actor_id' IS DISTINCT FROM p.actor_id::text OR m->>'request_id' IS DISTINCT FROM p.id::text
 OR p.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object(
  'body',jsonb_build_object('rerun',false),'if_match',format('"task-template:%s:%s"',d.id,v.revision)))::design.sha256 THEN
  RAISE EXCEPTION 'task_package_command_binding' USING ERRCODE='23514'; END IF;
 expected_result:=CASE WHEN x.run_id IS NULL THEN 'null'::jsonb ELSE jsonb_build_object(
  'kind','declared_package_scope_review','run_id',r.id,'run_ref',expected_ref,
  'input_digest',r.input_digest,'result_digest',x.digest,'overall_coverage','partial',
  'formal_scoring_eligible',false,'submission_eligible',false) END;
 ack:=p.response;
 IF ack->>'status' IS DISTINCT FROM '202'
 OR ack->'headers' IS DISTINCT FROM '{"Task-Run-Reused":"false"}'::jsonb
 OR NOT design.package_json_keys(ack->'body',ARRAY['id','bid_id','definition_version_id','root_operation_id','final_operation_id','state','stage','frozen_manifest','result','error_code','formal_decisions_created','coverage'])
 OR ack#>>'{body,id}' IS DISTINCT FROM t.id::text
 OR ack#>>'{body,bid_id}' IS DISTINCT FROM t.bid_id::text
 OR ack#>>'{body,definition_version_id}' IS DISTINCT FROM v.id::text
 OR ack#>>'{body,root_operation_id}' IS DISTINCT FROM r.operation_id::text
 OR ack#>>'{body,final_operation_id}' IS DISTINCT FROM r.operation_id::text
 OR ack#>>'{body,stage}' IS DISTINCT FROM 'review'
 OR ack#>'{body,state}' IS DISTINCT FROM native_ack#>'{operation,state}'
 OR ack#>'{body,error_code}' IS DISTINCT FROM native_ack#>'{operation,error_code}'
 OR ack#>'{body,result}' IS DISTINCT FROM expected_result
 OR ack#>'{body,frozen_manifest}' IS DISTINCT FROM m
 OR ack#>'{body,formal_decisions_created}' IS DISTINCT FROM 'false'::jsonb
 OR ack#>>'{body,coverage}' IS DISTINCT FROM 'not_formal_score' THEN
  RAISE EXCEPTION 'task_package_original_ack' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT FROM design.model_calls mc JOIN design.bid_package_review_runs pending
 ON pending.operation_id=mc.operation_id WHERE pending.bid_id=t.bid_id
 AND pending.input_manifest->>'model_input_digest'=r.input_manifest->>'model_input_digest'
 AND mc.state IN('reserved','unknown')) THEN
  RAISE EXCEPTION 'task_package_unreconciled_call' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=t.bid_id AND a.command_id=p.id
 AND a.actor_id=p.actor_id AND a.event_type='task.run_created' AND a.payload=jsonb_build_object(
  'run_id',t.id,'definition_version_id',v.id,'operation_id',r.operation_id,'input_digest',m->'input_digest'))<>1 THEN
  RAISE EXCEPTION 'task_package_audit_binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER task_package_binding_complete AFTER INSERT ON task_package_review_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION task_package_binding_guard();
CREATE CONSTRAINT TRIGGER task_package_run_complete AFTER INSERT ON task_runs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION task_package_binding_guard();
REVOKE ALL ON TABLE task_package_review_bindings FROM PUBLIC,tender_worker;
GRANT SELECT,INSERT ON task_package_review_bindings TO tender_api;
REVOKE ALL ON FUNCTION task_package_digest(jsonb),task_package_binding_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION task_package_digest(jsonb),task_package_binding_guard() TO tender_api;
