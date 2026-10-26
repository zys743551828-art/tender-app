-- Optional fresh-install /3 artifact registry. No certification or business routing.
-- Requires reviewed package-history feature training/final and exposure bridge.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_history_exposure_bridge.readiness()') IS NULL
 OR to_regclass('package_historical_research.feature_final_predictions') IS NULL
 OR EXISTS(SELECT FROM package_historical_research.cohorts) THEN
  RAISE EXCEPTION 'package_model_registry_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA package_model_registry;
REVOKE ALL ON SCHEMA package_model_registry FROM PUBLIC;
CREATE TABLE package_model_registry.registrations(
 model_id uuid PRIMARY KEY,
 training_job_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.results(job_id),
 actor_id uuid NOT NULL REFERENCES design.members(id),
 document jsonb NOT NULL,artifact_digest design.sha256 NOT NULL,
 request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 200),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(octet_length(document::text)<=2097152),CHECK(design.package_technical_digest(document)=artifact_digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_model_registry.registrations
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_model_registry.registrations FROM PUBLIC,tender_api,tender_worker,tender_model_train,tender_model_evaluate,tender_model_score;
CREATE FUNCTION package_model_registry.source(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_registry,pg_temp AS $$
DECLARE job package_historical_research.jobs; cohort package_historical_research.cohorts;
 result package_historical_research.results; protocol package_historical_research.protocols; candidate jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_registry_isolation_required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 SELECT * INTO cohort FROM package_historical_research.cohorts WHERE id=job.cohort_id;
 IF cohort.id IS NULL OR cohort.created_by IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_registry_actor_denied' USING ERRCODE='42501'; END IF;
 IF package_history_exposure_bridge.readiness()->>'configured' IS DISTINCT FROM 'true'
 OR NOT package_historical_research.current_cohort(cohort.id) THEN
  RAISE EXCEPTION 'package_registry_source_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target FOR UPDATE;
 IF job.kind<>'train' OR job.state<>'succeeded' THEN
  RAISE EXCEPTION 'package_registry_training_unavailable' USING ERRCODE='55000'; END IF;
 SELECT * INTO result FROM package_historical_research.results WHERE job_id=target;
 SELECT * INTO protocol FROM package_historical_research.protocols WHERE id=cohort.protocol_id;
 candidate:=result.document->'complete_feature_training';
 IF candidate IS NULL OR candidate->>'version' IS DISTINCT FROM 'package-complete-feature-training/1'
 OR candidate->>'status' IS DISTINCT FROM 'research_candidate'
 OR candidate->>'origin' IS DISTINCT FROM cohort.origin
 OR candidate->>'membership_digest' IS DISTINCT FROM cohort.membership_digest::text THEN
  RAISE EXCEPTION 'package_registry_candidate_mismatch' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-score-registration-source/1','training_job_id',target,
  'cohort_id',cohort.id,'cohort_digest',cohort.digest,'membership_digest',cohort.membership_digest,
  'protocol_digest',protocol.digest,'result_digest',result.digest,'candidate',candidate,
  'candidate_digest',design.package_technical_digest(candidate),'origin',cohort.origin);
END $$;
CREATE FUNCTION package_model_registry.read(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_registry,pg_temp AS $$
DECLARE stored package_model_registry.registrations; source jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO stored FROM package_model_registry.registrations WHERE model_id=target;
 IF stored.model_id IS NULL OR stored.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_registry_actor_denied' USING ERRCODE='42501'; END IF;
 source:=package_model_registry.source(stored.training_job_id,actor);
 IF stored.document->'source' IS DISTINCT FROM source THEN
  RAISE EXCEPTION 'package_registry_identity_changed' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','registered-package-score-receipt/1','model_id',stored.model_id,
  'document',stored.document,'artifact_digest',stored.artifact_digest,'created_at',stored.created_at,
  'research_only',true,'formal_eligibility','unavailable','certification_issued',false);
END $$;
CREATE FUNCTION package_model_registry.register(target uuid,actor uuid,document jsonb,request_key text,reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_registry,pg_temp AS $$
DECLARE source jsonb; stored package_model_registry.registrations; identity uuid;
BEGIN
 source:=package_model_registry.source(target,actor);
 IF document IS NULL OR jsonb_typeof(document)<>'object' OR octet_length(document::text)>2097152
 OR request_key IS NULL OR length(btrim(request_key)) NOT BETWEEN 1 AND 200
 OR reason IS NULL OR length(btrim(reason)) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'package_registry_document_invalid' USING ERRCODE='22023'; END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document)k) IS DISTINCT FROM
 ARRAY['adapter_method_digest','feature_contract','formal_eligibility','model_id','research_only','schema','source']::text[]
 OR document->>'schema' IS DISTINCT FROM 'registered-package-score-artifact/1'
 OR document->'source' IS DISTINCT FROM source
 OR document->>'formal_eligibility' IS DISTINCT FROM 'unavailable'
 OR document->'research_only' IS DISTINCT FROM 'true'::jsonb
 OR document->>'adapter_method_digest' IS NULL OR document->>'adapter_method_digest' !~ '^[a-f0-9]{64}$'
 OR document->'feature_contract' IS DISTINCT FROM '{"schema":"package-complete-numeric-features/1","names":["declared_band_fraction","modal_agreement","specificity_supported","validity_supported","consistency_supported","uncertain_fraction"],"feature_scale":"unit_interval","target_scale":"normalized_0_100"}'::jsonb THEN
  RAISE EXCEPTION 'package_registry_document_mismatch' USING ERRCODE='22023'; END IF;
 identity:=(document->>'model_id')::uuid;
 IF identity IS NULL THEN RAISE EXCEPTION 'package_registry_identity_required' USING ERRCODE='22023'; END IF;
 SELECT * INTO stored FROM package_model_registry.registrations WHERE training_job_id=target;
 IF FOUND THEN
  IF stored.document IS DISTINCT FROM document OR stored.request_key IS DISTINCT FROM request_key OR stored.reason IS DISTINCT FROM reason THEN
   RAISE EXCEPTION 'package_registry_already_registered' USING ERRCODE='55000'; END IF;
  RETURN package_model_registry.read(stored.model_id,actor);
 END IF;
 INSERT INTO package_model_registry.registrations VALUES(identity,target,actor,document,
  design.package_technical_digest(document),request_key,reason,clock_timestamp());
 RETURN package_model_registry.read(identity,actor);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_model_registry FROM PUBLIC;
GRANT USAGE ON SCHEMA package_model_registry TO tender_api;
GRANT EXECUTE ON FUNCTION package_model_registry.source(uuid,uuid),package_model_registry.read(uuid,uuid),package_model_registry.register(uuid,uuid,jsonb,text,text) TO tender_api;
COMMIT;
