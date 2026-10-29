-- Optional B6, installed after B5. Same table, same runtime permissions.
-- Preserve the original single-node validator and all immutable v1 records.
-- No runtime role is granted any new privilege by this extension.
BEGIN;
SET LOCAL search_path=design,public;
ALTER FUNCTION authoring_exact_check_manual_record(uuid) RENAME TO authoring_exact_check_single_text_record;
CREATE FUNCTION authoring_exact_check_multi_text_record(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_manual_revisions; parentq record; rootq design.authoring_exact_revisions;
 r design.section_revisions; parent design.section_revisions; cmd design.commands;
 snapshot design.draft_snapshots; previous design.draft_snapshots;
 m jsonb; request jsonb; original_node jsonb; node_count bigint; expected jsonb; expected_result jsonb;
 old_structure jsonb; new_structure jsonb; replacement text; edit jsonb; reconstructed jsonb; changes jsonb;
BEGIN
 SELECT * INTO q FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 SELECT * INTO parentq FROM design.authoring_exact_revision_records WHERE id=q.parent_qualification_id;
 SELECT * INTO rootq FROM design.authoring_exact_revisions WHERE id=q.root_qualification_id;
 SELECT * INTO r FROM design.section_revisions WHERE id=q.section_revision_id;
 SELECT * INTO parent FROM design.section_revisions WHERE id=q.parent_revision_id;
 SELECT * INTO cmd FROM design.commands WHERE id=q.command_id;
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision;
 SELECT * INTO previous FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision-1;
 m=q.manifest; request=q.before_action->'request'; reconstructed=parent.content;
 IF q.id IS NULL OR parentq.id IS NULL OR rootq.id IS NULL OR r.id IS NULL OR parent.id IS NULL
  OR cmd.id IS NULL OR snapshot.id IS NULL OR previous.id IS NULL
  OR q.bid_id IS DISTINCT FROM r.bid_id OR q.draft_id IS DISTINCT FROM r.draft_id OR q.section_id IS DISTINCT FROM r.section_id
  OR q.bid_id IS DISTINCT FROM rootq.bid_id OR q.draft_id IS DISTINCT FROM rootq.draft_id OR q.section_id IS DISTINCT FROM rootq.section_id
  OR q.bid_id IS DISTINCT FROM parentq.bid_id OR q.draft_id IS DISTINCT FROM parentq.draft_id OR q.section_id IS DISTINCT FROM parentq.section_id
  OR parentq.section_revision_id IS DISTINCT FROM parent.id OR parent.section_id IS DISTINCT FROM r.section_id
  OR parent.bid_id IS DISTINCT FROM r.bid_id OR parent.draft_id IS DISTINCT FROM r.draft_id
  OR r.revision IS DISTINCT FROM parent.revision+1 OR r.schema_digest IS DISTINCT FROM parent.schema_digest
  OR q.input_id IS DISTINCT FROM rootq.input_id OR parentq.input_id IS DISTINCT FROM q.input_id
  OR r.digest::text IS DISTINCT FROM design.authoring_package_digest(r.content) OR r.created_by IS DISTINCT FROM q.actor_id
  OR q.parent_qualification_id=q.id OR parentq.draft_revision>=q.draft_revision
  OR q.root_qualification_id IS DISTINCT FROM (CASE WHEN parentq.manifest->>'protocol'='authoring-exact-revision/1'
      THEN parentq.id ELSE (parentq.manifest#>>'{origin,root_qualification_id}')::uuid END)
  OR EXISTS(SELECT FROM design.authoring_exact_revisions other WHERE other.id=q.id OR other.section_revision_id=q.section_revision_id
      OR (other.draft_id=q.draft_id AND other.draft_revision=q.draft_revision))
  OR jsonb_typeof(request) IS DISTINCT FROM 'object'
  OR NOT (request ?& ARRAY['protocol','base_draft_revision','section_revision_id','edits','reason'])
  OR request-ARRAY['protocol','base_draft_revision','section_revision_id','edits','reason'] <> '{}'::jsonb
  OR request->'base_draft_revision' IS DISTINCT FROM to_jsonb(q.draft_revision-1)
  OR request->>'section_revision_id' IS DISTINCT FROM parent.id::text
  OR request->>'protocol' IS DISTINCT FROM 'authoring-exact-multi-text-edit/1'
  OR jsonb_typeof(request->'edits') IS DISTINCT FROM 'array'
  OR jsonb_typeof(request->'reason') IS DISTINCT FROM 'string' OR length(request->>'reason') NOT BETWEEN 1 AND 1000
  OR NOT ((request->>'reason') ~ '[^[:space:]]') OR regexp_replace(request->>'reason',E'[\n\t]','','g') ~ '[[:cntrl:]]'
  OR q.before_action IS DISTINCT FROM jsonb_build_object('request',request,'base_snapshot_id',previous.id,'base_snapshot_digest',previous.digest)
  OR previous.digest::text IS DISTINCT FROM design.authoring_package_digest(previous.manifest)
  OR cmd.actor_id IS DISTINCT FROM q.actor_id OR cmd.command_kind IS DISTINCT FROM 'authoring-exact-text-edit'
  OR cmd.target_id IS DISTINCT FROM q.draft_id
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',request,'if_match',q.request_condition))
  OR q.request_condition IS DISTINCT FROM '"draft:'||q.draft_id::text||':'||(q.draft_revision-1)::text||'"' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(request->'edits') NOT BETWEEN 2 AND 20
  OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(request->'edits')) <> jsonb_array_length(request->'edits')
  OR (SELECT sum(length(value->>'replacement_text')) FROM jsonb_array_elements(request->'edits')) > 20000 THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 changes='[]'::jsonb;
 FOR edit IN SELECT value FROM jsonb_array_elements(request->'edits') LOOP
  replacement=edit->>'replacement_text';
  IF jsonb_typeof(edit) IS DISTINCT FROM 'object'
   OR NOT (edit ?& ARRAY['node_id','before_node_digest','replacement_text'])
   OR edit-ARRAY['node_id','before_node_digest','replacement_text'] <> '{}'::jsonb
   OR jsonb_typeof(edit->'node_id') IS DISTINCT FROM 'string' OR length(edit->>'node_id') NOT BETWEEN 1 AND 128
   OR jsonb_typeof(edit->'before_node_digest') IS DISTINCT FROM 'string' OR (edit->>'before_node_digest') !~ '^[0-9a-f]{64}$'
   OR jsonb_typeof(edit->'replacement_text') IS DISTINCT FROM 'string' OR length(replacement)>20000
   OR regexp_replace(replacement,E'[\n\t]','','g') ~ '[[:cntrl:]]' THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
  WITH RECURSIVE nodes(value) AS (
    SELECT parent.content UNION ALL SELECT child FROM nodes n CROSS JOIN LATERAL jsonb_array_elements(coalesce(n.value->'content','[]'::jsonb)) child
  ) SELECT count(*),jsonb_agg(value)->0 INTO node_count,original_node FROM nodes WHERE value#>>'{attrs,id}'=edit->>'node_id';
  IF node_count<>1 OR original_node->>'type' NOT IN('paragraph','heading')
   OR design.authoring_package_digest(original_node) IS DISTINCT FROM edit->>'before_node_digest'
   OR EXISTS(SELECT FROM jsonb_array_elements(original_node->'content') child
     WHERE child->>'type' IS DISTINCT FROM 'text' OR coalesce(child->'marks','[]'::jsonb)<>'[]'::jsonb)
   OR design.authoring_exact_replace(parent.content,edit->>'node_id',replacement)=parent.content THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
  reconstructed=design.authoring_exact_replace(reconstructed,edit->>'node_id',replacement);
  changes=changes||jsonb_build_array(jsonb_build_object('node_id',edit->'node_id',
    'before_node_digest',edit->'before_node_digest','replacement_text_digest',encode(sha256(convert_to(replacement,'UTF8')),'hex')));
 END LOOP;
 IF r.content IS DISTINCT FROM reconstructed OR r.content=parent.content
  OR r.content->'attrs' IS DISTINCT FROM parent.content->'attrs' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 expected=jsonb_build_object('protocol','authoring-exact-manual-revision/2','id',q.id,'bid_id',q.bid_id,'draft_id',q.draft_id,
  'draft_revision',q.draft_revision,'section_id',q.section_id,'section_revision_id',r.id,'section_revision',r.revision,
  'section_digest',r.digest,'schema_digest',r.schema_digest,'parent_section_revision_id',parent.id,
  'parent_section_revision',parent.revision,'parent_section_digest',parent.digest,'input',rootq.manifest->'input',
  'origin',jsonb_build_object('kind','manual_multi_text_edit','parent_qualification_id',parentq.id,'parent_qualification_digest',parentq.digest,
   'root_qualification_id',rootq.id,'root_qualification_digest',rootq.digest,'command_id',cmd.id,'actor_id',q.actor_id,
   'before_action_digest',design.authoring_package_digest(q.before_action),'edits',changes,
   'reason',request->'reason'),
  'source_scope','exact_package_context','source_refs_digest',design.authoring_package_digest(r.content#>'{attrs,source_refs}'),
  'rule_ids_digest',design.authoring_package_digest(r.content#>'{attrs,rule_ids}'),'method',m->'method',
  'method_digest',design.authoring_package_digest(m->'method'),'candidate_adopted',false,'content_correctness_certified',false);
 IF m IS DISTINCT FROM expected OR q.digest::text IS DISTINCT FROM design.authoring_package_digest(m)
  OR m#>>'{method,protocol}' IS DISTINCT FROM 'authoring-exact-text-edit-policy/2'
  OR m#>>'{method,supported_content}' IS DISTINCT FROM 'plain_text_stable_nodes'
  OR jsonb_typeof(m#>'{method,source_sha256}') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_MANIFEST_INVALID' USING ERRCODE='23514'; END IF;
 expected_result=jsonb_build_object('protocol','authoring-exact-text-edit-result/2','bid_id',q.bid_id,
  'draft_id',q.draft_id,'draft_revision',q.draft_revision,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest,
  'parent_section_revision_id',parent.id,'section_revision_id',r.id,'section_digest',r.digest,
  'qualification',jsonb_build_object('manifest',m,'digest',q.digest));
 IF cmd.response IS DISTINCT FROM jsonb_build_object('body',expected_result,'status',200,
    'headers',jsonb_build_object('ETag','"draft:'||q.draft_id::text||':'||q.draft_revision::text||'"'))
  OR NOT EXISTS(SELECT FROM design.audit_entries e WHERE e.command_id=cmd.id AND e.actor_id=q.actor_id AND e.bid_id=q.bid_id
    AND e.event_type='authoring.exact_text_edited' AND e.payload=jsonb_build_object('qualification_id',q.id,
     'qualification_digest',q.digest,'section_revision_id',r.id,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_RECEIPT_INVALID' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.draft_snapshot_sections WHERE snapshot_id=previous.id AND section_revision_id=parent.id)
  OR NOT EXISTS(SELECT FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id AND section_revision_id=r.id)
  OR EXISTS(SELECT FROM design.draft_snapshot_sections old WHERE old.snapshot_id=previous.id AND old.section_revision_id<>parent.id
    AND NOT EXISTS(SELECT FROM design.draft_snapshot_sections cur WHERE cur.snapshot_id=snapshot.id
      AND cur.section_revision_id=old.section_revision_id AND cur.ordinal=old.ordinal))
  OR (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=previous.id)
    <> (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id)
  OR snapshot.manifest->'title' IS DISTINCT FROM previous.manifest->'title' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_SNAPSHOT_INVALID' USING ERRCODE='23514'; END IF;
 old_structure=previous.manifest->'authoring_structure'; new_structure=snapshot.manifest->'authoring_structure';
 IF old_structure IS NULL THEN
  IF new_structure IS NOT NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 ELSE
  expected=jsonb_set(old_structure-'id'-'digest','{nodes}',(
   SELECT jsonb_agg(CASE WHEN n.value->>'section_id'=q.section_id::text THEN jsonb_set(n.value,'{section_revision}',to_jsonb(r.revision))
    ELSE n.value END ORDER BY n.ord) FROM jsonb_array_elements(old_structure->'nodes') WITH ORDINALITY n(value,ord)));
  IF new_structure IS NULL OR new_structure-'id'-'digest' IS DISTINCT FROM expected
   OR new_structure->>'digest' IS DISTINCT FROM design.authoring_package_digest(new_structure-'digest')
   OR NOT EXISTS(SELECT FROM design.authoring_structure_versions v WHERE v.id=(new_structure->>'id')::uuid AND v.bid_id=q.bid_id
    AND v.draft_id=q.draft_id AND v.snapshot_id=snapshot.id AND v.draft_revision=q.draft_revision AND v.digest::text=new_structure->>'digest') THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 END IF;
 IF EXISTS(SELECT FROM jsonb_array_elements(r.content#>'{attrs,source_refs}') ref WHERE NOT EXISTS(
  SELECT FROM retrieval.citations cite WHERE cite.bid_id=q.bid_id AND cite.target_object_id=r.id AND cite.purpose='authoring'
   AND cite.source_id::text=ref.value->>'source_id' AND cite.source_revision::text=ref.value->>'source_revision'
   AND cite.evidence_id::text=ref.value->>'evidence_id')) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_CITATION_BINDING_INVALID' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_exact_check_manual_record(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE version text;
BEGIN
 SELECT manifest->>'protocol' INTO version FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 IF version='authoring-exact-manual-revision/2' THEN
  PERFORM design.authoring_exact_check_multi_text_record(selected_revision);
 ELSE
  PERFORM design.authoring_exact_check_single_text_record(selected_revision);
 END IF;
END $$;
REVOKE ALL ON FUNCTION authoring_exact_check_manual_record(uuid),authoring_exact_check_multi_text_record(uuid)
 FROM PUBLIC,tender_api,tender_worker;
COMMIT;
