-- Dedicated ID-only transport for the existing material judgment outbox.
-- No ordinary worker role, ordinary outbox, paid admission or retry is granted.
BEGIN;
CREATE SCHEMA material_dispatch;
REVOKE ALL ON SCHEMA material_dispatch FROM PUBLIC;
CREATE ROLE tender_material_dispatch_relay NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_material_dispatch_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_dispatch.profiles(
 id uuid PRIMARY KEY,relay_login name NOT NULL,relay_login_oid oid NOT NULL,worker_login name NOT NULL,worker_login_oid oid NOT NULL,
 job_profile_id uuid NOT NULL REFERENCES material_judgment_job.profiles(id),job_profile_digest design.sha256 NOT NULL,
 preparation_profile_id uuid NOT NULL REFERENCES material_preparation.profiles(id),preparation_profile_digest design.sha256 NOT NULL,
 execution_profile_id uuid REFERENCES material_execution.profiles(id),execution_profile_digest design.sha256,
 mode text NOT NULL CHECK(mode IN('production_admission','synthetic_mechanism')),
 origin text NOT NULL CHECK(origin IN('current_prebid','synthetic_mechanism')),
 lease_seconds integer NOT NULL CHECK(lease_seconds BETWEEN 1 AND 120),
 dispatch_method_digest design.sha256 NOT NULL,dispatch_sql_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,
 CHECK(relay_login<>worker_login AND relay_login_oid<>worker_login_oid),
 CHECK(valid_from<valid_until AND valid_until<=valid_from+interval '24 hours'),
 CHECK((execution_profile_id IS NULL)=(execution_profile_digest IS NULL)),
 CHECK(mode<>'synthetic_mechanism' OR (origin='synthetic_mechanism' AND database_name ~ '^fusion_[a-z0-9_]+$' AND execution_profile_id IS NOT NULL))
);
CREATE TABLE material_dispatch.profile_heads(
 job_profile_id uuid PRIMARY KEY REFERENCES material_judgment_job.profiles(id),profile_id uuid NOT NULL REFERENCES material_dispatch.profiles(id),
 revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_dispatch.leases(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,event_id uuid NOT NULL REFERENCES material_judgment_job.outbox(id),
 profile_id uuid NOT NULL REFERENCES material_dispatch.profiles(id),purpose text NOT NULL CHECK(purpose IN('relay','worker')),
 actor name NOT NULL,actor_oid oid NOT NULL,fence bigint NOT NULL CHECK(fence BETWEEN 1 AND 9007199254740991),
 token uuid NOT NULL UNIQUE,document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384),UNIQUE(purpose,event_id,fence)
);
CREATE TABLE material_dispatch.states(
 purpose text NOT NULL CHECK(purpose IN('relay','worker')),event_id uuid NOT NULL REFERENCES material_judgment_job.outbox(id),
 lease_id uuid NOT NULL REFERENCES material_dispatch.leases(id),fence bigint NOT NULL,lease_until timestamptz NOT NULL,
 state text NOT NULL CHECK(state IN('running','published','blocked','mechanism_completed','billing_unresolved')),
 PRIMARY KEY(purpose,event_id)
);
CREATE TABLE material_dispatch.results(
 event_id uuid PRIMARY KEY REFERENCES material_judgment_job.outbox(id),lease_id uuid NOT NULL REFERENCES material_dispatch.leases(id),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=32768)
);
CREATE TRIGGER immutable_material_dispatch_profile BEFORE UPDATE OR DELETE ON material_dispatch.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_material_dispatch_lease BEFORE UPDATE OR DELETE ON material_dispatch.leases FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_material_dispatch_result BEFORE UPDATE OR DELETE ON material_dispatch.results FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_dispatch.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_dispatch.native_method_digest()','material_dispatch.require_purpose(text,boolean)',
 'material_dispatch.profile_context(uuid,text)','material_dispatch.envelope(uuid)','material_dispatch.claim(uuid,uuid,text,uuid)',
 'material_dispatch.observation(uuid,boolean)','material_dispatch.claim_publication(uuid,text,uuid)','material_dispatch.ack_publication(uuid,uuid)',
 'material_dispatch.claim_delivery(uuid,jsonb,uuid)','material_dispatch.heartbeat(uuid,uuid)','material_dispatch.owned_job(uuid,uuid)',
 'material_dispatch.finish(uuid,uuid,text)','material_dispatch.read(uuid)']) s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>13 THEN RETURN NULL;END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$dispatch_method$;

CREATE FUNCTION material_dispatch.require_purpose(kind text,write_required boolean)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_purpose$
DECLARE allowed text[];group_name text;
BEGIN
 IF (write_required AND (current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off'))
  OR (NOT write_required AND (current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on')) THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF kind='relay' THEN
  group_name:='tender_material_dispatch_relay';allowed:=ARRAY['material_dispatch.claim_publication(uuid,text,uuid)','material_dispatch.ack_publication(uuid,uuid)'];
 ELSIF kind='worker' THEN
  group_name:='tender_material_dispatch_worker';allowed:=ARRAY['material_dispatch.claim_delivery(uuid,jsonb,uuid)','material_dispatch.heartbeat(uuid,uuid)','material_dispatch.owned_job(uuid,uuid)','material_dispatch.finish(uuid,uuid,text)','material_dispatch.read(uuid)'];
 ELSE RAISE EXCEPTION 'MATERIAL_DISPATCH_PURPOSE_INVALID' USING ERRCODE='P0001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,group_name,allowed) THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
END;
$dispatch_purpose$;

CREATE FUNCTION material_dispatch.profile_context(target uuid,kind text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_profile$
DECLARE p material_dispatch.profiles;h material_dispatch.profile_heads;jp material_judgment_job.profiles;pp material_preparation.profiles;ep material_execution.profiles;at timestamptz;
BEGIN
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=target;
 SELECT * INTO h FROM material_dispatch.profile_heads WHERE job_profile_id=p.job_profile_id;
 SELECT * INTO jp FROM material_judgment_job.profiles WHERE id=p.job_profile_id;
 SELECT * INTO pp FROM material_preparation.profiles WHERE id=p.preparation_profile_id;
 SELECT * INTO ep FROM material_execution.profiles WHERE id=p.execution_profile_id;
 at:=clock_timestamp();
 IF p.id IS NULL OR jp.id IS NULL OR pp.id IS NULL OR NOT coalesce(h.profile_id=p.id AND h.enabled
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.dispatch_sql_method_digest::text=material_dispatch.native_method_digest() AND at>=p.valid_from AND at<p.valid_until
  AND p.job_profile_digest::text=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(jp)),'UTF8')),'hex')
  AND p.preparation_profile_digest::text=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(pp)),'UTF8')),'hex')
  AND pp.job_profile_id=jp.id AND pp.job_profile_digest=p.job_profile_digest AND pp.origin=p.origin AND jp.origin=p.origin
  AND p.relay_login NOT IN(p.worker_login,jp.submit_login,jp.request_login,pp.worker_login)
  AND p.worker_login NOT IN(jp.submit_login,jp.request_login,pp.worker_login)
  AND p.relay_login_oid NOT IN(p.worker_login_oid,jp.submit_login_oid,jp.request_login_oid,pp.worker_login_oid)
  AND p.worker_login_oid NOT IN(jp.submit_login_oid,jp.request_login_oid,pp.worker_login_oid)
  AND EXISTS(SELECT FROM pg_roles WHERE oid=p.relay_login_oid AND rolname=p.relay_login AND rolcanlogin)
  AND EXISTS(SELECT FROM pg_roles WHERE oid=p.worker_login_oid AND rolname=p.worker_login AND rolcanlogin)
  AND ((kind='relay' AND p.relay_login=session_user AND p.relay_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user))
    OR(kind='worker' AND p.worker_login=session_user AND p.worker_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)))
  AND (p.mode='production_admission' OR (ep.id IS NOT NULL AND ep.preparation_profile_id=pp.id AND ep.preparation_profile_digest=p.preparation_profile_digest
    AND p.execution_profile_digest::text=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(ep)),'UTF8')),'hex')
    AND ep.worker_login NOT IN(p.relay_login,p.worker_login) AND ep.worker_login_oid NOT IN(p.relay_login_oid,p.worker_login_oid))),false) THEN RETURN NULL;END IF;
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),'revision',h.revision);
END;
$dispatch_profile$;

CREATE FUNCTION material_dispatch.envelope(target_event uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_envelope$
DECLARE e material_judgment_job.outbox;
BEGIN
 SELECT * INTO e FROM material_judgment_job.outbox WHERE id=target_event;
 IF NOT FOUND THEN RETURN NULL;END IF;
 RETURN e.payload||jsonb_build_object('version','material-judgment-task/1','event_id',e.id::text);
END;
$dispatch_envelope$;

CREATE FUNCTION material_dispatch.observation(target_lease uuid,new_claim boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_observation$
DECLARE l material_dispatch.leases;s material_dispatch.states;r material_dispatch.results;
BEGIN
 SELECT * INTO l FROM material_dispatch.leases WHERE id=target_lease AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO s FROM material_dispatch.states WHERE purpose=l.purpose AND event_id=l.event_id;
 SELECT * INTO r FROM material_dispatch.results WHERE event_id=l.event_id;
 RETURN jsonb_build_object('lease',jsonb_build_object('document',l.document,'digest',l.digest::text),'new_claim',new_claim,'state',s.state,
  'lease_current',s.lease_id=l.id AND s.fence=l.fence AND clock_timestamp()<s.lease_until AND s.state='running',
  'lease_until',to_char(s.lease_until,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'result',CASE WHEN l.purpose<>'worker' OR r.event_id IS NULL THEN NULL ELSE jsonb_build_object('document',r.document,'digest',r.digest::text) END);
END;
$dispatch_observation$;

CREATE FUNCTION material_dispatch.claim(target_profile uuid,target_event uuid,kind text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_claim$
DECLARE p material_dispatch.profiles;old material_dispatch.leases;s material_dispatch.states;ctx jsonb;e material_judgment_job.outbox;job material_judgment_job.jobs;
 result jsonb;checksum text;identifier uuid;token uuid;next_fence bigint;at timestamptz;until_at timestamptz;
BEGIN
 IF command IS NULL OR target_event IS NULL OR target_profile IS NULL THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('material_dispatch_command:'||command::text,0));
 SELECT * INTO old FROM material_dispatch.leases WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.event_id<>target_event OR old.profile_id<>target_profile OR old.purpose<>kind THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN material_dispatch.observation(old.id,false);
 END IF;
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=target_profile;
 PERFORM 1 FROM material_dispatch.profile_heads WHERE job_profile_id=p.job_profile_id FOR SHARE;
 ctx:=material_dispatch.profile_context(p.id,kind);
 SELECT * INTO e FROM material_judgment_job.outbox WHERE id=target_event;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=e.job_id;
 IF ctx IS NULL OR job.profile_id IS DISTINCT FROM p.job_profile_id OR job.document->>'origin' IS DISTINCT FROM p.origin THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_PROFILE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('material_dispatch:'||kind||':'||e.id::text,0));
 SELECT * INTO s FROM material_dispatch.states WHERE purpose=kind AND event_id=e.id FOR UPDATE;
 at:=clock_timestamp();
 IF s.event_id IS NOT NULL AND (s.state<>'running' OR at<s.lease_until) THEN
  SELECT * INTO old FROM material_dispatch.leases WHERE id=s.lease_id;
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_ALREADY_OWNED' USING ERRCODE='P0001';END IF;
  RETURN material_dispatch.observation(old.id,false);
 END IF;
 next_fence:=coalesce(s.fence,0)+1;
 IF next_fence>9007199254740991 THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_FENCE_OVERFLOW' USING ERRCODE='P0001';END IF;
 identifier:=gen_random_uuid();token:=gen_random_uuid();until_at:=least(at+make_interval(secs=>p.lease_seconds),p.valid_until);
 result:=jsonb_build_object('version','material-dispatch-lease/1','lease_id',identifier::text,'command_id',command::text,'event_id',e.id::text,'job_id',job.id::text,
  'job_digest',job.digest::text,'generation',1,'fence',next_fence,'profile_id',p.id::text,'profile_digest',ctx->>'profile_digest','profile_head_revision',ctx->'revision',
  'purpose',kind,'mode',p.mode,'origin',p.origin,'token',token::text,'lease_until',to_char(until_at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'message',material_dispatch.envelope(e.id),'dispatch_method_digest',p.dispatch_method_digest::text,'native_sql_method_digest',material_dispatch.native_method_digest(),
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'production_send_authorized',false,'formal_prediction_eligible',false,'automatic_model_retry',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_dispatch.leases VALUES(identifier,command,e.id,p.id,kind,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),next_fence,token,result,checksum);
 INSERT INTO material_dispatch.states VALUES(kind,e.id,identifier,next_fence,until_at,'running') ON CONFLICT(purpose,event_id) DO UPDATE SET lease_id=excluded.lease_id,fence=excluded.fence,lease_until=excluded.lease_until,state='running';
 RETURN material_dispatch.observation(identifier,true);
END;
$dispatch_claim$;

CREATE FUNCTION material_dispatch.claim_publication(target_profile uuid,expected_profile_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_claim_publication$
DECLARE p material_dispatch.profiles;ctx jsonb;candidate uuid;old material_dispatch.leases;
BEGIN
 PERFORM material_dispatch.require_purpose('relay',true);
 ctx:=material_dispatch.profile_context(target_profile,'relay');
 IF ctx IS NULL OR ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_PROFILE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=target_profile;
 SELECT * INTO old FROM material_dispatch.leases WHERE command_id=command;
 IF FOUND THEN RETURN material_dispatch.claim(p.id,old.event_id,'relay',command);END IF;
 SELECT e.id INTO candidate FROM material_judgment_job.outbox e JOIN material_judgment_job.jobs job ON job.id=e.job_id
  LEFT JOIN material_dispatch.states s ON s.purpose='relay' AND s.event_id=e.id
  WHERE job.profile_id=p.job_profile_id AND (s.event_id IS NULL OR (s.state='running' AND s.lease_until<=clock_timestamp()))
  ORDER BY e.id LIMIT 1 FOR UPDATE OF e SKIP LOCKED;
 IF candidate IS NULL THEN RETURN NULL;END IF;
 RETURN material_dispatch.claim(p.id,candidate,'relay',command);
END;
$dispatch_claim_publication$;

CREATE FUNCTION material_dispatch.ack_publication(target_lease uuid,token_value uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_ack_publication$
DECLARE l material_dispatch.leases;s material_dispatch.states;
BEGIN
 PERFORM material_dispatch.require_purpose('relay',true);
 SELECT * INTO l FROM material_dispatch.leases WHERE id=target_lease AND token=token_value AND purpose='relay' AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO s FROM material_dispatch.states WHERE purpose='relay' AND event_id=l.event_id FOR UPDATE;
 IF s.lease_id<>l.id OR s.fence<>l.fence OR (s.state<>'published' AND clock_timestamp()>=s.lease_until) THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 UPDATE material_dispatch.states SET state='published' WHERE purpose='relay' AND event_id=l.event_id;
 RETURN material_dispatch.observation(l.id,false);
END;
$dispatch_ack_publication$;

CREATE FUNCTION material_dispatch.claim_delivery(target_event uuid,message jsonb,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_claim_delivery$
DECLARE job material_judgment_job.jobs;p material_dispatch.profiles;completed material_dispatch.leases;
BEGIN
 PERFORM material_dispatch.require_purpose('worker',true);
 IF message IS DISTINCT FROM material_dispatch.envelope(target_event) OR message IS NULL THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_MESSAGE_MISMATCH' USING ERRCODE='P0001';END IF;
 -- A terminal receipt survives profile expiry/revocation: a lost Kafka offset
 -- ACK must remain observation-only, without reopening admission or the wallet.
 SELECT l.* INTO completed FROM material_dispatch.leases l JOIN material_dispatch.states s ON s.lease_id=l.id
  WHERE s.purpose='worker' AND s.event_id=target_event AND s.state IN('blocked','mechanism_completed','billing_unresolved')
   AND l.actor=session_user AND l.actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF FOUND THEN RETURN material_dispatch.observation(completed.id,false);END IF;
 SELECT j.* INTO job FROM material_judgment_job.jobs j JOIN material_judgment_job.outbox e ON e.job_id=j.id WHERE e.id=target_event;
 SELECT profile.* INTO p FROM material_dispatch.profiles profile JOIN material_dispatch.profile_heads head ON head.profile_id=profile.id WHERE head.job_profile_id=job.profile_id;
 RETURN material_dispatch.claim(p.id,target_event,'worker',command);
END;
$dispatch_claim_delivery$;

CREATE FUNCTION material_dispatch.heartbeat(target_lease uuid,token_value uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_heartbeat$
DECLARE l material_dispatch.leases;s material_dispatch.states;p material_dispatch.profiles;ctx jsonb;
BEGIN
 PERFORM material_dispatch.require_purpose('worker',true);
 SELECT * INTO l FROM material_dispatch.leases WHERE id=target_lease AND token=token_value AND purpose='worker' AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=l.profile_id;
 PERFORM 1 FROM material_dispatch.profile_heads WHERE job_profile_id=p.job_profile_id FOR SHARE;
 SELECT * INTO s FROM material_dispatch.states WHERE purpose='worker' AND event_id=l.event_id FOR UPDATE;
 ctx:=material_dispatch.profile_context(l.profile_id,'worker');
 IF ctx IS NULL OR ctx->'revision' IS DISTINCT FROM l.document->'profile_head_revision' OR s.lease_id<>l.id OR s.fence<>l.fence OR s.state<>'running' OR clock_timestamp()>=s.lease_until THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 UPDATE material_dispatch.states SET lease_until=least(clock_timestamp()+make_interval(secs=>p.lease_seconds),p.valid_until) WHERE purpose='worker' AND event_id=l.event_id;
 RETURN material_dispatch.observation(l.id,false);
END;
$dispatch_heartbeat$;

CREATE FUNCTION material_dispatch.owned_job(target_lease uuid,token_value uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_owned_job$
DECLARE l material_dispatch.leases;s material_dispatch.states;p material_dispatch.profiles;job material_judgment_job.jobs;sealed material_input_seal.records;storage technical_material_store.records;
 ctx jsonb;prepared jsonb;financial material_execution.job_balances;result jsonb;
BEGIN
 PERFORM material_dispatch.require_purpose('worker',false);
 SELECT * INTO l FROM material_dispatch.leases WHERE id=target_lease AND token=token_value AND purpose='worker' AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO s FROM material_dispatch.states WHERE purpose='worker' AND event_id=l.event_id;
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=l.profile_id;
 ctx:=material_dispatch.profile_context(l.profile_id,'worker');
 IF ctx IS NULL OR ctx->'revision' IS DISTINCT FROM l.document->'profile_head_revision' OR s.lease_id<>l.id OR s.fence<>l.fence OR s.state<>'running' OR clock_timestamp()>=s.lease_until THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 SELECT j.* INTO job FROM material_judgment_job.jobs j JOIN material_judgment_job.outbox e ON e.job_id=j.id WHERE e.id=l.event_id;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=job.seal_id;
 SELECT * INTO storage FROM technical_material_store.records WHERE id=(sealed.document->>'storage_record_id')::uuid;
 SELECT * INTO financial FROM material_execution.job_balances WHERE job_id=job.id;
 prepared:=material_preparation.current_context(job.id,p.preparation_profile_id);
 result:=jsonb_build_object('version','material-dispatch-owned-job/1','lease',jsonb_build_object('document',l.document,'digest',l.digest::text),
  'job',jsonb_build_object('document',job.document,'digest',job.digest::text),'source_current',coalesce(prepared->'job_current'='true'::jsonb,false),
  'preparation_profile_id',p.preparation_profile_id::text,'preparation_profile_digest',p.preparation_profile_digest::text,
  'execution_profile_id',p.execution_profile_id::text,'execution_profile_digest',p.execution_profile_digest::text,
  'store_command_id',storage.command_id::text,'packet_digest',sealed.document->>'storage_packet_digest','storage_record_digest',sealed.document->>'storage_record_digest',
  'financial_state',financial.state,'mode',p.mode,'production_send_authorized',false,
  'blockers',jsonb_build_array('LIVE_ACCOUNT_PRICE_UNCONFIRMED','MODEL_CONTEXT_FIT_UNPROVEN','VISUAL_READABILITY_UNVERIFIED','LIVE_SENDER_UNQUALIFIED'));
 RETURN result;
END;
$dispatch_owned_job$;

CREATE FUNCTION material_dispatch.finish(target_lease uuid,token_value uuid,failure_code text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_finish$
DECLARE l material_dispatch.leases;s material_dispatch.states;p material_dispatch.profiles;job material_judgment_job.jobs;
 prior material_dispatch.results;financial material_execution.job_balances;ctx jsonb;prepared jsonb;result jsonb;checksum text;state_name text;source_current boolean;attempts bigint;fenced integer;
BEGIN
 PERFORM material_dispatch.require_purpose('worker',true);
 IF failure_code IS NULL OR failure_code NOT IN('NONE','LIVE_QUALIFICATION_UNAVAILABLE','PREPARATION_FAILED','EXECUTION_FAILED','CONFIGURATION_UNAVAILABLE') THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_FAILURE_CODE_INVALID' USING ERRCODE='P0001';END IF;
 SELECT * INTO l FROM material_dispatch.leases WHERE id=target_lease AND token=token_value AND purpose='worker' AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO p FROM material_dispatch.profiles WHERE id=l.profile_id;
 SELECT j.* INTO job FROM material_judgment_job.jobs j JOIN material_judgment_job.outbox e ON e.job_id=j.id WHERE e.id=l.event_id;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_execution:'||job.id::text,0));
 PERFORM 1 FROM material_dispatch.profile_heads WHERE job_profile_id=p.job_profile_id FOR SHARE;
 PERFORM material_preparation.lock_inputs(job.id,p.preparation_profile_id);
 PERFORM 1 FROM material_preparation.states WHERE job_id=job.id FOR UPDATE;
 SELECT * INTO s FROM material_dispatch.states WHERE purpose='worker' AND event_id=l.event_id FOR UPDATE;
 SELECT * INTO prior FROM material_dispatch.results WHERE event_id=l.event_id;
 IF prior.event_id IS NOT NULL THEN RETURN material_dispatch.observation(l.id,false);END IF;
 ctx:=material_dispatch.profile_context(l.profile_id,'worker');
 IF ctx IS NULL OR ctx->'revision' IS DISTINCT FROM l.document->'profile_head_revision' OR s.lease_id<>l.id OR s.fence<>l.fence OR s.state<>'running' OR clock_timestamp()>=s.lease_until THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 SELECT * INTO financial FROM material_execution.job_balances WHERE job_id=job.id;
 SELECT count(*) INTO attempts FROM material_execution.attempts WHERE job_id=job.id;
 prepared:=material_preparation.current_context(job.id,p.preparation_profile_id);
 source_current:=coalesce(prepared->'job_current'='true'::jsonb,false);
 state_name:=CASE WHEN financial.state IN('unknown','in_flight') THEN 'billing_unresolved'
  WHEN p.mode='synthetic_mechanism' AND financial.state='completed' AND source_current THEN 'mechanism_completed' ELSE 'blocked' END;
 -- Terminal transport state cancels only this profile's current preparation
 -- lease in the same locked transaction. An old worker paused after heartbeat
 -- cannot acquire a fresh slot grant after terminal commit. Already committed
 -- sends remain financially settleable by the unchanged execution ledger.
 UPDATE material_preparation.states state SET lease_until=least(state.lease_until,clock_timestamp())
  FROM material_preparation.leases lease WHERE state.job_id=job.id AND lease.id=state.lease_id AND lease.job_id=job.id
   AND lease.profile_id=p.preparation_profile_id;
 GET DIAGNOSTICS fenced=ROW_COUNT;
 result:=jsonb_build_object('version','material-dispatch-result/1','event_id',l.event_id::text,'job_id',job.id::text,'generation',1,'job_digest',job.digest::text,
  'profile_id',p.id::text,'profile_digest',l.document->>'profile_digest','dispatch_method_digest',p.dispatch_method_digest::text,
  'state',state_name,'mode',p.mode,'source_current',source_current,'financial_state',financial.state,'held_minor',coalesce(financial.held_minor,0),
  'estimated_minor',coalesce(financial.estimated_minor,0),'observed_send_grants',attempts,'failure_code',failure_code,'preparation_fenced',fenced=1,
  'production_send_authorized',false,'formal_prediction_eligible',false,'automatic_model_retry',false,
  'blockers',CASE WHEN p.mode='production_admission' THEN jsonb_build_array('LIVE_ACCOUNT_PRICE_UNCONFIRMED','MODEL_CONTEXT_FIT_UNPROVEN','VISUAL_READABILITY_UNVERIFIED','LIVE_SENDER_UNQUALIFIED') ELSE '[]'::jsonb END,
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'recorded_at',to_char(clock_timestamp(),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_dispatch.results VALUES(l.event_id,l.id,result,checksum);
 UPDATE material_dispatch.states SET state=state_name WHERE purpose='worker' AND event_id=l.event_id;
 RETURN material_dispatch.observation(l.id,false);
END;
$dispatch_finish$;

CREATE FUNCTION material_dispatch.read(target_event uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_dispatch,design,pg_temp SET TimeZone='UTC'
AS $dispatch_read$
DECLARE l material_dispatch.leases;
BEGIN
 PERFORM material_dispatch.require_purpose('worker',false);
 SELECT lease.* INTO l FROM material_dispatch.leases lease JOIN material_dispatch.states state ON state.lease_id=lease.id
  WHERE state.purpose='worker' AND state.event_id=target_event AND lease.actor=session_user AND lease.actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF l.id IS NULL THEN RAISE EXCEPTION 'MATERIAL_DISPATCH_NOT_FOUND' USING ERRCODE='P0001';END IF;
 RETURN material_dispatch.observation(l.id,false);
END;
$dispatch_read$;
REVOKE ALL ON FUNCTION material_dispatch.native_method_digest(),material_dispatch.require_purpose(text,boolean),material_dispatch.profile_context(uuid,text),material_dispatch.envelope(uuid),material_dispatch.claim(uuid,uuid,text,uuid),material_dispatch.observation(uuid,boolean),material_dispatch.claim_publication(uuid,text,uuid),material_dispatch.ack_publication(uuid,uuid),material_dispatch.claim_delivery(uuid,jsonb,uuid),material_dispatch.heartbeat(uuid,uuid),material_dispatch.owned_job(uuid,uuid),material_dispatch.finish(uuid,uuid,text),material_dispatch.read(uuid) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_dispatch TO tender_material_dispatch_relay,tender_material_dispatch_worker;
GRANT EXECUTE ON FUNCTION material_dispatch.claim_publication(uuid,text,uuid),material_dispatch.ack_publication(uuid,uuid) TO tender_material_dispatch_relay;
GRANT EXECUTE ON FUNCTION material_dispatch.claim_delivery(uuid,jsonb,uuid),material_dispatch.heartbeat(uuid,uuid),material_dispatch.owned_job(uuid,uuid),material_dispatch.finish(uuid,uuid,text),material_dispatch.read(uuid) TO tender_material_dispatch_worker;
COMMIT;
