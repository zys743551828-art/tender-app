-- Fresh environments only. Independent immutable whole-package input records, never review jobs.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_review_inputs(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bids(id),
 package_id uuid NOT NULL REFERENCES bid_packages(id),
 revision_id uuid NOT NULL REFERENCES bid_package_revisions(id),
 inventory_id uuid NOT NULL REFERENCES bid_package_requirement_inventories(id),
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 digest sha256 NOT NULL,
 evidence_text text NOT NULL,
 evidence_digest sha256 NOT NULL,
 frozen_at timestamptz NOT NULL,
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest),
 CHECK(encode(sha256(convert_to(evidence_text,'UTF8')),'hex')=evidence_digest),
 UNIQUE(bid_id,id)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_review_inputs
 FOR EACH ROW EXECUTE FUNCTION append_only();

-- Protect absent fact heads as well as updates, matching native decision/source serialization.
CREATE FUNCTION bid_review_fact_serial_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.bid_id IS DISTINCT FROM NEW.bid_id THEN
  RAISE EXCEPTION 'review_fact_head_rebind' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN PERFORM design.lock_worker_bid(OLD.bid_id); RETURN OLD; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id); RETURN NEW;
END $$;
CREATE TRIGGER review_fact_serial BEFORE INSERT OR UPDATE OR DELETE ON fact_heads
 FOR EACH ROW EXECUTE FUNCTION bid_review_fact_serial_guard();

CREATE FUNCTION bid_review_frozen_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE inv design.bid_package_requirement_inventories; own design.bid_package_revisions;
 official design.bid_package_revisions; root jsonb; selected jsonb; context jsonb; fhead jsonb; item jsonb;
 key text; doc jsonb; member jsonb; expected_pages jsonb; expected_blocks jsonb; current_id uuid; current_revision bigint; actual_count bigint; captured_count bigint; basis_text text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'review_freeze_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO inv FROM design.bid_package_requirement_inventories WHERE id=NEW.inventory_id AND bid_id=NEW.bid_id AND package_id=NEW.package_id AND target_revision_id=NEW.revision_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'review_freeze_inventory_scope' USING ERRCODE='23514'; END IF;
 SELECT * INTO own FROM design.bid_package_revisions WHERE id=NEW.revision_id AND package_id=NEW.package_id;
 SELECT * INTO official FROM design.bid_package_revisions WHERE id=inv.authority_revision_id;
 root=NEW.evidence_text::jsonb; selected=root->'selection'; context=root->'context';
 IF NOT design.package_json_keys(NEW.manifest,ARRAY['version','kind','id','bid_id','package_id','revision_id','inventory_id','actor_id','command_id','input_digest','context_digest','evidence_digest','execution_context','as_of','frozen_at','blockers','review_ready','launch_available'])
 OR NEW.manifest->>'version' IS DISTINCT FROM 'package-review-frozen-input/1'
 OR NEW.manifest->>'kind' IS DISTINCT FROM 'frozen_input'
 OR NEW.manifest->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.manifest->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR NEW.manifest->>'package_id' IS DISTINCT FROM NEW.package_id::text
 OR NEW.manifest->>'revision_id' IS DISTINCT FROM NEW.revision_id::text
 OR NEW.manifest->>'inventory_id' IS DISTINCT FROM NEW.inventory_id::text
 OR NEW.manifest->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR NEW.manifest->>'command_id' IS DISTINCT FROM NEW.command_id::text
 OR NEW.manifest->'review_ready' IS DISTINCT FROM 'false'::jsonb
 OR NEW.manifest->'launch_available' IS DISTINCT FROM 'false'::jsonb
 OR NEW.manifest->>'evidence_digest' IS DISTINCT FROM NEW.evidence_digest::text
 OR (NEW.manifest->>'frozen_at')::timestamptz IS DISTINCT FROM NEW.frozen_at
 THEN RAISE EXCEPTION 'review_freeze_manifest_shape' USING ERRCODE='23514'; END IF;
 IF root->>'version' IS DISTINCT FROM 'package-review-evidence/1'
 OR selected->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR selected->'target'->'manifest' IS DISTINCT FROM own.manifest
 OR selected->'target'->'identity' IS DISTINCT FROM own.identity_snapshot
 OR selected->'target'->>'digest' IS DISTINCT FROM own.digest::text
 OR selected->'authority'->'manifest' IS DISTINCT FROM official.manifest
 OR selected->'authority'->'identity' IS DISTINCT FROM official.identity_snapshot
 OR selected->'authority'->>'digest' IS DISTINCT FROM official.digest::text
 OR selected->'inventory' IS DISTINCT FROM jsonb_build_object('manifest',inv.manifest,'digest',inv.digest)
 OR NEW.manifest->>'input_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(selected),'UTF8')),'hex')
 THEN RAISE EXCEPTION 'review_freeze_selection_mismatch' USING ERRCODE='23514'; END IF;
 IF selected->'coverage' IS DISTINCT FROM 'null'::jsonb AND NOT EXISTS(
 SELECT 1 FROM design.bid_package_coverage_attempts a WHERE a.bid_id=NEW.bid_id AND a.inventory_id=NEW.inventory_id
 AND selected->'coverage'=jsonb_build_object('manifest',a.manifest,'digest',a.digest)) THEN
 RAISE EXCEPTION 'review_freeze_coverage_scope' USING ERRCODE='23514'; END IF;
 IF context->>'version' IS DISTINCT FROM 'package-review-context/1'
 OR context->>'kind' IS DISTINCT FROM 'candidate'
 OR context->>'input_digest' IS DISTINCT FROM NEW.manifest->>'input_digest'
 OR context->>'purpose' IS DISTINCT FROM 'prebid_compliance'
 OR context->'method'->'executor_available' IS DISTINCT FROM 'false'::jsonb
 OR context->'policy'->'formal_scoring_eligible' IS DISTINCT FROM 'false'::jsonb
 OR context->'method'->'formal_scoring_eligible' IS DISTINCT FROM 'false'::jsonb
 OR context->'policy'->'executor_available' IS DISTINCT FROM 'false'::jsonb
 OR context->'method'->>'execution_status' IS DISTINCT FROM 'not_implemented'
 OR context->'facts'->>'qualification' IS DISTINCT FROM 'not_validated'
 OR context->'facts'->>'value_encoding' IS DISTINCT FROM 'postgresql-jsonb-text'
 OR NEW.manifest->'execution_context'->'executor_available' IS DISTINCT FROM 'false'::jsonb
 OR NEW.manifest->'execution_context'->'formal_scoring_eligible' IS DISTINCT FROM 'false'::jsonb
 OR NEW.manifest->>'context_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(context-'as_of'),'UTF8')),'hex')
 OR NEW.manifest->'execution_context'->>'snapshot_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(context),'UTF8')),'hex')
 OR context->>'as_of' IS DISTINCT FROM NEW.manifest->>'as_of'
 OR jsonb_typeof(root->'documents') IS DISTINCT FROM 'array'
 OR jsonb_typeof(NEW.manifest->'blockers') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.manifest->'blockers')<1
 THEN RAISE EXCEPTION 'review_freeze_context_mismatch' USING ERRCODE='23514'; END IF;
 IF context->'sources' IS DISTINCT FROM inv.manifest->'source_snapshot'
 OR jsonb_array_length(root->'documents') IS DISTINCT FROM (jsonb_array_length(own.manifest->'members')+jsonb_array_length(official.manifest->'members')) THEN
 RAISE EXCEPTION 'review_freeze_document_scope' USING ERRCODE='23514'; END IF;
 FOR doc IN SELECT value FROM jsonb_array_elements(root->'documents') LOOP
  SELECT value INTO member FROM jsonb_array_elements(CASE doc->>'package_role' WHEN 'target' THEN own.manifest->'members' WHEN 'authority' THEN official.manifest->'members' ELSE '[]'::jsonb END)
  WHERE value->>'member_id'=doc->>'member_id';
  IF member IS NULL OR doc->>'document_version_id' IS DISTINCT FROM member->>'document_version_id'
  OR doc->>'parse_id' IS DISTINCT FROM member->'parse'->>'parse_run_id'
  OR doc->>'digest' IS DISTINCT FROM member->>'file_digest'
  OR doc->>'parser_digest' IS DISTINCT FROM member->'parse'->>'parser_digest'
  OR doc->>'config_digest' IS DISTINCT FROM member->'parse'->>'config_digest'
  OR doc->'page_count' IS DISTINCT FROM member->'page_count'
  OR doc->>'coverage' IS DISTINCT FROM 'complete' OR doc->'gaps' IS DISTINCT FROM '[]'::jsonb OR doc ? 'object_key'
  OR NOT EXISTS(SELECT 1 FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=NEW.bid_id AND v.id=(doc->>'document_version_id')::uuid AND b.id=(doc->>'blob_id')::uuid AND b.digest::text=doc->>'digest' AND b.byte_size=(doc->>'byte_size')::bigint)
  THEN RAISE EXCEPTION 'review_freeze_document_binding' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY physical_page),'[]'::jsonb) INTO expected_pages FROM (SELECT physical_page,quality,gaps FROM design.pages WHERE bid_id=NEW.bid_id AND parse_id=(doc->>'parse_id')::uuid) p;
  SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY physical_page,ordinal,id),'[]'::jsonb) INTO expected_blocks FROM (SELECT id,physical_page,ordinal,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE bid_id=NEW.bid_id AND parse_id=(doc->>'parse_id')::uuid) e;
  IF doc->'pages' IS DISTINCT FROM expected_pages OR doc->'blocks' IS DISTINCT FROM expected_blocks THEN
   RAISE EXCEPTION 'review_freeze_evidence_binding' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT (d->>'package_role',d->>'member_id')) FROM jsonb_array_elements(root->'documents') d) IS DISTINCT FROM jsonb_array_length(root->'documents')::bigint THEN
 RAISE EXCEPTION 'review_freeze_duplicate_member' USING ERRCODE='23514'; END IF;
 FOR key IN SELECT unnest(ARRAY['method','policy','facts','sources']) LOOP
  IF context->>(key||'_digest') IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(context->key),'UTF8')),'hex')
  OR NEW.manifest->'execution_context'->>(key||'_digest') IS DISTINCT FROM context->>(key||'_digest') THEN
   RAISE EXCEPTION 'review_freeze_component_digest' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF NEW.manifest->'execution_context'->>'semantic_digest' IS DISTINCT FROM NEW.manifest->>'context_digest'
 OR NEW.manifest->'execution_context'->>'as_of' IS DISTINCT FROM context->>'as_of'
 OR (context->>'as_of')::timestamptz>NEW.frozen_at OR NEW.frozen_at>clock_timestamp() THEN
 RAISE EXCEPTION 'review_freeze_observation_time' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id AND c.target_id=NEW.inventory_id AND c.command_kind='package-review-input-freeze'
 AND c.response->'body'=jsonb_build_object('manifest',NEW.manifest,'digest',NEW.digest)
 AND c.response->>'status'='201') THEN
 RAISE EXCEPTION 'review_freeze_command_scope' USING ERRCODE='23514'; END IF;
 -- Existing deferred authority check revalidates all rules, package/identity/source heads and effectivity at commit.
 PERFORM design.bid_requirement_final_recheck(NEW.inventory_id);
 IF NOT EXISTS(SELECT 1 FROM design.bid_package_requirement_heads WHERE target_revision_id=NEW.revision_id AND inventory_id=NEW.inventory_id) THEN
 RAISE EXCEPTION 'review_freeze_inventory_stale' USING ERRCODE='23514'; END IF;
 SELECT jsonb_build_object('fact_set_id',h.fact_set_id,'revision',h.revision,'fact_set_digest',s.digest) INTO fhead
 FROM design.fact_heads h LEFT JOIN design.fact_sets s ON s.bid_id=h.bid_id AND s.id=h.fact_set_id WHERE h.bid_id=NEW.bid_id;
 fhead=coalesce(fhead,jsonb_build_object('fact_set_id',NULL,'revision',0,'fact_set_digest',NULL));
 IF context->'facts'->'head' IS DISTINCT FROM fhead THEN RAISE EXCEPTION 'review_freeze_fact_head_stale' USING ERRCODE='23514'; END IF;
 SELECT count(*) INTO actual_count FROM design.fact_items WHERE bid_id=NEW.bid_id AND fact_set_id=(fhead->>'fact_set_id')::uuid;
 captured_count=jsonb_array_length(context->'facts'->'items');
 IF captured_count IS DISTINCT FROM actual_count OR captured_count IS DISTINCT FROM
 (SELECT count(DISTINCT f->'fact'->>'id') FROM jsonb_array_elements(context->'facts'->'items') f) THEN RAISE EXCEPTION 'review_freeze_fact_scope' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(context->'facts'->'items') LOOP
  IF NOT EXISTS(SELECT 1 FROM design.fact_items f JOIN design.fact_sets s ON s.bid_id=f.bid_id AND s.id=f.fact_set_id WHERE f.bid_id=NEW.bid_id AND f.fact_set_id=(fhead->>'fact_set_id')::uuid AND f.id=(item->'fact'->>'id')::uuid
  AND item->'fact'=jsonb_build_object('id',f.id,'bid_id',f.bid_id,'fact_set_id',f.fact_set_id,'subject',f.subject,'scope',f.scope,'name',f.name,'value_jsonb_text',f.value::text,'unit',f.unit,'evidence_ids',f.evidence_ids,'fact_set_digest',s.digest)) THEN
   RAISE EXCEPTION 'review_freeze_fact_content' USING ERRCODE='23514';
  END IF;
  SELECT decision_id,revision INTO current_id,current_revision FROM design.decision_heads WHERE bid_id=NEW.bid_id AND object_kind='fact' AND object_id=(item->'fact'->>'id')::uuid;
  IF item->'decision'->>'id' IS DISTINCT FROM current_id::text OR (item->'decision'->>'decision_revision')::bigint IS DISTINCT FROM current_revision THEN
   RAISE EXCEPTION 'review_freeze_fact_decision_stale' USING ERRCODE='23514';
  END IF;
  SELECT (payload->'basis')::text INTO basis_text FROM design.audit_entries WHERE bid_id=NEW.bid_id AND event_type='human.decision_recorded' AND payload->>'decision_id'=current_id::text ORDER BY created_at DESC,id DESC LIMIT 1;
  IF item->>'decision_basis_jsonb_text' IS DISTINCT FROM basis_text THEN RAISE EXCEPTION 'review_freeze_fact_basis_stale' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER frozen_review_complete AFTER INSERT ON bid_package_review_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_review_frozen_guard();
REVOKE ALL ON FUNCTION bid_review_fact_serial_guard(),bid_review_frozen_guard() FROM PUBLIC;
COMMIT;
