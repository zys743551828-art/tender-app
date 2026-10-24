-- Optional fresh isolated initialization; authenticates an issuer, not content truth.
BEGIN;
CREATE SCHEMA scope_review_issuer;
REVOKE ALL ON SCHEMA scope_review_issuer FROM PUBLIC;
CREATE ROLE tender_scope_review_issuer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_scope_review_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE scope_review_issuer.profiles(
 id uuid PRIMARY KEY, login_name name NOT NULL, subject_id uuid NOT NULL,
 issuer_kind text NOT NULL CHECK(issuer_kind IN('human','controlled_program','external_receipt')),
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 authority_policy_digest design.sha256 NOT NULL,
 findings_method_digest design.sha256 NOT NULL, store_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,
 CHECK(valid_from<valid_until)
);
CREATE TABLE scope_review_issuer.profile_heads(
 login_name name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES scope_review_issuer.profiles(id),
 revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE scope_review_issuer.cases(
 id uuid PRIMARY KEY,profile_id uuid NOT NULL REFERENCES scope_review_issuer.profiles(id),
 registration_id uuid NOT NULL REFERENCES material_registration.records(id),
 registration_digest design.sha256 NOT NULL,context_digest design.sha256 NOT NULL,review_digest design.sha256 NOT NULL,
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE scope_review_issuer.case_heads(
 case_id uuid PRIMARY KEY REFERENCES scope_review_issuer.cases(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE scope_review_issuer.attestations(
 id uuid PRIMARY KEY,case_id uuid NOT NULL REFERENCES scope_review_issuer.cases(id),
 command_id uuid NOT NULL UNIQUE,actor name NOT NULL,bid_id uuid NOT NULL,
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384)
);
CREATE TRIGGER immutable_scope_issuer_profile BEFORE UPDATE OR DELETE ON scope_review_issuer.profiles
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_scope_issuer_case BEFORE UPDATE OR DELETE ON scope_review_issuer.cases
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_scope_issuer_attestation BEFORE UPDATE OR DELETE ON scope_review_issuer.attestations
 FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION scope_review_issuer.role_policy(candidate name,expected_group text,allowed_calls text[])
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,scope_review_issuer,design,pg_temp
AS $scope_issuer_policy$
DECLARE memberships text[];
BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=candidate AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
  AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR pg_has_role(candidate,current_user,'MEMBER') THEN RETURN false; END IF;
 WITH RECURSIVE roles(id) AS(SELECT roleid FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=candidate)
  UNION SELECT a.roleid FROM pg_auth_members a JOIN roles r ON a.member=r.id)
 SELECT array_agg(rolname::text ORDER BY rolname) INTO memberships FROM roles JOIN pg_roles ON oid=roles.id;
 IF memberships IS DISTINCT FROM ARRAY[expected_group] THEN RETURN false; END IF;
 IF coalesce(cardinality(allowed_calls),0)=0 OR EXISTS(SELECT FROM unnest(allowed_calls) AS allowed(x) WHERE to_regprocedure(x) IS NULL) THEN RETURN false; END IF;
 IF has_database_privilege(candidate,current_database(),'CREATE') OR EXISTS(
  SELECT FROM pg_namespace n WHERE left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema'
  AND has_schema_privilege(candidate,n.oid,'CREATE')) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE left(n.nspname,3)<>'pg_'
  AND n.nspname<>'information_schema' AND t.relkind IN('r','p','v','m','f')
  AND(has_table_privilege(candidate,t.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
   OR has_any_column_privilege(candidate,t.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE left(n.nspname,3)<>'pg_'
  AND n.nspname<>'information_schema' AND CASE WHEN t.relkind='S' THEN has_sequence_privilege(candidate,t.oid,'SELECT,USAGE,UPDATE') ELSE false END) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prosecdef
  AND left(n.nspname,3)<>'pg_' AND n.nspname<>'information_schema' AND has_schema_privilege(candidate,n.oid,'USAGE')
  AND has_function_privilege(candidate,p.oid,'EXECUTE')
  AND p.oid<>ALL(ARRAY(SELECT to_regprocedure(x)::oid FROM unnest(allowed_calls) AS allowed(x) WHERE to_regprocedure(x) IS NOT NULL))) THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN undefined_object THEN RETURN false;
END;
$scope_issuer_policy$;

CREATE FUNCTION scope_review_issuer.attest(target_case uuid,command uuid,reference jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,scope_review_issuer,design,pg_temp SET TimeZone='UTC'
AS $scope_issuer_attest$
DECLARE old scope_review_issuer.attestations;p scope_review_issuer.profiles;h scope_review_issuer.profile_heads;
 c scope_review_issuer.cases;ch scope_review_issuer.case_heads;r material_registration.records;
 at timestamptz;identifier uuid;result jsonb;checksum text;item record;
BEGIN
 IF current_setting('transaction_read_only')<>'off' OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_scope_review_issuer',ARRAY['scope_review_issuer.attest(uuid,uuid,jsonb)']) THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_case IS NULL OR command IS NULL OR reference IS NULL OR jsonb_typeof(reference)<>'object'
 OR octet_length(reference::text)>4096 OR NOT design.package_json_keys(reference,ARRAY['version','context_digest','review_digest',
  'findings_digest','findings_commit_digest','findings_method_digest','findings_store_method_digest'])
 OR reference->>'version' IS DISTINCT FROM 'package-scope-review-attestation-reference/1' THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 FOR item IN SELECT key,value FROM jsonb_each(reference) WHERE key<>'version' LOOP
  IF jsonb_typeof(item.value)<>'string' OR item.value#>>'{}' !~ '^[0-9a-f]{64}$' OR item.value#>>'{}'=repeat('0',64) THEN
   RAISE EXCEPTION 'SCOPE_ISSUER_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 PERFORM pg_advisory_xact_lock(hashtextextended('scope_review_issuer:'||command::text,0));
 SELECT * INTO old FROM scope_review_issuer.attestations WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.case_id<>target_case OR old.document->'reference'<>reference THEN
   RAISE EXCEPTION 'SCOPE_ISSUER_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 at:=clock_timestamp();
 SELECT * INTO h FROM scope_review_issuer.profile_heads WHERE login_name=session_user;
 SELECT * INTO p FROM scope_review_issuer.profiles WHERE id=h.profile_id AND login_name=session_user;
 IF p.id IS NULL OR h.enabled IS DISTINCT FROM true OR at<p.valid_from OR at>=p.valid_until
 OR p.database_name<>current_database() OR p.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database()) THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_PROFILE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM scope_review_issuer.cases WHERE id=target_case AND profile_id=p.id;
 SELECT * INTO ch FROM scope_review_issuer.case_heads WHERE case_id=c.id;
 IF c.id IS NULL OR ch.enabled IS DISTINCT FROM true OR at<c.valid_from OR at>=c.valid_until THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_CASE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 IF r.id IS NULL OR r.document#>>'{packet,context_digest}' IS DISTINCT FROM c.context_digest::text
 OR reference->>'context_digest' IS DISTINCT FROM c.context_digest::text OR reference->>'review_digest' IS DISTINCT FROM c.review_digest::text
 OR reference->>'findings_method_digest' IS DISTINCT FROM p.findings_method_digest::text
 OR reference->>'findings_store_method_digest' IS DISTINCT FROM p.store_method_digest::text THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','package-native-scope-review-attestation/1','attestation_id',identifier::text,
  'case_id',c.id::text,'command_id',command::text,'profile_id',p.id::text,'subject_id',p.subject_id::text,
  'issuer_kind',p.issuer_kind,'issuer_origin',p.origin,'authority_policy_digest',p.authority_policy_digest::text,
  'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'case_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex'),
  'registration_id',r.id::text,'registration_digest',r.digest::text,'bid_id',r.bid_id::text,
  'scope_id',r.scope_id::text,'recorded_by',session_user::text,'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'reference',reference,'status','issuer_attestation_recorded','necessary_scope_verified',false,
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO scope_review_issuer.attestations(id,case_id,command_id,actor,bid_id,document,digest)
 VALUES(identifier,c.id,command,session_user,r.bid_id,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$scope_issuer_attest$;

CREATE FUNCTION scope_review_issuer.read(target_bid uuid,target_command uuid,expected_reference_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,scope_review_issuer,design,pg_temp SET TimeZone='UTC'
AS $scope_issuer_read$
DECLARE a scope_review_issuer.attestations;p scope_review_issuer.profiles;h scope_review_issuer.profile_heads;
 c scope_review_issuer.cases;ch scope_review_issuer.case_heads;r material_registration.records;at timestamptz;
 issuer_active boolean;case_active boolean;
BEGIN
 IF current_setting('transaction_read_only')<>'on' OR current_setting('transaction_isolation')<>'repeatable read' THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_scope_review_verify',ARRAY['scope_review_issuer.read(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE command_id=target_command AND bid_id=target_bid
  AND encode(sha256(convert_to(design.package_canonical_json(document->'reference'),'UTF8')),'hex')=expected_reference_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'SCOPE_ISSUER_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO p FROM scope_review_issuer.profiles WHERE id=c.profile_id;
 SELECT * INTO h FROM scope_review_issuer.profile_heads WHERE login_name=p.login_name;
 SELECT * INTO ch FROM scope_review_issuer.case_heads WHERE case_id=c.id;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 IF r.id IS NULL OR p.id::text IS DISTINCT FROM a.document->>'profile_id' OR p.login_name IS DISTINCT FROM a.actor
 OR encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') IS DISTINCT FROM a.document->>'profile_digest'
 OR encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex') IS DISTINCT FROM a.document->>'case_digest' THEN
  RAISE EXCEPTION 'SCOPE_ISSUER_REFERENCE_STATE_INVALID' USING ERRCODE='P0001'; END IF;
 at:=clock_timestamp();
 issuer_active:=coalesce(h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND scope_review_issuer.role_policy(p.login_name,'tender_scope_review_issuer',ARRAY['scope_review_issuer.attest(uuid,uuid,jsonb)']),false);
 case_active:=coalesce(ch.enabled AND at>=c.valid_from AND at<c.valid_until,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',a.document,'digest',a.digest::text),
  'current',jsonb_build_object('observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'issuer_active',issuer_active,'case_active',case_active,'profile_head_revision',h.revision,'case_head_revision',ch.revision,
   'configured_issuer_identity_verified',true,'current_business_sources_rechecked',false,'necessary_scope_verified',false,
   'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false));
END;
$scope_issuer_read$;
REVOKE ALL ON FUNCTION scope_review_issuer.role_policy(name,text,text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION scope_review_issuer.attest(uuid,uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION scope_review_issuer.read(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA scope_review_issuer TO tender_scope_review_issuer,tender_scope_review_verify;
GRANT EXECUTE ON FUNCTION scope_review_issuer.attest(uuid,uuid,jsonb) TO tender_scope_review_issuer;
GRANT EXECUTE ON FUNCTION scope_review_issuer.read(uuid,uuid,text) TO tender_scope_review_verify;
COMMIT;
