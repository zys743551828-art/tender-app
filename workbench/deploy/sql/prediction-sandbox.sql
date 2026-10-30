-- Optional test-only installation. Never add to business bootstrap or formal registry.
BEGIN;
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM package_historical_research.test_environments e WHERE e.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND e.database_name=current_database()) THEN
  RAISE EXCEPTION 'sandbox_registered_test_database_required' USING ERRCODE='55000'; END IF;
END $$;
CREATE SCHEMA prediction_sandbox;
REVOKE ALL ON SCHEMA prediction_sandbox FROM PUBLIC;
CREATE TABLE prediction_sandbox.environment(
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),id uuid NOT NULL UNIQUE,
 database_oid oid NOT NULL,database_name name NOT NULL,system_id text NOT NULL,postmaster timestamptz NOT NULL
);
INSERT INTO prediction_sandbox.environment SELECT true,gen_random_uuid(),oid,datname,(pg_control_system()).system_identifier::text,pg_postmaster_start_time() FROM pg_database WHERE datname=current_database();
CREATE TABLE prediction_sandbox.certificates(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,actor_id uuid NOT NULL REFERENCES design.members(id),bid_id uuid NOT NULL REFERENCES design.bids(id),scope_id uuid NOT NULL,
 environment_id uuid NOT NULL REFERENCES prediction_sandbox.environment(id),request jsonb NOT NULL,valid_until timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),CHECK(valid_until>created_at)
);
CREATE TABLE prediction_sandbox.revocations(certificate_id uuid PRIMARY KEY REFERENCES prediction_sandbox.certificates(id),command_id uuid NOT NULL UNIQUE,reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000));
CREATE TABLE prediction_sandbox.results(command_id uuid PRIMARY KEY,certificate_id uuid NOT NULL REFERENCES prediction_sandbox.certificates(id),operation_id uuid NOT NULL UNIQUE REFERENCES design.operations(id),result jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),CHECK(result->>'schema'='prediction-sandbox-result/1' AND result->'test_only'='true'::jsonb AND result->'production_eligible'='false'::jsonb));
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['environment','certificates','revocations','results'] LOOP EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON prediction_sandbox.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',t); END LOOP;END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA prediction_sandbox FROM PUBLIC,tender_api,tender_worker;
CREATE FUNCTION prediction_sandbox.operate(actor uuid,bid uuid,certificate uuid,action text,body jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp SET timezone='UTC' AS $$
DECLARE env prediction_sandbox.environment;c prediction_sandbox.certificates;r prediction_sandbox.results;old prediction_sandbox.revocations;active boolean;output jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF actor IS NULL OR bid IS NULL OR action IS NULL OR body IS NULL OR jsonb_typeof(body)<>'object' THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 IF action='issue' AND (NOT body ?& ARRAY['command_id','scope_id','source_ref','packet_digest','method_digest','valid_until'] OR body-ARRAY['command_id','scope_id','source_ref','packet_digest','method_digest','valid_until']<>'{}'::jsonb OR EXISTS(SELECT FROM jsonb_each(body) x WHERE jsonb_typeof(x.value)<>'string')) THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 IF action='publish' AND (NOT body ?& ARRAY['command_id','operation_id','result_ref','value','method_digest'] OR body-ARRAY['command_id','operation_id','result_ref','value','method_digest']<>'{}'::jsonb OR EXISTS(SELECT FROM jsonb_each(body) x WHERE jsonb_typeof(x.value)<>'string')) THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 IF action='revoke' AND (NOT body ?& ARRAY['command_id','reason'] OR body-ARRAY['command_id','reason']<>'{}'::jsonb OR EXISTS(SELECT FROM jsonb_each(body) x WHERE jsonb_typeof(x.value)<>'string')) THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 IF action='result' AND (NOT body ? 'command_id' OR body-ARRAY['command_id']<>'{}'::jsonb OR jsonb_typeof(body->'command_id')<>'string') THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 IF action='prepare' AND body<>'{}'::jsonb THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
 PERFORM pg_advisory_xact_lock(975031,1);
 SELECT * INTO env FROM prediction_sandbox.environment;
 IF env.database_name IS DISTINCT FROM current_database() OR env.database_oid IS DISTINCT FROM (SELECT oid FROM pg_database WHERE datname=current_database())
 OR env.system_id IS DISTINCT FROM (pg_control_system()).system_identifier::text OR env.postmaster IS DISTINCT FROM pg_postmaster_start_time()
 OR NOT EXISTS(SELECT FROM package_historical_research.test_environments e WHERE e.database_oid=env.database_oid AND e.database_name=env.database_name)
 THEN RAISE EXCEPTION 'sandbox_environment_changed' USING ERRCODE='55000';END IF;
 IF NOT EXISTS(SELECT FROM design.members m WHERE m.id=actor AND m.active) THEN RAISE EXCEPTION 'sandbox_actor_denied' USING ERRCODE='42501';END IF;
 IF action='issue' THEN
  SELECT * INTO c FROM prediction_sandbox.certificates WHERE command_id=(body->>'command_id')::uuid;
  IF FOUND THEN IF c.actor_id IS DISTINCT FROM actor OR c.bid_id IS DISTINCT FROM bid OR c.request IS DISTINCT FROM body THEN RAISE EXCEPTION 'sandbox_command_conflict' USING ERRCODE='55000';END IF;
  ELSE
   IF (body->>'valid_until')::timestamptz<=clock_timestamp() OR (body->>'valid_until')::timestamptz>clock_timestamp()+interval '1 day'
   OR body->>'source_ref' !~ '^[a-f0-9]{64}$' OR body->>'packet_digest' !~ '^[a-f0-9]{64}$' OR body->>'method_digest' !~ '^[a-f0-9]{64}$'
   THEN RAISE EXCEPTION 'sandbox_input_invalid' USING ERRCODE='22023';END IF;
   INSERT INTO prediction_sandbox.certificates VALUES(gen_random_uuid(),(body->>'command_id')::uuid,actor,bid,(body->>'scope_id')::uuid,env.id,body,(body->>'valid_until')::timestamptz,clock_timestamp()) RETURNING * INTO c;
  END IF;
 ELSE SELECT * INTO c FROM prediction_sandbox.certificates WHERE id=certificate; END IF;
 IF c.id IS NULL OR c.actor_id IS DISTINCT FROM actor OR c.bid_id IS DISTINCT FROM bid OR c.environment_id IS DISTINCT FROM env.id THEN RAISE EXCEPTION 'sandbox_certificate_denied' USING ERRCODE='42501';END IF;
 IF action='revoke' THEN
  SELECT * INTO old FROM prediction_sandbox.revocations WHERE certificate_id=c.id OR command_id=(body->>'command_id')::uuid;
  IF FOUND THEN IF old.certificate_id IS DISTINCT FROM c.id OR old.command_id IS DISTINCT FROM (body->>'command_id')::uuid OR old.reason IS DISTINCT FROM body->>'reason' THEN RAISE EXCEPTION 'sandbox_revoke_conflict' USING ERRCODE='55000'; END IF;
  ELSE INSERT INTO prediction_sandbox.revocations VALUES(c.id,(body->>'command_id')::uuid,body->>'reason');END IF;
 END IF;
 active:=clock_timestamp()<c.valid_until AND NOT EXISTS(SELECT FROM prediction_sandbox.revocations WHERE certificate_id=c.id);
 IF action='publish' THEN
  IF NOT active OR body->>'method_digest' IS DISTINCT FROM c.request->>'method_digest' THEN RAISE EXCEPTION 'sandbox_certificate_invalid' USING ERRCODE='55000';END IF;
  IF NOT EXISTS(SELECT FROM design.operations o JOIN design.step_receipts s ON s.operation_id=o.id JOIN design.effect_receipts e ON e.operation_id=o.id AND e.effect_key=s.step_key
   JOIN design.audit_entries a ON a.event_type='package.prediction.task_accepted' AND a.payload->>'request_id'=body->>'command_id'
   WHERE o.id=(body->>'operation_id')::uuid AND o.id=(a.payload->>'operation_id')::uuid AND o.bid_id=bid AND o.state='succeeded' AND o.handler_version='package-prediction/1'
   AND s.step_key='compute-package-prediction' AND s.state='succeeded' AND s.lease_until IS NULL
   AND a.payload#>>'{body,certificate}'=c.id::text AND a.payload#>>'{body,actor}'=actor::text AND a.payload#>>'{body,scope}'=c.scope_id::text
   AND e.result->>'result_ref'=body->>'result_ref' AND e.result->>'input_ref'=a.payload->>'input_ref') THEN RAISE EXCEPTION 'sandbox_completed_task_required' USING ERRCODE='55000';END IF;
  output:=jsonb_build_object('schema','prediction-sandbox-result/1','test_only',true,'production_eligible',false,'value',body->>'value','result_ref',body->>'result_ref','certificate_id',c.id,'environment_id',env.id);
  IF (body->>'value')::numeric NOT BETWEEN 0 AND 100 OR body->>'value' IN('NaN','Infinity','-Infinity') THEN RAISE EXCEPTION 'sandbox_value_invalid' USING ERRCODE='22023';END IF;
  SELECT * INTO r FROM prediction_sandbox.results WHERE command_id=(body->>'command_id')::uuid;
  IF FOUND THEN IF r.certificate_id IS DISTINCT FROM c.id OR r.operation_id IS DISTINCT FROM (body->>'operation_id')::uuid OR r.result IS DISTINCT FROM output THEN RAISE EXCEPTION 'sandbox_result_conflict' USING ERRCODE='55000';END IF;
  ELSE INSERT INTO prediction_sandbox.results VALUES((body->>'command_id')::uuid,c.id,(body->>'operation_id')::uuid,output,clock_timestamp());END IF;
 ELSIF action='result' THEN
  SELECT * INTO r FROM prediction_sandbox.results WHERE command_id=(body->>'command_id')::uuid AND certificate_id=c.id;
  output:=r.result;
 END IF;
 IF action NOT IN('issue','prepare','revoke','publish','result') THEN RAISE EXCEPTION 'sandbox_action_invalid' USING ERRCODE='22023';END IF;
 RETURN jsonb_build_object('schema','prediction-sandbox-certificate/1','test_only',true,'production_eligible',false,'id',c.id,'scope_id',c.scope_id,'actor_id',actor,'bid_id',bid,'environment_id',env.id,'request',c.request,'state',CASE WHEN active THEN 'active' ELSE 'invalid' END,'result',CASE WHEN active THEN output ELSE NULL END);
END $$;
REVOKE ALL ON FUNCTION prediction_sandbox.operate(uuid,uuid,uuid,text,jsonb) FROM PUBLIC;
GRANT USAGE ON SCHEMA prediction_sandbox TO tender_api;
GRANT EXECUTE ON FUNCTION prediction_sandbox.operate(uuid,uuid,uuid,text,jsonb) TO tender_api;
COMMIT;
