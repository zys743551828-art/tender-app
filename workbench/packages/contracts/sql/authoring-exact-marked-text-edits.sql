-- Optional B7, installed after B6. Historical validators remain unchanged.
-- Only one existing marked text leaf may change; all marks and provenance survive.
BEGIN;
SET LOCAL search_path=design,public;
-- Fail before replacing the dispatcher: B5 alone has no renamed single checker.
DO $$
BEGIN
 IF to_regprocedure('design.authoring_exact_check_single_text_record(uuid)') IS NULL
  OR to_regprocedure('design.authoring_exact_check_multi_text_record(uuid)') IS NULL
  OR to_regprocedure('design.authoring_exact_check_manual_record(uuid)') IS NULL THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_MARKED_TEXT_EDIT_REQUIRES_B6' USING ERRCODE='55000';
 END IF;
END $$;
CREATE FUNCTION authoring_exact_check_marked_text_record(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_manual_revisions; parentq record; rootq design.authoring_exact_revisions;
 r design.section_revisions; parent design.section_revisions; cmd design.commands;
 snapshot design.draft_snapshots; previous design.draft_snapshots;
 m jsonb; request jsonb; original_node jsonb; node_count bigint; expected jsonb; expected_result jsonb;
 old_structure jsonb; new_structure jsonb; replacement text; node_path text[]; marks jsonb;
BEGIN
 SELECT * INTO q FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 SELECT * INTO parentq FROM design.authoring_exact_revision_records WHERE id=q.parent_qualification_id;
 SELECT * INTO rootq FROM design.authoring_exact_revisions WHERE id=q.root_qualification_id;
 SELECT * INTO r FROM design.section_revisions WHERE id=q.section_revision_id;
 SELECT * INTO parent FROM design.section_revisions WHERE id=q.parent_revision_id;
 SELECT * INTO cmd FROM design.commands WHERE id=q.command_id;
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision;
 SELECT * INTO previous FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision-1;
 m=q.manifest; request=q.before_action->'request'; replacement=request->>'replacement_text';
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
  OR NOT (request ?& ARRAY['protocol','base_draft_revision','section_revision_id','node_id','before_node_digest','replacement_text','reason'])
  OR request-ARRAY['protocol','base_draft_revision','section_revision_id','node_id','before_node_digest','replacement_text','reason'] <> '{}'::jsonb
  OR request->>'protocol' IS DISTINCT FROM 'authoring-exact-marked-text-edit/1'
  OR request->'base_draft_revision' IS DISTINCT FROM to_jsonb(q.draft_revision-1)
  OR request->>'section_revision_id' IS DISTINCT FROM parent.id::text
  OR jsonb_typeof(request->'node_id') IS DISTINCT FROM 'string' OR length(request->>'node_id') NOT BETWEEN 1 AND 128
  OR jsonb_typeof(request->'before_node_digest') IS DISTINCT FROM 'string' OR (request->>'before_node_digest') !~ '^[0-9a-f]{64}$'
  OR jsonb_typeof(request->'replacement_text') IS DISTINCT FROM 'string' OR length(replacement)>20000
  OR length(replacement)<1 OR btrim(replacement,U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')='' OR EXISTS(SELECT FROM regexp_split_to_table(replacement,'') ch WHERE ascii(ch)<32 OR ascii(ch)=127)
  OR jsonb_typeof(request->'reason') IS DISTINCT FROM 'string' OR length(request->>'reason') NOT BETWEEN 1 AND 1000
  OR btrim(request->>'reason',U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')='' OR EXISTS(SELECT FROM regexp_split_to_table(request->>'reason','') ch WHERE (ascii(ch)<32 AND ascii(ch) NOT IN (9,10)) OR ascii(ch)=127)
  OR q.before_action IS DISTINCT FROM jsonb_build_object('request',request,'base_snapshot_id',previous.id,'base_snapshot_digest',previous.digest)
  OR previous.digest::text IS DISTINCT FROM design.authoring_package_digest(previous.manifest)
  OR cmd.actor_id IS DISTINCT FROM q.actor_id OR cmd.command_kind IS DISTINCT FROM 'authoring-exact-text-edit'
  OR cmd.target_id IS DISTINCT FROM q.draft_id
  OR length(cmd.idempotency_key) NOT BETWEEN 1 AND 128
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',request,'if_match',q.request_condition))
  OR q.request_condition IS DISTINCT FROM '"draft:'||q.draft_id::text||':'||(q.draft_revision-1)::text||'"' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 WITH RECURSIVE nodes(value,path) AS (
   SELECT parent.content,ARRAY[]::text[] UNION ALL
   SELECT child.value,n.path||ARRAY['content',(child.ord-1)::text]
   FROM nodes n CROSS JOIN LATERAL jsonb_array_elements(coalesce(n.value->'content','[]'::jsonb)) WITH ORDINALITY child(value,ord)
 ) SELECT count(*),jsonb_agg(value)->0 INTO node_count,original_node
 FROM nodes WHERE value#>>'{attrs,id}'=request->>'node_id';
 IF node_count<>1 OR coalesce(original_node->>'type','') NOT IN('paragraph','heading')
  OR design.authoring_package_digest(original_node) IS DISTINCT FROM request->>'before_node_digest'
  OR jsonb_typeof(original_node->'content') IS DISTINCT FROM 'array'
  OR jsonb_array_length(original_node->'content')<>1
  OR original_node#>>'{content,0,type}' IS DISTINCT FROM 'text'
  OR jsonb_typeof(original_node#>'{content,0,text}') IS DISTINCT FROM 'string'
  OR jsonb_typeof(original_node#>'{content,0,marks}') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 marks=original_node#>'{content,0,marks}';
 IF jsonb_array_length(marks) NOT BETWEEN 1 AND 2
  OR EXISTS(SELECT FROM jsonb_array_elements(marks) mark WHERE mark NOT IN ('{"type":"bold"}'::jsonb,'{"type":"italic"}'::jsonb))
  OR (SELECT count(DISTINCT mark) FROM jsonb_array_elements(marks) mark)<>jsonb_array_length(marks) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 WITH RECURSIVE nodes(value,path) AS (
   SELECT parent.content,ARRAY[]::text[] UNION ALL
   SELECT child.value,n.path||ARRAY['content',(child.ord-1)::text]
   FROM nodes n CROSS JOIN LATERAL jsonb_array_elements(coalesce(n.value->'content','[]'::jsonb)) WITH ORDINALITY child(value,ord)
 ) SELECT path INTO node_path FROM nodes WHERE value#>>'{attrs,id}'=request->>'node_id';
 IF r.content IS DISTINCT FROM jsonb_set(parent.content,node_path||ARRAY['content','0','text'],to_jsonb(replacement),false)
  OR r.content=parent.content OR r.content->'attrs' IS DISTINCT FROM parent.content->'attrs' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 expected=jsonb_build_object('protocol','authoring-exact-manual-revision/3','id',q.id,'bid_id',q.bid_id,'draft_id',q.draft_id,
  'draft_revision',q.draft_revision,'section_id',q.section_id,'section_revision_id',r.id,'section_revision',r.revision,
  'section_digest',r.digest,'schema_digest',r.schema_digest,'parent_section_revision_id',parent.id,
  'parent_section_revision',parent.revision,'parent_section_digest',parent.digest,'input',rootq.manifest->'input',
  'origin',jsonb_build_object('kind','manual_marked_text_edit','parent_qualification_id',parentq.id,'parent_qualification_digest',parentq.digest,
   'root_qualification_id',rootq.id,'root_qualification_digest',rootq.digest,'command_id',cmd.id,'actor_id',q.actor_id,
   'before_action_digest',design.authoring_package_digest(q.before_action),'node_id',request->'node_id',
   'before_node_digest',request->'before_node_digest','replacement_text_digest',encode(sha256(convert_to(replacement,'UTF8')),'hex'),
   'preserved_marks_digest',design.authoring_package_digest(marks),'reason',request->'reason'),
  'source_scope','exact_package_context','source_refs_digest',design.authoring_package_digest(r.content#>'{attrs,source_refs}'),
  'rule_ids_digest',design.authoring_package_digest(r.content#>'{attrs,rule_ids}'),'method',m->'method',
  'method_digest',design.authoring_package_digest(m->'method'),'candidate_adopted',false,'content_correctness_certified',false);
 IF m IS DISTINCT FROM expected OR q.digest::text IS DISTINCT FROM design.authoring_package_digest(m)
  OR m#>>'{method,protocol}' IS DISTINCT FROM 'authoring-exact-text-edit-policy/3'
  OR m#>>'{method,supported_content}' IS DISTINCT FROM 'single_marked_text_leaf_preserve_marks'
  OR jsonb_typeof(m#>'{method,source_sha256}') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_MANIFEST_INVALID' USING ERRCODE='23514'; END IF;
 expected_result=jsonb_build_object('protocol','authoring-exact-text-edit-result/3','bid_id',q.bid_id,
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
  OR snapshot.manifest->'title' IS DISTINCT FROM previous.manifest->'title'
  OR (SELECT ordinal FROM design.draft_snapshot_sections WHERE snapshot_id=previous.id AND section_revision_id=parent.id)
    IS DISTINCT FROM (SELECT ordinal FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id AND section_revision_id=r.id) THEN
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

CREATE OR REPLACE FUNCTION authoring_exact_check_manual_record(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE version text;
BEGIN
 SELECT manifest->>'protocol' INTO version FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 IF version='authoring-exact-manual-revision/3' THEN
  PERFORM design.authoring_exact_check_marked_text_record(selected_revision);
 ELSIF version='authoring-exact-manual-revision/2' THEN
  PERFORM design.authoring_exact_check_multi_text_record(selected_revision);
 ELSE
  PERFORM design.authoring_exact_check_single_text_record(selected_revision);
 END IF;
END $$;
REVOKE ALL ON FUNCTION authoring_exact_check_manual_record(uuid),authoring_exact_check_marked_text_record(uuid)
 FROM PUBLIC,tender_api,tender_worker;
COMMIT;
