-- One native submission head; exact whole-package facts never impersonate one body.
SET search_path=design,public;

ALTER TABLE submission_records ADD COLUMN subject_kind text NOT NULL DEFAULT 'single_body'
 CHECK(subject_kind IN ('single_body','bid_package'));
ALTER TABLE submission_records ALTER COLUMN body_version_id DROP NOT NULL;
ALTER TABLE submission_records DROP CONSTRAINT submission_records_check;
ALTER TABLE submission_records ADD CONSTRAINT submission_subject_binding CHECK(
 (subject_kind='single_body' AND body_version_id IS NOT NULL
   AND (kind<>'standard' OR (review_id IS NOT NULL AND gate_snapshot IS NOT NULL)))
 OR (subject_kind='bid_package' AND body_version_id IS NULL AND review_id IS NULL AND gate_snapshot IS NOT NULL)
);

CREATE FUNCTION package_submission_digest(value jsonb) RETURNS text LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
 SELECT encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex')
$$;

CREATE TABLE bid_package_submission_bindings(
 submission_id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bids(id),
 package_id uuid NOT NULL,
 revision_id uuid NOT NULL,
 authority_revision_id uuid REFERENCES bid_package_revisions(id),
 inventory_id uuid,
 review_run_id uuid,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,submission_id) REFERENCES submission_records(bid_id,id),
 FOREIGN KEY(package_id,bid_id) REFERENCES bid_packages(id,bid_id),
 FOREIGN KEY(package_id,revision_id) REFERENCES bid_package_revisions(package_id,id),
 FOREIGN KEY(bid_id,inventory_id) REFERENCES bid_package_requirement_inventories(bid_id,id),
 FOREIGN KEY(bid_id,review_run_id) REFERENCES bid_package_review_runs(bid_id,id),
 CHECK(octet_length(manifest::text)<=67108864),
 CHECK(digest=package_submission_digest(manifest)),
 CHECK((manifest->>'version'='package-submission-binding/1'
  AND manifest->>'submission_id'=submission_id::text AND manifest->>'bid_id'=bid_id::text
  AND manifest->>'command_id'=command_id::text
  AND manifest->'subject'->>'kind'='bid_package'
  AND manifest->'subject'->>'package_id'=package_id::text
  AND manifest->'subject'->>'revision_id'=revision_id::text
  AND manifest->'subject'->>'bid_id'=bid_id::text) IS TRUE)
);
CREATE INDEX bid_package_submission_history ON bid_package_submission_bindings(bid_id,package_id,revision_id,submission_id);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_submission_bindings
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE OR REPLACE FUNCTION validate_standard_submission() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE reviewed_body uuid; selected_kind text; previous_kind text;
BEGIN
 IF NEW.supersedes_id IS NOT NULL THEN
  SELECT subject_kind INTO previous_kind FROM design.submission_records
   WHERE bid_id=NEW.bid_id AND id=NEW.supersedes_id;
  IF previous_kind='bid_package' AND NEW.subject_kind<>'bid_package' THEN
   RAISE EXCEPTION 'package_submission_cannot_become_single_body' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.subject_kind='bid_package' THEN
  IF current_setting('transaction_isolation')<>'read committed' THEN
   RAISE EXCEPTION 'package_submission_requires_read_committed' USING ERRCODE='25001';
  END IF;
  PERFORM id FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
  PERFORM pg_advisory_xact_lock(90127,1);
  IF NEW.body_version_id IS NOT NULL OR NEW.review_id IS NOT NULL THEN
   RAISE EXCEPTION 'package_submission_has_legacy_body' USING ERRCODE='23514';
  END IF;
  -- The implemented gate proves no semantic completeness. A checkbox or SQL caller
  -- cannot promote a fact to a pre-submission standard approval.
  IF NEW.kind='standard' THEN
   RAISE EXCEPTION 'package_submission_gate_unproven' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.kind='standard' THEN
  SELECT i.body_version_id INTO reviewed_body
   FROM design.review_runs r JOIN design.review_inputs i ON i.bid_id=r.bid_id AND i.id=r.input_id
   WHERE r.bid_id=NEW.bid_id AND r.id=NEW.review_id;
  SELECT artifact_kind INTO selected_kind FROM design.document_versions WHERE bid_id=NEW.bid_id AND id=NEW.body_version_id;
  IF reviewed_body IS DISTINCT FROM NEW.body_version_id OR selected_kind IS DISTINCT FROM 'bid_body' THEN
   RAISE EXCEPTION 'submission_body_mismatch' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END;
$$;

CREATE FUNCTION package_submission_sources(versions uuid[]) RETURNS jsonb LANGUAGE sql VOLATILE
 SET search_path=pg_catalog,design,retrieval AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object(
  'source_id',s.source_id,'ancestor_id',n.id,'document_version_id',n.document_version_id,
  'policy_class',n.policy_class,'known_at',n.known_at,'revision',h.revision,
  'status',h.status,'valid_from',h.valid_from,'valid_until',h.valid_until)
  ORDER BY s.source_id,n.id),'[]'::jsonb)
 FROM retrieval.source_ancestors s JOIN retrieval.source_nodes n ON n.id=s.ancestor_id
 LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
 WHERE s.source_id IN(SELECT id FROM retrieval.source_nodes WHERE document_version_id=ANY(versions))
$$;

CREATE FUNCTION package_submission_originals(bid uuid,target uuid,authority uuid,attachment uuid)
 RETURNS jsonb LANGUAGE sql VOLATILE SET search_path=pg_catalog,design,retrieval AS $$
 WITH direct AS (
  SELECT document_version_id AS id,'target'::text AS role FROM design.bid_package_members WHERE revision_id=target
  UNION ALL SELECT document_version_id,'authority' FROM design.bid_package_members WHERE revision_id=authority
  UNION ALL SELECT attachment,'submission_attachment' WHERE attachment IS NOT NULL
 ), all_roles AS (
  SELECT * FROM direct
  UNION ALL
  SELECT ancestor.document_version_id,'source_ancestor' FROM direct d
  JOIN retrieval.source_nodes source ON source.document_version_id=d.id
  JOIN retrieval.source_ancestors a ON a.source_id=source.id
  JOIN retrieval.source_nodes ancestor ON ancestor.id=a.ancestor_id
  WHERE ancestor.document_version_id IS NOT NULL
 ), grouped AS (
  SELECT id,jsonb_agg(DISTINCT role ORDER BY role) AS roles FROM all_roles GROUP BY id
 )
 SELECT coalesce(jsonb_agg(jsonb_build_object(
  'document_version_id',v.id,'digest',b.digest,'byte_size',b.byte_size,'media_type',b.media_type,
  'artifact_kind',v.artifact_kind,'original_name',v.original_name,'roles',r.roles)
  ORDER BY v.id),'[]'::jsonb)
 FROM grouped r JOIN design.document_versions v ON v.id=r.id AND v.bid_id=bid
 JOIN design.blobs b ON b.id=v.blob_id
$$;

CREATE FUNCTION package_submission_head_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE selected design.submission_records; binding design.bid_package_submission_bindings;
BEGIN
 SELECT * INTO selected FROM design.submission_records WHERE bid_id=NEW.bid_id AND id=NEW.submission_id;
 IF TG_OP='UPDATE' AND EXISTS(SELECT FROM design.submission_records s WHERE s.id=OLD.submission_id AND s.subject_kind='bid_package')
    AND selected.subject_kind<>'bid_package' THEN
  RAISE EXCEPTION 'package_submission_cannot_become_single_body' USING ERRCODE='23514';
 END IF;
 IF selected.subject_kind<>'bid_package' THEN RETURN NEW; END IF;
 SELECT * INTO binding FROM design.bid_package_submission_bindings WHERE submission_id=selected.id;
 IF binding.submission_id IS NULL OR NEW.revision IS DISTINCT FROM (binding.manifest->>'head_revision')::bigint THEN
  RAISE EXCEPTION 'package_submission_head_unbound' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.revision<>1 OR selected.supersedes_id IS NOT NULL OR binding.manifest->'request'->'expected_head'<>'null'::jsonb THEN
   RAISE EXCEPTION 'package_submission_initial_head_invalid' USING ERRCODE='23514';
  END IF;
 ELSE
  IF NEW.bid_id<>OLD.bid_id OR NEW.revision<>OLD.revision+1 OR selected.supersedes_id IS DISTINCT FROM OLD.submission_id
   OR binding.manifest->'request'->'expected_head' IS DISTINCT FROM jsonb_build_object('id',OLD.submission_id,'revision',OLD.revision) THEN
   RAISE EXCEPTION 'package_submission_head_cas_invalid' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER package_submission_head BEFORE INSERT OR UPDATE ON submission_heads
 FOR EACH ROW EXECUTE FUNCTION package_submission_head_guard();

CREATE FUNCTION package_submission_binding_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE binding design.bid_package_submission_bindings; s design.submission_records;
 command design.commands; m jsonb; selected jsonb; context jsonb; gate jsonb; request jsonb;
 target design.bid_package_revisions; authority design.bid_package_revisions;
 inventory design.bid_package_requirement_inventories; run design.bid_package_review_runs;
 source_versions uuid[]; originals jsonb; receipt jsonb; item jsonb; actual jsonb; expected_evidence jsonb; expected_view jsonb;
BEGIN
 IF TG_TABLE_NAME='submission_records' THEN
  SELECT * INTO binding FROM design.bid_package_submission_bindings WHERE submission_id=NEW.id;
 ELSE
  SELECT * INTO binding FROM design.bid_package_submission_bindings WHERE submission_id=NEW.submission_id;
 END IF;
 IF binding.submission_id IS NULL THEN RAISE EXCEPTION 'package_submission_binding_missing' USING ERRCODE='23514'; END IF;
 SELECT * INTO s FROM design.submission_records WHERE id=binding.submission_id AND bid_id=binding.bid_id;
 SELECT * INTO command FROM design.commands WHERE id=binding.command_id;
 m=binding.manifest; selected=m->'selection'; context=m->'context'; gate=m->'gate'->'manifest'; request=m->'request';
 IF package_json_keys(m,ARRAY['version','submission_id','bid_id','subject','selection','selection_request','package_identity','recorded_identity',
  'submitted_at','recorded_at','assessed_at','actor_id','command_id','request','request_digest','if_match','input_digest','context','review_run',
  'inventory_proof','gate','originals','evidence','attachment_sources','supersedes_id','head_revision','platform_submission_verified',
  'pre_submission_system_check_verified','original_bytes_verified']) IS NOT TRUE
  OR package_json_keys(selected,ARRAY['target','authority','inventory','coverage']) IS NOT TRUE
  OR package_json_keys(context,ARRAY['method_digest','current','rule_decisions','risk_history','current_submission_head','originals','original_sources']) IS NOT TRUE
  OR package_json_keys(request,ARRAY['kind','selection','input_digest','evidence','submitted_at','explanation','expected_head','correction_reason']) IS NOT TRUE
  OR s.subject_kind<>'bid_package' OR s.body_version_id IS NOT NULL OR s.review_id IS NOT NULL
  OR s.kind<>'offline_fact' OR request->>'kind'<>s.kind
  OR m->'platform_submission_verified'<>'false'::jsonb OR m->'pre_submission_system_check_verified'<>'false'::jsonb
  OR m->'original_bytes_verified'<>'true'::jsonb
  OR gate->>'version'<>'package-submission-gate/1'
  OR gate->'allowed'<>'false'::jsonb OR gate->'submission_eligible'<>'false'::jsonb
  OR gate->'inventory_complete'<>'false'::jsonb OR gate->'formal_scoring_eligible'<>'false'::jsonb
  OR gate->'publication_authorized'<>'false'::jsonb OR gate->'platform_submission_verified'<>'false'::jsonb
  OR gate->>'policy_digest' IS DISTINCT FROM context->>'method_digest'
  OR package_submission_digest(gate)::text IS DISTINCT FROM m->'gate'->>'digest'
  OR s.gate_snapshot IS DISTINCT FROM m->'gate'
  OR s.created_by::text IS DISTINCT FROM m->>'actor_id'
  OR s.supersedes_id IS DISTINCT FROM (m->>'supersedes_id')::uuid
  OR s.submitted_at IS DISTINCT FROM (m->>'submitted_at')::timestamptz
  OR s.submitted_at IS DISTINCT FROM (request->>'submitted_at')::timestamptz
  OR s.created_at IS DISTINCT FROM (m->>'recorded_at')::timestamptz
  OR (m->>'assessed_at')::timestamptz IS DISTINCT FROM (gate->>'checked_at')::timestamptz
  OR s.submitted_at>s.created_at OR s.created_at>clock_timestamp()
  OR (m->>'assessed_at')::timestamptz>s.created_at
  OR command.id IS NULL OR command.command_kind<>'package-submission-register'
  OR command.target_id<>binding.bid_id OR command.actor_id<>s.created_by
  OR command.created_at>(m->>'assessed_at')::timestamptz
  OR command.created_at>s.created_at
  OR command.request_digest::text IS DISTINCT FROM m->>'request_digest'
  OR command.request_digest IS DISTINCT FROM package_submission_digest(jsonb_build_object(
    'body',request||jsonb_build_object('scope',jsonb_build_array(binding.bid_id,binding.package_id,binding.revision_id),'supersedes_id',s.supersedes_id),
    'if_match',m->'if_match'))
  OR jsonb_typeof(request->'explanation')<>'string' OR length(btrim(request->>'explanation')) NOT BETWEEN 1 AND 2000
  OR (s.supersedes_id IS NULL AND (request->'expected_head'<>'null'::jsonb OR request->'correction_reason'<>'null'::jsonb))
  OR (s.supersedes_id IS NOT NULL AND (jsonb_typeof(request->'correction_reason')<>'string' OR length(btrim(request->>'correction_reason')) NOT BETWEEN 1 AND 2000))
 THEN RAISE EXCEPTION 'package_submission_record_unbound' USING ERRCODE='23514'; END IF;

 SELECT * INTO target FROM design.bid_package_revisions WHERE id=binding.revision_id AND package_id=binding.package_id;
 IF target.id IS NULL OR selected->'target'->'manifest' IS DISTINCT FROM target.manifest
  OR selected->'target'->>'digest' IS DISTINCT FROM target.digest::text
  OR selected->'target'->'identity' IS DISTINCT FROM target.identity_snapshot
  OR target.manifest->>'kind'<>'bid'
  OR jsonb_array_length(target.manifest->'members')<1
  OR target.manifest->'scope'->>'bid_id'<>binding.bid_id::text
  OR m->'package_identity' IS DISTINCT FROM target.identity_snapshot
  OR m->'recorded_identity' IS DISTINCT FROM design.identity_snapshot_v2(binding.bid_id)
  OR m->'recorded_identity' IS DISTINCT FROM context->'current'->'current'->'identity'
  OR m->'subject' IS DISTINCT FROM jsonb_build_object('kind','bid_package','bid_id',binding.bid_id,'package_id',binding.package_id,'revision_id',binding.revision_id,'package_digest',target.digest)
  OR gate->'subject' IS DISTINCT FROM m->'subject'||jsonb_build_object('identity_digest',m->'package_identity'->>'digest')
  OR m->'selection_request' IS DISTINCT FROM request->'selection'
  OR m->'selection_request'->>'package_id'<>binding.package_id::text
  OR m->'selection_request'->>'revision_id'<>binding.revision_id::text
  OR m->'selection_request'->>'package_digest'<>target.digest::text
 THEN RAISE EXCEPTION 'package_submission_package_mismatch' USING ERRCODE='23514'; END IF;
 IF binding.inventory_id IS NULL THEN
  IF binding.authority_revision_id IS NOT NULL OR binding.review_run_id IS NOT NULL
   OR selected->'authority'<>'null'::jsonb OR selected->'inventory'<>'null'::jsonb OR selected->'coverage'<>'null'::jsonb
   OR m->'review_run'<>'null'::jsonb OR m->'inventory_proof'<>'null'::jsonb
   OR request->'selection'->'inventory'<>'null'::jsonb OR request->'selection'->'coverage'<>'null'::jsonb
   OR request->'selection'->'review_run'<>'null'::jsonb OR context->'rule_decisions'<>'[]'::jsonb
  THEN RAISE EXCEPTION 'package_submission_unselected_inventory' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=binding.inventory_id AND bid_id=binding.bid_id;
  SELECT * INTO authority FROM design.bid_package_revisions WHERE id=binding.authority_revision_id;
  IF inventory.target_revision_id<>target.id OR inventory.authority_revision_id IS DISTINCT FROM authority.id
   OR selected->'inventory' IS DISTINCT FROM jsonb_build_object('manifest',inventory.manifest,'digest',inventory.digest)
   OR selected->'authority'->'manifest' IS DISTINCT FROM authority.manifest
   OR selected->'authority'->>'digest' IS DISTINCT FROM authority.digest::text
   OR selected->'authority'->'identity' IS DISTINCT FROM authority.identity_snapshot
   OR authority.manifest->>'kind'<>'authority' OR authority.manifest->'scope' IS DISTINCT FROM target.manifest->'scope'
   OR request->'selection'->'inventory' IS DISTINCT FROM jsonb_build_object('id',inventory.id,'digest',inventory.digest)
  THEN RAISE EXCEPTION 'package_submission_inventory_mismatch' USING ERRCODE='23514'; END IF;
  IF selected->'coverage'<>'null'::jsonb THEN
   IF NOT EXISTS(SELECT FROM design.bid_package_coverage_attempts a WHERE a.bid_id=binding.bid_id AND a.inventory_id=inventory.id
    AND a.id=(selected->'coverage'->'manifest'->>'id')::uuid
    AND selected->'coverage'=jsonb_build_object('manifest',a.manifest,'digest',a.digest)
    AND request->'selection'->'coverage'=jsonb_build_object('id',a.id,'digest',a.digest)) THEN
    RAISE EXCEPTION 'package_submission_coverage_mismatch' USING ERRCODE='23514';
   END IF;
  ELSIF request->'selection'->'coverage'<>'null'::jsonb THEN
   RAISE EXCEPTION 'package_submission_coverage_unselected' USING ERRCODE='23514';
  END IF;
  IF jsonb_array_length(context->'rule_decisions')<>jsonb_array_length(inventory.manifest->'requirements')
   OR EXISTS(SELECT FROM jsonb_array_elements(inventory.manifest->'requirements') q
      WHERE 1<>(SELECT count(*) FROM jsonb_array_elements(context->'rule_decisions') d
       WHERE d->>'rule_id'=q->>'rule_id' AND d->>'rule_digest'=q->>'rule_digest')) THEN
   RAISE EXCEPTION 'package_submission_decision_set_mismatch' USING ERRCODE='23514';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(context->'rule_decisions') LOOP
   SELECT to_jsonb(d) INTO actual FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id
    WHERE h.bid_id=binding.bid_id AND h.object_kind='rule' AND h.object_id=(item->>'rule_id')::uuid;
   IF actual IS NULL THEN
    SELECT to_jsonb(d) INTO actual FROM design.rule_carryovers r JOIN design.decisions d ON d.id=r.from_decision_id
     WHERE r.bid_id=binding.bid_id AND r.new_rule_id=(item->>'rule_id')::uuid;
   END IF;
   IF coalesce(actual,'null'::jsonb) IS DISTINCT FROM item->'decision' THEN
    RAISE EXCEPTION 'package_submission_decision_changed' USING ERRCODE='23514';
   END IF;
  END LOOP;
 END IF;
 IF binding.review_run_id IS NOT NULL THEN
  SELECT * INTO run FROM design.bid_package_review_runs WHERE id=binding.review_run_id AND bid_id=binding.bid_id;
  IF run.id IS NULL OR run.input_manifest->'scope' IS DISTINCT FROM jsonb_build_object('bid_id',binding.bid_id,'package_id',binding.package_id,'revision_id',binding.revision_id,'inventory_id',binding.inventory_id)
   OR m->'review_run'->>'id'<>run.id::text OR m->'review_run'->>'input_digest'<>run.input_digest::text
   OR request->'selection'->'review_run' IS DISTINCT FROM jsonb_build_object('id',run.id,'input_digest',run.input_digest,
     'result_digest',(SELECT digest FROM design.bid_package_review_results WHERE run_id=run.id)) THEN
   RAISE EXCEPTION 'package_submission_run_mismatch' USING ERRCODE='23514';
  END IF;
 ELSIF m->'review_run'<>'null'::jsonb OR request->'selection'->'review_run'<>'null'::jsonb THEN
  RAISE EXCEPTION 'package_submission_run_unselected' USING ERRCODE='23514';
 END IF;

 SELECT array_agg(DISTINCT document_version_id ORDER BY document_version_id) INTO source_versions
  FROM design.bid_package_members WHERE revision_id IN(binding.revision_id,binding.authority_revision_id);
 IF context->'original_sources' IS DISTINCT FROM design.package_submission_sources(source_versions)
  OR context->'current'->'sources' IS DISTINCT FROM design.bid_requirement_source_snapshot(binding.revision_id,binding.authority_revision_id)
  OR context->'originals' IS DISTINCT FROM design.package_submission_originals(binding.bid_id,binding.revision_id,binding.authority_revision_id,NULL)
 THEN RAISE EXCEPTION 'package_submission_sources_changed' USING ERRCODE='23514'; END IF;
 source_versions=array_append(source_versions,(m->'evidence'->>'document_version_id')::uuid);
 originals=design.package_submission_originals(binding.bid_id,binding.revision_id,binding.authority_revision_id,(m->'evidence'->>'document_version_id')::uuid);
 IF m->'originals' IS DISTINCT FROM originals
  OR m->'attachment_sources' IS DISTINCT FROM design.package_submission_sources(source_versions)
  OR NOT (m->'originals' @> jsonb_build_array(m->'evidence'))
  OR NOT (m->'evidence'->'roles' @> '["submission_attachment"]'::jsonb)
  OR request->'evidence' IS DISTINCT FROM jsonb_build_object('document_version_id',m->'evidence'->'document_version_id','digest',m->'evidence'->'digest','byte_size',m->'evidence'->'byte_size')
  OR jsonb_array_length(originals)<1 OR jsonb_array_length(originals)>2000
 THEN RAISE EXCEPTION 'package_submission_originals_mismatch' USING ERRCODE='23514'; END IF;
 IF m->>'input_digest' IS DISTINCT FROM request->>'input_digest'
  OR m->>'input_digest' IS DISTINCT FROM package_submission_digest(jsonb_build_object(
   'selection',selected,'selection_request',m->'selection_request','context',context,
   'review_run',m->'review_run','inventory_proof',m->'inventory_proof'))::text
  OR gate->'selection'->>'digest' IS DISTINCT FROM package_submission_digest(selected)::text THEN
  RAISE EXCEPTION 'package_submission_input_mismatch' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT FROM design.submission_heads h WHERE h.bid_id=binding.bid_id AND h.submission_id=s.id AND h.revision=(m->>'head_revision')::bigint)
  OR NOT EXISTS(SELECT FROM design.audit_entries a WHERE a.command_id=command.id AND a.bid_id=binding.bid_id AND a.actor_id=s.created_by
   AND a.event_type=CASE WHEN s.supersedes_id IS NULL THEN 'submission.recorded' ELSE 'submission.corrected' END
   AND a.payload->>'submission_id'=s.id::text AND a.payload->>'binding_digest'=binding.digest::text AND a.payload->>'subject_kind'='bid_package') THEN
  RAISE EXCEPTION 'package_submission_native_receipt_missing' USING ERRCODE='23514';
 END IF;
 expected_evidence=jsonb_build_object(
  'evidence_ref',m->'evidence'->'document_version_id','evidence_digest',m->'evidence'->'digest',
  'evidence_type','user_declared_package_submission_attachment','platform_submission_verified',false,
  'pre_submission_system_check_verified',false,'identity',m->'package_identity','recorded_identity',m->'recorded_identity',
  'package_binding_digest',binding.digest,'actual_package',m->'subject','registration_assessed_at',m->'assessed_at',
  'checks_label','未经过系统完整检查；已记录完整投标包实际提交事实','explanation',request->'explanation',
  'correction_reason',request->'correction_reason','open_risk_snapshot',gate->'gates'->'known_blocking_risks');
 IF s.evidence IS DISTINCT FROM expected_evidence THEN
  RAISE EXCEPTION 'package_submission_evidence_mismatch' USING ERRCODE='23514';
 END IF;
 expected_view=jsonb_build_object(
  'id',s.id,'bid_id',s.bid_id,'subject_kind','bid_package','body_version_id',NULL,'review_id',NULL,
  'kind',s.kind,'submitted_at',m->'submitted_at','recorded_at',m->'recorded_at','recorded_by',s.created_by,
  'gate_checked',false,'evidence_ref',m->'evidence'->'document_version_id','current',true,'supersedes_id',s.supersedes_id,
  'identity',m->'package_identity','original_name',NULL,'artifact_kind',NULL,
  'checks_label','未经过系统完整检查；已记录完整投标包实际提交事实',
  'open_risk_snapshot',gate->'gates'->'known_blocking_risks','platform_submission_verified',false,
  'explanation',request->'explanation','correction_reason',request->'correction_reason',
  'package_binding',jsonb_build_object('manifest',m,'digest',binding.digest));
 receipt=command.response;
 IF receipt IS NULL OR receipt->>'status'<>'201'
  OR receipt->'body'->'command' IS DISTINCT FROM jsonb_build_object('command_id',command.id,'actor_id',command.actor_id,'idempotency_key',command.idempotency_key,
      'request_digest',command.request_digest,'request',request,'if_match',m->'if_match')
  OR receipt->'body'->'submission' IS DISTINCT FROM expected_view
  OR jsonb_typeof(receipt->'headers'->'X-Bid-ETag')<>'string'
 THEN RAISE EXCEPTION 'package_submission_ack_mismatch' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER package_submission_binding_complete AFTER INSERT ON bid_package_submission_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION package_submission_binding_guard();
CREATE CONSTRAINT TRIGGER package_submission_native_complete AFTER INSERT ON submission_records
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(NEW.subject_kind='bid_package') EXECUTE FUNCTION package_submission_binding_guard();

REVOKE ALL ON TABLE bid_package_submission_bindings FROM PUBLIC,tender_worker;
GRANT SELECT,INSERT ON bid_package_submission_bindings TO tender_api;
REVOKE ALL ON FUNCTION package_submission_digest(jsonb),package_submission_sources(uuid[]),package_submission_originals(uuid,uuid,uuid,uuid),package_submission_head_guard(),package_submission_binding_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_submission_digest(jsonb),package_submission_sources(uuid[]),package_submission_originals(uuid,uuid,uuid,uuid),package_submission_head_guard(),package_submission_binding_guard() TO tender_api;
