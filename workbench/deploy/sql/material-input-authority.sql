-- Optional fresh isolated initialization. Verifier is separate from producer.
BEGIN;
CREATE SCHEMA material_input_authority;
REVOKE ALL ON SCHEMA material_input_authority FROM PUBLIC;
CREATE ROLE tender_material_input_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_input_authority.policies(
 id uuid PRIMARY KEY,verifier_login name NOT NULL,verifier_login_oid oid NOT NULL,
 program_profile_id uuid NOT NULL REFERENCES material_verification.profiles(id),
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 verifier_method_digest design.sha256 NOT NULL,verifier_sql_method_digest design.sha256 NOT NULL,program_port_method_digest design.sha256 NOT NULL,
 program_method_digest design.sha256 NOT NULL,program_policy_digest design.sha256 NOT NULL,
 controller_method_digest design.sha256 NOT NULL,current_review_method_digest design.sha256 NOT NULL,
 context_derivation_method_digest design.sha256 NOT NULL,context_method_digest design.sha256 NOT NULL,
 findings_method_digest design.sha256 NOT NULL,renderer_image_id text NOT NULL CHECK(renderer_image_id~'^sha256:[0-9a-f]{64}$'),
 renderer_source_digest design.sha256 NOT NULL,review_issuer_kind text NOT NULL CHECK(review_issuer_kind IN('human','controlled_program','external_receipt')),
 database_oid oid NOT NULL,database_name text NOT NULL,max_program_age_seconds integer NOT NULL CHECK(max_program_age_seconds BETWEEN 1 AND 120),
 valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_input_authority.policy_heads(
 program_profile_id uuid PRIMARY KEY REFERENCES material_verification.profiles(id),policy_id uuid NOT NULL REFERENCES material_input_authority.policies(id),
 revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_input_authority.verifications(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,program_result_id uuid NOT NULL REFERENCES material_verification.program_results(id),
 policy_id uuid NOT NULL REFERENCES material_input_authority.policies(id),policy_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,scope_id uuid NOT NULL,
 document jsonb NOT NULL,digest design.sha256 NOT NULL,CHECK(octet_length(document::text)<=16384),
 UNIQUE(program_result_id,policy_id,policy_head_revision)
);
CREATE TRIGGER immutable_input_policy BEFORE UPDATE OR DELETE ON material_input_authority.policies FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_input_verification BEFORE UPDATE OR DELETE ON material_input_authority.verifications FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_input_authority.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_input_authority,design,pg_temp SET TimeZone='UTC'
AS $input_authority_method$
DECLARE descriptor jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,descriptor FROM unnest(ARRAY['material_input_authority.native_method_digest()',
  'material_input_authority.source_current(uuid,uuid,text)','material_input_authority.policy_context(uuid,uuid)',
  'material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)']) AS s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>5 THEN RETURN NULL; END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(descriptor),'UTF8')),'hex');
END;
$input_authority_method$;
REVOKE ALL ON FUNCTION material_input_authority.native_method_digest() FROM PUBLIC;

CREATE FUNCTION material_input_authority.source_current(target_bid uuid,target_scope uuid,expected_scope text)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_input_authority,design,pg_temp SET TimeZone='UTC'
AS $input_authority_source$
DECLARE s design.bid_package_technical_scopes;own design.bid_package_revisions;authority design.bid_package_revisions;
 inventory design.bid_package_requirement_inventories;
BEGIN
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=target_scope AND bid_id=target_bid AND digest=expected_scope;
 SELECT * INTO own FROM design.bid_package_revisions WHERE id=s.revision_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 SELECT * INTO authority FROM design.bid_package_revisions WHERE id=inventory.authority_revision_id;
 RETURN coalesce(s.id IS NOT NULL AND own.id IS NOT NULL AND inventory.id IS NOT NULL AND authority.id IS NOT NULL
  AND design.package_technical_digest(s.manifest)=expected_scope
  AND EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=target_bid AND archived_at IS NULL AND phase NOT IN('submitted','closed','terminated') AND current_rule_set_id=inventory.rule_set_id)
  AND NOT EXISTS(SELECT FROM design.submission_heads WHERE bid_id=target_bid)
  AND own.identity_digest::text=design.identity_snapshot_v2(target_bid)->>'digest'
  AND design.identity_snapshot_v2(target_bid)->>'binding_status'='confirmed' AND authority.identity_digest=own.identity_digest
  AND EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=own.package_id AND revision_id=own.id AND digest=own.digest)
  AND EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=authority.package_id AND revision_id=authority.id AND digest=authority.digest)
  AND EXISTS(SELECT FROM design.bid_package_requirement_heads WHERE target_revision_id=own.id AND inventory_id=inventory.id AND digest=inventory.digest)
  AND inventory.manifest->'source_snapshot'=design.bid_requirement_source_snapshot(own.id,authority.id),false);
END;
$input_authority_source$;
REVOKE ALL ON FUNCTION material_input_authority.source_current(uuid,uuid,text) FROM PUBLIC;

CREATE FUNCTION material_input_authority.policy_context(target_result uuid,target_policy uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_input_authority,design,pg_temp SET TimeZone='UTC'
AS $input_authority_context$
DECLARE p material_input_authority.policies;h material_input_authority.policy_heads;done material_verification.program_results;
 task material_verification.commands;c material_verification.cases;pp material_verification.profiles;
 ph material_verification.profile_heads;ch material_verification.case_heads;r material_registration.records;
 a scope_review_issuer.attestations;rc scope_review_issuer.cases;rp scope_review_issuer.profiles;
 rh scope_review_issuer.profile_heads;rch scope_review_issuer.case_heads;stored technical_material_store.records;
 report jsonb;capsule jsonb;live jsonb;at timestamptz;policy_hash text;fingerprints boolean;program_active boolean;review_active boolean;
BEGIN
 SELECT * INTO p FROM material_input_authority.policies WHERE id=target_policy;
 SELECT * INTO h FROM material_input_authority.policy_heads WHERE program_profile_id=p.program_profile_id;
 SELECT * INTO done FROM material_verification.program_results WHERE id=target_result;
 SELECT * INTO task FROM material_verification.commands WHERE id=done.command_row_id;
 SELECT * INTO c FROM material_verification.cases WHERE id=task.case_id;
 SELECT * INTO pp FROM material_verification.profiles WHERE id=c.profile_id;
 SELECT * INTO ph FROM material_verification.profile_heads WHERE target_login=pp.target_login;
 SELECT * INTO ch FROM material_verification.case_heads WHERE case_id=c.id;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE id=c.review_attestation_id AND digest=c.review_attestation_digest;
 SELECT * INTO rc FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO rp FROM scope_review_issuer.profiles WHERE id=rc.profile_id;
 SELECT * INTO rh FROM scope_review_issuer.profile_heads WHERE login_name=rp.login_name;
 SELECT * INTO rch FROM scope_review_issuer.case_heads WHERE case_id=rc.id;
 SELECT * INTO stored FROM technical_material_store.records WHERE id=(r.document#>>'{packet,storage_record_id}')::uuid AND digest=r.document#>>'{packet,storage_record_digest}';
 BEGIN
  SELECT convert_from(data,'UTF8')::jsonb INTO report FROM technical_material_store.objects WHERE sha=stored.document#>>'{packet,findings_object,sha256}';
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN RETURN NULL;
 END;
 IF p.id IS NULL OR done.id IS NULL OR task.id IS NULL OR c.id IS NULL OR pp.id IS NULL OR r.id IS NULL OR a.id IS NULL OR report IS NULL THEN RETURN NULL; END IF;
 at:=clock_timestamp();policy_hash:=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex');
 capsule:=done.observation->'verified_material';live:=capsule->'live_derivation';
 fingerprints:=coalesce(p.verifier_sql_method_digest::text=material_input_authority.native_method_digest()
  AND p.program_profile_id=pp.id AND p.origin=pp.origin AND pp.origin=done.document->>'origin'
  AND done.digest::text=encode(sha256(convert_to(design.package_canonical_json(done.document),'UTF8')),'hex')
  AND done.document->>'observation_digest'=done.observation->>'digest'
  AND done.observation->>'digest'=encode(sha256(convert_to(design.package_canonical_json(done.observation-'digest'),'UTF8')),'hex')
  AND done.document->>'version'='material-verification-program-result/1' AND done.document->'program_runtime_authenticated'='true'::jsonb
  AND done.document->>'command_row_id'=task.id::text AND done.document->>'command_digest'=task.digest::text
  AND done.bid_id=task.bid_id AND done.document->>'bid_id'=task.bid_id::text
  AND done.document->>'scope_id'=task.document->>'scope_id' AND done.document->>'scope_digest'=task.document->>'scope_digest'
  AND done.document->>'profile_id'=pp.id::text AND done.document->>'case_id'=c.id::text
  AND done.actor=pp.target_login AND done.actor_oid=pp.target_login_oid AND done.document->>'recorded_by'=done.actor::text
  AND done.document->>'recorded_by_oid'=done.actor_oid::text
  AND done.document->>'registration_id'=r.id::text AND done.document->>'registration_digest'=r.digest::text
  AND done.document->>'review_attestation_id'=a.id::text AND done.document->>'review_attestation_digest'=a.digest::text
  AND done.document->>'context_digest'=r.document#>>'{packet,context_digest}'
  AND done.document->>'findings_digest'=report->>'digest' AND report->>'digest'=r.document#>>'{packet,findings_digest}'
  AND capsule->>'context_digest'=done.document->>'context_digest' AND capsule->>'findings_digest'=report->>'digest'
  AND report->>'context_digest'=done.document->>'context_digest' AND live->>'context_digest'=done.document->>'context_digest'
  AND p.program_port_method_digest::text=done.document->>'port_method_digest'
  AND p.program_method_digest::text=done.document->>'program_method_digest'
  AND p.program_policy_digest=pp.authority_policy_digest AND p.program_policy_digest::text=done.document->>'policy_digest'
  AND p.controller_method_digest=pp.controller_method_digest AND p.controller_method_digest::text=done.document->>'controller_method_digest'
  AND p.controller_method_digest::text=capsule->>'method_digest'
  AND p.current_review_method_digest::text=capsule#>>'{initial_current_review,method_digest}'
  AND p.current_review_method_digest::text=capsule#>>'{final_current_review,method_digest}'
  AND p.context_derivation_method_digest::text=live->>'method_digest'
  AND p.context_method_digest::text=live->>'context_method_digest'
  AND p.context_method_digest::text=r.document#>>'{packet,context_method_digest}'
  AND p.findings_method_digest::text=report->>'method_digest' AND p.findings_method_digest=rp.findings_method_digest
  AND p.renderer_image_id=live#>>'{runtime,image_id}' AND p.renderer_source_digest::text=live#>>'{runtime,source_digest}'
  AND p.review_issuer_kind=rp.issuer_kind AND rp.origin=p.origin
  AND ((p.origin='synthetic_mechanism' AND done.observation->>'byte_profile'='development_s3') OR (p.origin='current_prebid' AND done.observation->>'byte_profile'='oss_hangzhou')),false);
 program_active:=coalesce(at>=(done.document->>'recorded_at')::timestamptz-interval '5 seconds'
  AND at<(done.document->>'recorded_at')::timestamptz+make_interval(secs=>p.max_program_age_seconds)
  AND ph.profile_id=pp.id AND ph.enabled AND ph.revision::text=task.document->>'profile_head_revision'
  AND ch.enabled AND ch.revision::text=task.document->>'case_head_revision' AND at>=pp.valid_from AND at<pp.valid_until
  AND at>=c.valid_from AND at<c.valid_until AND pp.database_name=current_database()
  AND pp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND EXISTS(SELECT FROM pg_roles WHERE oid=pp.target_login_oid AND rolname=pp.target_login AND rolcanlogin)
  AND scope_review_issuer.role_policy(pp.target_login,'tender_material_verification_program',ARRAY['material_verification.program_context(uuid,text)','material_verification.record_program_result(uuid,text,jsonb)'])
  AND EXISTS(SELECT FROM pg_roles WHERE oid=c.request_login_oid AND rolname=c.request_login AND rolcanlogin)
  AND scope_review_issuer.role_policy(c.request_login,'tender_material_verification_commands',ARRAY['material_verification.begin_command(uuid,uuid,text)','material_verification.read_command(uuid,uuid,text)']),false);
 review_active:=coalesce(rh.profile_id=rp.id AND rh.enabled AND rch.enabled AND at>=rc.valid_from AND at<rc.valid_until
  AND at>=rp.valid_from AND at<rp.valid_until AND rp.database_name=current_database()
  AND rp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND scope_review_issuer.role_policy(rp.login_name,'tender_native_evidence_issuer',ARRAY['scope_review_issuer.attest_native(uuid,uuid,jsonb)']),false);
 review_active:=review_active AND coalesce(rh.revision::text=capsule#>>'{final_current_review,issuer_after,current,profile_head_revision}'
  AND rch.revision::text=capsule#>>'{final_current_review,issuer_after,current,case_head_revision}',false);
 RETURN jsonb_build_object('policy',to_jsonb(p),'policy_digest',policy_hash,'policy_head_revision',h.revision,
  'program_result',jsonb_build_object('document',done.document,'digest',done.digest::text),'command',task.document,
  'program_case',to_jsonb(c),'program_profile',to_jsonb(pp),'review_case',to_jsonb(rc),'review_profile',to_jsonb(rp),
  'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'verifier_identity_matches',coalesce(p.verifier_login=session_user AND p.verifier_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user),false),
  'policy_current',coalesce(h.policy_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until AND p.database_name=current_database()
    AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database()),false),
  'program_current',program_active,'review_current',review_active,'fingerprints_match',fingerprints,
  'complete_findings_confirmed',coalesce(report->'all_findings_claimed_confirmed'='true'::jsonb AND report->'scope_changes_requested'='false'::jsonb,false),
  'source_current',material_input_authority.source_current(task.bid_id,(task.document->>'scope_id')::uuid,task.document->>'scope_digest'));
END;
$input_authority_context$;
REVOKE ALL ON FUNCTION material_input_authority.policy_context(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION material_input_authority.qualify(target_result uuid,expected_result_digest text,target_policy uuid,expected_policy_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_authority,design,pg_temp SET TimeZone='UTC'
AS $input_authority_qualify$
DECLARE ctx jsonb;p material_input_authority.policies;done material_verification.program_results;
 task material_verification.commands;c material_verification.cases;pp material_verification.profiles;
 a scope_review_issuer.attestations;rc scope_review_issuer.cases;rp scope_review_issuer.profiles;
 s design.bid_package_technical_scopes;inventory design.bid_package_requirement_inventories;
 old material_input_authority.verifications;identifier uuid;result jsonb;checksum text;at timestamptz;is_current boolean;revision bigint;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_verify',ARRAY['material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_result IS NULL OR target_policy IS NULL OR command IS NULL OR expected_result_digest IS NULL OR expected_policy_digest IS NULL
 OR expected_result_digest !~ '^[0-9a-f]{64}$' OR expected_policy_digest !~ '^[0-9a-f]{64}$'
 OR expected_result_digest=repeat('0',64) OR expected_policy_digest=repeat('0',64) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT * INTO old FROM material_input_authority.verifications WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
  OR old.program_result_id<>target_result OR old.policy_id<>target_policy
  OR old.document->>'program_result_digest' IS DISTINCT FROM expected_result_digest OR old.document->>'policy_digest' IS DISTINCT FROM expected_policy_digest THEN
   RAISE EXCEPTION 'INPUT_AUTHORITY_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT * INTO done FROM material_verification.program_results WHERE id=target_result AND digest=expected_result_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'INPUT_AUTHORITY_PROGRAM_RESULT_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO p FROM material_input_authority.policies WHERE id=target_policy;
 SELECT * INTO task FROM material_verification.commands WHERE id=done.command_row_id;
 SELECT * INTO c FROM material_verification.cases WHERE id=task.case_id;
 SELECT * INTO pp FROM material_verification.profiles WHERE id=c.profile_id;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE id=c.review_attestation_id;
 SELECT * INTO rc FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO rp FROM scope_review_issuer.profiles WHERE id=rc.profile_id;
 PERFORM pg_advisory_xact_lock(91143,1);
 PERFORM design.lock_worker_bid(task.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_input_authority:'||command::text,0));
 SELECT * INTO old FROM material_input_authority.verifications WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
  OR old.program_result_id<>target_result OR old.policy_id<>target_policy
  OR old.document->>'program_result_digest' IS DISTINCT FROM expected_result_digest OR old.document->>'policy_digest' IS DISTINCT FROM expected_policy_digest THEN
   RAISE EXCEPTION 'INPUT_AUTHORITY_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 PERFORM 1 FROM material_input_authority.policy_heads WHERE program_profile_id=p.program_profile_id FOR SHARE;
 PERFORM 1 FROM material_verification.profile_heads WHERE target_login=pp.target_login FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id=c.id FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE login_name=rp.login_name FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=rc.id FOR SHARE;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=(task.document->>'scope_id')::uuid;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_verify',ARRAY['material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 ctx:=material_input_authority.policy_context(target_result,target_policy);
 IF ctx IS NULL OR ctx->>'policy_digest' IS DISTINCT FROM expected_policy_digest THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_POLICY_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF ctx->'verifier_identity_matches' IS DISTINCT FROM 'true'::jsonb
 OR p.verifier_login IN(pp.target_login,c.request_login) OR p.verifier_login_oid IN(pp.target_login_oid,c.request_login_oid) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_VERIFIER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 IF ctx->'policy_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'program_current' IS DISTINCT FROM 'true'::jsonb
 OR ctx->'review_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'source_current' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 IF ctx->'fingerprints_match' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_APPROVED_METHOD_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF ctx->'complete_findings_confirmed' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_REVIEW_INCOMPLETE' USING ERRCODE='P0001'; END IF;
 revision:=(ctx->>'policy_head_revision')::bigint;
 IF EXISTS(SELECT FROM material_input_authority.verifications WHERE program_result_id=target_result AND policy_id=target_policy AND policy_head_revision=revision) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_ALREADY_VERIFIED' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();at:=clock_timestamp();is_current:=(p.origin='current_prebid');
 result:=jsonb_build_object('version','material-input-verification/1','verification_id',identifier::text,'command_id',command::text,
  'program_result_id',done.id::text,'program_result_digest',done.digest::text,'policy_id',p.id::text,'policy_digest',expected_policy_digest,
  'policy_head_revision',revision,'origin',p.origin,'bid_id',task.bid_id::text,'scope_id',task.document->>'scope_id',
  'scope_digest',task.document->>'scope_digest','context_digest',done.document->>'context_digest','context_method_digest',p.context_method_digest::text,
  'findings_digest',done.document->>'findings_digest','program_profile_id',pp.id::text,'program_case_id',c.id::text,
  'program_command_row_id',task.id::text,'program_command_digest',task.digest::text,'registration_id',task.document->>'registration_id',
  'registration_digest',task.document->>'registration_digest','review_attestation_id',a.id::text,'review_attestation_digest',a.digest::text,
  'verifier_method_digest',p.verifier_method_digest::text,'native_sql_method_digest',material_input_authority.native_method_digest(),
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'status',CASE WHEN is_current THEN 'current_input_verified' ELSE 'mechanism_input_verified' END,
  'software_input_verified',true,'necessary_scope_policy_accepted',true,'native_binding_verified',true,
  'necessary_scope_verified',is_current,'input_verified',is_current,'input_authority_granted',is_current,
  'execution_authorized',false,'raw_judgment_executable',false,'uncalibrated_numeric_eligible',false,'formal_prediction_eligible',false,
  'historical_sample_eligible',false,'actual_human_reading_verified',false,'historical_existence_verified',false,'atomic_snapshot_verified',false,'send_lease_granted',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_input_authority.verifications VALUES(identifier,command,done.id,p.id,revision,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),task.bid_id,(task.document->>'scope_id')::uuid,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$input_authority_qualify$;

CREATE FUNCTION material_input_authority.read(target_verification uuid,expected_verification_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_authority,design,pg_temp SET TimeZone='UTC'
AS $input_authority_read$
DECLARE stored material_input_authority.verifications;ctx jsonb;eligible boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_verify',ARRAY['material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM material_input_authority.verifications WHERE id=target_verification AND digest=expected_verification_digest
  AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'INPUT_AUTHORITY_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 ctx:=material_input_authority.policy_context(stored.program_result_id,stored.policy_id);
 IF ctx IS NULL OR ctx->'verifier_identity_matches' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'INPUT_AUTHORITY_VERIFIER_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 eligible:=coalesce(ctx->'policy_current'='true'::jsonb AND ctx->'program_current'='true'::jsonb AND ctx->'review_current'='true'::jsonb
  AND ctx->'source_current'='true'::jsonb AND ctx->'fingerprints_match'='true'::jsonb AND ctx->'complete_findings_confirmed'='true'::jsonb
  AND (ctx->>'policy_head_revision')::bigint=stored.policy_head_revision,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',stored.document,'digest',stored.digest::text),
  'current',jsonb_build_object('observed_at',ctx->>'observed_at','policy_current',ctx->'policy_current','program_current',ctx->'program_current',
   'review_current',ctx->'review_current','source_current',ctx->'source_current','fingerprints_match',ctx->'fingerprints_match',
   'complete_findings_confirmed',ctx->'complete_findings_confirmed','policy_head_revision',ctx->'policy_head_revision',
   'software_input_current',eligible,'current_input_verified',eligible AND stored.document->>'origin'='current_prebid',
   'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$input_authority_read$;
REVOKE ALL ON FUNCTION material_input_authority.qualify(uuid,text,uuid,text,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_input_authority.read(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_input_authority TO tender_material_input_verify;
GRANT EXECUTE ON FUNCTION material_input_authority.qualify(uuid,text,uuid,text,uuid),material_input_authority.read(uuid,text) TO tender_material_input_verify;
COMMIT;
