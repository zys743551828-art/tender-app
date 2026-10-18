-- F01首批持久化；只在全新隔离库按core.sql -> domain.sql -> 本文件执行。
-- 不接入旧单正文API；不创建平行工程/轮次/profile。正式运行角色授权另行评审。
BEGIN;
SET search_path TO design,public;

CREATE FUNCTION package_canonical_json(value jsonb) RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT
 SET search_path=pg_catalog,design AS $$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN
  SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||design.package_canonical_json(item),',' ORDER BY key COLLATE "C"),'')||'}'
  INTO result FROM jsonb_each(value) e(key,item);
 WHEN 'array' THEN
  SELECT '['||coalesce(string_agg(design.package_canonical_json(item),',' ORDER BY ordinal),'')||']'
  INTO result FROM jsonb_array_elements(value) WITH ORDINALITY e(item,ordinal);
 ELSE result=value::text;
 END CASE;
 RETURN result;
END $$;
CREATE FUNCTION package_json_keys(value jsonb,keys text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN jsonb_typeof(value)='object' THEN value ?& keys AND
 (SELECT count(*) FROM jsonb_object_keys(value))=cardinality(keys) ELSE false END
$$;
CREATE FUNCTION package_json_integer(value jsonb,minimum bigint) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE WHEN jsonb_typeof(value)='number' AND value::text ~ '^(0|[1-9][0-9]*)$'
 THEN value::text::numeric BETWEEN minimum AND 9007199254740991 ELSE false END
$$;
CREATE FUNCTION package_json_text(value jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND length(value#>>'{}') BETWEEN 1 AND 200
 AND (value#>>'{}') ~ '\S',false)
$$;
CREATE FUNCTION package_manifest_shape(value jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; p jsonb; n jsonb; key text;
BEGIN
 IF NOT design.package_json_keys(value,ARRAY['package_id','revision_id','revision','kind','scope','members','predecessor_digest','identity_version'])
 OR NOT design.package_json_text(value->'package_id') OR NOT design.package_json_text(value->'revision_id')
 OR (value->>'identity_version'='bid-package/1') IS NOT TRUE
 OR NOT design.package_json_integer(value->'revision',1)
 OR (value->>'kind' IN ('authority','bid')) IS NOT TRUE
 OR NOT design.package_json_keys(value->'scope',ARRAY['engineering_project_id','lot_id','round_id','bid_id','bidder_id','bidder_status'])
 OR (value->'scope'->>'bidder_status' IN ('confirmed','pending')) IS NOT TRUE
 OR jsonb_typeof(value->'members') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 IF jsonb_array_length(value->'members')=0 THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['engineering_project_id','lot_id','round_id','bid_id','bidder_id'] LOOP
  IF NOT design.package_json_text(value->'scope'->key) THEN RETURN false; END IF;
 END LOOP;
 FOR m IN SELECT * FROM jsonb_array_elements(value->'members') LOOP
  IF NOT design.package_json_keys(m,ARRAY['member_id','document_version_id','file_digest','source_kind','source_ref','scope','purposes','page_count','parse','parts'])
  OR m->'scope' IS DISTINCT FROM value->'scope'
  OR (m->>'source_kind'=CASE value->>'kind' WHEN 'bid' THEN 'own' ELSE 'authority' END) IS NOT TRUE
  OR NOT design.package_json_text(m->'member_id') OR NOT design.package_json_text(m->'document_version_id')
  OR NOT design.package_json_text(m->'source_ref') OR jsonb_typeof(m->'file_digest') IS DISTINCT FROM 'string'
  OR (m->>'file_digest' ~ '^[a-f0-9]{64}$') IS NOT TRUE
  OR jsonb_typeof(m->'purposes') IS DISTINCT FROM 'array' OR jsonb_typeof(m->'parts') IS DISTINCT FROM 'array'
  OR NOT design.package_json_keys(m->'parse',ARRAY['status','parse_run_id','parser_digest','config_digest','evidence_digest','reason'])
  THEN RETURN false; END IF;
  IF jsonb_array_length(m->'purposes')=0 OR EXISTS(SELECT FROM jsonb_array_elements(m->'purposes') x(v) WHERE NOT design.package_json_text(v))
  OR (SELECT count(*) FROM jsonb_array_elements(m->'purposes'))<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(m->'purposes') x(v))
  THEN RETURN false; END IF;
  IF m->'page_count'<>'null'::jsonb AND NOT design.package_json_integer(m->'page_count',1) THEN RETURN false; END IF;
  IF m->'parse'->>'status'='frozen' THEN
   IF m->'page_count'='null'::jsonb OR jsonb_array_length(m->'parts')=0
   OR NOT design.package_json_text(m->'parse'->'parse_run_id') OR m->'parse'->'reason'<>'null'::jsonb
   THEN RETURN false; END IF;
   FOREACH key IN ARRAY ARRAY['parser_digest','config_digest','evidence_digest'] LOOP
    IF jsonb_typeof(m->'parse'->key) IS DISTINCT FROM 'string' OR (m->'parse'->>key ~ '^[a-f0-9]{64}$') IS NOT TRUE THEN RETURN false; END IF;
   END LOOP;
  ELSIF m->'parse'->>'status'='not_frozen' THEN
   IF NOT design.package_json_text(m->'parse'->'reason') THEN RETURN false; END IF;
   FOREACH key IN ARRAY ARRAY['parse_run_id','parser_digest','config_digest','evidence_digest'] LOOP
    IF m->'parse'->key IS DISTINCT FROM 'null'::jsonb THEN RETURN false; END IF;
   END LOOP;
  ELSE RETURN false;
  END IF;
  IF m->'page_count'='null'::jsonb AND jsonb_array_length(m->'parts')>0 THEN RETURN false; END IF;
  FOR p IN SELECT * FROM jsonb_array_elements(m->'parts') LOOP
   IF NOT design.package_json_keys(p,ARRAY['part_id','category','first_page','last_page','shared_attachment','heading_path'])
   OR NOT design.package_json_text(p->'part_id') OR NOT design.package_json_text(p->'category')
   OR NOT design.package_json_integer(p->'first_page',1) OR NOT design.package_json_integer(p->'last_page',1)
   OR (p->>'first_page')::numeric>(p->>'last_page')::numeric OR (p->>'last_page')::numeric>(m->>'page_count')::numeric
   OR jsonb_typeof(p->'shared_attachment') IS DISTINCT FROM 'boolean'
   OR jsonb_typeof(p->'heading_path') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   FOR n IN SELECT * FROM jsonb_array_elements(p->'heading_path') LOOP
    IF NOT design.package_json_integer(n,1) THEN RETURN false; END IF;
   END LOOP;
  END LOOP;
  IF EXISTS(SELECT FROM jsonb_array_elements(m->'parts') WITH ORDINALITY x(a,i),jsonb_array_elements(m->'parts') WITH ORDINALITY y(b,j)
   WHERE i<j AND greatest((a->>'first_page')::bigint,(b->>'first_page')::bigint)<=least((a->>'last_page')::bigint,(b->>'last_page')::bigint)
   AND NOT ((a->>'shared_attachment')::boolean AND (b->>'shared_attachment')::boolean)) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE TABLE engineering_lots (
 id uuid PRIMARY KEY, engineering_project_id uuid NOT NULL REFERENCES engineering_projects(id),
 label text NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 200), UNIQUE(engineering_project_id,id)
);
ALTER TABLE bid_rounds ADD COLUMN lot_id uuid;
ALTER TABLE bid_rounds ADD CONSTRAINT bid_round_real_lot
 FOREIGN KEY(engineering_project_id,lot_id) REFERENCES engineering_lots(engineering_project_id,id);
ALTER TABLE bid_rounds ADD CONSTRAINT bid_round_package_scope UNIQUE(id,engineering_project_id,lot_id);
ALTER TABLE bid_rounds DROP CONSTRAINT bid_rounds_engineering_project_id_lot_round_no_key;
CREATE UNIQUE INDEX bid_round_unmapped_legacy_identity
 ON bid_rounds(engineering_project_id,lot,round_no) WHERE lot_id IS NULL;
ALTER TABLE bid_rounds ADD CONSTRAINT bid_round_stable_identity UNIQUE(engineering_project_id,lot_id,round_no);
-- lot_id暂可空：已有身份入口尚未接入；整包仓储拒绝未显式登记稳定标段的轮次。

CREATE TABLE bid_packages (
 id uuid PRIMARY KEY, bid_id uuid NOT NULL REFERENCES bid_profiles(bid_id),
 kind text NOT NULL CHECK(kind IN ('authority','bid')),
 engineering_project_id uuid NOT NULL, lot_id uuid NOT NULL, round_id uuid NOT NULL,
 bidder_id uuid NOT NULL REFERENCES bidders(id),
 FOREIGN KEY(round_id,engineering_project_id,lot_id)
 REFERENCES bid_rounds(id,engineering_project_id,lot_id), UNIQUE(id,bid_id)
);
CREATE TABLE bid_package_revisions (
 id uuid PRIMARY KEY, package_id uuid NOT NULL REFERENCES bid_packages(id),
 revision bigint NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
 predecessor_digest sha256, digest sha256 NOT NULL,
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 identity_authority_id uuid REFERENCES audit_entries(id), identity_digest sha256 NOT NULL,
 identity_snapshot jsonb NOT NULL CHECK(jsonb_typeof(identity_snapshot)='object'),
 bidder_status text NOT NULL CHECK(bidder_status IN ('confirmed','pending')),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((revision=1)=(predecessor_digest IS NULL)),
 CHECK(package_manifest_shape(manifest)),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest),
 CHECK((jsonb_typeof(identity_snapshot->'digest')='string' AND identity_snapshot->>'digest'=identity_digest::text) IS TRUE),
 CHECK(encode(sha256(convert_to(package_canonical_json(identity_snapshot-'digest'),'UTF8')),'hex')=identity_digest),
 CHECK((identity_snapshot->>'authority_id')::uuid IS NOT DISTINCT FROM identity_authority_id),
 CHECK((manifest->>'revision_id' IS NOT DISTINCT FROM id::text) AND (manifest->>'package_id' IS NOT DISTINCT FROM package_id::text)),
 CHECK((manifest->>'revision')::bigint IS NOT DISTINCT FROM revision),
 CHECK(manifest->>'predecessor_digest' IS NOT DISTINCT FROM predecessor_digest::text),
 CHECK((jsonb_typeof(manifest->'members')='array' AND jsonb_array_length(manifest->'members')>0) IS TRUE),
 UNIQUE(package_id,revision), UNIQUE(package_id,id), UNIQUE(package_id,digest),
 FOREIGN KEY(package_id,predecessor_digest) REFERENCES bid_package_revisions(package_id,digest)
);
CREATE TABLE bid_package_heads (
 package_id uuid PRIMARY KEY REFERENCES bid_packages(id), revision_id uuid NOT NULL,
 revision bigint NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991), digest sha256 NOT NULL,
 FOREIGN KEY(package_id,revision_id) REFERENCES bid_package_revisions(package_id,id)
);
CREATE TABLE bid_package_parse_bindings (
 parse_run_id uuid PRIMARY KEY, bid_id uuid NOT NULL, document_version_id uuid NOT NULL,
 file_digest sha256 NOT NULL, parser_digest sha256 NOT NULL, config_digest sha256 NOT NULL,
 evidence_digest sha256 NOT NULL, page_count bigint NOT NULL CHECK(page_count BETWEEN 1 AND 9007199254740991),
 FOREIGN KEY(bid_id,parse_run_id,document_version_id) REFERENCES parse_runs(bid_id,id,document_version_id)
);
CREATE TABLE bid_package_members (
 revision_id uuid NOT NULL REFERENCES bid_package_revisions(id), member_id text NOT NULL,
 ordinal bigint NOT NULL CHECK(ordinal BETWEEN 0 AND 9007199254740991),
 bid_id uuid NOT NULL, document_version_id uuid NOT NULL, file_digest sha256 NOT NULL,
 parse_run_id uuid REFERENCES bid_package_parse_bindings(parse_run_id),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 PRIMARY KEY(revision_id,member_id), UNIQUE(revision_id,ordinal), UNIQUE(revision_id,document_version_id),
 FOREIGN KEY(bid_id,document_version_id) REFERENCES document_versions(bid_id,id)
);
CREATE TABLE bid_package_parts (
 revision_id uuid NOT NULL, member_id text NOT NULL, part_id text NOT NULL,
 ordinal bigint NOT NULL CHECK(ordinal BETWEEN 0 AND 9007199254740991), category text NOT NULL,
 first_page bigint NOT NULL CHECK(first_page BETWEEN 1 AND 9007199254740991),
 last_page bigint NOT NULL CHECK(last_page BETWEEN first_page AND 9007199254740991),
 shared_attachment boolean NOT NULL, heading_path jsonb NOT NULL CHECK(jsonb_typeof(heading_path)='array'),
 PRIMARY KEY(revision_id,part_id), UNIQUE(revision_id,member_id,ordinal),
 FOREIGN KEY(revision_id,member_id) REFERENCES bid_package_members(revision_id,member_id)
);

CREATE FUNCTION package_revision_context_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE p design.bid_packages; association jsonb; authority record; status text; expected jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'package_requires_read_committed' USING ERRCODE='25001';
 END IF;
 SELECT * INTO p FROM design.bid_packages WHERE id=NEW.package_id;
 PERFORM id FROM design.bids WHERE id=p.bid_id FOR UPDATE;
 IF NEW.manifest->>'kind' IS DISTINCT FROM p.kind OR NEW.manifest->'scope' IS DISTINCT FROM jsonb_build_object(
 'engineering_project_id',p.engineering_project_id,'lot_id',p.lot_id,'round_id',p.round_id,
 'bid_id',p.bid_id,'bidder_id',p.bidder_id,'bidder_status',NEW.bidder_status)
 THEN RAISE EXCEPTION 'package_revision_scope_mismatch' USING ERRCODE='23514'; END IF;
 SELECT jsonb_build_object('bidder_id',b.id,'bidder_name',b.name,'round_id',r.id,
 'engineering_project_id',e.id,'engineering_title',e.title,'region',e.region,'engineering_type',e.engineering_type,
 'lot',r.lot,'round_no',r.round_no) INTO association
 FROM design.bid_profiles profile JOIN design.bidders b ON b.id=profile.bidder_id
 JOIN design.bid_rounds r ON r.id=profile.round_id JOIN design.engineering_projects e ON e.id=r.engineering_project_id
 WHERE profile.bid_id=p.bid_id AND profile.bidder_id=p.bidder_id AND r.id=p.round_id AND r.lot_id=p.lot_id;
 IF association IS NULL THEN RAISE EXCEPTION 'package_current_profile_mismatch' USING ERRCODE='23514'; END IF;
 SELECT id,payload INTO authority FROM design.audit_entries WHERE bid_id=p.bid_id AND event_type='identity.bound'
 ORDER BY coalesce((payload->>'identity_epoch')::bigint,0) DESC,created_at DESC,id DESC LIMIT 1;
 status=CASE WHEN authority.payload->'after'=association AND authority.payload->'confirmed'='true'::jsonb THEN 'confirmed' ELSE 'pending' END;
 IF status='confirmed' AND NOT EXISTS(SELECT FROM design.audit_entries WHERE event_type='identity.bidder_registered' AND payload->>'bidder_id'=p.bidder_id::text)
 THEN RAISE EXCEPTION 'package_bidder_registration_required' USING ERRCODE='23514'; END IF;
 expected=association||jsonb_build_object('binding_status',status,'authority_id',authority.id);
 IF NEW.bidder_status IS DISTINCT FROM status OR NEW.identity_authority_id IS DISTINCT FROM authority.id
 OR NEW.identity_snapshot-'digest' IS DISTINCT FROM expected
 THEN RAISE EXCEPTION 'package_identity_snapshot_mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER revision_context BEFORE INSERT ON bid_package_revisions FOR EACH ROW EXECUTE FUNCTION package_revision_context_guard();

CREATE FUNCTION package_parse_evidence_manifest(run_id uuid) RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT jsonb_build_object('identity_version','package-parse-evidence/1','parse_run_id',run_id,
 'pages',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY physical_page) FROM
 (SELECT physical_page,printed_label,width::text,height::text,rotation,quality,gaps::text
 FROM design.pages WHERE parse_id=run_id) p),'[]'::jsonb),
 'blocks',coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY physical_page,ordinal,id) FROM
 (SELECT id::text,physical_page,ordinal,kind,text_content,bbox::text,structure::text,digest::text
 FROM design.evidence_blocks WHERE parse_id=run_id) b),'[]'::jsonb))
$$;
CREATE FUNCTION package_parse_binding_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE actual record;
BEGIN
 SELECT r.*,b.digest AS file_digest INTO actual FROM design.parse_runs r
 JOIN design.document_versions v ON v.id=r.document_version_id AND v.bid_id=r.bid_id
 JOIN design.blobs b ON b.id=v.blob_id WHERE r.id=NEW.parse_run_id FOR UPDATE OF r;
 IF actual.id IS NULL OR actual.bid_id IS DISTINCT FROM NEW.bid_id OR actual.document_version_id IS DISTINCT FROM NEW.document_version_id
 OR actual.file_digest IS DISTINCT FROM NEW.file_digest OR actual.parser_digest IS DISTINCT FROM NEW.parser_digest
 OR actual.config_digest IS DISTINCT FROM NEW.config_digest OR actual.page_count IS DISTINCT FROM NEW.page_count
 OR actual.coverage IS DISTINCT FROM 'complete' OR actual.gaps IS DISTINCT FROM '[]'::jsonb OR actual.page_count<1
 OR (SELECT count(*) FROM design.pages WHERE parse_id=NEW.parse_run_id)<>actual.page_count
 OR EXISTS(SELECT FROM design.pages WHERE parse_id=NEW.parse_run_id AND
 (physical_page NOT BETWEEN 1 AND actual.page_count OR quality<>'usable' OR gaps<>'[]'::jsonb))
 OR EXISTS(SELECT FROM design.evidence_blocks WHERE parse_id=NEW.parse_run_id AND
 encode(sha256(convert_to(text_content,'UTF8')),'hex')<>digest)
 OR encode(sha256(convert_to(design.package_canonical_json(design.package_parse_evidence_manifest(NEW.parse_run_id)),'UTF8')),'hex') IS DISTINCT FROM NEW.evidence_digest::text
 THEN RAISE EXCEPTION 'package_parse_binding_invalid' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER parse_binding_source BEFORE INSERT ON bid_package_parse_bindings FOR EACH ROW EXECUTE FUNCTION package_parse_binding_guard();

CREATE FUNCTION package_member_matches_manifest() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE expected jsonb; p design.bid_packages; binding design.bid_package_parse_bindings; actual_file_digest design.sha256;
BEGIN
 SELECT r.manifest->'members'->NEW.ordinal::integer INTO expected FROM design.bid_package_revisions r WHERE r.id=NEW.revision_id;
 SELECT k.* INTO p FROM design.bid_packages k JOIN design.bid_package_revisions r ON r.package_id=k.id WHERE r.id=NEW.revision_id;
 IF expected IS DISTINCT FROM NEW.payload OR NEW.payload->>'member_id' IS DISTINCT FROM NEW.member_id
 OR NEW.payload->>'document_version_id' IS DISTINCT FROM NEW.document_version_id::text
 OR NEW.payload->>'file_digest' IS DISTINCT FROM NEW.file_digest::text
 OR NEW.bid_id IS DISTINCT FROM p.bid_id THEN RAISE EXCEPTION 'package_member_manifest_mismatch' USING ERRCODE='23514'; END IF;
 SELECT b.digest INTO actual_file_digest FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id
 WHERE v.bid_id=NEW.bid_id AND v.id=NEW.document_version_id;
 IF actual_file_digest IS DISTINCT FROM NEW.file_digest THEN
  RAISE EXCEPTION 'package_document_file_mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.parse_run_id IS NOT NULL THEN
  SELECT * INTO binding FROM design.bid_package_parse_bindings WHERE parse_run_id=NEW.parse_run_id;
  IF binding.bid_id IS DISTINCT FROM NEW.bid_id OR binding.document_version_id IS DISTINCT FROM NEW.document_version_id
  OR binding.file_digest IS DISTINCT FROM NEW.file_digest
  OR NEW.payload->'parse'->>'parse_run_id' IS DISTINCT FROM NEW.parse_run_id::text
  OR NEW.payload->'parse'->>'parser_digest' IS DISTINCT FROM binding.parser_digest::text
  OR NEW.payload->'parse'->>'config_digest' IS DISTINCT FROM binding.config_digest::text
  OR NEW.payload->'parse'->>'evidence_digest' IS DISTINCT FROM binding.evidence_digest::text
  OR (NEW.payload->>'page_count')::bigint IS DISTINCT FROM binding.page_count
  THEN RAISE EXCEPTION 'package_parse_binding_mismatch' USING ERRCODE='23514'; END IF;
 ELSIF NEW.payload->'parse'->>'status' IS DISTINCT FROM 'not_frozen' THEN
  RAISE EXCEPTION 'package_parse_binding_missing' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER member_manifest BEFORE INSERT ON bid_package_members FOR EACH ROW EXECUTE FUNCTION package_member_matches_manifest();

CREATE FUNCTION package_part_matches_manifest() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE expected jsonb;
BEGIN
 SELECT payload->'parts'->NEW.ordinal::integer INTO expected FROM design.bid_package_members
 WHERE revision_id=NEW.revision_id AND member_id=NEW.member_id;
 IF expected IS DISTINCT FROM jsonb_build_object('part_id',NEW.part_id,'category',NEW.category,
 'first_page',NEW.first_page,'last_page',NEW.last_page,'shared_attachment',NEW.shared_attachment,'heading_path',NEW.heading_path)
 THEN RAISE EXCEPTION 'package_part_manifest_mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER part_manifest BEFORE INSERT ON bid_package_parts FOR EACH ROW EXECUTE FUNCTION package_part_matches_manifest();

CREATE FUNCTION package_revision_complete() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE parent_revision bigint;
BEGIN
 IF NEW.revision>1 THEN
  SELECT revision INTO parent_revision FROM design.bid_package_revisions WHERE package_id=NEW.package_id AND digest=NEW.predecessor_digest;
  IF parent_revision IS DISTINCT FROM NEW.revision-1 THEN RAISE EXCEPTION 'package_revision_chain_invalid' USING ERRCODE='23514'; END IF;
 END IF;
 IF (SELECT count(*) FROM design.bid_package_members WHERE revision_id=NEW.id) IS DISTINCT FROM jsonb_array_length(NEW.manifest->'members')::bigint
 OR EXISTS(SELECT FROM design.bid_package_members m WHERE m.revision_id=NEW.id AND
 (SELECT count(*) FROM design.bid_package_parts p WHERE p.revision_id=m.revision_id AND p.member_id=m.member_id) IS DISTINCT FROM jsonb_array_length(m.payload->'parts')::bigint)
 THEN RAISE EXCEPTION 'package_revision_incomplete' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER revision_complete AFTER INSERT ON bid_package_revisions DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION package_revision_complete();

CREATE FUNCTION package_head_forward_only() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE r design.bid_package_revisions;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'package_head_delete_forbidden' USING ERRCODE='55000'; END IF;
 SELECT * INTO r FROM design.bid_package_revisions WHERE id=NEW.revision_id AND package_id=NEW.package_id;
 IF r.digest IS DISTINCT FROM NEW.digest OR r.revision IS DISTINCT FROM NEW.revision
 OR (TG_OP='INSERT' AND NEW.revision<>1)
 OR (TG_OP='UPDATE' AND (NEW.package_id<>OLD.package_id OR NEW.revision<>OLD.revision+1 OR r.predecessor_digest IS DISTINCT FROM OLD.digest))
 THEN RAISE EXCEPTION 'package_head_cas_failed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER head_forward BEFORE INSERT OR UPDATE OR DELETE ON bid_package_heads FOR EACH ROW EXECUTE FUNCTION package_head_forward_only();

CREATE FUNCTION frozen_package_parse_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE run_id uuid; old_run_id uuid;
BEGIN
 IF TG_TABLE_NAME='parse_runs' THEN run_id=OLD.id;
 ELSE
  IF TG_OP='DELETE' THEN run_id=OLD.parse_id; ELSE run_id=NEW.parse_id; END IF;
  IF TG_OP='UPDATE' THEN old_run_id=OLD.parse_id; END IF;
  PERFORM id FROM design.parse_runs WHERE id=run_id FOR UPDATE;
 END IF;
 IF EXISTS(SELECT FROM design.bid_package_parse_bindings WHERE parse_run_id=run_id)
 OR EXISTS(SELECT FROM design.bid_package_parse_bindings WHERE parse_run_id=old_run_id)
 THEN RAISE EXCEPTION 'package_parse_is_frozen' USING ERRCODE='55000'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER package_parse_freeze BEFORE UPDATE OR DELETE ON parse_runs FOR EACH ROW EXECUTE FUNCTION frozen_package_parse_guard();
CREATE TRIGGER package_pages_freeze BEFORE INSERT OR UPDATE OR DELETE ON pages FOR EACH ROW EXECUTE FUNCTION frozen_package_parse_guard();
CREATE TRIGGER package_evidence_freeze BEFORE INSERT OR UPDATE OR DELETE ON evidence_blocks FOR EACH ROW EXECUTE FUNCTION frozen_package_parse_guard();

DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['engineering_lots','bid_packages','bid_package_revisions','bid_package_parse_bindings','bid_package_members','bid_package_parts'] LOOP
 EXECUTE format('CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON design.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',name);
 END LOOP;
END $$;
COMMIT;
