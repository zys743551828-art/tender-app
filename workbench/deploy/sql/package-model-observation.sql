-- Optional fresh /3 internal retrospective observations. No certification/routing.
-- Install after package-model-registry.sql. Existing nonowner API role only.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_model_registry.read(uuid,uuid)') IS NULL
 OR EXISTS(SELECT FROM package_model_registry.registrations) THEN
  RAISE EXCEPTION 'package_observation_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA package_model_observation;
REVOKE ALL ON SCHEMA package_model_observation FROM PUBLIC;
CREATE TABLE package_model_observation.events(
 command_id uuid PRIMARY KEY,actor_id uuid NOT NULL REFERENCES design.members(id),
 model_id uuid NOT NULL REFERENCES package_model_registry.registrations(model_id),
 admission_id uuid NOT NULL REFERENCES package_historical_research.admissions(id),
 request jsonb NOT NULL,request_digest design.sha256 NOT NULL,
 source jsonb NOT NULL,source_digest design.sha256 NOT NULL,
 result jsonb NOT NULL,result_digest design.sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(request)=request_digest),
 CHECK(design.package_technical_digest(source)=source_digest),
 CHECK(design.package_technical_digest(result)=result_digest),
 CHECK(octet_length(source::text)<=16777216),CHECK(octet_length(result::text)<=16384)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_model_observation.events
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_model_observation.events FROM PUBLIC,tender_api,tender_worker,tender_model_train,tender_model_evaluate,tender_model_score;
CREATE FUNCTION package_model_observation.source(actor uuid,model uuid,admission uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_observation,pg_temp SET timezone='UTC' AS $$
DECLARE registration package_model_registry.registrations; a package_historical_research.admissions;
 p package_historical_research.proofs; s design.bid_package_technical_scopes;
 members text[]; seeds text[]; registered jsonb; binding jsonb; labels jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO registration FROM package_model_registry.registrations WHERE model_id=model;
 SELECT * INTO a FROM package_historical_research.admissions WHERE id=admission;
 IF registration.actor_id IS DISTINCT FROM actor OR a.created_by IS DISTINCT FROM actor
 OR NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_observation_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT array_agg('package:'||m.admission_id::text ORDER BY m.admission_id) INTO members
 FROM package_historical_research.members m
 WHERE m.cohort_id=(registration.document#>>'{source,cohort_id}')::uuid;
 IF members IS NULL THEN RAISE EXCEPTION 'package_observation_cohort_missing' USING ERRCODE='55000'; END IF;
 seeds:=members||ARRAY['package:'||admission::text];
 -- Union all bids before graph/exposure locks; never take a second bid after graph.
 PERFORM package_history_exposure_bridge.lock_scope(seeds);
 IF package_history_exposure_bridge.related_entities(members) && package_history_exposure_bridge.related_entities(ARRAY['package:'||admission::text])
 OR package_history_exposure_bridge.has_foreign_exposure(ARRAY['package:'||admission::text],NULL,NULL) THEN
  RAISE EXCEPTION 'package_observation_source_leak' USING ERRCODE='55000'; END IF;
 registered:=package_model_registry.read(model,actor);
 IF package_historical_research.current_proof(a.proof_id) IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'package_observation_source_stale' USING ERRCODE='55000'; END IF;
 PERFORM package_historical_research.assert_origin(a.origin,true);
 IF a.origin IS DISTINCT FROM registered#>>'{document,source,origin}' THEN
  RAISE EXCEPTION 'package_observation_origin_mismatch' USING ERRCODE='55000'; END IF;
 SELECT * INTO p FROM package_historical_research.proofs WHERE id=a.proof_id;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=a.scope_id;
 binding:=jsonb_build_object('admission_id',a.id,'proof_id',p.id,'context_digest',p.context_digest,
  'bid_id',a.bid_id,'scope_id',a.scope_id,'scope_digest',s.digest,'scope_manifest',s.manifest,
  'submitted_at',p.native_context#>'{submission,submitted_at}','origin',a.origin,
  'originals',(SELECT jsonb_agg(jsonb_build_object('document_version_id',v->'document_version_id','digest',v->'digest','byte_size',v->'byte_size') ORDER BY v->>'document_version_id') FROM jsonb_array_elements(p.native_context->'originals')v));
 -- Exclusion identities only; no official labels or target values enter CPU.
 SELECT jsonb_build_object(
  'ids',jsonb_agg(DISTINCT proof.native_context#>'{label,source_version_id}'),
  'digests',jsonb_agg(DISTINCT proof.native_context#>'{label,file_digest}')) INTO labels
 FROM package_historical_research.proofs proof
 JOIN package_historical_research.admissions admitted ON admitted.proof_id=proof.id
 WHERE 'package:'||admitted.id::text=ANY(seeds);
 RETURN jsonb_build_object('schema','package-native-observation-source/1',
  'document',registered->'document','binding',binding,
  'closure',package_history_exposure_bridge.closure_snapshot(seeds),
  'label_document_ids',labels->'ids','label_file_digests',labels->'digests');
END $$;
CREATE FUNCTION package_model_observation.replay(actor uuid,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_observation,pg_temp SET timezone='UTC' AS $$
DECLARE stored package_model_observation.events;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_observation_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM package_model_observation.events WHERE command_id=(body->>'command_id')::uuid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF stored.actor_id IS DISTINCT FROM actor THEN
  RAISE EXCEPTION 'package_observation_actor_denied' USING ERRCODE='42501'; END IF;
 IF stored.request IS DISTINCT FROM body THEN
  RAISE EXCEPTION 'package_observation_command_reused' USING ERRCODE='55000'; END IF;
 -- Historical receipt remains recoverable after source revocation, never authority.
 RETURN jsonb_build_object('schema','package-internal-observation-receipt/1',
  'command_id',stored.command_id,'model_id',stored.model_id,'admission_id',stored.admission_id,
  'request_digest',stored.request_digest,'source_digest',stored.source_digest,'result_digest',stored.result_digest,
  'mode','retrospective_internal','historical_receipt',true,'current_authority_checked',false,
  'formal_eligibility','unavailable','certification_issued',false);
END $$;
CREATE FUNCTION package_model_observation.record(actor uuid,body jsonb,pinned text,prediction jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_observation,pg_temp SET timezone='UTC' AS $$
DECLARE snapshot jsonb; previous jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 -- Global scope lock also serializes command replay and commit after lost ACK.
 PERFORM pg_advisory_xact_lock(91143,1);
 previous:=package_model_observation.replay(actor,body);
 IF previous IS NOT NULL THEN RETURN previous; END IF;
 IF body IS NULL OR octet_length(body::text)>16384
 OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(body)k) IS DISTINCT FROM
 ARRAY['admission_id','artifact_digest','command_id','method_digest','model_id','reference','version']::text[]
 OR body->>'version' IS DISTINCT FROM 'package-internal-observation-request/1'
 OR body->>'method_digest' IS NULL OR body->>'method_digest' !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'package_observation_request_invalid' USING ERRCODE='22023'; END IF;
 snapshot:=package_model_observation.source(actor,(body->>'model_id')::uuid,(body->>'admission_id')::uuid);
 IF design.package_technical_digest(snapshot) IS DISTINCT FROM pinned
 OR design.package_technical_digest(snapshot->'document') IS DISTINCT FROM body->>'artifact_digest'
 OR prediction IS NULL OR octet_length(prediction::text)>16384
 OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(prediction)k) IS DISTINCT FROM
 ARRAY['artifact_digest','certification_issued','formal_eligibility','input_digest','intervals','method_digest','mode','model_id','origin','projection_digest','request_digest','schema','source_digest','value']::text[]
 OR prediction->>'schema' IS DISTINCT FROM 'package-internal-observation/1'
 OR prediction->>'method_digest' IS DISTINCT FROM body->>'method_digest'
 OR prediction->>'source_digest' IS DISTINCT FROM pinned
 OR prediction->>'request_digest' IS DISTINCT FROM design.package_technical_digest(body)
 OR prediction->>'model_id' IS DISTINCT FROM body->>'model_id'
 OR prediction->>'artifact_digest' IS DISTINCT FROM body->>'artifact_digest'
 OR prediction->>'input_digest' IS DISTINCT FROM body#>>'{reference,expected_input_digest}'
 OR prediction->>'origin' IS DISTINCT FROM snapshot#>>'{binding,origin}'
 OR prediction->>'mode' IS DISTINCT FROM 'retrospective_internal'
 OR prediction->>'formal_eligibility' IS DISTINCT FROM 'unavailable'
 OR prediction->'certification_issued' IS DISTINCT FROM 'false'::jsonb
 OR prediction->>'projection_digest' IS NULL OR prediction->>'projection_digest' !~ '^[a-f0-9]{64}$'
 OR prediction->>'value' IS NULL OR prediction->>'value' !~ '^[0-9]+(\.[0-9]+)?$'
 THEN RAISE EXCEPTION 'package_observation_result_mismatch' USING ERRCODE='55000'; END IF;
 IF (prediction->>'value')::numeric NOT BETWEEN 0 AND 100 THEN
  RAISE EXCEPTION 'package_observation_result_invalid' USING ERRCODE='22023'; END IF;
 INSERT INTO package_model_observation.events VALUES((body->>'command_id')::uuid,actor,
  (body->>'model_id')::uuid,(body->>'admission_id')::uuid,body,design.package_technical_digest(body),
  snapshot,pinned,prediction,design.package_technical_digest(prediction),clock_timestamp());
 RETURN package_model_observation.replay(actor,body);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_model_observation FROM PUBLIC;
GRANT USAGE ON SCHEMA package_model_observation TO tender_api;
GRANT EXECUTE ON FUNCTION package_model_observation.source(uuid,uuid,uuid),package_model_observation.replay(uuid,jsonb),package_model_observation.record(uuid,jsonb,text,jsonb) TO tender_api;
COMMIT;
