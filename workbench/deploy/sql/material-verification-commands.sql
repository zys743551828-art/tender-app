-- Optional fresh isolated initializer. Commands never grant input authority.
BEGIN;
CREATE SCHEMA material_verification;
REVOKE ALL ON SCHEMA material_verification FROM PUBLIC;
CREATE ROLE tender_material_verification_commands NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_verification.profiles(
 id uuid PRIMARY KEY,target_login name NOT NULL,target_login_oid oid NOT NULL,
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 controller_method_digest design.sha256 NOT NULL,authority_policy_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_verification.profile_heads(
 target_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_verification.profiles(id),
 revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_verification.cases(
 id uuid PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_verification.profiles(id),request_login name NOT NULL,request_login_oid oid NOT NULL,
 registration_id uuid NOT NULL REFERENCES material_registration.records(id),registration_digest design.sha256 NOT NULL,
 review_attestation_id uuid NOT NULL REFERENCES scope_review_issuer.attestations(id),review_attestation_digest design.sha256 NOT NULL,
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_verification.case_heads(
 case_id uuid PRIMARY KEY REFERENCES material_verification.cases(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_verification.commands(
 id uuid PRIMARY KEY,case_id uuid NOT NULL REFERENCES material_verification.cases(id),command_id uuid NOT NULL UNIQUE,
 actor name NOT NULL,bid_id uuid NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=16384)
);
CREATE TRIGGER immutable_verification_profile BEFORE UPDATE OR DELETE ON material_verification.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_verification_case BEFORE UPDATE OR DELETE ON material_verification.cases FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_verification_command BEFORE UPDATE OR DELETE ON material_verification.commands FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_verification.begin_command(target_case uuid,command uuid,expected_case_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_verification,design,pg_temp SET TimeZone='UTC'
AS $verification_command_begin$
DECLARE c material_verification.cases;p material_verification.profiles;h material_verification.profile_heads;
 ch material_verification.case_heads;r material_registration.records;a scope_review_issuer.attestations;
 rc scope_review_issuer.cases;rp scope_review_issuer.profiles;old material_verification.commands;
 at timestamptz;identifier uuid;result jsonb;checksum text;case_hash text;profile_hash text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_verification_commands',ARRAY['material_verification.begin_command(uuid,uuid,text)','material_verification.read_command(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_case IS NULL OR command IS NULL OR expected_case_digest IS NULL OR expected_case_digest !~ '^[0-9a-f]{64}$' OR expected_case_digest=repeat('0',64) THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('material_verification_command:'||command::text,0));
 SELECT * INTO old FROM material_verification.commands WHERE command_id=command;
 IF FOUND THEN
  IF old.case_id<>target_case OR old.actor<>session_user OR old.document->>'recorded_by_oid' IS DISTINCT FROM (SELECT oid::text FROM pg_roles WHERE rolname=session_user)
  OR old.document->>'case_digest' IS DISTINCT FROM expected_case_digest THEN
   RAISE EXCEPTION 'VERIFICATION_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 at:=clock_timestamp();
 SELECT * INTO c FROM material_verification.cases WHERE id=target_case AND request_login=session_user
  AND request_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 SELECT * INTO ch FROM material_verification.case_heads WHERE case_id=c.id;
 case_hash:=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex');
 IF c.id IS NULL OR ch.enabled IS DISTINCT FROM true OR at<c.valid_from OR at>=c.valid_until OR case_hash IS DISTINCT FROM expected_case_digest THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_CASE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO p FROM material_verification.profiles WHERE id=c.profile_id;
 SELECT * INTO h FROM material_verification.profile_heads WHERE target_login=p.target_login;
 IF p.id IS NULL OR p.target_login=session_user OR h.profile_id IS DISTINCT FROM p.id OR h.enabled IS DISTINCT FROM true OR at<p.valid_from OR at>=p.valid_until
 OR p.database_name<>current_database() OR p.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database())
 OR NOT EXISTS(SELECT FROM pg_roles WHERE oid=p.target_login_oid AND rolname=p.target_login AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR pg_has_role(p.target_login,current_user,'MEMBER') THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_PROFILE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE id=c.review_attestation_id AND digest=c.review_attestation_digest;
 SELECT * INTO rc FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO rp FROM scope_review_issuer.profiles WHERE id=rc.profile_id;
 IF r.id IS NULL OR a.id IS NULL OR r.document->>'version' IS DISTINCT FROM 'package-native-material-registration/2'
 OR a.document->>'version' IS DISTINCT FROM 'package-native-evidence-attestation/2'
 OR a.document->>'registration_id' IS DISTINCT FROM r.id::text OR a.document->>'registration_digest' IS DISTINCT FROM r.digest::text
 OR a.bid_id IS DISTINCT FROM r.bid_id OR a.document->>'scope_id' IS DISTINCT FROM r.scope_id::text
 OR NOT EXISTS(SELECT FROM scope_review_issuer.profile_heads WHERE login_name=rp.login_name AND profile_id=rp.id AND enabled)
 OR NOT EXISTS(SELECT FROM scope_review_issuer.case_heads WHERE case_id=rc.id AND enabled)
 OR at<rp.valid_from OR at>=rp.valid_until OR at<rc.valid_from OR at>=rc.valid_until
 OR rp.database_name<>current_database() OR rp.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database())
 OR NOT scope_review_issuer.role_policy(rp.login_name,'tender_native_evidence_issuer',ARRAY['scope_review_issuer.attest_native(uuid,uuid,jsonb)']) THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_REVIEW_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 IF NOT EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=r.bid_id AND archived_at IS NULL AND phase NOT IN('submitted','closed','terminated'))
 OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=r.bid_id) THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_NOT_CURRENT_PREBID' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();
 profile_hash:=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex');
 result:=jsonb_build_object('version','material-verification-command/1','record_id',identifier::text,'case_id',c.id::text,
  'case_digest',case_hash,'profile_id',p.id::text,'profile_digest',profile_hash,'command_id',command::text,
  'bid_id',r.bid_id::text,'scope_id',r.scope_id::text,'scope_digest',r.document->>'scope_digest',
  'context_digest',r.document#>>'{packet,context_digest}','registration_id',r.id::text,'registration_digest',r.digest::text,
  'review_attestation_id',a.id::text,'review_attestation_digest',a.digest::text,
  'target_login',p.target_login::text,'target_login_oid',p.target_login_oid::bigint,'origin',p.origin,
  'controller_method_digest',p.controller_method_digest::text,'authority_policy_digest',p.authority_policy_digest::text,
  'profile_head_revision',h.revision,'case_head_revision',ch.revision,
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'status','pending_controlled_verification','controlled_program_executed',false,'necessary_scope_verified',false,
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_verification.commands VALUES(identifier,c.id,command,session_user,r.bid_id,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$verification_command_begin$;

CREATE FUNCTION material_verification.read_command(target_case uuid,target_command uuid,expected_case_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_verification,design,pg_temp SET TimeZone='UTC'
AS $verification_command_read$
DECLARE stored material_verification.commands;c material_verification.cases;p material_verification.profiles;
 h material_verification.profile_heads;ch material_verification.case_heads;at timestamptz;active boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_verification_commands',ARRAY['material_verification.begin_command(uuid,uuid,text)','material_verification.read_command(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'VERIFICATION_COMMAND_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM material_verification.commands WHERE case_id=target_case AND command_id=target_command AND actor=session_user
  AND document->>'recorded_by_oid'=(SELECT oid::text FROM pg_roles WHERE rolname=session_user)
  AND document->>'case_digest'=expected_case_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'VERIFICATION_COMMAND_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM material_verification.cases WHERE id=stored.case_id;
 SELECT * INTO p FROM material_verification.profiles WHERE id=c.profile_id;
 SELECT * INTO h FROM material_verification.profile_heads WHERE target_login=p.target_login;
 SELECT * INTO ch FROM material_verification.case_heads WHERE case_id=c.id;
 at:=clock_timestamp();
 active:=coalesce(h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND EXISTS(SELECT FROM pg_roles WHERE oid=p.target_login_oid AND rolname=p.target_login AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
  AND NOT pg_has_role(p.target_login,current_user,'MEMBER'),false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',stored.document,'digest',stored.digest::text),
  'current',jsonb_build_object('observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'program_configuration_active',active,'case_active',coalesce(ch.enabled AND at>=c.valid_from AND at<c.valid_until,false),
  'profile_head_revision',h.revision,'case_head_revision',ch.revision,
  'program_runtime_authenticated',false,'controlled_program_executed',false,'necessary_scope_verified',false,
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false));
END;
$verification_command_read$;
REVOKE ALL ON FUNCTION material_verification.begin_command(uuid,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_verification.read_command(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_verification TO tender_material_verification_commands;
GRANT EXECUTE ON FUNCTION material_verification.begin_command(uuid,uuid,text),material_verification.read_command(uuid,uuid,text) TO tender_material_verification_commands;
COMMIT;
