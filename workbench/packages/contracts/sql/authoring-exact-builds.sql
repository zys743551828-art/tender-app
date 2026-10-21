-- Optional B4: complete B3 snapshot builds and subsequent output admission.
-- Requires B1, B2 and B3. No direct qualification/fact-table privilege for Worker.
BEGIN;
SET LOCAL search_path=design,public;

-- SELECT-only state for RR admission. The initial proof is accepted only after
-- B3's current authority guard; every later new use must reproduce this state.
-- Hash before returning, so no fact values or decision text leave this function.
CREATE FUNCTION authoring_exact_build_dependencies(selected_input uuid) RETURNS text
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE input design.authoring_package_inputs; x jsonb; b jsonb; result jsonb;
 source_ids uuid[]; source_state jsonb; rule_state jsonb; fact_state jsonb;
 scopes jsonb; documents jsonb; authority_clock timestamptz;
BEGIN
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=selected_input;
 IF input.id IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_INPUT_MISSING' USING ERRCODE='23514'; END IF;
 x=input.context_text::jsonb; b=input.manifest->'selection'; authority_clock=clock_timestamp();
 SELECT array_agg(DISTINCT (value->>'source_id')::uuid ORDER BY (value->>'source_id')::uuid)
  INTO source_ids FROM jsonb_array_elements(x->'sources');
 SELECT coalesce(jsonb_agg(jsonb_build_object('source_id',a.source_id,'ancestor_id',a.ancestor_id,
   'node',to_jsonb(n),'head',to_jsonb(h),'effective',n.known_at<=authority_clock AND h.status='published'
    AND h.valid_from<=authority_clock AND (h.valid_until IS NULL OR h.valid_until>authority_clock))
   ORDER BY a.source_id,a.ancestor_id),'[]'::jsonb) INTO source_state
  FROM retrieval.source_ancestors a LEFT JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
  LEFT JOIN retrieval.source_heads h ON h.source_id=n.id WHERE a.source_id=ANY(source_ids);
 SELECT coalesce(jsonb_agg(jsonb_build_object('rule',to_jsonb(r),'head',to_jsonb(h),
   'carryover',to_jsonb(carry),'decision',to_jsonb(dec)) ORDER BY frozen.value->>'rule_id'),'[]'::jsonb)
  INTO rule_state FROM jsonb_array_elements(x#>'{inventory,record,manifest,requirements}') frozen
  LEFT JOIN design.rule_items r ON r.id=(frozen.value->>'rule_id')::uuid AND r.bid_id=input.bid_id
  LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
  LEFT JOIN design.rule_carryovers carry ON carry.bid_id=r.bid_id AND carry.new_rule_id=r.id
  LEFT JOIN design.decisions dec ON dec.id=coalesce(h.decision_id,carry.from_decision_id) AND dec.bid_id=r.bid_id;
 SELECT coalesce(jsonb_agg(jsonb_build_object('fact',to_jsonb(f),'head',to_jsonb(h),'decision',to_jsonb(dec))
   ORDER BY frozen.value#>>'{item,fact,id}'),'[]'::jsonb) INTO fact_state
  FROM jsonb_array_elements(x#>'{facts,items}') frozen
  LEFT JOIN design.fact_items f ON f.id=(frozen.value#>>'{item,fact,id}')::uuid AND f.bid_id=input.bid_id
  LEFT JOIN design.decision_heads h ON h.bid_id=f.bid_id AND h.object_kind='fact' AND h.object_id=f.id
  LEFT JOIN design.decisions dec ON dec.id=h.decision_id AND dec.bid_id=f.bid_id;
 SELECT coalesce(jsonb_agg(to_jsonb(latest) ORDER BY frozen.value#>>'{manifest,fact_id}'),'[]'::jsonb)
  INTO scopes FROM jsonb_array_elements(input.manifest->'fact_declarations') frozen
  LEFT JOIN LATERAL (SELECT s.* FROM design.authoring_package_fact_scopes s
    WHERE s.bid_id=input.bid_id AND s.input_id=input.id AND s.fact_id=(frozen.value#>>'{manifest,fact_id}')::uuid
    ORDER BY s.revision DESC LIMIT 1) latest ON true;
 SELECT coalesce(jsonb_agg(jsonb_build_object('document',to_jsonb(d),'blob',to_jsonb(blob),'parse',to_jsonb(p))
   ORDER BY frozen.value->>'document_version_id',frozen.value->>'parse_id'),'[]'::jsonb) INTO documents
  FROM jsonb_array_elements(x->'documents') frozen
  LEFT JOIN design.document_versions d ON d.id=(frozen.value->>'document_version_id')::uuid AND d.bid_id=input.bid_id
  LEFT JOIN design.blobs blob ON blob.id=d.blob_id
  LEFT JOIN design.parse_runs p ON p.id=(frozen.value->>'parse_id')::uuid AND p.bid_id=d.bid_id AND p.document_version_id=d.id;
 result=jsonb_build_object('protocol','authoring-exact-build-dependencies/1','input_id',input.id,
  'input_digest',input.digest,'identity',design.identity_snapshot_v2(input.bid_id),
  'project',(SELECT jsonb_build_object('phase',p.phase,'archived_at',p.archived_at,'rule_set_id',p.current_rule_set_id)
    FROM design.bid_profiles p WHERE p.bid_id=input.bid_id),
  'inventory',(SELECT jsonb_build_object('inventory',to_jsonb(i),'head',to_jsonb(h))
    FROM design.bid_package_requirement_inventories i LEFT JOIN design.bid_package_requirement_heads h ON h.inventory_id=i.id
    WHERE i.id=(b#>>'{package_context,inventory,id}')::uuid AND i.bid_id=input.bid_id),
  'fact_head',(SELECT to_jsonb(h) FROM design.fact_heads h WHERE h.bid_id=input.bid_id),
  'rules',rule_state,'facts',fact_state,'fact_declarations',scopes,'sources',source_state,'documents',documents);
 RETURN design.authoring_package_digest(result);
END $$;

CREATE FUNCTION authoring_exact_build_packet(selected_snapshot uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE snapshot design.draft_snapshots; exact jsonb; original_documents jsonb; inputs uuid[];
 dependencies jsonb; source_ids jsonb; section_digests jsonb; section_revisions jsonb; proof jsonb;
BEGIN
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE id=selected_snapshot;
 exact=design.authoring_exact_snapshot_proof(selected_snapshot);
 IF exact IS NULL THEN RETURN NULL; END IF;
 -- Bind the exact revisions to a real B3 output snapshot. Legacy sections in
 -- this snapshot retain their ordinary source guards in the build service.
 IF NOT EXISTS(SELECT FROM design.authoring_exact_revisions q WHERE q.bid_id=snapshot.bid_id
   AND q.draft_id=snapshot.draft_id AND q.draft_revision=snapshot.revision
   AND EXISTS(SELECT FROM design.draft_snapshot_sections ss WHERE ss.snapshot_id=snapshot.id AND ss.section_revision_id=q.section_revision_id)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_BUILD_SNAPSHOT_UNQUALIFIED' USING ERRCODE='23514'; END IF;
 SELECT array_agg(DISTINCT (value->>'authoring_input_id')::uuid ORDER BY (value->>'authoring_input_id')::uuid)
  INTO inputs FROM jsonb_array_elements(exact->'sections');
 SELECT jsonb_agg(jsonb_build_object('id',i.id,'digest',i.digest,'context_digest',i.context_digest,
   'dependency_digest',design.authoring_exact_build_dependencies(i.id)) ORDER BY i.id)
  INTO dependencies FROM design.authoring_package_inputs i WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id;
 SELECT jsonb_agg(value ORDER BY value->>'document_version_id',value->>'object_key') INTO original_documents
  FROM (SELECT DISTINCT jsonb_build_object('document_version_id',doc.value->'document_version_id',
     'digest',doc.value->'digest','byte_size',doc.value->'byte_size','object_key',doc.value->'object_key') AS value
   FROM design.authoring_package_inputs i CROSS JOIN LATERAL jsonb_array_elements(i.context_text::jsonb->'documents') doc
   WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id) originals;
 SELECT jsonb_agg(source_id ORDER BY source_id) INTO source_ids FROM (
  SELECT DISTINCT source.value->>'source_id' AS source_id FROM design.authoring_package_inputs i
  CROSS JOIN LATERAL jsonb_array_elements(i.context_text::jsonb->'sources') source WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id) ids;
 SELECT jsonb_agg(r.digest ORDER BY ss.ordinal),
  jsonb_agg(jsonb_build_object('section_revision_id',r.id,'section_id',r.section_id,'digest',r.digest) ORDER BY ss.ordinal)
  INTO section_digests,section_revisions FROM design.draft_snapshot_sections ss
  JOIN design.section_revisions r ON r.id=ss.section_revision_id AND r.bid_id=ss.bid_id
  WHERE ss.snapshot_id=snapshot.id AND ss.bid_id=snapshot.bid_id;
 proof=jsonb_build_object('protocol','authoring-exact-build/1','bid_id',snapshot.bid_id,'snapshot_id',snapshot.id,
  'snapshot_digest',snapshot.digest,'exact_sections_digest',exact->'digest','section_digests',section_digests,'section_revisions',section_revisions,
  'input_identities',dependencies,'direct_source_ids',source_ids,'originals_digest',design.authoring_package_digest(original_documents));
 proof=proof||jsonb_build_object('digest',design.authoring_package_digest(proof));
 RETURN jsonb_build_object('proof',proof,'originals',original_documents);
END $$;

CREATE FUNCTION authoring_exact_assert_build(selected_snapshot uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE exact jsonb; section jsonb; packet jsonb; authority_clock timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 exact=design.authoring_exact_snapshot_proof(selected_snapshot);
 IF exact IS NULL THEN RETURN NULL; END IF;
 FOR section IN SELECT value FROM jsonb_array_elements(exact->'sections') ORDER BY value->>'section_revision_id' LOOP
  PERFORM design.authoring_exact_assert_revision((section->>'section_revision_id')::uuid);
 END LOOP;
 packet=design.authoring_exact_build_packet(selected_snapshot); authority_clock=clock_timestamp();
 -- A single final instant covers all already locked ancestors, even when an
 -- earlier qualification expires during a later qualification's verification.
 IF EXISTS(SELECT FROM jsonb_array_elements_text(packet#>'{proof,direct_source_ids}') ids
   JOIN retrieval.source_ancestors a ON a.source_id=ids.value::uuid
   JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
   WHERE n.known_at>authority_clock OR h.status IS DISTINCT FROM 'published'
    OR h.valid_from IS NULL OR h.valid_from>authority_clock OR h.valid_until<=authority_clock) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_BUILD_SOURCE_EXPIRED' USING ERRCODE='23514'; END IF;
 RETURN packet;
END $$;

CREATE FUNCTION authoring_exact_build_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE input design.build_inputs; packet jsonb;
BEGIN
 IF TG_TABLE_NAME='build_inputs' THEN input=NEW;
 ELSE
  SELECT i.* INTO input FROM design.builds b JOIN design.build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
   WHERE b.id=NEW.build_id AND b.bid_id=NEW.bid_id;
 END IF;
 packet=design.authoring_exact_assert_build(input.draft_snapshot_id);
 IF input.manifest->'authoring_exact' IS DISTINCT FROM packet->'proof' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_BUILD_CHANGED' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_exact_build_input_complete AFTER INSERT ON build_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_build_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_build_output_complete AFTER INSERT ON build_outputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_build_guard();

REVOKE ALL ON FUNCTION authoring_exact_build_dependencies(uuid),authoring_exact_build_packet(uuid),
 authoring_exact_assert_build(uuid),authoring_exact_build_guard() FROM PUBLIC,tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION authoring_exact_build_packet(uuid),authoring_exact_assert_build(uuid) TO tender_api,tender_worker;
COMMIT;
