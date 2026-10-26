-- Optional fresh lifecycle over existing report/protocol/observation/route authority.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_model_observation.business_source(uuid,uuid)') IS NULL
 OR EXISTS(SELECT FROM package_model_observation.events) THEN RAISE EXCEPTION 'package_certification_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE TABLE package_model_admission.certificates(
 id uuid PRIMARY KEY,model_id uuid NOT NULL UNIQUE REFERENCES package_model_registry.registrations(model_id),actor_id uuid NOT NULL REFERENCES design.members(id),
 command_id uuid NOT NULL UNIQUE,request jsonb NOT NULL,source_digest design.sha256 NOT NULL,method_digest design.sha256 NOT NULL,
 shadow_event_id uuid NOT NULL REFERENCES package_model_route.events(command_id),rollback_event_id uuid NOT NULL REFERENCES package_model_route.events(command_id),
 issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),valid_until timestamptz NOT NULL,CHECK(issued_at<valid_until),
 CHECK(shadow_event_id<>rollback_event_id),CHECK(octet_length(request::text)<=8192)
);
CREATE TABLE package_model_admission.certificate_revocations(
 certificate_id uuid PRIMARY KEY REFERENCES package_model_admission.certificates(id),actor_id uuid NOT NULL REFERENCES design.members(id),
 command_id uuid NOT NULL UNIQUE,reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER immutable_certificate BEFORE UPDATE OR DELETE ON package_model_admission.certificates FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_certificate_revocation BEFORE UPDATE OR DELETE ON package_model_admission.certificate_revocations FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_model_admission.certificates,package_model_admission.certificate_revocations FROM PUBLIC,tender_api,tender_worker;
CREATE FUNCTION package_model_admission.certification_event(target uuid) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
 SELECT jsonb_build_object('command_id',e.command_id,'route_id',e.route_id,'revision',e.revision,'action',e.action,
 'previous_model_id',e.previous_model_id,'selected_model_id',e.selected_model_id,'created_at',e.created_at,'source',o.source,'result',o.result)
 FROM package_model_route.events e JOIN package_model_observation.events o ON o.command_id=e.observation_id
 WHERE e.command_id=target AND e.result_digest=o.result_digest AND design.package_technical_digest(o.result)=o.result_digest
 AND design.package_technical_digest(o.source)=o.source_digest AND o.intent_id IS NOT NULL AND o.admission_id IS NULL
$$;
CREATE FUNCTION package_model_admission.certification_source(actor uuid,model uuid,shadow_id uuid,rollback_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE shadow package_model_route.events; rollback package_model_route.events; route package_model_route.routes;
 observation package_model_observation.events; frozen package_model_admission.business_evidence_bindings; saved_report package_model_admission.reports;
 registered jsonb; fallback jsonb; report jsonb; current_source jsonb; shadow_value jsonb; rollback_value jsonb;
 seeds text[]; bids uuid[]; actual_bids uuid[]; b uuid; job_bid uuid; deadline timestamptz; captured timestamptz;
 metrics jsonb; limits jsonb; value numeric; bounds jsonb; item record;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM package_model_registry.registrations WHERE model_id=model AND actor_id=actor)
 OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'package_certificate_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO shadow FROM package_model_route.events WHERE command_id=shadow_id;
 SELECT * INTO rollback FROM package_model_route.events WHERE command_id=rollback_id;
 SELECT * INTO route FROM package_model_route.routes WHERE id=shadow.route_id;
 SELECT * INTO observation FROM package_model_observation.events WHERE command_id=shadow.observation_id;
 IF shadow.actor_id IS DISTINCT FROM actor OR rollback.actor_id IS DISTINCT FROM actor OR route.actor_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'package_certificate_actor_denied' USING ERRCODE='42501'; END IF;
 IF shadow.selected_model_id IS DISTINCT FROM model OR rollback.previous_model_id IS DISTINCT FROM model OR rollback.action IS DISTINCT FROM 'rollback'
 OR rollback.route_id IS DISTINCT FROM shadow.route_id OR shadow.revision>=rollback.revision
 OR rollback.selected_model_id=model OR route.current_model_id IS DISTINCT FROM rollback.selected_model_id OR NOT route.rolled_back
 OR route.config->>'candidate_model_id' IS DISTINCT FROM model::text OR route.config->>'fallback_model_id' IS DISTINCT FROM rollback.selected_model_id::text
 OR route.config->>'intent_id' IS DISTINCT FROM observation.intent_id::text OR observation.intent_id IS NULL THEN
  RAISE EXCEPTION 'package_certificate_event_chain_invalid' USING ERRCODE='55000'; END IF;
 SELECT bid_id INTO job_bid FROM material_qualification.intents WHERE id=observation.intent_id AND actor_id=actor;
 SELECT array_agg(DISTINCT 'package:'||m.admission_id::text) INTO seeds FROM package_model_registry.registrations r
 JOIN package_historical_research.members m ON m.cohort_id=(r.document#>>'{source,cohort_id}')::uuid WHERE r.model_id IN(model,rollback.selected_model_id);
 IF job_bid IS NULL OR seeds IS NULL THEN RAISE EXCEPTION 'package_certificate_source_missing' USING ERRCODE='55000'; END IF;
 SELECT array_agg(DISTINCT x ORDER BY x) INTO bids FROM unnest(package_history_exposure_bridge.related_bids(seeds)||ARRAY[job_bid])x;
 FOREACH b IN ARRAY bids LOOP PERFORM design.lock_worker_bid(b); END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT array_agg(DISTINCT x ORDER BY x) INTO actual_bids FROM unnest(package_history_exposure_bridge.related_bids(seeds)||ARRAY[job_bid])x;
 IF bids IS DISTINCT FROM actual_bids THEN RAISE EXCEPTION 'package_certificate_relation_changed' USING ERRCODE='40001'; END IF;
 PERFORM a.id FROM package_historical_research.adapters a WHERE a.id IN(SELECT p.adapter_id FROM package_historical_research.proofs p JOIN package_historical_research.members m ON m.proof_id=p.id WHERE 'package:'||m.admission_id::text=ANY(seeds)) ORDER BY a.id FOR SHARE OF a;
 LOCK TABLE package_historical_research.adapter_revocations IN SHARE MODE;
 registered:=package_model_registry.read(model,actor);fallback:=package_model_registry.read(rollback.selected_model_id,actor);
 SELECT * INTO frozen FROM package_model_admission.business_evidence_bindings WHERE model_id=model AND actor_id=actor;
 SELECT * INTO saved_report FROM package_model_admission.reports WHERE model_id=model AND actor_id=actor;
 IF frozen.model_id IS NULL OR saved_report.model_id IS NULL THEN RAISE EXCEPTION 'package_certificate_protocol_report_required' USING ERRCODE='55000'; END IF;
 report:=package_model_admission.report_source(model,saved_report.evaluation_job_id,actor);
 current_source:=package_model_observation.business_source(actor,observation.intent_id);
 shadow_value:=package_model_admission.certification_event(shadow_id);rollback_value:=package_model_admission.certification_event(rollback_id);
 SELECT c.created_at,least((r.document->>'valid_until')::timestamptz,(r.document#>>'{price,valid_until}')::timestamptz,p.valid_until,
  (SELECT min(adapter.valid_until) FROM package_historical_research.members m JOIN package_historical_research.proofs proof ON proof.id=m.proof_id JOIN package_historical_research.adapters adapter ON adapter.id=proof.adapter_id
    WHERE 'package:'||m.admission_id::text=ANY(seeds))) INTO captured,deadline
 FROM package_model_observation.captures c JOIN material_execution.profiles p ON p.id=c.profile_id
 JOIN material_qualification.acceptances a ON a.job_id=c.job_id JOIN material_qualification.intents i ON i.id=a.intent_id
 JOIN material_qualification.records r ON r.id=i.qualification_id WHERE c.id=(current_source->>'capture_id')::uuid;
 IF registered#>>'{document,source,origin}' IS DISTINCT FROM 'external_evidence' OR fallback#>>'{document,source,origin}' IS DISTINCT FROM 'external_evidence'
 OR current_source->>'mode' IS DISTINCT FROM 'live' OR deadline IS NULL OR deadline<=clock_timestamp()
 OR EXISTS(SELECT FROM package_historical_research.test_environments e JOIN pg_database d ON d.oid=e.database_oid AND d.datname=e.database_name WHERE d.datname=current_database())
 OR frozen.digest::text IS DISTINCT FROM route.config->>'binding_digest'
 OR frozen.document->>'schema' IS DISTINCT FROM 'score-business-admission-protocol/3'
 OR frozen.document->'protocol' IS DISTINCT FROM report->'protocol' OR frozen.protocol_digest::text IS DISTINCT FROM report->>'protocol_digest'
 OR frozen.document#>>'{evidence_contract,producer_method_digest}' IS DISTINCT FROM current_source->>'producer_method_digest'
 OR frozen.frozen_at>=(report->>'exposure_at')::timestamptz
 OR EXISTS(SELECT FROM package_historical_research.exposures WHERE id=(report->>'exposure_id')::uuid AND created_xact=frozen.frozen_xact)
 OR frozen.frozen_at>=captured OR captured>shadow.created_at OR shadow.created_at>rollback.created_at
 OR saved_report.packet IS DISTINCT FROM report OR saved_report.packet_digest::text IS DISTINCT FROM design.package_technical_digest(report)
 OR shadow_value IS NULL OR rollback_value IS NULL OR shadow_value->'source' IS DISTINCT FROM current_source OR rollback_value->'source' IS DISTINCT FROM current_source
 OR shadow_value#>>'{result,schema}' IS DISTINCT FROM 'package-business-shadow-result/1'
 OR rollback_value#>>'{result,schema}' IS DISTINCT FROM 'package-business-shadow-result/1'
 OR shadow_value#>>'{result,mode}' IS DISTINCT FROM 'live' OR rollback_value#>>'{result,mode}' IS DISTINCT FROM 'live'
 OR shadow_value#>>'{result,producer_method_digest}' IS DISTINCT FROM current_source->>'producer_method_digest'
 OR rollback_value#>>'{result,producer_method_digest}' IS DISTINCT FROM current_source->>'producer_method_digest'
 OR shadow_value#>>'{result,formal_eligibility}' IS DISTINCT FROM 'unavailable' OR rollback_value#>>'{result,formal_eligibility}' IS DISTINCT FROM 'unavailable'
 OR shadow_value#>'{result,certification_issued}' IS DISTINCT FROM 'false'::jsonb OR rollback_value#>'{result,certification_issued}' IS DISTINCT FROM 'false'::jsonb
 OR shadow_value#>>'{result,input_digest}' IS DISTINCT FROM current_source->>'input_digest'
 OR rollback_value#>>'{result,input_digest}' IS DISTINCT FROM current_source->>'input_digest'
 OR shadow_value#>>'{result,model_id}' IS DISTINCT FROM model::text OR rollback_value#>>'{result,model_id}' IS DISTINCT FROM rollback.selected_model_id::text
 OR shadow_value#>>'{result,artifact_digest}' IS DISTINCT FROM registered->>'artifact_digest' OR rollback_value#>>'{result,artifact_digest}' IS DISTINCT FROM fallback->>'artifact_digest'
 OR report#>>'{report,origin}' IS DISTINCT FROM 'external_evidence' THEN
  RAISE EXCEPTION 'package_certificate_real_evidence_required' USING ERRCODE='55000'; END IF;
 -- Same explicitly frozen numeric policy, no caller boolean and no new/default threshold.
 limits:=report#>'{protocol,thresholds}';
 metrics:=jsonb_build_object('maximum_project_mae',report#>'{report,report,project_mae}',
 'minimum_success_coverage',report#>'{report,report,success_coverage}',
 'minimum_paired_baseline_gain',report#>ARRAY['report','report','paired_baselines',report#>>'{protocol,baseline}','gain'],
 'minimum_interval_coverage',report#>ARRAY['report','report','intervals',limits->>'interval_level','coverage']);
 bounds:='{"maximum_project_mae":[0,100],"minimum_success_coverage":[0,1],"minimum_paired_baseline_gain":[-100,100],"minimum_interval_coverage":[0,1]}'::jsonb;
 FOR item IN SELECT * FROM jsonb_each(metrics) LOOP
  IF jsonb_typeof(item.value) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'package_certificate_metrics_invalid' USING ERRCODE='55000'; END IF;
  value:=(item.value#>>'{}')::numeric;
  IF value IN('NaN','Infinity','-Infinity') OR value<(bounds#>>ARRAY[item.key,'0'])::numeric OR value>(bounds#>>ARRAY[item.key,'1'])::numeric
  OR (item.key='maximum_project_mae' AND value>(limits->>item.key)::numeric)
  OR (item.key<>'maximum_project_mae' AND value<(limits->>item.key)::numeric) THEN RAISE EXCEPTION 'package_certificate_thresholds_not_met' USING ERRCODE='55000'; END IF;
 END LOOP;
 RETURN jsonb_build_object('schema','package-certification-source/1','model',registered->'document','fallback_model',fallback->'document','report',report,
 'binding',jsonb_build_object('document',frozen.document,'digest',frozen.digest,'frozen_at',frozen.frozen_at),
 'shadow',shadow_value,'rollback',rollback_value,'current_source',current_source,'captured_at',captured,'evidence_valid_until',deadline);
END $$;
CREATE FUNCTION package_model_admission.read_certificate(actor uuid,target uuid,method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE c package_model_admission.certificates; packet jsonb; status text; revoked package_model_admission.certificate_revocations;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO c FROM package_model_admission.certificates WHERE id=target;
 IF c.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'package_certificate_actor_denied' USING ERRCODE='42501'; END IF;
 -- Serialize read/consume with terminal revocation. No shared mutable sessions.
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO revoked FROM package_model_admission.certificate_revocations WHERE certificate_id=target;
 status:=CASE WHEN revoked.certificate_id IS NOT NULL THEN 'revoked' WHEN clock_timestamp()>=c.valid_until THEN 'expired' WHEN c.method_digest::text IS DISTINCT FROM method THEN 'stale' ELSE 'active' END;
 IF status='active' THEN
  BEGIN
   packet:=package_model_admission.certification_source(actor,c.model_id,c.shadow_event_id,c.rollback_event_id);
   IF design.package_technical_digest(packet) IS DISTINCT FROM c.source_digest::text THEN status:='stale'; END IF;
  EXCEPTION WHEN SQLSTATE '55000' OR SQLSTATE '42501' OR SQLSTATE '40001' OR SQLSTATE 'P0002' OR SQLSTATE 'P0001' OR SQLSTATE '22023' THEN
   status:='stale';packet:=NULL;
  END;
 END IF;
 RETURN jsonb_build_object('certificate',jsonb_build_object('id',c.id,'model_id',c.model_id,'command_id',c.command_id,'request',c.request,
 'source_digest',c.source_digest,'method_digest',c.method_digest,'issued_at',c.issued_at,'valid_until',c.valid_until,
 'revocation',CASE WHEN revoked.certificate_id IS NULL THEN NULL ELSE jsonb_build_object('command_id',revoked.command_id,'reason',revoked.reason,'revoked_at',revoked.created_at) END),'state',status,'source',packet);
END $$;
CREATE FUNCTION package_model_admission.certificate_replay(actor uuid,model uuid,body jsonb,command uuid,expected text,method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c package_model_admission.certificates;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO c FROM package_model_admission.certificates WHERE command_id=command OR model_id=model ORDER BY command_id=command DESC LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF c.actor_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'package_certificate_actor_denied' USING ERRCODE='42501'; END IF;
 IF c.model_id IS DISTINCT FROM model OR c.command_id IS DISTINCT FROM command OR c.request IS DISTINCT FROM body OR c.source_digest::text IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'package_certificate_already_issued' USING ERRCODE='55000'; END IF;
 RETURN package_model_admission.read_certificate(actor,c.id,method);
END $$;
CREATE FUNCTION package_model_admission.issue_certificate(actor uuid,model uuid,body jsonb,command uuid,expected text,method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE replay jsonb; packet jsonb; identity uuid; expiry timestamptz;
BEGIN
 PERFORM package_historical_research.assert_role('api');PERFORM pg_advisory_xact_lock(91143,1);
 replay:=package_model_admission.certificate_replay(actor,model,body,command,expected,method);IF replay IS NOT NULL THEN RETURN replay; END IF;
 IF NOT design.package_json_keys(body,ARRAY['shadow_event_id','rollback_event_id','valid_until','reason']) OR octet_length(body::text)>8192
 OR command IS NULL OR method IS NULL OR method !~ '^[a-f0-9]{64}$' OR body->>'reason' IS NULL OR length(btrim(body->>'reason')) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'package_certificate_request_invalid' USING ERRCODE='22023'; END IF;
 packet:=package_model_admission.certification_source(actor,model,(body->>'shadow_event_id')::uuid,(body->>'rollback_event_id')::uuid);
 expiry:=(body->>'valid_until')::timestamptz;
 IF design.package_technical_digest(packet) IS DISTINCT FROM expected OR expiry IS NULL OR expiry<=clock_timestamp() OR expiry>(packet->>'evidence_valid_until')::timestamptz THEN
  RAISE EXCEPTION 'package_certificate_source_or_expiry_changed' USING ERRCODE='55000'; END IF;
 identity:=public.uuid_generate_v5(model,'package-model-certification/1');
 INSERT INTO package_model_admission.certificates VALUES(identity,model,actor,command,body,expected,method,(body->>'shadow_event_id')::uuid,(body->>'rollback_event_id')::uuid,clock_timestamp(),expiry);
 RETURN package_model_admission.read_certificate(actor,identity,method);
END $$;
CREATE FUNCTION package_model_admission.revoke_certificate(actor uuid,target uuid,command uuid,reason text,method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c package_model_admission.certificates; old package_model_admission.certificate_revocations;
BEGIN
 PERFORM package_historical_research.assert_role('api');PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO c FROM package_model_admission.certificates WHERE id=target;
 IF c.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'package_certificate_actor_denied' USING ERRCODE='42501'; END IF;
 IF command IS NULL OR reason IS NULL OR length(btrim(reason)) NOT BETWEEN 1 AND 4000 THEN RAISE EXCEPTION 'package_certificate_revoke_invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM package_model_admission.certificate_revocations WHERE certificate_id=target OR command_id=command;
 IF FOUND THEN
  IF old.certificate_id IS DISTINCT FROM target OR old.command_id IS DISTINCT FROM command OR old.reason IS DISTINCT FROM reason THEN RAISE EXCEPTION 'package_certificate_terminal_revocation' USING ERRCODE='55000'; END IF;
 ELSE INSERT INTO package_model_admission.certificate_revocations VALUES(target,actor,command,reason,clock_timestamp()); END IF;
 RETURN package_model_admission.read_certificate(actor,target,method);
END $$;
REVOKE ALL ON FUNCTION package_model_admission.certification_event(uuid),package_model_admission.certification_source(uuid,uuid,uuid,uuid),package_model_admission.read_certificate(uuid,uuid,text),package_model_admission.certificate_replay(uuid,uuid,jsonb,uuid,text,text),package_model_admission.issue_certificate(uuid,uuid,jsonb,uuid,text,text),package_model_admission.revoke_certificate(uuid,uuid,uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_model_admission.certification_source(uuid,uuid,uuid,uuid),package_model_admission.read_certificate(uuid,uuid,text),package_model_admission.certificate_replay(uuid,uuid,jsonb,uuid,text,text),package_model_admission.issue_certificate(uuid,uuid,jsonb,uuid,text,text),package_model_admission.revoke_certificate(uuid,uuid,uuid,text,text) TO tender_api;
COMMIT;
