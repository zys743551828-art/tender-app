-- Optional fresh isolated initialization. Renew evidence, never rewrite input.
BEGIN;
CREATE SCHEMA material_input_renewal;
REVOKE ALL ON SCHEMA material_input_renewal FROM PUBLIC;
CREATE ROLE tender_material_input_renew NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_input_renewal.profiles(
 id uuid PRIMARY KEY,renew_login name NOT NULL,renew_login_oid oid NOT NULL,
 quote_policy_id uuid NOT NULL REFERENCES material_cost_quote.policies(id),quote_policy_digest design.sha256 NOT NULL,
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 renew_method_digest design.sha256 NOT NULL,renew_sql_method_digest design.sha256 NOT NULL,
 database_oid oid NOT NULL,database_name text NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL,CHECK(valid_from<valid_until)
);
CREATE TABLE material_input_renewal.profile_heads(
 renew_login name PRIMARY KEY,profile_id uuid NOT NULL REFERENCES material_input_renewal.profiles(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_input_renewal.records(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,seal_id uuid NOT NULL REFERENCES material_input_seal.records(id),
 quote_id uuid NOT NULL REFERENCES material_cost_quote.quotes(id),verification_id uuid NOT NULL REFERENCES material_input_authority.verifications(id),
 profile_id uuid NOT NULL REFERENCES material_input_renewal.profiles(id),profile_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,scope_id uuid NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=32768),UNIQUE(quote_id,verification_id,profile_id,profile_head_revision)
);
CREATE TRIGGER immutable_input_renewal_profile BEFORE UPDATE OR DELETE ON material_input_renewal.profiles FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_input_renewal_record BEFORE UPDATE OR DELETE ON material_input_renewal.records FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_input_renewal.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_input_renewal,design,pg_temp SET TimeZone='UTC'
AS $input_renewal_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_input_renewal.native_method_digest()','material_input_renewal.current_context(uuid,uuid,uuid,uuid)',
  'material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)','material_input_renewal.read(uuid,text)']) AS s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>4 THEN RETURN NULL; END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$input_renewal_method$;
REVOKE ALL ON FUNCTION material_input_renewal.native_method_digest() FROM PUBLIC;

CREATE FUNCTION material_input_renewal.current_context(target_seal uuid,target_quote uuid,target_verification uuid,target_profile uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_input_renewal,design,pg_temp SET TimeZone='UTC'
AS $input_renewal_context$
DECLARE p material_input_renewal.profiles;h material_input_renewal.profile_heads;sealed material_input_seal.records;
 quoted material_cost_quote.quotes;qp material_cost_quote.policies;qh material_cost_quote.policy_heads;
 sp material_input_seal.profiles;sh material_input_seal.profile_heads;
 original material_input_authority.verifications;fresh material_input_authority.verifications;approved material_input_authority.policies;
 task material_verification.commands;old_context jsonb;new_context jsonb;key text;at timestamptz;
 configuration boolean;seal_valid boolean;quote_valid boolean;fresh_valid boolean;roots boolean;
BEGIN
 SELECT * INTO p FROM material_input_renewal.profiles WHERE id=target_profile;
 SELECT * INTO h FROM material_input_renewal.profile_heads WHERE renew_login=p.renew_login;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=target_seal;
 SELECT * INTO quoted FROM material_cost_quote.quotes WHERE id=target_quote;
 SELECT * INTO qp FROM material_cost_quote.policies WHERE id=quoted.policy_id;
 SELECT * INTO qh FROM material_cost_quote.policy_heads WHERE quote_login=qp.quote_login;
 SELECT * INTO sp FROM material_input_seal.profiles WHERE id=sealed.profile_id;
 SELECT * INTO sh FROM material_input_seal.profile_heads WHERE sealer_login=sp.sealer_login;
 SELECT * INTO original FROM material_input_authority.verifications WHERE id=sealed.verification_id;
 SELECT * INTO fresh FROM material_input_authority.verifications WHERE id=target_verification;
 SELECT * INTO approved FROM material_input_authority.policies WHERE id=fresh.policy_id;
 SELECT * INTO task FROM material_verification.commands WHERE id=(fresh.document->>'program_command_row_id')::uuid;
 IF p.id IS NULL OR sealed.id IS NULL OR quoted.id IS NULL OR qp.id IS NULL OR sp.id IS NULL
  OR original.id IS NULL OR fresh.id IS NULL OR approved.id IS NULL OR task.id IS NULL THEN RETURN NULL; END IF;
 old_context:=material_cost_quote.current_context(sealed.id,qp.id);
 new_context:=material_input_authority.policy_context(fresh.program_result_id,fresh.policy_id);
 IF old_context IS NULL OR new_context IS NULL THEN RETURN NULL; END IF;
 at:=clock_timestamp();
 configuration:=coalesce(p.renew_login=session_user AND p.renew_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.renew_sql_method_digest::text=material_input_renewal.native_method_digest()
  AND p.quote_policy_id=qp.id AND p.quote_policy_digest::text=old_context->>'policy_digest' AND p.origin=qp.origin
  AND p.renew_login NOT IN(sealed.actor,quoted.actor,fresh.actor,new_context#>>'{program_profile,target_login}',new_context#>>'{program_case,request_login}')
  AND p.renew_login_oid NOT IN(sealed.actor_oid,quoted.actor_oid,fresh.actor_oid,(new_context#>>'{program_profile,target_login_oid}')::oid,(new_context#>>'{program_case,request_login_oid}')::oid),false);
 seal_valid:=coalesce(sh.profile_id=sp.id AND sh.enabled AND sh.revision=sealed.profile_head_revision
  AND at>=sp.valid_from AND at<sp.valid_until AND sp.database_name=current_database()
  AND sp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND sp.seal_sql_method_digest::text=material_input_seal.native_method_digest()
  AND sealed.actor=sp.sealer_login AND sealed.actor_oid=sp.sealer_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=sealed.actor_oid AND rolname=sealed.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(sealed.actor,'tender_material_input_seal',ARRAY['material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)'])
  AND sealed.digest::text=encode(sha256(convert_to(design.package_canonical_json(sealed.document),'UTF8')),'hex')
  AND sealed.document->>'profile_digest'=old_context#>>'{input_context,profile_digest}'
  AND sealed.document->>'seal_method_digest'=sp.seal_method_digest::text
  AND sealed.document->>'native_sql_method_digest'=material_input_seal.native_method_digest()
  AND sealed.document->>'verification_digest'=original.digest::text
  AND sealed.document->>'context_digest'=old_context#>>'{context,digest}'
  AND sealed.document->>'storage_record_digest'=old_context#>>'{input_context,storage,digest}'
  AND sealed.document->>'storage_packet_digest'=old_context#>>'{input_context,storage,document,packet_digest}'
  AND old_context#>'{input_context,storage_current}'='true'::jsonb,false);
 quote_valid:=coalesce(qh.policy_id=qp.id AND qh.enabled AND qh.revision=quoted.policy_head_revision
  AND qp.database_name=current_database() AND qp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND qp.quote_sql_method_digest::text=material_cost_quote.native_method_digest()
  AND quoted.actor=qp.quote_login AND quoted.actor_oid=qp.quote_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=quoted.actor_oid AND rolname=quoted.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(quoted.actor,'tender_material_cost_quote',ARRAY['material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)','material_cost_quote.read(uuid,text)'])
  AND quoted.digest::text=encode(sha256(convert_to(design.package_canonical_json(quoted.document),'UTF8')),'hex')
  AND quoted.seal_id=sealed.id AND qp.seal_profile_id=sp.id
  AND quoted.document->>'seal_digest'=sealed.digest::text AND quoted.document->>'policy_digest'=old_context->>'policy_digest'
  AND quoted.document->>'native_sql_method_digest'=material_cost_quote.native_method_digest()
  AND quoted.document->>'quote_method_digest'=qp.quote_method_digest::text
  AND quoted.document->>'material_input_digest'=sealed.document->>'material_input_digest'
  AND quoted.document->>'context_digest'=sealed.document->>'context_digest'
  AND old_context->'price_effective'='true'::jsonb,false);
 roots:=fresh.id<>original.id AND fresh.program_result_id<>original.program_result_id;
 FOREACH key IN ARRAY ARRAY['bid_id','scope_id','scope_digest','context_digest','context_method_digest','findings_digest',
  'policy_id','policy_digest','policy_head_revision','registration_id','registration_digest','review_attestation_id','review_attestation_digest'] LOOP
  IF fresh.document->key IS DISTINCT FROM original.document->key THEN roots:=false; END IF;
 END LOOP;
 fresh_valid:=coalesce(roots AND fresh.bid_id=sealed.bid_id AND fresh.scope_id=sealed.scope_id AND p.origin=approved.origin
  AND fresh.document->>'origin'=p.origin AND sealed.document->>'origin'=p.origin AND original.document->>'origin'=p.origin
  AND fresh.digest::text=encode(sha256(convert_to(design.package_canonical_json(fresh.document),'UTF8')),'hex')
  AND fresh.actor=approved.verifier_login AND fresh.actor_oid=approved.verifier_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=fresh.actor_oid AND rolname=fresh.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(fresh.actor,'tender_material_input_verify',ARRAY['material_input_authority.qualify(uuid,text,uuid,text,uuid)','material_input_authority.read(uuid,text)'])
  AND fresh.document->>'policy_digest'=new_context->>'policy_digest'
  AND fresh.document->>'verifier_method_digest'=approved.verifier_method_digest::text
  AND fresh.document->>'native_sql_method_digest'=material_input_authority.native_method_digest()
  AND fresh.document->>'program_command_digest'=task.digest::text
  AND fresh.document->>'program_result_digest'=new_context#>>'{program_result,digest}'
  AND fresh.document->'software_input_verified'='true'::jsonb AND fresh.document->'native_binding_verified'='true'::jsonb
  AND fresh.document->'input_authority_granted'=to_jsonb(p.origin='current_prebid')
  AND (fresh.document->>'policy_head_revision')::bigint=(new_context->>'policy_head_revision')::bigint
  AND new_context->'policy_current'='true'::jsonb AND new_context->'program_current'='true'::jsonb
  AND new_context->'review_current'='true'::jsonb AND new_context->'source_current'='true'::jsonb
  AND new_context->'fingerprints_match'='true'::jsonb AND new_context->'complete_findings_confirmed'='true'::jsonb,false);
 RETURN jsonb_build_object('profile',to_jsonb(p),'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'profile_head_revision',h.revision,'seal',jsonb_build_object('document',sealed.document,'digest',sealed.digest::text),
  'quote',jsonb_build_object('document',quoted.document,'digest',quoted.digest::text),
  'admission',jsonb_build_object('document',original.document,'digest',original.digest::text),
  'verification',jsonb_build_object('document',fresh.document,'digest',fresh.digest::text),'program_command_id',task.command_id::text,
  'new_context',new_context,'profile_current',configuration,'seal_current',seal_valid,'quote_current',quote_valid,
  'verification_current',fresh_valid,'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
END;
$input_renewal_context$;
REVOKE ALL ON FUNCTION material_input_renewal.current_context(uuid,uuid,uuid,uuid) FROM PUBLIC;

CREATE FUNCTION material_input_renewal.record(target_seal uuid,expected_seal_digest text,target_quote uuid,expected_quote_digest text,
 target_verification uuid,expected_verification_digest text,target_profile uuid,expected_profile_digest text,command uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_renewal,design,pg_temp SET TimeZone='UTC'
AS $input_renewal_write$
DECLARE old material_input_renewal.records;p material_input_renewal.profiles;sealed material_input_seal.records;
 quoted material_cost_quote.quotes;fresh material_input_authority.verifications;task material_verification.commands;
 s design.bid_package_technical_scopes;inventory design.bid_package_requirement_inventories;ctx jsonb;
 identifier uuid;result jsonb;checksum text;revision bigint;key text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_renew',ARRAY['material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)','material_input_renewal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_seal IS NULL OR target_quote IS NULL OR target_verification IS NULL OR target_profile IS NULL OR command IS NULL THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH key IN ARRAY ARRAY[expected_seal_digest,expected_quote_digest,expected_verification_digest,expected_profile_digest] LOOP
  IF key IS NULL OR key !~ '^[0-9a-f]{64}$' OR key=repeat('0',64) THEN RAISE EXCEPTION 'INPUT_RENEWAL_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO old FROM material_input_renewal.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
   OR old.seal_id<>target_seal OR old.quote_id<>target_quote OR old.verification_id<>target_verification OR old.profile_id<>target_profile
   OR old.document->>'seal_digest' IS DISTINCT FROM expected_seal_digest OR old.document->>'quote_digest' IS DISTINCT FROM expected_quote_digest
   OR old.document->>'current_verification_digest' IS DISTINCT FROM expected_verification_digest OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN
   RAISE EXCEPTION 'INPUT_RENEWAL_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=target_seal AND digest=expected_seal_digest;
 SELECT * INTO quoted FROM material_cost_quote.quotes WHERE id=target_quote AND digest=expected_quote_digest;
 SELECT * INTO fresh FROM material_input_authority.verifications WHERE id=target_verification AND digest=expected_verification_digest;
 SELECT * INTO p FROM material_input_renewal.profiles WHERE id=target_profile;
 SELECT * INTO task FROM material_verification.commands WHERE id=(fresh.document->>'program_command_row_id')::uuid;
 IF sealed.id IS NULL OR quoted.id IS NULL OR fresh.id IS NULL OR p.id IS NULL THEN RAISE EXCEPTION 'INPUT_RENEWAL_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 IF task.id IS NULL OR task.command_id<>command THEN RAISE EXCEPTION 'INPUT_RENEWAL_PROGRAM_COMMAND_MISMATCH' USING ERRCODE='P0001'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(sealed.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_input_renewal:'||command::text,0));
 SELECT * INTO old FROM material_input_renewal.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user)
   OR old.seal_id<>target_seal OR old.quote_id<>target_quote OR old.verification_id<>target_verification OR old.profile_id<>target_profile
   OR old.document->>'seal_digest' IS DISTINCT FROM expected_seal_digest OR old.document->>'quote_digest' IS DISTINCT FROM expected_quote_digest
   OR old.document->>'current_verification_digest' IS DISTINCT FROM expected_verification_digest OR old.document->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN
   RAISE EXCEPTION 'INPUT_RENEWAL_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 PERFORM 1 FROM material_input_renewal.profile_heads WHERE renew_login=p.renew_login FOR SHARE;
 PERFORM 1 FROM material_cost_quote.policy_heads WHERE policy_id=quoted.policy_id FOR SHARE;
 PERFORM 1 FROM material_input_seal.profile_heads WHERE profile_id=sealed.profile_id FOR SHARE;
 PERFORM 1 FROM material_input_authority.policy_heads WHERE program_profile_id=(fresh.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.profile_heads WHERE profile_id=(fresh.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id=(fresh.document->>'program_case_id')::uuid FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE profile_id=(SELECT c.profile_id FROM scope_review_issuer.cases c JOIN scope_review_issuer.attestations a ON a.case_id=c.id WHERE a.id=(fresh.document->>'review_attestation_id')::uuid) FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=(SELECT case_id FROM scope_review_issuer.attestations WHERE id=(fresh.document->>'review_attestation_id')::uuid) FOR SHARE;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=sealed.scope_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_renew',ARRAY['material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)','material_input_renewal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 ctx:=material_input_renewal.current_context(target_seal,target_quote,target_verification,target_profile);
 IF ctx IS NULL OR ctx->>'profile_digest' IS DISTINCT FROM expected_profile_digest THEN RAISE EXCEPTION 'INPUT_RENEWAL_PROFILE_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF ctx->'profile_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'seal_current' IS DISTINCT FROM 'true'::jsonb
  OR ctx->'quote_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'verification_current' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 revision:=(ctx->>'profile_head_revision')::bigint;identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','material-input-renewal/1','renewal_id',identifier::text,'command_id',command::text,
  'profile_id',p.id::text,'profile_digest',expected_profile_digest,'profile_head_revision',revision,
  'seal_id',sealed.id::text,'seal_digest',sealed.digest::text,'quote_id',quoted.id::text,'quote_digest',quoted.digest::text,
  'admission_verification_id',sealed.verification_id::text,'admission_verification_digest',ctx#>>'{admission,digest}',
  'current_verification_id',fresh.id::text,'current_verification_digest',fresh.digest::text,
  'material_input_digest',sealed.document->>'material_input_digest','context_digest',sealed.document->>'context_digest',
  'context_method_digest',sealed.document->>'context_method_digest','findings_digest',sealed.document->>'findings_digest',
  'quote_policy_id',quoted.policy_id::text,'quote_policy_digest',quoted.document->>'policy_digest',
  'bid_id',sealed.bid_id::text,'scope_id',sealed.scope_id::text,'scope_digest',sealed.document->>'scope_digest','origin',p.origin,
  'renew_method_digest',p.renew_method_digest::text,'native_sql_method_digest',material_input_renewal.native_method_digest(),
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'recorded_at',ctx->>'observed_at','status',CASE WHEN p.origin='current_prebid' THEN 'current_evidence_registered' ELSE 'synthetic_current_evidence_registered' END,
  'software_current_evidence_verified',true,'frozen_input_preserved',true,'frozen_quote_preserved',true,'native_binding_verified',true,
  'budget_sufficient_under_policy',quoted.document#>'{quote,budget_sufficient_under_policy}',
  'fee_ledger_reserved',false,'automatic_retry',false,'input_authority_granted',false,'execution_authorized',false,
  'send_lease_granted',false,'atomic_snapshot_verified',false,'actual_human_reading_verified',false,
  'model_context_fit_proven',false,'request_body_limit_verified',false,'account_price_confirmed',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_input_renewal.records VALUES(identifier,command,sealed.id,quoted.id,fresh.id,p.id,revision,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),sealed.bid_id,sealed.scope_id,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$input_renewal_write$;

CREATE FUNCTION material_input_renewal.read(target_renewal uuid,expected_renewal_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_input_renewal,design,pg_temp SET TimeZone='UTC'
AS $input_renewal_read$
DECLARE old material_input_renewal.records;ctx jsonb;eligible boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_input_renew',ARRAY['material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid)','material_input_renewal.read(uuid,text)']) THEN
  RAISE EXCEPTION 'INPUT_RENEWAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO old FROM material_input_renewal.records WHERE id=target_renewal AND digest=expected_renewal_digest
  AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'INPUT_RENEWAL_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 ctx:=material_input_renewal.current_context(old.seal_id,old.quote_id,old.verification_id,old.profile_id);
 IF ctx IS NULL THEN RAISE EXCEPTION 'INPUT_RENEWAL_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 eligible:=coalesce(ctx->'profile_current'='true'::jsonb AND ctx->'seal_current'='true'::jsonb AND ctx->'quote_current'='true'::jsonb
  AND ctx->'verification_current'='true'::jsonb AND (ctx->>'profile_head_revision')::bigint=old.profile_head_revision,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',old.document,'digest',old.digest::text),
  'current',jsonb_build_object('observed_at',ctx->>'observed_at','profile_head_revision',ctx->'profile_head_revision',
   'profile_current',ctx->'profile_current','seal_current',ctx->'seal_current','quote_current',ctx->'quote_current','verification_current',ctx->'verification_current',
   'software_evidence_current',eligible,'software_budget_sufficient',eligible AND old.document->'budget_sufficient_under_policy'='true'::jsonb,
   'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$input_renewal_read$;
REVOKE ALL ON FUNCTION material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_input_renewal.read(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_input_renewal TO tender_material_input_renew;
GRANT EXECUTE ON FUNCTION material_input_renewal.record(uuid,text,uuid,text,uuid,text,uuid,text,uuid),material_input_renewal.read(uuid,text) TO tender_material_input_renew;
COMMIT;
