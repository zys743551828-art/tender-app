-- DRAFT: new reviewed extension only. Requires BASE through package submissions.
-- No score/historical/model table or permission is changed. No execution is granted.
BEGIN;
SET search_path=design,public;
-- Explicit owner-installed dependency. Missing native extension files abort this
-- installation; business roles receive neither database CREATE nor ownership.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public VERSION '1.1';
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
 WHERE e.extname='uuid-ossp' AND e.extversion='1.1' AND n.nspname='public')
 THEN RAISE EXCEPTION 'technical_scope_uuid_dependency_mismatch'; END IF;
END $$;

CREATE FUNCTION package_technical_digest(value jsonb) RETURNS text LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
 SELECT encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex')
$$;

CREATE FUNCTION package_technical_gap(code text,subject text,message text) RETURNS jsonb
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,design AS $$
 SELECT value||jsonb_build_object('id',design.package_technical_digest(value))
 FROM (SELECT jsonb_build_object('code',code,'subject',subject,'message',message) AS value) q
$$;

CREATE FUNCTION package_technical_text(value jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND length(value#>>'{}') BETWEEN 1 AND 2000
 AND (value#>>'{}') ~ '\S',false)
$$;

CREATE FUNCTION package_technical_nonblank(value text) RETURNS boolean LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $$
 -- The exact Unicode whitespace set stripped by Python str.strip().
 SELECT coalesce(length(btrim(value,E' \t\n\r\f'||chr(11)||chr(28)||chr(29)||chr(30)||chr(31)||
 chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||
 chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||
 chr(8239)||chr(8287)||chr(12288)))>0,false)
$$;

CREATE FUNCTION package_technical_preview_shape(p jsonb) RETURNS boolean LANGUAGE plpgsql
 IMMUTABLE SET search_path=pg_catalog,design AS $$
DECLARE v jsonb; item jsonb; field text; request jsonb;
BEGIN
 IF NOT design.package_json_keys(p,ARRAY['version','scope','basis','method','request','request_digest','context_digest','parts','rules','documents','source_snapshot','coverage','timing','original_bytes_verified','inventory_complete','scoring_ready','formal_scoring_eligible','model_execution_enabled','training_eligible'])
 OR NOT design.package_json_keys(p->'scope',ARRAY['bid_id','package_id','revision_id','inventory_id'])
 OR NOT design.package_json_keys(p->'basis',ARRAY['package_digest','authority_revision_id','authority_digest','inventory_digest','rule_set_id','rule_set_digest','identity_digest'])
 OR NOT design.package_json_keys(p->'method',ARRAY['version','digest','sources','limits'])
 OR NOT design.package_json_keys(p#>'{method,sources}',ARRAY[
 'packages/domain/package_technical_scope.py','packages/domain/bid_package_technical_scope_repository.py',
 'packages/domain/bid_package_technical_scope_service.py','packages/contracts/package_technical_scope_api.py',
 'packages/contracts/sql/bid-package-technical-scopes.sql','packages/domain/bid_package_review_documents.py',
 'packages/domain/bid_package_repository.py','packages/rag/indexing.py'])
 OR p#>'{method,limits}' IS DISTINCT FROM '{"members":500,"parts":2000,"rules":1000,"source_rows":20000,"blocks":100000,"pages":100000,"request_bytes":1048576,"snapshot_bytes":33554432,"original_bytes":1073741824}'::jsonb
 OR NOT design.package_json_keys(p->'coverage',ARRAY['state','all_part_count','selected_part_count','all_scoring_rule_count','included_rule_count','frozen_parse_member_count','gaps','visual_coverage','required_range_completeness'])
 OR (p#>>'{coverage,state}' IN('partial','unknown')) IS NOT TRUE
 THEN RETURN false; END IF;
 FOREACH field IN ARRAY ARRAY['parts','rules','documents','source_snapshot'] LOOP
  IF jsonb_typeof(p->field) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 END LOOP;
 IF jsonb_typeof(p#>'{coverage,gaps}') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOREACH field IN ARRAY ARRAY['request_digest','context_digest'] LOOP
  IF jsonb_typeof(p->field) IS DISTINCT FROM 'string' OR (p->>field ~ '^[a-f0-9]{64}$') IS NOT TRUE THEN RETURN false; END IF;
 END LOOP;
 FOR v IN SELECT value FROM jsonb_each(p#>'{method,sources}') LOOP
  IF jsonb_typeof(v) IS DISTINCT FROM 'string' OR (v#>>'{}' ~ '^[a-f0-9]{64}$') IS NOT TRUE THEN RETURN false; END IF;
 END LOOP;
 FOREACH field IN ARRAY ARRAY['all_part_count','selected_part_count','all_scoring_rule_count','included_rule_count','frozen_parse_member_count'] LOOP
  IF NOT design.package_json_integer(p->'coverage'->field,0) THEN RETURN false; END IF;
 END LOOP;
 FOR v IN SELECT * FROM jsonb_array_elements(p#>'{coverage,gaps}') LOOP
  IF NOT design.package_json_keys(v,ARRAY['id','code','subject','message'])
  OR NOT design.package_json_text(v->'code') OR NOT design.package_technical_text(v->'message')
  OR (jsonb_typeof(v->'subject') IN('string','null')) IS NOT TRUE
  OR v->>'id' IS DISTINCT FROM design.package_technical_digest(v-'id') THEN RETURN false; END IF;
 END LOOP;
 request:=p->'request';
 IF NOT design.package_json_keys(request,ARRAY['purpose','package_digest','authority_revision_id','authority_digest','inventory_id','inventory_digest','technical_part_ids','rule_scopes','reason'])
 OR jsonb_typeof(request->'technical_part_ids') IS DISTINCT FROM 'array'
 OR jsonb_typeof(request->'rule_scopes') IS DISTINCT FROM 'array'
 OR NOT design.package_technical_text(request->'reason') THEN RETURN false; END IF;
 IF jsonb_array_length(request->'technical_part_ids') NOT BETWEEN 1 AND 2000
 OR jsonb_array_length(request->'rule_scopes')>1000
 OR EXISTS(SELECT FROM jsonb_array_elements(request->'technical_part_ids') t WHERE NOT design.package_json_text(t))
 OR octet_length(convert_to(design.package_canonical_json(request),'UTF8'))>1048576
 THEN RETURN false; END IF;
 FOR v IN SELECT * FROM jsonb_array_elements(request->'rule_scopes') LOOP
  IF NOT design.package_json_keys(v,ARRAY['rule_id','rule_digest','selection','part_ids','reason'])
  OR jsonb_typeof(v->'part_ids') IS DISTINCT FROM 'array'
  OR (v->>'selection' IN('include','exclude','unclassified')) IS NOT TRUE
  OR NOT design.package_technical_text(v->'reason') THEN RETURN false; END IF;
  IF jsonb_array_length(v->'part_ids')>2000
  OR EXISTS(SELECT FROM jsonb_array_elements(v->'part_ids') t WHERE NOT design.package_json_text(t))
  OR jsonb_array_length(v->'part_ids') IS DISTINCT FROM (SELECT count(DISTINCT t) FROM jsonb_array_elements(v->'part_ids')t)
  THEN RETURN false; END IF;
 END LOOP;
 FOR v IN SELECT * FROM jsonb_array_elements(p->'parts') LOOP
  IF NOT design.package_json_keys(v,ARRAY['member_id','document_version_id','file_digest','part','selected','read_physical_pages','block_ids','text_evidence_present','visual_coverage'])
  OR NOT design.package_json_keys(v->'part',ARRAY['part_id','category','first_page','last_page','shared_attachment','heading_path'])
  OR jsonb_typeof(v->'read_physical_pages') IS DISTINCT FROM 'array'
  OR jsonb_typeof(v->'block_ids') IS DISTINCT FROM 'array'
  OR jsonb_typeof(v->'selected') IS DISTINCT FROM 'boolean'
  OR jsonb_typeof(v->'text_evidence_present') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
 END LOOP;
 FOR v IN SELECT * FROM jsonb_array_elements(p->'rules') LOOP
  IF NOT design.package_json_keys(v,ARRAY['rule_id','rule_digest','selection','part_ids','reason','rule_snapshot','requirement_digest','declared_target_part_ids','source_evidence'])
  OR jsonb_typeof(v->'rule_snapshot') IS DISTINCT FROM 'object'
  OR jsonb_typeof(v->'part_ids') IS DISTINCT FROM 'array'
  OR jsonb_typeof(v->'declared_target_part_ids') IS DISTINCT FROM 'array'
  OR jsonb_typeof(v->'source_evidence') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  FOR item IN SELECT * FROM jsonb_array_elements(v->'source_evidence') LOOP
   IF NOT design.package_json_keys(item,ARRAY['member_id','document_version_id','file_digest','parse_run_id','physical_page','evidence_id','evidence_digest','text_content','part_ids'])
   OR jsonb_typeof(item->'part_ids') IS DISTINCT FROM 'array'
   OR jsonb_typeof(item->'text_content') IS DISTINCT FROM 'string'
   OR NOT design.package_json_integer(item->'physical_page',1) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR v IN SELECT * FROM jsonb_array_elements(p->'documents') LOOP
  IF NOT design.package_json_keys(v,ARRAY['package_role','member_id','document_version_id','file_digest','byte_size','parse','page_count','pages','blocks'])
  OR (v->>'package_role' IN('target','authority')) IS NOT TRUE
  OR NOT design.package_json_keys(v->'parse',ARRAY['status','parse_run_id','parser_digest','config_digest','evidence_digest','reason'])
  OR jsonb_typeof(v->'pages') IS DISTINCT FROM 'array' OR jsonb_typeof(v->'blocks') IS DISTINCT FROM 'array'
  OR NOT design.package_json_integer(v->'byte_size',0) THEN RETURN false; END IF;
  IF jsonb_array_length(v->'pages')>100000 OR jsonb_array_length(v->'blocks')>100000 THEN RETURN false; END IF;
  FOR item IN SELECT * FROM jsonb_array_elements(v->'pages') LOOP
   IF NOT design.package_json_keys(item,ARRAY['physical_page','quality','gaps'])
   OR NOT design.package_json_integer(item->'physical_page',1)
   OR (item->>'quality' IN('usable','partial','failed')) IS NOT TRUE
   OR jsonb_typeof(item->'gaps') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
  END LOOP;
  FOR item IN SELECT * FROM jsonb_array_elements(v->'blocks') LOOP
   IF NOT design.package_json_keys(item,ARRAY['id','physical_page','ordinal','kind','text_content','digest','bbox_json','structure_json'])
   OR (item->>'kind' IN('text','table','visual_observation')) IS NOT TRUE
   OR NOT design.package_json_integer(item->'physical_page',1) OR NOT design.package_json_integer(item->'ordinal',0)
   OR jsonb_typeof(item->'text_content') IS DISTINCT FROM 'string'
   OR (jsonb_typeof(item->'bbox_json') IN('string','null')) IS NOT TRUE
   OR (jsonb_typeof(item->'structure_json') IN('string','null')) IS NOT TRUE THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR v IN SELECT * FROM jsonb_array_elements(p->'source_snapshot') LOOP
  IF NOT design.package_json_keys(v,ARRAY['source_id','ancestor_id','document_version_id','digest','kind','policy_class','known_at','revision','status','valid_from','valid_until','document_bid','original_digest'])
  OR NOT design.package_json_integer(v->'revision',1) THEN RETURN false; END IF;
  -- PostgreSQL accepts case/brace/hyphen UUID aliases. The public snapshot has
  -- one canonical spelling, so text-distinct aliases cannot replace ancestors.
  FOREACH field IN ARRAY ARRAY['source_id','ancestor_id','document_version_id','document_bid'] LOOP
   IF jsonb_typeof(v->field) IS DISTINCT FROM 'string'
   OR (v->>field ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$') IS NOT TRUE
   THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION package_technical_parts(target uuid,selected jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object(
 'member_id',m.member_id,'document_version_id',m.document_version_id,'file_digest',m.file_digest,
 'part',part.value,'selected',selected ? p.part_id,'read_physical_pages',
 (SELECT coalesce(jsonb_agg(physical_page ORDER BY physical_page),'[]'::jsonb) FROM design.pages WHERE bid_id=m.bid_id AND parse_id=m.parse_run_id AND physical_page BETWEEN p.first_page AND p.last_page),
 'block_ids',(SELECT coalesce(jsonb_agg(id ORDER BY physical_page,ordinal,id),'[]'::jsonb) FROM design.evidence_blocks WHERE bid_id=m.bid_id AND parse_id=m.parse_run_id AND physical_page BETWEEN p.first_page AND p.last_page),
 'text_evidence_present',EXISTS(SELECT FROM design.evidence_blocks WHERE bid_id=m.bid_id AND parse_id=m.parse_run_id AND physical_page BETWEEN p.first_page AND p.last_page AND kind='text' AND design.package_technical_nonblank(text_content)),
 'visual_coverage','unproven') ORDER BY m.ordinal,p.ordinal),'[]'::jsonb)
 FROM design.bid_package_members m JOIN design.bid_package_parts p ON p.revision_id=m.revision_id AND p.member_id=m.member_id
 CROSS JOIN LATERAL jsonb_array_elements(m.payload->'parts') part(value)
 WHERE m.revision_id=target AND part.value->>'part_id'=p.part_id
$$;

CREATE FUNCTION package_technical_rule_evidence(authority uuid,evidence_ids jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object('member_id',m.member_id,'document_version_id',m.document_version_id,
 'file_digest',m.file_digest,'parse_run_id',m.parse_run_id,'physical_page',b.physical_page,
 'evidence_id',b.id,'evidence_digest',b.digest,'text_content',b.text_content,
 'part_ids',(SELECT jsonb_agg(p.part_id ORDER BY p.ordinal) FROM design.bid_package_parts p
 WHERE p.revision_id=m.revision_id AND p.member_id=m.member_id AND b.physical_page BETWEEN p.first_page AND p.last_page))
 ORDER BY m.ordinal,b.physical_page,b.ordinal,b.id),'[]'::jsonb)
 FROM design.bid_package_members m JOIN design.evidence_blocks b ON b.bid_id=m.bid_id AND b.parse_id=m.parse_run_id
 WHERE m.revision_id=authority AND evidence_ids ? b.id::text AND EXISTS(SELECT FROM design.bid_package_parts p
 WHERE p.revision_id=m.revision_id AND p.member_id=m.member_id AND b.physical_page BETWEEN p.first_page AND p.last_page)
$$;

CREATE FUNCTION package_technical_gaps(p jsonb,target jsonb) RETURNS jsonb LANGUAGE plpgsql
 IMMUTABLE SET search_path=pg_catalog,design AS $$
DECLARE gaps jsonb; member jsonb; part jsonb; item jsonb; doc jsonb; code text;
BEGIN
 gaps:=jsonb_build_array(
 design.package_technical_gap('INVENTORY_COMPLETENESS_UNPROVEN',p#>>'{scope,inventory_id}','当前规则清单没有完整性实测权威；技术范围选择不会消除漏提风险。'),
 design.package_technical_gap('VISUAL_COMPLETENESS_UNPROVEN',NULL,'当前证据只记录实际解析内容，没有全图表完整阅读的资格证明。'),
 design.package_technical_gap('REQUIRED_RANGE_UNPROVEN',NULL,'用户声明的适用章节不能独立证明已覆盖全部必要技术范围。'),
 design.package_technical_gap('MODEL_EXECUTION_NOT_OPEN',NULL,'本记录仅冻结范围，不创建评分任务、三次判断或训练样本。'));
 FOR member IN SELECT * FROM jsonb_array_elements(target->'members') LOOP
  IF member->'parts'='[]'::jsonb THEN gaps:=gaps||jsonb_build_array(design.package_technical_gap('MEMBER_RANGE_UNDECLARED',member->>'member_id','该包成员没有明确章节范围，仍保留在范围缺口中。')); END IF;
  SELECT d INTO doc FROM jsonb_array_elements(p->'documents')d WHERE d->>'package_role'='target' AND d->>'member_id'=member->>'member_id';
  FOR part IN SELECT v FROM jsonb_array_elements(p->'parts')v WHERE v->>'member_id'=member->>'member_id' LOOP
   IF part->'selected'='false'::jsonb THEN
    gaps:=gaps||jsonb_build_array(design.package_technical_gap('PACKAGE_PART_NOT_SELECTED',part#>>'{part,part_id}','该包章节未纳入技术范围；是否适用仍需独立有据核实，未从包中删除。'));
   ELSIF jsonb_array_length(part->'read_physical_pages') IS DISTINCT FROM ((part#>>'{part,last_page}')::bigint-(part#>>'{part,first_page}')::bigint+1) THEN
    gaps:=gaps||jsonb_build_array(design.package_technical_gap('EXACT_PARSE_UNAVAILABLE',part#>>'{part,part_id}','所选章节尚无全部准确物理页的冻结解析，不能借用其他解析。'));
   ELSIF part->'block_ids'='[]'::jsonb THEN
    gaps:=gaps||jsonb_build_array(design.package_technical_gap('EMPTY_EVIDENCE_RANGE',part#>>'{part,part_id}','已声明物理页没有可核对的实际内容证据，不能当作无需阅读。'));
   END IF;
   IF EXISTS(SELECT FROM jsonb_array_elements(doc->'pages')v WHERE (v->>'physical_page')::bigint BETWEEN (part#>>'{part,first_page}')::bigint AND (part#>>'{part,last_page}')::bigint AND (v->>'quality'<>'usable' OR v->'gaps'<>'[]'::jsonb)) THEN
    gaps:=gaps||jsonb_build_array(design.package_technical_gap('PARSE_PAGE_GAP',part#>>'{part,part_id}','该章节原解析含不可用或部分读取页，缺口保持原状态。'));
   END IF;
  END LOOP;
 END LOOP;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'rules') LOOP
  IF item#>'{rule_snapshot,evidence_ids}'='[]'::jsonb OR EXISTS(SELECT FROM jsonb_array_elements_text(item#>'{rule_snapshot,evidence_ids}')v WHERE NOT EXISTS(SELECT FROM jsonb_array_elements(item->'source_evidence')e WHERE e->>'evidence_id'=v)) THEN
   gaps:=gaps||jsonb_build_array(design.package_technical_gap('RULE_SOURCE_UNPROVEN',item->>'rule_id','评分条款缺少所选权威版本完整逐字原页依据。'));
  END IF;
  IF item->>'selection'='include' AND EXISTS(SELECT FROM jsonb_array_elements_text(item->'declared_target_part_ids')v WHERE NOT (item->'part_ids') ? v) THEN
   gaps:=gaps||jsonb_build_array(design.package_technical_gap('DECLARED_RULE_RANGE_OMITTED',item->>'rule_id','该条款既有检查计划声明了更多章节，本次遗漏的范围仍是缺口。'));
  END IF;
  IF item->>'selection'<>'include' THEN
   code:=CASE item->>'selection' WHEN 'exclude' THEN 'RULE_EXCLUDED_BY_DECLARATION' ELSE 'RULE_NOT_CLASSIFIED' END;
   gaps:=gaps||jsonb_build_array(design.package_technical_gap(code,item->>'rule_id','本条款未进入技术判断范围；人工选择与理由保留，不会删除潜在适用义务。'));
  END IF;
 END LOOP;
 IF p->'rules'='[]'::jsonb THEN gaps:=gaps||jsonb_build_array(design.package_technical_gap('SCORING_RULES_UNKNOWN',p#>>'{scope,inventory_id}','未识别评分项不等于不存在评分要求，评分分母未知。')); END IF;
 RETURN gaps;
END $$;

CREATE TABLE bid_package_technical_scopes(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bid_profiles(bid_id),
 package_id uuid NOT NULL,
 revision_id uuid NOT NULL,
 inventory_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(package_id,bid_id) REFERENCES bid_packages(id,bid_id),
 FOREIGN KEY(package_id,revision_id) REFERENCES bid_package_revisions(package_id,id),
 FOREIGN KEY(bid_id,inventory_id) REFERENCES bid_package_requirement_inventories(bid_id,id),
 CHECK(octet_length(convert_to(package_canonical_json(manifest),'UTF8'))<=33554432),
 CHECK(package_technical_digest(manifest)=digest),
 UNIQUE(bid_id,id)
);
CREATE INDEX package_technical_scope_history ON bid_package_technical_scopes(bid_id,package_id,revision_id,created_at DESC,id DESC);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_technical_scopes
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION package_technical_scope_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE inv design.bid_package_requirement_inventories; own design.bid_package_revisions;
 authority design.bid_package_revisions; c design.commands; profile design.bid_profiles;
 m jsonb; p jsonb; request jsonb; part jsonb; document jsonb; item jsonb; native jsonb;
 member jsonb; row_source record; expected jsonb; ids uuid[]; original_ids uuid[];
 at timestamptz; amount bigint; field text; condition text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'technical_scope_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 m:=NEW.manifest; p:=m#>'{preview,manifest}'; request:=p->'request';
 IF NOT design.package_json_keys(m,ARRAY['version','id','actor_id','command_id','frozen_at','preview','original_verification','inventory_complete','scoring_ready','formal_scoring_eligible','model_execution_enabled','training_eligible'])
 OR NOT design.package_json_keys(m->'preview',ARRAY['manifest','digest'])
 OR design.package_technical_preview_shape(p) IS NOT TRUE
 OR NOT design.package_json_keys(m->'original_verification',ARRAY['state','verified_at','files'])
 OR jsonb_typeof(m#>'{original_verification,files}') IS DISTINCT FROM 'array'
 OR jsonb_typeof(m#>'{original_verification,verified_at}') IS DISTINCT FROM 'string'
 OR jsonb_typeof(m->'frozen_at') IS DISTINCT FROM 'string'
 THEN RAISE EXCEPTION 'technical_scope_shape' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(m#>'{original_verification,files}') LOOP
  IF NOT design.package_json_keys(item,ARRAY['document_version_id','digest','byte_size'])
  OR NOT design.package_json_integer(item->'byte_size',0) THEN
   RAISE EXCEPTION 'technical_scope_original_shape' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT * INTO inv FROM design.bid_package_requirement_inventories WHERE id=NEW.inventory_id AND bid_id=NEW.bid_id;
 SELECT * INTO own FROM design.bid_package_revisions WHERE id=NEW.revision_id AND package_id=NEW.package_id;
 SELECT * INTO authority FROM design.bid_package_revisions WHERE id=inv.authority_revision_id;
 -- Required roots derive only from immutable native package members. Acquire
 -- every mutable ancestor head in a deterministic order before observing time
 -- or current status. The graph advisory lock alone does not block direct SQL
 -- head updates by the business role. Include the inventory's full alias graph
 -- because its exact source snapshot is also rechecked below.
 SELECT array_agg(DISTINCT root ORDER BY root) INTO ids FROM (
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||document_version_id::text) AS root
  FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id)
  UNION ALL
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||parse_run_id::text)
  FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id) AND parse_run_id IS NOT NULL
 ) required;
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN(
  SELECT a.ancestor_id FROM retrieval.source_ancestors a WHERE a.source_id=ANY(ids)
  UNION
  SELECT a.ancestor_id FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.source_id
  WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id))
 ) ORDER BY h.source_id FOR SHARE OF h;
 at:=clock_timestamp();
 SELECT * INTO profile FROM design.bid_profiles WHERE bid_id=NEW.bid_id;
 SELECT * INTO c FROM design.commands WHERE id=NEW.command_id;
 IF inv.id IS NULL OR own.id IS NULL OR authority.id IS NULL OR c.id IS NULL OR profile.bid_id IS NULL
 OR own.manifest->>'kind'<>'bid' OR authority.manifest->>'kind'<>'authority'
 OR own.manifest->'scope' IS DISTINCT FROM authority.manifest->'scope'
 OR own.manifest#>>'{scope,bid_id}' IS DISTINCT FROM NEW.bid_id::text
 OR inv.target_revision_id IS DISTINCT FROM own.id OR inv.package_id IS DISTINCT FROM own.package_id
 OR profile.archived_at IS NOT NULL OR profile.phase IN('closed','terminated','submitted')
 OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=NEW.bid_id)
 OR profile.current_rule_set_id IS DISTINCT FROM inv.rule_set_id
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=own.package_id AND revision_id=own.id)
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=authority.package_id AND revision_id=authority.id)
 OR NOT EXISTS(SELECT FROM design.bid_package_requirement_heads WHERE target_revision_id=own.id AND inventory_id=inv.id AND digest=inv.digest)
 OR own.identity_digest IS DISTINCT FROM authority.identity_digest
 OR own.identity_digest::text IS DISTINCT FROM design.identity_snapshot_v2(NEW.bid_id)->>'digest'
 OR inv.manifest->'source_snapshot' IS DISTINCT FROM design.bid_requirement_source_snapshot(own.id,authority.id)
 THEN RAISE EXCEPTION 'technical_scope_context_changed' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m,ARRAY['version','id','actor_id','command_id','frozen_at','preview','original_verification','inventory_complete','scoring_ready','formal_scoring_eligible','model_execution_enabled','training_eligible'])
 OR m->>'version' IS DISTINCT FROM 'package-technical-scope/1'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text
 OR (m->>'frozen_at')::timestamptz<transaction_timestamp() OR (m->>'frozen_at')::timestamptz>at
 OR NOT design.package_json_keys(m->'preview',ARRAY['manifest','digest'])
 OR design.package_technical_digest(p) IS DISTINCT FROM m#>>'{preview,digest}'
 OR p->>'version' IS DISTINCT FROM 'package-technical-scope-preview/1'
 OR p->'scope' IS DISTINCT FROM jsonb_build_object('bid_id',NEW.bid_id,'package_id',NEW.package_id,'revision_id',NEW.revision_id,'inventory_id',NEW.inventory_id)
 OR p->'basis' IS DISTINCT FROM jsonb_build_object('package_digest',own.digest,'authority_revision_id',authority.id,'authority_digest',authority.digest,'inventory_digest',inv.digest,'rule_set_id',inv.rule_set_id,'rule_set_digest',inv.manifest->'rule_set_digest','identity_digest',own.identity_digest)
 OR p->>'request_digest' IS DISTINCT FROM design.package_technical_digest(request)
 OR p->'original_bytes_verified' IS DISTINCT FROM 'false'::jsonb
 OR (p#>>'{coverage,state}' IN('partial','unknown')) IS NOT TRUE
 OR p#>>'{coverage,visual_coverage}' IS DISTINCT FROM 'unproven'
 OR p#>>'{coverage,required_range_completeness}' IS DISTINCT FROM 'unproven'
 OR p#>>'{method,version}' IS DISTINCT FROM 'package-technical-scope-policy/1'
 OR p#>>'{method,digest}' IS DISTINCT FROM design.package_technical_digest((p->'method')-'digest')
 OR p->'timing' IS DISTINCT FROM '{"purpose":"current_prebid","historical_as_of":null,"submitted_at":null,"label_known_at":null,"training_frozen_at":null,"submission_split_at":null,"label_available_as_of":null,"historical_qualification":"not_established"}'::jsonb
 THEN RAISE EXCEPTION 'technical_scope_manifest_invalid' USING ERRCODE='23514'; END IF;
 FOREACH field IN ARRAY ARRAY['inventory_complete','scoring_ready','formal_scoring_eligible','model_execution_enabled','training_eligible'] LOOP
  IF m->field IS DISTINCT FROM 'false'::jsonb OR p->field IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'technical_scope_cannot_grant_execution' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF request->>'purpose' IS DISTINCT FROM 'current_prebid'
 OR request->>'package_digest' IS DISTINCT FROM own.digest::text
 OR request->>'authority_revision_id' IS DISTINCT FROM authority.id::text
 OR request->>'authority_digest' IS DISTINCT FROM authority.digest::text
 OR request->>'inventory_id' IS DISTINCT FROM inv.id::text
 OR request->>'inventory_digest' IS DISTINCT FROM inv.digest::text
 OR NOT design.package_json_keys(request,ARRAY['purpose','package_digest','authority_revision_id','authority_digest','inventory_id','inventory_digest','technical_part_ids','rule_scopes','reason'])
 OR jsonb_typeof(request->'technical_part_ids') IS DISTINCT FROM 'array'
 OR jsonb_array_length(request->'technical_part_ids') NOT BETWEEN 1 AND 2000
 OR jsonb_array_length(request->'technical_part_ids') IS DISTINCT FROM (SELECT count(DISTINCT v) FROM jsonb_array_elements(request->'technical_part_ids')v)
 OR jsonb_array_length(p->'parts') IS DISTINCT FROM (SELECT count(*) FROM design.bid_package_parts WHERE revision_id=own.id)
 OR jsonb_array_length(p->'parts')>2000
 OR jsonb_array_length(p->'parts') IS DISTINCT FROM (SELECT count(DISTINCT v#>>'{part,part_id}') FROM jsonb_array_elements(p->'parts')v)
 THEN RAISE EXCEPTION 'technical_scope_part_set' USING ERRCODE='23514'; END IF;
 -- Rebuild from exact member parses; declared read pages/blocks/visible text
 -- cannot be invented, omitted or copied from a newer parse.
 IF p->'parts' IS DISTINCT FROM design.package_technical_parts(own.id,request->'technical_part_ids') THEN
  RAISE EXCEPTION 'technical_scope_part_evidence' USING ERRCODE='23514'; END IF;
 FOR part IN SELECT * FROM jsonb_array_elements(p->'parts') LOOP
  SELECT v INTO member FROM jsonb_array_elements(own.manifest->'members')v WHERE v->>'member_id'=part->>'member_id';
  SELECT v INTO native FROM jsonb_array_elements(member->'parts')v WHERE v->>'part_id'=part#>>'{part,part_id}';
  IF member IS NULL OR native IS NULL OR native IS DISTINCT FROM part->'part'
  OR part->>'document_version_id' IS DISTINCT FROM member->>'document_version_id'
  OR part->>'file_digest' IS DISTINCT FROM member->>'file_digest'
  OR part->'selected' IS DISTINCT FROM to_jsonb((request->'technical_part_ids') ? (native->>'part_id'))
  OR part->>'visual_coverage' IS DISTINCT FROM 'unproven' THEN
   RAISE EXCEPTION 'technical_scope_part_binding' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT FROM jsonb_array_elements_text(request->'technical_part_ids')v WHERE NOT EXISTS(SELECT FROM design.bid_package_parts q WHERE q.revision_id=own.id AND q.part_id=v)) THEN
  RAISE EXCEPTION 'technical_scope_foreign_part' USING ERRCODE='23514'; END IF;
 SELECT count(*) INTO amount FROM jsonb_array_elements(inv.manifest->'requirements')r WHERE r#>>'{rule_snapshot,kind}'='scoring';
 IF jsonb_array_length(p->'rules') IS DISTINCT FROM amount OR jsonb_array_length(request->'rule_scopes') IS DISTINCT FROM amount OR amount>1000
 OR jsonb_array_length(p->'rules') IS DISTINCT FROM (SELECT count(DISTINCT r->>'rule_id') FROM jsonb_array_elements(p->'rules')r)
 OR jsonb_array_length(request->'rule_scopes') IS DISTINCT FROM (SELECT count(DISTINCT r->>'rule_id') FROM jsonb_array_elements(request->'rule_scopes')r)
 THEN RAISE EXCEPTION 'technical_scope_rule_set_incomplete' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'rules') LOOP
  SELECT r INTO native FROM jsonb_array_elements(inv.manifest->'requirements')r WHERE r->>'rule_id'=item->>'rule_id' AND r#>>'{rule_snapshot,kind}'='scoring';
  SELECT r INTO expected FROM jsonb_array_elements(request->'rule_scopes')r WHERE r->>'rule_id'=item->>'rule_id';
  IF native IS NULL OR expected IS NULL OR item->'rule_snapshot' IS DISTINCT FROM native->'rule_snapshot'
  OR item->>'rule_digest' IS DISTINCT FROM native->>'rule_digest'
  OR item->>'requirement_digest' IS DISTINCT FROM native->>'requirement_digest'
  OR item->'declared_target_part_ids' IS DISTINCT FROM native#>'{requirement,target_part_ids}'
  OR (item-ARRAY['rule_snapshot','requirement_digest','declared_target_part_ids','source_evidence']) IS DISTINCT FROM expected
  OR (item->>'selection' IN('include','exclude','unclassified')) IS NOT TRUE
  OR (item->>'selection'='include' AND (native#>>'{rule_snapshot,provenance_status}'<>'effective' OR jsonb_array_length(item->'part_ids')=0))
  OR (item->>'selection'<>'include' AND item->'part_ids'<>'[]'::jsonb)
  OR EXISTS(SELECT FROM jsonb_array_elements_text(item->'part_ids')v WHERE NOT (request->'technical_part_ids') ? v)
  THEN RAISE EXCEPTION 'technical_scope_rule_binding' USING ERRCODE='23514'; END IF;
  expected:=design.package_technical_rule_evidence(authority.id,native#>'{rule_snapshot,evidence_ids}');
  IF item->'source_evidence' IS DISTINCT FROM expected THEN
   RAISE EXCEPTION 'technical_scope_rule_source_evidence' USING ERRCODE='23514'; END IF;
  IF item->>'selection' IN('include','exclude') AND
  (native#>'{rule_snapshot,evidence_ids}'='[]'::jsonb OR EXISTS(
   SELECT FROM jsonb_array_elements_text(native#>'{rule_snapshot,evidence_ids}')v
   WHERE NOT EXISTS(SELECT FROM jsonb_array_elements(expected)e WHERE e->>'evidence_id'=v)))
  THEN RAISE EXCEPTION 'technical_scope_rule_source_unproven' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF jsonb_array_length(p->'documents') IS DISTINCT FROM (SELECT count(*) FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id))
 OR jsonb_array_length(p->'documents') IS DISTINCT FROM (SELECT count(DISTINCT (d->>'package_role',d->>'member_id')) FROM jsonb_array_elements(p->'documents')d)
 OR (SELECT sum(jsonb_array_length(d->'blocks')) FROM jsonb_array_elements(p->'documents')d)>100000
 OR (SELECT sum(jsonb_array_length(d->'pages')) FROM jsonb_array_elements(p->'documents')d)>100000
 THEN RAISE EXCEPTION 'technical_scope_document_set' USING ERRCODE='23514'; END IF;
 FOR document IN SELECT * FROM jsonb_array_elements(p->'documents') LOOP
  SELECT v INTO member FROM jsonb_array_elements(CASE document->>'package_role' WHEN 'target' THEN own.manifest->'members' WHEN 'authority' THEN authority.manifest->'members' ELSE '[]'::jsonb END)v WHERE v->>'member_id'=document->>'member_id';
  IF member IS NULL OR document->'parse' IS DISTINCT FROM member->'parse'
  OR document->>'document_version_id' IS DISTINCT FROM member->>'document_version_id'
  OR document->>'file_digest' IS DISTINCT FROM member->>'file_digest'
  OR document->'page_count' IS DISTINCT FROM member->'page_count'
  OR NOT EXISTS(SELECT FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=NEW.bid_id AND v.id=(document->>'document_version_id')::uuid AND b.digest::text=document->>'file_digest' AND b.byte_size=(document->>'byte_size')::bigint)
  THEN RAISE EXCEPTION 'technical_scope_document_binding' USING ERRCODE='23514'; END IF;
  IF member#>>'{parse,status}'='not_frozen' THEN
   IF document->'pages' IS DISTINCT FROM '[]'::jsonb OR document->'blocks' IS DISTINCT FROM '[]'::jsonb THEN RAISE EXCEPTION 'technical_scope_parse_not_frozen' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT coalesce(jsonb_agg(jsonb_build_object('physical_page',physical_page,'quality',quality,'gaps',gaps) ORDER BY physical_page),'[]'::jsonb) INTO expected FROM design.pages WHERE bid_id=NEW.bid_id AND parse_id=(member#>>'{parse,parse_run_id}')::uuid;
   IF expected IS DISTINCT FROM document->'pages' THEN RAISE EXCEPTION 'technical_scope_page_binding' USING ERRCODE='23514'; END IF;
   SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'physical_page',physical_page,'ordinal',ordinal,'kind',kind,'text_content',text_content,'digest',digest,'bbox_json',bbox::text,'structure_json',structure::text) ORDER BY physical_page,ordinal,id),'[]'::jsonb) INTO expected FROM design.evidence_blocks WHERE bid_id=NEW.bid_id AND parse_id=(member#>>'{parse,parse_run_id}')::uuid;
   IF expected IS DISTINCT FROM document->'blocks' THEN RAISE EXCEPTION 'technical_scope_evidence_binding' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 -- Required roots derive independently from every native member/version/parse.
 -- No self-declared subset, unrelated graph or missing parse root can pass.
 IF ids IS NULL OR jsonb_array_length(p->'source_snapshot')>20000
 OR ids IS DISTINCT FROM (SELECT array_agg(DISTINCT (v->>'source_id')::uuid ORDER BY (v->>'source_id')::uuid) FROM jsonb_array_elements(p->'source_snapshot')v)
 OR EXISTS(SELECT FROM unnest(ids)r WHERE NOT EXISTS(SELECT FROM retrieval.source_ancestors a WHERE a.source_id=r AND a.ancestor_id=r))
 OR jsonb_array_length(p->'source_snapshot') IS DISTINCT FROM (SELECT count(*) FROM retrieval.source_ancestors WHERE source_id=ANY(ids))
 OR jsonb_array_length(p->'source_snapshot') IS DISTINCT FROM (SELECT count(DISTINCT ((v->>'source_id')::uuid,(v->>'ancestor_id')::uuid)) FROM jsonb_array_elements(p->'source_snapshot')v)
 OR (SELECT jsonb_agg(jsonb_build_array(a.source_id,a.ancestor_id) ORDER BY a.source_id,a.ancestor_id)
     FROM retrieval.source_ancestors a WHERE a.source_id=ANY(ids)) IS DISTINCT FROM
    (SELECT jsonb_agg(jsonb_build_array((v->>'source_id')::uuid,(v->>'ancestor_id')::uuid) ORDER BY (v->>'source_id')::uuid,(v->>'ancestor_id')::uuid)
     FROM jsonb_array_elements(p->'source_snapshot')v)
 THEN RAISE EXCEPTION 'technical_scope_source_closure' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT FROM design.bid_package_members member WHERE member.revision_id IN(own.id,authority.id) AND (
 NOT EXISTS(SELECT FROM retrieval.source_nodes n WHERE n.id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||member.document_version_id::text)
 AND n.document_version_id=member.document_version_id AND n.digest=member.file_digest)
 OR (member.parse_run_id IS NOT NULL AND NOT EXISTS(SELECT FROM retrieval.source_nodes n WHERE n.id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||member.parse_run_id::text)
 AND n.document_version_id=member.document_version_id AND n.digest=member.file_digest)))) THEN
 RAISE EXCEPTION 'technical_scope_canonical_source_binding' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT FROM design.bid_package_members member
 WHERE member.revision_id IN(own.id,authority.id) AND member.parse_run_id IS NOT NULL
 AND NOT EXISTS(SELECT FROM retrieval.lineage_edges edge
 WHERE edge.child_id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||member.parse_run_id::text)
 AND edge.parent_id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||member.document_version_id::text))) THEN
  RAISE EXCEPTION 'technical_scope_parse_original_edge_missing' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'source_snapshot') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until,v.bid_id,b.digest AS original_digest INTO row_source FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id JOIN retrieval.source_heads h ON h.source_id=n.id JOIN design.document_versions v ON v.id=n.document_version_id JOIN design.blobs b ON b.id=v.blob_id WHERE a.source_id=(item->>'source_id')::uuid AND a.ancestor_id=(item->>'ancestor_id')::uuid;
  IF row_source.id IS NULL OR row_source.bid_id<>NEW.bid_id OR row_source.kind<>'document'
  OR row_source.policy_class<>'prebid_content' OR row_source.status<>'published'
  OR row_source.digest<>row_source.original_digest OR row_source.known_at>at OR row_source.valid_from>at OR row_source.valid_until<=at
  OR item->>'document_version_id' IS DISTINCT FROM row_source.document_version_id::text
  OR item->>'digest' IS DISTINCT FROM row_source.digest::text
  OR item->>'original_digest' IS DISTINCT FROM row_source.original_digest::text
  OR item->>'kind' IS DISTINCT FROM row_source.kind OR item->>'policy_class' IS DISTINCT FROM row_source.policy_class
  OR item->>'document_bid' IS DISTINCT FROM NEW.bid_id::text OR item->>'status' IS DISTINCT FROM row_source.status
  OR (item->>'revision')::bigint IS DISTINCT FROM row_source.revision
  OR (item->>'known_at')::timestamptz IS DISTINCT FROM row_source.known_at
  OR (item->>'valid_from')::timestamptz IS DISTINCT FROM row_source.valid_from
  OR (item->>'valid_until')::timestamptz IS DISTINCT FROM row_source.valid_until
  THEN RAISE EXCEPTION 'technical_scope_source_changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF EXISTS(SELECT FROM jsonb_array_elements(p->'documents')d WHERE NOT EXISTS(SELECT FROM jsonb_array_elements(p->'source_snapshot')s WHERE s->>'document_version_id'=d->>'document_version_id' AND s->>'digest'=d->>'file_digest')) THEN
  RAISE EXCEPTION 'technical_scope_original_source_missing' USING ERRCODE='23514'; END IF;
 -- Original-byte receipts cover the independently derived database closure,
 -- never a document set proposed by the caller's JSON snapshot.
 SELECT array_agg(DISTINCT n.document_version_id ORDER BY n.document_version_id) INTO original_ids
 FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
 WHERE a.source_id=ANY(ids);
 SELECT coalesce(jsonb_agg(jsonb_build_object('document_version_id',v.id,'digest',b.digest,'byte_size',b.byte_size) ORDER BY v.id),'[]'::jsonb) INTO expected FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=NEW.bid_id AND v.id=ANY(original_ids);
 IF m#>>'{original_verification,state}' IS DISTINCT FROM 'verified_at_recording'
 OR m#>'{original_verification,files}' IS DISTINCT FROM expected
 OR (SELECT sum((v->>'byte_size')::bigint) FROM jsonb_array_elements(expected)v)>1073741824
 OR (m#>>'{original_verification,verified_at}')::timestamptz>(m->>'frozen_at')::timestamptz
 THEN RAISE EXCEPTION 'technical_scope_original_receipt' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object(
  'state',CASE WHEN EXISTS(SELECT FROM jsonb_array_elements(p->'parts')v WHERE v->'selected'='true'::jsonb AND v->'block_ids'<>'[]'::jsonb) THEN 'partial' ELSE 'unknown' END,
  'all_part_count',jsonb_array_length(p->'parts'),'selected_part_count',jsonb_array_length(request->'technical_part_ids'),
  'all_scoring_rule_count',jsonb_array_length(p->'rules'),
  'included_rule_count',(SELECT count(*) FROM jsonb_array_elements(p->'rules')v WHERE v->>'selection'='include'),
  'frozen_parse_member_count',(SELECT count(*) FROM design.bid_package_members WHERE revision_id=own.id AND parse_run_id IS NOT NULL),
  'gaps',design.package_technical_gaps(p,own.manifest),'visual_coverage','unproven','required_range_completeness','unproven');
 IF p->'coverage' IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'technical_scope_coverage_forged' USING ERRCODE='23514'; END IF;
 -- context_digest and the exact runtime source hashes are recomputed by the
 -- API before and after object IO. SQL cannot authenticate application source
 -- bytes: it only closes method shape/file set/limits and checks native data.
 -- This declaration grants no score/training privilege. Future consumers must
 -- independently revalidate the trusted method and context before execution.
 condition:=format('"package-technical-scope-context:%s:%s"',NEW.revision_id,design.package_technical_digest(jsonb_build_object('snapshot_digest',p->'context_digest','method_digest',p#>'{method,digest}')));
 IF c.actor_id IS DISTINCT FROM NEW.actor_id OR c.command_kind<>'package-technical-scope-freeze' OR c.target_id IS DISTINCT FROM NEW.revision_id
 OR c.request_digest::text IS DISTINCT FROM design.package_technical_digest(jsonb_build_object('body',jsonb_build_object('scope',jsonb_build_array(NEW.bid_id,NEW.package_id,NEW.revision_id),'request',request,'preview_digest',m#>'{preview,digest}'),'if_match',condition))
 THEN RAISE EXCEPTION 'technical_scope_command_identity' USING ERRCODE='23514'; END IF;
 NEW.created_at:=(m->>'frozen_at')::timestamptz;
 RETURN NEW;
END $$;
CREATE TRIGGER technical_scope_context BEFORE INSERT ON bid_package_technical_scopes FOR EACH ROW EXECUTE FUNCTION package_technical_scope_guard();

CREATE FUNCTION package_technical_scope_receipt_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE c design.commands; p jsonb; expected jsonb; condition text;
BEGIN
 SELECT * INTO c FROM design.commands WHERE id=NEW.command_id;
 p:=NEW.manifest#>'{preview,manifest}';
 condition:=format('"package-technical-scope-context:%s:%s"',NEW.revision_id,design.package_technical_digest(jsonb_build_object('snapshot_digest',p->'context_digest','method_digest',p#>'{method,digest}')));
 expected:=jsonb_build_object('body',jsonb_build_object('scope',jsonb_build_object('manifest',NEW.manifest,'digest',NEW.digest),'command',jsonb_build_object('command_id',c.id,'actor_id',c.actor_id,'idempotency_key',c.idempotency_key,'request_digest',c.request_digest,'request',jsonb_build_object('request',p->'request','preview_digest',NEW.manifest#>'{preview,digest}'),'if_match',condition)),'status',201,'headers',jsonb_build_object('ETag',format('"package-technical-scope:%s:%s"',NEW.id,NEW.digest)));
 IF c.response IS DISTINCT FROM expected OR (SELECT count(*) FROM design.audit_entries WHERE command_id=c.id AND actor_id=NEW.actor_id AND bid_id=NEW.bid_id AND event_type='package.technical_scope_frozen' AND payload=jsonb_build_object('scope_id',NEW.id,'digest',NEW.digest,'inventory_id',NEW.inventory_id))<>1 THEN
  RAISE EXCEPTION 'technical_scope_receipt_mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER technical_scope_original_ack AFTER INSERT ON bid_package_technical_scopes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION package_technical_scope_receipt_guard();

REVOKE ALL ON bid_package_technical_scopes FROM PUBLIC,tender_worker;
GRANT SELECT ON bid_package_technical_scopes TO tender_api;
GRANT INSERT(id,bid_id,package_id,revision_id,inventory_id,actor_id,command_id,manifest,digest) ON bid_package_technical_scopes TO tender_api;
REVOKE ALL ON FUNCTION package_technical_digest(jsonb),package_technical_gap(text,text,text),package_technical_text(jsonb),package_technical_nonblank(text),package_technical_preview_shape(jsonb),package_technical_parts(uuid,jsonb),package_technical_rule_evidence(uuid,jsonb),package_technical_gaps(jsonb,jsonb),package_technical_scope_guard(),package_technical_scope_receipt_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_technical_digest(jsonb),package_technical_gap(text,text,text),package_technical_text(jsonb),package_technical_nonblank(text),package_technical_preview_shape(jsonb),package_technical_parts(uuid,jsonb),package_technical_rule_evidence(uuid,jsonb),package_technical_gaps(jsonb,jsonb),package_technical_scope_guard(),package_technical_scope_receipt_guard() TO tender_api;
REVOKE ALL ON FUNCTION public.uuid_generate_v1(),public.uuid_generate_v1mc(),public.uuid_generate_v3(uuid,text),public.uuid_generate_v4(),public.uuid_generate_v5(uuid,text),public.uuid_nil(),public.uuid_ns_dns(),public.uuid_ns_url(),public.uuid_ns_oid(),public.uuid_ns_x500() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.uuid_generate_v5(uuid,text) TO tender_api;
COMMIT;
