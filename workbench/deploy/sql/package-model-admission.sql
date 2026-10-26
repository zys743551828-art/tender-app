-- Optional fresh-install /3 business protocol and native final report binding.
-- Requires package-model-registry; never issues certification or enables execution.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_model_registry.source(uuid,uuid)') IS NULL
 OR EXISTS(SELECT FROM package_historical_research.cohorts) THEN
  RAISE EXCEPTION 'package_admission_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA package_model_admission;
REVOKE ALL ON SCHEMA package_model_admission FROM PUBLIC;
CREATE TABLE package_model_admission.protocols(
 model_id uuid PRIMARY KEY REFERENCES package_model_registry.registrations(model_id),
 cohort_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.cohorts(id),
 actor_id uuid NOT NULL REFERENCES design.members(id),document jsonb NOT NULL,digest design.sha256 NOT NULL,
 request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 200),reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 frozen_xact xid8 NOT NULL DEFAULT pg_current_xact_id(),frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(octet_length(document::text)<=16384),CHECK(design.package_technical_digest(document)=digest)
);
CREATE TABLE package_model_admission.reports(
 model_id uuid PRIMARY KEY REFERENCES package_model_admission.protocols(model_id),
 evaluation_job_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.results(job_id),
 actor_id uuid NOT NULL REFERENCES design.members(id),packet jsonb NOT NULL,packet_digest design.sha256 NOT NULL,
 request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 200),reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),CHECK(octet_length(packet::text)<=2097152),
 CHECK(design.package_technical_digest(packet)=packet_digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_model_admission.protocols FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_model_admission.reports FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON ALL TABLES IN SCHEMA package_model_admission FROM PUBLIC,tender_api,tender_worker,tender_model_train,tender_model_evaluate,tender_model_score;
CREATE FUNCTION package_model_admission.context(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE registered jsonb; source jsonb; manifest text; bound jsonb;
BEGIN
 registered:=package_model_registry.read(target,actor);
 source:=registered#>'{document,source}';
 SELECT digest::text INTO manifest FROM package_historical_research.exports
 WHERE cohort_id=(source->>'cohort_id')::uuid AND purpose='final_manifest';
 IF manifest IS NULL THEN RAISE EXCEPTION 'package_admission_manifest_missing' USING ERRCODE='55000'; END IF;
 bound:=jsonb_build_object('model_id',target,'artifact_digest',registered->>'artifact_digest',
  'cohort_id',source->>'cohort_id','cohort_digest',source->>'cohort_digest','membership_digest',source->>'membership_digest',
  'candidate_digest',source->>'candidate_digest','training_method_digest',source#>>'{candidate,method_digest}',
  'input_reference_digest',source#>>'{candidate,source_digest}','final_manifest_digest',manifest);
 RETURN jsonb_build_object('schema','package-admission-context/1','binding',bound,'artifact',registered->'document',
  'formal_eligibility','unavailable','certification_issued',false);
END $$;
CREATE FUNCTION package_model_admission.read_protocol(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE stored package_model_admission.protocols;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO stored FROM package_model_admission.protocols WHERE model_id=target;
 IF stored.model_id IS NULL OR stored.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_admission_actor_denied' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('schema','package-admission-protocol-receipt/1','document',stored.document,'digest',stored.digest,
  'frozen_at',stored.frozen_at,'snapshot_only',true,'formal_eligibility','unavailable','certification_issued',false);
END $$;
CREATE FUNCTION package_model_admission.freeze_protocol(target uuid,actor uuid,document jsonb,request_key text,reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE ctx jsonb; old package_model_admission.protocols; cohort uuid; item record; n numeric;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 PERFORM pg_advisory_xact_lock(91143,1);
 IF document IS NULL OR jsonb_typeof(document)<>'object' OR octet_length(document::text)>16384
 OR request_key IS NULL OR length(btrim(request_key)) NOT BETWEEN 1 AND 200
 OR reason IS NULL OR length(btrim(reason)) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'package_admission_protocol_invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM package_model_admission.protocols WHERE model_id=target;
 IF FOUND THEN
  IF old.actor_id IS DISTINCT FROM actor OR old.document IS DISTINCT FROM document OR old.request_key IS DISTINCT FROM request_key OR old.reason IS DISTINCT FROM reason THEN
   RAISE EXCEPTION 'package_admission_already_frozen' USING ERRCODE='55000'; END IF;
  RETURN package_model_admission.read_protocol(target,actor);
 END IF;
 ctx:=package_model_admission.context(target,actor);
 cohort:=(ctx#>>'{binding,cohort_id}')::uuid;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document)k) IS DISTINCT FROM ARRAY['artifact_family','baseline','binding','schema','thresholds']::text[]
 OR document->>'schema' IS DISTINCT FROM 'score-business-admission-protocol/2'
 OR document->>'artifact_family' IS DISTINCT FROM 'registered-package-score-artifact/1'
 OR document->'binding' IS DISTINCT FROM ctx->'binding'
 OR (document->>'baseline' IN ('mean','median')) IS NOT TRUE
 OR jsonb_typeof(document->'thresholds') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'package_admission_binding_invalid' USING ERRCODE='22023'; END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document->'thresholds')k) IS DISTINCT FROM
 ARRAY['interval_level','maximum_project_mae','minimum_interval_coverage','minimum_paired_baseline_gain','minimum_success_coverage']::text[] THEN
  RAISE EXCEPTION 'package_admission_thresholds_required' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT * FROM jsonb_each(document->'thresholds') LOOP
  IF jsonb_typeof(item.value)<>'string' OR length(item.value#>>'{}') NOT BETWEEN 1 AND 80 THEN
   RAISE EXCEPTION 'package_admission_threshold_invalid' USING ERRCODE='22023'; END IF;
  n:=(item.value#>>'{}')::numeric;
  IF n IN ('NaN','Infinity','-Infinity')
   OR (item.key='maximum_project_mae' AND (n<0 OR n>100))
   OR (item.key='minimum_paired_baseline_gain' AND (n< -100 OR n>100))
   OR (item.key IN ('minimum_interval_coverage','minimum_success_coverage') AND (n<0 OR n>1))
   OR (item.key='interval_level' AND (item.value#>>'{}') NOT IN ('0.8','0.9')) THEN
   RAISE EXCEPTION 'package_admission_threshold_invalid' USING ERRCODE='22023'; END IF;
 END LOOP;
 -- Context's current_cohort holds the reviewed cross-channel closure/exposure locks.
 PERFORM pg_advisory_xact_lock(91144,1);
 IF EXISTS(SELECT FROM package_historical_research.exposures WHERE cohort_id=cohort) THEN
  RAISE EXCEPTION 'package_admission_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO package_model_admission.protocols VALUES(target,cohort,actor,document,design.package_technical_digest(document),request_key,reason,pg_current_xact_id(),clock_timestamp());
 RETURN package_model_admission.read_protocol(target,actor);
END $$;
CREATE FUNCTION package_model_admission.report_source(target uuid,evaluation_job uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE ctx jsonb; frozen package_model_admission.protocols; job package_historical_research.jobs;
 exposure package_historical_research.exposures; result package_historical_research.results; report jsonb;
 input package_historical_research.feature_final_inputs; prediction package_historical_research.feature_final_predictions;
BEGIN
 ctx:=package_model_admission.context(target,actor);
 SELECT * INTO frozen FROM package_model_admission.protocols WHERE model_id=target;
 IF frozen.model_id IS NULL OR frozen.actor_id IS DISTINCT FROM actor OR frozen.document->'binding' IS DISTINCT FROM ctx->'binding' THEN
  RAISE EXCEPTION 'package_admission_frozen_binding_required' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=evaluation_job;
 SELECT * INTO exposure FROM package_historical_research.exposures WHERE job_id=evaluation_job;
 SELECT * INTO result FROM package_historical_research.results WHERE job_id=evaluation_job;
 SELECT * INTO input FROM package_historical_research.feature_final_inputs WHERE job_id=evaluation_job;
 SELECT * INTO prediction FROM package_historical_research.feature_final_predictions WHERE job_id=evaluation_job;
 IF job.id IS NULL OR job.kind<>'evaluate' OR job.state<>'succeeded' OR job.cohort_id<>frozen.cohort_id
 OR exposure.id IS NULL OR exposure.cohort_id<>frozen.cohort_id
 OR frozen.frozen_at>=exposure.created_at OR frozen.frozen_xact=exposure.created_xact
 OR exposure.created_xact=pg_current_xact_id() OR result.job_id IS NULL
 OR input.job_id IS NULL OR prediction.job_id IS NULL
 OR input.document->>'candidate_digest' IS DISTINCT FROM ctx#>>'{binding,candidate_digest}'
 OR input.document->>'manifest_digest' IS DISTINCT FROM ctx#>>'{binding,final_manifest_digest}' THEN
  RAISE EXCEPTION 'package_admission_final_identity_invalid' USING ERRCODE='55000'; END IF;
 report:=result.document->'feature_final_evaluation';
 IF report IS NULL OR report->>'candidate_digest' IS DISTINCT FROM ctx#>>'{binding,candidate_digest}'
 OR report->>'exposure_id' IS DISTINCT FROM exposure.id::text
 OR report->>'model_digest' IS DISTINCT FROM ctx#>>'{artifact,source,candidate,model_digest}'
 OR report->>'input_digest' IS DISTINCT FROM input.digest::text
 OR report->>'predictions_digest' IS DISTINCT FROM prediction.digest::text
 OR report->>'labels_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.exports WHERE cohort_id=frozen.cohort_id AND purpose='final_labels')
 OR report->>'origin' IS DISTINCT FROM ctx#>>'{artifact,source,origin}' THEN
  RAISE EXCEPTION 'package_admission_report_binding_invalid' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-admission-native-report/1','protocol',frozen.document,'protocol_digest',frozen.digest,
  'protocol_frozen_at',frozen.frozen_at,'exposure_at',exposure.created_at,'exposure_id',exposure.id,
  'evaluation_job_id',evaluation_job,'result_digest',result.digest,'report',report);
END $$;
CREATE FUNCTION package_model_admission.read_report(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE stored package_model_admission.reports;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO stored FROM package_model_admission.reports WHERE model_id=target;
 IF stored.model_id IS NULL OR stored.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_admission_actor_denied' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('schema','package-admission-report-receipt/1','model_id',target,'evaluation_job_id',stored.evaluation_job_id,
  'packet',stored.packet,'packet_digest',stored.packet_digest,'created_at',stored.created_at,'snapshot_only',true,
  'formal_eligibility','unavailable','certification_issued',false);
END $$;
CREATE FUNCTION package_model_admission.register_report(target uuid,evaluation_job uuid,actor uuid,expected_digest text,request_key text,reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_admission,pg_temp SET TimeZone='UTC' AS $$
DECLARE packet jsonb; fingerprint text; old package_model_admission.reports;
BEGIN
 packet:=package_model_admission.report_source(target,evaluation_job,actor);
 fingerprint:=design.package_technical_digest(packet);
 IF expected_digest IS DISTINCT FROM fingerprint OR request_key IS NULL OR length(btrim(request_key)) NOT BETWEEN 1 AND 200
 OR reason IS NULL OR length(btrim(reason)) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'package_admission_report_changed' USING ERRCODE='55000'; END IF;
 SELECT * INTO old FROM package_model_admission.reports WHERE model_id=target;
 IF FOUND THEN
  IF old.evaluation_job_id IS DISTINCT FROM evaluation_job OR old.actor_id IS DISTINCT FROM actor
  OR old.packet_digest::text IS DISTINCT FROM expected_digest OR old.request_key IS DISTINCT FROM request_key OR old.reason IS DISTINCT FROM reason THEN
   RAISE EXCEPTION 'package_admission_report_already_registered' USING ERRCODE='55000'; END IF;
  RETURN package_model_admission.read_report(target,actor);
 END IF;
 INSERT INTO package_model_admission.reports VALUES(target,evaluation_job,actor,packet,fingerprint,request_key,reason,clock_timestamp());
 RETURN package_model_admission.read_report(target,actor);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_model_admission FROM PUBLIC;
GRANT USAGE ON SCHEMA package_model_admission TO tender_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA package_model_admission TO tender_api;
COMMIT;
