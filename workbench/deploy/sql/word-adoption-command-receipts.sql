-- Expose only successful adoption receipts bound to their immutable audit record.
BEGIN;
CREATE VIEW design.word_adoption_command_receipts WITH (security_barrier=true) AS
SELECT c.id, c.actor_id, c.command_kind, c.target_id, c.request_digest,
       jsonb_build_object('body', c.response->'body') AS response
FROM design.commands c
WHERE c.command_kind = 'adopt_word_render'
  AND EXISTS (
    SELECT 1 FROM design.audit_entries a
    WHERE a.command_id = c.id AND a.actor_id = c.actor_id
      AND a.event_type = 'word.material_adoption_recorded'
      AND a.payload->>'state' = 'adopted'
      AND a.payload->>'source_document_version_id' = c.target_id::text
  );
REVOKE ALL ON design.word_adoption_command_receipts FROM PUBLIC;
GRANT SELECT ON design.word_adoption_command_receipts TO tender_api,tender_worker;
COMMIT;
