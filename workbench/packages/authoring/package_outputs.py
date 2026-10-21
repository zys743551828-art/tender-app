"""Exact generated-output admission; a body artifact label is never qualification.

Object bytes are checked outside transactions. The final caller holds the bid
and shared source-graph locks and rechecks the complete immutable observation.
"""

from __future__ import annotations

from uuid import UUID

from packages.authoring import build_views, rich_snapshots, snapshot_structure
from packages.authoring.repository import (
    assert_sources,
    snapshot_content,
    source_authority_manifest,
)
from packages.domain import original_verification
from packages.domain.runtime import DomainError, audit, clean, fetch, now, sha
from packages.knowledge import sources
from packages.rag.indexing import original_source_id
from packages.word_intake.inspection import DOCX, PDF

EVENT = "authoring.output_qualified"
PROTOCOL = "authoring-build-output/1"


def rejected(message="生成文件与成功构建、固定快照或来源关系不能互相核对"):
    raise DomainError("AUTHORING_OUTPUT_NOT_QUALIFIED", message, 409)


def _references(snapshot):
    refs = [ref for section in snapshot["sections"] for ref in section["attrs"]["source_refs"]]
    extension = snapshot.get("authoring_structure")
    if extension is not None:
        refs.extend(
            ref for plan in extension["plans"].values() for ref in plan["payload"]["source_refs"]
        )
        refs.extend(
            ref
            for binding in extension["metadata"].get("format_bindings", [])
            for ref in binding["source_refs"]
        )
    refs.extend(
        ref
        for image in (snapshot.get("authoring_images") or {}).get("items", [])
        for ref in image["source_refs"]
    )
    return refs


def capture(c, bid_id, build_id, document_id):
    """Read-only packet; no source registration or I/O, safe in a repeatable read."""
    row = c.execute(
        """SELECT b.*,i.draft_snapshot_id,i.manifest,s.draft_id,
        s.revision AS draft_revision,s.digest AS snapshot_digest,
        o.input_digest,o.kind AS operation_kind,o.state AS operation_state,
        o.handler_version AS operation_handler
        FROM design.builds b JOIN design.build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
        JOIN design.draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
        JOIN design.operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
        WHERE b.id=%s AND b.bid_id=%s""",
        (build_id, bid_id),
    ).fetchone()
    if row is None:
        rejected()
    identity = build_views.identity(row)
    manifest = row["manifest"]
    if (
        row["operation_state"] != "succeeded"
        or row["operation_handler"] != "export/1"
        or row["input_digest"] != sha({"id": str(row["input_id"]), "manifest": manifest})
        or identity["writer_kind"]
        not in {"strict_text/1", "structured_text/1", "generated_text/2", "generated_rich/3"}
        or manifest.get("artifact_kind") != "bid_body"
    ):
        rejected()
    snapshot = snapshot_content(c, bid_id, row["draft_snapshot_id"])
    if snapshot["snapshot_digest"] != identity["snapshot_digest"]:
        rejected()
    outputs = c.execute(
        """SELECT o.format,o.state,o.document_version_id,d.bid_id,d.artifact_kind,d.obtained_at,
        f.id AS file_id,f.role,v.revision AS file_revision,b.digest,b.byte_size,b.media_type,b.object_key
        FROM design.build_outputs o
        LEFT JOIN design.document_versions d ON d.id=o.document_version_id AND d.bid_id=o.bid_id
        LEFT JOIN design.blobs b ON b.id=d.blob_id
        LEFT JOIN design.document_file_versions v ON v.version_id=d.id AND v.bid_id=d.bid_id
        LEFT JOIN design.document_files f ON f.id=v.file_id AND f.bid_id=v.bid_id
        WHERE o.bid_id=%s AND o.build_id=%s ORDER BY o.format""",
        (bid_id, build_id),
    ).fetchall()
    by_format = {item["format"]: item for item in outputs}
    if len(outputs) != len(by_format) or not set(by_format) <= {"docx", "pdf"}:
        rejected()
    selected = [item for item in outputs if str(item["document_version_id"]) == str(document_id)]
    if len(selected) != 1 or "docx" not in by_format:
        rejected()
    chosen, word = selected[0], by_format["docx"]
    documents = [word] if chosen["format"] == "docx" else [word, chosen]
    for item in documents:
        if (
            item["state"] != "succeeded"
            or str(item["bid_id"]) != str(bid_id)
            or item["artifact_kind"] != "bid_body"
            or item["role"] != "body"
            or item["file_id"] is None
            or type(item["file_revision"]) is not int
            or item["file_revision"] < 1
            or item["media_type"] != (DOCX if item["format"] == "docx" else PDF)
            or type(item["byte_size"]) is not int
            or item["byte_size"] <= 0
        ):
            rejected()
    receipts = c.execute(
        """SELECT payload FROM design.audit_entries WHERE bid_id=%s
        AND event_type='build.outputs_published' AND payload->>'build_id'=%s ORDER BY created_at,id""",
        (bid_id, str(build_id)),
    ).fetchall()
    expected_outputs = {
        item["format"]: str(item["document_version_id"])
        for item in outputs
        if item["state"] == "succeeded"
    }
    if len(receipts) != 1:
        rejected()
    receipt = receipts[0]["payload"]
    chain = receipt.get("conversion_chain")
    if (
        receipt.get("build_id") != str(build_id)
        or receipt.get("snapshot_id") != identity["snapshot_id"]
        or receipt.get("outputs") != expected_outputs
        or not isinstance(chain, dict)
        or chain.get("source_docx_digest") != word["digest"]
    ):
        rejected()
    if chosen["format"] == "pdf":
        relations = c.execute(
            """SELECT source_document_version_id,kind,verification FROM design.document_relations
            WHERE bid_id=%s AND document_version_id=%s ORDER BY source_document_version_id,kind""",
            (bid_id, document_id),
        ).fetchall()
        profile = manifest.get("renderer_identity")
        if (
            len(relations) != 1
            or str(relations[0]["source_document_version_id"]) != str(word["document_version_id"])
            or relations[0]["kind"] != "controlled_render"
            or relations[0]["verification"] != "verified"
            or not isinstance(profile, dict)
            or profile.get("profile_digest") != sha(profile.get("identity"))
            or chain.get("profile_digest") != profile["profile_digest"]
            or chain.get("pdf_digest") != chosen["digest"]
        ):
            rejected("该 PDF 缺少与本次 Word 输出匹配的完整受控转换关系；原文件仍可下载")
    refs = _references(snapshot)
    authority = source_authority_manifest(c, refs)
    proof = {
        "protocol": PROTOCOL,
        "bid_id": str(bid_id),
        "build_id": str(build_id),
        "document_version_id": str(document_id),
        "format": chosen["format"],
        "sha256": chosen["digest"],
        "byte_size": chosen["byte_size"],
        "build_identity": {
            key: value
            for key, value in identity.items()
            if key not in {"protocol", "bid_id", "request"}
        },
        "word_document_version_id": str(word["document_version_id"]),
        "word_sha256": word["digest"],
        "word_pdf_relation": "verified" if chosen["format"] == "pdf" else "not_applicable",
        "publication_receipt_digest": sha(receipt),
        "source_authority_digest": sha(authority),
        "direct_source_ids": sorted({ref["source_id"] for ref in refs}),
    }
    return clean(
        {"proof": proof, "documents": documents, "snapshot": snapshot, "manifest": manifest}
    )


def verify_bytes(packet):
    """Call after closing the input transaction; bounded exact SHA256/size checks."""
    for document in packet["documents"]:
        original_verification.verify(document)


def assert_current(c, packet, *, worker=False):
    proof, snapshot, manifest = packet["proof"], packet["snapshot"], packet["manifest"]
    sources.lock_graph(c)
    for section in snapshot["sections"]:
        assert_sources(c, UUID(proof["bid_id"]), section)
    if manifest.get("writer_kind") in {"structured_text/1", "generated_text/2", "generated_rich/3"}:
        if (
            snapshot_structure.frozen_authority(
                c, UUID(proof["bid_id"]), snapshot["authoring_structure"], snapshot["sections"]
            )
            != manifest["authoring_authority"]
        ):
            rejected("冻结正文、章节计划或版式依据已变化，请核对后生成新文件")
    if manifest.get("writer_kind") == "generated_rich/3":
        rich_snapshots.assert_current(
            c,
            UUID(proof["bid_id"]),
            snapshot.get("authoring_images"),
            snapshot["sections"],
            worker=worker,
        )
    # This checks natural expiry as well as explicit revisions/withdrawals.
    sources.authority_manifest(c, [UUID(value) for value in proof["direct_source_ids"]], now())


def _nodes(c, packet, *, register, lock=True):
    """Generated Word retains every declared basis; PDF is a child of exact Word."""
    proof = packet["proof"]
    word = original_source_id(UUID(proof["word_document_version_id"]))
    for document in packet["documents"]:
        document_id = UUID(document["document_version_id"])
        identity = original_source_id(document_id)
        if register:
            c.execute(
                """INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest)
                VALUES(%s,%s,'document','prebid_content',%s,%s) ON CONFLICT(id) DO NOTHING""",
                (identity, document_id, document["obtained_at"], document["digest"]),
            )
        node = c.execute("SELECT * FROM retrieval.source_nodes WHERE id=%s", (identity,)).fetchone()
        if (
            node is None
            or str(node["document_version_id"]) != str(document_id)
            or node["digest"] != document["digest"]
            or node["kind"] != "document"
            or node["policy_class"] != "prebid_content"
        ):
            rejected("生成文件的来源身份与原件不一致")
        if register:
            c.execute(
                """INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from)
                VALUES(%s,1,'candidate',%s) ON CONFLICT(source_id) DO NOTHING""",
                (identity, document["obtained_at"]),
            )
        head = fetch(
            c,
            (
                "SELECT * FROM retrieval.source_heads WHERE source_id=%s FOR UPDATE"
                if lock
                else "SELECT * FROM retrieval.source_heads WHERE source_id=%s"
            ),
            (identity,),
        )
        if head["status"] not in ({"candidate", "published"} if register else {"published"}):
            rejected("生成文件来源已撤回或状态未知，不能重新采用")
        parents = set(proof["direct_source_ids"]) if document["format"] == "docx" else {str(word)}
        existing = {
            str(row["parent_id"])
            for row in c.execute(
                "SELECT parent_id FROM retrieval.lineage_edges WHERE child_id=%s", (identity,)
            ).fetchall()
        }
        if not existing <= parents or not register and existing != parents:
            rejected("生成文件的完整来源边与冻结编写依据不一致")
        if register:
            for parent in sorted(parents - existing):
                c.execute(
                    "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (identity, UUID(parent)),
                )
            c.execute(
                "UPDATE retrieval.source_heads SET status='published',revision=revision+1 WHERE source_id=%s AND status='candidate'",
                (identity,),
            )
        authority = sources.authority_manifest(c, [identity], now())
        if any(row["policy_class"] != "prebid_content" for row in authority):
            rejected("生成文件包含不可用于投标编制的来源祖先")


def qualify(c, packet, actor, command_id):
    sources.lock_graph(c)
    proof = packet["proof"]
    current = capture(c, proof["bid_id"], proof["build_id"], proof["document_version_id"])
    if current != packet:
        rejected("原件核对期间构建或来源状态变化，尚未采用文件")
    assert_current(c, packet)
    _nodes(c, packet, register=True)
    audit(
        c, actor, proof["bid_id"], EVENT, {"proof": proof, "proof_digest": sha(proof)}, command_id
    )


def admitted(c, bid_id, document_id, *, worker=False):
    """Existing package edits can reuse only a real, still valid adoption qualification."""
    sources.lock_graph(c)
    rows = c.execute(
        """SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
        AND payload->'proof'->>'document_version_id'=%s ORDER BY created_at,id""",
        (bid_id, EVENT, str(document_id)),
    ).fetchall()
    if not rows:
        return False
    value = rows[0]["payload"]
    proof = value.get("proof")
    if not isinstance(proof, dict) or value.get("proof_digest") != sha(proof):
        rejected()
    packet = capture(c, bid_id, proof["build_id"], document_id)
    if packet["proof"] != proof:
        rejected("此前生成物采用依据与当前固定来源不一致")
    assert_current(c, packet, worker=worker)
    _nodes(c, packet, register=False)
    return True


def observe_admission(c, bid_id, document_id):
    """SELECT-only current-use observation, safe under an outer RR snapshot.

    None means this is not an authoring build output; ordinary uploaded originals
    keep their existing qualification path. Generated outputs must be qualified.
    Consumers must repeat this observation under the existing bid/graph locks
    immediately before new publication. Historical downloads do not call it.
    """
    generated = c.execute(
        """SELECT o.build_id FROM design.build_outputs o
        WHERE o.bid_id=%s AND o.document_version_id=%s""",
        (bid_id, document_id),
    ).fetchall()
    if not generated:
        return None
    try:
        if len(generated) != 1:
            rejected()
        rows = c.execute(
            """SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
            AND payload->'proof'->>'document_version_id'=%s ORDER BY created_at,id""",
            (bid_id, EVENT, str(document_id)),
        ).fetchall()
        if not rows:
            rejected()
        receipt = rows[0]["payload"]
        packet = capture(c, bid_id, generated[0]["build_id"], document_id)
        proof = packet["proof"]
        if receipt.get("proof") != proof or receipt.get("proof_digest") != sha(proof):
            rejected()
        snapshot = packet["snapshot"]
        contents = list(snapshot["sections"])
        extension = snapshot.get("authoring_structure")
        if packet["manifest"].get("writer_kind") in {
            "structured_text/1",
            "generated_text/2",
            "generated_rich/3",
        }:
            current = snapshot_structure.frozen_authority(
                c, UUID(str(bid_id)), extension, snapshot["sections"], lock_sources=False
            )
            if current != packet["manifest"]["authoring_authority"]:
                rejected("冻结正文、计划或格式确认依据已变化")
            contents = []  # The complete shared authority guard already checks these references.
        additional_refs = [
            item["source_refs"]
            for item in (snapshot.get("authoring_images") or {}).get("items", [])
        ]
        if extension is not None:
            additional_refs.extend(
                item["source_refs"] for item in extension["metadata"].get("format_bindings", [])
            )
        contents.extend(
            {
                "type": "doc",
                "attrs": {
                    "title": "冻结输出依据",
                    "ordinal": 0,
                    "source_refs": refs,
                    "rule_ids": [],
                },
                "content": [],
            }
            for refs in additional_refs
        )
        # Check exact current references without taking locks in this read snapshot.
        for content in contents:
            assert_sources(c, UUID(str(bid_id)), content, lock_sources=False)
        _nodes(c, packet, register=False, lock=False)
        expected = (snapshot.get("authoring_images") or {}).get("items", [])
        images = []
        if expected:
            actual = c.execute(
                """SELECT a.id AS asset_id,a.head_revision,a.head_version_id,
                v.revision,v.state,v.digest,v.normalization_proof,v.source_refs,
                v.original_blob_id,v.normalized_blob_id
                FROM design.authoring_image_assets a
                JOIN design.authoring_image_versions v
                  ON v.bid_id=a.bid_id AND v.asset_id=a.id AND v.id=a.head_version_id
                WHERE a.bid_id=%s AND a.id=ANY(%s) ORDER BY a.id""",
                (bid_id, [UUID(item["asset_id"]) for item in expected]),
            ).fetchall()
            by_id = {str(row["asset_id"]): clean(row) for row in actual}
            if set(by_id) != {item["asset_id"] for item in expected}:
                rejected()
            for item in expected:
                row = by_id[item["asset_id"]]
                if (
                    row["head_version_id"] != item["asset_version_id"]
                    or row["head_revision"] != item["asset_revision"]
                    or row["revision"] != item["asset_revision"]
                    or row["state"] != "active"
                    or row["digest"] != item["version_digest"]
                    or row["normalization_proof"] != item["normalization_proof"]
                    or row["source_refs"] != item["source_refs"]
                    or row["original_blob_id"] != item["original_blob"]["id"]
                    or row["normalized_blob_id"] != item["normalized_blob"]["id"]
                ):
                    rejected()
                images.append(
                    {
                        key: row[key]
                        for key in (
                            "asset_id",
                            "head_revision",
                            "head_version_id",
                            "state",
                            "digest",
                        )
                    }
                )
        return {
            "protocol": "authoring-output-current/1",
            "state": "matched",
            "bid_id": str(bid_id),
            "document_version_id": str(document_id),
            "build_id": proof["build_id"],
            "qualification_digest": sha(proof),
            "source_authority_digest": proof["source_authority_digest"],
            "images": sorted(images, key=lambda item: item["asset_id"]),
        }
    except (DomainError, KeyError, TypeError, ValueError, AttributeError) as error:
        return {
            "protocol": "authoring-output-current/1",
            "state": "blocked",
            "bid_id": str(bid_id),
            "document_version_id": str(document_id),
            "reason_code": error.code
            if isinstance(error, DomainError)
            else "AUTHORING_OUTPUT_CORRUPT",
        }
