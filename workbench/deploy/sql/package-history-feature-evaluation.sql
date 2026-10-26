-- Optional feature evaluation /1; AFTER feature-final, BEFORE exposure bridge.
-- Fresh reviewed database only. Never reseal installed guards or grant new roles.
BEGIN;
DO $verify$ DECLARE p pg_proc; BEGIN
 IF to_regnamespace('package_history_exposure_bridge') IS NOT NULL OR EXISTS(SELECT FROM package_historical_research.cohorts)
 THEN RAISE EXCEPTION 'package_history_feature_evaluation_fresh_install_required' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.claim_job(uuid,bigint,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[] OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'8bf4aec9136c52dc4bb47c3d7ff33cb80cb203d8e291f6b73d88ae142c9a8927' THEN RAISE EXCEPTION 'package_history_feature_evaluation_function_drift' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.open_final(uuid,bigint,bigint,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[] OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'bf7b3d468047f51a399bc03d9fbc4f854f73d42508cf060a486c5d7790cf08f4' THEN RAISE EXCEPTION 'package_history_feature_evaluation_function_drift' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.read_final(uuid,bigint,bigint,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[] OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'84f85e63f53d9038efefa53eadad597dc3ce87dfd63f9da727c60e30eb5ba03b' THEN RAISE EXCEPTION 'package_history_feature_evaluation_function_drift' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.finish_job(uuid,bigint,bigint,uuid,jsonb,design.sha256)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[] OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'08943dcaf8166080909cf10c4f55b5c4f878183228ccdf6fae17c202f263e153' THEN RAISE EXCEPTION 'package_history_feature_evaluation_function_drift' USING ERRCODE='55000'; END IF;
END $verify$;
CREATE TABLE package_historical_research.feature_final_exposures(
 job_id uuid PRIMARY KEY REFERENCES package_historical_research.feature_final_predictions(job_id),
 exposure_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.exposures(id),
 input_digest design.sha256 NOT NULL,predictions_digest design.sha256 NOT NULL,candidate_digest design.sha256 NOT NULL
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_historical_research.feature_final_exposures FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_historical_research.feature_final_exposures FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;
CREATE OR REPLACE FUNCTION package_historical_research.claim_job(target uuid,expected_generation bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; packet jsonb; candidate jsonb; bindings jsonb; trained jsonb; manifest jsonb; prior jsonb;
BEGIN
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_job_missing' USING ERRCODE='P0002'; END IF;
 PERFORM package_historical_research.assert_role(job.kind);
 IF NOT package_historical_research.current_cohort(job.cohort_id) THEN RAISE EXCEPTION 'package_history_cohort_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target FOR UPDATE;
 IF owner IS NULL OR expected_generation IS DISTINCT FROM job.generation THEN RAISE EXCEPTION 'package_history_lease_invalid' USING ERRCODE='55000'; END IF;
 IF job.state='succeeded' THEN RETURN jsonb_build_object('job_id',job.id,'state','succeeded','result_digest',(SELECT digest FROM package_historical_research.results WHERE job_id=target)); END IF;
 IF job.state NOT IN('queued','running') OR job.state='running' AND job.lease_until>clock_timestamp() THEN RAISE EXCEPTION 'package_history_job_not_claimable' USING ERRCODE='55000'; END IF;
 UPDATE package_historical_research.jobs SET state='running',owner_token=owner,lease_until=clock_timestamp()+interval '120 seconds',fence=jobs.fence+1 WHERE id=target RETURNING * INTO job;
 IF job.kind='evaluate' THEN
  IF to_regclass('package_history_exposure_bridge.guard_manifest') IS NULL THEN RAISE EXCEPTION 'package_history_feature_final_bridge_required' USING ERRCODE='55000'; END IF;
  SELECT r.document INTO trained FROM package_historical_research.predictions v JOIN package_historical_research.results r ON r.job_id=v.training_job_id WHERE v.job_id=target;
  candidate:=trained->'complete_feature_training';
  IF candidate IS NOT NULL THEN
   IF EXISTS(SELECT FROM package_historical_research.exposures WHERE job_id=target) AND NOT EXISTS(
    SELECT FROM package_historical_research.feature_final_exposures x JOIN package_historical_research.feature_final_predictions v ON v.job_id=x.job_id JOIN package_historical_research.feature_final_inputs i ON i.job_id=x.job_id
    WHERE x.job_id=target AND x.predictions_digest=v.digest AND x.input_digest=i.digest AND x.candidate_digest::text=design.package_technical_digest(candidate))
   THEN RAISE EXCEPTION 'package_history_feature_evaluation_exposure_mismatch' USING ERRCODE='55000'; END IF;
   SELECT document INTO prior FROM package_historical_research.feature_final_predictions WHERE job_id=target;
   SELECT document INTO manifest FROM package_historical_research.exports WHERE cohort_id=job.cohort_id AND purpose='final_manifest';
   SELECT jsonb_agg(jsonb_build_object(
    'admission_id',m.admission_id,'proof_id',p.id,'context_digest',p.context_digest,
    'bid_id',a.bid_id,'scope_id',a.scope_id,'scope_digest',sc.digest,'scope_manifest',sc.manifest,
    'project_id',p.native_context#>'{identity,engineering_project_id}',
    'submitted_at',m.submitted_at,'origin',a.origin,
    'originals',(SELECT jsonb_agg(jsonb_build_object('document_version_id',v->'document_version_id','digest',v->'digest','byte_size',v->'byte_size') ORDER BY v->>'document_version_id') FROM jsonb_array_elements(p.native_context->'originals')v)) ORDER BY m.admission_id)
   INTO bindings FROM package_historical_research.members m
    JOIN package_historical_research.admissions a ON a.id=m.admission_id
    JOIN package_historical_research.proofs p ON p.id=m.proof_id
    JOIN design.bid_package_technical_scopes sc ON sc.id=a.scope_id
    JOIN package_historical_research.cohorts c ON c.id=m.cohort_id
   WHERE m.cohort_id=job.cohort_id AND m.submitted_at>=c.submission_split_at;
   packet:=jsonb_build_object('schema','package-history-feature-final-input/1','cohort_id',job.cohort_id,
    'membership_digest',trained->'membership_digest','origin',trained->'origin',
    'candidate',candidate,'candidate_digest',design.package_technical_digest(candidate),
    'manifest',manifest,'manifest_digest',design.package_technical_digest(manifest),
    'material_bindings',bindings,'bindings_digest',design.package_technical_digest(bindings),
    'training_inputs',trained#>'{complete_material_consumer,receipts}',
    'training_members',(SELECT jsonb_agg(jsonb_build_object('id',m.admission_id,'group_id',m.group_id,'project_id',p.native_context#>'{identity,engineering_project_id}') ORDER BY m.admission_id) FROM package_historical_research.members m JOIN package_historical_research.proofs p ON p.id=m.proof_id WHERE m.cohort_id=job.cohort_id AND m.purpose IN('fit','development','calibration')),
    'forbidden_label_sources',(SELECT jsonb_agg(jsonb_build_object('id',p.native_context#>'{label,source_version_id}','digest',p.native_context#>'{label,file_digest}') ORDER BY m.admission_id) FROM package_historical_research.members m JOIN package_historical_research.proofs p ON p.id=m.proof_id WHERE m.cohort_id=job.cohort_id));
   SELECT document INTO prior FROM package_historical_research.feature_final_inputs WHERE job_id=target;
   IF prior IS NOT NULL AND prior IS DISTINCT FROM packet THEN RAISE EXCEPTION 'package_history_feature_final_input_drift' USING ERRCODE='55000'; END IF;
   INSERT INTO package_historical_research.feature_final_inputs(job_id,document,digest) VALUES(target,packet,design.package_technical_digest(packet)) ON CONFLICT(job_id) DO NOTHING;
   SELECT document INTO prior FROM package_historical_research.feature_final_predictions WHERE job_id=target;
   IF octet_length(packet::text)>16777216 THEN RAISE EXCEPTION 'package_history_feature_final_budget' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN jsonb_build_object('job_id',job.id,'generation',job.generation,'fence',job.fence,'owner',owner,'state','running') || CASE WHEN packet IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('feature_final_input',packet,'feature_final_frozen',prior) END;
END $$;

CREATE OR REPLACE FUNCTION package_historical_research.open_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; cohort package_historical_research.cohorts; prior uuid; exposure_identity uuid:=gen_random_uuid(); ids uuid[]; prediction package_historical_research.predictions; fp package_historical_research.feature_final_predictions; fi package_historical_research.feature_final_inputs; candidate jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('evaluate'); job:=package_historical_research.assert_lease(target,generation,fence,owner);
 SELECT r.document->'complete_feature_training' INTO candidate FROM package_historical_research.predictions v JOIN package_historical_research.results r ON r.job_id=v.training_job_id WHERE v.job_id=target;
 IF candidate IS NOT NULL THEN
  SELECT * INTO fp FROM package_historical_research.feature_final_predictions WHERE job_id=target;
  SELECT * INTO fi FROM package_historical_research.feature_final_inputs WHERE job_id=target;
  IF fp.job_id IS NULL OR fi.job_id IS NULL OR candidate->>'status' IS DISTINCT FROM 'research_candidate'
   OR fp.digest::text IS DISTINCT FROM design.package_technical_digest(fp.document) OR fi.digest::text IS DISTINCT FROM design.package_technical_digest(fi.document)
   OR fp.document->>'candidate_digest' IS DISTINCT FROM design.package_technical_digest(candidate)
   OR fi.document->'candidate' IS DISTINCT FROM candidate
   OR fp.document->'model_digest' IS DISTINCT FROM candidate->'model_digest'
   OR fp.document->'bindings_digest' IS DISTINCT FROM fi.document->'bindings_digest'
   OR fp.document->'manifest_digest' IS DISTINCT FROM fi.document->'manifest_digest'
   OR fp.document->>'cohort_id' IS DISTINCT FROM job.cohort_id::text
  THEN RAISE EXCEPTION 'package_history_feature_evaluation_predictions_required' USING ERRCODE='55000'; END IF;
 END IF;
 SELECT * INTO prediction FROM package_historical_research.predictions WHERE job_id=target;
 IF job.kind<>'evaluate' OR prediction.job_id IS NULL THEN RAISE EXCEPTION 'package_history_predictions_not_frozen' USING ERRCODE='55000'; END IF;
 SELECT * INTO cohort FROM package_historical_research.cohorts WHERE id=job.cohort_id;
 SELECT id INTO prior FROM package_historical_research.exposures WHERE job_id=target;
 IF FOUND THEN
  IF candidate IS NOT NULL AND NOT EXISTS(SELECT FROM package_historical_research.feature_final_exposures x WHERE x.job_id=target AND x.exposure_id=prior AND x.predictions_digest=fp.digest AND x.input_digest=fi.digest AND x.candidate_digest::text=design.package_technical_digest(candidate)) THEN RAISE EXCEPTION 'package_history_feature_evaluation_exposure_mismatch' USING ERRCODE='55000'; END IF;
  RETURN prior;
 END IF;
 SELECT array_agg(DISTINCT related ORDER BY related) INTO ids FROM package_historical_research.members m CROSS JOIN LATERAL unnest(m.closure_ids)related WHERE m.cohort_id=job.cohort_id AND m.submitted_at>=cohort.submission_split_at;
 IF ids IS NULL OR package_historical_research.already_exposed(ids,job.cohort_id) THEN RAISE EXCEPTION 'package_history_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO package_historical_research.exposures VALUES(exposure_identity,target,cohort.id,cohort.digest,cohort.membership_digest,prediction.digest,ids,pg_current_xact_id(),clock_timestamp());
 IF candidate IS NOT NULL THEN
  INSERT INTO package_historical_research.feature_final_exposures VALUES(target,exposure_identity,fi.digest,fp.digest,design.package_technical_digest(candidate));
 END IF;
 INSERT INTO package_historical_research.exposure_members SELECT exposure_identity,k.kind,k.identity FROM package_historical_research.exposure_keys(ids)k;
 INSERT INTO design.audit_entries(id,actor_id,event_type,payload) VALUES(gen_random_uuid(),NULL,'package-history.final-exposed',jsonb_build_object('exposure_id',exposure_identity,'cohort_id',cohort.id,'cohort_digest',cohort.digest,'membership_digest',cohort.membership_digest,'predictions_digest',prediction.digest,'principal',session_user));
 RETURN exposure_identity;
END $$;

CREATE OR REPLACE FUNCTION package_historical_research.read_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; value jsonb; feature jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('evaluate'); job:=package_historical_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'evaluate' OR NOT EXISTS(SELECT FROM package_historical_research.exposures x WHERE x.job_id=target AND x.created_xact<>pg_current_xact_id()) THEN RAISE EXCEPTION 'package_history_committed_exposure_required' USING ERRCODE='55000'; END IF;
 value:=(SELECT jsonb_build_object('schema','package-history-final-evaluation-export/1','origin',c.origin,'cohort_id',c.id,'protocol',p.document,'timing',c.document->'timing','labels',l.document,'labels_digest',l.digest,'predictions',v.document,'predictions_digest',v.digest,'model_digest',v.model_digest,'membership_digest',c.membership_digest,
  'denominator',jsonb_build_object('selected_submissions',(SELECT count(*) FROM package_historical_research.members WHERE cohort_id=c.id),'excluded_submissions',(SELECT count(*) FROM package_historical_research.members WHERE cohort_id=c.id AND purpose='excluded'),'final_side_candidates',jsonb_array_length(l.document)))
  FROM package_historical_research.cohorts c JOIN package_historical_research.protocols p ON p.id=c.protocol_id JOIN package_historical_research.exports l ON l.cohort_id=c.id AND l.purpose='final_labels' JOIN package_historical_research.predictions v ON v.job_id=target WHERE c.id=job.cohort_id);
 SELECT jsonb_build_object('version','package-history-feature-evaluation-input/1','exposure_id',x.exposure_id,'input',i.document,'input_digest',x.input_digest,'predictions',v.document,'predictions_digest',x.predictions_digest,'candidate_digest',x.candidate_digest) INTO feature
 FROM package_historical_research.feature_final_exposures x JOIN package_historical_research.feature_final_inputs i ON i.job_id=x.job_id JOIN package_historical_research.feature_final_predictions v ON v.job_id=x.job_id
 WHERE x.job_id=target AND x.input_digest=i.digest AND x.predictions_digest=v.digest;
 IF EXISTS(SELECT FROM package_historical_research.feature_final_inputs WHERE job_id=target) AND feature IS NULL THEN RAISE EXCEPTION 'package_history_feature_evaluation_exposure_mismatch' USING ERRCODE='55000'; END IF;
 RETURN value || CASE WHEN feature IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('feature_final',feature) END;
END $$;

CREATE OR REPLACE FUNCTION package_historical_research.finish_job(target uuid,generation bigint,fence bigint,owner uuid,payload jsonb,payload_digest design.sha256) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; c package_historical_research.cohorts; pr package_historical_research.protocols; trained jsonb; prior jsonb; manifest jsonb; frozen_input jsonb; row_value jsonb; calculated numeric; feature jsonb; exposure package_historical_research.feature_final_exposures;
BEGIN
 job:=package_historical_research.assert_lease(target,generation,fence,owner);
 IF payload->>'schema'='package-history-feature-final-predictions/1' THEN
  IF job.kind<>'evaluate' OR to_regclass('package_history_exposure_bridge.guard_manifest') IS NULL OR EXISTS(SELECT FROM package_historical_research.exposures WHERE job_id=target) THEN RAISE EXCEPTION 'package_history_feature_final_freeze_denied' USING ERRCODE='55000'; END IF;
  SELECT r.document INTO trained FROM package_historical_research.predictions v JOIN package_historical_research.results r ON r.job_id=v.training_job_id WHERE v.job_id=target;
  SELECT document INTO manifest FROM package_historical_research.exports WHERE cohort_id=job.cohort_id AND purpose='final_manifest';
  SELECT document INTO frozen_input FROM package_historical_research.feature_final_inputs WHERE job_id=target;
  IF frozen_input IS NULL THEN RAISE EXCEPTION 'package_history_feature_final_input_required' USING ERRCODE='55000'; END IF;
  IF NOT design.package_json_keys(payload,ARRAY['schema','cohort_id','membership_digest','candidate_digest','model_digest','method_digest','reference_digest','bindings_digest','manifest_digest','rows','research_only','formal_prediction','evaluation_status'])
   OR payload_digest::text IS DISTINCT FROM design.package_technical_digest(payload)
   OR payload->>'cohort_id' IS DISTINCT FROM job.cohort_id::text
   OR payload->'membership_digest' IS DISTINCT FROM trained->'membership_digest'
   OR payload->>'candidate_digest' IS DISTINCT FROM design.package_technical_digest(trained->'complete_feature_training')
   OR trained#>>'{complete_feature_training,status}' IS DISTINCT FROM 'research_candidate'
   OR payload->'model_digest' IS DISTINCT FROM trained#>'{complete_feature_training,model_digest}'
   OR payload->'bindings_digest' IS DISTINCT FROM frozen_input->'bindings_digest'
   OR (payload->>'method_digest' ~ '^[0-9a-f]{64}$') IS NOT TRUE OR (payload->>'reference_digest' ~ '^[0-9a-f]{64}$') IS NOT TRUE
   OR payload->>'manifest_digest' IS DISTINCT FROM design.package_technical_digest(manifest)
   OR payload->'research_only' IS DISTINCT FROM 'true'::jsonb OR payload->'formal_prediction' IS DISTINCT FROM 'null'::jsonb
   OR payload->>'evaluation_status' IS DISTINCT FROM 'not_implemented'
   OR jsonb_typeof(payload->'rows') IS DISTINCT FROM 'array'
   OR jsonb_array_length(payload->'rows')<>jsonb_array_length(manifest)
   OR EXISTS(SELECT FROM jsonb_array_elements(payload->'rows')r GROUP BY r->>'id' HAVING count(*)<>1)
   OR EXISTS(SELECT FROM jsonb_array_elements(manifest)m WHERE NOT EXISTS(SELECT FROM jsonb_array_elements(payload->'rows')r WHERE r->'id'=m->'id' AND (r->'status'=m->'status' OR m->>'status'='succeeded' AND r->>'status'='failed')))
  THEN RAISE EXCEPTION 'package_history_feature_final_binding_invalid' USING ERRCODE='23514'; END IF;
  FOR row_value IN SELECT v FROM jsonb_array_elements(payload->'rows')v LOOP
   IF NOT design.package_json_keys(row_value,ARRAY['id','status','prediction','projection','receipt'])
   THEN RAISE EXCEPTION 'package_history_feature_final_row_invalid' USING ERRCODE='23514'; END IF;
   IF row_value->>'status'='succeeded' THEN
    IF jsonb_typeof(row_value->'prediction') IS DISTINCT FROM 'string'
     OR jsonb_typeof(row_value#>'{projection,values}') IS DISTINCT FROM 'array'
     OR jsonb_array_length(row_value#>'{projection,values}')<>6
     OR row_value#>>'{projection,schema}' IS DISTINCT FROM 'package-complete-numeric-features/1'
     OR row_value#>'{projection,method_digest}' IS DISTINCT FROM trained#>'{complete_feature_training,method_digest}'
     OR row_value#>>'{projection,digest}' IS DISTINCT FROM design.package_technical_digest((row_value->'projection')-'digest')
     OR row_value#>'{projection,input_digest}' IS DISTINCT FROM row_value#>'{receipt,input_digest}'
     OR (row_value->>'prediction')::numeric NOT BETWEEN 0 AND 100
     OR EXISTS(SELECT FROM jsonb_array_elements_text(row_value#>'{projection,values}')v WHERE v::numeric NOT BETWEEN 0 AND 1 OR v::numeric IN('NaN','Infinity','-Infinity'))
    THEN RAISE EXCEPTION 'package_history_feature_final_prediction_invalid' USING ERRCODE='23514'; END IF;
    SELECT greatest(0,least(100,(trained#>>'{complete_feature_training,model,intercept}')::numeric+sum(
     ((row_value#>>ARRAY['projection','values',i::text])::numeric-(trained#>>ARRAY['complete_feature_training','model','means',i::text])::numeric)
     /(trained#>>ARRAY['complete_feature_training','model','scales',i::text])::numeric
     *(trained#>>ARRAY['complete_feature_training','model','coefficients',i::text])::numeric))) INTO calculated FROM generate_series(0,5)i;
    IF calculated IS NULL OR abs(calculated-(row_value->>'prediction')::numeric)>0.00000001 THEN RAISE EXCEPTION 'package_history_feature_final_prediction_changed' USING ERRCODE='23514'; END IF;
   ELSE
    IF row_value->'prediction' IS DISTINCT FROM 'null'::jsonb OR row_value->'projection' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'package_history_feature_final_failure_invalid' USING ERRCODE='23514'; END IF;
   END IF;
  END LOOP;
  SELECT document INTO prior FROM package_historical_research.feature_final_predictions WHERE job_id=target;
  IF prior IS NOT NULL AND prior IS DISTINCT FROM payload THEN RAISE EXCEPTION 'package_history_feature_final_freeze_conflict' USING ERRCODE='23514'; END IF;
  INSERT INTO package_historical_research.feature_final_predictions(job_id,document,digest) VALUES(target,payload,payload_digest) ON CONFLICT(job_id) DO NOTHING;
  -- The stage is complete, not the evaluation job. A retry can immediately claim
  -- and compare the immutable prediction; no lease expiry or lost ACK ambiguity.
  UPDATE package_historical_research.jobs SET state='queued',owner_token=NULL,lease_until=NULL WHERE id=target;
  RETURN true;
 END IF;
 SELECT * INTO c FROM package_historical_research.cohorts WHERE id=job.cohort_id;
 SELECT * INTO pr FROM package_historical_research.protocols WHERE id=c.protocol_id;
 IF payload_digest::text IS DISTINCT FROM design.package_technical_digest(payload) OR payload->>'cohort_id' IS DISTINCT FROM c.id::text OR payload->>'origin' IS DISTINCT FROM c.origin OR payload->>'protocol_digest' IS DISTINCT FROM pr.digest::text OR payload->>'membership_digest' IS DISTINCT FROM c.membership_digest::text
 OR payload->'research_only' IS DISTINCT FROM 'true'::jsonb OR payload->>'formal_eligibility' IS DISTINCT FROM 'unavailable' OR payload->'provider_requests' IS DISTINCT FROM '0'::jsonb OR payload->'paid_calls' IS DISTINCT FROM '0'::jsonb
 THEN RAISE EXCEPTION 'package_history_result_binding_invalid' USING ERRCODE='23514'; END IF;
 IF job.kind='train' THEN
  IF payload->>'schema' IS DISTINCT FROM 'package-history-training-result/1' OR payload->>'training_export_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.exports WHERE cohort_id=c.id AND purpose='training')
  OR payload->>'model_digest' IS DISTINCT FROM design.package_technical_digest(payload->'model') OR payload#>>'{model,schema}' IS DISTINCT FROM 'package-history-constant-model/1'
  OR payload#>>'{model,method_digest}' IS DISTINCT FROM pr.document#>>'{method,digest}' OR (payload#>>'{model,family}' IN('mean','median')) IS NOT TRUE
  OR jsonb_typeof(payload#>'{model,constant}') IS DISTINCT FROM 'string'
  OR (payload#>>'{model,constant}')::numeric NOT BETWEEN 0 AND 100 OR (payload#>>'{model,constant}')::numeric IN('NaN','Infinity','-Infinity')
  OR payload#>>'{model,training_export_digest}' IS DISTINCT FROM payload->>'training_export_digest'
  THEN RAISE EXCEPTION 'package_history_training_result_invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF payload->>'schema' IS DISTINCT FROM 'package-history-independent-evaluation/1' OR payload->>'acceptance_decision' IS DISTINCT FROM 'unavailable'
  OR payload->>'predictions_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.predictions WHERE job_id=target)
  OR payload->>'model_digest' IS DISTINCT FROM (SELECT model_digest::text FROM package_historical_research.predictions WHERE job_id=target)
  OR payload->>'labels_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.exports WHERE cohort_id=c.id AND purpose='final_labels')
  OR NOT EXISTS(SELECT FROM package_historical_research.exposures WHERE job_id=target AND created_xact<>pg_current_xact_id())
  THEN RAISE EXCEPTION 'package_history_evaluation_result_invalid' USING ERRCODE='23514'; END IF;
 END IF;
 IF job.kind='evaluate' THEN
  SELECT * INTO exposure FROM package_historical_research.feature_final_exposures WHERE job_id=target;
  feature:=payload->'feature_final_evaluation';
  IF exposure.job_id IS NULL THEN
   IF feature IS NOT NULL THEN RAISE EXCEPTION 'package_history_feature_evaluation_unbound_result' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT document INTO prior FROM package_historical_research.feature_final_predictions WHERE job_id=target;
   IF feature IS NULL OR NOT design.package_json_keys(feature,ARRAY['version','cohort_id','origin','membership_digest','method_digest','freeze_method_digest','candidate_digest','model_digest','predictions_digest','labels_digest','input_digest','exposure_id','report','research_only','formal_prediction','acceptance_decision','provider_requests','paid_calls'])
    OR feature->>'version' IS DISTINCT FROM 'package-history-feature-evaluation/1'
    OR feature->'cohort_id' IS DISTINCT FROM payload->'cohort_id' OR feature->'origin' IS DISTINCT FROM payload->'origin' OR feature->'membership_digest' IS DISTINCT FROM payload->'membership_digest'
    OR feature->>'exposure_id' IS DISTINCT FROM exposure.exposure_id::text
    OR feature->>'predictions_digest' IS DISTINCT FROM exposure.predictions_digest::text OR feature->>'input_digest' IS DISTINCT FROM exposure.input_digest::text OR feature->>'candidate_digest' IS DISTINCT FROM exposure.candidate_digest::text
    OR feature->'model_digest' IS DISTINCT FROM prior->'model_digest' OR feature->'freeze_method_digest' IS DISTINCT FROM prior->'method_digest' OR feature->'labels_digest' IS DISTINCT FROM payload->'labels_digest'
    OR (feature->>'method_digest' ~ '^[0-9a-f]{64}$') IS NOT TRUE
    OR feature->'research_only' IS DISTINCT FROM 'true'::jsonb OR feature->'formal_prediction' IS DISTINCT FROM 'null'::jsonb OR feature->>'acceptance_decision' IS DISTINCT FROM 'unavailable'
    OR feature->'provider_requests' IS DISTINCT FROM '0'::jsonb OR feature->'paid_calls' IS DISTINCT FROM '0'::jsonb
    OR feature#>'{report,denominator}' IS DISTINCT FROM payload#>'{report,denominator}'
   THEN RAISE EXCEPTION 'package_history_feature_evaluation_result_invalid' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 INSERT INTO package_historical_research.results VALUES(target,payload,payload_digest,clock_timestamp());
 UPDATE package_historical_research.jobs SET state='succeeded',owner_token=NULL,lease_until=NULL WHERE id=target;
 RETURN true;
END $$;
COMMIT;
