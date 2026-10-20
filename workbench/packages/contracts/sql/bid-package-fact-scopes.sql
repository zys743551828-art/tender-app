-- Append-only human scope declarations. No qualification or dispatch capability.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_fact_scopes(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 execution_input_id uuid NOT NULL,
 fact_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 previous_digest sha256,
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,execution_input_id) REFERENCES bid_package_execution_inputs(bid_id,id),
 UNIQUE(bid_id,execution_input_id,fact_id,digest),
 UNIQUE NULLS NOT DISTINCT(execution_input_id,fact_id,previous_digest),
 FOREIGN KEY(bid_id,execution_input_id,fact_id,previous_digest)
 REFERENCES bid_package_fact_scopes(bid_id,execution_input_id,fact_id,digest),
 CHECK(previous_digest IS DISTINCT FROM digest),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_fact_scopes
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE FUNCTION bid_fact_scope_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE prepared design.bid_package_execution_inputs; prior design.bid_package_fact_scopes;
 m jsonb; b jsonb; original jsonb; context jsonb; item jsonb; expected jsonb; subject_field text; k text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'fact_scope_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 m:=NEW.manifest; b:=m->'binding';
 IF NOT design.package_json_keys(m,ARRAY['version','kind','id','actor_id','command_id','recorded_at','reason','action','previous_digest','binding','subject','facts_qualified','review_ready','launch_available','publication_authorized'])
 OR m->>'version' IS DISTINCT FROM 'package-fact-scope/1' OR m->>'kind' IS DISTINCT FROM 'fact_scope_declaration'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text OR m->>'previous_digest' IS DISTINCT FROM NEW.previous_digest::text
 OR b->>'bid_id' IS DISTINCT FROM NEW.bid_id::text OR b->>'execution_input_id' IS DISTINCT FROM NEW.execution_input_id::text
 OR b->>'fact_id' IS DISTINCT FROM NEW.fact_id::text OR jsonb_typeof(m->'action') IS DISTINCT FROM 'string' OR m->>'action' NOT IN ('bind','withdraw')
 OR jsonb_typeof(m->'reason') IS DISTINCT FROM 'string' OR length(btrim(m->>'reason')) NOT BETWEEN 1 AND 2000
 OR m->>'reason' IS DISTINCT FROM btrim(m->>'reason')
 OR jsonb_typeof(m->'recorded_at') IS DISTINCT FROM 'string'
 OR m->>'recorded_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$' THEN
  RAISE EXCEPTION 'fact_scope_manifest' USING ERRCODE='23514'; END IF;
 PERFORM (m->>'recorded_at')::timestamptz;
 FOREACH k IN ARRAY ARRAY['facts_qualified','review_ready','launch_available','publication_authorized'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'fact_scope_never_authorized' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT * INTO prepared FROM design.bid_package_execution_inputs WHERE bid_id=NEW.bid_id AND id=NEW.execution_input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'fact_scope_prepared' USING ERRCODE='23514'; END IF;
 original:=prepared.manifest#>'{identity,binding}'; context:=prepared.snapshot_text::jsonb#>'{context,manifest}';
 SELECT value INTO item FROM jsonb_array_elements(context#>'{facts,items}') WHERE value#>>'{fact,id}'=NEW.fact_id::text;
 IF item IS NULL OR item#>>'{fact,bid_id}' IS DISTINCT FROM NEW.bid_id::text
 OR item#>'{fact,fact_set_id}' IS DISTINCT FROM context#>'{facts,head,fact_set_id}' THEN
  RAISE EXCEPTION 'fact_scope_fact' USING ERRCODE='23514'; END IF;
 expected:=original||jsonb_build_object('execution_input_id',NEW.execution_input_id,'execution_input_digest',prepared.digest,
 'facts_digest',context->'facts_digest','fact_set_id',context#>'{facts,head,fact_set_id}','fact_id',NEW.fact_id,
 'fact_item_digest',encode(sha256(convert_to(design.package_canonical_json(item),'UTF8')),'hex'),'proof_digest',b->'proof_digest');
 IF b IS DISTINCT FROM expected OR jsonb_typeof(b->'proof_digest') IS DISTINCT FROM 'string'
 OR b->>'proof_digest' !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'fact_scope_binding' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m->'subject',ARRAY['kind','id']) THEN RAISE EXCEPTION 'fact_scope_subject' USING ERRCODE='23514'; END IF;
 subject_field:=CASE m#>>'{subject,kind}' WHEN 'engineering_project' THEN 'engineering_project_id'
 WHEN 'lot' THEN 'lot_id' WHEN 'round' THEN 'round_id' WHEN 'bidder' THEN 'bidder_id' END;
 IF subject_field IS NULL OR context#>>'{identity,binding_status}' IS DISTINCT FROM 'confirmed'
 OR m#>'{subject,id}' IS DISTINCT FROM context->'identity'->subject_field THEN
  RAISE EXCEPTION 'fact_scope_subject' USING ERRCODE='23514'; END IF;
 IF NEW.previous_digest IS NOT NULL THEN
  SELECT * INTO prior FROM design.bid_package_fact_scopes WHERE bid_id=NEW.bid_id AND execution_input_id=NEW.execution_input_id AND fact_id=NEW.fact_id AND digest=NEW.previous_digest;
  IF NOT FOUND OR prior.manifest->'binding' IS DISTINCT FROM b THEN RAISE EXCEPTION 'fact_scope_predecessor' USING ERRCODE='23514'; END IF;
 END IF;
 IF m->>'action'='withdraw' AND (NEW.previous_digest IS NULL OR prior.manifest->>'action' IS DISTINCT FROM 'bind' OR prior.manifest->'subject' IS DISTINCT FROM m->'subject') THEN
  RAISE EXCEPTION 'fact_scope_withdrawal' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('execution_input_digest',prepared.digest,'fact_id',NEW.fact_id,'action',m->'action',
 'subject',CASE WHEN m->>'action'='bind' THEN m->'subject' ELSE 'null'::jsonb END,'reason',m->'reason','previous_digest',m->'previous_digest');
 IF NOT EXISTS(SELECT 1 FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id
 AND c.command_kind='package-fact-scope-declare' AND c.target_id=NEW.execution_input_id
 AND c.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',expected,'if_match',NULL)),'UTF8')),'hex')
 AND c.response->>'status'='201' AND c.response->'body'=jsonb_build_object('manifest',m,'digest',NEW.digest)) THEN
  RAISE EXCEPTION 'fact_scope_ack' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER fact_scope_complete AFTER INSERT ON bid_package_fact_scopes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_fact_scope_guard();
REVOKE ALL ON FUNCTION bid_fact_scope_guard() FROM PUBLIC;
COMMIT;
