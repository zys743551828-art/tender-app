-- Optional fresh /3 business mirrors. Existing roles/ledgers/events only.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_model_route.prepare(uuid,jsonb)') IS NULL
 OR to_regclass('material_qualification.acceptances') IS NULL
 OR EXISTS(SELECT FROM package_model_observation.events) THEN
  RAISE EXCEPTION 'business_shadow_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
ALTER TABLE package_model_observation.events ALTER COLUMN admission_id DROP NOT NULL;
ALTER TABLE package_model_observation.events ADD COLUMN intent_id uuid REFERENCES material_qualification.intents(id);
ALTER TABLE package_model_observation.events ADD CONSTRAINT observation_source_lane CHECK((admission_id IS NULL)<>(intent_id IS NULL));
CREATE TABLE package_model_observation.captures(
 id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES material_judgment_job.jobs(id),actor_id uuid NOT NULL REFERENCES design.members(id),
 profile_id uuid NOT NULL REFERENCES material_execution.profiles(id),producer_method_digest design.sha256 NOT NULL,
 mode text NOT NULL CHECK(mode IN('synthetic','live')),executor_pid integer NOT NULL,executor_login name NOT NULL,executor_backend_start timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_model_observation.capture_completions(
 capture_id uuid PRIMARY KEY REFERENCES package_model_observation.captures(id),completed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_model_admission.business_evidence_bindings(
 model_id uuid PRIMARY KEY REFERENCES package_model_admission.protocols(model_id),actor_id uuid NOT NULL REFERENCES design.members(id),
 protocol_digest design.sha256 NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,command_id uuid NOT NULL UNIQUE,
 frozen_xact xid8 NOT NULL,frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),CHECK(design.package_technical_digest(document)=digest)
);
CREATE TRIGGER immutable_capture BEFORE UPDATE OR DELETE ON package_model_observation.captures FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_capture_completion BEFORE UPDATE OR DELETE ON package_model_observation.capture_completions FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_business_binding BEFORE UPDATE OR DELETE ON package_model_admission.business_evidence_bindings FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_model_observation.captures,package_model_observation.capture_completions,package_model_admission.business_evidence_bindings FROM PUBLIC,tender_api,tender_worker;
CREATE FUNCTION package_model_observation.begin_capture(actor uuid,job uuid,profile uuid,method text,kind text,backend integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p material_execution.profiles; old package_model_observation.captures; i material_qualification.intents; identity uuid;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT intent.* INTO i FROM material_qualification.intents intent JOIN material_qualification.acceptances a ON a.intent_id=intent.id WHERE a.job_id=job;
 SELECT * INTO p FROM material_execution.profiles WHERE id=profile;
 IF EXISTS(SELECT FROM package_historical_research.test_environments e JOIN pg_database d ON d.oid=e.database_oid AND d.datname=e.database_name WHERE d.datname=current_database()) THEN kind:='synthetic'; END IF;
 IF i.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM design.lock_worker_bid(i.bid_id);
 IF kind IS NULL OR kind NOT IN('synthetic','live') OR method IS NULL OR method !~ '^[a-f0-9]{64}$'
 OR p.id IS NULL OR p.origin<>'current_prebid' OR p.database_name<>current_database() OR p.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database())
 OR NOT EXISTS(SELECT FROM material_execution.profile_heads WHERE profile_id=p.id AND enabled AND worker_login=p.worker_login)
 OR NOT (clock_timestamp()>=p.valid_from AND clock_timestamp()<p.valid_until)
 OR NOT EXISTS(SELECT FROM pg_stat_activity WHERE pid=backend AND usename=p.worker_login AND datname=current_database()) THEN
  RAISE EXCEPTION 'business_shadow_host_invalid' USING ERRCODE='55000'; END IF;
 SELECT * INTO old FROM package_model_observation.captures WHERE job_id=job;
 IF FOUND THEN
  IF (old.actor_id,old.profile_id,old.producer_method_digest::text,old.mode,old.executor_pid,old.executor_backend_start) IS DISTINCT FROM (actor,profile,method,kind,backend,(SELECT backend_start FROM pg_stat_activity WHERE pid=backend)) THEN
   RAISE EXCEPTION 'business_shadow_capture_conflict' USING ERRCODE='55000'; END IF;
  RETURN old.id;
 END IF;
 IF EXISTS(SELECT FROM material_execution.attempts WHERE job_id=job) THEN RAISE EXCEPTION 'business_shadow_prior_execution_not_live_evidence' USING ERRCODE='55000'; END IF;
 identity:=gen_random_uuid();
 INSERT INTO package_model_observation.captures VALUES(identity,job,actor,profile,method,kind,backend,p.worker_login,(SELECT backend_start FROM pg_stat_activity WHERE pid=backend),clock_timestamp());
 RETURN identity;
END $$;
CREATE FUNCTION package_model_observation.capture_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE capture package_model_observation.captures;
BEGIN
 -- Shares the existing bid lock; no new grant, sender, retry or budget bypass.
 SELECT * INTO capture FROM package_model_observation.captures WHERE job_id=NEW.job_id;
 IF FOUND AND (capture.executor_pid<>pg_backend_pid() OR capture.executor_login<>session_user OR capture.executor_backend_start IS DISTINCT FROM (SELECT backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()) OR capture.profile_id<>NEW.profile_id
 OR EXISTS(SELECT FROM package_model_observation.capture_completions WHERE capture_id=capture.id)) THEN
  RAISE EXCEPTION 'business_shadow_executor_fence' USING ERRCODE='55000'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER business_shadow_execution_fence BEFORE INSERT ON material_execution.attempts FOR EACH ROW EXECUTE FUNCTION package_model_observation.capture_fence();
CREATE FUNCTION package_model_observation.finish_capture(actor uuid,target uuid,method text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c package_model_observation.captures;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO c FROM package_model_observation.captures WHERE id=target;
 IF c.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM design.lock_worker_bid((SELECT bid_id FROM material_judgment_job.jobs WHERE id=c.job_id));
 IF c.producer_method_digest::text IS DISTINCT FROM method OR NOT EXISTS(SELECT FROM material_execution.job_balances WHERE job_id=c.job_id AND state='completed' AND held_minor=0)
 OR EXISTS(SELECT FROM material_judgment_job.slots s LEFT JOIN material_execution.attempts a ON a.slot_id=s.id LEFT JOIN material_execution.outcomes o ON o.attempt_id=a.id
 WHERE s.job_id=c.job_id AND (a.id IS NULL OR o.attempt_id IS NULL OR a.profile_id<>c.profile_id
 OR a.document->>'execution_mode' IS DISTINCT FROM 'qualified_live' OR o.document->>'execution_mode' IS DISTINCT FROM 'qualified_live'
 OR (a.document->>'recorded_at')::timestamptz<c.created_at OR o.document->'valid_slot' IS DISTINCT FROM 'true'::jsonb
 OR o.document->>'billing_state' IS DISTINCT FROM 'usage_reported' OR o.document->'source_current_at_settlement' IS DISTINCT FROM 'true'::jsonb)) THEN
  RAISE EXCEPTION 'business_shadow_incomplete_execution' USING ERRCODE='55000'; END IF;
 INSERT INTO package_model_observation.capture_completions VALUES(target,clock_timestamp()) ON CONFLICT DO NOTHING;
 RETURN target;
END $$;
CREATE FUNCTION package_model_admission.bind_business_evidence(actor uuid,model uuid,expected text,command uuid,contract jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE p package_model_admission.protocols; old package_model_admission.business_evidence_bindings; ctx jsonb; document jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 ctx:=package_model_admission.context(model,actor);
 SELECT * INTO p FROM package_model_admission.protocols WHERE model_id=model;
 IF p.actor_id IS DISTINCT FROM actor OR p.digest::text IS DISTINCT FROM expected OR p.document->'binding' IS DISTINCT FROM ctx->'binding'
 OR NOT design.package_json_keys(contract,ARRAY['schema','producer_method_digest','material_contract','observation_schema','route_command_schema'])
 OR contract->>'schema' IS DISTINCT FROM 'package-business-evidence-binding/1'
 OR contract->>'material_contract' IS DISTINCT FROM 'package-history-feature-handoff/2'
 OR contract->>'observation_schema' IS DISTINCT FROM 'package-business-shadow-result/1'
 OR contract->>'route_command_schema' IS DISTINCT FROM 'package-business-shadow-command/1'
 OR contract->>'producer_method_digest' IS NULL OR contract->>'producer_method_digest' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'business_evidence_binding_invalid' USING ERRCODE='55000'; END IF;
 document:=jsonb_build_object('schema','score-business-admission-protocol/3','protocol',p.document,'protocol_digest',p.digest,'evidence_contract',contract);
 SELECT * INTO old FROM package_model_admission.business_evidence_bindings WHERE model_id=model;
 IF FOUND THEN
  IF old.document IS DISTINCT FROM document OR old.command_id IS DISTINCT FROM command THEN RAISE EXCEPTION 'business_evidence_already_frozen' USING ERRCODE='55000'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest,'frozen_at',old.frozen_at);
 END IF;
 PERFORM pg_advisory_xact_lock(91144,1);
 IF EXISTS(SELECT FROM package_historical_research.exposures WHERE cohort_id=p.cohort_id) THEN RAISE EXCEPTION 'business_evidence_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO package_model_admission.business_evidence_bindings VALUES(model,actor,p.digest,document,design.package_technical_digest(document),command,pg_current_xact_id(),clock_timestamp());
 RETURN jsonb_build_object('document',document,'digest',design.package_technical_digest(document));
END $$;
CREATE FUNCTION package_model_observation.business_source(actor uuid,intent uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE i material_qualification.intents;j material_judgment_job.jobs;c package_model_observation.captures;
 s design.bid_package_technical_scopes; status record; parts jsonb; p jsonb; at_time timestamptz; qualification jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO i FROM material_qualification.intents WHERE id=intent;
 IF i.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM design.lock_worker_bid(i.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT job.* INTO j FROM material_judgment_job.jobs job JOIN material_qualification.acceptances a ON a.job_id=job.id AND a.job_digest=job.digest WHERE a.intent_id=intent;
 SELECT * INTO c FROM package_model_observation.captures WHERE job_id=j.id;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=i.scope_id;
 PERFORM h.record_id FROM material_qualification.heads h WHERE h.record_id=i.qualification_id FOR SHARE OF h;
 PERFORM h.worker_login FROM material_execution.profile_heads h WHERE h.profile_id=c.profile_id FOR SHARE OF h;
 SELECT * INTO status FROM material_qualification.execution_status WHERE intent_id=intent;
 SELECT document INTO qualification FROM material_qualification.records WHERE id=i.qualification_id AND digest=i.qualification_digest;
 p:=s.manifest#>'{preview,manifest}';
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN(SELECT a.ancestor_id FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.source_id WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,(p#>>'{basis,authority_revision_id}')::uuid))) ORDER BY h.source_id FOR SHARE OF h;
 at_time:=clock_timestamp();
 IF j.id IS NULL OR c.id IS NULL OR c.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM package_model_observation.capture_completions WHERE capture_id=c.id)
 OR status.qualification_state IS DISTINCT FROM 'approved' OR status.execution_state IS DISTINCT FROM 'completed'
 OR status.held_minor IS DISTINCT FROM 0 OR status.unknown_count IS DISTINCT FROM 0 OR status.unsettled_count IS DISTINCT FROM 0
 OR j.document->>'origin' IS DISTINCT FROM 'current_prebid' OR s.digest::text IS DISTINCT FROM j.document->>'scope_digest'
 OR design.package_technical_digest(s.manifest) IS DISTINCT FROM s.digest::text
 OR NOT EXISTS(SELECT FROM material_qualification.heads h JOIN material_qualification.decisions d ON d.id=h.decision_id JOIN design.members m ON m.id=d.actor_id AND m.active WHERE h.record_id=i.qualification_id AND h.revision=i.qualification_revision AND d.decision='approved')
 OR NOT (at_time>=(qualification#>>'{price,valid_from}')::timestamptz AND at_time<(qualification#>>'{price,valid_until}')::timestamptz)
 OR NOT EXISTS(SELECT FROM material_execution.profiles e JOIN material_execution.profile_heads h ON h.profile_id=e.id AND h.enabled WHERE e.id=c.profile_id AND e.valid_from<=at_time AND e.valid_until>at_time AND e.origin='current_prebid' AND e.database_name=current_database() AND e.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND e.execution_sql_method_digest::text=material_execution.native_method_digest())
 OR EXISTS(SELECT FROM jsonb_each(qualification->'evidence') proof WHERE NOT EXISTS(SELECT FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=i.bid_id AND v.id=(proof.value->>'document_version_id')::uuid AND b.digest::text=proof.value->>'digest'))
 OR NOT EXISTS(SELECT FROM design.bid_package_requirement_inventories inv WHERE inv.id=s.inventory_id AND inv.manifest->'source_snapshot'=design.bid_requirement_source_snapshot(s.revision_id,(p#>>'{basis,authority_revision_id}')::uuid))
 OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=i.bid_id)
 OR NOT EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=i.bid_id AND archived_at IS NULL AND phase NOT IN('submitted','closed','terminated'))
 OR design.identity_snapshot_v2(i.bid_id)->>'digest' IS DISTINCT FROM p#>>'{basis,identity_digest}'
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=s.package_id AND revision_id=s.revision_id AND digest::text=p#>>'{basis,package_digest}')
 OR NOT EXISTS(SELECT FROM design.bid_package_requirement_heads WHERE target_revision_id=s.revision_id AND inventory_id=s.inventory_id AND digest::text=p#>>'{basis,inventory_digest}')
 OR NOT EXISTS(SELECT FROM design.bid_package_revisions r JOIN design.bid_package_heads h ON h.revision_id=r.id WHERE r.id=(p#>>'{basis,authority_revision_id}')::uuid AND r.digest::text=p#>>'{basis,authority_digest}' AND h.digest=r.digest)
 OR NOT EXISTS(SELECT FROM design.bid_profiles b JOIN design.rule_sets r ON r.id=b.current_rule_set_id WHERE b.bid_id=i.bid_id AND r.id::text=p#>>'{basis,rule_set_id}' AND r.digest::text=p#>>'{basis,rule_set_digest}' AND r.coverage='complete') THEN
  RAISE EXCEPTION 'business_shadow_source_not_current' USING ERRCODE='55000'; END IF;
 PERFORM package_model_observation.finish_capture(actor,c.id,c.producer_method_digest);
 SELECT jsonb_agg(jsonb_build_object('attempt_id',a.id,'rule_id',slot.rule_id,'slot',slot.slot_number,'request_digest',a.document#>'{request,request_digest}',
 'raw_response_digest',encode(sha256(o.raw_response),'hex'),'response_id',o.document->'response_id','outcome_digest',o.digest) ORDER BY slot.rule_id,slot.slot_number)
 INTO parts FROM material_judgment_job.slots slot JOIN material_execution.attempts a ON a.slot_id=slot.id JOIN material_execution.outcomes o ON o.attempt_id=a.id WHERE slot.job_id=j.id;
 IF parts IS NULL OR jsonb_array_length(parts)<>(j.document->>'required_valid_slots')::integer THEN RAISE EXCEPTION 'business_shadow_slot_set_changed' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-business-shadow-source/1','mode',c.mode,'capture_id',c.id,'producer_method_digest',c.producer_method_digest,
 'intent_id',i.id,'job_id',j.id,'job_digest',j.digest,'qualification_id',i.qualification_id,'qualification_digest',i.qualification_digest,
 'bid_id',i.bid_id,'scope_id',i.scope_id,'scope_digest',s.digest,'scope_manifest',s.manifest,
 'input_digest',j.document->'material_input_digest','context_digest',j.document->'context_digest','attempts',parts,
 'originals',(SELECT jsonb_agg(jsonb_build_object('document_version_id',d->'document_version_id','digest',d->'file_digest','byte_size',d->'byte_size') ORDER BY d->>'document_version_id') FROM jsonb_array_elements(p->'documents')d));
END $$;
CREATE FUNCTION package_model_route.business_replay(actor uuid,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE e package_model_route.events; o package_model_observation.events;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO e FROM package_model_route.events WHERE command_id=(body->>'command_id')::uuid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF e.actor_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 IF e.request IS DISTINCT FROM body THEN RAISE EXCEPTION 'business_shadow_command_conflict' USING ERRCODE='55000'; END IF;
 SELECT * INTO o FROM package_model_observation.events WHERE command_id=e.observation_id;
 RETURN jsonb_build_object('schema','package-business-shadow-receipt/1','command_id',e.command_id,'route_id',e.route_id,'revision',e.revision,
 'action',e.action,'previous_model_id',e.previous_model_id,'selected_model_id',e.selected_model_id,'observation_id',e.observation_id,
 'result_digest',e.result_digest,'mode',o.source->'mode','capture_id',o.source->'capture_id','input_digest',o.result->'input_digest',
 'historical_receipt',true,'current_authority_checked',false,'business_route_changed',false,'certification_issued',false,'formal_eligibility','unavailable');
END $$;
CREATE FUNCTION package_model_route.business_prepare(actor uuid,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE old package_model_route.routes; config jsonb; target uuid; selected jsonb; src jsonb; binding package_model_admission.business_evidence_bindings;
 previous uuid; revision bigint; seeds text[]; bids uuid[]; actual_bids uuid[]; b uuid; job_bid uuid; fallback jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 IF body->>'version' IS DISTINCT FROM 'package-business-shadow-command/1' OR body->>'action' IS NULL OR body->>'action' NOT IN('activate','observe','rollback')
 OR octet_length(body::text)>16384 OR body->>'producer_method_digest' IS NULL OR body->>'producer_method_digest' !~ '^[a-f0-9]{64}$'
 OR jsonb_typeof(body->'expected_revision') IS DISTINCT FROM 'number' OR body->>'expected_revision' !~ '^[0-9]+$'
 OR NOT design.package_json_keys(body,CASE WHEN body->>'action'='activate' THEN ARRAY['version','command_id','route_id','action','expected_revision','producer_method_digest','config'] ELSE ARRAY['version','command_id','route_id','action','expected_revision','producer_method_digest'] END) THEN
  RAISE EXCEPTION 'business_shadow_command_invalid' USING ERRCODE='22023'; END IF;
 revision:=(body->>'expected_revision')::bigint;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO old FROM package_model_route.routes WHERE id=(body->>'route_id')::uuid FOR UPDATE;
 IF old.id IS NOT NULL AND old.actor_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 IF body->>'action'='activate' THEN
  config:=body->'config';
  IF old.id IS NOT NULL OR revision<>0 OR NOT design.package_json_keys(config,ARRAY['candidate_model_id','fallback_model_id','intent_id','reference','binding_digest'])
  OR (config->>'candidate_model_id')::uuid=(config->>'fallback_model_id')::uuid THEN RAISE EXCEPTION 'business_shadow_activation_invalid' USING ERRCODE='55000'; END IF;
  target:=(config->>'candidate_model_id')::uuid;
 ELSE
  IF old.id IS NULL OR old.revision<>revision OR old.method_digest::text IS DISTINCT FROM body->>'producer_method_digest' OR old.config->>'intent_id' IS NULL THEN RAISE EXCEPTION 'business_shadow_route_conflict' USING ERRCODE='40001'; END IF;
  config:=old.config;previous:=old.current_model_id;
  IF body->>'action'='rollback' THEN
   IF old.rolled_back OR previous IS DISTINCT FROM (config->>'candidate_model_id')::uuid THEN RAISE EXCEPTION 'business_shadow_rollback_invalid' USING ERRCODE='55000'; END IF;
   target:=(config->>'fallback_model_id')::uuid;
  ELSE target:=previous; END IF;
 END IF;
 SELECT bid_id INTO job_bid FROM material_qualification.intents WHERE id=(config->>'intent_id')::uuid AND actor_id=actor;
 IF job_bid IS NULL THEN RAISE EXCEPTION 'business_shadow_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT array_agg(DISTINCT 'package:'||m.admission_id::text) INTO seeds FROM package_model_registry.registrations r JOIN package_historical_research.members m ON m.cohort_id=(r.document#>>'{source,cohort_id}')::uuid WHERE r.model_id IN((config->>'candidate_model_id')::uuid,(config->>'fallback_model_id')::uuid);
 IF seeds IS NULL THEN RAISE EXCEPTION 'business_shadow_models_missing' USING ERRCODE='55000'; END IF;
 SELECT array_agg(DISTINCT item ORDER BY item) INTO bids FROM unnest(package_history_exposure_bridge.related_bids(seeds)||ARRAY[job_bid])item;
 FOREACH b IN ARRAY bids LOOP PERFORM design.lock_worker_bid(b); END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT array_agg(DISTINCT item ORDER BY item) INTO actual_bids FROM unnest(package_history_exposure_bridge.related_bids(seeds)||ARRAY[job_bid])item;
 IF bids IS DISTINCT FROM actual_bids THEN RAISE EXCEPTION 'business_shadow_relation_changed_retry' USING ERRCODE='40001'; END IF;
 IF job_bid=ANY(package_history_exposure_bridge.related_bids(seeds))
 OR EXISTS(SELECT FROM package_history_exposure_bridge.entity_keys() k WHERE k.entity=ANY(package_history_exposure_bridge.related_entities(seeds)) AND k.kind='project' AND k.identity=design.identity_snapshot_v2(job_bid)->>'engineering_project_id') THEN RAISE EXCEPTION 'business_shadow_training_project_leak' USING ERRCODE='55000'; END IF;
 SELECT * INTO binding FROM package_model_admission.business_evidence_bindings WHERE model_id=(config->>'candidate_model_id')::uuid AND actor_id=actor;
 IF binding.model_id IS NULL OR binding.digest::text IS DISTINCT FROM config->>'binding_digest'
 OR binding.document#>>'{evidence_contract,producer_method_digest}' IS DISTINCT FROM body->>'producer_method_digest'
 OR EXISTS(SELECT FROM package_historical_research.exposures x WHERE x.cohort_id=(binding.document#>>'{protocol,binding,cohort_id}')::uuid AND (x.created_at<=binding.frozen_at OR x.created_xact=binding.frozen_xact)) THEN
  RAISE EXCEPTION 'business_shadow_frozen_binding_required' USING ERRCODE='55000'; END IF;
 selected:=package_model_registry.read(target,actor);
 IF body->>'action'='activate' THEN fallback:=package_model_registry.read((config->>'fallback_model_id')::uuid,actor); END IF;
 src:=package_model_observation.business_source(actor,(config->>'intent_id')::uuid);
 IF NOT EXISTS(SELECT FROM package_model_observation.captures captured WHERE captured.id=(src->>'capture_id')::uuid AND captured.created_at>binding.frozen_at)
 OR src->>'producer_method_digest' IS DISTINCT FROM body->>'producer_method_digest'
 OR (src->>'mode'='live' AND selected#>>'{document,source,origin}' IS DISTINCT FROM 'external_evidence') THEN RAISE EXCEPTION 'business_shadow_origin_mismatch' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-business-shadow-preparation/1','source',src,'artifact',selected->'document','fallback_at_activation',fallback,
 'reference',config->'reference','config',config,'binding_digest',binding.digest,'revision',revision+1,'previous_model_id',previous,'selected_model_id',target);
END $$;
CREATE FUNCTION package_model_route.business_commit(actor uuid,body jsonb,pinned text,prediction jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE packet jsonb; replay jsonb; observation uuid; target uuid; next_revision bigint;
BEGIN
 PERFORM package_historical_research.assert_role('api');PERFORM pg_advisory_xact_lock(91143,1);
 replay:=package_model_route.business_replay(actor,body);IF replay IS NOT NULL THEN RETURN replay;END IF;
 packet:=package_model_route.business_prepare(actor,body);
 IF design.package_technical_digest(packet) IS DISTINCT FROM pinned
 OR NOT design.package_json_keys(prediction,ARRAY['schema','producer_method_digest','mode','source_digest','packet_digest','model_id','artifact_digest','input_digest','projection_digest','value','formal_eligibility','certification_issued'])
 OR prediction->>'schema' IS DISTINCT FROM 'package-business-shadow-result/1'
 OR prediction->>'producer_method_digest' IS DISTINCT FROM body->>'producer_method_digest'
 OR prediction->>'mode' IS DISTINCT FROM packet#>>'{source,mode}' OR prediction->>'packet_digest' IS DISTINCT FROM pinned
 OR prediction->>'source_digest' IS DISTINCT FROM design.package_technical_digest(packet->'source')
 OR prediction->>'model_id' IS DISTINCT FROM packet->>'selected_model_id'
 OR prediction->>'artifact_digest' IS DISTINCT FROM design.package_technical_digest(packet->'artifact')
 OR prediction->>'input_digest' IS DISTINCT FROM packet#>>'{source,input_digest}'
 OR prediction->>'formal_eligibility' IS DISTINCT FROM 'unavailable' OR prediction->'certification_issued' IS DISTINCT FROM 'false'::jsonb
 OR prediction->>'value' IS NULL OR prediction->>'value' !~ '^[0-9]+(\.[0-9]+)?$' THEN RAISE EXCEPTION 'business_shadow_result_invalid' USING ERRCODE='55000'; END IF;
 IF (prediction->>'value')::numeric NOT BETWEEN 0 AND 100 THEN RAISE EXCEPTION 'business_shadow_value_invalid' USING ERRCODE='22023'; END IF;
 observation:=public.uuid_generate_v5((body->>'command_id')::uuid,'package-business-shadow-observation/1');target:=(packet->>'selected_model_id')::uuid;next_revision:=(packet->>'revision')::bigint;
 INSERT INTO package_model_observation.events(command_id,actor_id,model_id,admission_id,request,request_digest,source,source_digest,result,result_digest,intent_id)
 VALUES(observation,actor,target,NULL,body,design.package_technical_digest(body),packet->'source',design.package_technical_digest(packet->'source'),prediction,design.package_technical_digest(prediction),(packet#>>'{config,intent_id}')::uuid);
 IF body->>'action'='activate' THEN
  INSERT INTO package_model_route.routes VALUES((body->>'route_id')::uuid,actor,packet->'config',body->>'producer_method_digest',next_revision,target,false,clock_timestamp());
 ELSE
  UPDATE package_model_route.routes SET revision=next_revision,current_model_id=target,rolled_back=rolled_back OR body->>'action'='rollback' WHERE id=(body->>'route_id')::uuid AND routes.revision=(body->>'expected_revision')::bigint;
  IF NOT FOUND THEN RAISE EXCEPTION 'business_shadow_route_conflict' USING ERRCODE='40001'; END IF;
 END IF;
 INSERT INTO package_model_route.events VALUES((body->>'command_id')::uuid,(body->>'route_id')::uuid,actor,next_revision,
 CASE WHEN body->>'action'='observe' THEN 'consume' ELSE body->>'action' END,(packet->>'previous_model_id')::uuid,target,body,design.package_technical_digest(body),pinned,observation,design.package_technical_digest(prediction),clock_timestamp());
 RETURN package_model_route.business_replay(actor,body);
END $$;
REVOKE ALL ON FUNCTION package_model_observation.begin_capture(uuid,uuid,uuid,text,text,integer),package_model_observation.capture_fence(),package_model_observation.finish_capture(uuid,uuid,text),package_model_observation.business_source(uuid,uuid),package_model_admission.bind_business_evidence(uuid,uuid,text,uuid,jsonb),package_model_route.business_replay(uuid,jsonb),package_model_route.business_prepare(uuid,jsonb),package_model_route.business_commit(uuid,jsonb,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_model_observation.begin_capture(uuid,uuid,uuid,text,text,integer),package_model_observation.finish_capture(uuid,uuid,text),package_model_observation.business_source(uuid,uuid),package_model_admission.bind_business_evidence(uuid,uuid,text,uuid,jsonb),package_model_route.business_replay(uuid,jsonb),package_model_route.business_prepare(uuid,jsonb),package_model_route.business_commit(uuid,jsonb,text,jsonb) TO tender_api;
COMMIT;
