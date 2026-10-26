-- Optional fresh installation after review registry, native jobs and execution.
-- Does not change native RPC signatures, enable a provider, or add native role grants.
BEGIN;
CREATE TABLE material_qualification.intents(
 id uuid PRIMARY KEY REFERENCES design.commands(id),
 actor_id uuid NOT NULL REFERENCES design.members(id),bid_id uuid NOT NULL,scope_id uuid NOT NULL,
 qualification_id uuid NOT NULL REFERENCES material_qualification.records(id),qualification_digest design.sha256 NOT NULL,
 qualification_revision bigint NOT NULL CHECK(qualification_revision>=1),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,
 FOREIGN KEY(bid_id,scope_id) REFERENCES design.bid_package_technical_scopes(bid_id,id),
 CHECK(octet_length(design.package_canonical_json(document))<=16384),
 CHECK(digest::text=encode(sha256(convert_to(design.package_canonical_json(document),'UTF8')),'hex'))
);
CREATE TABLE material_qualification.acceptances(
 intent_id uuid PRIMARY KEY REFERENCES material_qualification.intents(id),
 job_id uuid NOT NULL UNIQUE REFERENCES material_judgment_job.jobs(id),job_digest design.sha256 NOT NULL,
 document jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(job_digest::text=encode(sha256(convert_to(design.package_canonical_json(document),'UTF8')),'hex'))
);
CREATE TRIGGER immutable_qualification_intent BEFORE UPDATE OR DELETE ON material_qualification.intents FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_qualification_acceptance BEFORE UPDATE OR DELETE ON material_qualification.acceptances FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE FUNCTION material_qualification.enforce()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_qualification,design,pg_temp SET TimeZone='UTC'
AS $qualification_enforce$
DECLARE r material_qualification.records;h material_qualification.heads;d material_qualification.decisions;
 j material_judgment_job.jobs;q material_cost_quote.quotes;p material_cost_quote.policies;
 i material_qualification.intents;ep material_execution.profiles;binding jsonb;proof jsonb;actual jsonb;item jsonb;at timestamptz;
BEGIN
 IF TG_TABLE_SCHEMA='material_judgment_job' THEN
  j:=NEW;
  SELECT * INTO i FROM material_qualification.intents WHERE id=j.command_id;
 ELSE
  SELECT * INTO j FROM material_judgment_job.jobs WHERE id=NEW.job_id;
  SELECT intent.* INTO i FROM material_qualification.intents intent JOIN material_qualification.acceptances a ON a.intent_id=intent.id
   WHERE a.job_id=j.id AND a.job_digest=j.digest;
 END IF;
 IF i.id IS NULL OR i.actor_id IS NULL OR i.bid_id IS DISTINCT FROM j.bid_id OR i.scope_id IS DISTINCT FROM j.scope_id
  OR i.digest::text IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(i.document),'UTF8')),'hex')
  OR NOT EXISTS(SELECT FROM design.members WHERE id=i.actor_id AND active)
  OR i.document->>'version' IS DISTINCT FROM 'material-qualified-job-intent/1'
  OR i.document->>'guard_digest' IS DISTINCT FROM (SELECT encode(sha256(convert_to(prosrc,'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('material_qualification.enforce()'))
  OR i.document#>>'{request,version}' IS DISTINCT FROM 'material-qualified-job-request/1'
  OR i.document#>>'{command,version}' IS DISTINCT FROM 'material-job-command/1'
  OR i.document#>>'{command,operation}' IS DISTINCT FROM 'start'
  OR i.document#>>'{request,qualification_id}' IS DISTINCT FROM i.qualification_id::text
  OR i.document#>>'{request,qualification_digest}' IS DISTINCT FROM i.qualification_digest::text
  OR i.document#>'{request,qualification_revision}' IS DISTINCT FROM to_jsonb(i.qualification_revision)
  OR i.document#>>'{request,scope_digest}' IS DISTINCT FROM j.document->>'scope_digest'
  OR i.document#>>'{request,renewal_id}' IS DISTINCT FROM j.document->>'initial_renewal_id'
  OR i.document#>>'{request,renewal_digest}' IS DISTINCT FROM j.document->>'initial_renewal_digest'
  OR i.document#>>'{command,arguments,command_id}' IS DISTINCT FROM j.command_id::text
  OR i.document#>>'{command,arguments,renewal_id}' IS DISTINCT FROM j.document->>'initial_renewal_id'
  OR i.document#>>'{command,arguments,expected_renewal_digest}' IS DISTINCT FROM j.document->>'initial_renewal_digest'
  OR i.document#>>'{command,arguments,profile_id}' IS DISTINCT FROM j.profile_id::text
  OR i.document#>>'{command,arguments,expected_profile_digest}' IS DISTINCT FROM j.document->>'profile_digest'
  OR i.document#>>'{command,arguments,expected_method_digest}' IS DISTINCT FROM j.document->>'job_method_digest'
 THEN RAISE EXCEPTION 'MATERIAL_QUALIFICATION_INTENT_MISMATCH' USING ERRCODE='P0001';END IF;
 SELECT * INTO r FROM material_qualification.records WHERE id=i.qualification_id AND digest=i.qualification_digest;
 SELECT * INTO h FROM material_qualification.heads WHERE record_id=r.id FOR SHARE;
 SELECT * INTO d FROM material_qualification.decisions WHERE id=h.decision_id AND record_id=r.id AND revision=h.revision;
 at:=clock_timestamp();binding:=r.document->'binding';
 IF r.id IS NULL OR r.document->>'version' IS DISTINCT FROM 'material-qualification-review/1' OR r.bid_id IS DISTINCT FROM i.bid_id OR r.scope_id IS DISTINCT FROM i.scope_id OR h.revision IS DISTINCT FROM i.qualification_revision OR d.decision IS DISTINCT FROM 'approved'
  OR NOT EXISTS(SELECT FROM design.members WHERE id=d.actor_id AND active)
  OR (at>=(r.document->>'valid_from')::timestamptz AND at<(r.document->>'valid_until')::timestamptz) IS NOT TRUE
  OR r.digest::text<>encode(sha256(convert_to(design.package_canonical_json(r.document),'UTF8')),'hex')
  OR binding->>'scope_digest' IS DISTINCT FROM j.document->>'scope_digest'
  OR binding->>'input_digest' IS DISTINCT FROM j.document->>'material_input_digest'
  OR binding->>'seal_id' IS DISTINCT FROM j.seal_id::text OR binding->>'seal_digest' IS DISTINCT FROM j.document->>'seal_digest'
  OR binding->>'quote_id' IS DISTINCT FROM j.quote_id::text OR binding->>'quote_digest' IS DISTINCT FROM j.document->>'quote_digest'
  OR binding->>'job_profile_id' IS DISTINCT FROM j.profile_id::text OR binding->>'job_profile_digest' IS DISTINCT FROM j.document->>'profile_digest'
 THEN RAISE EXCEPTION 'MATERIAL_QUALIFICATION_NOT_CURRENT' USING ERRCODE='P0001';END IF;
 SELECT * INTO q FROM material_cost_quote.quotes WHERE id=j.quote_id AND digest=j.document->>'quote_digest';
 SELECT * INTO p FROM material_cost_quote.policies WHERE id=q.policy_id;
 IF q.id IS NULL OR (at>=(r.document#>>'{price,valid_from}')::timestamptz AND at<(r.document#>>'{price,valid_until}')::timestamptz) IS NOT TRUE
  OR r.document->'price' IS DISTINCT FROM p.price_policy
  OR binding->>'profile_digest' IS DISTINCT FROM p.provider_profile_digest::text
  OR binding->>'serializer_digest' IS DISTINCT FROM p.serializer_digest::text
  OR binding->>'judgment_method_digest' IS DISTINCT FROM p.judgment_method_digest::text
  OR r.document->'price'->>'model_alias' IS DISTINCT FROM 'deepseek-flash'
 THEN RAISE EXCEPTION 'MATERIAL_QUALIFICATION_PRICE_OR_MODEL_CHANGED' USING ERRCODE='P0001';END IF;
 IF NOT design.package_json_keys(r.document->'evidence',ARRAY['price','capacity','validation']) THEN
  RAISE EXCEPTION 'MATERIAL_QUALIFICATION_EVIDENCE_CHANGED' USING ERRCODE='P0001';END IF;
 SELECT * INTO ep FROM material_execution.profiles WHERE id=(binding->>'execution_profile_id')::uuid;
 IF ep.id IS NULL OR (at>=ep.valid_from AND at<ep.valid_until) IS NOT TRUE
  OR NOT EXISTS(SELECT FROM material_preparation.profiles pp WHERE pp.id=ep.preparation_profile_id
   AND pp.job_profile_id=j.profile_id AND pp.job_profile_digest::text=j.document->>'profile_digest'
   AND ep.preparation_profile_digest::text=encode(sha256(convert_to(design.package_canonical_json(to_jsonb(pp)),'UTF8')),'hex'))
  OR NOT EXISTS(SELECT FROM material_execution.accounts a WHERE a.id=ep.account_id AND a.currency=p.price_policy->>'currency')
  OR binding->>'execution_profile_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(to_jsonb(ep)),'UTF8')),'hex')
  OR binding->>'account_id' IS DISTINCT FROM ep.account_id::text
  OR binding->>'profile_digest' IS DISTINCT FROM ep.provider_profile_digest::text
  OR binding->>'serializer_digest' IS DISTINCT FROM ep.serializer_digest::text
  OR binding->>'judgment_method_digest' IS DISTINCT FROM ep.judgment_method_digest::text THEN
  RAISE EXCEPTION 'MATERIAL_QUALIFICATION_EXECUTOR_CHANGED' USING ERRCODE='P0001';END IF;
 FOR proof IN SELECT value FROM jsonb_each(r.document->'evidence') LOOP
  IF NOT EXISTS(SELECT FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id
   WHERE v.id=(proof->>'document_version_id')::uuid AND v.bid_id=j.bid_id AND b.digest=proof->>'digest') THEN
   RAISE EXCEPTION 'MATERIAL_QUALIFICATION_EVIDENCE_CHANGED' USING ERRCODE='P0001';END IF;
 END LOOP;
 IF TG_TABLE_SCHEMA='material_judgment_job' THEN
  IF (SELECT jsonb_agg(x->>'rule_id' ORDER BY x->>'rule_id') FROM jsonb_array_elements(r.document->'requests') x)
   IS DISTINCT FROM (SELECT jsonb_agg(x ORDER BY x) FROM jsonb_array_elements_text(j.document->'rule_ids') x) THEN
   RAISE EXCEPTION 'MATERIAL_QUALIFICATION_RULES_CHANGED' USING ERRCODE='P0001';END IF;
  INSERT INTO material_qualification.acceptances(intent_id,job_id,job_digest,document)
   VALUES(i.id,j.id,j.digest,j.document);
 ELSE
  SELECT * INTO ep FROM material_execution.profiles WHERE id=NEW.profile_id;
  IF binding->>'execution_profile_id' IS DISTINCT FROM ep.id::text OR binding->>'execution_profile_digest' IS DISTINCT FROM NEW.document->>'profile_digest' OR binding->>'account_id' IS DISTINCT FROM ep.account_id::text
   OR binding->>'profile_digest' IS DISTINCT FROM ep.provider_profile_digest::text
   OR binding->>'serializer_digest' IS DISTINCT FROM ep.serializer_digest::text
   OR binding->>'judgment_method_digest' IS DISTINCT FROM ep.judgment_method_digest::text THEN
   RAISE EXCEPTION 'MATERIAL_QUALIFICATION_EXECUTOR_CHANGED' USING ERRCODE='P0001';END IF;
  IF ((NEW.document->>'send_until')::timestamptz<=least((r.document->>'valid_until')::timestamptz,(r.document#>>'{price,valid_until}')::timestamptz)) IS NOT TRUE THEN
   RAISE EXCEPTION 'MATERIAL_QUALIFICATION_GRANT_WINDOW_INVALID' USING ERRCODE='P0001';END IF;
  actual:=NEW.document->'request';
  SELECT x INTO item FROM jsonb_array_elements(r.document->'requests') x WHERE x->>'rule_id'=NEW.document->>'rule_id';
  IF item IS NULL OR item->>'request_digest' IS DISTINCT FROM actual->>'request_digest'
   OR item->'body_byte_count' IS DISTINCT FROM actual->'body_byte_count'
   OR ((item->>'input_tokens')::numeric>=1 AND (item->>'input_tokens')::numeric+4096<=(r.document#>>'{price,context_token_capacity}')::numeric) IS NOT TRUE
   OR ((r.document#>>'{price,provider_output_token_capacity}')::numeric>=4096) IS NOT TRUE
   OR at>=(r.document#>>'{price,valid_until}')::timestamptz OR at<(r.document#>>'{price,valid_from}')::timestamptz THEN
   RAISE EXCEPTION 'MATERIAL_QUALIFICATION_CAPACITY_CHANGED' USING ERRCODE='P0001';END IF;
 END IF;
 RETURN NEW;
END;
$qualification_enforce$;
REVOKE ALL ON FUNCTION material_qualification.enforce() FROM PUBLIC;
CREATE TRIGGER qualified_material_job AFTER INSERT ON material_judgment_job.jobs FOR EACH ROW EXECUTE FUNCTION material_qualification.enforce();
CREATE TRIGGER qualified_material_attempt BEFORE INSERT ON material_execution.attempts FOR EACH ROW EXECUTE FUNCTION material_qualification.enforce();
GRANT SELECT,INSERT ON material_qualification.intents TO tender_api;
GRANT SELECT ON material_qualification.acceptances TO tender_api;
COMMIT;
