-- Optional fresh install after package-model-certification.sql; no provider calls.
BEGIN;
DO $$ BEGIN IF to_regprocedure('package_model_admission.read_certificate(uuid,uuid,text)') IS NULL THEN RAISE EXCEPTION 'package_prediction_dependencies_required' USING ERRCODE='55000'; END IF; END $$;
CREATE SCHEMA package_prediction;
REVOKE ALL ON SCHEMA package_prediction FROM PUBLIC;
GRANT USAGE ON SCHEMA package_prediction TO tender_api;
CREATE TABLE package_prediction.results(
 command_id uuid PRIMARY KEY,actor_id uuid NOT NULL REFERENCES design.members(id),bid_id uuid NOT NULL REFERENCES design.bids(id),
 scope_id uuid NOT NULL UNIQUE REFERENCES design.bid_package_technical_scopes(id),certificate_id uuid NOT NULL REFERENCES package_model_admission.certificates(id),
 method_digest design.sha256 NOT NULL,certificate_method_digest design.sha256 NOT NULL,source_digest design.sha256 NOT NULL,
 result jsonb NOT NULL,result_digest design.sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(result)=result_digest),CHECK(octet_length(result::text)<=16384)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_prediction.results FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_prediction.results FROM PUBLIC,tender_api,tender_worker;
CREATE FUNCTION package_prediction.prepare(actor uuid,bid uuid,scope uuid,certificate uuid,method text,cert_method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE authority jsonb; src jsonb; reference jsonb; seeds text[];
BEGIN
 PERFORM package_historical_research.assert_role('api');
 authority:=package_model_admission.read_certificate(actor,certificate,cert_method);
 IF authority->>'state' IS DISTINCT FROM 'active' THEN RAISE EXCEPTION 'package_prediction_certificate_unavailable' USING ERRCODE='55000'; END IF;
 src:=authority#>'{source,current_source}';
 IF src->>'bid_id' IS DISTINCT FROM bid::text OR src->>'scope_id' IS DISTINCT FROM scope::text OR src->>'mode' IS DISTINCT FROM 'live'
 OR method IS NULL OR method !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'package_prediction_scope_denied' USING ERRCODE='42501'; END IF;
 -- Existing certificate locks its complete candidate/fallback/input scope and authority.
 -- Never generate a prospective prediction once a label or submission is present.
 IF EXISTS(SELECT FROM design.outcomes WHERE bid_id=bid) OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=bid) THEN RAISE EXCEPTION 'package_prediction_not_prospective' USING ERRCODE='55000'; END IF;
 SELECT array_agg('package:'||m.admission_id::text) INTO seeds FROM package_historical_research.members m WHERE m.cohort_id IN((authority#>>'{source,model,source,cohort_id}')::uuid,(authority#>>'{source,fallback_model,source,cohort_id}')::uuid);
 IF bid=ANY(package_history_exposure_bridge.related_bids(seeds)) OR EXISTS(SELECT FROM package_history_exposure_bridge.entity_keys() k WHERE k.entity=ANY(package_history_exposure_bridge.related_entities(seeds)) AND k.kind='project' AND k.identity=design.identity_snapshot_v2(bid)->>'engineering_project_id') THEN RAISE EXCEPTION 'package_prediction_training_project_leak' USING ERRCODE='55000'; END IF;
 SELECT r.config->'reference' INTO reference FROM package_model_route.routes r WHERE r.id=(authority#>>'{source,shadow,route_id}')::uuid AND r.actor_id=actor;
 IF reference IS NULL THEN RAISE EXCEPTION 'package_prediction_material_reference_missing' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-formal-prediction-source/1','authority',authority,'reference',reference,'method_digest',method);
END $$;
CREATE FUNCTION package_prediction.read(actor uuid,bid uuid,scope uuid,command uuid,method text,cert_method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE old package_prediction.results; packet jsonb; state text:='valid'; visible boolean;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN RAISE EXCEPTION 'package_prediction_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO old FROM package_prediction.results WHERE command_id=command;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF old.actor_id IS DISTINCT FROM actor OR old.bid_id IS DISTINCT FROM bid OR old.scope_id IS DISTINCT FROM scope THEN RAISE EXCEPTION 'package_prediction_actor_denied' USING ERRCODE='42501'; END IF;
 IF old.method_digest::text IS DISTINCT FROM method OR old.certificate_method_digest::text IS DISTINCT FROM cert_method THEN state:='stale';
 ELSE BEGIN
  packet:=package_prediction.prepare(actor,bid,scope,old.certificate_id,method,cert_method);
  IF design.package_technical_digest(packet) IS DISTINCT FROM old.source_digest::text THEN state:='stale'; END IF;
 EXCEPTION WHEN SQLSTATE '55000' OR SQLSTATE '42501' OR SQLSTATE '40001' THEN state:='stale'; END; END IF;
 SELECT coalesce((settings->>'show_prediction')::boolean,false) INTO visible FROM design.bids WHERE id=bid;
 IF NOT visible AND state='valid' THEN state:='hidden'; END IF;
 RETURN jsonb_build_object('schema','package-formal-prediction/1','command_id',command,'actor_id',actor,'bid_id',bid,'scope_id',scope,'certificate_id',old.certificate_id,
 'model_id',old.result->'model_id','input_digest',old.result->'input_digest','method_digest',old.method_digest,'created_at',old.created_at,'state',state,
 'value',CASE WHEN state='valid' THEN old.result->'value' ELSE NULL END,'maximum',CASE WHEN state='valid' THEN '100' ELSE NULL END,
 'interval_level',CASE WHEN state='valid' THEN old.result->'interval_level' ELSE NULL END,
 'low',CASE WHEN state='valid' THEN old.result->'low' ELSE NULL END,'high',CASE WHEN state='valid' THEN old.result->'high' ELSE NULL END,
 'training_groups',CASE WHEN state='valid' THEN old.result->'training_groups' ELSE NULL END,
 'evaluation_project_mae',CASE WHEN state='valid' THEN old.result->'evaluation_project_mae' ELSE NULL END,
 'historical',state='stale','provider_requests',0);
END $$;
CREATE FUNCTION package_prediction.commit(actor uuid,bid uuid,scope uuid,certificate uuid,command uuid,expected text,result jsonb,method text,cert_method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE packet jsonb; old package_prediction.results; v numeric;
BEGIN
 PERFORM package_historical_research.assert_role('api');PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO old FROM package_prediction.results WHERE command_id=command OR scope_id=scope;
 IF FOUND THEN
  IF old.command_id IS DISTINCT FROM command OR old.actor_id IS DISTINCT FROM actor OR old.certificate_id IS DISTINCT FROM certificate OR old.bid_id IS DISTINCT FROM bid OR old.scope_id IS DISTINCT FROM scope OR old.source_digest::text IS DISTINCT FROM expected OR old.result IS DISTINCT FROM result THEN RAISE EXCEPTION 'package_prediction_already_fixed' USING ERRCODE='55000'; END IF;
  RETURN package_prediction.read(actor,bid,scope,command,method,cert_method);
 END IF;
 packet:=package_prediction.prepare(actor,bid,scope,certificate,method,cert_method);
 IF command IS NULL OR design.package_technical_digest(packet) IS DISTINCT FROM expected
 OR NOT design.package_json_keys(result,ARRAY['schema','method_digest','certificate_id','model_id','artifact_digest','input_digest','projection_digest','value','maximum','source_digest','interval_level','low','high','training_groups','evaluation_project_mae'])
 OR result->>'schema' IS DISTINCT FROM 'package-formal-prediction/1' OR result->>'method_digest' IS DISTINCT FROM method OR result->>'certificate_id' IS DISTINCT FROM certificate::text
 OR result->>'model_id' IS DISTINCT FROM packet#>>'{authority,certificate,model_id}' OR result->>'artifact_digest' IS DISTINCT FROM design.package_technical_digest(packet#>'{authority,source,model}')
 OR result->>'input_digest' IS DISTINCT FROM packet#>>'{authority,source,current_source,input_digest}' OR result->>'source_digest' IS DISTINCT FROM expected
 OR result->>'maximum' IS DISTINCT FROM '100' OR jsonb_typeof(result->'value') IS DISTINCT FROM 'string' OR result->>'projection_digest' IS NULL OR result->>'projection_digest' !~ '^[a-f0-9]{64}$'
 THEN RAISE EXCEPTION 'package_prediction_result_mismatch' USING ERRCODE='55000'; END IF;
 IF result->>'interval_level' IS DISTINCT FROM '0.8' OR result->'training_groups' IS DISTINCT FROM packet#>'{authority,source,model,source,candidate,groups}'
 OR result->'evaluation_project_mae' IS DISTINCT FROM packet#>'{authority,source,report,report,report,project_mae}'
 OR jsonb_typeof(result->'low') IS DISTINCT FROM 'string' OR jsonb_typeof(result->'high') IS DISTINCT FROM 'string'
 OR (result->>'low')::numeric IS DISTINCT FROM greatest(0,(result->>'value')::numeric-(packet#>>'{authority,source,model,source,candidate,intervals,0.8,radius}')::numeric)
 OR (result->>'high')::numeric IS DISTINCT FROM least(100,(result->>'value')::numeric+(packet#>>'{authority,source,model,source,candidate,intervals,0.8,radius}')::numeric)
 THEN RAISE EXCEPTION 'package_prediction_interval_mismatch' USING ERRCODE='55000'; END IF;
 v:=(result->>'value')::numeric;
 IF v IN('NaN','Infinity','-Infinity') OR v<0 OR v>100 THEN RAISE EXCEPTION 'package_prediction_value_invalid' USING ERRCODE='22023'; END IF;
 INSERT INTO package_prediction.results VALUES(command,actor,bid,scope,certificate,method,cert_method,expected,result,design.package_technical_digest(result),clock_timestamp());
 RETURN package_prediction.read(actor,bid,scope,command,method,cert_method);
END $$;
REVOKE ALL ON FUNCTION package_prediction.prepare(uuid,uuid,uuid,uuid,text,text),package_prediction.read(uuid,uuid,uuid,uuid,text,text),package_prediction.commit(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_prediction.prepare(uuid,uuid,uuid,uuid,text,text),package_prediction.read(uuid,uuid,uuid,uuid,text,text),package_prediction.commit(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text) TO tender_api;
-- Read a deterministic pre-submission pair from immutable sources. No retrospective
-- writes, label inputs or best-of-many selection; ambiguous scope matches are refused.
CREATE FUNCTION package_prediction.submission_pair(target uuid,as_of timestamptz,method text,cert_method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE matches jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT jsonb_agg(jsonb_build_object('prediction_id',p.command_id,'value',p.result->'value','maximum','100','created_at',p.created_at,'certificate_id',p.certificate_id,'scope_id',p.scope_id,'submission_id',s.id)) INTO matches
 FROM design.submission_records s JOIN design.bid_package_submission_bindings b ON b.submission_id=s.id
 JOIN design.bid_package_technical_scopes scope ON scope.bid_id=s.bid_id AND scope.package_id=b.package_id AND scope.revision_id=b.revision_id AND scope.inventory_id=b.inventory_id
 JOIN package_prediction.results p ON p.scope_id=scope.id AND p.bid_id=s.bid_id
 JOIN package_model_admission.certificates cert ON cert.id=p.certificate_id
 WHERE s.id=target AND s.subject_kind='bid_package' AND p.created_at<s.submitted_at AND s.submitted_at<=as_of AND p.created_at<=as_of
 AND p.method_digest::text=method AND p.certificate_method_digest::text=cert_method
 AND cert.issued_at<=p.created_at AND cert.valid_until>s.submitted_at
 AND NOT EXISTS(SELECT FROM package_model_admission.certificate_revocations r WHERE r.certificate_id=cert.id)
 AND scope.manifest#>>'{preview,manifest,basis,package_digest}'=b.manifest#>>'{subject,package_digest}'
 AND scope.manifest#>>'{preview,manifest,basis,authority_revision_id}'=b.authority_revision_id::text
 AND scope.manifest#>>'{preview,manifest,basis,identity_digest}'=b.manifest#>>'{package_identity,digest}'
 AND design.package_technical_digest(p.result)=p.result_digest;
 IF jsonb_array_length(matches) IS DISTINCT FROM 1 THEN RETURN NULL; END IF;
 RETURN matches->0;
END $$;
REVOKE ALL ON FUNCTION package_prediction.submission_pair(uuid,timestamptz,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_prediction.submission_pair(uuid,timestamptz,text,text) TO tender_api;
COMMIT;
