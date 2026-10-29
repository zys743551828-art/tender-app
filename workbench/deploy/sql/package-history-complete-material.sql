-- Optional complete-material training export /2. Fresh reviewed database only.
-- Install AFTER package-historical-research.sql and BEFORE exposure-bridge.sql.
-- Replaces one existing function, preserving its OID, owner and ACL. No grants.
-- Never edit or reseal an already installed exposure guard to install this file.
BEGIN;
DO $verify$ DECLARE p pg_proc; BEGIN
 IF to_regnamespace('package_history_exposure_bridge') IS NOT NULL
 OR EXISTS(SELECT FROM package_historical_research.cohorts)
 THEN RAISE EXCEPTION 'package_history_complete_fresh_install_required' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.read_training(uuid,bigint,bigint,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'jsonb'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'b1fc92b5b04309ec78ea03bf1437a0653ebe1f1d5e53c2531403992ba692ca19'
 THEN RAISE EXCEPTION 'package_history_complete_function_drift' USING ERRCODE='55000'; END IF;
END $verify$;
CREATE OR REPLACE FUNCTION package_historical_research.read_training(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $complete$
DECLARE job package_historical_research.jobs; training jsonb; bindings jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('train');
 -- The cross-lane exposure guard must be installed after this optional reader.
 IF to_regclass('package_history_exposure_bridge.guard_manifest') IS NULL
 THEN RAISE EXCEPTION 'package_history_complete_exposure_bridge_required' USING ERRCODE='55000'; END IF;
 job:=package_historical_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'train' THEN RAISE EXCEPTION 'package_history_purpose_denied' USING ERRCODE='42501'; END IF;
 SELECT document INTO training FROM package_historical_research.exports WHERE cohort_id=job.cohort_id AND purpose='training';
 -- Only training-side material identities; never return final/excluded labels,
 -- full official-label documents or arbitrary caller-supplied verification flags.
 SELECT jsonb_agg(jsonb_build_object(
  'admission_id',m.admission_id,'proof_id',p.id,'context_digest',p.context_digest,
  'bid_id',a.bid_id,'scope_id',a.scope_id,'scope_digest',s.digest,'scope_manifest',s.manifest,
  'project_id',p.native_context#>'{identity,engineering_project_id}',
  'submitted_at',m.submitted_at,'origin',a.origin,
  'originals',(SELECT jsonb_agg(jsonb_build_object('document_version_id',v->'document_version_id','digest',v->'digest','byte_size',v->'byte_size') ORDER BY v->>'document_version_id') FROM jsonb_array_elements(p.native_context->'originals')v),
  'label_document_id',p.native_context#>'{label,source_version_id}',
  'label_file_digest',p.native_context#>'{label,file_digest}') ORDER BY m.admission_id)
 INTO bindings FROM package_historical_research.members m
 JOIN package_historical_research.admissions a ON a.id=m.admission_id
 JOIN package_historical_research.proofs p ON p.id=m.proof_id
 JOIN design.bid_package_technical_scopes s ON s.id=a.scope_id
 WHERE m.cohort_id=job.cohort_id AND m.purpose IN('fit','development','calibration');
 IF training IS NULL OR bindings IS NULL OR jsonb_array_length(bindings)<>jsonb_array_length(training->'rows')
 OR octet_length(bindings::text)>16777216
 THEN RAISE EXCEPTION 'package_history_complete_bindings_invalid' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-history-complete-training-export/2',
  'training_export',training,'material_bindings',bindings,
  'bindings_digest',design.package_technical_digest(bindings));
END $complete$;
COMMIT;
