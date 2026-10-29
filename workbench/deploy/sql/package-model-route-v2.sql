-- Native installer /2: parenthesized CASE expression; /1 bytes retained.
-- Optional fresh internal /3 route exercise. No business route/certification writes.
-- Requires package-model-observation.sql; install before any observation events.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('package_model_observation.record(uuid,jsonb,text,jsonb)') IS NULL
 OR EXISTS(SELECT FROM package_model_observation.events) THEN
  RAISE EXCEPTION 'package_internal_route_fresh_dependencies_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA package_model_route;
REVOKE ALL ON SCHEMA package_model_route FROM PUBLIC;
CREATE TABLE package_model_route.routes(
 id uuid PRIMARY KEY,actor_id uuid NOT NULL REFERENCES design.members(id),
 config jsonb NOT NULL,method_digest design.sha256 NOT NULL,
 revision bigint NOT NULL CHECK(revision>0),current_model_id uuid NOT NULL REFERENCES package_model_registry.registrations(model_id),
 rolled_back boolean NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_model_route.events(
 command_id uuid PRIMARY KEY,route_id uuid NOT NULL REFERENCES package_model_route.routes(id),
 actor_id uuid NOT NULL REFERENCES design.members(id),revision bigint NOT NULL CHECK(revision>0),
 action text NOT NULL CHECK(action IN('activate','consume','rollback')),
 previous_model_id uuid REFERENCES package_model_registry.registrations(model_id),
 selected_model_id uuid NOT NULL REFERENCES package_model_registry.registrations(model_id),
 request jsonb NOT NULL,request_digest design.sha256 NOT NULL,packet_digest design.sha256 NOT NULL,
 observation_id uuid NOT NULL UNIQUE REFERENCES package_model_observation.events(command_id),
 result_digest design.sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(route_id,revision),CHECK(design.package_technical_digest(request)=request_digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_model_route.events
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON ALL TABLES IN SCHEMA package_model_route FROM PUBLIC,tender_api,tender_worker,tender_model_train,tender_model_evaluate,tender_model_score;
CREATE FUNCTION package_model_route.replay(actor uuid,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_route,pg_temp SET timezone='UTC' AS $$
DECLARE stored package_model_route.events;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_internal_route_actor_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM package_model_route.events WHERE command_id=(body->>'command_id')::uuid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF stored.actor_id IS DISTINCT FROM actor THEN
  RAISE EXCEPTION 'package_internal_route_actor_denied' USING ERRCODE='42501'; END IF;
 IF stored.request IS DISTINCT FROM body THEN
  RAISE EXCEPTION 'package_internal_route_command_reused' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('schema','package-internal-route-receipt/1','route_id',stored.route_id,
  'command_id',stored.command_id,'revision',stored.revision,'action',stored.action,
  'previous_model_id',stored.previous_model_id,'selected_model_id',stored.selected_model_id,
  'request_digest',stored.request_digest,'packet_digest',stored.packet_digest,
  'observation_id',stored.observation_id,'result_digest',stored.result_digest,
  'mode','retrospective_internal','historical_receipt',true,'current_authority_checked',false,
  'business_route_changed',false,'certification_issued',false,'formal_eligibility','unavailable');
END $$;
CREATE FUNCTION package_model_route.prepare(actor uuid,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_route,pg_temp SET timezone='UTC' AS $$
DECLARE old package_model_route.routes; config jsonb; target uuid; snapshot jsonb; fallback jsonb;
 members text[]; previous uuid; expected bigint; observation jsonb; action_name text;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT EXISTS(SELECT FROM design.members WHERE id=actor AND active) THEN
  RAISE EXCEPTION 'package_internal_route_actor_denied' USING ERRCODE='42501'; END IF;
 action_name:=body->>'action';
 IF body IS NULL OR octet_length(body::text)>16384 OR body->>'version' IS DISTINCT FROM 'package-internal-route-command/1'
 OR action_name IS NULL OR action_name NOT IN('activate','consume','rollback')
 OR body->>'method_digest' IS NULL OR body->>'method_digest' !~ '^[a-f0-9]{64}$'
 OR body->>'expected_revision' IS NULL OR jsonb_typeof(body->'expected_revision') IS DISTINCT FROM 'number'
 OR body->>'expected_revision' !~ '^[0-9]+$'
 OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(body)k) IS DISTINCT FROM
 (CASE WHEN action_name='activate' THEN ARRAY['action','command_id','config','expected_revision','method_digest','route_id','version']::text[]
 ELSE ARRAY['action','command_id','expected_revision','method_digest','route_id','version']::text[] END) THEN
  RAISE EXCEPTION 'package_internal_route_request_invalid' USING ERRCODE='22023'; END IF;
 expected:=(body->>'expected_revision')::bigint;
 IF expected<0 OR expected>=9007199254740992 THEN RAISE EXCEPTION 'package_internal_route_revision_invalid' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO old FROM package_model_route.routes WHERE id=(body->>'route_id')::uuid FOR UPDATE;
 IF old.id IS NOT NULL AND old.actor_id IS DISTINCT FROM actor THEN
  RAISE EXCEPTION 'package_internal_route_actor_denied' USING ERRCODE='42501'; END IF;
 IF action_name='activate' THEN
  IF old.id IS NOT NULL OR expected<>0 THEN RAISE EXCEPTION 'package_internal_route_revision_conflict' USING ERRCODE='40001'; END IF;
  config:=body->'config';
  IF config IS NULL OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(config)k) IS DISTINCT FROM
   ARRAY['admission_id','candidate_artifact_digest','candidate_model_id','fallback_artifact_digest','fallback_model_id','observation_method_digest','reference']::text[]
  OR config->>'candidate_model_id' IS NULL OR config->>'fallback_model_id' IS NULL OR config->>'admission_id' IS NULL
  OR (config->>'candidate_model_id')::uuid=(config->>'fallback_model_id')::uuid
  OR config->>'observation_method_digest' IS NULL OR config->>'observation_method_digest' !~ '^[a-f0-9]{64}$' THEN
   RAISE EXCEPTION 'package_internal_route_config_invalid' USING ERRCODE='22023'; END IF;
  target:=(config->>'candidate_model_id')::uuid;
 ELSE
  IF old.id IS NULL OR old.revision<>expected THEN RAISE EXCEPTION 'package_internal_route_revision_conflict' USING ERRCODE='40001'; END IF;
  IF body->>'method_digest' IS DISTINCT FROM old.method_digest::text THEN
   RAISE EXCEPTION 'package_internal_route_method_changed' USING ERRCODE='55000'; END IF;
  config:=old.config; previous:=old.current_model_id;
  IF action_name='rollback' THEN
   IF old.rolled_back OR previous IS DISTINCT FROM (config->>'candidate_model_id')::uuid THEN
    RAISE EXCEPTION 'package_internal_route_rollback_target_invalid' USING ERRCODE='55000'; END IF;
   target:=(config->>'fallback_model_id')::uuid;
  ELSE target:=previous; END IF;
 END IF;
 -- Candidate/current/fallback union before graph lock, matching existing release semantics.
 SELECT array_agg(DISTINCT 'package:'||m.admission_id::text ORDER BY 'package:'||m.admission_id::text) INTO members
 FROM package_model_registry.registrations r JOIN package_historical_research.members m
 ON m.cohort_id=(r.document#>>'{source,cohort_id}')::uuid
 WHERE r.model_id IN((config->>'candidate_model_id')::uuid,(config->>'fallback_model_id')::uuid);
 IF members IS NULL THEN RAISE EXCEPTION 'package_internal_route_sources_missing' USING ERRCODE='55000'; END IF;
 PERFORM package_history_exposure_bridge.lock_scope(members||ARRAY['package:'||(config->>'admission_id')]);
 -- Rollback must remain possible when the old candidate source was revoked.
 -- Only the selected target grants fresh consumption; no stale fallback is allowed.
 snapshot:=package_model_observation.source(actor,target,(config->>'admission_id')::uuid);
 IF design.package_technical_digest(snapshot->'document') IS DISTINCT FROM
  (CASE WHEN target=(config->>'candidate_model_id')::uuid THEN config->>'candidate_artifact_digest' ELSE config->>'fallback_artifact_digest' END) THEN
  RAISE EXCEPTION 'package_internal_route_artifact_changed' USING ERRCODE='55000'; END IF;
 IF action_name='activate' THEN
  fallback:=package_model_observation.source(actor,(config->>'fallback_model_id')::uuid,(config->>'admission_id')::uuid);
  IF design.package_technical_digest(fallback->'document') IS DISTINCT FROM config->>'fallback_artifact_digest' THEN
   RAISE EXCEPTION 'package_internal_route_fallback_changed' USING ERRCODE='55000'; END IF;
 END IF;
 observation:=jsonb_build_object('version','package-internal-observation-request/1',
  'command_id',public.uuid_generate_v5((body->>'command_id')::uuid,'package-internal-route-observation/1'),
  'model_id',target,'admission_id',config->'admission_id','artifact_digest',design.package_technical_digest(snapshot->'document'),
  'method_digest',config->'observation_method_digest','reference',config->'reference');
 RETURN jsonb_build_object('schema','package-internal-route-preparation/1',
  'route_id',body->'route_id','revision',expected+1,'previous_model_id',previous,
  'selected_model_id',target,'action',action_name,'config',config,'source',snapshot,
  'fallback_at_activation',fallback,'observation_request',observation);
END $$;
CREATE FUNCTION package_model_route.commit_action(actor uuid,body jsonb,pinned text,prediction jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_model_route,pg_temp SET timezone='UTC' AS $$
DECLARE previous jsonb; packet jsonb; observation jsonb; target uuid; next_revision bigint;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 PERFORM pg_advisory_xact_lock(91143,1);
 previous:=package_model_route.replay(actor,body);
 IF previous IS NOT NULL THEN RETURN previous; END IF;
 packet:=package_model_route.prepare(actor,body);
 IF design.package_technical_digest(packet) IS DISTINCT FROM pinned THEN
  RAISE EXCEPTION 'package_internal_route_preparation_changed' USING ERRCODE='55000'; END IF;
 observation:=package_model_observation.record(actor,packet->'observation_request',design.package_technical_digest(packet->'source'),prediction);
 IF observation->>'result_digest' IS DISTINCT FROM design.package_technical_digest(prediction)
 OR observation->>'source_digest' IS DISTINCT FROM design.package_technical_digest(packet->'source') THEN
  RAISE EXCEPTION 'package_internal_route_observation_changed' USING ERRCODE='55000'; END IF;
 target:=(packet->>'selected_model_id')::uuid; next_revision:=(packet->>'revision')::bigint;
 IF body->>'action'='activate' THEN
  INSERT INTO package_model_route.routes VALUES((body->>'route_id')::uuid,actor,packet->'config',body->>'method_digest',next_revision,target,false,clock_timestamp());
 ELSE
  UPDATE package_model_route.routes SET revision=next_revision,current_model_id=target,
   rolled_back=rolled_back OR body->>'action'='rollback'
  WHERE id=(body->>'route_id')::uuid AND routes.revision=(body->>'expected_revision')::bigint;
  IF NOT FOUND THEN RAISE EXCEPTION 'package_internal_route_revision_conflict' USING ERRCODE='40001'; END IF;
 END IF;
 INSERT INTO package_model_route.events VALUES((body->>'command_id')::uuid,(body->>'route_id')::uuid,actor,next_revision,
  body->>'action',(packet->>'previous_model_id')::uuid,target,body,design.package_technical_digest(body),pinned,
  (observation->>'command_id')::uuid,observation->>'result_digest',clock_timestamp());
 RETURN package_model_route.replay(actor,body);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_model_route FROM PUBLIC;
GRANT USAGE ON SCHEMA package_model_route TO tender_api;
GRANT EXECUTE ON FUNCTION package_model_route.replay(uuid,jsonb),package_model_route.prepare(uuid,jsonb),package_model_route.commit_action(uuid,jsonb,text,jsonb) TO tender_api;
COMMIT;
