-- Optional fresh isolated initializer. Registration is never a send grant.
BEGIN;
CREATE SCHEMA material_judgment_job;
REVOKE ALL ON SCHEMA material_judgment_job FROM PUBLIC;
CREATE ROLE tender_material_judgment_submit NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_judgment_job.profiles(
 id uuid PRIMARY KEY,submit_login name NOT NULL,submit_login_oid oid NOT NULL,request_login name NOT NULL,request_login_oid oid NOT NULL,
 renewal_profile_id uuid NOT NULL REFERENCES material_input_renewal.profiles(id),renewal_profile_digest design.sha256 NOT NULL,
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),job_method_digest design.sha256 NOT NULL,job_sql_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_judgment_job.profile_heads(
 submit_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_judgment_job.profiles(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_judgment_job.jobs(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,intent_command_id uuid NOT NULL UNIQUE,
 profile_id uuid NOT NULL REFERENCES material_judgment_job.profiles(id),profile_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,scope_id uuid NOT NULL,
 seal_id uuid NOT NULL REFERENCES material_input_seal.records(id),quote_id uuid NOT NULL REFERENCES material_cost_quote.quotes(id),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=524288)
);
CREATE TABLE material_judgment_job.slots(
 id uuid PRIMARY KEY,job_id uuid NOT NULL REFERENCES material_judgment_job.jobs(id),rule_id uuid NOT NULL,
 rule_ordinal integer NOT NULL CHECK(rule_ordinal BETWEEN 1 AND 400),slot_number integer NOT NULL CHECK(slot_number BETWEEN 1 AND 3),
 max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),UNIQUE(job_id,rule_id,slot_number),UNIQUE(job_id,rule_ordinal,slot_number)
);
CREATE TABLE material_judgment_job.evidence_events(
 id uuid PRIMARY KEY,job_id uuid NOT NULL REFERENCES material_judgment_job.jobs(id),command_id uuid NOT NULL UNIQUE,
 revision bigint NOT NULL CHECK(revision>=1),renewal_id uuid NOT NULL REFERENCES material_input_renewal.records(id),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,UNIQUE(job_id,revision)
);
CREATE TABLE material_judgment_job.evidence_heads(
 job_id uuid PRIMARY KEY REFERENCES material_judgment_job.jobs(id),event_id uuid NOT NULL REFERENCES material_judgment_job.evidence_events(id),revision bigint NOT NULL CHECK(revision>=1)
);
CREATE TABLE material_judgment_job.outbox(
 id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES material_judgment_job.jobs(id),event_type text NOT NULL CHECK(event_type='judgment_job_preparation_requested'),
 payload jsonb NOT NULL,CHECK(payload=jsonb_build_object('job_id',job_id::text,'generation',1))
);
CREATE TRIGGER immutable_judgment_profile BEFORE UPDATE OR DELETE ON material_judgment_job.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_judgment_job BEFORE UPDATE OR DELETE ON material_judgment_job.jobs FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_judgment_slot BEFORE UPDATE OR DELETE ON material_judgment_job.slots FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_judgment_evidence BEFORE UPDATE OR DELETE ON material_judgment_job.evidence_events FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_judgment_outbox BEFORE UPDATE OR DELETE ON material_judgment_job.outbox FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_judgment_job.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
 'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_judgment_job.native_method_digest()','material_judgment_job.current_context(uuid,uuid)',
 'material_judgment_job.lock_inputs(uuid)','material_judgment_job.start(uuid,text,uuid,text,uuid)','material_judgment_job.read(uuid,text)',
 'material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)']) s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>6 THEN RETURN NULL;END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$judgment_job_method$;

CREATE FUNCTION material_judgment_job.current_context(target_renewal uuid,target_profile uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_context$
DECLARE p material_judgment_job.profiles;h material_judgment_job.profile_heads;r material_input_renewal.records;
 rp material_input_renewal.profiles;rh material_input_renewal.profile_heads;initial material_verification.commands;original_case material_verification.cases;
 ctx jsonb;context jsonb;rules jsonb;at timestamptz;configuration boolean;renewal_valid boolean;request_valid boolean;
BEGIN
 SELECT * INTO p FROM material_judgment_job.profiles WHERE id=target_profile;
 SELECT * INTO h FROM material_judgment_job.profile_heads WHERE submit_login=p.submit_login;
 SELECT * INTO r FROM material_input_renewal.records WHERE id=target_renewal;
 SELECT * INTO rp FROM material_input_renewal.profiles WHERE id=r.profile_id;
 SELECT * INTO rh FROM material_input_renewal.profile_heads WHERE renew_login=rp.renew_login;
 IF p.id IS NULL OR r.id IS NULL OR rp.id IS NULL THEN RETURN NULL;END IF;
 ctx:=material_input_renewal.current_context(r.seal_id,r.quote_id,r.verification_id,r.profile_id);
 IF ctx IS NULL THEN RETURN NULL;END IF;
 SELECT * INTO initial FROM material_verification.commands WHERE id=(ctx#>>'{admission,document,program_command_row_id}')::uuid;
 SELECT * INTO original_case FROM material_verification.cases WHERE id=initial.case_id;
 SELECT convert_from(data,'UTF8')::jsonb INTO context FROM technical_material_store.objects WHERE sha=(ctx#>>'{seal,document,context_object_digest}')::design.sha256;
 SELECT jsonb_agg(value->'rule_id' ORDER BY ordinal) INTO rules FROM jsonb_array_elements(context->'rules') WITH ORDINALITY q(value,ordinal) WHERE value->>'selection'='include';
 at:=clock_timestamp();
 configuration:=coalesce(p.submit_login=session_user AND p.submit_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.job_sql_method_digest::text=material_judgment_job.native_method_digest()
  AND p.renewal_profile_id=rp.id AND p.renewal_profile_digest::text=ctx->>'profile_digest' AND p.origin=rp.origin
  AND p.submit_login NOT IN(r.actor,p.request_login,ctx#>>'{seal,document,recorded_by}',ctx#>>'{quote,document,recorded_by}',ctx#>>'{verification,document,recorded_by}',ctx#>>'{new_context,program_profile,target_login}')
  AND p.submit_login_oid NOT IN(r.actor_oid,p.request_login_oid,(ctx#>>'{seal,document,recorded_by_oid}')::oid,(ctx#>>'{quote,document,recorded_by_oid}')::oid,(ctx#>>'{verification,document,recorded_by_oid}')::oid,(ctx#>>'{new_context,program_profile,target_login_oid}')::oid),false);
 renewal_valid:=coalesce(rh.profile_id=rp.id AND rh.enabled AND rh.revision=r.profile_head_revision
  AND at>=rp.valid_from AND at<rp.valid_until AND rp.database_name=current_database()
  AND rp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND rp.renew_sql_method_digest::text=material_input_renewal.native_method_digest()
  AND r.actor=rp.renew_login AND r.actor_oid=rp.renew_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=r.actor_oid AND rolname=r.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(r.actor,'tender_material_input_renew',ARRAY['material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)','material_input_renewal.read(uuid,text)'])
  AND r.digest::text=encode(sha256(convert_to(design.package_canonical_json(r.document),'UTF8')),'hex')
  AND r.document->>'renew_method_digest'=rp.renew_method_digest::text AND r.document->>'native_sql_method_digest'=material_input_renewal.native_method_digest()
  AND ctx->'seal_current'='true'::jsonb AND ctx->'quote_current'='true'::jsonb AND ctx->'verification_current'='true'::jsonb
  AND r.document->>'seal_digest'=ctx#>>'{seal,digest}' AND r.document->>'quote_digest'=ctx#>>'{quote,digest}'
  AND r.document->>'current_verification_digest'=ctx#>>'{verification,digest}' AND r.document->>'profile_digest'=ctx->>'profile_digest'
  AND context->>'digest'=r.document->>'context_digest' AND rules=ctx#>'{quote,document,quote,rule_ids}'
  AND jsonb_array_length(rules) BETWEEN 1 AND 400,false);
 request_valid:=coalesce(initial.id IS NOT NULL AND original_case.id IS NOT NULL
  AND initial.actor=p.request_login AND (initial.document->>'recorded_by_oid')::oid=p.request_login_oid
  AND original_case.request_login=p.request_login AND original_case.request_login_oid=p.request_login_oid
  AND at>=original_case.valid_from AND at<original_case.valid_until
  AND EXISTS(SELECT FROM material_verification.case_heads ch WHERE ch.case_id=original_case.id AND ch.enabled AND ch.revision=(initial.document->>'case_head_revision')::bigint)
  AND EXISTS(SELECT FROM pg_roles WHERE oid=p.request_login_oid AND rolname=p.request_login AND rolcanlogin)
  AND scope_review_issuer.role_policy(p.request_login,'tender_material_verification_commands',ARRAY['material_verification.begin_command(uuid,uuid,text)','material_verification.read_command(uuid,uuid,text)'])
  AND initial.digest::text=ctx#>>'{admission,document,program_command_digest}'
  AND ctx#>>'{new_context,program_case,request_login}'=p.request_login::text
  AND (ctx#>>'{new_context,program_case,request_login_oid}')::oid=p.request_login_oid,false);
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'profile_head_revision',h.revision,'renewal',jsonb_build_object('document',r.document,'digest',r.digest::text),'renewal_context',ctx,
  'intent_command_id',initial.command_id::text,'intent_command_digest',initial.digest::text,'rule_ids',rules,
  'profile_current',configuration,'renewal_current',renewal_valid,'request_current',request_valid,
  'budget_sufficient',ctx#>'{quote,document,quote,budget_sufficient_under_policy}',
  'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
END;
$judgment_job_context$;

CREATE FUNCTION material_judgment_job.lock_inputs(target_renewal uuid)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_locks$
DECLARE r material_input_renewal.records;fresh material_input_authority.verifications;sealed material_input_seal.records;p material_input_renewal.profiles;
 s design.bid_package_technical_scopes;inventory design.bid_package_requirement_inventories;
BEGIN
 SELECT * INTO r FROM material_input_renewal.records WHERE id=target_renewal;
 SELECT * INTO fresh FROM material_input_authority.verifications WHERE id=r.verification_id;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=r.seal_id;
 SELECT * INTO p FROM material_input_renewal.profiles WHERE id=r.profile_id;
 PERFORM 1 FROM material_input_renewal.profile_heads WHERE renew_login=p.renew_login FOR SHARE;
 PERFORM 1 FROM material_cost_quote.policy_heads WHERE policy_id=(SELECT policy_id FROM material_cost_quote.quotes WHERE id=r.quote_id) FOR SHARE;
 PERFORM 1 FROM material_input_seal.profile_heads WHERE profile_id=sealed.profile_id FOR SHARE;
 PERFORM 1 FROM material_input_authority.policy_heads WHERE program_profile_id=(fresh.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.profile_heads WHERE profile_id=(fresh.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id IN((fresh.document->>'program_case_id')::uuid,
  (SELECT command.case_id FROM material_verification.commands command JOIN material_input_authority.verifications original ON (original.document->>'program_command_row_id')::uuid=command.id WHERE original.id=sealed.verification_id)) ORDER BY case_id FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE profile_id=(SELECT c.profile_id FROM scope_review_issuer.cases c JOIN scope_review_issuer.attestations a ON a.case_id=c.id WHERE a.id=(fresh.document->>'review_attestation_id')::uuid) FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=(SELECT case_id FROM scope_review_issuer.attestations WHERE id=(fresh.document->>'review_attestation_id')::uuid) FOR SHARE;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=sealed.scope_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
END;
$judgment_job_locks$;

CREATE FUNCTION material_judgment_job.start(target_renewal uuid,expected_renewal_digest text,target_profile uuid,expected_profile_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_start$
DECLARE old material_judgment_job.jobs;p material_judgment_job.profiles;r material_input_renewal.records;ctx jsonb;identifier uuid;event_id uuid;result jsonb;checksum text;event jsonb;
 slots jsonb:='[]'::jsonb;rule jsonb;ordinal integer:=0;slot integer;slot_id uuid;attempts integer;key text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION 'JUDGMENT_JOB_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_judgment_submit',ARRAY['material_judgment_job.start(uuid,text,uuid,text,uuid)','material_judgment_job.read(uuid,text)','material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)']) THEN RAISE EXCEPTION 'JUDGMENT_JOB_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 IF target_renewal IS NULL OR target_profile IS NULL OR command IS NULL THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 FOREACH key IN ARRAY ARRAY[expected_renewal_digest,expected_profile_digest] LOOP
  IF key IS NULL OR key !~ '^[0-9a-f]{64}$' OR key=repeat('0',64) THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 END LOOP;
 SELECT * INTO r FROM material_input_renewal.records WHERE id=target_renewal;
 IF r.id IS NULL THEN RAISE EXCEPTION 'JUDGMENT_JOB_NOT_FOUND' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(r.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_judgment_job:'||command::text,0));
 SELECT * INTO old FROM material_judgment_job.jobs WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.profile_id<>target_profile
   OR old.document->>'initial_renewal_id'<>target_renewal::text OR old.document->>'initial_renewal_digest'<>expected_renewal_digest
   OR old.document->>'profile_digest'<>expected_profile_digest THEN RAISE EXCEPTION 'JUDGMENT_JOB_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 IF EXISTS(SELECT FROM material_judgment_job.evidence_events WHERE command_id=command) THEN RAISE EXCEPTION 'JUDGMENT_JOB_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
 SELECT * INTO p FROM material_judgment_job.profiles WHERE id=target_profile;
 PERFORM 1 FROM material_judgment_job.profile_heads WHERE submit_login=p.submit_login FOR SHARE;
 PERFORM material_judgment_job.lock_inputs(target_renewal);
 ctx:=material_judgment_job.current_context(target_renewal,target_profile);
 IF ctx IS NULL OR ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest OR r.digest::text<>expected_renewal_digest THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 IF ctx->'profile_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'renewal_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'request_current' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'JUDGMENT_JOB_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 IF ctx->'budget_sufficient' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'JUDGMENT_JOB_BUDGET_INSUFFICIENT' USING ERRCODE='P0001';END IF;
 IF EXISTS(SELECT FROM material_judgment_job.jobs WHERE intent_command_id=(ctx->>'intent_command_id')::uuid) THEN RAISE EXCEPTION 'JUDGMENT_JOB_INTENT_ALREADY_REGISTERED' USING ERRCODE='P0001';END IF;
 identifier:=gen_random_uuid();event_id:=gen_random_uuid();attempts:=(ctx#>>'{renewal_context,quote,document,quote,max_attempts_per_slot}')::integer;
 FOR rule IN SELECT value FROM jsonb_array_elements(ctx->'rule_ids') LOOP
  ordinal:=ordinal+1;
  FOR slot IN 1..3 LOOP
   slot_id:=gen_random_uuid();slots:=slots||jsonb_build_array(jsonb_build_object('slot_id',slot_id::text,'rule_id',rule,'rule_ordinal',ordinal,'slot_number',slot,'max_attempts',attempts));
  END LOOP;
 END LOOP;
 result:=jsonb_build_object('version','material-judgment-job/1','job_id',identifier::text,'command_id',command::text,
  'intent_command_id',ctx->>'intent_command_id','intent_command_digest',ctx->>'intent_command_digest',
  'profile_id',p.id::text,'profile_digest',expected_profile_digest,'profile_head_revision',ctx->'profile_head_revision',
  'bid_id',r.bid_id::text,'scope_id',r.scope_id::text,'scope_digest',r.document->>'scope_digest',
  'seal_id',r.seal_id::text,'seal_digest',r.document->>'seal_digest','quote_id',r.quote_id::text,'quote_digest',r.document->>'quote_digest',
  'material_input_digest',r.document->>'material_input_digest','context_digest',r.document->>'context_digest','context_method_digest',r.document->>'context_method_digest','findings_digest',r.document->>'findings_digest',
  'initial_renewal_id',r.id::text,'initial_renewal_digest',r.digest::text,'initial_evidence_id',event_id::text,
  'rule_ids',ctx->'rule_ids','slots',slots,'required_valid_slots',jsonb_array_length(slots),'max_attempts_per_slot',attempts,
  'maximum_external_calls',jsonb_array_length(slots)*attempts,'currency',ctx#>>'{renewal_context,quote,document,quote,currency}',
  'required_reservation_minor',ctx#>'{renewal_context,quote,document,quote,required_reservation_minor}',
  'budget_ceiling_minor',ctx#>'{renewal_context,quote,document,quote,budget_ceiling_minor}',
  'origin',p.origin,'generation',1,'status','awaiting_budget_reservation','job_method_digest',p.job_method_digest::text,'native_sql_method_digest',material_judgment_job.native_method_digest(),
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'request_login',p.request_login::text,'request_login_oid',p.request_login_oid::bigint,
  'recorded_at',ctx->>'observed_at')||jsonb_build_object('software_job_registered',true,'native_binding_verified',true,
  'fee_ledger_reserved',false,'automatic_retry',false,'input_authority_granted',false,'execution_authorized',false,'send_lease_granted',false,
  'atomic_snapshot_verified',false,'actual_human_reading_verified',false,'model_context_fit_proven',false,'request_body_limit_verified',false,'account_price_confirmed',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_judgment_job.jobs VALUES(identifier,command,(ctx->>'intent_command_id')::uuid,p.id,(ctx->>'profile_head_revision')::bigint,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),r.bid_id,r.scope_id,r.seal_id,r.quote_id,result,checksum);
 INSERT INTO material_judgment_job.slots SELECT (v->>'slot_id')::uuid,identifier,(v->>'rule_id')::uuid,(v->>'rule_ordinal')::integer,(v->>'slot_number')::integer,attempts FROM jsonb_array_elements(slots) v;
 event:=jsonb_build_object('version','material-judgment-evidence/1','event_id',event_id::text,'job_id',identifier::text,'job_digest',checksum,'command_id',command::text,
  'revision',1,'previous_revision',0,'renewal_id',r.id::text,'renewal_digest',r.digest::text,'recorded_at',ctx->>'observed_at','recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user));
 INSERT INTO material_judgment_job.evidence_events VALUES(event_id,identifier,command,1,r.id,event,encode(sha256(convert_to(design.package_canonical_json(event),'UTF8')),'hex'));
 INSERT INTO material_judgment_job.evidence_heads VALUES(identifier,event_id,1);
 INSERT INTO material_judgment_job.outbox VALUES(gen_random_uuid(),identifier,'judgment_job_preparation_requested',jsonb_build_object('job_id',identifier::text,'generation',1));
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$judgment_job_start$;

CREATE FUNCTION material_judgment_job.refresh(target_job uuid,expected_job_digest text,target_renewal uuid,expected_renewal_digest text,expected_revision bigint,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_refresh$
DECLARE job material_judgment_job.jobs;old material_judgment_job.evidence_events;h material_judgment_job.evidence_heads;ctx jsonb;r material_input_renewal.records;identifier uuid;result jsonb;checksum text;key text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION 'JUDGMENT_JOB_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_judgment_submit',ARRAY['material_judgment_job.start(uuid,text,uuid,text,uuid)','material_judgment_job.read(uuid,text)','material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)']) THEN RAISE EXCEPTION 'JUDGMENT_JOB_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=target_job AND digest=expected_job_digest AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'JUDGMENT_JOB_NOT_FOUND' USING ERRCODE='P0001';END IF;
 IF command IS NULL OR target_renewal IS NULL OR expected_revision IS NULL OR expected_revision<1 THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_INVALID' USING ERRCODE='P0001';END IF;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(job.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_judgment_job:'||command::text,0));
 SELECT * INTO old FROM material_judgment_job.evidence_events WHERE command_id=command;
 IF FOUND THEN
  IF old.job_id<>job.id OR old.revision=1 OR old.renewal_id<>target_renewal OR old.document->>'renewal_digest' IS DISTINCT FROM expected_renewal_digest OR (old.document->>'previous_revision')::bigint<>expected_revision THEN RAISE EXCEPTION 'JUDGMENT_JOB_COMMAND_CONFLICT' USING ERRCODE='P0001';END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT * INTO h FROM material_judgment_job.evidence_heads WHERE job_id=job.id FOR UPDATE;
 IF h.revision<>expected_revision THEN RAISE EXCEPTION 'JUDGMENT_JOB_REVISION_CONFLICT' USING ERRCODE='P0001';END IF;
 SELECT * INTO r FROM material_input_renewal.records WHERE id=target_renewal AND digest=expected_renewal_digest;
 IF r.id IS NULL OR r.seal_id<>job.seal_id OR r.quote_id<>job.quote_id THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 IF r.id=(SELECT renewal_id FROM material_judgment_job.evidence_events WHERE id=h.event_id) THEN RAISE EXCEPTION 'JUDGMENT_JOB_NEW_EVIDENCE_REQUIRED' USING ERRCODE='P0001';END IF;
 PERFORM 1 FROM material_judgment_job.profile_heads WHERE profile_id=job.profile_id FOR SHARE;
 PERFORM material_judgment_job.lock_inputs(target_renewal);
 ctx:=material_judgment_job.current_context(target_renewal,job.profile_id);
 IF ctx IS NULL OR ctx->'profile_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'renewal_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'request_current' IS DISTINCT FROM 'true'::jsonb OR (ctx->>'profile_head_revision')::bigint<>job.profile_head_revision THEN RAISE EXCEPTION 'JUDGMENT_JOB_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001';END IF;
 FOREACH key IN ARRAY ARRAY['material_input_digest','context_digest','scope_digest','findings_digest','quote_digest','seal_digest'] LOOP
  IF r.document->key IS DISTINCT FROM job.document->key THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 END LOOP;
 IF ctx->>'intent_command_id'<>job.intent_command_id::text OR ctx->'rule_ids'<>job.document->'rule_ids' THEN RAISE EXCEPTION 'JUDGMENT_JOB_REFERENCE_MISMATCH' USING ERRCODE='P0001';END IF;
 identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','material-judgment-evidence/1','event_id',identifier::text,'job_id',job.id::text,'job_digest',job.digest::text,'command_id',command::text,
 'revision',h.revision+1,'previous_revision',h.revision,'renewal_id',r.id::text,'renewal_digest',r.digest::text,'recorded_at',ctx->>'observed_at','recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user));
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_judgment_job.evidence_events VALUES(identifier,job.id,command,h.revision+1,r.id,result,checksum);
 UPDATE material_judgment_job.evidence_heads SET event_id=identifier,revision=h.revision+1 WHERE job_id=job.id;
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$judgment_job_refresh$;

CREATE FUNCTION material_judgment_job.read(target_job uuid,expected_job_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_judgment_job,design,pg_temp SET TimeZone='UTC'
AS $judgment_job_read$
DECLARE job material_judgment_job.jobs;h material_judgment_job.evidence_heads;e material_judgment_job.evidence_events;ctx jsonb;slots jsonb;eligible boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN RAISE EXCEPTION 'JUDGMENT_JOB_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001';END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_judgment_submit',ARRAY['material_judgment_job.start(uuid,text,uuid,text,uuid)','material_judgment_job.read(uuid,text)','material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid)']) THEN RAISE EXCEPTION 'JUDGMENT_JOB_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';END IF;
 SELECT * INTO job FROM material_judgment_job.jobs WHERE id=target_job AND digest=expected_job_digest AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'JUDGMENT_JOB_NOT_FOUND' USING ERRCODE='P0001';END IF;
 SELECT * INTO h FROM material_judgment_job.evidence_heads WHERE job_id=job.id;
 SELECT * INTO e FROM material_judgment_job.evidence_events WHERE id=h.event_id AND job_id=job.id AND revision=h.revision;
 ctx:=material_judgment_job.current_context(e.renewal_id,job.profile_id);
 SELECT jsonb_agg(jsonb_build_object('slot_id',id::text,'rule_id',rule_id::text,'rule_ordinal',rule_ordinal,'slot_number',slot_number,'max_attempts',max_attempts) ORDER BY rule_ordinal,slot_number) INTO slots FROM material_judgment_job.slots WHERE job_id=job.id;
 eligible:=coalesce(ctx->'profile_current'='true'::jsonb AND ctx->'renewal_current'='true'::jsonb AND ctx->'request_current'='true'::jsonb
  AND (ctx->>'profile_head_revision')::bigint=job.profile_head_revision AND slots=job.document->'slots'
  AND ctx#>>'{renewal,digest}'=e.document->>'renewal_digest',false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',job.document,'digest',job.digest::text),
  'evidence',jsonb_build_object('document',e.document,'digest',e.digest::text),
  'current',jsonb_build_object('observed_at',ctx->>'observed_at','evidence_revision',h.revision,'profile_current',ctx->'profile_current','renewal_current',ctx->'renewal_current','request_current',ctx->'request_current',
   'slots_intact',coalesce(slots=job.document->'slots',false),'software_preparation_current',eligible,'software_budget_sufficient',eligible AND ctx->'budget_sufficient'='true'::jsonb,
   'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$judgment_job_read$;
REVOKE ALL ON FUNCTION material_judgment_job.native_method_digest(),material_judgment_job.current_context(uuid,uuid),material_judgment_job.lock_inputs(uuid),
 material_judgment_job.start(uuid,text,uuid,text,uuid),material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid),material_judgment_job.read(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_judgment_job TO tender_material_judgment_submit;
GRANT EXECUTE ON FUNCTION material_judgment_job.start(uuid,text,uuid,text,uuid),material_judgment_job.refresh(uuid,text,uuid,text,bigint,uuid),material_judgment_job.read(uuid,text) TO tender_material_judgment_submit;
COMMIT;
