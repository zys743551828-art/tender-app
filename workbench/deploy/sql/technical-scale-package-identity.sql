-- Optional forward adapter after technical-scale-authority.sql and stable-lot-identity.sql.
-- Reviewed current_prebid full identity-v2 join; no backfill, new score rights or
-- historical package authority. Test only in a fresh isolated capability database.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('technical_scale.current_context(uuid)') IS NULL
  OR to_regprocedure('design.identity_snapshot_v2(uuid)') IS NULL THEN
  RAISE EXCEPTION 'technical_scale_identity_dependencies_missing' USING ERRCODE='55000';
 END IF;
END $$;

CREATE OR REPLACE FUNCTION technical_scale.current_context(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,technical_scale,historical_backtest,design,pg_temp AS $$
DECLARE
 v technical_scale.versions;
 subject historical_backtest.subjects;
 profile design.bid_profiles;
 actual_identity jsonb;
 actual uuid[];
 expected uuid[];
BEGIN
 v:=technical_scale.lock_version(target);
 IF v.purpose='historical_backtest' THEN
  -- Original single-body historical proof path is deliberately unchanged.
  -- A package submission has no body_version_id and cannot pass this branch.
  PERFORM historical_backtest.lock_submission(v.submission_id);
  SELECT * INTO subject FROM historical_backtest.subjects WHERE id=v.subject_id;
  RETURN subject.bid_id IS NOT DISTINCT FROM v.bid_id AND subject.submission_id IS NOT DISTINCT FROM v.submission_id
   AND subject.identity_snapshot IS NOT DISTINCT FROM v.identity_snapshot
   AND EXISTS(SELECT FROM historical_backtest.subject_heads h JOIN historical_backtest.decisions d ON d.id=h.decision_id
    WHERE h.submission_id=v.submission_id AND h.subject_id=v.subject_id AND h.decision_id=v.subject_decision_id AND d.object_kind='subject' AND d.object_id=v.subject_id AND d.decision='confirmed')
   AND EXISTS(SELECT FROM design.submission_records s JOIN design.document_versions body ON body.id=s.body_version_id JOIN design.blobs b ON b.id=body.blob_id
    WHERE s.id=v.submission_id AND s.bid_id=v.bid_id AND s.body_version_id=subject.body_version_id AND s.submitted_at=subject.submitted_at AND b.digest=subject.body_digest)
   AND EXISTS(SELECT FROM design.bid_rounds r WHERE r.id=subject.round_id AND r.engineering_project_id=subject.engineering_project_id
    AND subject.identity_snapshot->'round_no'=to_jsonb(r.round_no) AND subject.identity_snapshot->'lot' IS NOT DISTINCT FROM coalesce(to_jsonb(r.lot),'null'::jsonb))
   AND historical_backtest.current_proofs(v.subject_id,NULL);
 END IF;

 SELECT * INTO profile FROM design.bid_profiles WHERE bid_id=v.bid_id;
 IF NOT FOUND OR profile.archived_at IS NOT NULL OR profile.phase IN ('closed','terminated') THEN
  RETURN false;
 END IF;
 actual_identity:=design.identity_snapshot_v2(v.bid_id);
 -- Compare the full server-derived snapshot, including stable lot, registered
 -- bidder, round, engineering project, authority ID, version and canonical digest.
 -- Old v1 rows remain immutable and unusable; no missing field is defaulted.
 IF actual_identity IS NULL
  OR actual_identity->>'identity_version' IS DISTINCT FROM 'bid-identity/2'
  OR actual_identity->>'binding_status' IS DISTINCT FROM 'confirmed'
  OR actual_identity->>'lot_id' IS NULL
  OR actual_identity->>'authority_id' IS NULL
  OR v.identity_snapshot IS DISTINCT FROM actual_identity THEN
  RETURN false;
 END IF;
 -- Preserve the registry's exact current tender/supplement material requirement.
 SELECT array_agg(document_version_id ORDER BY document_version_id) INTO actual
  FROM design.material_assignments
  WHERE bid_id=v.bid_id AND snapshot_id=profile.current_material_id AND role IN ('tender','supplement');
 SELECT array_agg(document_version_id ORDER BY document_version_id) INTO expected
  FROM design.material_assignments
  WHERE bid_id=v.bid_id AND snapshot_id=v.material_snapshot_id AND role IN ('tender','supplement');
 RETURN expected IS NOT NULL AND actual IS NOT DISTINCT FROM expected;
END $$;

-- CREATE OR REPLACE preserves ownership and ACL. Reassert its private boundary:
-- API only reaches this function through the already-authorized current_version RPC.
REVOKE ALL ON FUNCTION technical_scale.current_context(uuid) FROM PUBLIC;
COMMIT;
