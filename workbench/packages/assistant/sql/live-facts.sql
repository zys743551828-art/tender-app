-- Fresh reviewed schema only; after identity/2 + retrieval, before live-budget execution.
-- Invoked only by budget SECURITY DEFINER RPCs; no Worker fact-table grants.
BEGIN;
CREATE FUNCTION design.assistant_assert_live_fact(bid uuid,proof jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE f record; d record; basis jsonb; refs jsonb; closure jsonb; ref jsonb; ancestor jsonb;
 actual record; node record; identity_value jsonb; identity_hash text; source_ids uuid[];
 cursor_id uuid; seen uuid[]='{}'; mapping jsonb; adoption timestamptz; audit_basis jsonb;
 fact_id uuid=(proof->>'id')::uuid; at_time timestamptz;
BEGIN
 SELECT * INTO f FROM design.fact_items WHERE id=fact_id AND bid_id=bid;
 SELECT x.* INTO d FROM design.decision_heads h JOIN design.decisions x ON x.id=h.decision_id
 WHERE h.bid_id=bid AND h.object_kind='fact' AND h.object_id=fact_id;
 SELECT payload->'basis' INTO audit_basis FROM design.audit_entries
 WHERE event_type='human.decision_recorded' AND bid_id=bid AND payload->>'decision_id'=d.id::text
 ORDER BY created_at DESC,id DESC LIMIT 1;
 basis=proof->'basis';closure=proof->'source_closure';refs=basis->'evidence'->'references';
 IF f.id IS NULL OR d.id IS NULL OR d.bid_id IS DISTINCT FROM bid OR d.object_kind IS DISTINCT FROM 'fact'
 OR d.decision IS DISTINCT FROM 'confirmed' OR d.id::text IS DISTINCT FROM proof->>'decision_id'
 OR audit_basis IS NULL OR jsonb_typeof(basis) IS DISTINCT FROM 'object' OR basis IS DISTINCT FROM audit_basis
 OR jsonb_typeof(refs) IS DISTINCT FROM 'array' OR jsonb_typeof(closure) IS DISTINCT FROM 'array'
 OR cardinality(f.evidence_ids)=0 OR NOT(f.evidence_ids<@d.evidence_ids AND f.evidence_ids@>d.evidence_ids)
 THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 identity_value=jsonb_build_object('subject',f.subject,'scope',f.scope,'name',f.name,'value',f.value,'unit',f.unit,
 'evidence_ids',(SELECT jsonb_agg(id::text ORDER BY id::text COLLATE "C") FROM (SELECT DISTINCT unnest(f.evidence_ids) AS id) x));
 identity_hash=encode(sha256(convert_to(design.package_canonical_json(identity_value),'UTF8')),'hex');
 IF basis->>'fact_identity' IS DISTINCT FROM identity_hash
 OR basis->'evidence'->>'source_closure_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(closure),'UTF8')),'hex')
 OR (SELECT count(*) FROM jsonb_array_elements(refs)) IS DISTINCT FROM cardinality(f.evidence_ids)::bigint
 OR (SELECT count(DISTINCT value->>'evidence_id') FROM jsonb_array_elements(refs)) IS DISTINCT FROM cardinality(f.evidence_ids)::bigint
 THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 SELECT array_agg(DISTINCT (value->>'source_id')::uuid ORDER BY (value->>'source_id')::uuid) INTO source_ids FROM jsonb_array_elements(refs);
 -- The caller has already taken bid -> graph. Heads remain locked through dispatch commit.
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN
 (SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(source_ids)) ORDER BY h.source_id FOR UPDATE;
 at_time=clock_timestamp();
 IF d.created_at>at_time OR jsonb_array_length(closure)=0
 OR (SELECT count(*) FROM retrieval.source_ancestors WHERE source_id=ANY(source_ids)) IS DISTINCT FROM jsonb_array_length(closure)::bigint
 OR (SELECT count(DISTINCT (value->>'source_id',value->>'id')) FROM jsonb_array_elements(closure)) IS DISTINCT FROM jsonb_array_length(closure)::bigint
 THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(refs) LOOP
  SELECT e.*,p.document_version_id,p.coverage,page.quality,b.digest AS original_digest INTO actual
  FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id
  JOIN design.pages page ON page.parse_id=e.parse_id AND page.bid_id=e.bid_id AND page.physical_page=e.physical_page
  JOIN design.document_versions v ON v.id=p.document_version_id AND v.bid_id=p.bid_id
  JOIN design.blobs b ON b.id=v.blob_id
  WHERE e.id=(ref->>'evidence_id')::uuid AND e.bid_id=bid;
  IF actual.id IS NULL OR NOT actual.id=ANY(f.evidence_ids)
  OR actual.document_version_id::text IS DISTINCT FROM ref->>'document_version_id'
  OR actual.coverage='failed'
  OR actual.parse_id IS DISTINCT FROM (SELECT id FROM design.parse_runs WHERE document_version_id=actual.document_version_id ORDER BY created_at DESC,id DESC LIMIT 1)
  OR NOT EXISTS(SELECT FROM design.bid_profiles p WHERE p.bid_id=bid AND (p.current_body_id=actual.document_version_id OR EXISTS(
    SELECT FROM design.material_assignments a WHERE a.bid_id=bid AND a.snapshot_id=p.current_material_id AND a.document_version_id=actual.document_version_id
      AND a.role IN ('tender','supplement','drawing','boq','body','other'))))
  THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
  SELECT n.*,h.revision INTO node FROM retrieval.source_nodes n JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE n.id=(ref->>'source_id')::uuid;
  IF node.id IS NULL OR node.kind IS DISTINCT FROM 'document' OR node.document_version_id IS DISTINCT FROM actual.document_version_id
  OR node.digest IS DISTINCT FROM actual.original_digest OR node.revision IS DISTINCT FROM (ref->>'source_revision')::bigint
  OR NOT EXISTS(SELECT FROM retrieval.lineage_edges edge JOIN retrieval.source_nodes root ON root.id=edge.parent_id
    WHERE edge.child_id=node.id AND root.kind='document' AND root.document_version_id=actual.document_version_id AND root.digest=actual.original_digest)
  THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR ancestor IN SELECT value FROM jsonb_array_elements(closure) LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until INTO node FROM retrieval.source_ancestors a
  JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE a.source_id=(ancestor->>'source_id')::uuid AND a.ancestor_id=(ancestor->>'id')::uuid AND a.source_id=ANY(source_ids);
  IF node.id IS NULL OR node.id::text IS DISTINCT FROM ancestor->>'id'
  OR node.document_version_id::text IS DISTINCT FROM ancestor->>'document_version_id'
  OR node.kind IS DISTINCT FROM ancestor->>'kind' OR node.policy_class IS DISTINCT FROM ancestor->>'policy_class'
  OR node.digest::text IS DISTINCT FROM ancestor->>'digest' OR node.revision IS DISTINCT FROM (ancestor->>'revision')::bigint
  OR node.status IS DISTINCT FROM ancestor->>'status' OR node.known_at IS DISTINCT FROM (ancestor->>'known_at')::timestamptz
  OR node.valid_from IS DISTINCT FROM (ancestor->>'valid_from')::timestamptz OR node.valid_until IS DISTINCT FROM (ancestor->>'valid_until')::timestamptz
  OR node.kind IS DISTINCT FROM 'document' OR node.policy_class IS DISTINCT FROM 'prebid_content' OR node.status IS DISTINCT FROM 'published'
  OR node.known_at>at_time OR node.valid_from>at_time OR node.valid_until<=at_time
  OR NOT EXISTS(SELECT FROM design.document_versions v JOIN design.bid_profiles p ON p.bid_id=v.bid_id
    WHERE v.id=node.document_version_id AND v.bid_id=bid AND (p.current_body_id=v.id OR EXISTS(SELECT FROM design.material_assignments a
      WHERE a.bid_id=bid AND a.snapshot_id=p.current_material_id AND a.document_version_id=v.id AND a.role IN ('tender','supplement','drawing','boq','body','other'))))
  THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 END LOOP;
 cursor_id=f.id;
 WHILE cursor_id IS DISTINCT FROM d.object_id LOOP
  IF cursor_id=ANY(seen) THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
  seen=array_append(seen,cursor_id);
  SELECT item,a.created_at INTO mapping,adoption FROM design.audit_entries a CROSS JOIN LATERAL jsonb_array_elements(a.payload->'carryovers') item
  WHERE a.bid_id=bid AND a.event_type='facts.set_replaced' AND item->>'new_fact_id'=cursor_id::text ORDER BY a.created_at DESC,a.id DESC LIMIT 1;
  IF mapping IS NULL OR mapping->>'from_decision_id' IS DISTINCT FROM d.id::text OR adoption>at_time
  OR mapping->>'equivalence_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(basis),'UTF8')),'hex')
  THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
  cursor_id=(mapping->>'from_fact_id')::uuid;
  SELECT * INTO f FROM design.fact_items WHERE id=cursor_id AND bid_id=bid;
  identity_value=jsonb_build_object('subject',f.subject,'scope',f.scope,'name',f.name,'value',f.value,'unit',f.unit,
   'evidence_ids',(SELECT jsonb_agg(id::text ORDER BY id::text COLLATE "C") FROM (SELECT DISTINCT unnest(f.evidence_ids) AS id) x));
  IF f.id IS NULL OR encode(sha256(convert_to(design.package_canonical_json(identity_value),'UTF8')),'hex') IS DISTINCT FROM identity_hash
  THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION design.assistant_assert_live_fact(uuid,jsonb) FROM PUBLIC;

CREATE FUNCTION design.assistant_assert_job_authority(job uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE j record; i record; target jsonb; bid uuid; proof jsonb; authority_clock timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO i FROM design.assistant_logical_intents WHERE job_id=job;
 IF j.id IS NULL OR i.id IS NULL THEN RAISE EXCEPTION 'ASSISTANT_INTENT_INVALID' USING ERRCODE='23514'; END IF;
 target=i.target;
 IF target->>'kind'<>'general' THEN
  bid=(target->>'bid_id')::uuid;
  PERFORM id FROM design.bids WHERE id=bid FOR UPDATE;
 END IF;
 IF j.scope='global' THEN PERFORM id FROM design.assistant_global_runs WHERE id=job FOR UPDATE;
 ELSE PERFORM id FROM design.operations WHERE id=j.operation_id FOR UPDATE; END IF;
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM design.assistant_check_target(target,i.actor_id);
 IF target->>'kind'='general' THEN RETURN; END IF;
 FOR proof IN SELECT value FROM jsonb_array_elements(target->'proof'->'identity_facts') LOOP
  PERFORM design.assistant_assert_live_fact(bid,proof);
 END LOOP;
 -- One final authorization instant for every already locked ancestor: an early
 -- fact's source may expire while later facts or large closures are checked.
 authority_clock=clock_timestamp();
 IF EXISTS(SELECT FROM (
   SELECT DISTINCT (ancestor->>'id')::uuid AS id FROM jsonb_array_elements(target->'proof'->'identity_facts') fact
   CROSS JOIN LATERAL jsonb_array_elements(fact->'source_closure') ancestor
  ) frozen LEFT JOIN retrieval.source_nodes n ON n.id=frozen.id
  LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE n.id IS NULL OR h.status IS DISTINCT FROM 'published' OR n.known_at>authority_clock
   OR h.valid_from>authority_clock OR h.valid_until<=authority_clock)
 THEN RAISE EXCEPTION 'ASSISTANT_TARGET_IDENTITY_UNPROVEN' USING ERRCODE='23514'; END IF;
END $$;
REVOKE ALL ON FUNCTION design.assistant_assert_job_authority(uuid) FROM PUBLIC;
COMMIT;
