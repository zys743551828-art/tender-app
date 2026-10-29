-- Optional isolated initialization. Preparation is not permission to spend/send.
BEGIN;
CREATE SCHEMA material_preparation;
REVOKE ALL ON SCHEMA material_preparation FROM PUBLIC;
CREATE ROLE tender_material_preparation_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_preparation.profiles(
 id uuid PRIMARY KEY,worker_login name NOT NULL,worker_login_oid oid NOT NULL,
 job_profile_id uuid NOT NULL REFERENCES material_judgment_job.profiles(id),job_profile_digest design.sha256 NOT NULL,
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),lease_seconds integer NOT NULL CHECK(lease_seconds BETWEEN 1 AND 120),
 preparation_method_digest design.sha256 NOT NULL,preparation_sql_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_preparation.profile_heads(
 worker_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_preparation.profiles(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_preparation.leases(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,job_id uuid NOT NULL REFERENCES material_judgment_job.jobs(id),
 profile_id uuid NOT NULL REFERENCES material_preparation.profiles(id),profile_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,generation bigint NOT NULL CHECK(generation=1),fence bigint NOT NULL CHECK(fence BETWEEN 1 AND 9007199254740991),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384),UNIQUE(job_id,fence)
);
CREATE TABLE material_preparation.heartbeats(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,lease_id uuid NOT NULL REFERENCES material_preparation.leases(id),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384)
);
CREATE TABLE material_preparation.states(
 job_id uuid PRIMARY KEY REFERENCES material_judgment_job.jobs(id),lease_id uuid NOT NULL REFERENCES material_preparation.leases(id),
 generation bigint NOT NULL CHECK(generation=1),fence bigint NOT NULL CHECK(fence BETWEEN 1 AND 9007199254740991),lease_until timestamptz NOT NULL
);
CREATE TRIGGER immutable_preparation_profile BEFORE UPDATE OR DELETE ON material_preparation.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_preparation_lease BEFORE UPDATE OR DELETE ON material_preparation.leases FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_preparation_heartbeat BEFORE UPDATE OR DELETE ON material_preparation.heartbeats FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_preparation.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_preparation.native_method_digest()','material_preparation.current_context(uuid,uuid)',
 'material_preparation.lease_context(uuid,text)','material_preparation.lock_inputs(uuid,uuid)',
 'material_preparation.claim(uuid,text,uuid,text,uuid)','material_preparation.heartbeat(uuid,text,uuid)',
 'material_preparation.inspect(uuid,text)','material_preparation.owned_context(uuid,text)','material_preparation.owned_asset(uuid,text,text)','material_preparation.owned_assets(uuid,text)']) s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>10 THEN RETURN NULL;END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$preparation_method$;

CREATE FUNCTION material_preparation.current_context(target_job uuid,target_profile uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_context$
DECLARE p material_preparation.profiles;h material_preparation.profile_heads;job material_judgment_job.jobs;
 jp material_judgment_job.profiles;jh material_judgment_job.profile_heads;e material_judgment_job.evidence_events;eh material_judgment_job.evidence_heads;
 ctx jsonb;slots jsonb;at timestamptz;configuration boolean;job_valid boolean;
BEGIN
 SELECT * INTO p FROM material_preparation.profiles WHERE id=target_profile;
 SELECT * INTO h FROM material_preparation.profile_heads WHERE worker_login=p.worker_login;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=target_job;
 SELECT * INTO jp FROM material_judgment_job.profiles WHERE id=job.profile_id;
 SELECT * INTO jh FROM material_judgment_job.profile_heads WHERE submit_login=jp.submit_login;
 SELECT * INTO eh FROM material_judgment_job.evidence_heads WHERE job_id=job.id;
 SELECT * INTO e FROM material_judgment_job.evidence_events WHERE id=eh.event_id AND job_id=job.id AND revision=eh.revision;
 IF p.id IS NULL OR job.id IS NULL OR jp.id IS NULL OR e.id IS NULL THEN RETURN NULL;END IF;
 ctx:=material_judgment_job.current_context(e.renewal_id,jp.id);
 IF ctx IS NULL THEN RETURN NULL;END IF;
 SELECT jsonb_agg(jsonb_build_object('slot_id',id::text,'rule_id',rule_id::text,'rule_ordinal',rule_ordinal,'slot_number',slot_number,'max_attempts',max_attempts) ORDER BY rule_ordinal,slot_number)
 INTO slots FROM material_judgment_job.slots WHERE job_id=job.id;
 at:=clock_timestamp();
 configuration:=coalesce(p.worker_login=session_user AND p.worker_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.preparation_sql_method_digest::text=material_preparation.native_method_digest()
  AND p.job_profile_id=jp.id AND p.job_profile_digest::text=ctx->>'profile_digest' AND p.origin=jp.origin
  AND p.worker_login NOT IN(job.actor,jp.request_login,ctx#>>'{renewal,document,recorded_by}',ctx#>>'{renewal_context,seal,document,recorded_by}',ctx#>>'{renewal_context,quote,document,recorded_by}',ctx#>>'{renewal_context,verification,document,recorded_by}',ctx#>>'{renewal_context,new_context,program_profile,target_login}')
  AND p.worker_login_oid NOT IN(job.actor_oid,jp.request_login_oid,(ctx#>>'{renewal,document,recorded_by_oid}')::oid,(ctx#>>'{renewal_context,seal,document,recorded_by_oid}')::oid,(ctx#>>'{renewal_context,quote,document,recorded_by_oid}')::oid,(ctx#>>'{renewal_context,verification,document,recorded_by_oid}')::oid,(ctx#>>'{renewal_context,new_context,program_profile,target_login_oid}')::oid),false);
 job_valid:=coalesce(jh.profile_id=jp.id AND jh.enabled AND jh.revision=job.profile_head_revision
  AND at>=jp.valid_from AND at<jp.valid_until AND jp.database_name=current_database()
  AND jp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND jp.job_sql_method_digest::text=material_judgment_job.native_method_digest()
  AND job.actor=jp.submit_login AND job.actor_oid=jp.submit_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=job.actor_oid AND rolname=job.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(job.actor,'tender_material_judgment_submit',ARRAY['material_judgment_job.start(uuid,text,uuid,text,uuid)','material_judgment_job.read(uuid,text)','material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)'])
  AND job.digest::text=encode(sha256(convert_to(design.package_canonical_json(job.document),'UTF8')),'hex')
  AND job.document->>'profile_digest'=ctx->>'profile_digest' AND job.document->>'job_method_digest'=jp.job_method_digest::text
  AND job.document->>'native_sql_method_digest'=material_judgment_job.native_method_digest() AND slots=job.document->'slots'
  AND e.digest::text=encode(sha256(convert_to(design.package_canonical_json(e.document),'UTF8')),'hex')
  AND e.document->>'job_digest'=job.digest::text AND e.document->>'renewal_digest'=ctx#>>'{renewal,digest}'
  AND ctx->'renewal_current'='true'::jsonb AND ctx->'request_current'='true'::jsonb AND ctx->'budget_sufficient'='true'::jsonb
  AND ctx->>'intent_command_id'=job.intent_command_id::text AND ctx->'rule_ids'=job.document->'rule_ids'
  AND ctx#>>'{renewal,document,material_input_digest}'=job.document->>'material_input_digest'
  AND ctx#>>'{renewal,document,seal_id}'=job.seal_id::text AND ctx#>>'{renewal,document,quote_id}'=job.quote_id::text,false);
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'profile_head_revision',h.revision,'job',jsonb_build_object('document',job.document,'digest',job.digest::text),
  'evidence',jsonb_build_object('document',e.document,'digest',e.digest::text),'job_context',ctx,
  'profile_current',configuration,'job_current',job_valid,'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
END;
$preparation_context$;

CREATE FUNCTION material_preparation.lease_context(target_lease uuid,expected_lease_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_lease_context$
DECLARE l material_preparation.leases;s material_preparation.states;ctx jsonb;eligible boolean;at timestamptz;
BEGIN
 SELECT * INTO l FROM material_preparation.leases WHERE id=target_lease AND digest=expected_lease_digest
  AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RETURN NULL;END IF;
 SELECT * INTO s FROM material_preparation.states WHERE job_id=l.job_id;
 ctx:=material_preparation.current_context(l.job_id,l.profile_id);at:=clock_timestamp();
 eligible:=coalesce(s.lease_id=l.id AND s.generation=l.generation AND s.fence=l.fence AND at<s.lease_until
  AND ctx->'profile_current'='true'::jsonb AND ctx->'job_current'='true'::jsonb
  AND (ctx->>'profile_head_revision')::bigint=l.profile_head_revision
  AND l.document->>'profile_digest'=ctx->>'profile_digest'
  AND l.document->>'native_sql_method_digest'=material_preparation.native_method_digest(),false);
 RETURN jsonb_build_object('lease',jsonb_build_object('document',l.document,'digest',l.digest::text),'context',ctx,
  'current',jsonb_build_object('observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'generation',s.generation,'fence',s.fence,
   'lease_until',to_char(s.lease_until,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'profile_head_revision',ctx->'profile_head_revision','profile_current',coalesce(ctx->'profile_current','false'::jsonb),
   'job_current',coalesce(ctx->'job_current','false'::jsonb),'preparation_lease_current',eligible,
   'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$preparation_lease_context$;

CREATE FUNCTION material_preparation.lock_inputs(target_job uuid,target_profile uuid)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_locks$
DECLARE p material_preparation.profiles;job material_judgment_job.jobs;e material_judgment_job.evidence_events;
BEGIN
 SELECT * INTO p FROM material_preparation.profiles WHERE id=target_profile;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=target_job;
 PERFORM 1 FROM material_preparation.profile_heads WHERE worker_login=p.worker_login FOR SHARE;
 PERFORM 1 FROM material_judgment_job.profile_heads WHERE profile_id=job.profile_id FOR SHARE;
 PERFORM 1 FROM material_judgment_job.evidence_heads WHERE job_id=job.id FOR SHARE;
 SELECT e2.* INTO e FROM material_judgment_job.evidence_events e2 JOIN material_judgment_job.evidence_heads h ON h.event_id=e2.id WHERE h.job_id=job.id;
 PERFORM material_judgment_job.lock_inputs(e.renewal_id);
END;
$preparation_locks$;

CREATE FUNCTION material_preparation.claim(target_job uuid,expected_job_digest text,target_profile uuid,expected_profile_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_claim$
DECLARE job material_judgment_job.jobs;old material_preparation.leases;s material_preparation.states;p material_preparation.profiles;ctx jsonb;identifier uuid;result jsonb;checksum text;next_fence bigint;at timestamptz;until_at timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION 'PREPARATION_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_preparation_worker',ARRAY['material_preparation.claim(uuid,text,uuid,text,uuid)','material_preparation.heartbeat(uuid,text,uuid)','material_preparation.inspect(uuid,text)','material_preparation.owned_context(uuid,text)','material_preparation.owned_asset(uuid,text,text)','material_preparation.owned_assets(uuid,text)']) THEN RAISE EXCEPTION 'PREPARATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 IF target_job IS NULL OR target_profile IS NULL OR command IS NULL OR expected_job_digest IS NULL OR expected_profile_digest IS NULL THEN RAISE EXCEPTION 'PREPARATION_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=target_job AND digest=expected_job_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'PREPARATION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_preparation:'||command::text,0));
 SELECT * INTO old FROM material_preparation.leases WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.job_id<>job.id OR old.profile_id<>target_profile OR old.document->>'job_digest' IS DISTINCT FROM expected_job_digest OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'PREPARATION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 IF EXISTS(SELECT FROM material_preparation.heartbeats WHERE command_id=command) THEN RAISE EXCEPTION 'PREPARATION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
 PERFORM material_preparation.lock_inputs(job.id,target_profile);
 ctx:=material_preparation.current_context(job.id,target_profile);
 IF ctx IS NULL OR ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'PREPARATION_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 IF ctx->'profile_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'job_current' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 SELECT * INTO p FROM material_preparation.profiles WHERE id=target_profile;
 SELECT * INTO s FROM material_preparation.states WHERE job_id=job.id FOR UPDATE;
 at:=clock_timestamp();
 IF s.job_id IS NOT NULL AND at<s.lease_until THEN RAISE EXCEPTION 'PREPARATION_ALREADY_OWNED' USING ERRCODE='P0001';END IF;
 next_fence:=coalesce(s.fence,0)+1;
 IF next_fence>9007199254740991 THEN RAISE EXCEPTION 'PREPARATION_FENCE_OVERFLOW' USING ERRCODE='P0001';END IF;
 identifier:=gen_random_uuid();until_at:=at+make_interval(secs=>p.lease_seconds);
 result:=jsonb_build_object('version','material-preparation-lease/1','lease_id',identifier::text,'command_id',command::text,
  'job_id',job.id::text,'job_digest',job.digest::text,'profile_id',p.id::text,'profile_digest',expected_profile_digest,'profile_head_revision',ctx->'profile_head_revision',
  'generation',1,'fence',next_fence,'lease_seconds',p.lease_seconds,'lease_until',to_char(until_at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'material_input_digest',job.document->>'material_input_digest','quote_digest',job.document->>'quote_digest','context_digest',job.document->>'context_digest',
  'origin',p.origin,'preparation_method_digest',p.preparation_method_digest::text,'native_sql_method_digest',material_preparation.native_method_digest(),
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'preparation_lease_created',true,'native_binding_verified',true,'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,
  'input_authority_granted',false,'atomic_snapshot_verified',false,'automatic_retry',false,'account_price_confirmed',false,'model_context_fit_proven',false,'request_body_limit_verified',false,'actual_human_reading_verified',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_preparation.leases VALUES(identifier,command,job.id,p.id,(ctx->>'profile_head_revision')::bigint,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),1,next_fence,result,checksum);
 INSERT INTO material_preparation.states VALUES(job.id,identifier,1,next_fence,until_at) ON CONFLICT(job_id) DO UPDATE SET lease_id=excluded.lease_id,generation=excluded.generation,fence=excluded.fence,lease_until=excluded.lease_until;
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$preparation_claim$;

CREATE FUNCTION material_preparation.heartbeat(target_lease uuid,expected_lease_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_heartbeat$
DECLARE l material_preparation.leases;old material_preparation.heartbeats;job material_judgment_job.jobs;ctx jsonb;at timestamptz;until_at timestamptz;identifier uuid;result jsonb;checksum text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION 'PREPARATION_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_preparation_worker',ARRAY['material_preparation.claim(uuid,text,uuid,text,uuid)','material_preparation.heartbeat(uuid,text,uuid)','material_preparation.inspect(uuid,text)','material_preparation.owned_context(uuid,text)','material_preparation.owned_asset(uuid,text,text)','material_preparation.owned_assets(uuid,text)']) THEN RAISE EXCEPTION 'PREPARATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 SELECT * INTO l FROM material_preparation.leases WHERE id=target_lease AND digest=expected_lease_digest AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND OR command IS NULL THEN RAISE EXCEPTION 'PREPARATION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=l.job_id;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_preparation:'||command::text,0));
 SELECT * INTO old FROM material_preparation.heartbeats WHERE command_id=command;
 IF FOUND THEN
  IF old.lease_id<>l.id OR old.document->>'lease_digest' IS DISTINCT FROM expected_lease_digest THEN RAISE EXCEPTION 'PREPARATION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 IF EXISTS(SELECT FROM material_preparation.leases WHERE command_id=command) THEN RAISE EXCEPTION 'PREPARATION_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
 PERFORM material_preparation.lock_inputs(job.id,l.profile_id);
 PERFORM 1 FROM material_preparation.states WHERE job_id=job.id FOR UPDATE;
 ctx:=material_preparation.lease_context(l.id,expected_lease_digest);
 IF ctx#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 at:=clock_timestamp();until_at:=greatest((ctx#>>'{current,lease_until}')::timestamptz,at+make_interval(secs=>(ctx#>>'{context,profile,lease_seconds}')::integer));identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','material-preparation-heartbeat/1','heartbeat_id',identifier::text,'command_id',command::text,'lease_id',l.id::text,'lease_digest',l.digest::text,
  'job_id',l.job_id::text,'generation',l.generation,'fence',l.fence,'previous_lease_until',ctx#>>'{current,lease_until}',
  'lease_until',to_char(until_at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_preparation.heartbeats VALUES(identifier,command,l.id,result,checksum);
 UPDATE material_preparation.states SET lease_until=until_at WHERE job_id=job.id;
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$preparation_heartbeat$;

CREATE FUNCTION material_preparation.inspect(target_lease uuid,expected_lease_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_inspect$
DECLARE ctx jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN RAISE EXCEPTION 'PREPARATION_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_preparation_worker',ARRAY['material_preparation.claim(uuid,text,uuid,text,uuid)','material_preparation.heartbeat(uuid,text,uuid)','material_preparation.inspect(uuid,text)','material_preparation.owned_context(uuid,text)','material_preparation.owned_asset(uuid,text,text)','material_preparation.owned_assets(uuid,text)']) THEN RAISE EXCEPTION 'PREPARATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 ctx:=material_preparation.lease_context(target_lease,expected_lease_digest);
 IF ctx IS NULL THEN RAISE EXCEPTION 'PREPARATION_NOT_FOUND' USING ERRCODE='P0001';END IF;
 RETURN jsonb_build_object('record',ctx->'lease','current',ctx->'current');
END;
$preparation_inspect$;

CREATE FUNCTION material_preparation.owned_context(target_lease uuid,expected_lease_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_owned_context$
DECLARE checked jsonb;ctx jsonb;data bytea;result jsonb;object_sha text;
BEGIN
 checked:=material_preparation.inspect(target_lease,expected_lease_digest);
 IF checked#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 ctx:=material_preparation.lease_context(target_lease,expected_lease_digest);
 object_sha:=ctx#>>'{context,job_context,renewal_context,seal,document,context_object_digest}';
 SELECT o.data INTO data FROM technical_material_store.objects o WHERE sha=object_sha;
 IF data IS NULL OR octet_length(data)>12582912 OR encode(sha256(data),'hex')<>object_sha THEN RAISE EXCEPTION 'PREPARATION_OBJECT_INVALID' USING ERRCODE='P0001';END IF;
 result:=jsonb_build_object('lease',ctx->'lease','lease_id',target_lease::text,'job_id',ctx#>>'{lease,document,job_id}','generation',ctx#>'{lease,document,generation}',
  'fence',ctx#>'{lease,document,fence}','evidence_revision',ctx#>'{context,evidence,document,revision}',
  'context',convert_from(data,'UTF8')::jsonb,'context_object_digest',object_sha,
  'material_input',ctx#>'{context,job_context,renewal_context,seal,document,material_input}');
 IF material_preparation.lease_context(target_lease,expected_lease_digest)#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 RETURN result;
END;
$preparation_owned_context$;

CREATE FUNCTION material_preparation.owned_asset(target_lease uuid,expected_lease_digest text,object_sha text)
RETURNS bytea LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_owned_asset$
DECLARE checked jsonb;ctx jsonb;storage technical_material_store.records;data bytea;expected_size bigint;
BEGIN
 checked:=material_preparation.inspect(target_lease,expected_lease_digest);
 IF checked#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 ctx:=material_preparation.lease_context(target_lease,expected_lease_digest);
 SELECT * INTO storage FROM technical_material_store.records WHERE id=(ctx#>>'{context,job_context,renewal_context,seal,document,storage_record_id}')::uuid
  AND digest=ctx#>>'{context,job_context,renewal_context,seal,document,storage_record_digest}';
 SELECT (value->>'byte_size')::bigint INTO expected_size FROM jsonb_array_elements(storage.document#>'{packet,image_objects}') WHERE value->>'sha256'=object_sha LIMIT 1;
 IF expected_size IS NULL THEN RAISE EXCEPTION 'PREPARATION_ASSET_NOT_OWNED' USING ERRCODE='P0001';END IF;
 SELECT o.data INTO data FROM technical_material_store.objects o WHERE sha=object_sha;
 IF data IS NULL OR octet_length(data)<>expected_size OR octet_length(data)>33554432 OR encode(sha256(data),'hex')<>object_sha THEN RAISE EXCEPTION 'PREPARATION_OBJECT_INVALID' USING ERRCODE='P0001';END IF;
 IF material_preparation.lease_context(target_lease,expected_lease_digest)#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 RETURN data;
END;
$preparation_owned_asset$;
CREATE FUNCTION material_preparation.owned_assets(target_lease uuid,expected_lease_digest text)
RETURNS bytea[] LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_preparation,design,pg_temp SET TimeZone='UTC'
AS $preparation_owned_assets$
DECLARE checked jsonb;ctx jsonb;storage technical_material_store.records;data bytea[];amount integer;required integer;total_bytes bigint;valid boolean;
BEGIN
 checked:=material_preparation.inspect(target_lease,expected_lease_digest);
 IF checked#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 ctx:=material_preparation.lease_context(target_lease,expected_lease_digest);
 SELECT * INTO storage FROM technical_material_store.records WHERE id=(ctx#>>'{context,job_context,renewal_context,seal,document,storage_record_id}')::uuid
  AND digest=ctx#>>'{context,job_context,renewal_context,seal,document,storage_record_digest}';
 SELECT count(DISTINCT value->>'sha256') INTO required FROM jsonb_array_elements(storage.document#>'{packet,image_objects}');
 SELECT array_agg(o.data ORDER BY o.sha::text COLLATE "C"),count(*),sum(octet_length(o.data)),bool_and(octet_length(o.data)=r.byte_size AND octet_length(o.data)<=33554432 AND encode(sha256(o.data),'hex')=o.sha::text)
 INTO data,amount,total_bytes,valid FROM technical_material_store.objects o JOIN (
  SELECT DISTINCT value->>'sha256' sha,(value->>'byte_size')::bigint byte_size FROM jsonb_array_elements(storage.document#>'{packet,image_objects}')
 ) r ON r.sha=o.sha::text;
 IF required NOT BETWEEN 1 AND 384 OR amount<>required OR total_bytes>67108864 OR valid IS DISTINCT FROM true THEN RAISE EXCEPTION 'PREPARATION_OBJECT_INVALID' USING ERRCODE='P0001';END IF;
 IF material_preparation.lease_context(target_lease,expected_lease_digest)#>'{current,preparation_lease_current}' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'PREPARATION_LEASE_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 RETURN data;
END;
$preparation_owned_assets$;
REVOKE ALL ON FUNCTION material_preparation.native_method_digest(),material_preparation.current_context(uuid,uuid),material_preparation.lease_context(uuid,text),material_preparation.lock_inputs(uuid,uuid),
 material_preparation.claim(uuid,text,uuid,text,uuid),material_preparation.heartbeat(uuid,text,uuid),material_preparation.inspect(uuid,text),material_preparation.owned_context(uuid,text),material_preparation.owned_asset(uuid,text,text),material_preparation.owned_assets(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_preparation TO tender_material_preparation_worker;
GRANT EXECUTE ON FUNCTION material_preparation.claim(uuid,text,uuid,text,uuid),material_preparation.heartbeat(uuid,text,uuid),material_preparation.inspect(uuid,text),material_preparation.owned_context(uuid,text),material_preparation.owned_asset(uuid,text,text),material_preparation.owned_assets(uuid,text) TO tender_material_preparation_worker;
COMMIT;
