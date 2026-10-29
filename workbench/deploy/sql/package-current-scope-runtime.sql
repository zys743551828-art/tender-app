-- Optional fresh initialization. No business table or old scope is modified.
BEGIN;
CREATE SCHEMA current_technical_scope;
REVOKE ALL ON SCHEMA current_technical_scope FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='tender_current_scope_verify') THEN
  RAISE EXCEPTION 'current_scope_role_already_exists';
 END IF;
 CREATE ROLE tender_current_scope_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
END $$;

CREATE FUNCTION current_technical_scope.observe(target_bid uuid,target_scope uuid,expected_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design,pg_temp
AS $current_scope$
DECLARE s design.bid_package_technical_scopes; p jsonb; own design.bid_package_revisions;
 authority design.bid_package_revisions; inventory design.bid_package_requirement_inventories;
 profile design.bid_profiles; identity jsonb; output jsonb; bytes bigint;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_OWNED_READ_ONLY_TRANSACTION_REQUIRED' USING ERRCODE='25001';
 END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolcanlogin AND NOT rolsuper
  AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT pg_has_role(session_user,'tender_current_scope_verify','MEMBER') THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501';
 END IF;
 SELECT octet_length(manifest::text) INTO bytes FROM design.bid_package_technical_scopes
  WHERE bid_id=target_bid AND id=target_scope AND digest=expected_digest;
 IF bytes IS NULL THEN RAISE EXCEPTION 'CURRENT_SCOPE_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 IF bytes>8388608 THEN RAISE EXCEPTION 'CURRENT_SCOPE_TOO_LARGE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO STRICT s FROM design.bid_package_technical_scopes WHERE bid_id=target_bid AND id=target_scope;
 IF design.package_technical_digest(s.manifest) IS DISTINCT FROM expected_digest THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_CORRUPT' USING ERRCODE='P0001'; END IF;
 p:=s.manifest#>'{preview,manifest}';
 SELECT * INTO profile FROM design.bid_profiles WHERE bid_id=target_bid;
 IF profile.bid_id IS NULL OR profile.archived_at IS NOT NULL OR profile.phase IN('submitted','closed','terminated')
 OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=target_bid) THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_NOT_CURRENT_PREBID' USING ERRCODE='P0001'; END IF;
 identity:=design.identity_snapshot_v2(target_bid);
 IF identity IS NULL OR identity->>'binding_status' IS DISTINCT FROM 'confirmed'
 OR identity->>'digest' IS DISTINCT FROM p#>>'{basis,identity_digest}' THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_IDENTITY_CHANGED' USING ERRCODE='P0001'; END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=s.package_id AND revision_id=s.revision_id
  AND digest::text=p#>>'{basis,package_digest}') THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_TARGET_CHANGED' USING ERRCODE='P0001'; END IF;
 SELECT octet_length(manifest::text) INTO bytes FROM design.bid_package_revisions WHERE id=s.revision_id;
 IF bytes IS NULL OR bytes>8388608 THEN RAISE EXCEPTION 'CURRENT_SCOPE_TOO_LARGE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO STRICT own FROM design.bid_package_revisions WHERE id=s.revision_id;
 IF own.identity_digest::text IS DISTINCT FROM identity->>'digest' OR own.manifest->>'kind'<>'bid' THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_TARGET_CHANGED' USING ERRCODE='P0001'; END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_requirement_heads WHERE target_revision_id=s.revision_id
  AND inventory_id=s.inventory_id AND digest::text=p#>>'{basis,inventory_digest}') THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_INVENTORY_CHANGED' USING ERRCODE='P0001'; END IF;
 SELECT octet_length(manifest::text) INTO bytes FROM design.bid_package_requirement_inventories
  WHERE bid_id=target_bid AND id=s.inventory_id;
 IF bytes IS NULL OR bytes>8388608 THEN RAISE EXCEPTION 'CURRENT_SCOPE_TOO_LARGE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO STRICT inventory FROM design.bid_package_requirement_inventories WHERE bid_id=target_bid AND id=s.inventory_id;
 IF inventory.target_revision_id<>s.revision_id OR inventory.authority_revision_id::text IS DISTINCT FROM p#>>'{basis,authority_revision_id}'
 OR inventory.rule_set_id IS DISTINCT FROM profile.current_rule_set_id
 OR inventory.rule_set_id::text IS DISTINCT FROM p#>>'{basis,rule_set_id}'
 OR NOT EXISTS(SELECT FROM design.rule_sets WHERE bid_id=target_bid AND id=inventory.rule_set_id
  AND digest::text=p#>>'{basis,rule_set_digest}' AND coverage='complete') THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_RULES_CHANGED' USING ERRCODE='P0001'; END IF;
 SELECT octet_length(manifest::text) INTO bytes FROM design.bid_package_revisions WHERE id=inventory.authority_revision_id;
 IF bytes IS NULL OR bytes>8388608 THEN RAISE EXCEPTION 'CURRENT_SCOPE_TOO_LARGE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO STRICT authority FROM design.bid_package_revisions WHERE id=inventory.authority_revision_id;
 IF authority.digest::text IS DISTINCT FROM p#>>'{basis,authority_digest}'
 OR authority.identity_digest::text IS DISTINCT FROM identity->>'digest' OR authority.manifest->>'kind'<>'authority'
 OR NOT EXISTS(SELECT FROM design.bid_packages WHERE id=authority.package_id AND bid_id=target_bid AND kind='authority')
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=authority.package_id AND revision_id=authority.id AND digest=authority.digest) THEN
  RAISE EXCEPTION 'CURRENT_SCOPE_AUTHORITY_CHANGED' USING ERRCODE='P0001'; END IF;
 output:=jsonb_build_object('version','package-current-scope-facts/1','bid_id',target_bid,'observed_at',clock_timestamp(),
  'scope',jsonb_build_object('manifest',s.manifest,'digest',s.digest),
  'target',jsonb_build_object('manifest',own.manifest,'digest',own.digest,'identity',own.identity_snapshot),
  'authority',jsonb_build_object('manifest',authority.manifest,'digest',authority.digest,'identity',authority.identity_snapshot),
  'inventory',jsonb_build_object('manifest',inventory.manifest,'digest',inventory.digest),'current_identity',identity,
  'native_current_facts_checked',true,'necessary_scope_verified',false,'original_bytes_reverified',false,
  'input_authority_granted',false,'execution_authorized',false,'historical_existence_verified',false);
 IF octet_length(output::text)>8388608 THEN RAISE EXCEPTION 'CURRENT_SCOPE_TOO_LARGE' USING ERRCODE='P0001'; END IF;
 RETURN output;
END;
$current_scope$;
REVOKE ALL ON FUNCTION current_technical_scope.observe(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA current_technical_scope TO tender_current_scope_verify;
GRANT EXECUTE ON FUNCTION current_technical_scope.observe(uuid,uuid,text) TO tender_current_scope_verify;
COMMIT;
