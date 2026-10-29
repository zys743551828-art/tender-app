-- Human opinion on one immutable scope-review row. No model/result/qualification updates.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_review_decisions(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 run_id uuid NOT NULL,
 requirement_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 sequence_no bigint NOT NULL CHECK(sequence_no BETWEEN 1 AND 9007199254740991),
 previous_id uuid,
 previous_digest sha256,
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL,
 FOREIGN KEY(bid_id,run_id) REFERENCES bid_package_review_runs(bid_id,id),
 UNIQUE(bid_id,run_id,requirement_id,sequence_no),
 UNIQUE(bid_id,run_id,requirement_id,id,digest),
 UNIQUE(bid_id,run_id,requirement_id,id,digest,sequence_no),
 UNIQUE NULLS NOT DISTINCT(bid_id,run_id,requirement_id,previous_id),
 FOREIGN KEY(bid_id,run_id,requirement_id,previous_id,previous_digest)
 REFERENCES bid_package_review_decisions(bid_id,run_id,requirement_id,id,digest),
 CHECK((sequence_no=1 AND previous_id IS NULL AND previous_digest IS NULL)
 OR (sequence_no>1 AND previous_id IS NOT NULL AND previous_digest IS NOT NULL)),
 CHECK(previous_id IS DISTINCT FROM id),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE INDEX bid_package_review_decision_history ON bid_package_review_decisions
 (bid_id,run_id,requirement_id,sequence_no DESC,id DESC);
CREATE TABLE bid_package_review_decision_heads(
 bid_id uuid NOT NULL,
 run_id uuid NOT NULL,
 requirement_id uuid NOT NULL,
 decision_id uuid NOT NULL,
 digest sha256 NOT NULL,
 sequence_no bigint NOT NULL,
 PRIMARY KEY(bid_id,run_id,requirement_id),
 FOREIGN KEY(bid_id,run_id,requirement_id,decision_id,digest,sequence_no)
 REFERENCES bid_package_review_decisions(bid_id,run_id,requirement_id,id,digest,sequence_no)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_review_decisions
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE DELETE ON bid_package_review_decision_heads
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION bid_scope_review_decision_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE r design.bid_package_review_runs; result design.bid_package_review_results;
 h design.bid_package_review_decision_heads; m jsonb; original jsonb; previous jsonb; k text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_review_decision_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM 1 FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM design.bid_profiles WHERE bid_id=NEW.bid_id
 AND archived_at IS NULL AND phase NOT IN('closed','terminated')) THEN
  RAISE EXCEPTION 'package_review_decision_work_closed' USING ERRCODE='23514'; END IF;
 SELECT * INTO r FROM design.bid_package_review_runs WHERE bid_id=NEW.bid_id AND id=NEW.run_id;
 SELECT * INTO result FROM design.bid_package_review_results WHERE bid_id=NEW.bid_id AND run_id=NEW.run_id;
 IF r.id IS NULL OR result.run_id IS NULL OR NOT EXISTS(SELECT 1 FROM design.operations
 WHERE id=r.operation_id AND bid_id=NEW.bid_id AND state='succeeded') THEN
  RAISE EXCEPTION 'package_review_decision_result_unavailable' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(result.manifest->'matrix') x
 WHERE x->>'requirement_id'=NEW.requirement_id::text)<>1 THEN
  RAISE EXCEPTION 'package_review_decision_requirement' USING ERRCODE='23514'; END IF;
 SELECT x INTO original FROM jsonb_array_elements(result.manifest->'matrix') x
 WHERE x->>'requirement_id'=NEW.requirement_id::text;
 m:=NEW.manifest;
 previous:=CASE WHEN NEW.previous_id IS NULL THEN 'null'::jsonb
 ELSE jsonb_build_object('id',NEW.previous_id,'digest',NEW.previous_digest) END;
 IF NOT design.package_json_keys(m,ARRAY['version','id','actor_id','created_at','sequence_no','scope',
 'frozen_input_id','execution_input_id','run_id','requirement_id','input_digest','result_digest','row_digest',
 'previous_head','state','reason','selected_quotes','inventory_complete','formal_scoring_eligible','submission_eligible'])
 OR m->>'version' IS DISTINCT FROM 'package-review-human-decision/1'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->'sequence_no' IS DISTINCT FROM to_jsonb(NEW.sequence_no)
 OR m->>'created_at' IS DISTINCT FROM to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
 OR NEW.created_at>clock_timestamp()
 OR m->'scope' IS DISTINCT FROM r.input_manifest->'scope'
 OR m->>'frozen_input_id' IS DISTINCT FROM r.input_manifest#>>'{frozen_input,id}'
 OR m->>'execution_input_id' IS DISTINCT FROM r.execution_input_id::text
 OR m->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR m->>'requirement_id' IS DISTINCT FROM NEW.requirement_id::text
 OR m->>'input_digest' IS DISTINCT FROM r.input_digest
 OR m->>'result_digest' IS DISTINCT FROM result.digest
 OR m->>'row_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(original),'UTF8')),'hex')
 OR m->'previous_head' IS DISTINCT FROM previous
 OR jsonb_typeof(m->'state') IS DISTINCT FROM 'string'
 OR m->>'state' NOT IN('confirmed','rejected','needs_review')
 OR jsonb_typeof(m->'reason') IS DISTINCT FROM 'string'
 OR length(m->>'reason') NOT BETWEEN 1 AND 2000 OR m->>'reason' !~ '[^[:space:]]'
 OR jsonb_typeof(m->'selected_quotes') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'package_review_decision_binding' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['inventory_complete','formal_scoring_eligible','submission_eligible'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'package_review_decision_never_qualified' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF jsonb_array_length(m->'selected_quotes')>40
 OR jsonb_array_length(m->'selected_quotes')<>(SELECT count(DISTINCT q) FROM jsonb_array_elements(m->'selected_quotes') q)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(m->'selected_quotes') selected WHERE NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements((original->'target_quotes')||(original->'authority_quotes')) q WHERE q=selected)) THEN
  RAISE EXCEPTION 'package_review_decision_evidence' USING ERRCODE='23514'; END IF;
 SELECT * INTO h FROM design.bid_package_review_decision_heads
 WHERE bid_id=NEW.bid_id AND run_id=NEW.run_id AND requirement_id=NEW.requirement_id FOR UPDATE;
 IF (h.decision_id IS NULL AND (NEW.previous_id IS NOT NULL OR NEW.sequence_no<>1))
 OR (h.decision_id IS NOT NULL AND (NEW.previous_id IS DISTINCT FROM h.decision_id
 OR NEW.previous_digest IS DISTINCT FROM h.digest OR NEW.sequence_no IS DISTINCT FROM h.sequence_no+1)) THEN
  RAISE EXCEPTION 'package_review_decision_head_changed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER package_review_decision_binding BEFORE INSERT ON bid_package_review_decisions
 FOR EACH ROW EXECUTE FUNCTION bid_scope_review_decision_guard();

CREATE FUNCTION bid_scope_review_decision_head_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE d design.bid_package_review_decisions;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_review_decision_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM 1 FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM design.bid_profiles WHERE bid_id=NEW.bid_id
 AND archived_at IS NULL AND phase NOT IN('closed','terminated')) THEN
  RAISE EXCEPTION 'package_review_decision_work_closed' USING ERRCODE='23514'; END IF;
 SELECT * INTO d FROM design.bid_package_review_decisions WHERE bid_id=NEW.bid_id
 AND run_id=NEW.run_id AND requirement_id=NEW.requirement_id AND id=NEW.decision_id
 AND digest=NEW.digest AND sequence_no=NEW.sequence_no;
 IF d.id IS NULL THEN RAISE EXCEPTION 'package_review_decision_head_binding' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF d.previous_id IS NOT NULL OR d.sequence_no<>1 THEN
   RAISE EXCEPTION 'package_review_decision_head_initial' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.bid_id IS DISTINCT FROM OLD.bid_id OR NEW.run_id IS DISTINCT FROM OLD.run_id
  OR NEW.requirement_id IS DISTINCT FROM OLD.requirement_id OR d.previous_id IS DISTINCT FROM OLD.decision_id
  OR d.previous_digest IS DISTINCT FROM OLD.digest OR d.sequence_no IS DISTINCT FROM OLD.sequence_no+1 THEN
   RAISE EXCEPTION 'package_review_decision_head_cas' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER package_review_decision_head_binding BEFORE INSERT OR UPDATE ON bid_package_review_decision_heads
 FOR EACH ROW EXECUTE FUNCTION bid_scope_review_decision_head_guard();

CREATE FUNCTION bid_scope_review_decision_complete_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; body jsonb; ack jsonb; expected_payload jsonb;
BEGIN
 m:=NEW.manifest;
 IF NOT EXISTS(SELECT 1 FROM design.bid_package_review_decision_heads h
 WHERE h.bid_id=NEW.bid_id AND h.run_id=NEW.run_id AND h.requirement_id=NEW.requirement_id
 AND h.sequence_no>=NEW.sequence_no) THEN
  RAISE EXCEPTION 'package_review_decision_head_missing' USING ERRCODE='23514'; END IF;
 body:=jsonb_build_object('result_digest',m->'result_digest','row_digest',m->'row_digest',
 'expected_head',m->'previous_head','state',m->'state','reason',m->'reason','selected_quotes',m->'selected_quotes');
 SELECT c.response INTO ack FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id
 AND c.command_kind='package-scope-review-human-decision' AND c.target_id=NEW.run_id
 AND c.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',body,'if_match',NULL)),'UTF8')),'hex');
 IF ack IS DISTINCT FROM jsonb_build_object('status',201,'headers','{}'::jsonb,
 'body',jsonb_build_object('manifest',m,'digest',NEW.digest)) THEN
  RAISE EXCEPTION 'package_review_decision_ack' USING ERRCODE='23514'; END IF;
 expected_payload:=jsonb_build_object('decision_id',NEW.id,'decision_digest',NEW.digest,'run_id',NEW.run_id,
 'requirement_id',NEW.requirement_id,'result_digest',m->'result_digest','row_digest',m->'row_digest',
 'state',m->'state','previous_decision_id',NEW.previous_id);
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id
 AND a.actor_id=NEW.actor_id AND a.bid_id=NEW.bid_id AND a.event_type='package.scope_review.human_decision'
 AND a.payload=expected_payload) THEN
  RAISE EXCEPTION 'package_review_decision_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER package_review_decision_complete AFTER INSERT ON bid_package_review_decisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_scope_review_decision_complete_guard();
REVOKE ALL ON FUNCTION bid_scope_review_decision_guard(),bid_scope_review_decision_head_guard(),
 bid_scope_review_decision_complete_guard() FROM PUBLIC;
COMMIT;
