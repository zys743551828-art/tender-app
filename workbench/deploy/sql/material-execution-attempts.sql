-- Optional isolated mechanism lane. No live provider/account qualification is granted.
BEGIN;
CREATE SCHEMA material_execution;
REVOKE ALL ON SCHEMA material_execution FROM PUBLIC;
CREATE ROLE tender_material_execution_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_execution.accounts(
 id uuid PRIMARY KEY,currency text NOT NULL CHECK(currency IN('USD','CNY')),
 limit_minor bigint NOT NULL CHECK(limit_minor BETWEEN 0 AND 9007199254740991),
 origin text NOT NULL CHECK(origin='synthetic_mechanism')
);
CREATE TABLE material_execution.balances(
 account_id uuid PRIMARY KEY REFERENCES material_execution.accounts(id),
 held_minor bigint NOT NULL CHECK(held_minor BETWEEN 0 AND 9007199254740991),
 estimated_minor bigint NOT NULL CHECK(estimated_minor BETWEEN 0 AND 9007199254740991)
);
CREATE TABLE material_execution.profiles(
 id uuid PRIMARY KEY,worker_login name NOT NULL,worker_login_oid oid NOT NULL,
 preparation_profile_id uuid NOT NULL REFERENCES material_preparation.profiles(id),preparation_profile_digest design.sha256 NOT NULL,
 account_id uuid NOT NULL REFERENCES material_execution.accounts(id),origin text NOT NULL CHECK(origin='synthetic_mechanism'),
 execution_method_digest design.sha256 NOT NULL,execution_sql_method_digest design.sha256 NOT NULL,
 preflight_method_digest design.sha256 NOT NULL,serializer_digest design.sha256 NOT NULL,
 provider_profile_digest design.sha256 NOT NULL,judgment_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL CHECK(database_name ~ '^fusion_[a-z0-9_]+$'),
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until AND valid_until<=valid_from+interval '24 hours')
);
CREATE TABLE material_execution.profile_heads(
 worker_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_execution.profiles(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_execution.reservations(
 job_id uuid PRIMARY KEY REFERENCES material_judgment_job.jobs(id),profile_id uuid NOT NULL REFERENCES material_execution.profiles(id),
 account_id uuid NOT NULL REFERENCES material_execution.accounts(id),request_set_digest design.sha256 NOT NULL,
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384)
);
CREATE TABLE material_execution.job_balances(
 job_id uuid PRIMARY KEY REFERENCES material_execution.reservations(job_id),
 held_minor bigint NOT NULL CHECK(held_minor BETWEEN 0 AND 9007199254740991),
 estimated_minor bigint NOT NULL CHECK(estimated_minor BETWEEN 0 AND 9007199254740991),
 released_minor bigint NOT NULL CHECK(released_minor BETWEEN 0 AND 9007199254740991),
 state text NOT NULL CHECK(state IN('ready','in_flight','unknown','paused_invalid','paused_stale','paused_overrun','completed'))
);
CREATE TABLE material_execution.attempts(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,job_id uuid NOT NULL REFERENCES material_execution.reservations(job_id),
 slot_id uuid NOT NULL UNIQUE REFERENCES material_judgment_job.slots(id),actor name NOT NULL,actor_oid oid NOT NULL,
 lease_id uuid NOT NULL REFERENCES material_preparation.leases(id),profile_id uuid NOT NULL REFERENCES material_execution.profiles(id),
 send_token uuid NOT NULL UNIQUE,preflight jsonb NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(preflight::text)<=1048576),CHECK(octet_length(document::text)<=32768)
);
CREATE TABLE material_execution.outcomes(
 attempt_id uuid PRIMARY KEY REFERENCES material_execution.attempts(id),command_id uuid NOT NULL UNIQUE,
 submitted_digest design.sha256 NOT NULL,raw_response bytea NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(raw_response)<=1048576),CHECK(octet_length(document::text)<=16384)
);
CREATE TRIGGER immutable_execution_account BEFORE UPDATE OR DELETE ON material_execution.accounts FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_execution_profile BEFORE UPDATE OR DELETE ON material_execution.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_execution_reservation BEFORE UPDATE OR DELETE ON material_execution.reservations FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_execution_attempt BEFORE UPDATE OR DELETE ON material_execution.attempts FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_execution_outcome BEFORE UPDATE OR DELETE ON material_execution.outcomes FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_execution.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
 'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_execution.native_method_digest()','material_execution.require_worker(boolean)',
 'material_execution.current_context(jsonb,uuid)','material_execution.observation(uuid,boolean)','material_execution.judgment_valid(uuid,jsonb,text)',
 'material_execution.begin_attempt(jsonb,uuid,text,uuid,uuid,uuid)','material_execution.settle(uuid,uuid,jsonb,bytea,uuid)',
 'material_execution.read(uuid)','material_execution.response(uuid,text)']) s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>9 THEN RETURN NULL;END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$execution_method$;

CREATE FUNCTION material_execution.require_worker(write_required boolean)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_worker$
BEGIN
 IF (write_required AND (current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off'))
  OR (NOT write_required AND (current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on')) THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_execution_worker',ARRAY['material_execution.begin_attempt(jsonb,uuid,text,uuid,uuid,uuid)','material_execution.settle(uuid,uuid,jsonb,bytea,uuid)','material_execution.read(uuid)','material_execution.response(uuid,text)']) THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
END;
$execution_worker$;

CREATE FUNCTION material_execution.current_context(checked jsonb,target_profile uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_context$
DECLARE p material_execution.profiles;h material_execution.profile_heads;pp material_preparation.profiles;ph material_preparation.profile_heads;
 l material_preparation.leases;s material_preparation.states;job material_judgment_job.jobs;storage technical_material_store.records;
 ctx jsonb;q jsonb;r jsonb;rule_ids jsonb;images jsonb;key text;bytes_total bigint:=0;at timestamptz;current_ok boolean;
BEGIN
 IF NOT design.package_json_keys(checked,ARRAY['version','method_digest','serializer_digest','preparation_method_digest','lease_id','lease_digest','job_id','job_digest','quote_digest',
  'generation','fence','evidence_revision','input_digest','context_digest','asset_set_digest','requests','rule_count','required_valid_slots','request_bytes_per_round',
  'checked_at','lease_until_at_check','all_included_rules_serialized','complete_owned_images_matched','digest','fee_ledger_reserved','send_lease_granted',
  'execution_authorized','model_token_limit_verified','account_prices_verified','visual_readability_verified','atomic_snapshot_verified','formal_prediction_eligible'])
  OR checked->>'version' IS DISTINCT FROM 'material-request-preflight/1'
  OR checked->>'digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(checked-'digest'),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
 FOREACH key IN ARRAY ARRAY['fee_ledger_reserved','send_lease_granted','execution_authorized','model_token_limit_verified','account_prices_verified','visual_readability_verified','atomic_snapshot_verified','formal_prediction_eligible'] LOOP
  IF checked->key IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
 END LOOP;
 SELECT * INTO p FROM material_execution.profiles WHERE id=target_profile;
 SELECT * INTO h FROM material_execution.profile_heads WHERE worker_login=p.worker_login;
 SELECT * INTO pp FROM material_preparation.profiles WHERE id=p.preparation_profile_id;
 SELECT * INTO ph FROM material_preparation.profile_heads WHERE worker_login=pp.worker_login;
 SELECT * INTO l FROM material_preparation.leases WHERE id=(checked->>'lease_id')::uuid AND digest=checked->>'lease_digest';
 SELECT * INTO s FROM material_preparation.states WHERE job_id=l.job_id;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=l.job_id;
 IF p.id IS NULL OR l.id IS NULL OR pp.id IS NULL OR job.id IS NULL THEN RETURN NULL;END IF;
 ctx:=material_preparation.current_context(job.id,pp.id);at:=clock_timestamp();
 q:=ctx#>'{job_context,renewal_context,quote,document}';
 -- current_context's preparation profile flag belongs to its original LOGIN.
 -- Validate that owner separately; never borrow a session-dependent true flag.
 current_ok:=coalesce(p.worker_login=session_user AND p.worker_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND p.worker_login<>pp.worker_login AND p.worker_login_oid<>pp.worker_login_oid
  AND h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.execution_sql_method_digest::text=material_execution.native_method_digest()
  AND p.origin='synthetic_mechanism' AND pp.origin=p.origin AND job.document->>'origin'=p.origin
  AND p.preparation_profile_digest::text=ctx->>'profile_digest'
  AND ph.profile_id=pp.id AND ph.enabled AND ph.revision=l.profile_head_revision
  AND at>=pp.valid_from AND at<pp.valid_until AND pp.database_name=current_database()
  AND pp.database_oid=p.database_oid AND pp.preparation_sql_method_digest::text=material_preparation.native_method_digest()
  AND pp.job_profile_id=job.profile_id AND pp.job_profile_digest::text=ctx#>>'{job_context,profile_digest}'
  AND l.profile_id=pp.id AND l.actor=pp.worker_login AND l.actor_oid=pp.worker_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=pp.worker_login_oid AND rolname=pp.worker_login AND rolcanlogin)
  AND scope_review_issuer.role_policy(pp.worker_login,'tender_material_preparation_worker',ARRAY['material_preparation.claim(uuid,text,uuid,text,uuid)','material_preparation.heartbeat(uuid,text,uuid)','material_preparation.inspect(uuid,text)','material_preparation.owned_context(uuid,text)','material_preparation.owned_asset(uuid,text,text)','material_preparation.owned_assets(uuid,text)'])
  AND l.document->>'profile_digest'=ctx->>'profile_digest'
  AND l.document->>'preparation_method_digest'=pp.preparation_method_digest::text
  AND l.document->>'native_sql_method_digest'=material_preparation.native_method_digest()
  AND l.digest::text=encode(sha256(convert_to(design.package_canonical_json(l.document),'UTF8')),'hex')
  AND s.lease_id=l.id AND s.generation=l.generation AND s.fence=l.fence AND at<s.lease_until
  AND ctx->'job_current'='true'::jsonb
  AND checked->>'method_digest'=p.preflight_method_digest::text
  AND checked->>'serializer_digest'=p.serializer_digest::text AND checked->>'preparation_method_digest'=pp.preparation_method_digest::text
  AND checked->>'job_id'=job.id::text AND checked->>'job_digest'=job.digest::text
  AND checked->>'quote_digest'=job.document->>'quote_digest' AND checked->>'input_digest'=job.document->>'material_input_digest'
  AND checked->>'context_digest'=job.document->>'context_digest'
  AND checked->'generation'=to_jsonb(l.generation) AND checked->'fence'=to_jsonb(l.fence)
  AND checked->'evidence_revision'=ctx#>'{evidence,document,revision}'
  AND p.serializer_digest::text=q->>'serializer_digest' AND p.provider_profile_digest::text=q->>'provider_profile_digest'
  AND p.judgment_method_digest::text=q->>'judgment_method_digest',false);
 IF NOT current_ok THEN RETURN NULL;END IF;
 IF checked->'all_included_rules_serialized' IS DISTINCT FROM 'true'::jsonb OR checked->'complete_owned_images_matched' IS DISTINCT FROM 'true'::jsonb
  OR jsonb_typeof(checked->'requests') IS DISTINCT FROM 'array' OR jsonb_array_length(checked->'requests') NOT BETWEEN 1 AND 400
  OR checked->'rule_count' IS DISTINCT FROM to_jsonb(jsonb_array_length(checked->'requests'))
  OR checked->'required_valid_slots' IS DISTINCT FROM job.document->'required_valid_slots' THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
 SELECT jsonb_agg(value->'rule_id' ORDER BY ordinal) INTO rule_ids FROM jsonb_array_elements(checked->'requests') WITH ORDINALITY r(value,ordinal);
 IF rule_ids IS DISTINCT FROM job.document->'rule_ids' THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
 FOR r IN SELECT value FROM jsonb_array_elements(checked->'requests') LOOP
  IF NOT design.package_json_keys(r,ARRAY['version','input_digest','context_digest','serializer_digest','profile_digest','judgment_method_digest','semantic_input_digest','request_digest','rule_id','body_byte_count','image_count','complete_native_material_serialized','native_binding_verified','model_token_limit_verified','visual_readability_verified','execution_authorized'])
   OR r->>'version' IS DISTINCT FROM 'package-technical-complete-vision-request/3'
   OR r->>'input_digest' IS DISTINCT FROM checked->>'input_digest' OR r->>'context_digest' IS DISTINCT FROM checked->>'context_digest'
   OR r->>'serializer_digest' IS DISTINCT FROM p.serializer_digest::text OR r->>'profile_digest' IS DISTINCT FROM p.provider_profile_digest::text
   OR r->>'judgment_method_digest' IS DISTINCT FROM p.judgment_method_digest::text
   OR coalesce(r->>'semantic_input_digest','') !~ '^[0-9a-f]{64}$' OR coalesce(r->>'request_digest','') !~ '^[0-9a-f]{64}$'
   OR r->'complete_native_material_serialized' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
  FOREACH key IN ARRAY ARRAY['native_binding_verified','model_token_limit_verified','visual_readability_verified','execution_authorized'] LOOP
   IF r->key IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
  END LOOP;
  FOREACH key IN ARRAY ARRAY['body_byte_count','image_count'] LOOP
   IF jsonb_typeof(r->key) IS DISTINCT FROM 'number' OR coalesce(r->>key,'') !~ '^[1-9][0-9]{0,8}$' THEN
    RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
  END LOOP;
  IF (r->>'body_byte_count')::bigint>50331648 OR (r->>'image_count')::bigint>384 THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
  bytes_total:=bytes_total+(r->>'body_byte_count')::bigint;
 END LOOP;
 SELECT * INTO storage FROM technical_material_store.records WHERE id=(ctx#>>'{job_context,renewal_context,seal,document,storage_record_id}')::uuid;
 SELECT jsonb_agg(sha ORDER BY sha COLLATE "C") INTO images FROM (SELECT DISTINCT value->>'sha256' sha FROM jsonb_array_elements(storage.document#>'{packet,image_objects}')) image_set;
 IF checked->'request_bytes_per_round' IS DISTINCT FROM to_jsonb(bytes_total)
  OR checked->>'asset_set_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(images),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_PREFLIGHT_INVALID' USING ERRCODE='P0001';END IF;
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'profile_head_revision',h.revision,'job',job.document,'quote',q,'send_until',least(s.lease_until,p.valid_until,pp.valid_until));
END;
$execution_context$;

CREATE FUNCTION material_execution.observation(target uuid,new_send boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_observation$
DECLARE a material_execution.attempts;o material_execution.outcomes;j material_execution.job_balances;r material_execution.reservations;b material_execution.balances;
BEGIN
 SELECT * INTO a FROM material_execution.attempts WHERE id=target AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO o FROM material_execution.outcomes WHERE attempt_id=a.id;
 SELECT * INTO r FROM material_execution.reservations WHERE job_id=a.job_id;
 SELECT * INTO j FROM material_execution.job_balances WHERE job_id=a.job_id;
 SELECT * INTO b FROM material_execution.balances WHERE account_id=r.account_id;
 RETURN jsonb_build_object('attempt',jsonb_build_object('document',a.document,'digest',a.digest::text),
  'outcome',CASE WHEN o.attempt_id IS NULL THEN NULL ELSE jsonb_build_object('document',o.document,'digest',o.digest::text) END,
  'reservation',jsonb_build_object('document',r.document,'digest',r.digest::text),'job_balance',to_jsonb(j),'account_balance',to_jsonb(b),'new_send',new_send);
END;
$execution_observation$;

CREATE FUNCTION material_execution.begin_attempt(checked jsonb,target_profile uuid,expected_profile_digest text,target_slot uuid,expected_rule uuid,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_begin$
DECLARE p material_execution.profiles;job material_judgment_job.jobs;slot material_judgment_job.slots;
 old material_execution.attempts;reservation material_execution.reservations;wallet material_execution.accounts;balance material_execution.balances;
 ctx jsonb;request jsonb;result jsonb;res jsonb;checksum text;request_set text;required bigint;per_call bigint;identifier uuid;token uuid;at timestamptz;
BEGIN
 PERFORM material_execution.require_worker(true);
 IF target_profile IS NULL OR target_slot IS NULL OR command IS NULL OR expected_profile_digest IS NULL THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=(checked->>'job_id')::uuid AND digest=checked->>'job_digest';
 SELECT * INTO slot FROM material_judgment_job.slots WHERE id=target_slot AND job_id=job.id AND rule_id=expected_rule;
 SELECT * INTO p FROM material_execution.profiles WHERE id=target_profile;
 IF job.id IS NULL OR slot.id IS NULL OR p.id IS NULL THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_execution:'||job.id::text,0));
 SELECT * INTO old FROM material_execution.attempts WHERE command_id=command OR slot_id=target_slot ORDER BY command_id=command DESC LIMIT 1;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.job_id<>job.id OR old.slot_id<>target_slot
   OR old.profile_id<>p.id OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest
   OR old.preflight->'requests' IS DISTINCT FROM checked->'requests' THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  -- Lost acknowledgments, a new command, and even a new lease cannot resend a slot.
  RETURN material_execution.observation(old.id,false);
 END IF;
 IF EXISTS(SELECT FROM material_execution.outcomes WHERE command_id=command) THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
 PERFORM 1 FROM material_execution.profile_heads WHERE worker_login=p.worker_login FOR SHARE;
 PERFORM material_preparation.lock_inputs(job.id,p.preparation_profile_id);
 PERFORM 1 FROM material_preparation.states WHERE job_id=job.id FOR UPDATE;
 ctx:=material_execution.current_context(checked,p.id);
 IF ctx IS NULL THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 IF ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 SELECT value INTO request FROM jsonb_array_elements(checked->'requests') WHERE value->>'rule_id'=slot.rule_id::text;
 required:=(ctx#>>'{quote,quote,required_reservation_minor}')::bigint;per_call:=(ctx#>>'{quote,quote,per_call_ceiling_minor}')::bigint;
 IF required IS DISTINCT FROM (job.document->>'required_reservation_minor')::bigint OR request IS NULL THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 request_set:=encode(sha256(convert_to(design.package_canonical_json(checked->'requests'),'UTF8')),'hex');
 SELECT * INTO wallet FROM material_execution.accounts WHERE id=p.account_id;
 SELECT * INTO balance FROM material_execution.balances WHERE account_id=wallet.id FOR UPDATE;
 IF wallet.currency IS DISTINCT FROM job.document->>'currency' OR balance.account_id IS NULL THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_ACCOUNT_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 SELECT * INTO reservation FROM material_execution.reservations WHERE job_id=job.id;
 at:=clock_timestamp();
 IF reservation.job_id IS NULL THEN
  IF balance.held_minor::numeric+balance.estimated_minor::numeric+required>wallet.limit_minor THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_BUDGET_INSUFFICIENT' USING ERRCODE='P0001';END IF;
  res:=jsonb_build_object('version','material-execution-reservation/1','job_id',job.id::text,'job_digest',job.digest::text,'profile_id',p.id::text,'account_id',wallet.id::text,
   'quote_digest',job.document->>'quote_digest','request_set_digest',request_set,'currency',wallet.currency,'reserved_minor',required,'per_call_reserved_minor',per_call,
   'execution_mode','isolated_synthetic_mechanism','execution_method_digest',p.execution_method_digest::text,'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'mechanism_fee_ledger_reserved',true,'account_price_confirmed',false,'formal_prediction_eligible',false,'invoice_reconciled',false);
  checksum:=encode(sha256(convert_to(design.package_canonical_json(res),'UTF8')),'hex');
  INSERT INTO material_execution.reservations VALUES(job.id,p.id,wallet.id,request_set,res,checksum);
  INSERT INTO material_execution.job_balances VALUES(job.id,required,0,0,'ready');
  UPDATE material_execution.balances SET held_minor=held_minor+required WHERE account_id=wallet.id;
 ELSIF reservation.profile_id<>p.id OR reservation.account_id<>wallet.id OR reservation.request_set_digest::text<>request_set THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_RESERVATION_CONFLICT' USING ERRCODE='P0001';
 END IF;
 IF EXISTS(SELECT FROM material_execution.job_balances WHERE job_id=job.id AND (state<>'ready' OR held_minor<per_call)) THEN
  RAISE EXCEPTION 'MATERIAL_EXECUTION_JOB_BLOCKED' USING ERRCODE='P0001';END IF;
 IF balance.held_minor::numeric+balance.estimated_minor::numeric>wallet.limit_minor THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_BUDGET_INSUFFICIENT' USING ERRCODE='P0001';END IF;
 -- The final native check is after lock acquisition and before the durable send grant.
 ctx:=material_execution.current_context(checked,p.id);
 IF ctx IS NULL OR at>=(ctx->>'send_until')::timestamptz THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 identifier:=gen_random_uuid();token:=gen_random_uuid();
 result:=jsonb_build_object('version','material-execution-attempt/1','attempt_id',identifier::text,'command_id',command::text,'job_id',job.id::text,'slot_id',slot.id::text,
  'rule_id',slot.rule_id::text,'slot_number',slot.slot_number,'attempt_number',1,'profile_id',p.id::text,'profile_digest',expected_profile_digest,'profile_head_revision',ctx->'profile_head_revision',
  'lease_id',checked->>'lease_id','lease_digest',checked->>'lease_digest','generation',checked->'generation','fence',checked->'fence','preflight_digest',checked->>'digest',
  'send_token',token::text,'send_until',to_char((ctx->>'send_until')::timestamptz,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'request',request,
  'price_policy',ctx#>'{quote,price_policy}','reserved_call_minor',per_call,'currency',wallet.currency,'execution_method_digest',p.execution_method_digest::text,
  'native_sql_method_digest',material_execution.native_method_digest(),'execution_mode','isolated_synthetic_mechanism','recorded_by',session_user::text,
  'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'mechanism_send_once_granted',true,'execution_authorized',false,'account_price_confirmed',false,'model_context_fit_proven',false,'visual_readability_verified',false,
  'automatic_retry',false,'atomic_snapshot_verified',false,'formal_prediction_eligible',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_execution.attempts VALUES(identifier,command,job.id,slot.id,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),(checked->>'lease_id')::uuid,p.id,token,checked,result,checksum);
 UPDATE material_execution.job_balances SET state='in_flight' WHERE job_id=job.id;
 RETURN material_execution.observation(identifier,true);
END;
$execution_begin$;

CREATE FUNCTION material_execution.judgment_valid(target uuid,response jsonb,expected_judgment_digest text)
RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_judgment$
DECLARE a material_execution.attempts;content text;content_lexical json;data jsonb;context jsonb;rule jsonb;reference jsonb;reference_lexical json;native jsonb;region jsonb;key text;point json;raw bytea;object_sha text;
BEGIN
 SELECT * INTO a FROM material_execution.attempts WHERE id=target;
 IF a.id IS NULL OR jsonb_typeof(response->'choices') IS DISTINCT FROM 'array' OR jsonb_array_length(response->'choices')<>1
  OR response#>>'{choices,0,finish_reason}' IS DISTINCT FROM 'stop' OR response#>>'{choices,0,message,role}' IS DISTINCT FROM 'assistant'
  OR jsonb_typeof(response#>'{choices,0,message,content}') IS DISTINCT FROM 'string'
  OR coalesce(response#>'{choices,0,message,tool_calls}','null'::jsonb) NOT IN('null'::jsonb,'[]'::jsonb,'{}'::jsonb,'false'::jsonb,'0'::jsonb,'""'::jsonb) THEN RETURN false;END IF;
 content:=response#>>'{choices,0,message,content}';
 IF NOT (content IS JSON OBJECT WITH UNIQUE KEYS) THEN RETURN false;END IF;
 data:=content::jsonb;content_lexical:=content::json;
 IF design.package_json_keys(data,ARRAY['status','coverage','band_id','reason','covered_part_ids','dimensions','evidence']) IS DISTINCT FROM true
  OR data->>'status' IS DISTINCT FROM 'valid' OR data->>'coverage' IS DISTINCT FROM 'complete'
  OR jsonb_typeof(data->'reason') IS DISTINCT FROM 'string' OR length(data->>'reason') NOT BETWEEN 1 AND 12000
  OR jsonb_typeof(data->'covered_part_ids') IS DISTINCT FROM 'array' OR jsonb_array_length(data->'covered_part_ids')>2000
  OR jsonb_typeof(data->'evidence') IS DISTINCT FROM 'array' OR jsonb_array_length(data->'evidence') NOT BETWEEN 1 AND 2000
  OR design.package_json_keys(data->'dimensions',ARRAY['specificity','validity','consistency']) IS DISTINCT FROM true
  OR expected_judgment_digest IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(data),'UTF8')),'hex') THEN RETURN false;END IF;
 FOREACH key IN ARRAY ARRAY['specificity','validity','consistency'] LOOP
  IF coalesce(data#>>ARRAY['dimensions',key],'') NOT IN('supported','unsupported','uncertain') THEN RETURN false;END IF;
 END LOOP;
 SELECT sealed.document->>'context_object_digest' INTO object_sha FROM material_judgment_job.jobs job JOIN material_input_seal.records sealed ON sealed.id=job.seal_id WHERE job.id=a.job_id;
 SELECT o.data INTO raw FROM technical_material_store.objects o WHERE sha=object_sha;
 IF raw IS NULL OR octet_length(raw)>12582912 OR encode(sha256(raw),'hex') IS DISTINCT FROM object_sha THEN RETURN false;END IF;
 context:=convert_from(raw,'UTF8')::jsonb;
 IF context->>'digest' IS DISTINCT FROM a.document#>>'{request,context_digest}' THEN RETURN false;END IF;
 SELECT value INTO rule FROM jsonb_array_elements(context->'rules') WHERE value->>'rule_id'=a.document->>'rule_id' AND value->>'selection'='include';
 IF rule IS NULL OR NOT EXISTS(SELECT FROM jsonb_array_elements(rule->'bands') band WHERE band->'band_id'=data->'band_id')
  OR NOT ((data->'covered_part_ids') @> (rule->'required_part_ids') AND (rule->'required_part_ids') @> (data->'covered_part_ids'))
  OR jsonb_array_length(data->'covered_part_ids')<>jsonb_array_length(rule->'required_part_ids') THEN RETURN false;END IF;
 FOR reference_lexical IN SELECT value FROM json_array_elements(content_lexical->'evidence') LOOP
  reference:=reference_lexical::jsonb;
  IF design.package_json_keys(reference,ARRAY['evidence_id','document_version_id','parse_run_id','physical_page','page_image_digest','quote','region']) IS DISTINCT FROM true
   OR jsonb_typeof(reference->'quote') IS DISTINCT FROM 'string' OR length(reference->>'quote')>16000 OR reference->>'quote' !~ '\S' THEN RETURN false;END IF;
  SELECT value INTO native FROM jsonb_array_elements(context->'evidence_catalog') WHERE value->'id'=reference->'evidence_id';
  IF native IS NULL THEN RETURN false;END IF;
  FOREACH key IN ARRAY ARRAY['document_version_id','parse_run_id','physical_page','page_image_digest'] LOOP
   IF reference->key IS DISTINCT FROM native->key THEN RETURN false;END IF;
  END LOOP;
  -- jsonb normalizes 1e0 to 1. The original strict Python codec forbids floats,
  -- so keep the original JSON number spelling for these integer-only fields.
  IF coalesce(reference_lexical->>'physical_page','') !~ '^-?(0|[1-9][0-9]{0,5})$' THEN RETURN false;END IF;
  IF position(reference->>'quote' in native->>'text_content')=0 THEN RETURN false;END IF;
  region:=reference->'region';
  IF region IS DISTINCT FROM 'null'::jsonb THEN
   IF jsonb_typeof(region) IS DISTINCT FROM 'array' OR jsonb_array_length(region)<>4 THEN RETURN false;END IF;
   FOR point IN SELECT value FROM json_array_elements(reference_lexical->'region') LOOP
    IF json_typeof(point) IS DISTINCT FROM 'number' OR coalesce(point#>>'{}','') !~ '^-?(0|[1-9][0-9]{0,5})$' THEN RETURN false;END IF;
    IF (point#>>'{}')::numeric NOT BETWEEN 0 AND 100000 THEN RETURN false;END IF;
   END LOOP;
   IF (region->>0)::numeric>=(region->>2)::numeric OR (region->>1)::numeric>=(region->>3)::numeric
    OR (region->>2)::numeric>(native->>'page_width')::numeric OR (region->>3)::numeric>(native->>'page_height')::numeric THEN RETURN false;END IF;
  END IF;
 END LOOP;
 RETURN true;
END;
$execution_judgment$;

CREATE FUNCTION material_execution.settle(target uuid,token uuid,submitted jsonb,raw bytea,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_settle$
DECLARE a material_execution.attempts;o material_execution.outcomes;r material_execution.reservations;j material_execution.job_balances;b material_execution.balances;
 p material_execution.profiles;job material_judgment_job.jobs;
 result jsonb;response jsonb;response_lexical json;usage jsonb;price jsonb;key text;checksum text;submitted_sha text;fee numeric;per_call bigint;held bigint;
 current_ok boolean;valid boolean;duplicate boolean;overrun boolean;state_name text;at timestamptz;
BEGIN
 PERFORM material_execution.require_worker(true);
 SELECT * INTO a FROM material_execution.attempts WHERE id=target AND send_token=token AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 IF command IS NULL OR raw IS NULL OR octet_length(raw)>1048576 OR NOT design.package_json_keys(submitted,ARRAY['version','attempt_id','request_digest','raw_response_digest','raw_complete','billing_state','usage','response_id','request_id','valid_slot','judgment_digest','failure_code','formal_prediction_eligible','invoice_reconciled'])
  OR submitted->>'version' IS DISTINCT FROM 'material-execution-submitted-outcome/1' OR submitted->>'attempt_id' IS DISTINCT FROM a.id::text
  OR submitted->>'request_digest' IS DISTINCT FROM a.document#>>'{request,request_digest}'
  OR submitted->>'raw_response_digest' IS DISTINCT FROM encode(sha256(raw),'hex')
  OR submitted->'formal_prediction_eligible' IS DISTINCT FROM 'false'::jsonb OR submitted->'invoice_reconciled' IS DISTINCT FROM 'false'::jsonb
  OR jsonb_typeof(submitted->'raw_complete') IS DISTINCT FROM 'boolean' OR jsonb_typeof(submitted->'valid_slot') IS DISTINCT FROM 'boolean'
  OR coalesce(submitted->>'billing_state','') NOT IN('usage_reported','unknown')
  OR coalesce(submitted->>'failure_code','') !~ '^[A-Z][A-Z0-9_]{0,79}$' THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
 FOREACH key IN ARRAY ARRAY['request_id','response_id'] LOOP
  IF submitted->key IS DISTINCT FROM 'null'::jsonb AND (jsonb_typeof(submitted->key) IS DISTINCT FROM 'string' OR coalesce(submitted->>key,'') !~ '^[A-Za-z0-9._:-]{1,200}$') THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
 END LOOP;
 submitted_sha:=encode(sha256(convert_to(design.package_canonical_json(submitted),'UTF8')),'hex');
 SELECT * INTO p FROM material_execution.profiles WHERE id=a.profile_id;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=a.job_id;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_execution:'||a.job_id::text,0));
 SELECT * INTO o FROM material_execution.outcomes WHERE attempt_id=a.id;
 IF FOUND THEN
  IF o.submitted_digest::text<>submitted_sha OR o.raw_response<>raw THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_SETTLEMENT_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN material_execution.observation(a.id,false);
 END IF;
 IF EXISTS(SELECT FROM material_execution.outcomes WHERE command_id=command) OR EXISTS(SELECT FROM material_execution.attempts WHERE command_id=command) THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
 PERFORM 1 FROM material_execution.profile_heads WHERE worker_login=p.worker_login FOR SHARE;
 PERFORM material_preparation.lock_inputs(a.job_id,p.preparation_profile_id);
 PERFORM 1 FROM material_preparation.states WHERE job_id=a.job_id FOR UPDATE;
 SELECT * INTO r FROM material_execution.reservations WHERE job_id=a.job_id;
 SELECT * INTO b FROM material_execution.balances WHERE account_id=r.account_id FOR UPDATE;
 SELECT * INTO j FROM material_execution.job_balances WHERE job_id=a.job_id FOR UPDATE;
 per_call:=(a.document->>'reserved_call_minor')::bigint;price:=a.document->'price_policy';fee:=NULL;
 IF submitted->>'billing_state'='usage_reported' THEN
  IF submitted->'raw_complete' IS DISTINCT FROM 'true'::jsonb OR jsonb_typeof(submitted->'usage') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  IF NOT (convert_from(raw,'UTF8') IS JSON OBJECT WITH UNIQUE KEYS) THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  response:=convert_from(raw,'UTF8')::jsonb;response_lexical:=convert_from(raw,'UTF8')::json;usage:=submitted->'usage';
  IF response->>'model' IS DISTINCT FROM 'deepseek-flash' OR jsonb_typeof(response->'id') IS DISTINCT FROM 'string' OR response->>'id' IS DISTINCT FROM submitted->>'response_id'
   OR coalesce(submitted->>'response_id','') !~ '^[A-Za-z0-9._:-]{1,200}$'
   OR coalesce(submitted->>'request_id','') !~ '^[A-Za-z0-9._:-]{1,200}$'
   OR NOT design.package_json_keys(usage,ARRAY['prompt_tokens','completion_tokens','total_tokens']) THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  IF jsonb_typeof(response->'choices') IS DISTINCT FROM 'array' OR jsonb_array_length(response->'choices')<>1
   OR response#>>'{choices,0,message,role}' IS DISTINCT FROM 'assistant'
   OR jsonb_typeof(response#>'{choices,0,message,content}') IS DISTINCT FROM 'string'
   OR coalesce(response#>>'{choices,0,message,content}','') !~ '\S'
   OR coalesce(response#>'{choices,0,message,tool_calls}','null'::jsonb) NOT IN('null'::jsonb,'[]'::jsonb,'{}'::jsonb,'false'::jsonb,'0'::jsonb,'""'::jsonb)
   OR (coalesce(response->'system_fingerprint','null'::jsonb)<>'null'::jsonb AND
    (jsonb_typeof(response->'system_fingerprint') IS DISTINCT FROM 'string' OR coalesce(response->>'system_fingerprint','') !~ '^[A-Za-z0-9._:-]{1,200}$'))
   THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  FOREACH key IN ARRAY ARRAY['prompt_tokens','completion_tokens','total_tokens'] LOOP
   IF jsonb_typeof(usage->key) IS DISTINCT FROM 'number' OR coalesce(usage->>key,'') !~ '^(0|[1-9][0-9]{0,15})$'
    OR coalesce(response_lexical#>>ARRAY['usage',key],'') !~ '^-?(0|[1-9][0-9]{0,15})$'
    OR (usage->>key)::numeric>9007199254740991 OR usage->key IS DISTINCT FROM response#>ARRAY['usage',key] THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  END LOOP;
  IF (usage->>'total_tokens')::numeric<>(usage->>'prompt_tokens')::numeric+(usage->>'completion_tokens')::numeric THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
  fee:=ceil(((usage->>'prompt_tokens')::numeric*(price->>'input_per_million_minor')::numeric+(usage->>'completion_tokens')::numeric*(price->>'output_per_million_minor')::numeric)/1000000);
  IF fee>9007199254740991 OR fee+b.estimated_minor>9007199254740991 OR fee+j.estimated_minor>9007199254740991 THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_AMOUNT_OVERFLOW' USING ERRCODE='P0001';END IF;
 ELSE
  IF submitted->'usage' IS DISTINCT FROM 'null'::jsonb OR submitted->'valid_slot' IS DISTINCT FROM 'false'::jsonb OR submitted->'judgment_digest' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
 END IF;
 IF submitted->'valid_slot'='true'::jsonb AND coalesce(submitted->>'judgment_digest','') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
 IF submitted->'valid_slot'='true'::jsonb AND material_execution.judgment_valid(a.id,response,submitted->>'judgment_digest') IS DISTINCT FROM true THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_OUTCOME_INVALID' USING ERRCODE='P0001';END IF;
 -- Late financial evidence remains recordable after expiry/revocation. It cannot
 -- resurrect a send grant or qualify a judgment from the stale material.
 result:=material_execution.current_context(a.preflight,a.profile_id);
 current_ok:=result IS NOT NULL AND result->'profile_head_revision'=a.document->'profile_head_revision';
 duplicate:=EXISTS(SELECT FROM material_execution.outcomes other JOIN material_execution.attempts prior ON prior.id=other.attempt_id
  WHERE prior.job_id=a.job_id AND other.document->>'response_id'=submitted->>'response_id' AND other.document->>'billing_state'='usage_reported');
 valid:=submitted->'valid_slot'='true'::jsonb AND current_ok AND NOT duplicate;
 overrun:=fee IS NOT NULL AND fee>per_call;
 state_name:=CASE WHEN fee IS NULL THEN 'unknown' WHEN overrun THEN 'paused_overrun' WHEN NOT current_ok THEN 'paused_stale' WHEN NOT valid THEN 'paused_invalid' ELSE 'ready' END;
 at:=clock_timestamp();
 result:=submitted||jsonb_build_object('version','material-execution-outcome/1','command_id',command::text,'estimated_fee_minor',fee::bigint,
  'fee_basis',CASE WHEN fee IS NULL THEN 'unresolved' ELSE 'usage_price_estimate' END,'source_current_at_settlement',current_ok,'duplicate_response',duplicate,
  'valid_slot',valid,'over_reservation',overrun,'state',state_name,'execution_mode','isolated_synthetic_mechanism','recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_execution.outcomes VALUES(a.id,command,submitted_sha,raw,result,checksum);
 IF fee IS NOT NULL THEN
  IF j.held_minor<per_call OR b.held_minor<per_call THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_LEDGER_INVALID' USING ERRCODE='P0001';END IF;
  UPDATE material_execution.job_balances SET held_minor=held_minor-per_call,estimated_minor=estimated_minor+fee::bigint,released_minor=released_minor+greatest(per_call-fee::bigint,0),state=state_name WHERE job_id=a.job_id;
  UPDATE material_execution.balances SET held_minor=held_minor-per_call,estimated_minor=estimated_minor+fee::bigint WHERE account_id=r.account_id;
 ELSE
  UPDATE material_execution.job_balances SET state='unknown' WHERE job_id=a.job_id;
 END IF;
 IF state_name='ready' AND NOT EXISTS(SELECT FROM material_judgment_job.slots slot WHERE slot.job_id=a.job_id AND NOT EXISTS(
  SELECT FROM material_execution.attempts attempt JOIN material_execution.outcomes outcome ON outcome.attempt_id=attempt.id
  WHERE attempt.slot_id=slot.id AND outcome.document->'valid_slot'='true'::jsonb)) THEN
  SELECT held_minor INTO held FROM material_execution.job_balances WHERE job_id=a.job_id;
  UPDATE material_execution.job_balances SET held_minor=0,released_minor=released_minor+held,state='completed' WHERE job_id=a.job_id;
  UPDATE material_execution.balances SET held_minor=held_minor-held WHERE account_id=r.account_id;
 END IF;
 RETURN material_execution.observation(a.id,false);
END;
$execution_settle$;

CREATE FUNCTION material_execution.read(target uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_read$
BEGIN
 PERFORM material_execution.require_worker(false);
 RETURN material_execution.observation(target,false);
END;
$execution_read$;

CREATE FUNCTION material_execution.response(target uuid,expected_outcome_digest text)
RETURNS bytea LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_execution,design,pg_temp SET TimeZone='UTC'
AS $execution_response$
DECLARE raw bytea;
BEGIN
 PERFORM material_execution.require_worker(false);
 PERFORM material_execution.observation(target,false);
 SELECT raw_response INTO raw FROM material_execution.outcomes WHERE attempt_id=target AND digest=expected_outcome_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_EXECUTION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 RETURN raw;
END;
$execution_response$;
REVOKE ALL ON FUNCTION material_execution.native_method_digest(),material_execution.require_worker(boolean),material_execution.current_context(jsonb,uuid),material_execution.observation(uuid,boolean),material_execution.judgment_valid(uuid,jsonb,text),material_execution.begin_attempt(jsonb,uuid,text,uuid,uuid,uuid),material_execution.settle(uuid,uuid,jsonb,bytea,uuid),material_execution.read(uuid),material_execution.response(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_execution TO tender_material_execution_worker;
GRANT EXECUTE ON FUNCTION material_execution.begin_attempt(jsonb,uuid,text,uuid,uuid,uuid),material_execution.settle(uuid,uuid,jsonb,bytea,uuid),material_execution.read(uuid),material_execution.response(uuid,text) TO tender_material_execution_worker;
COMMIT;
