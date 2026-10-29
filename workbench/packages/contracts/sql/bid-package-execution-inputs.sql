-- Prepared immutable inputs only; no operations, dispatch or publication permission.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_execution_inputs(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 frozen_input_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 snapshot_text text NOT NULL,
 snapshot_digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,frozen_input_id) REFERENCES bid_package_review_inputs(bid_id,id),
 UNIQUE(bid_id,id),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest),
 CHECK(encode(sha256(convert_to(snapshot_text,'UTF8')),'hex')=snapshot_digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_execution_inputs
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE FUNCTION bid_execution_input_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE original design.bid_package_review_inputs; m jsonb; s jsonb; i jsonb; b jsonb; x jsonb; context jsonb; k text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'execution_input_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO original FROM design.bid_package_review_inputs WHERE bid_id=NEW.bid_id AND id=NEW.frozen_input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'execution_input_scope' USING ERRCODE='23514'; END IF;
 m:=NEW.manifest; s:=NEW.snapshot_text::jsonb; i:=m->'identity'; b:=i->'binding'; context:=s->'context'; x:=context->'manifest';
 IF NOT design.package_json_keys(m,ARRAY['version','kind','id','bid_id','package_id','revision_id','inventory_id','frozen_input_id','actor_id','command_id','identity','execution_context','snapshot_digest','originals_verified_at','saved_at','blockers','review_ready','launch_available','publication_authorized'])
 OR m->>'version' IS DISTINCT FROM 'package-review-execution-input/1' OR m->>'kind' IS DISTINCT FROM 'prepared_input'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'frozen_input_id' IS DISTINCT FROM NEW.frozen_input_id::text OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text OR m->>'snapshot_digest' IS DISTINCT FROM NEW.snapshot_digest THEN
  RAISE EXCEPTION 'execution_input_manifest' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['review_ready','launch_available','publication_authorized'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb OR s->'result'->k IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'execution_input_never_authorized' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['package_id','revision_id','inventory_id','input_digest','evidence_digest'] LOOP
  IF b->k IS DISTINCT FROM original.manifest->k THEN RAISE EXCEPTION 'execution_input_binding' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['bid_id','package_id','revision_id','inventory_id','frozen_input_id'] LOOP
  IF b->k IS DISTINCT FROM m->k THEN RAISE EXCEPTION 'execution_input_scope' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF b->>'frozen_digest' IS DISTINCT FROM original.digest OR s->'binding' IS DISTINCT FROM b
 OR b->>'identity_digest' IS DISTINCT FROM (original.evidence_text::jsonb#>>'{selection,target,identity,digest}')
 OR i->>'version' IS DISTINCT FROM 'package-review-execution/1' OR i->>'kind' IS DISTINCT FROM 'identity'
 OR b->>'purpose' IS DISTINCT FROM 'prebid_compliance'
 OR i->>'content_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('version','package-review-content/1','binding',b)),'UTF8')),'hex')
 OR i->>'execution_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('version','package-review-execution/1','content_digest',i->'content_digest','rerun',i->'rerun')),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'execution_input_identity' USING ERRCODE='23514'; END IF;
 IF context->>'semantic_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(x-'as_of'),'UTF8')),'hex')
 OR context->>'snapshot_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(x),'UTF8')),'hex')
 OR b->'context_digest' IS DISTINCT FROM context->'semantic_digest'
 OR b->'input_digest' IS DISTINCT FROM x->'input_digest'
 OR b->'method_digest' IS DISTINCT FROM x->'method_digest' OR b->'policy_digest' IS DISTINCT FROM x->'policy_digest'
 OR m->'execution_context' IS DISTINCT FROM s->'result'->'current_context'
 OR m->'blockers' IS DISTINCT FROM s->'result'->'blockers'
 OR m->>'originals_verified_at' IS DISTINCT FROM s->'result'->>'checked_at' THEN
  RAISE EXCEPTION 'execution_input_context' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['method','policy','facts','sources'] LOOP
  IF x->>(k||'_digest') IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(x->k),'UTF8')),'hex') THEN
   RAISE EXCEPTION 'execution_input_context_digest' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id
 AND c.command_kind='package-review-execution-input-save' AND c.target_id=NEW.frozen_input_id
 AND c.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',jsonb_build_object('frozen_digest',b->'frozen_digest','context_digest',b->'context_digest','rerun',i->'rerun'),'if_match',NULL)),'UTF8')),'hex')
 AND c.response->>'status'='201' AND c.response->'body'=jsonb_build_object('manifest',m,'digest',NEW.digest)) THEN
  RAISE EXCEPTION 'execution_input_ack' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER execution_input_complete AFTER INSERT ON bid_package_execution_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_execution_input_guard();
REVOKE ALL ON FUNCTION bid_execution_input_guard() FROM PUBLIC;
COMMIT;
