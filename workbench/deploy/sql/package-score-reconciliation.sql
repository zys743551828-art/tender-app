-- Dedicated reconciliation increment /1, NEW disposable mechanism DB only.
-- Install after package-score-execution.sql. No public/formal permission is added.
-- A purpose worker/API cannot upload a receipt or call this independent role.
BEGIN;
CREATE ROLE tender_package_score_test_reconciler NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA package_score_execution TO tender_package_score_test_reconciler;

CREATE TABLE package_score_execution.reconciliation_receipts(
 id uuid PRIMARY KEY,
 database_oid oid NOT NULL REFERENCES package_score_execution.test_environments(database_oid),
 call_id uuid NOT NULL REFERENCES score_execution.calls(id),
 expected_call_digest design.sha256 NOT NULL,
 origin text NOT NULL CHECK(origin='synthetic'),
 resolution text NOT NULL CHECK(resolution IN('succeeded','not_sent')),
 provider_record text NOT NULL,provider_record_digest design.sha256 NOT NULL,
 raw_response text,raw_response_digest design.sha256,
 observed_at timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 valid_until timestamptz NOT NULL,
 CHECK(octet_length(provider_record) BETWEEN 1 AND 2097152 AND jsonb_typeof(provider_record::jsonb)='object'),
 CHECK(encode(sha256(convert_to(provider_record,'UTF8')),'hex')=provider_record_digest::text),
 CHECK((resolution='succeeded' AND raw_response IS NOT NULL AND raw_response_digest IS NOT NULL
   AND octet_length(raw_response) BETWEEN 1 AND 2097152 AND jsonb_typeof(raw_response::jsonb)='object'
   AND encode(sha256(convert_to(raw_response,'UTF8')),'hex')=raw_response_digest::text)
  OR (resolution='not_sent' AND raw_response IS NULL AND raw_response_digest IS NULL)),
 CHECK(observed_at<=created_at AND valid_until>created_at AND valid_until<=created_at+interval '8 hours')
);
CREATE TABLE package_score_execution.reconciliations(
 id uuid PRIMARY KEY,
 receipt_id uuid NOT NULL UNIQUE REFERENCES package_score_execution.reconciliation_receipts(id),
 call_id uuid NOT NULL UNIQUE REFERENCES score_execution.calls(id),
 command_key uuid NOT NULL UNIQUE,request_digest design.sha256 NOT NULL,
 requested_by name NOT NULL,reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 previous_call jsonb NOT NULL,settled_call jsonb NOT NULL,
 receipt_digest design.sha256 NOT NULL,result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(previous_call->>'state' IN('reserved','unknown')),
 CHECK(settled_call->>'state' IN('succeeded','not_sent')),
 CHECK(result->>'execution_mode'='mechanism_test'),
 CHECK(result->'formal_scoring_eligible'='false'::jsonb AND result->'training_eligible'='false'::jsonb AND result->'metrics_eligible'='false'::jsonb),
 CHECK(result->'provider_requests'='0'::jsonb AND result->'paid_calls'='0'::jsonb)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_score_execution.reconciliation_receipts FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_score_execution.reconciliations FOR EACH ROW EXECUTE FUNCTION design.append_only();
REVOKE ALL ON package_score_execution.reconciliation_receipts,package_score_execution.reconciliations
 FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_model_score,tender_package_score_test_api,tender_package_score_test_worker,tender_package_score_test_reconciler;

CREATE FUNCTION package_score_execution.isolated_reconciler() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,package_score_execution AS $$
 SELECT EXISTS(SELECT FROM package_score_execution.test_environments e JOIN pg_database d ON d.oid=e.database_oid
  WHERE d.datname=current_database() AND e.database_name=d.datname
   AND d.datname ~ '^fusion_package_score_mechanism_[a-z0-9]{8}$')
 AND pg_has_role(session_user,'tender_package_score_test_reconciler','MEMBER')
 AND NOT (pg_has_role(session_user,'tender_api','MEMBER') OR pg_has_role(session_user,'tender_worker','MEMBER')
  OR pg_has_role(session_user,'tender_research_worker','MEMBER') OR pg_has_role(session_user,'tender_model_score','MEMBER')
  OR pg_has_role(session_user,'tender_package_score_test_api','MEMBER') OR pg_has_role(session_user,'tender_package_score_test_worker','MEMBER'))
 AND NOT has_schema_privilege(session_user,'design','USAGE')
 AND NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication))
$$;

CREATE FUNCTION package_score_execution.reconcile_call(target_receipt uuid,operation_key uuid,reason_text text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_score_execution,score_execution,design,pg_temp AS $$
DECLARE proof package_score_execution.reconciliation_receipts;
 previous package_score_execution.reconciliations; call score_execution.calls; job score_execution.jobs; input score_execution.inputs;
 record jsonb; raw jsonb; before_call jsonb; after_call jsonb; request_sha design.sha256; proof_sha design.sha256;
 calculated numeric; identity uuid:=gen_random_uuid(); response jsonb; at timestamptz;
BEGIN
 IF NOT package_score_execution.isolated_reconciler() THEN RAISE EXCEPTION 'package_score_reconciler_required' USING ERRCODE='42501'; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'fresh_read_committed_required' USING ERRCODE='55000'; END IF;
 IF target_receipt IS NULL OR operation_key IS NULL OR reason_text IS NULL OR length(btrim(reason_text)) NOT BETWEEN 1 AND 4000 THEN
  RAISE EXCEPTION 'package_score_reconciliation_command_invalid' USING ERRCODE='22023'; END IF;
 request_sha:=design.package_technical_digest(jsonb_build_object('receipt_id',target_receipt,'reason',reason_text));
 -- Serializes exact command replay across unrelated calls. No other subsystem
 -- takes this namespace; the established governance->bid->job order follows.
 PERFORM pg_advisory_xact_lock(91502,hashtext(operation_key::text));
 SELECT * INTO previous FROM package_score_execution.reconciliations WHERE command_key=operation_key;
 IF FOUND THEN
  IF previous.requested_by IS DISTINCT FROM session_user OR previous.request_digest IS DISTINCT FROM request_sha THEN
   RAISE EXCEPTION 'package_score_reconciliation_key_conflict' USING ERRCODE='23505'; END IF;
  RETURN previous.result;
 END IF;
 SELECT p.* INTO proof FROM package_score_execution.reconciliation_receipts p JOIN pg_database d ON d.oid=p.database_oid
  WHERE p.id=target_receipt AND d.datname=current_database();
 IF NOT FOUND THEN RAISE EXCEPTION 'package_score_reconciliation_receipt_missing' USING ERRCODE='P0002'; END IF;
 SELECT * INTO call FROM score_execution.calls WHERE id=proof.call_id;
 SELECT * INTO job FROM score_execution.jobs WHERE id=call.job_id;
 input:=score_execution.lock_input(job.input_id);
 IF input.package_scope_id IS NULL OR input.origin<>'synthetic' OR input.method_digest::text<>package_score_execution.method_digest() THEN
  RAISE EXCEPTION 'package_score_reconciliation_subject_invalid' USING ERRCODE='23514'; END IF;
 SELECT * INTO job FROM score_execution.jobs WHERE id=call.job_id FOR UPDATE;
 SELECT c.* INTO call FROM score_execution.calls c WHERE c.id=proof.call_id FOR UPDATE;
 at:=clock_timestamp();before_call:=to_jsonb(call);
 IF EXISTS(SELECT FROM package_score_execution.reconciliations WHERE call_id=call.id)
  OR call.state NOT IN('unknown','reserved') OR job.state NOT IN('running','paused','cancelled','failed')
  OR proof.valid_until<=at OR proof.created_at>at OR proof.observed_at<call.created_at THEN
  RAISE EXCEPTION 'package_score_reconciliation_not_available' USING ERRCODE='55000'; END IF;
 IF call.state='reserved' AND job.state='running' AND job.lease_until>at THEN
  RAISE EXCEPTION 'package_score_reconciliation_active_lease' USING ERRCODE='55000'; END IF;
 IF proof.expected_call_digest::text IS DISTINCT FROM design.package_technical_digest(before_call) THEN
  RAISE EXCEPTION 'package_score_reconciliation_call_changed' USING ERRCODE='23514'; END IF;
 record:=proof.provider_record::jsonb;
 IF NOT score_execution.exact_keys(record,ARRAY['schema','origin','provider','model','request_digest','profile_digest','provider_receipt_id','observed_state','response_digest'])
  OR record->>'schema' IS DISTINCT FROM 'isolated-package-score-provider-receipt/1'
  OR record->>'origin' IS DISTINCT FROM 'synthetic' OR record->>'provider' IS DISTINCT FROM 'deepseek'
  OR record->>'model' IS DISTINCT FROM 'deepseek-flash'
  OR record->>'request_digest' IS DISTINCT FROM call.request_digest::text
  OR record->>'profile_digest' IS DISTINCT FROM call.profile_digest::text
  OR jsonb_typeof(record->'provider_receipt_id') IS DISTINCT FROM 'string'
  OR length(btrim(record->>'provider_receipt_id')) NOT BETWEEN 1 AND 1000
  OR record->>'observed_state' IS DISTINCT FROM proof.resolution
  OR record->>'response_digest' IS DISTINCT FROM proof.raw_response_digest::text THEN
  RAISE EXCEPTION 'package_score_provider_receipt_mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT FROM package_score_execution.reconciliations r
   JOIN package_score_execution.reconciliation_receipts p ON p.id=r.receipt_id
   WHERE p.provider_record::jsonb->>'provider_receipt_id'=record->>'provider_receipt_id') THEN
  RAISE EXCEPTION 'package_score_provider_receipt_reused' USING ERRCODE='23514'; END IF;
 IF proof.resolution='succeeded' THEN
  raw:=proof.raw_response::jsonb;
  IF jsonb_typeof(raw->'response_id') IS DISTINCT FROM 'string' OR coalesce(length(btrim(raw->>'response_id')),0)=0 THEN
   RAISE EXCEPTION 'package_score_delayed_response_identity_missing' USING ERRCODE='23514'; END IF;
  calculated:=((raw#>>'{usage,prompt_tokens}')::numeric*(input.price_config->>'input_per_million')::numeric
    +(raw#>>'{usage,completion_tokens}')::numeric*(input.price_config->>'output_per_million')::numeric)/1000000;
 ELSE calculated:=0;
 END IF;
 -- The prior unknown/reserved row is preserved verbatim below. The temporary
 -- reserved state is transaction-local and lets the unchanged settlement RPC
 -- validate the exact response, model, usage and frozen prices before release.
 -- Any failure, including audit failure, rolls this and every fee change back.
 IF call.state='unknown' THEN UPDATE score_execution.calls SET state='reserved' WHERE id=call.id; END IF;
 PERFORM score_execution.settle_call(call.id,call.owner_token,proof.resolution,proof.raw_response,calculated);
 UPDATE score_execution.jobs SET state=CASE WHEN state IN('cancelled','failed') THEN state ELSE 'paused' END,
  generation=generation+1,owner_token=NULL,lease_until=NULL WHERE id=job.id RETURNING * INTO job;
 SELECT to_jsonb(c) INTO after_call FROM score_execution.calls c WHERE c.id=call.id;
 proof_sha:=design.package_technical_digest(to_jsonb(proof));
 response:=jsonb_build_object('schema','package-score-reconciliation/1','reconciliation_id',identity,
  'receipt_id',proof.id,'call_id',call.id,'job_id',job.id,'previous_state',before_call->>'state','state',proof.resolution,
  'generation',job.generation,'reserved_fee_after',job.reserved_fee::text,'estimated_fee_after',job.estimated_fee::text,
  'original_call_digest',proof.expected_call_digest,'settled_call_digest',design.package_technical_digest(after_call),
  'receipt_digest',proof_sha,'provider_record_digest',proof.provider_record_digest,
  'execution_mode','mechanism_test','formal_scoring_eligible',false,'training_eligible',false,'metrics_eligible',false,
  'provider_requests',0,'paid_calls',0);
 INSERT INTO package_score_execution.reconciliations(id,receipt_id,call_id,command_key,request_digest,requested_by,reason,previous_call,settled_call,receipt_digest,result)
  VALUES(identity,proof.id,call.id,operation_key,request_sha,session_user,reason_text,before_call,after_call,proof_sha,response);
 INSERT INTO design.audit_entries(id,bid_id,event_type,payload)
  VALUES(gen_random_uuid(),input.bid_id,'package_score.call_reconciled',jsonb_build_object(
   'reconciliation_id',identity,'command_key',operation_key,'service_principal',session_user,
   'receipt_id',proof.id,'call_id',call.id,'job_id',job.id,'previous_state',before_call->>'state',
   'state',proof.resolution,'original_call_digest',proof.expected_call_digest,'receipt_digest',proof_sha,
   'execution_mode','mechanism_test','reason',reason_text));
 RETURN response;
END $$;
REVOKE ALL ON FUNCTION package_score_execution.isolated_reconciler(),package_score_execution.reconcile_call(uuid,uuid,text)
 FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_model_score,tender_package_score_test_api,tender_package_score_test_worker,tender_package_score_test_reconciler;
GRANT EXECUTE ON FUNCTION package_score_execution.reconcile_call(uuid,uuid,text) TO tender_package_score_test_reconciler;
COMMIT;
