-- Optional fresh extension. No model issuance, activation or new external account role.
BEGIN;
CREATE FUNCTION package_prediction.eligible_certificates(actor uuid,bid uuid,scope uuid,method text,cert_method text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE item record; packet jsonb; result jsonb:='[]'::jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_prediction_actor_denied' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 FOR item IN SELECT id FROM package_model_admission.certificates WHERE actor_id=actor ORDER BY id LOOP
  BEGIN
   packet:=package_prediction.prepare(actor,bid,scope,item.id,method,cert_method);
   IF packet->'authority'->>'state'='active' THEN result:=result||jsonb_build_array(item.id); END IF;
  EXCEPTION WHEN SQLSTATE '42501' OR SQLSTATE '55000' OR SQLSTATE '22023' OR SQLSTATE 'P0002' THEN
   NULL;
  END;
 END LOOP;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION package_prediction.eligible_certificates(uuid,uuid,uuid,text,text) FROM PUBLIC,tender_worker;
GRANT EXECUTE ON FUNCTION package_prediction.eligible_certificates(uuid,uuid,uuid,text,text) TO tender_api;
-- Database publication guard also covers an older coordinator consuming the same job.
CREATE FUNCTION package_prediction.guard_project_intent() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE planned jsonb; r design.bid_package_review_runs; o design.operations; scope_row design.bid_package_technical_scopes; actual_result text; automatic boolean; result_manifest jsonb; expected_docs jsonb; actual_docs jsonb;
BEGIN
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT payload INTO planned FROM design.audit_entries WHERE event_type='package.prediction.pipeline_planned' AND payload->>'command'=NEW.command_id::text;
 IF planned IS NULL THEN RETURN NEW; END IF;
 IF planned->>'actor' IS DISTINCT FROM NEW.actor_id::text OR planned->>'bid' IS DISTINCT FROM NEW.bid_id::text
 OR planned->>'scope' IS DISTINCT FROM NEW.scope_id::text OR planned->>'certificate' IS DISTINCT FROM NEW.certificate_id::text
 OR EXISTS(SELECT FROM design.audit_entries WHERE event_type IN('package.prediction.pipeline_cancelled','package.prediction.pipeline_rejected') AND payload->>'command'=NEW.command_id::text) THEN
  RAISE EXCEPTION 'package_prediction_intent_changed' USING ERRCODE='55000'; END IF;
 SELECT * INTO scope_row FROM design.bid_package_technical_scopes WHERE id=NEW.scope_id AND bid_id=NEW.bid_id AND actor_id=NEW.actor_id;
 SELECT * INTO r FROM design.bid_package_review_runs WHERE bid_id=NEW.bid_id AND actor_id=NEW.actor_id
 AND input_manifest->'scope'=scope_row.manifest#>'{preview,manifest,scope}' ORDER BY created_at DESC,id DESC LIMIT 1;
 SELECT * INTO o FROM design.operations WHERE id=r.operation_id;
 SELECT digest::text,manifest INTO actual_result,result_manifest FROM design.bid_package_review_results WHERE run_id=r.id AND bid_id=NEW.bid_id AND operation_id=o.id;
 SELECT coalesce((settings->>'auto_review')::boolean,false) INTO automatic FROM design.bids WHERE id=NEW.bid_id;
 SELECT jsonb_agg(DISTINCT jsonb_build_array(v->>'document_version_id',v->>'parse_run_id',v->>'file_digest') ORDER BY jsonb_build_array(v->>'document_version_id',v->>'parse_run_id',v->>'file_digest')) INTO expected_docs FROM jsonb_array_elements(scope_row.manifest#>'{preview,manifest,documents}')v;
 SELECT jsonb_agg(DISTINCT jsonb_build_array(v->>'document_version_id',v->>'parse_run_id',v->>'file_digest') ORDER BY jsonb_build_array(v->>'document_version_id',v->>'parse_run_id',v->>'file_digest')) INTO actual_docs FROM jsonb_array_elements(result_manifest->'submitted_documents')v;
 IF expected_docs IS NULL OR actual_docs IS DISTINCT FROM expected_docs
 OR jsonb_array_length(expected_docs)<>jsonb_array_length(scope_row.manifest#>'{preview,manifest,documents}')
 OR jsonb_array_length(actual_docs)<>jsonb_array_length(result_manifest->'submitted_documents')
 OR actual_result IS DISTINCT FROM design.package_technical_digest(result_manifest) THEN
  RAISE EXCEPTION 'package_prediction_intent_documents_changed' USING ERRCODE='55000'; END IF;

 IF scope_row.digest::text IS DISTINCT FROM planned#>>'{snapshot,scope_digest}' OR r.id::text IS DISTINCT FROM planned#>>'{snapshot,review_id}'
 OR r.input_digest::text IS DISTINCT FROM planned#>>'{snapshot,review_input_digest}' OR actual_result IS NULL
 OR actual_result IS DISTINCT FROM planned#>>'{snapshot,review_result_digest}' OR o.state IS DISTINCT FROM 'succeeded'
 OR (CASE WHEN automatic THEN 'materials_ready' ELSE 'start_review' END) IS DISTINCT FROM planned#>>'{snapshot,trigger}'
 OR (CASE WHEN automatic THEN scope_row.command_id ELSE r.command_id END)::text IS DISTINCT FROM planned#>>'{snapshot,trigger_id}' THEN
  RAISE EXCEPTION 'package_prediction_intent_context_changed' USING ERRCODE='55000'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION package_prediction.guard_project_intent() FROM PUBLIC,tender_api,tender_worker;
CREATE TRIGGER guard_project_intent BEFORE INSERT ON package_prediction.results FOR EACH ROW EXECUTE FUNCTION package_prediction.guard_project_intent();
COMMIT;
