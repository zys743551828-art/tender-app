-- Optional fresh isolated pricing publication and quotes; no budget mutation.
BEGIN;
CREATE SCHEMA material_cost_quote;
REVOKE ALL ON SCHEMA material_cost_quote FROM PUBLIC;
CREATE ROLE tender_material_cost_quote NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_cost_quote.policies(
 id uuid PRIMARY KEY,quote_login name NOT NULL,quote_login_oid oid NOT NULL,
 seal_profile_id uuid NOT NULL REFERENCES material_input_seal.profiles(id),
 origin text NOT NULL CHECK(origin IN('synthetic_mechanism','current_prebid')),
 quote_method_digest design.sha256 NOT NULL,quote_sql_method_digest design.sha256 NOT NULL,cost_method_digest design.sha256 NOT NULL,
 provider_profile_digest design.sha256 NOT NULL,serializer_digest design.sha256 NOT NULL,judgment_method_digest design.sha256 NOT NULL,
 price_policy jsonb NOT NULL,price_policy_digest design.sha256 NOT NULL,max_attempts_per_slot integer NOT NULL CHECK(max_attempts_per_slot BETWEEN 1 AND 5),
 database_oid oid NOT NULL,database_name text NOT NULL,CHECK(octet_length(price_policy::text)<=8192)
);
CREATE TABLE material_cost_quote.policy_heads(
 quote_login name PRIMARY KEY,policy_id uuid NOT NULL REFERENCES material_cost_quote.policies(id),revision bigint NOT NULL CHECK(revision>=1),enabled boolean NOT NULL
);
CREATE TABLE material_cost_quote.quotes(
 id uuid PRIMARY KEY,command_id uuid NOT NULL UNIQUE,seal_id uuid NOT NULL REFERENCES material_input_seal.records(id),
 policy_id uuid NOT NULL REFERENCES material_cost_quote.policies(id),policy_head_revision bigint NOT NULL,
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,scope_id uuid NOT NULL,max_attempts integer NOT NULL,
 budget_currency text NOT NULL,budget_minor bigint NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=65536)
);
CREATE TRIGGER immutable_material_price BEFORE UPDATE OR DELETE ON material_cost_quote.policies FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_material_quote BEFORE UPDATE OR DELETE ON material_cost_quote.quotes FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_cost_quote.native_method_digest()
RETURNS text LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,material_cost_quote,design,pg_temp SET TimeZone='UTC'
AS $cost_quote_method$
DECLARE description jsonb;amount integer;
BEGIN
 SELECT count(*),jsonb_agg(jsonb_build_object('signature',s.signature,'source',p.prosrc,'security_definer',p.prosecdef,
  'volatility',p.provolatile::text,'language',l.lanname,'config',to_jsonb(p.proconfig),'owner_oid',p.proowner::bigint) ORDER BY s.signature)
 INTO amount,description FROM unnest(ARRAY['material_cost_quote.native_method_digest()','material_cost_quote.current_context(uuid,uuid)',
  'material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)','material_cost_quote.read(uuid,text)']) AS s(signature)
 JOIN pg_proc p ON p.oid=to_regprocedure(s.signature) JOIN pg_language l ON l.oid=p.prolang;
 IF amount<>4 THEN RETURN NULL; END IF;
 RETURN encode(sha256(convert_to(design.package_canonical_json(description),'UTF8')),'hex');
END;
$cost_quote_method$;
REVOKE ALL ON FUNCTION material_cost_quote.native_method_digest() FROM PUBLIC;

CREATE FUNCTION material_cost_quote.current_context(target_seal uuid,target_policy uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_cost_quote,design,pg_temp SET TimeZone='UTC'
AS $cost_quote_context$
DECLARE p material_cost_quote.policies;h material_cost_quote.policy_heads;sealed material_input_seal.records;
 sp material_input_seal.profiles;sh material_input_seal.profile_heads;ctx jsonb;metadata jsonb;price jsonb;key text;
 at timestamptz;observed timestamptz;starts timestamptz;ends timestamptz;configuration boolean;input_valid boolean;price_valid boolean;
BEGIN
 SELECT * INTO p FROM material_cost_quote.policies WHERE id=target_policy;
 SELECT * INTO h FROM material_cost_quote.policy_heads WHERE quote_login=p.quote_login;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=target_seal;
 SELECT * INTO sp FROM material_input_seal.profiles WHERE id=sealed.profile_id;
 SELECT * INTO sh FROM material_input_seal.profile_heads WHERE sealer_login=sp.sealer_login;
 IF p.id IS NULL OR sealed.id IS NULL OR sp.id IS NULL THEN RETURN NULL; END IF;
 ctx:=material_input_seal.current_context(sealed.verification_id,sealed.profile_id);
 IF ctx IS NULL THEN RETURN NULL; END IF;
 BEGIN
  SELECT convert_from(data,'UTF8')::jsonb INTO metadata FROM technical_material_store.objects WHERE sha=ctx#>>'{storage,document,packet,context_object,sha256}';
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN RETURN NULL;
 END;
 at:=clock_timestamp();price:=p.price_policy;
 configuration:=coalesce(p.quote_login=session_user AND p.quote_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user)
  AND h.policy_id=p.id AND h.enabled AND p.database_name=current_database()
  AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND p.quote_sql_method_digest::text=material_cost_quote.native_method_digest()
  AND p.quote_login NOT IN(sp.sealer_login,ctx#>>'{verification_context,policy,verifier_login}',ctx#>>'{verification_context,program_profile,target_login}',ctx#>>'{verification_context,program_case,request_login}')
  AND p.quote_login_oid NOT IN(sp.sealer_login_oid,(ctx#>>'{verification_context,policy,verifier_login_oid}')::oid,(ctx#>>'{verification_context,program_profile,target_login_oid}')::oid,(ctx#>>'{verification_context,program_case,request_login_oid}')::oid),false);
 -- The older helper's profile_current also authenticates the *sealer* caller.
 -- Here independently check its recorded sealer and present configuration;
 -- do not reinterpret a different purpose's session identity as authentication.
 input_valid:=coalesce(p.seal_profile_id=sealed.profile_id AND p.origin=sp.origin AND p.origin=sealed.document->>'origin'
  AND sh.profile_id=sp.id AND sh.enabled AND sh.revision=sealed.profile_head_revision
  AND at>=sp.valid_from AND at<sp.valid_until AND sp.database_name=current_database()
  AND sp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND sp.seal_sql_method_digest::text=material_input_seal.native_method_digest()
  AND sealed.actor=sp.sealer_login AND sealed.actor_oid=sp.sealer_login_oid
  AND EXISTS(SELECT FROM pg_roles WHERE oid=sealed.actor_oid AND rolname=sealed.actor AND rolcanlogin)
  AND scope_review_issuer.role_policy(sealed.actor,'tender_material_input_seal',ARRAY['material_input_seal.seal(uuid,text,uuid,text,uuid)','material_input_seal.read(uuid,text)'])
  AND sealed.digest::text=encode(sha256(convert_to(design.package_canonical_json(sealed.document),'UTF8')),'hex')
  AND sealed.document->>'seal_id'=sealed.id::text AND sealed.document->>'profile_id'=sp.id::text
  AND sealed.document->>'profile_digest'=ctx->>'profile_digest' AND sealed.document->>'seal_method_digest'=sp.seal_method_digest::text
  AND sealed.document->>'native_sql_method_digest'=material_input_seal.native_method_digest()
  AND sealed.document->>'verification_id'=ctx#>>'{verification,document,verification_id}'
  AND sealed.document->>'verification_digest'=ctx#>>'{verification,digest}'
  AND sealed.document->>'storage_record_digest'=ctx#>>'{storage,digest}'
  AND sealed.document->>'storage_packet_digest'=ctx#>>'{storage,document,packet_digest}'
  AND sealed.document->>'context_digest'=metadata->>'digest'
  AND metadata->>'digest'=encode(sha256(convert_to(design.package_canonical_json(metadata-'digest'),'UTF8')),'hex')
  AND metadata->>'provider_profile_digest'=p.provider_profile_digest::text
  AND metadata->>'judgment_method_digest'=p.judgment_method_digest::text
  AND metadata->>'context_method_digest'=sp.context_method_digest::text
  AND ctx->'verification_current'='true'::jsonb AND ctx->'storage_current'='true'::jsonb,false);
 price_valid:=coalesce(jsonb_typeof(price)='object' AND design.package_json_keys(price,ARRAY['version','policy_id','profile_digest','model_alias','currency','minor_per_unit',
  'input_per_million_minor','output_per_million_minor','context_token_capacity','provider_output_token_capacity','source_observation_digest',
  'source_observed_at','valid_from','valid_until','reservation_basis'])
  AND price->>'version'='package-material-cost-policy/1' AND price->>'policy_id'=p.id::text
  AND price->>'profile_digest'=p.provider_profile_digest::text AND price->>'model_alias'='deepseek-flash'
  AND price->>'currency' IN('USD','CNY') AND price->'minor_per_unit'='1000000'::jsonb
  AND price->>'reservation_basis'='full_context_capacity_no_discount'
  AND price->>'source_observation_digest'~'^[0-9a-f]{64}$' AND price->>'source_observation_digest'<>repeat('0',64)
  AND p.price_policy_digest::text=encode(sha256(convert_to(design.package_canonical_json(price),'UTF8')),'hex'),false);
 FOREACH key IN ARRAY ARRAY['input_per_million_minor','output_per_million_minor','context_token_capacity','provider_output_token_capacity'] LOOP
  IF jsonb_typeof(price->key) IS DISTINCT FROM 'number' OR price->>key !~ '^(0|[1-9][0-9]{0,15})$' THEN price_valid:=false;
  ELSIF (price->>key)::numeric>9007199254740991 THEN price_valid:=false; END IF;
 END LOOP;
 IF price_valid THEN
  price_valid:=(price->>'context_token_capacity')::numeric>=1 AND (price->>'provider_output_token_capacity')::numeric>=4096
   AND (price->>'provider_output_token_capacity')::numeric<=(price->>'context_token_capacity')::numeric;
 END IF;
 FOREACH key IN ARRAY ARRAY['source_observed_at','valid_from','valid_until'] LOOP
  IF jsonb_typeof(price->key) IS DISTINCT FROM 'string' OR length(price->>key)>40 OR price->>key !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN price_valid:=false; END IF;
 END LOOP;
 IF price_valid THEN
  BEGIN
   observed:=(price->>'source_observed_at')::timestamptz;starts:=(price->>'valid_from')::timestamptz;ends:=(price->>'valid_until')::timestamptz;
   price_valid:=observed<=starts AND starts<ends AND ends<=observed+interval '24 hours' AND at>=starts AND at<ends;
  EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN price_valid:=false;
  END;
 END IF;
 RETURN jsonb_build_object('policy',to_jsonb(p),'policy_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'policy_head_revision',h.revision,'seal',jsonb_build_object('document',sealed.document,'digest',sealed.digest::text),
  'context',metadata,'input_context',ctx,'configuration_current',configuration,'input_current',input_valid,'price_effective',price_valid,
  'observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
END;
$cost_quote_context$;
REVOKE ALL ON FUNCTION material_cost_quote.current_context(uuid,uuid) FROM PUBLIC;

CREATE FUNCTION material_cost_quote.quote(target_seal uuid,expected_seal_digest text,target_policy uuid,expected_policy_digest text,command uuid,attempts integer,currency text,budget bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_cost_quote,design,pg_temp SET TimeZone='UTC'
AS $cost_quote_write$
DECLARE old material_cost_quote.quotes;p material_cost_quote.policies;sealed material_input_seal.records;
 q material_input_authority.verifications;s design.bid_package_technical_scopes;inventory design.bid_package_requirement_inventories;
 ctx jsonb;price jsonb;metadata jsonb;rule jsonb;rule_ids jsonb:='[]'::jsonb;count_rules integer;minimum_calls integer;maximum_calls integer;
 per_call numeric;required numeric;trial jsonb;result jsonb;identifier uuid;checksum text;revision bigint;at text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'COST_QUOTE_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_cost_quote',ARRAY['material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)','material_cost_quote.read(uuid,text)']) THEN
  RAISE EXCEPTION 'COST_QUOTE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_seal IS NULL OR target_policy IS NULL OR command IS NULL OR expected_seal_digest IS NULL OR expected_policy_digest IS NULL
  OR expected_seal_digest !~ '^[0-9a-f]{64}$' OR expected_policy_digest !~ '^[0-9a-f]{64}$'
  OR expected_seal_digest=repeat('0',64) OR expected_policy_digest=repeat('0',64) OR attempts IS NULL OR attempts NOT BETWEEN 1 AND 5
  OR currency IS NULL OR currency NOT IN('USD','CNY') OR budget IS NULL OR budget NOT BETWEEN 0 AND 9007199254740991 THEN
  RAISE EXCEPTION 'COST_QUOTE_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT * INTO old FROM material_cost_quote.quotes WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.seal_id<>target_seal OR old.policy_id<>target_policy
   OR old.document->>'seal_digest' IS DISTINCT FROM expected_seal_digest OR old.document->>'policy_digest' IS DISTINCT FROM expected_policy_digest
   OR old.max_attempts<>attempts OR old.budget_currency<>currency OR old.budget_minor<>budget THEN RAISE EXCEPTION 'COST_QUOTE_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT * INTO sealed FROM material_input_seal.records WHERE id=target_seal AND digest=expected_seal_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'COST_QUOTE_SEAL_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO p FROM material_cost_quote.policies WHERE id=target_policy;
 SELECT * INTO q FROM material_input_authority.verifications WHERE id=sealed.verification_id;
 PERFORM pg_advisory_xact_lock(91143,1);PERFORM design.lock_worker_bid(sealed.bid_id);PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_cost_quote:'||command::text,0));
 SELECT * INTO old FROM material_cost_quote.quotes WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.seal_id<>target_seal OR old.policy_id<>target_policy
   OR old.document->>'seal_digest' IS DISTINCT FROM expected_seal_digest OR old.document->>'policy_digest' IS DISTINCT FROM expected_policy_digest
   OR old.max_attempts<>attempts OR old.budget_currency<>currency OR old.budget_minor<>budget THEN RAISE EXCEPTION 'COST_QUOTE_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 PERFORM 1 FROM material_cost_quote.policy_heads WHERE quote_login=p.quote_login FOR SHARE;
 PERFORM 1 FROM material_input_seal.profile_heads WHERE profile_id=sealed.profile_id FOR SHARE;
 PERFORM 1 FROM material_input_authority.policy_heads WHERE program_profile_id=(q.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.profile_heads WHERE profile_id=(q.document->>'program_profile_id')::uuid FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id=(q.document->>'program_case_id')::uuid FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE profile_id=(SELECT c.profile_id FROM scope_review_issuer.cases c JOIN scope_review_issuer.attestations a ON a.case_id=c.id WHERE a.id=(q.document->>'review_attestation_id')::uuid) FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=(SELECT case_id FROM scope_review_issuer.attestations WHERE id=(q.document->>'review_attestation_id')::uuid) FOR SHARE;
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=sealed.scope_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=s.inventory_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,inventory.authority_revision_id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_cost_quote',ARRAY['material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)','material_cost_quote.read(uuid,text)']) THEN
  RAISE EXCEPTION 'COST_QUOTE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 ctx:=material_cost_quote.current_context(target_seal,target_policy);
 IF ctx IS NULL OR ctx->>'policy_digest' IS DISTINCT FROM expected_policy_digest THEN RAISE EXCEPTION 'COST_QUOTE_POLICY_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF ctx->'configuration_current' IS DISTINCT FROM 'true'::jsonb OR ctx->'input_current' IS DISTINCT FROM 'true'::jsonb
  OR ctx->'price_effective' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'COST_QUOTE_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 price:=p.price_policy;metadata:=ctx->'context';revision:=(ctx->>'policy_head_revision')::bigint;at:=ctx->>'observed_at';
 IF attempts>p.max_attempts_per_slot OR currency<>price->>'currency' THEN RAISE EXCEPTION 'COST_QUOTE_BUDGET_INVALID' USING ERRCODE='P0001'; END IF;
 FOR rule IN SELECT value FROM jsonb_array_elements(metadata->'rules') LOOP
  IF rule->>'selection'='include' THEN
   IF rule->>'source_coverage' IS DISTINCT FROM 'complete' THEN RAISE EXCEPTION 'COST_QUOTE_RULE_SOURCE_INCOMPLETE' USING ERRCODE='P0001'; END IF;
   rule_ids:=rule_ids||jsonb_build_array(rule->'rule_id');
  END IF;
 END LOOP;
 count_rules:=jsonb_array_length(rule_ids);
 IF count_rules NOT BETWEEN 1 AND 400 OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(rule_ids))<>count_rules THEN
  RAISE EXCEPTION 'COST_QUOTE_RULES_INVALID' USING ERRCODE='P0001'; END IF;
 minimum_calls:=count_rules*3;maximum_calls:=minimum_calls*attempts;
 per_call:=floor(((price->>'context_token_capacity')::numeric*(price->>'input_per_million_minor')::numeric+4096*(price->>'output_per_million_minor')::numeric+999999)/1000000);
 required:=per_call*maximum_calls;
 IF per_call>9007199254740991 OR required>9007199254740991 THEN RAISE EXCEPTION 'COST_QUOTE_AMOUNT_OVERFLOW' USING ERRCODE='P0001'; END IF;
 trial:=jsonb_build_object('version','package-material-reservation-quote/1','method_digest',p.cost_method_digest::text,
  'context_digest',metadata->>'digest','policy_digest',p.price_policy_digest::text,'profile_digest',p.provider_profile_digest::text,
  'serializer_digest',p.serializer_digest::text,'as_of',at,'currency',currency,'minor_per_unit',1000000,'rule_ids',rule_ids,
  'required_valid_slots',minimum_calls,'max_attempts_per_slot',attempts,'maximum_external_calls',maximum_calls,
  'reserved_input_tokens_per_call',(price->>'context_token_capacity')::bigint,'reserved_output_tokens_per_call',4096,
  'per_call_ceiling_minor',per_call::bigint,'required_reservation_minor',required::bigint,'budget_ceiling_minor',budget,
  'budget_sufficient_under_policy',budget>=required,'all_declared_included_rules_retained',true,'reservation_is_not_invoice_cap',true,
  'price_policy_native_verified',false,'model_context_fit_proven',false,'request_body_limit_verified',false,'fee_ledger_reserved',false,
  'automatic_retry',false,'native_binding_verified',false,'execution_authorized',false);
 trial:=trial||jsonb_build_object('digest',encode(sha256(convert_to(design.package_canonical_json(trial),'UTF8')),'hex'));
 identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','material-cost-quote/1','quote_id',identifier::text,'command_id',command::text,
  'seal_id',sealed.id::text,'seal_digest',sealed.digest::text,'material_input_digest',sealed.document->>'material_input_digest',
  'policy_id',p.id::text,'policy_digest',expected_policy_digest,'policy_head_revision',revision,'origin',p.origin,
  'context_digest',metadata->>'digest','context_method_digest',metadata->>'context_method_digest',
  'bid_id',sealed.bid_id::text,'scope_id',sealed.scope_id::text,'scope_digest',sealed.document->>'scope_digest',
  'price_policy',price,'price_policy_digest',p.price_policy_digest::text,'cost_method_digest',p.cost_method_digest::text,
  'provider_profile_digest',p.provider_profile_digest::text,'serializer_digest',p.serializer_digest::text,'judgment_method_digest',p.judgment_method_digest::text,
  'quote_method_digest',p.quote_method_digest::text,'native_sql_method_digest',material_cost_quote.native_method_digest(),
  'quote',trial,'quote_digest',trial->>'digest','recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'recorded_at',at,'status',CASE WHEN budget>=required THEN 'quoted_sufficient' ELSE 'quoted_insufficient' END,
  'software_quote_verified',true,'price_policy_native_verified',true,'native_binding_verified',true,
  'account_price_confirmed',false,'model_context_fit_proven',false,'request_body_limit_verified',false,'fee_ledger_reserved',false,
  'automatic_retry',false,'input_authority_granted',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_cost_quote.quotes VALUES(identifier,command,sealed.id,p.id,revision,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),sealed.bid_id,sealed.scope_id,attempts,currency,budget,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$cost_quote_write$;

CREATE FUNCTION material_cost_quote.read(target_quote uuid,expected_quote_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_cost_quote,design,pg_temp SET TimeZone='UTC'
AS $cost_quote_read$
DECLARE old material_cost_quote.quotes;ctx jsonb;eligible boolean;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'COST_QUOTE_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_cost_quote',ARRAY['material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint)','material_cost_quote.read(uuid,text)']) THEN
  RAISE EXCEPTION 'COST_QUOTE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO old FROM material_cost_quote.quotes WHERE id=target_quote AND digest=expected_quote_digest
  AND actor=session_user AND actor_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user);
 IF NOT FOUND THEN RAISE EXCEPTION 'COST_QUOTE_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 ctx:=material_cost_quote.current_context(old.seal_id,old.policy_id);
 IF ctx IS NULL THEN RAISE EXCEPTION 'COST_QUOTE_CURRENT_STATE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 eligible:=coalesce(ctx->'configuration_current'='true'::jsonb AND ctx->'input_current'='true'::jsonb AND ctx->'price_effective'='true'::jsonb
  AND (ctx->>'policy_head_revision')::bigint=old.policy_head_revision,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',old.document,'digest',old.digest::text),
  'current',jsonb_build_object('observed_at',ctx->>'observed_at','configuration_current',ctx->'configuration_current','input_current',ctx->'input_current',
   'price_effective',ctx->'price_effective','policy_head_revision',ctx->'policy_head_revision','software_quote_current',eligible,
   'software_budget_sufficient',eligible AND old.document#>'{quote,budget_sufficient_under_policy}'='true'::jsonb,
   'fee_ledger_reserved',false,'execution_authorized',false,'send_lease_granted',false,'atomic_snapshot_verified',false));
END;
$cost_quote_read$;
REVOKE ALL ON FUNCTION material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_cost_quote.read(uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_cost_quote TO tender_material_cost_quote;
GRANT EXECUTE ON FUNCTION material_cost_quote.quote(uuid,text,uuid,text,uuid,integer,text,bigint),material_cost_quote.read(uuid,text) TO tender_material_cost_quote;
COMMIT;
