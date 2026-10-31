"""SELECT-only exact Word/PDF provenance for package storage; no review qualification."""

from packages.domain.bid_packages import PackageError
from packages.domain.runtime import clean, sha
from packages.word_intake.inspection import DOCX, PDF
from packages.word_intake.repository import controlled_qualified

ERROR = "PACKAGE_CONTROLLED_WORD_SOURCE_INVALID"


def require(value):
    if not value:
        raise PackageError(ERROR)


def _rows(c, query, args):
    return c.execute(query, args).fetchall()


def _one(c, query, args):
    return c.execute(query, args).fetchone()


def observe(c, bid, document, *, current=False, expected_digest=None):
    """None means unrelated to Word. Invalid claimed derivation is never ignored.

    Current admission requires the exact currently adopted latest requested run.
    Historical reads validate the saved PDF's own immutable run/adoption; a later
    failed request does not replace that evidence. Object bytes are separately
    checked by the existing original-verification IO boundary.
    """
    ready = _one(
        c,
        "SELECT to_regclass('design.word_render_runs') IS NOT NULL AND "
        "to_regclass('design.word_intake_receipts') IS NOT NULL AS ready, "
        "to_regclass('design.build_outputs') IS NOT NULL AS authoring_ready",
        (),
    )
    if not ready or not ready["ready"]:
        return None
    marker = _one(
        c,
        """SELECT EXISTS(SELECT 1 FROM design.document_relations rel
          JOIN design.word_intake_receipts w ON w.bid_id=rel.bid_id
            AND w.document_version_id=rel.source_document_version_id
          WHERE rel.bid_id=%s AND rel.document_version_id=%s AND rel.kind='controlled_render') AS word_relation,
        EXISTS(SELECT 1 FROM design.word_render_runs WHERE bid_id=%s
          AND pdf_document_version_id=%s) AS word_run,
        EXISTS(SELECT 1 FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id
          WHERE d.bid_id=%s AND d.id=%s AND b.object_key LIKE 'word-rendered/%%'
          AND NOT EXISTS(SELECT 1 FROM design.uploads u WHERE u.bid_id=d.bid_id
            AND u.verified_version_id=d.id AND u.state='verified'
            AND u.declared_digest=b.digest AND u.declared_size=b.byte_size)) AS unproven_word_blob""",
        (bid, document, bid, document, bid, document),
    )
    if not marker:
        return None
    if not marker["word_relation"] and not marker["word_run"]:
        if not marker["unproven_word_blob"]:
            return None
        # Authoring also has controlled_render relations and may deduplicate a
        # blob. Its existing build/adoption observer remains the authority.
        if (
            ready["authoring_ready"]
            and _one(
                c,
                "SELECT 1 FROM design.build_outputs WHERE bid_id=%s AND document_version_id=%s",
                (bid, document),
            )
            is not None
        ):
            return None
    rows = _rows(
        c,
        """SELECT r.operation_id,r.source_document_version_id,r.profile_digest,
          r.frozen_profile,r.outcome,o.state AS operation_state,o.kind AS operation_kind,
          o.handler_version,o.input_digest,w.upload_id,w.inspection_digest,w.inspection_report,
          u.state AS upload_state,u.verified_version_id,u.role AS upload_role,
          u.declared_digest,u.declared_size,vo.state AS verify_state,
          s.id AS source_id,sb.digest AS source_digest,sb.byte_size AS source_size,
          sb.media_type AS source_media_type,sf.id AS source_file_id,sf.role AS source_role,
          sf.head_version_id AS source_head,p.id AS pdf_id,p.artifact_kind,
          pb.digest AS pdf_digest,pb.byte_size AS pdf_size,pb.media_type AS pdf_media_type,
          pb.object_key AS pdf_object_key,
          pf.id AS pdf_file_id,pf.role AS pdf_role,pf.head_version_id AS pdf_head,
          rel.source_document_version_id AS relation_source,rel.verification
        FROM design.word_render_runs r
        JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id
        JOIN design.word_intake_receipts w ON w.bid_id=r.bid_id AND w.document_version_id=r.source_document_version_id
        JOIN design.uploads u ON u.id=w.upload_id AND u.bid_id=w.bid_id
        JOIN design.operations vo ON vo.id=w.verify_operation_id AND vo.bid_id=w.bid_id
        JOIN design.document_versions s ON s.id=w.document_version_id AND s.bid_id=w.bid_id
        JOIN design.blobs sb ON sb.id=s.blob_id
        JOIN design.document_file_versions sv ON sv.version_id=s.id AND sv.bid_id=s.bid_id
        JOIN design.document_files sf ON sf.id=sv.file_id AND sf.bid_id=sv.bid_id
        JOIN design.document_versions p ON p.id=r.pdf_document_version_id AND p.bid_id=r.bid_id
        JOIN design.blobs pb ON pb.id=p.blob_id
        JOIN design.document_file_versions pv ON pv.version_id=p.id AND pv.bid_id=p.bid_id
        JOIN design.document_files pf ON pf.id=pv.file_id AND pf.bid_id=pv.bid_id
        JOIN design.document_relations rel ON rel.bid_id=r.bid_id AND rel.document_version_id=p.id
          AND rel.kind='controlled_render'
        WHERE r.bid_id=%s AND r.pdf_document_version_id=%s""",
        (bid, document),
    )
    require(len(rows) == 1)
    row = clean(rows[0])
    try:
        _validate(row, str(document), expected_digest)
        adoptions = _rows(
            c,
            """SELECT a.id,a.payload,a.actor_id,cmd.command_kind,cmd.target_id,
            cmd.actor_id AS command_actor,cmd.request_digest,cmd.response
            FROM design.audit_entries a LEFT JOIN design.word_adoption_command_receipts cmd ON cmd.id=a.command_id
            WHERE a.bid_id=%s
            AND event_type='word.material_adoption_recorded'
            AND payload->>'state'='adopted' AND payload->>'document_version_id'=%s
            AND payload->>'conversion_operation_id'=%s
            AND payload->>'source_document_version_id'=%s ORDER BY a.created_at,a.id""",
            (bid, str(document), row["operation_id"], row["source_id"]),
        )
        require(bool(adoptions))
        # Every candidate is an immutable successful adoption of this exact run;
        # verify its original selection and material scope, not a current pointer.
        for adoption in adoptions:
            _adoption(c, bid, row, clean(adoption))
        if current:
            latest = _one(
                c,
                """SELECT operation_id FROM design.word_render_runs WHERE bid_id=%s
                AND source_document_version_id=%s ORDER BY created_at DESC,operation_id DESC LIMIT 1""",
                (bid, row["source_id"]),
            )
            require(latest and str(latest["operation_id"]) == row["operation_id"])
            require(row["source_head"] == row["source_id"] and row["pdf_head"] == row["pdf_id"])
            selected = _one(
                c,
                """SELECT p.current_body_id FROM design.bid_profiles p
                JOIN design.material_assignments a ON a.bid_id=p.bid_id AND a.snapshot_id=p.current_material_id
                WHERE p.bid_id=%s AND a.document_version_id=%s AND a.role=%s""",
                (bid, document, row["pdf_role"]),
            )
            require(
                selected
                and (row["pdf_role"] != "body" or str(selected["current_body_id"]) == str(document))
            )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PackageError(ERROR) from None
    return {
        "kind": "controlled_word_pdf",
        "source_document_version_id": row["source_id"],
        "document_version_id": row["pdf_id"],
        "source_sha256": row["source_digest"],
        "source_byte_size": row["source_size"],
        "pdf_sha256": row["pdf_digest"],
        "pdf_byte_size": row["pdf_size"],
        "operation_id": row["operation_id"],
        "profile_digest": row["profile_digest"],
    }


def _validate(row, document, expected_digest):
    outcome, profile = row["outcome"], row["frozen_profile"]
    require(isinstance(profile, dict) and isinstance(profile.get("identity"), dict))
    require(profile.get("profile_digest") == sha(profile["identity"]) == row["profile_digest"])
    require(controlled_qualified(outcome))
    chain = outcome["chain"]
    require(
        row["operation_state"] == "succeeded"
        and row["operation_kind"] == "word-render"
        and row["handler_version"] == "word-render/1"
    )
    require(row["verify_state"] == "succeeded" and row["upload_state"] == "verified")
    require(
        row["verified_version_id"]
        == row["source_id"]
        == row["source_document_version_id"]
        == row["relation_source"]
    )
    require(row["source_media_type"] == DOCX and row["pdf_media_type"] == PDF)
    require(
        row["source_size"] > 0
        and row["pdf_size"] > 0
        and row["source_size"] == row["declared_size"]
    )
    require(row["source_digest"] == row["declared_digest"] == chain["source_docx_digest"])
    require(row["pdf_id"] == document and row["pdf_digest"] == chain["pdf_digest"])
    require(expected_digest is None or row["pdf_digest"] == expected_digest)
    require(row["upload_role"] == row["source_role"] == row["pdf_role"])
    require(row["pdf_role"] in {"body", "tender", "supplement", "drawing", "boq"})
    require(
        row["artifact_kind"] == ("bid_body" if row["pdf_role"] == "body" else "source_original")
    )
    require(row["verification"] == "verified" and row["profile_digest"] == chain["profile_digest"])
    require(
        all(
            chain[k] == profile["identity"].get(k)
            for k in ("renderer_digest", "fontset_digest", "options_digest")
        )
    )
    require(
        row["input_digest"]
        == sha(
            {
                "id": row["source_id"],
                "digest": row["source_digest"],
                "render_profile_digest": row["profile_digest"],
            }
        )
    )
    require(
        sha(row["inspection_report"]) == row["inspection_digest"]
        and row["inspection_report"].get("conversion_eligible") is True
    )


def _adoption(c, bid, row, adoption):
    payload = adoption["payload"]
    selection = _one(
        c,
        """SELECT payload,actor_id FROM design.audit_entries WHERE bid_id=%s AND id=%s
        AND event_type='word.material_selected'""",
        (bid, payload["selection_id"]),
    )
    require(selection is not None)
    require(str(selection["actor_id"]) == adoption["actor_id"] == adoption["command_actor"])
    selection = clean(selection["payload"])
    context = selection["context"]
    require(selection["context_digest"] == sha(context))
    conversion = {
        "document_version_id": row["pdf_id"],
        "file_id": row["pdf_file_id"],
        "digest": row["pdf_digest"],
        "byte_size": row["pdf_size"],
        "object_key": row["pdf_object_key"],
        "source_document_version_id": row["source_id"],
        "operation_id": row["operation_id"],
        "profile_digest": row["profile_digest"],
    }
    require(
        adoption["command_kind"] == "adopt_word_render"
        and adoption["target_id"] == row["source_id"]
    )
    require(adoption["response"]["body"] == payload)
    require(
        adoption["request_digest"]
        == sha(
            {
                "body": {
                    "selection_id": payload["selection_id"],
                    "context_digest": selection["context_digest"],
                    "conversion": conversion,
                },
                "if_match": None,
            }
        )
    )
    require(
        selection["source_document_version_id"]
        == context["source_document_version_id"]
        == row["source_id"]
    )
    require(
        context["source_sha256"] == row["source_digest"]
        and context["file_id"] == row["source_file_id"]
        and context["role"] == row["pdf_role"]
    )
    snapshot = _one(
        c,
        "SELECT revision,manifest,digest FROM design.material_snapshots WHERE bid_id=%s AND id=%s",
        (bid, payload["material_snapshot_id"]),
    )
    require(snapshot is not None)
    require(
        snapshot["revision"] == payload["material_revision"] == context["material_revision"] + 1
    )
    require(sha(snapshot["manifest"]["documents"]) == snapshot["digest"])
    require(
        any(
            str(x["document_version_id"]) == row["pdf_id"]
            and x["role"] == row["pdf_role"]
            and str(x["file_id"]) == row["pdf_file_id"]
            for x in snapshot["manifest"]["documents"]
        )
    )
    for snapshot_id, document in (
        (context["current_material_id"], row["source_id"]),
        (payload["material_snapshot_id"], row["pdf_id"]),
    ):
        require(
            _one(
                c,
                "SELECT 1 FROM design.material_assignments WHERE bid_id=%s AND snapshot_id=%s AND document_version_id=%s AND role=%s",
                (bid, snapshot_id, document, row["pdf_role"]),
            )
            is not None
        )


def eligible(c, bid, document):
    """Discovery may show an invalid candidate, but never advertises its qualification."""
    try:
        return observe(c, bid, document, current=True) is not None
    except PackageError:
        return False
