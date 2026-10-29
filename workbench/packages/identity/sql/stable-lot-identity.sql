-- 前进契约：core -> domain -> bid-packages -> 本文件 -> roles；不重写既有绑定审计或包。
BEGIN;
SET search_path TO design,public;

CREATE FUNCTION design.identity_association_v2(target uuid) RETURNS jsonb
 LANGUAGE sql VOLATILE SET search_path=pg_catalog,design AS $$
 SELECT jsonb_build_object('bidder_id',b.id,'bidder_name',b.name,'round_id',r.id,
 'engineering_project_id',e.id,'engineering_title',e.title,'region',e.region,'engineering_type',e.engineering_type,
 'lot_id',r.lot_id,'lot',r.lot,'round_no',r.round_no)
 FROM design.bid_profiles p JOIN design.bidders b ON b.id=p.bidder_id
 JOIN design.bid_rounds r ON r.id=p.round_id JOIN design.engineering_projects e ON e.id=r.engineering_project_id
 WHERE p.bid_id=target
$$;

CREATE FUNCTION design.identity_snapshot_v2(target uuid) RETURNS jsonb
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,design AS $$
DECLARE association jsonb; authority record; confirmed boolean; value jsonb;
BEGIN
 association=design.identity_association_v2(target);
 IF association IS NULL THEN RETURN NULL; END IF;
 SELECT id,payload INTO authority FROM design.audit_entries WHERE bid_id=target AND event_type='identity.bound'
 ORDER BY coalesce((payload->>'identity_epoch')::bigint,0) DESC,created_at DESC,id DESC LIMIT 1;
 confirmed=coalesce(association->'lot_id'<>'null'::jsonb
 AND authority.payload->>'identity_version'='bid-identity/2'
 AND authority.payload->'after'=association AND authority.payload->'confirmed'='true'::jsonb
 AND EXISTS(SELECT FROM design.audit_entries WHERE event_type='identity.bidder_registered'
 AND payload->>'bidder_id'=association->>'bidder_id'),false);
 value=association||jsonb_build_object('binding_status',CASE WHEN confirmed THEN 'confirmed' ELSE 'pending' END,
 'authority_id',authority.id,'identity_version','bid-identity/2');
 RETURN value||jsonb_build_object('digest',encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex'));
END $$;

CREATE OR REPLACE FUNCTION design.package_revision_context_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE p design.bid_packages; expected jsonb;
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
 expected=design.identity_snapshot_v2(p.bid_id);
 IF expected IS NULL OR expected->>'engineering_project_id' IS DISTINCT FROM p.engineering_project_id::text
 OR expected->>'lot_id' IS DISTINCT FROM p.lot_id::text OR expected->>'round_id' IS DISTINCT FROM p.round_id::text
 OR expected->>'bidder_id' IS DISTINCT FROM p.bidder_id::text
 THEN RAISE EXCEPTION 'package_current_profile_mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.bidder_status IS DISTINCT FROM expected->>'binding_status'
 OR NEW.identity_authority_id IS DISTINCT FROM (expected->>'authority_id')::uuid
 OR NEW.identity_snapshot IS DISTINCT FROM expected OR NEW.identity_digest::text IS DISTINCT FROM expected->>'digest'
 THEN RAISE EXCEPTION 'package_identity_snapshot_mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

-- Invoker functions do not confer table privileges. Runtime roles are granted separately.
REVOKE ALL ON FUNCTION design.identity_association_v2(uuid),design.identity_snapshot_v2(uuid) FROM PUBLIC;
COMMIT;
