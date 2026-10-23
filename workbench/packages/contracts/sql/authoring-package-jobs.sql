-- Optional B2 exact package authoring; after B1 and assistant/live-facts/intent-budget.
-- No BASE migration, no Worker business-table grants, no apply/build authority.
BEGIN;
SET search_path=design,public;

CREATE TABLE authoring_package_job_bindings(
 job_id uuid PRIMARY KEY REFERENCES assistant_jobs(id),
 task_run_id uuid NOT NULL UNIQUE REFERENCES task_runs(id),
 bid_id uuid NOT NULL REFERENCES bids(id),
 input_id uuid NOT NULL,
 input_digest sha256 NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 definition_version_id uuid NOT NULL,
 writing_plan_id uuid NOT NULL UNIQUE REFERENCES writing_plans(id),
 job_input_digest sha256 NOT NULL,
 task_manifest_digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,input_id) REFERENCES authoring_package_inputs(bid_id,id),
 FOREIGN KEY(bid_id,definition_version_id) REFERENCES task_definition_versions(bid_id,id),
 FOREIGN KEY(job_id,job_input_digest) REFERENCES assistant_jobs(id,input_digest),
 UNIQUE(bid_id,job_id)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_package_job_bindings
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE TABLE authoring_package_action_bindings(
 action_id uuid PRIMARY KEY REFERENCES proposed_actions(id),
 job_id uuid NOT NULL UNIQUE REFERENCES authoring_package_job_bindings(job_id),
 bid_id uuid NOT NULL,
 input_id uuid NOT NULL,
 input_digest sha256 NOT NULL,
 candidate_digest sha256 NOT NULL,
 action_digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,job_id) REFERENCES authoring_package_job_bindings(bid_id,job_id),
 FOREIGN KEY(bid_id,input_id) REFERENCES authoring_package_inputs(bid_id,id)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_package_action_bindings
 FOR EACH ROW EXECUTE FUNCTION append_only();

-- The first command stores a queued ACK; a later explicit reuse command may
-- store a terminal view. Both are immutable historical receipts after finish.
CREATE FUNCTION authoring_package_command_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
BEGIN
 IF OLD.command_kind='task-package-authoring-run'
  OR (TG_OP='UPDATE' AND NEW.command_kind='task-package-authoring-run') THEN
  IF TG_OP='DELETE' OR (OLD.response IS NOT NULL AND NEW IS DISTINCT FROM OLD)
   OR (to_jsonb(NEW)-'response') IS DISTINCT FROM (to_jsonb(OLD)-'response') THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_RECEIPT_IMMUTABLE' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER authoring_package_command_immutable BEFORE UPDATE OR DELETE ON commands
 FOR EACH ROW EXECUTE FUNCTION authoring_package_command_guard();

-- Immutable B1 content is already constrained against complete packages/parses.
-- Recheck every mutable authority without selecting a newer parse or package.
CREATE FUNCTION authoring_package_assert_input(selected_id uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE input design.authoring_package_inputs; x jsonb; b jsonb; target jsonb; frozen jsonb;
 actual record; decision jsonb; source jsonb; direct_ids uuid[]; authority_clock timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=selected_id;
 IF input.id IS NULL OR design.authoring_package_digest(input.manifest) IS DISTINCT FROM input.digest::text
 OR encode(sha256(convert_to(input.context_text,'UTF8')),'hex') IS DISTINCT FROM input.context_digest::text THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_INPUT_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 x=input.context_text::jsonb; b=input.manifest->'selection'; target=b->'target_section';
 PERFORM design.lock_worker_bid(input.bid_id);
 PERFORM id FROM design.drafts WHERE id=(target->>'draft_id')::uuid AND bid_id=input.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 IF NOT EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=input.bid_id AND archived_at IS NULL AND phase NOT IN('closed','terminated')) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_PROJECT_CLOSED' USING ERRCODE='23514'; END IF;
 IF x->'identity' IS DISTINCT FROM design.identity_snapshot_v2(input.bid_id) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_IDENTITY_CHANGED' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.drafts d JOIN design.draft_snapshots s ON s.bid_id=d.bid_id AND s.draft_id=d.id
  WHERE d.id=(target->>'draft_id')::uuid AND d.bid_id=input.bid_id AND d.revision=(target->>'base_draft_revision')::bigint
   AND s.id=(target->>'snapshot_id')::uuid AND s.revision=d.revision AND s.digest::text=target->>'snapshot_digest'
   AND s.manifest=x#>'{target,snapshot_manifest}')
 OR EXISTS(SELECT FROM jsonb_array_elements(x#>'{target,sections}') f
  LEFT JOIN design.sections s ON s.id=(f.value->>'section_id')::uuid AND s.bid_id=input.bid_id
  LEFT JOIN design.section_revisions r ON r.id=(f.value->>'id')::uuid AND r.section_id=s.id AND r.bid_id=input.bid_id
  WHERE s.id IS NULL OR r.id IS NULL OR s.head_revision IS DISTINCT FROM (f.value->>'revision')::bigint
   OR r.digest::text IS DISTINCT FROM f.value->>'digest' OR r.content IS DISTINCT FROM f.value->'content') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_TARGET_CHANGED' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_requirement_inventories i
  JOIN design.bid_package_requirement_heads h ON h.inventory_id=i.id
  JOIN design.bid_profiles p ON p.bid_id=i.bid_id AND p.current_rule_set_id=i.rule_set_id
  WHERE i.id=(b#>>'{package_context,inventory,id}')::uuid AND i.bid_id=input.bid_id
   AND i.digest::text=b#>>'{package_context,inventory,digest}' AND i.manifest=x#>'{inventory,record,manifest}') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_INVENTORY_CHANGED' USING ERRCODE='23514'; END IF;
 FOR frozen IN SELECT value FROM jsonb_array_elements(x#>'{inventory,record,manifest,requirements}') LOOP
  SELECT to_jsonb(dec) INTO decision FROM design.rule_items r
   LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
   LEFT JOIN design.rule_carryovers carry ON carry.bid_id=r.bid_id AND carry.new_rule_id=r.id
   JOIN design.decisions dec ON dec.id=coalesce(h.decision_id,carry.from_decision_id) AND dec.bid_id=r.bid_id
   WHERE r.id=(frozen->>'rule_id')::uuid AND r.bid_id=input.bid_id
    AND r.rule_set_id=(b#>>'{package_context,inventory,rule_set_id}')::uuid;
  IF decision IS DISTINCT FROM frozen->'decision_snapshot' OR decision->>'decision' IS DISTINCT FROM 'confirmed' THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_RULE_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT FROM design.fact_heads h WHERE h.bid_id=input.bid_id
  AND h.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid AND h.revision=(b#>>'{facts,fact_head_revision}')::bigint) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_HEAD_CHANGED' USING ERRCODE='23514'; END IF;
 FOR frozen IN SELECT value FROM jsonb_array_elements(x#>'{facts,items}') LOOP
  SELECT dec.*,h.revision AS decision_revision INTO actual FROM design.decision_heads h
   JOIN design.decisions dec ON dec.id=h.decision_id WHERE h.bid_id=input.bid_id
    AND h.object_kind='fact' AND h.object_id=(frozen#>>'{item,fact,id}')::uuid;
  IF actual.id IS NULL OR (to_jsonb(actual)-'created_at') IS DISTINCT FROM ((frozen#>'{item,decision}')-'created_at')
   OR actual.created_at IS DISTINCT FROM (frozen#>>'{item,decision,created_at}')::timestamptz THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR frozen IN SELECT value FROM jsonb_array_elements(input.manifest->'fact_declarations') LOOP
  SELECT * INTO actual FROM design.authoring_package_fact_scopes s WHERE s.input_id=input.id
   AND s.bid_id=input.bid_id AND s.fact_id=(frozen#>>'{manifest,fact_id}')::uuid ORDER BY revision DESC LIMIT 1;
  IF actual.id IS NULL OR actual.digest::text IS DISTINCT FROM frozen->>'digest'
   OR actual.manifest IS DISTINCT FROM frozen->'manifest' OR actual.manifest->>'action' IS DISTINCT FROM 'bind' THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_DECLARATION_WITHDRAWN' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT array_agg(DISTINCT (value->>'source_id')::uuid) INTO direct_ids FROM jsonb_array_elements(x->'sources');
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN
  (SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) ORDER BY h.source_id FOR UPDATE;
 IF (SELECT count(*) FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) IS DISTINCT FROM jsonb_array_length(x->'sources')::bigint
 OR (SELECT count(DISTINCT (value->>'source_id',value->>'id')) FROM jsonb_array_elements(x->'sources')) IS DISTINCT FROM jsonb_array_length(x->'sources')::bigint THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(x->'sources') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until INTO actual FROM retrieval.source_ancestors a
   JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
   WHERE a.source_id=(source->>'source_id')::uuid AND a.ancestor_id=(source->>'id')::uuid;
  IF actual.id IS NULL OR actual.revision IS NULL OR actual.valid_from IS NULL
   OR actual.kind IS DISTINCT FROM 'document' OR actual.policy_class IS DISTINCT FROM 'prebid_content'
   OR actual.document_version_id::text IS DISTINCT FROM source->>'document_version_id'
   OR actual.digest::text IS DISTINCT FROM source->>'digest' OR actual.revision IS DISTINCT FROM (source->>'revision')::bigint
   OR actual.status IS DISTINCT FROM 'published' OR actual.status IS DISTINCT FROM source->>'status'
   OR actual.known_at IS DISTINCT FROM (source->>'known_at')::timestamptz
   OR actual.valid_from IS DISTINCT FROM (source->>'valid_from')::timestamptz
   OR actual.valid_until IS DISTINCT FROM (source->>'valid_until')::timestamptz THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 authority_clock=clock_timestamp();
 IF EXISTS(SELECT FROM jsonb_array_elements(x->'sources') frozen
  JOIN retrieval.source_nodes n ON n.id=(frozen.value->>'id')::uuid
  JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE n.known_at>authority_clock OR h.valid_from>authority_clock OR h.valid_until<=authority_clock) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_EXPIRED' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_package_check_job_binding(job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE binding design.authoring_package_job_bindings; j design.assistant_jobs; t design.task_runs;
 input design.authoring_package_inputs; p design.writing_plans; v design.task_definition_versions;
 cmd design.commands; op design.operations; m jsonb; f jsonb; x jsonb; plan jsonb; target jsonb;
 request jsonb; context jsonb; proofs jsonb; identity_names text[]=ARRAY['procurement_issuer_identifier','procurement_project_identifier','procurement_lot_identifier','procurement_round_identifier','bidder_identity_identifier'];
BEGIN
 SELECT * INTO binding FROM design.authoring_package_job_bindings WHERE job_id=job;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO t FROM design.task_runs WHERE id=binding.task_run_id AND bid_id=binding.bid_id;
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=binding.input_id AND bid_id=binding.bid_id;
 SELECT * INTO p FROM design.writing_plans WHERE id=binding.writing_plan_id AND bid_id=binding.bid_id;
 SELECT * INTO v FROM design.task_definition_versions WHERE id=binding.definition_version_id AND bid_id=binding.bid_id;
 SELECT * INTO cmd FROM design.commands WHERE id=binding.command_id;
 SELECT * INTO op FROM design.operations WHERE id=j.operation_id AND bid_id=binding.bid_id;
 IF binding.job_id IS NULL OR j.id IS NULL OR t.id IS NULL OR input.id IS NULL OR p.id IS NULL OR v.id IS NULL OR cmd.id IS NULL OR op.id IS NULL
  OR j.kind IS DISTINCT FROM 'authoring' OR j.scope IS DISTINCT FROM 'project' OR j.bid_id IS DISTINCT FROM binding.bid_id
  OR j.actor_id IS DISTINCT FROM binding.actor_id OR cmd.actor_id IS DISTINCT FROM binding.actor_id
  OR j.writing_plan_id IS DISTINCT FROM p.id OR j.operation_id IS DISTINCT FROM t.operation_id
  OR t.definition_version_id IS DISTINCT FROM v.id OR input.digest IS DISTINCT FROM binding.input_digest
  OR j.input_digest IS DISTINCT FROM binding.job_input_digest OR j.origin_action_id IS NOT NULL
  OR op.command_id IS DISTINCT FROM cmd.id OR op.kind IS DISTINCT FROM 'authoring-generate'
  OR op.handler_version IS DISTINCT FROM 'authoring-generate/1'
  OR cmd.command_kind IS DISTINCT FROM 'task-package-authoring-run' OR cmd.target_id IS DISTINCT FROM v.definition_id THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_JOB_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 m=j.input_manifest; f=t.frozen_manifest; x=input.context_text::jsonb;
 target=input.manifest#>'{selection,target_section}';
 request=jsonb_build_object('section_id',target->'section_id','base_section_revision',target->'base_section_revision',
  'instruction',v.config#>'{definition,instructions}','authoring_input_id',input.id,'authoring_input_digest',input.digest,'max_tokens',2048);
 x=jsonb_set(x,'{documents}',(SELECT jsonb_agg(value-'object_key' ORDER BY ord) FROM jsonb_array_elements(x->'documents') WITH ORDINALITY d(value,ord)));
 plan=jsonb_build_object('protocol','package-authoring-plan/1','generation_mode','exact_package_authoring/1',
  'input',jsonb_build_object('id',input.id,'digest',input.digest,'context_digest',input.context_digest),
  'instruction',v.config#>'{definition,instructions}','target',target,'context',x,
  'fact_declarations',input.manifest->'fact_declarations',
  'original_content',(SELECT value->'content' FROM jsonb_array_elements(x#>'{target,sections}') WHERE value->>'id'=target->>'section_revision_id'),
  'output_policy','plain_text_single_stable_node_candidate_only','complete_package_input',true,'formal_scoring_input',false,
  'execution_policy',m#>'{plan,execution_policy}','execution_policy_digest',design.authoring_package_digest(m#>'{plan,execution_policy}'));
 context=jsonb_build_object('input',jsonb_build_object('authoring_input_id',input.id,'authoring_input_digest',input.digest),
  'context_digest',input.context_digest,'target',target,'scope',input.manifest->'scope','source_scope','exact_package_context');
 IF NOT design.package_json_keys(m,ARRAY['schema_version','kind','purpose','scope','generation_mode','job_id','bid_id','actor_id','writing_plan_id','plan','request','formal_scoring_input','logical_intent'])
  OR m->'schema_version' IS DISTINCT FROM '1'::jsonb OR m->>'kind' IS DISTINCT FROM 'authoring'
  OR m->>'purpose' IS DISTINCT FROM 'authoring' OR m->>'scope' IS DISTINCT FROM 'project'
  OR m->>'generation_mode' IS DISTINCT FROM 'exact_package_authoring/1' OR m->>'job_id' IS DISTINCT FROM j.id::text
  OR m->>'bid_id' IS DISTINCT FROM j.bid_id::text OR m->>'actor_id' IS DISTINCT FROM j.actor_id::text
  OR m->>'writing_plan_id' IS DISTINCT FROM p.id::text OR m->'plan' IS DISTINCT FROM plan OR p.plan IS DISTINCT FROM plan
  OR m->'request' IS DISTINCT FROM request OR m->'formal_scoring_input' IS DISTINCT FROM 'false'::jsonb
  OR plan#>>'{execution_policy,protocol}' IS DISTINCT FROM 'package-authoring-generation-policy/1'
  OR plan#>>'{execution_policy,generation_mode}' IS DISTINCT FROM 'exact_package_authoring/1'
  OR plan#>'{execution_policy,complete_input_required}' IS DISTINCT FROM 'true'::jsonb
  OR plan#>>'{execution_policy,provider_call_key}' IS DISTINCT FROM 'authoring.generate/1'
  OR design.authoring_package_digest(m) IS DISTINCT FROM j.input_digest::text
  OR p.section_id::text IS DISTINCT FROM target->>'section_id' OR p.base_section_revision IS DISTINCT FROM (target->>'base_section_revision')::bigint
  OR p.fact_set_id::text IS DISTINCT FROM input.manifest#>>'{selection,facts,fact_set_id}'
  OR p.rule_ids IS DISTINCT FROM ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(plan#>'{original_content,attrs,rule_ids}'))
  OR p.source_version_ids IS DISTINCT FROM ARRAY(SELECT DISTINCT (value->>'document_version_id')::uuid FROM jsonb_array_elements(x->'documents') ORDER BY (value->>'document_version_id')::uuid)
  OR op.input_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('id',j.id,'digest',j.input_digest))
  OR (SELECT count(*) FROM design.operation_steps s WHERE s.operation_id=op.id)<>1
  OR NOT EXISTS(SELECT FROM design.operation_steps s WHERE s.operation_id=op.id AND s.step_key='authoring-generate'
    AND s.input_digest=op.input_digest AND s.handler_version='authoring-generate/1' AND s.required AND s.depends_on='{}'::text[]) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_PLAN_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(f,ARRAY['schema','definition_id','definition_version_id','configuration_digest','configuration','task_kind','purpose','actor_id','request_id','context','input_digest','fee_scope','trigger','trigger_event_id','scheduled_at','accepted_at','formal_decisions_allowed','assistant_job_id','authoring_binding'])
  OR f->>'schema' IS DISTINCT FROM 'task-package-authoring-run/1'
  OR f->>'definition_id' IS DISTINCT FROM v.definition_id::text OR f->>'definition_version_id' IS DISTINCT FROM v.id::text
  OR f->>'configuration_digest' IS DISTINCT FROM v.digest::text OR v.digest::text IS DISTINCT FROM design.authoring_package_digest(v.config)
  OR f->'configuration' IS DISTINCT FROM v.config->'definition' OR v.config->>'schema' IS DISTINCT FROM 'task-template/1'
  OR f#>>'{configuration,source_selection,mode}' IS DISTINCT FROM 'exact_package_authoring'
  OR f#>'{configuration,source_selection,input}' IS DISTINCT FROM context->'input'
  OR NOT design.package_json_keys(f#>'{configuration,source_selection}',ARRAY['mode','input'])
  OR f#>>'{configuration,task_kind}' IS DISTINCT FROM 'chapter_suggestion'
  OR f#>>'{configuration,section_id}' IS DISTINCT FROM target->>'section_id'
  OR f#>>'{configuration,trigger,mode}' IS DISTINCT FROM 'manual' OR f->>'task_kind' IS DISTINCT FROM 'chapter_suggestion'
  OR f->>'purpose' IS DISTINCT FROM 'assist' OR f->>'actor_id' IS DISTINCT FROM j.actor_id::text
  OR f->>'request_id' IS DISTINCT FROM cmd.id::text OR f->'context' IS DISTINCT FROM context
  OR f->>'input_digest' IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('schema','task-package-authoring-run/1',
    'definition_version_id',v.id,'configuration_digest',v.digest,'context',context))
  OR f->>'fee_scope' IS DISTINCT FROM m#>>'{logical_intent,coarse_key}'
  OR f->>'trigger' IS DISTINCT FROM 'manual' OR f->'trigger_event_id' IS DISTINCT FROM 'null'::jsonb
  OR f->'scheduled_at' IS DISTINCT FROM 'null'::jsonb OR f->'formal_decisions_allowed' IS DISTINCT FROM 'false'::jsonb
  OR (f->>'accepted_at')::timestamptz>clock_timestamp() OR f->>'assistant_job_id' IS DISTINCT FROM j.id::text
  OR f->'authoring_binding' IS DISTINCT FROM jsonb_build_object('job_input_digest',j.input_digest,'writing_plan_id',p.id,
    'writing_plan_digest',design.authoring_package_digest(plan),'operation_id',op.id)
  OR design.authoring_package_digest(f) IS DISTINCT FROM binding.task_manifest_digest::text
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',jsonb_build_object('rerun',false),
    'if_match',format('"task-template:%s:%s"',v.definition_id,v.revision))) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_TASK_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 SELECT jsonb_agg(jsonb_build_object('id',value#>'{item,fact,id}','name',value#>'{item,fact,name}',
  'value',(value#>>'{item,fact,value_jsonb_text}')::jsonb,'decision_id',value#>'{item,decision,id}',
  'evidence_ids',(SELECT jsonb_agg(e ORDER BY e#>>'{}' COLLATE "C") FROM jsonb_array_elements(value#>'{item,fact,evidence_ids}') e),
  'basis',(value#>>'{item,decision_basis_jsonb_text}')::jsonb,'source_closure',value#>'{proof,closure}')
  ORDER BY array_position(identity_names,value#>>'{item,fact,name}')) INTO proofs
  FROM jsonb_array_elements(x#>'{facts,items}') WHERE value#>>'{item,fact,id}' IN
    (SELECT value#>>'{}' FROM jsonb_array_elements(input.manifest#>'{selection,facts,identity_fact_ids}'));
 IF m#>>'{logical_intent,target,kind}' IS DISTINCT FROM 'section' OR m#>>'{logical_intent,target,id}' IS DISTINCT FROM target->>'section_id'
  OR m#>>'{logical_intent,target,bid_id}' IS DISTINCT FROM input.bid_id::text
  OR m#>>'{logical_intent,target,purpose}' IS DISTINCT FROM 'section_draft'
  OR m#>'{logical_intent,target,proof}' IS DISTINCT FROM jsonb_build_object('canonical_project_key',x#>'{facts,canonical_project_key}',
   'bid_id',input.bid_id,'identity_authority_id',x#>'{identity,authority_id}','identity_snapshot',x->'identity',
   'fact_set_id',input.manifest#>'{selection,facts,fact_set_id}','identity_facts',proofs)
  OR m#>'{logical_intent,target,object_context,content}' IS DISTINCT FROM plan->'original_content'
  OR m#>>'{logical_intent,target,object_context,content_digest}' IS DISTINCT FROM target->>'section_digest'
  OR m#>>'{logical_intent,target,object_context,head_revision}' IS DISTINCT FROM target->>'base_section_revision'
  OR m#>>'{logical_intent,target,object_context,draft_id}' IS DISTINCT FROM target->>'draft_id' THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_IDENTITY_PROOF_INVALID' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_package_assert_job(job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE binding design.authoring_package_job_bindings; j design.assistant_jobs; i design.assistant_logical_intents; op design.operations;
BEGIN
 PERFORM design.authoring_package_check_job_binding(job);
 SELECT * INTO binding FROM design.authoring_package_job_bindings WHERE job_id=job;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO i FROM design.assistant_logical_intents WHERE job_id=job;
 PERFORM design.lock_worker_bid(binding.bid_id);
 SELECT * INTO op FROM design.operations WHERE id=j.operation_id AND bid_id=binding.bid_id FOR UPDATE;
 IF i.id IS NULL OR i.actor_id IS DISTINCT FROM binding.actor_id OR i.target IS DISTINCT FROM j.input_manifest#>'{logical_intent,target}'
  OR op.id IS NULL OR op.cancel_requested_at IS NOT NULL OR op.state NOT IN('queued','running','succeeded') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_EXECUTION_STALE' USING ERRCODE='23514'; END IF;
 PERFORM design.authoring_package_assert_input(binding.input_id);
 PERFORM design.assistant_check_target(i.target,i.actor_id);
END $$;

-- Preserve RPC identity and the complete legacy branch. Neither a client mode
-- string nor an ordinary job JSON object grants exact package authority.
CREATE OR REPLACE FUNCTION design.assistant_assert_job_authority(job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE j record; i record; target jsonb; bid uuid; proof jsonb; authority_clock timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO i FROM design.assistant_logical_intents WHERE job_id=job;
 IF j.id IS NULL OR i.id IS NULL THEN RAISE EXCEPTION 'ASSISTANT_INTENT_INVALID' USING ERRCODE='23514'; END IF;
 IF j.input_manifest->>'generation_mode'='exact_package_authoring/1'
  OR EXISTS(SELECT FROM design.authoring_package_job_bindings WHERE job_id=job) THEN
  PERFORM design.authoring_package_assert_job(job); RETURN;
 END IF;
 target=i.target;
 IF target->>'kind'<>'general' THEN
  bid=(target->>'bid_id')::uuid;
  PERFORM id FROM design.bids WHERE id=bid FOR UPDATE;
 END IF;
 IF j.scope='global' THEN PERFORM id FROM design.assistant_global_runs WHERE id=job FOR UPDATE;
 ELSE PERFORM id FROM design.operations WHERE id=j.operation_id FOR UPDATE; END IF;
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM design.assistant_check_target(target,i.actor_id);
 IF target->>'kind'='general' THEN RETURN; END IF;
 FOR proof IN SELECT value FROM jsonb_array_elements(target->'proof'->'identity_facts') LOOP
  PERFORM design.assistant_assert_live_fact(bid,proof);
 END LOOP;
 -- One final authorization instant for every already locked ancestor: an early
 -- fact's source may expire while later facts or large closures are checked.
 authority_clock=clock_timestamp();
 IF EXISTS(SELECT FROM (
   SELECT DISTINCT (ancestor->>'id')::uuid AS id FROM jsonb_array_elements(target->'proof'->'identity_facts') fact
   CROSS JOIN LATERAL jsonb_array_elements(fact->'source_closure') ancestor
  ) frozen LEFT JOIN retrieval.source_nodes n ON n.id=frozen.id
  LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE n.id IS NULL OR h.status IS DISTINCT FROM 'published' OR n.known_at>authority_clock
   OR h.valid_from>authority_clock OR h.valid_until<=authority_clock)
 THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_package_job_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE identity uuid; binding design.authoring_package_job_bindings; t design.task_runs; cmd design.commands; v design.task_definition_versions;
 j design.assistant_jobs; expected_result jsonb; expected_ack jsonb;
BEGIN
 IF TG_TABLE_NAME='authoring_package_job_bindings' THEN identity=NEW.job_id;
 ELSIF TG_TABLE_NAME='assistant_jobs' THEN
  IF NEW.input_manifest->>'generation_mode' IS DISTINCT FROM 'exact_package_authoring/1'
   AND NEW.input_manifest#>>'{plan,generation_mode}' IS DISTINCT FROM 'exact_package_authoring/1'
   AND NOT EXISTS(SELECT FROM design.authoring_package_job_bindings WHERE job_id=NEW.id) THEN RETURN NEW; END IF;
  identity=NEW.id;
 ELSE
  IF NEW.frozen_manifest->>'schema' IS DISTINCT FROM 'task-package-authoring-run/1'
   AND NEW.frozen_manifest#>>'{configuration,source_selection,mode}' IS DISTINCT FROM 'exact_package_authoring'
   AND NOT EXISTS(SELECT FROM design.task_definition_versions tv WHERE tv.id=NEW.definition_version_id AND tv.config#>>'{definition,source_selection,mode}'='exact_package_authoring') THEN RETURN NEW; END IF;
  SELECT job_id INTO identity FROM design.authoring_package_job_bindings WHERE task_run_id=NEW.id;
 END IF;
 PERFORM design.authoring_package_assert_job(identity);
 SELECT * INTO binding FROM design.authoring_package_job_bindings WHERE job_id=identity;
 SELECT * INTO t FROM design.task_runs WHERE id=binding.task_run_id;
 SELECT * INTO cmd FROM design.commands WHERE id=binding.command_id;
 SELECT * INTO v FROM design.task_definition_versions WHERE id=binding.definition_version_id;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=identity;
 -- A new wrapper, input record ID or settled fee is not a new semantic request.
 -- The complete immutable context includes the actual target and selected facts.
 IF EXISTS(SELECT FROM design.authoring_package_job_bindings other_binding
  JOIN design.authoring_package_inputs other_input ON other_input.id=other_binding.input_id AND other_input.bid_id=other_binding.bid_id
  JOIN design.assistant_jobs other_job ON other_job.id=other_binding.job_id AND other_job.bid_id=other_binding.bid_id
  WHERE other_binding.bid_id=binding.bid_id AND other_binding.job_id<>identity
   AND other_input.context_digest=(SELECT context_digest FROM design.authoring_package_inputs WHERE id=binding.input_id)
   AND design.assistant_normalize_question(other_job.input_manifest#>>'{request,instruction}')=design.assistant_normalize_question(j.input_manifest#>>'{request,instruction}')
   AND other_job.input_manifest#>>'{plan,execution_policy_digest}'=j.input_manifest#>>'{plan,execution_policy_digest}') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_DUPLICATE_SEMANTIC_JOB' USING ERRCODE='23514'; END IF;
 expected_result=jsonb_build_object('schema','task-package-authoring-result/1','job_id',j.id,'job_input_digest',j.input_digest,
  'writing_plan_id',j.writing_plan_id,'operation_id',j.operation_id,'job_ref','/api/v1/assistant/jobs/'||j.id::text,
  'section_id',j.input_manifest#>'{request,section_id}','base_section_revision',j.input_manifest#>'{request,base_section_revision}',
  'authoring_input_id',binding.input_id,'authoring_input_digest',binding.input_digest,
  'context_digest',j.input_manifest#>'{plan,input,context_digest}','publication_state','pending',
  'candidate_digest',NULL,'action_id',NULL,'action_ref',NULL,'source_scope','exact_package_context',
  'automatic_apply',false,'apply_available',false,'build_available',false);
 expected_ack=jsonb_build_object('status',202,'headers',jsonb_build_object('Task-Run-Reused','false'),
  'body',jsonb_build_object('id',t.id,'bid_id',t.bid_id,'definition_version_id',t.definition_version_id,
   'root_operation_id',t.operation_id,'final_operation_id',NULL,'state','queued','stage','execution',
   'frozen_manifest',t.frozen_manifest,'result',expected_result,'error_code',NULL,'formal_decisions_created',false,'coverage','not_formal_score'));
 IF NOT EXISTS(SELECT FROM design.task_definitions d WHERE d.id=v.definition_id AND d.bid_id=binding.bid_id AND d.revision=v.revision AND NOT d.paused AND d.purpose='assist')
 OR cmd.response IS DISTINCT FROM expected_ack
 OR cmd.response->>'status' IS DISTINCT FROM '202' OR cmd.response->'headers' IS DISTINCT FROM '{"Task-Run-Reused":"false"}'::jsonb
 OR cmd.response#>>'{body,id}' IS DISTINCT FROM t.id::text OR cmd.response#>'{body,frozen_manifest}' IS DISTINCT FROM t.frozen_manifest
 OR cmd.response#>>'{body,bid_id}' IS DISTINCT FROM t.bid_id::text OR cmd.response#>>'{body,root_operation_id}' IS DISTINCT FROM t.operation_id::text
 OR cmd.response#>>'{body,state}' IS DISTINCT FROM 'queued' OR cmd.response#>>'{body,stage}' IS DISTINCT FROM 'execution'
 OR cmd.response#>>'{body,result,schema}' IS DISTINCT FROM 'task-package-authoring-result/1'
 OR cmd.response#>>'{body,result,job_id}' IS DISTINCT FROM identity::text
 OR cmd.response#>>'{body,result,publication_state}' IS DISTINCT FROM 'pending'
 OR cmd.response#>>'{body,result,source_scope}' IS DISTINCT FROM 'exact_package_context'
 OR cmd.response#>>'{body,result,authoring_input_id}' IS DISTINCT FROM binding.input_id::text
 OR cmd.response#>>'{body,result,authoring_input_digest}' IS DISTINCT FROM binding.input_digest::text
 OR cmd.response#>'{body,result,automatic_apply}' IS DISTINCT FROM 'false'::jsonb
 OR NOT EXISTS(SELECT FROM design.assistant_budget_reservations WHERE job_id=identity AND state='held')
 OR (SELECT count(*) FROM design.audit_entries a WHERE a.command_id=cmd.id AND a.actor_id=cmd.actor_id AND a.bid_id=t.bid_id
  AND a.event_type='task.run_created' AND a.payload=jsonb_build_object('run_id',t.id,'definition_version_id',v.id,'operation_id',t.operation_id,'input_digest',t.frozen_manifest->'input_digest'))<>1 THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_ORIGINAL_ACK_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_package_binding_complete AFTER INSERT ON authoring_package_job_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_job_guard();
CREATE CONSTRAINT TRIGGER authoring_package_job_complete AFTER INSERT ON assistant_jobs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_job_guard();
CREATE CONSTRAINT TRIGGER authoring_package_task_complete AFTER INSERT ON task_runs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_job_guard();

CREATE FUNCTION authoring_package_action_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE identity uuid; binding design.authoring_package_action_bindings; job_binding design.authoring_package_job_bindings;
 action design.proposed_actions; j design.assistant_jobs; output design.assistant_outputs; publication design.assistant_publications;
 candidate jsonb; target jsonb;
BEGIN
 IF TG_TABLE_NAME='authoring_package_action_bindings' THEN identity=NEW.action_id;
 ELSIF TG_TABLE_NAME='proposed_actions' THEN
  IF NEW.payload->>'kind' IS DISTINCT FROM 'package_authoring_patch' THEN RETURN NEW; END IF;
  identity=NEW.id;
 ELSE
  IF NEW.state<>'published' OR NOT EXISTS(SELECT FROM design.authoring_package_job_bindings WHERE job_id=NEW.job_id) THEN RETURN NEW; END IF;
  identity=NEW.action_id;
 END IF;
 SELECT * INTO binding FROM design.authoring_package_action_bindings WHERE action_id=identity;
 SELECT * INTO job_binding FROM design.authoring_package_job_bindings WHERE job_id=binding.job_id;
 SELECT * INTO action FROM design.proposed_actions WHERE id=identity;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=binding.job_id;
 SELECT * INTO output FROM design.assistant_outputs WHERE job_id=j.id;
 SELECT * INTO publication FROM design.assistant_publications WHERE job_id=j.id;
 candidate=output.payload; target=j.input_manifest#>'{plan,target}';
 IF binding.action_id IS NULL OR job_binding.job_id IS NULL OR action.id IS NULL OR j.id IS NULL OR output.job_id IS NULL OR publication.job_id IS NULL
  OR binding.bid_id IS DISTINCT FROM job_binding.bid_id OR action.bid_id IS DISTINCT FROM binding.bid_id
  OR binding.input_id IS DISTINCT FROM job_binding.input_id OR binding.input_digest IS DISTINCT FROM job_binding.input_digest
  OR binding.candidate_digest IS DISTINCT FROM output.digest OR output.digest::text IS DISTINCT FROM design.authoring_package_digest(candidate)
  OR binding.action_digest IS DISTINCT FROM action.request_digest OR action.request_digest::text IS DISTINCT FROM design.authoring_package_digest(action.payload)
  OR publication.state IS DISTINCT FROM 'published' OR publication.action_id IS DISTINCT FROM action.id
  OR NOT EXISTS(SELECT FROM design.assistant_action_links l WHERE l.action_id=action.id AND l.job_id=j.id AND l.tool='authoring.apply_patch' AND l.state='pending')
  OR NOT EXISTS(SELECT FROM design.operations o WHERE o.id=j.operation_id AND o.state='succeeded' AND o.cancel_requested_at IS NULL)
  OR NOT EXISTS(SELECT FROM design.model_calls c WHERE c.id=output.project_call_id AND c.operation_id=j.operation_id AND c.state='succeeded'
    AND c.response_ref IS NOT NULL AND c.logical_call_key='authoring.generate/1' AND c.attempt_no=1)
  OR NOT EXISTS(SELECT FROM design.assistant_budget_reservations r WHERE r.job_id=j.id AND r.state='settled' AND NOT r.requires_manual_reconciliation)
  OR action.base_revision IS DISTINCT FROM (target->>'base_draft_revision')::bigint
  OR action.payload IS DISTINCT FROM jsonb_build_object('kind','package_authoring_patch','job_id',j.id,
    'input',j.input_manifest#>'{plan,input}','target',target,'candidate',candidate,'apply_available',false,'build_available',false)
  OR NOT design.package_json_keys(candidate,ARRAY['protocol','input','node_id','before_digest','replacement_text','evidence_ids'])
  OR candidate->>'protocol' IS DISTINCT FROM 'package-authoring-candidate/1' OR candidate->'input' IS DISTINCT FROM j.input_manifest#>'{plan,input}'
  OR candidate->>'node_id' IS DISTINCT FROM target->>'node_id' OR candidate->>'before_digest' IS DISTINCT FROM target->>'before_node_digest'
  OR jsonb_typeof(candidate->'replacement_text') IS DISTINCT FROM 'string' OR length(candidate->>'replacement_text')>20000
  OR jsonb_typeof(candidate->'evidence_ids') IS DISTINCT FROM 'array' OR jsonb_array_length(candidate->'evidence_ids')>500
  OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(candidate->'evidence_ids'))<>jsonb_array_length(candidate->'evidence_ids')
  OR EXISTS(SELECT FROM jsonb_array_elements(candidate->'evidence_ids') e WHERE NOT EXISTS(
    SELECT FROM jsonb_array_elements(j.input_manifest#>'{plan,context,documents}') d
    CROSS JOIN LATERAL jsonb_array_elements(d.value->'blocks') block WHERE block.value->>'id'=e.value#>>'{}')) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_ACTION_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM design.authoring_package_assert_job(j.id);
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_package_action_complete AFTER INSERT ON authoring_package_action_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_action_guard();
CREATE CONSTRAINT TRIGGER authoring_package_proposal_complete AFTER INSERT ON proposed_actions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_action_guard();
CREATE CONSTRAINT TRIGGER authoring_package_publication_complete AFTER INSERT ON assistant_publications
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_action_guard();

REVOKE ALL ON authoring_package_job_bindings,authoring_package_action_bindings FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON authoring_package_job_bindings,authoring_package_action_bindings TO tender_api;
REVOKE ALL ON FUNCTION authoring_package_assert_input(uuid),authoring_package_check_job_binding(uuid),authoring_package_assert_job(uuid),authoring_package_job_guard(),authoring_package_action_guard(),authoring_package_command_guard() FROM PUBLIC,tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION authoring_package_assert_job(uuid) TO tender_api,tender_worker;
COMMIT;
