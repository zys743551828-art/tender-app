-- Optional fresh-install FR-002 protocol authority /1, after model-governance and the reviewed package-history exposure bridge.
-- No certification issuer, model route changes, runtime activation or new roles.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_history_exposure_bridge.readiness()') IS NULL
 OR EXISTS(SELECT FROM model_governance.cohorts) THEN
  RAISE EXCEPTION 'admission_fresh_bridge_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA model_admission;
REVOKE ALL ON SCHEMA model_admission FROM PUBLIC;
CREATE TABLE model_admission.protocols(
 cohort_id uuid PRIMARY KEY REFERENCES model_governance.cohorts(id),
 actor_id uuid NOT NULL REFERENCES design.members(id),
 cohort_digest design.sha256 NOT NULL,
 document jsonb NOT NULL,
 document_digest design.sha256 NOT NULL,
 request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 200),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(octet_length(document::text)<=16384),
 CHECK(document_digest::text=encode(sha256(convert_to(document::text,'UTF8')),'hex'))
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON model_admission.protocols
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON model_admission.protocols FROM PUBLIC,tender_api,tender_worker,tender_model_train,tender_model_evaluate,tender_model_score;
CREATE FUNCTION model_admission.read_protocol(target uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,model_admission,pg_temp AS $$
DECLARE stored model_admission.protocols;
BEGIN
 IF NOT EXISTS(SELECT FROM model_governance.cohorts c JOIN design.members m ON m.id=c.created_by
   WHERE c.id=target AND m.id=actor AND m.active) THEN
  RAISE EXCEPTION 'admission_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM model_admission.protocols WHERE cohort_id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'admission_protocol_missing' USING ERRCODE='55000'; END IF;
 RETURN to_jsonb(stored)||jsonb_build_object('schema','score-business-protocol-receipt/1',
  'formal_eligibility','unavailable','receipt_kind','immutable_freeze_record',
  'current_source_verified',false,'certification_issued',false);
END $$;
CREATE FUNCTION model_admission.freeze_protocol(target uuid,actor uuid,document jsonb,request_key text,reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,model_admission,pg_temp AS $$
DECLARE cohort model_governance.cohorts; old model_admission.protocols; item record; value numeric;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'admission_isolation_required' USING ERRCODE='55000'; END IF;
 -- Same ordering as source validation and existing final exposure; no Session sharing.
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO cohort FROM model_governance.cohorts WHERE id=target;
 IF cohort.id IS NULL OR cohort.created_by IS DISTINCT FROM actor OR NOT EXISTS(
  SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'admission_actor_denied' USING ERRCODE='42501'; END IF;
 IF document IS NULL OR jsonb_typeof(document)<>'object' OR octet_length(document::text)>16384 THEN
  RAISE EXCEPTION 'admission_protocol_invalid' USING ERRCODE='22023'; END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document)k) IS DISTINCT FROM ARRAY['artifact_family','baseline','schema','thresholds']::text[]
  OR document->>'schema' IS DISTINCT FROM 'score-business-admission-protocol/1'
  OR document->>'artifact_family' IS DISTINCT FROM 'registered-score-artifact/1'
  OR document->>'baseline' IS NULL OR document->>'baseline' NOT IN ('mean','median')
  OR jsonb_typeof(document->'thresholds') IS DISTINCT FROM 'object'
  OR request_key IS NULL OR length(btrim(request_key)) NOT BETWEEN 1 AND 200
  OR reason IS NULL OR length(btrim(reason)) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'admission_protocol_invalid' USING ERRCODE='22023'; END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(document->'thresholds')k)
  IS DISTINCT FROM ARRAY['interval_level','maximum_project_mae','minimum_interval_coverage','minimum_paired_baseline_gain','minimum_success_coverage']::text[] THEN
  RAISE EXCEPTION 'admission_thresholds_required' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT * FROM jsonb_each(document->'thresholds') LOOP
  IF jsonb_typeof(item.value)<>'number' THEN RAISE EXCEPTION 'admission_threshold_invalid' USING ERRCODE='22023'; END IF;
  value:=item.value::text::numeric;
  IF (item.key='maximum_project_mae' AND (value<0 OR value>100))
   OR (item.key='minimum_paired_baseline_gain' AND (value< -100 OR value>100))
   OR (item.key IN ('minimum_success_coverage','minimum_interval_coverage') AND (value<0 OR value>1))
   OR (item.key='interval_level' AND (value<=0 OR value>=1)) THEN
   RAISE EXCEPTION 'admission_threshold_invalid' USING ERRCODE='22023'; END IF;
 END LOOP;
 SELECT * INTO old FROM model_admission.protocols WHERE cohort_id=target;
 IF FOUND THEN
  IF old.request_key IS DISTINCT FROM request_key OR old.document IS DISTINCT FROM document OR old.reason IS DISTINCT FROM reason THEN
   RAISE EXCEPTION 'admission_protocol_already_frozen' USING ERRCODE='55000'; END IF;
  -- Lost ACK returns only the immutable historical receipt, never current eligibility.
  RETURN model_admission.read_protocol(target,actor);
 END IF;
 IF package_history_exposure_bridge.readiness()->>'configured' IS DISTINCT FROM 'true' THEN
  RAISE EXCEPTION 'admission_exposure_authority_unavailable' USING ERRCODE='55000'; END IF;
 IF NOT model_governance.current_cohort(target) THEN
  RAISE EXCEPTION 'admission_source_stale' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91144,1);
 IF EXISTS(SELECT FROM model_governance.exposures x JOIN model_governance.jobs j ON j.id=x.job_id WHERE j.cohort_id=target)
 OR EXISTS(SELECT FROM model_governance.members m CROSS JOIN LATERAL
  (VALUES('sample',m.sample_id::text),('group',m.group_id::text),('project',m.project_id::text),
   ('body',m.body_digest::text),('template',m.template_key),('near_duplicate',m.near_duplicate_key))k(kind,identity)
  JOIN model_governance.exposure_members e ON e.kind=k.kind AND e.identity=k.identity WHERE m.cohort_id=target) THEN
  RAISE EXCEPTION 'admission_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO model_admission.protocols VALUES(target,actor,cohort.digest,document,
  encode(sha256(convert_to(document::text,'UTF8')),'hex'),request_key,reason,clock_timestamp());
 RETURN model_admission.read_protocol(target,actor);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA model_admission FROM PUBLIC;
GRANT USAGE ON SCHEMA model_admission TO tender_api;
GRANT EXECUTE ON FUNCTION model_admission.freeze_protocol(uuid,uuid,jsonb,text,text),model_admission.read_protocol(uuid,uuid) TO tender_api;
COMMIT;
