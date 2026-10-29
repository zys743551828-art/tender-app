-- Optional fresh isolated initialization, never a default business capability.
BEGIN;
CREATE SCHEMA material_input_seal;
REVOKE ALL ON SCHEMA material_input_seal FROM PUBLIC;
CREATE ROLE tender_material_input_seal NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_input_seal.profiles(
 id uuid PRIMARY KEY,sealer_login name NOT NULL,sealer_login_oid oid NOT NULL,
 authority_policy_id uuid NOT NULL REFERENCES material_input_authority.policies(id),authority_policy_digest design.sha256 NOT NULL,
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 seal_method_digest design.sha256 NOT NULL,seal_sql_method_digest design.sha256 NOT NULL,
 input_method_digest design.sha256 NOT NULL,context_method_digest design.sha256 NOT NULL,store_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_input_seal.profile_heads(
 sealer_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_input_seal.profiles(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_input_seal.records(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,verification_id uuid NOT NULL REFERENCES material_input_authority.verifications(id),
 profile_id uuid NOT NULL REFERENCES material_input_seal.profiles(id),profile_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,scope_id uuid NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=32768),UNIQUE(verification_id,profile_id,profile_head_revision)
);
CREATE TRIGGER immutable_input_seal_profile BEFORE UPDATE OR DELETE ON material_input_seal.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_input_seal_record BEFORE UPDATE OR DELETE ON material_input_seal.records FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_input_seal.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_input_seal,design,pg_temp SET TimeZone='UTC'
AS $input_seal_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_input_seal.native_method_digest()','material_input_seal.current_context(uuid,uuid)',
  'material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)']) AS s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>4 THEN RETURN NULL; END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$input_seal_method$;
REVOKE ALL ON FUNCTION material_input_seal.native_method_digest() FROM PUBLIC;

CREATE FUNCTION material_input_seal.current_context(target_verification uuid,target_profile uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_input_seal,design,pg_temp SET TimeZone='UTC'
AS $input_seal_context$
DECLARE p material_input_seal.profiles;h material_input_seal.profile_heads;q material_input_authority.verifications;
 approved material_input_authority.policies;r material_registration.records;stored technical_material_store.records;
 ctx jsonb;at timestamptz;profile_hash text;verified boolean;storage_valid boolean;profile_valid boolean;ref jsonb;refs jsonb;keys text[];actual text[];
BEGIN
 SELECT * INTO p FROM material_input_seal.profiles WHERE id=target_profile;
 SELECT * INTO h FROM material_input_seal.profile_heads WHERE sealer_login=p.sealer_login;
 SELECT * INTO q FROM material_input_authority.verifications WHERE id=target_verification;
 SELECT * INTO approved FROM material_input_authority.policies WHERE id=q.policy_id;
 SELECT * INTO r FROM material_registration.records WHERE id=(q.document->>'registration_id')::uuid AND digest=q.document->>'registration_digest';
 SELECT * INTO stored FROM technical_material_store.records WHERE id=(r.document#>>'{packet,storage_record_id}')::uuid AND digest=r.document#>>'{packet,storage_record_digest}';
 IF p.id IS NULL OR q.id IS NULL OR approved.id IS NULL OR r.id IS NULL OR stored.id IS NULL THEN RETURN NULL; END IF;
 ctx:=material_input_authority.policy_context(q.program_result_id,q.policy_id);
 IF ctx IS NULL THEN RETURN NULL; END IF;
 at:=clock_timestamp();profile_hash:=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex');
 profile_valid:=coalesce(h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.sealer_login=session_user AND p.sealer_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND p.sealer_login NOT IN(approved.verifier_login,ctx#>>'{program_profile,target_login}',ctx#>>'{program_case,request_login}')
  AND p.sealer_login_oid NOT IN(approved.verifier_login_oid,(ctx#>>'{program_profile,target_login_oid}')::oid,(ctx#>>'{program_case,request_login_oid}')::oid),false);
 verified:=coalesce(p.authority_policy_id=q.policy_id AND p.authority_policy_digest::text=ctx->>'policy_digest'
  AND p.origin=q.document->>'origin' AND p.origin=approved.origin AND p.context_method_digest=approved.context_method_digest
  AND p.seal_sql_method_digest::text=material_input_seal.native_method_digest()
  AND q.digest::text=encode(sha256(convert_to(design.package_canonical_json(q.document),'UTF8')),'hex')
  AND q.document->>'version'='material-input-verification/1' AND q.document->>'verification_id'=q.id::text
  AND q.document->>'policy_id'=q.policy_id::text AND q.document->>'policy_digest'=ctx->>'policy_digest'
  AND q.document->>'verifier_method_digest'=approved.verifier_method_digest::text
  AND q.document->>'native_sql_method_digest'=material_input_authority.native_method_digest()
  AND q.document->>'program_result_id'=q.program_result_id::text AND q.document->>'program_result_digest'=ctx#>>'{program_result,digest}'
  AND q.actor=approved.verifier_login AND q.actor_oid=approved.verifier_login_oid
  AND q.document->>'recorded_by'=q.actor::text AND q.document->>'recorded_by_oid'=q.actor_oid::text
  AND EXISTS(SELECT FROM pg_roles WHERE oid=q.actor_oid AND rolname=q.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(q.actor,'tender_material_input_verify',ARRAY['material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)'])
  AND q.document->>'context_digest'=ctx#>>'{program_result,document,context_digest}'
  AND q.document->>'findings_digest'=ctx#>>'{program_result,document,findings_digest}'
  AND q.document->>'context_method_digest'=p.context_method_digest::text
  AND q.document->'software_input_verified'='true'::jsonb AND q.document->'native_binding_verified'='true'::jsonb
  AND q.document->'necessary_scope_policy_accepted'='true'::jsonb
  AND q.document->'input_authority_granted'=to_jsonb(p.origin='current_prebid')
  AND q.document->'input_verified'=to_jsonb(p.origin='current_prebid')
  AND q.document->'execution_authorized'='false'::jsonb
  AND (q.document->>'policy_head_revision')::bigint=(ctx->>'policy_head_revision')::bigint
  AND ctx->'policy_current'='true'::jsonb AND ctx->'program_current'='true'::jsonb AND ctx->'review_current'='true'::jsonb
  AND ctx->'source_current'='true'::jsonb AND ctx->'fingerprints_match'='true'::jsonb AND ctx->'complete_findings_confirmed'='true'::jsonb,false);
 storage_valid:=coalesce(stored.bid_id=q.bid_id AND stored.scope_id=q.scope_id
  AND stored.digest::text=encode(sha256(convert_to(design.package_canonical_json(stored.document),'UTF8')),'hex')
  AND stored.document->>'packet_digest'=r.document#>>'{packet,storage_packet_digest}'
  AND stored.document->>'packet_digest'=encode(sha256(convert_to(design.package_canonical_json(stored.document->'packet'),'UTF8')),'hex')
  AND stored.document#>>'{packet,store_method_digest}'=p.store_method_digest::text
  AND stored.document#>>'{packet,context_method_digest}'=p.context_method_digest::text
  AND stored.document#>>'{packet,context_digest}'=q.document->>'context_digest'
  AND stored.document#>>'{packet,findings_digest}'=q.document->>'findings_digest',false);
 refs:=jsonb_build_array(stored.document#>'{packet,context_object}',stored.document#>'{packet,source_observation_object}',
  stored.document#>'{packet,derivation_object}',stored.document#>'{packet,findings_object}')||(stored.document#>'{packet,image_objects}');
 SELECT array_agg(x ORDER BY x) INTO keys FROM(SELECT DISTINCT value->>'sha256' x FROM jsonb_array_elements(refs)) k;
 SELECT array_agg(object_sha::text ORDER BY object_sha) INTO actual FROM technical_material_store.record_objects WHERE record_id=stored.id;
 storage_valid:=storage_valid AND keys IS NOT NULL AND keys=actual;
 FOR ref IN SELECT value FROM jsonb_array_elements(refs) LOOP
  IF NOT EXISTS(SELECT FROM technical_material_store.objects WHERE sha=ref->>'sha256'
    AND octet_length(data)=(ref->>'byte_size')::bigint AND encode(sha256(data),'hex')=sha) THEN storage_valid:=false; END IF;
 END LOOP;
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',profile_hash,'profile_head_revision',h.revision,
  'verification',jsonb_build_object('document',q.document,'digest',q.digest::text),'verification_context',ctx,
  'storage',jsonb_build_object('document',stored.document,'digest',stored.digest::text),
  'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'profile_current',profile_valid,'verification_current',verified,'storage_current',storage_valid);
END;
$input_seal_context$;
REVOKE ALL ON FUNCTION material_input_seal.current_context(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION material_input_seal.seal(target_verification uuid,expected_verification_digest text,target_profile uuid,expected_profile_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_seal,design,pg_temp SET TimeZone='UTC'
AS $input_seal_write$
DECLARE old material_input_seal.records;q material_input_authority.verifications;p material_input_seal.profiles;
 ctx jsonb;qualified jsonb;stored jsonb;binding jsonb;input jsonb;result jsonb;checksum text;identifier uuid;revision bigint;real boolean;
 s design.bid_package_technical_scopes;inventory design.bid_package_requirement_inventories;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'INPUT_SEAL_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_seal',ARRAY['material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_SEAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_verification IS NULL OR target_profile IS NULL OR command IS NULL OR expected_verification_digest IS NULL OR expected_profile_digest IS NULL
  OR expected_verification_digest !~ '^[0-9a-f]{64}$' OR expected_profile_digest !~ '^[0-9a-f]{64}$'
  OR expected_verification_digest=repeat('0',64) OR expected_profile_digest=repeat('0',64) THEN
  RAISE EXCEPTION 'INPUT_SEAL_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT * INTO old FROM material_input_seal.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
   OR old.verification_id<>target_verification OR old.profile_id<>target_profile
   OR old.document->>'verification_digest' IS DISTINCT FROM expected_verification_digest
   OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'INPUT_SEAL_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT * INTO q FROM material_input_authority.verifications WHERE id=target_verification AND digest=expected_verification_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'INPUT_SEAL_VERIFICATION_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO p FROM material_input_seal.profiles WHERE id=target_profile;
 PERFORM pg_advisory_xact_lock(91143,1);
 PERFORM design.lock_worker_bid(q.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_input_seal:'||command::text,0));
 SELECT * INTO old FROM material_input_seal.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
   OR old.verification_id<>target_verification OR old.profile_id<>target_profile
   OR old.document->>'verification_digest' IS DISTINCT FROM expected_verification_digest
   OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'INPUT_SEAL_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 PERFORM 1 FROM material_input_seal.profile_heads WHERE sealer_login=p.sealer_login FOR SHARE;
 PERFORM 1 FROM material_input_authority.policy_heads WHERE program_profile_id=(q.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.profile_heads WHERE profile_id=(q.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id=(q.document->>'program_case_id')::uuid FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE profile_id=(SELECT c.profile_id FROM scope_review_issuer.cases c JOIN scope_review_issuer.attestations a ON a.case_id=c.id WHERE a.id=(q.document->>'review_attestation_id')::uuid) FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=(SELECT case_id FROM scope_review_issuer.attestations WHERE id=(q.document->>'review_attestation_id')::uuid) FOR SHARE;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=q.scope_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_seal',ARRAY['material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_SEAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 ctx:=material_input_seal.current_context(target_verification,target_profile);
 IF ctx IS NULL OR ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'INPUT_SEAL_PROFILE_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF ctx->'profile_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'verification_current' IS DISTINCT FROM 'true'::jsonb
  OR ctx->'storage_current' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'INPUT_SEAL_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 revision:=(ctx->>'profile_head_revision')::bigint;
 IF EXISTS(SELECT FROM material_input_seal.records WHERE verification_id=q.id AND profile_id=p.id AND profile_head_revision=revision) THEN
  RAISE EXCEPTION 'INPUT_SEAL_ALREADY_SEALED' USING ERRCODE='P0001'; END IF;
 qualified:=q.document;stored:=ctx#>'{storage,document}';identifier:=gen_random_uuid();real:=(p.origin='current_prebid');
 binding:=jsonb_build_object('version','package-technical-verification-binding/3','verification_id',q.id::text,
  'verification_receipt_digest',q.digest::text,'context_digest',qualified->>'context_digest','context_method_digest',p.context_method_digest::text);
 input:=jsonb_build_object('version','package-technical-material-input/3','context_digest',qualified->>'context_digest',
  'input_method_digest',p.input_method_digest::text,'binding_reference',binding,
  'binding_reference_digest',encode(sha256(convert_to(design.package_canonical_json(binding),'UTF8')),'hex'),
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false);
 input:=input||jsonb_build_object('digest',encode(sha256(convert_to(design.package_canonical_json(input),'UTF8')),'hex'));
 result:=jsonb_build_object('version','material-input-seal/1','seal_id',identifier::text,'command_id',command::text,
  'profile_id',p.id::text,'profile_digest',expected_profile_digest,'profile_head_revision',revision,
  'verification_id',q.id::text,'verification_digest',q.digest::text,'authority_policy_id',q.policy_id::text,
  'authority_policy_digest',qualified->>'policy_digest','authority_policy_revision',qualified->'policy_head_revision',
  'program_result_id',qualified->>'program_result_id','program_result_digest',qualified->>'program_result_digest',
  'registration_id',qualified->>'registration_id','registration_digest',qualified->>'registration_digest',
  'storage_record_id',stored->>'record_id','storage_record_digest',ctx#>>'{storage,digest}','storage_packet_digest',stored->>'packet_digest',
  'context_object_digest',stored#>>'{packet,context_object,sha256}','findings_object_digest',stored#>>'{packet,findings_object,sha256}',
  'context_digest',qualified->>'context_digest','context_method_digest',p.context_method_digest::text,
  'findings_digest',qualified->>'findings_digest','input_method_digest',p.input_method_digest::text,
  'material_input_digest',input->>'digest','material_input',input,'seal_method_digest',p.seal_method_digest::text,
  'native_sql_method_digest',material_input_seal.native_method_digest(),
  'bid_id',q.bid_id::text,'scope_id',q.scope_id::text,'scope_digest',qualified->>'scope_digest','origin',p.origin,
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'recorded_at',to_char(clock_timestamp(),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'status',CASE WHEN real THEN 'current_input_sealed' ELSE 'mechanism_input_sealed' END,
  'software_input_sealed',true,'native_binding_verified',true,'input_verified',real,'input_authority_granted',real,
  'execution_authorized',false,'raw_judgment_executable',false,'formal_prediction_eligible',false,'historical_sample_eligible',false,
  'actual_human_reading_verified',false,'atomic_snapshot_verified',false,'send_lease_granted',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_input_seal.records VALUES(identifier,command,q.id,p.id,revision,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),q.bid_id,q.scope_id,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$input_seal_write$;

CREATE FUNCTION material_input_seal.read(target_seal uuid,expected_seal_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_seal,design,pg_temp SET TimeZone='UTC'
AS $input_seal_read$
DECLARE old material_input_seal.records;ctx jsonb;eligible boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'INPUT_SEAL_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_seal',ARRAY['material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_SEAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO old FROM material_input_seal.records WHERE id=target_seal AND digest=expected_seal_digest
  AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'INPUT_SEAL_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 ctx:=material_input_seal.current_context(old.verification_id,old.profile_id);
 IF ctx IS NULL THEN RAISE EXCEPTION 'INPUT_SEAL_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 eligible:=coalesce(ctx->'profile_current'='true'::jsonb AND ctx->'verification_current'='true'::jsonb AND ctx->'storage_current'='true'::jsonb
  AND (ctx->>'profile_head_revision')::bigint=old.profile_head_revision,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',old.document,'digest',old.digest::text),
  'current',jsonb_build_object('observed_at',ctx->>'observed_at','profile_current',ctx->'profile_current',
   'verification_current',ctx->'verification_current','storage_current',ctx->'storage_current','profile_head_revision',ctx->'profile_head_revision',
   'software_input_current',eligible,'current_input_verified',eligible AND old.document->>'origin'='current_prebid',
   'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$input_seal_read$;
REVOKE ALL ON FUNCTION material_input_seal.seal(uuid,text,uuid,text,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_input_seal.read(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_input_seal TO tender_material_input_seal;
GRANT EXECUTE ON FUNCTION material_input_seal.seal(uuid,text,uuid,text,uuid),material_input_seal.read(uuid,text) TO tender_material_input_seal;
COMMIT;
