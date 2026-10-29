-- Explicit automatic package mode. Old manual request and manifest checks remain intact.
-- Apply only after task-package-reviews.sql. No grants to Worker or PUBLIC.
SET search_path=design,public;

CREATE TABLE task_package_trigger_intents(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bids(id),
 definition_id uuid NOT NULL,
 definition_version_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 request_command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 trigger_key sha256 NOT NULL,
 trigger text NOT NULL CHECK(trigger IN('material_updated','schedule')),
 trigger_event_id uuid REFERENCES audit_entries(id),
 schedule_id uuid REFERENCES schedules(id),
 scheduled_at timestamptz,
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 input_digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,definition_id) REFERENCES task_definitions(bid_id,id),
 FOREIGN KEY(bid_id,definition_version_id) REFERENCES task_definition_versions(bid_id,id),
 UNIQUE(bid_id,id), UNIQUE(bid_id,trigger_key),
 CHECK((trigger='material_updated' AND trigger_event_id IS NOT NULL AND schedule_id IS NULL AND scheduled_at IS NULL)
    OR (trigger='schedule' AND trigger_event_id IS NULL AND schedule_id IS NOT NULL AND scheduled_at IS NOT NULL))
);
CREATE INDEX task_package_trigger_pending ON task_package_trigger_intents(bid_id,created_at,id);
CREATE TABLE task_package_trigger_resolutions(
 intent_id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 state text NOT NULL CHECK(state IN('accepted','blocked','cancelled')),
 error_code text,
 task_run_id uuid REFERENCES task_runs(id),
 reused boolean NOT NULL DEFAULT false,
 run_command_id uuid UNIQUE REFERENCES commands(id),
 request jsonb NOT NULL CHECK(jsonb_typeof(request)='object'),
 if_match text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,intent_id) REFERENCES task_package_trigger_intents(bid_id,id),
 CHECK((state='accepted' AND error_code IS NULL AND task_run_id IS NOT NULL AND run_command_id IS NOT NULL)
    OR (state IN('blocked','cancelled') AND error_code IS NOT NULL AND task_run_id IS NULL AND run_command_id IS NULL AND NOT reused))
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON task_package_trigger_intents
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON task_package_trigger_resolutions
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION task_package_trigger_intent_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE d design.task_definitions; v design.task_definition_versions; p design.commands;
 e design.audit_entries; s design.schedules; m jsonb; activation jsonb; expected_key text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'task_trigger_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO d FROM design.task_definitions WHERE id=NEW.definition_id AND bid_id=NEW.bid_id;
 SELECT * INTO v FROM design.task_definition_versions WHERE id=NEW.definition_version_id AND bid_id=NEW.bid_id;
 SELECT * INTO p FROM design.commands WHERE id=NEW.request_command_id;
 m:=NEW.manifest;
 IF d.id IS NULL OR v.id IS NULL OR p.id IS NULL OR d.paused OR d.revision<>v.revision
 OR v.definition_id<>d.id OR d.purpose<>'compliance'
 OR NOT EXISTS(SELECT FROM design.bid_profiles b WHERE b.bid_id=NEW.bid_id AND b.archived_at IS NULL AND b.phase NOT IN('closed','terminated'))
 OR octet_length(m::text)>131072
 OR NOT design.package_json_keys(m,ARRAY['schema','id','bid_id','definition_id','definition_version_id','configuration_digest','configuration','actor_id','request_command_id','trigger','trigger_key','trigger_event_id','event_snapshot_id','schedule_id','scheduled_at','accepted_at'])
 OR m->>'schema' IS DISTINCT FROM 'task-package-trigger-intent/1'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'definition_id' IS DISTINCT FROM d.id::text OR m->>'definition_version_id' IS DISTINCT FROM v.id::text
 OR m->>'configuration_digest' IS DISTINCT FROM v.digest::text OR m->'configuration' IS DISTINCT FROM v.config
 OR v.digest IS DISTINCT FROM design.task_package_digest(v.config)::design.sha256
 OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'request_command_id' IS DISTINCT FROM p.id::text
 OR m->>'trigger_key' IS DISTINCT FROM NEW.trigger_key::text OR m->>'trigger' IS DISTINCT FROM NEW.trigger
 OR m->>'trigger_event_id' IS DISTINCT FROM NEW.trigger_event_id::text
 OR m->>'schedule_id' IS DISTINCT FROM NEW.schedule_id::text
 OR (m->>'scheduled_at')::timestamptz IS DISTINCT FROM NEW.scheduled_at
 OR (m->>'accepted_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.input_digest IS DISTINCT FROM design.task_package_digest(m)::design.sha256
 OR v.config->>'schema' IS DISTINCT FROM 'task-template/1'
 OR v.config->'formal_decisions_allowed' IS DISTINCT FROM 'false'::jsonb
 OR v.config#>>'{definition,task_kind}' IS DISTINCT FROM 'denial_check'
 OR v.config#>'{definition,section_id}' IS DISTINCT FROM 'null'::jsonb
 OR v.config#>>'{definition,source_selection,mode}' IS DISTINCT FROM 'exact_package_trigger'
 OR NOT design.package_json_keys(v.config#>'{definition,source_selection}',ARRAY['mode','input'])
 OR v.config#>>'{definition,trigger,mode}' IS DISTINCT FROM NEW.trigger
 OR p.actor_id IS DISTINCT FROM NEW.actor_id OR p.target_id IS DISTINCT FROM d.id
 OR p.command_kind IS DISTINCT FROM 'task-trigger'
 OR p.idempotency_key IS DISTINCT FROM NEW.trigger_key::text
 OR p.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object('body',jsonb_build_object(
  'trigger',NEW.trigger,'event_id',NEW.trigger_event_id,'scheduled_at',NEW.scheduled_at),'if_match',NULL))::design.sha256
 THEN RAISE EXCEPTION 'task_trigger_intent_binding' USING ERRCODE='23514'; END IF;
 IF NEW.trigger='material_updated' THEN
  SELECT * INTO e FROM design.audit_entries WHERE id=NEW.trigger_event_id AND bid_id=NEW.bid_id;
  SELECT a.payload INTO STRICT activation FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id
   AND a.event_type='task.event_window_started' AND a.payload->>'definition_version_id'=v.id::text;
  IF e.id IS NULL OR e.event_type<>'materials.committed'
  OR activation->'existing_event_ids' ? e.id::text
  OR m->>'event_snapshot_id' IS DISTINCT FROM e.payload->>'snapshot_id'
  OR NOT EXISTS(SELECT FROM design.bid_profiles b JOIN design.material_snapshots ms
    ON ms.bid_id=b.bid_id AND ms.id=b.current_material_id
    WHERE b.bid_id=NEW.bid_id AND ms.id::text=e.payload->>'snapshot_id')
  OR (e.actor_id IS NOT NULL AND NEW.actor_id<>e.actor_id)
  THEN RAISE EXCEPTION 'task_trigger_event_binding' USING ERRCODE='23514'; END IF;
  expected_key:=design.task_package_digest(jsonb_build_object('event_id',e.id,'version',v.id));
 ELSE
  SELECT * INTO s FROM design.schedules WHERE id=NEW.schedule_id AND bid_id=NEW.bid_id;
  IF s.id IS NULL OR s.paused OR s.definition_id<>d.id OR s.definition_revision<>v.revision
  OR NEW.scheduled_at IS DISTINCT FROM s.next_fire_at
  OR s.cron IS DISTINCT FROM v.config#>>'{definition,trigger,cron}'
  OR s.timezone IS DISTINCT FROM v.config#>>'{definition,trigger,timezone}'
  OR NEW.scheduled_at>NEW.created_at OR NEW.created_at-NEW.scheduled_at>=interval '1 minute'
  OR m->'event_snapshot_id' IS DISTINCT FROM 'null'::jsonb
  THEN RAISE EXCEPTION 'task_trigger_schedule_binding' USING ERRCODE='23514'; END IF;
  expected_key:=design.task_package_digest(jsonb_build_object('version_id',v.id,'scheduled_at',NEW.scheduled_at,'target',NULL));
 END IF;
 IF NEW.trigger_key::text<>expected_key THEN
  RAISE EXCEPTION 'task_trigger_key_binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER task_package_trigger_intent_validate BEFORE INSERT ON task_package_trigger_intents
 FOR EACH ROW EXECUTE FUNCTION task_package_trigger_intent_guard();

CREATE FUNCTION task_package_trigger_intent_complete() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE p design.commands; expected jsonb;
BEGIN
 SELECT * INTO p FROM design.commands WHERE id=NEW.request_command_id;
 expected:=jsonb_build_object('key',NEW.trigger_key,'trigger',NEW.trigger,'event_id',NEW.trigger_event_id,
  'run_id',NULL,'reused',false,'state','pending','error_code',NULL,'intent_id',NEW.id,
  'definition_version_id',NEW.definition_version_id,'scheduled_at',NEW.scheduled_at);
 IF p.response IS DISTINCT FROM jsonb_build_object('body',expected,'status',200,'headers','{}'::jsonb)
 OR (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id AND a.command_id=p.id
  AND a.actor_id=p.actor_id AND a.event_type='task.trigger_received' AND a.payload=expected)<>1
 THEN RAISE EXCEPTION 'task_trigger_original_receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER task_package_trigger_intent_receipt AFTER INSERT ON task_package_trigger_intents
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION task_package_trigger_intent_complete();

CREATE FUNCTION task_package_trigger_resolution_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE i design.task_package_trigger_intents; p design.commands; n design.commands;
 t design.task_runs; b design.task_package_review_bindings; expected jsonb; ack jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'task_trigger_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO i FROM design.task_package_trigger_intents WHERE id=NEW.intent_id AND bid_id=NEW.bid_id;
 SELECT * INTO p FROM design.commands WHERE id=NEW.command_id;
 IF i.id IS NULL OR p.id IS NULL OR p.target_id IS DISTINCT FROM i.id
 OR p.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object('body',NEW.request,'if_match',NEW.if_match))::design.sha256
 THEN RAISE EXCEPTION 'task_trigger_resolution_parent' USING ERRCODE='23514'; END IF;
 IF NEW.state='cancelled' THEN
  IF p.command_kind IS DISTINCT FROM 'task-package-trigger-cancel'
  OR NOT design.package_json_keys(NEW.request,ARRAY['reason'])
  OR jsonb_typeof(NEW.request->'reason') IS DISTINCT FROM 'string'
  OR length(btrim(NEW.request->>'reason')) NOT BETWEEN 1 AND 1000
  OR NEW.if_match IS DISTINCT FROM format('"task-package-trigger-intent:%s:%s"',i.id,i.input_digest)
  OR NEW.error_code IS DISTINCT FROM 'TASK_TRIGGER_CANCELLED'
  THEN RAISE EXCEPTION 'task_trigger_cancel_binding' USING ERRCODE='23514'; END IF;
 ELSE
  IF p.command_kind IS DISTINCT FROM 'task-package-trigger-resolve' OR p.actor_id IS DISTINCT FROM i.actor_id
  OR NEW.if_match IS NOT NULL OR NEW.request IS DISTINCT FROM jsonb_build_object('intent_id',i.id,'intent_digest',i.input_digest)
  THEN RAISE EXCEPTION 'task_trigger_resolution_request' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.state='accepted' THEN
  SELECT * INTO t FROM design.task_runs WHERE id=NEW.task_run_id AND bid_id=NEW.bid_id;
  SELECT * INTO n FROM design.commands WHERE id=NEW.run_command_id;
  SELECT * INTO b FROM design.task_package_review_bindings WHERE task_run_id=t.id AND bid_id=i.bid_id;
  IF t.id IS NULL OR n.id IS NULL OR b.task_run_id IS NULL
  OR t.definition_version_id IS DISTINCT FROM i.definition_version_id
  OR t.frozen_manifest->>'schema' IS DISTINCT FROM 'task-package-trigger-run/1'
  OR t.frozen_manifest->'configuration' IS DISTINCT FROM i.manifest#>'{configuration,definition}'
  OR n.command_kind IS DISTINCT FROM 'task-package-trigger-run' OR n.actor_id IS DISTINCT FROM i.actor_id
  OR n.target_id IS DISTINCT FROM i.id
  OR n.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object('body',NEW.request,'if_match',NULL))::design.sha256
  OR n.response->>'status' IS DISTINCT FROM '202'
  OR n.response->'headers' IS DISTINCT FROM jsonb_build_object('Task-Run-Reused',CASE WHEN NEW.reused THEN 'true' ELSE 'false' END)
  OR n.response#>'{body,frozen_manifest}' IS DISTINCT FROM t.frozen_manifest
  OR n.response#>>'{body,id}' IS DISTINCT FROM t.id::text
  OR n.response#>>'{body,root_operation_id}' IS DISTINCT FROM t.operation_id::text
  OR (NOT NEW.reused AND (b.parent_command_id IS DISTINCT FROM n.id OR t.frozen_manifest->>'trigger_intent_id' IS DISTINCT FROM i.id::text))
  THEN RAISE EXCEPTION 'task_trigger_resolution_run' USING ERRCODE='23514'; END IF;
  IF NEW.reused AND (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=i.bid_id AND a.command_id=n.id
   AND a.actor_id=i.actor_id AND a.event_type='task.run_reused' AND a.payload=jsonb_build_object(
    'run_id',t.id,'definition_version_id',i.definition_version_id,'trigger',i.trigger,
    'trigger_event_id',i.trigger_event_id,'scheduled_at',i.scheduled_at))<>1 THEN
   RAISE EXCEPTION 'task_trigger_reuse_binding' USING ERRCODE='23514'; END IF;
  IF i.schedule_id IS NOT NULL AND NOT EXISTS(SELECT FROM design.schedule_receipts s
   WHERE s.schedule_id=i.schedule_id AND s.scheduled_at=i.scheduled_at AND s.operation_id=t.operation_id) THEN
   RAISE EXCEPTION 'task_trigger_schedule_receipt' USING ERRCODE='23514'; END IF;
 END IF;
 ack:=p.response->'body';
 expected:=jsonb_build_object('id',i.id,'bid_id',i.bid_id,'definition_id',i.definition_id,
  'definition_version_id',i.definition_version_id,'trigger',i.trigger,'trigger_event_id',i.trigger_event_id,
  'selection',i.manifest#>'{configuration,definition,source_selection,input}','input_digest',i.input_digest,
  'state',NEW.state,'error_code',NEW.error_code,'run_id',NEW.task_run_id,'run_ref',
  CASE WHEN NEW.task_run_id IS NULL THEN NULL ELSE format('/api/v1/bids/%s/task-runs/%s',i.bid_id,NEW.task_run_id) END,
  'reused',NEW.reused,'automatic_input_selection',false);
 IF p.response->>'status' IS DISTINCT FROM '200' OR p.response->'headers' IS DISTINCT FROM '{}'::jsonb
 OR (ack-'created_at'-'scheduled_at') IS DISTINCT FROM expected
 OR (ack->>'created_at')::timestamptz IS DISTINCT FROM i.created_at
 OR (ack->>'scheduled_at')::timestamptz IS DISTINCT FROM i.scheduled_at
 OR (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=i.bid_id AND a.command_id=p.id
  AND a.actor_id=p.actor_id AND a.event_type='task.package_trigger_resolved' AND a.payload=jsonb_build_object(
   'intent_id',i.id,'definition_version_id',i.definition_version_id,'state',NEW.state,'error_code',NEW.error_code,
   'run_id',NEW.task_run_id,'reused',NEW.reused,'intent_ref',format('/api/v1/bids/%s/task-package-trigger-intents/%s',i.bid_id,i.id)))<>1
 THEN RAISE EXCEPTION 'task_trigger_resolution_receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER task_package_trigger_resolution_complete AFTER INSERT ON task_package_trigger_resolutions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION task_package_trigger_resolution_guard();

-- Native package binding for the explicit automatic schema.
CREATE FUNCTION task_package_trigger_run_assert(task_id uuid) RETURNS void LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE t design.task_runs; b design.task_package_review_bindings;
 v design.task_definition_versions; d design.task_definitions; r design.bid_package_review_runs;
 o design.operations; x design.bid_package_review_results;
 p design.commands; n design.commands; m jsonb; s jsonb; ctx jsonb; native_body jsonb;
 ack jsonb; native_ack jsonb; expected_result jsonb; operation_error text;
 expected_ref text; expected_context jsonb;
 i design.task_package_trigger_intents; z design.task_package_trigger_resolutions;
BEGIN
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
 SELECT * INTO i FROM design.task_package_trigger_intents WHERE id=(m->>'trigger_intent_id')::uuid AND bid_id=t.bid_id;
 SELECT * INTO z FROM design.task_package_trigger_resolutions WHERE intent_id=i.id AND bid_id=t.bid_id;
 IF i.id IS NULL OR z.intent_id IS NULL OR z.state<>'accepted' OR z.reused
 OR z.task_run_id IS DISTINCT FROM t.id OR z.run_command_id IS DISTINCT FROM p.id
 OR i.definition_version_id IS DISTINCT FROM v.id OR i.actor_id IS DISTINCT FROM p.actor_id
 OR i.input_digest IS DISTINCT FROM design.task_package_digest(i.manifest)::design.sha256
 OR i.manifest->'configuration' IS DISTINCT FROM v.config THEN
  RAISE EXCEPTION 'task_trigger_native_intent_binding' USING ERRCODE='23514'; END IF;
 IF octet_length(m::text)>131072
 OR NOT design.package_json_keys(m,ARRAY['schema','definition_id','definition_version_id','configuration_digest','configuration','task_kind','purpose','actor_id','request_id','context','input_digest','fee_scope','trigger','trigger_event_id','scheduled_at','accepted_at','formal_decisions_allowed','package_review','trigger_intent_id'])
 OR m->>'schema' IS DISTINCT FROM 'task-package-trigger-run/1'
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
 OR m#>>'{configuration,source_selection,mode}' IS DISTINCT FROM 'exact_package_trigger'
 OR NOT design.package_json_keys(m#>'{configuration,source_selection}',ARRAY['mode','input'])
 OR m#>>'{configuration,trigger,mode}' IS DISTINCT FROM i.trigger
 OR m->>'trigger' IS DISTINCT FROM i.trigger
 OR m->>'trigger_event_id' IS DISTINCT FROM i.trigger_event_id::text
 OR (m->>'scheduled_at')::timestamptz IS DISTINCT FROM i.scheduled_at
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
  'schema','task-package-trigger-run/1','definition_version_id',v.id,'configuration_digest',v.digest,'context',ctx))
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
 OR p.command_kind IS DISTINCT FROM 'task-package-trigger-run' OR p.target_id IS DISTINCT FROM i.id
 OR m->>'actor_id' IS DISTINCT FROM p.actor_id::text OR m->>'request_id' IS DISTINCT FROM p.id::text
 OR p.request_digest IS DISTINCT FROM design.task_package_digest(jsonb_build_object(
  'body',jsonb_build_object('intent_id',i.id,'intent_digest',i.input_digest),'if_match',NULL))::design.sha256 THEN
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
 RETURN;
END $$;

CREATE OR REPLACE FUNCTION task_package_binding_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE t design.task_runs; b design.task_package_review_bindings;
 v design.task_definition_versions; d design.task_definitions; r design.bid_package_review_runs;
 o design.operations; x design.bid_package_review_results;
 p design.commands; n design.commands; m jsonb; s jsonb; ctx jsonb; native_body jsonb;
 ack jsonb; native_ack jsonb; expected_result jsonb; operation_error text;
 task_id uuid; expected_ref text; expected_context jsonb;
 trigger_task uuid; trigger_schema text; trigger_mode text; trigger_template_mode text;
BEGIN
 -- Only the new explicit mode/schema reaches the independent strict automatic guard.
 -- Every original manual branch below is retained byte-for-byte.
 IF TG_TABLE_NAME='task_runs' THEN trigger_task:=NEW.id; ELSE trigger_task:=NEW.task_run_id; END IF;
 SELECT task.frozen_manifest->>'schema',task.frozen_manifest#>>'{configuration,source_selection,mode}',
  version.config#>>'{definition,source_selection,mode}'
 INTO trigger_schema,trigger_mode,trigger_template_mode FROM design.task_runs task
 JOIN design.task_definition_versions version ON version.id=task.definition_version_id AND version.bid_id=task.bid_id
 WHERE task.id=trigger_task;
 IF trigger_schema='task-package-trigger-run/1' OR trigger_mode='exact_package_trigger' OR trigger_template_mode='exact_package_trigger' THEN
  PERFORM design.task_package_trigger_run_assert(trigger_task); RETURN NEW; END IF;
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

REVOKE ALL ON TABLE task_package_trigger_intents,task_package_trigger_resolutions FROM PUBLIC,tender_worker;
GRANT SELECT,INSERT ON task_package_trigger_intents,task_package_trigger_resolutions TO tender_api;
REVOKE ALL ON FUNCTION task_package_trigger_intent_guard(),task_package_trigger_intent_complete(),
 task_package_trigger_resolution_guard(),task_package_trigger_run_assert(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION task_package_trigger_intent_guard(),task_package_trigger_intent_complete(),
 task_package_trigger_resolution_guard(),task_package_trigger_run_assert(uuid) TO tender_api;
