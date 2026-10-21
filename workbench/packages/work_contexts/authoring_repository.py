"""Exact saved authoring reads in the caller snapshot; never current-section reads."""

from copy import deepcopy
from typing import Any

from packages.authoring import build_views, package_outputs
from packages.authoring.content import validate_for_schema
from packages.authoring.repository import snapshot_content
from packages.authoring.structure_model import ordered
from packages.domain.runtime import clean, sha
from packages.work_contexts import policy

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def bounded_size(size):
    if size > MAX_SNAPSHOT_BYTES:
        policy.fail("CAPACITY_EXCEEDED", "完整历史正文超过本次只读预算，未截断或替换正文", 413)


def _images(c, bid, snapshot):
    images = (snapshot.get("authoring_images") or {}).get("items", [])
    if not images:
        return [], []
    policy.check(len(images) <= 10000)
    rows = c.execute(
        """SELECT v.id::text,v.asset_id::text,v.revision,v.state,v.digest,v.normalization_proof,v.source_refs,
        a.head_revision,a.head_version_id::text,h.state AS head_state,
        o.id::text AS original_id,o.digest AS original_digest,o.byte_size AS original_byte_size,o.media_type AS original_media_type,
        n.id::text AS normalized_id,n.digest AS normalized_digest,n.byte_size AS normalized_byte_size,n.media_type AS normalized_media_type
        FROM design.authoring_image_versions v
        JOIN design.authoring_image_assets a ON a.bid_id=v.bid_id AND a.id=v.asset_id
        JOIN design.authoring_image_versions h ON h.bid_id=a.bid_id AND h.asset_id=a.id AND h.id=a.head_version_id
        JOIN design.blobs o ON o.id=v.original_blob_id JOIN design.blobs n ON n.id=v.normalized_blob_id
        WHERE v.bid_id=%s AND v.id=ANY(%s::uuid[]) ORDER BY v.id""",
        (bid, [image["asset_version_id"] for image in images]),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    policy.check(len(by_id) == len(rows) == len(images))
    public, heads = [], []
    for image in images:
        row: Any = by_id.get(image["asset_version_id"])
        policy.check(
            row is not None
            and row["asset_id"] == image["asset_id"]
            and row["revision"] == image["asset_revision"]
            and row["state"] == "active"
            and row["digest"] == image["version_digest"]
            and clean(row["normalization_proof"]) == image["normalization_proof"]
            and clean(row["source_refs"]) == image["source_refs"]
            and all(
                row[f"{kind}_{field}"] == image[f"{kind}_blob"][field]
                for kind in ("original", "normalized")
                for field in ("id", "digest", "byte_size", "media_type")
            ),
            "历史图片与确切资产版本、规范化证明或字节身份不能核验",
        )
        public.append(
            {
                **{
                    key: image[key]
                    for key in ("asset_id", "asset_revision", "asset_version_id", "version_digest")
                },
                "normalized_sha256": row["normalized_digest"],
                "media_type": row["normalized_media_type"],
            }
        )
        heads.append(
            {
                "asset_id": image["asset_id"],
                "selected_revision": image["asset_revision"],
                "selected_version_id": image["asset_version_id"],
                **{key: row[key] for key in ("head_revision", "head_version_id", "head_state")},
            }
        )
    return public, heads


def snapshot(c, bid, snapshot_id):
    row = c.execute(
        """SELECT id::text,bid_id::text,draft_id::text,revision,digest,created_at,
        octet_length(manifest::text) AS manifest_bytes FROM design.draft_snapshots
        WHERE bid_id=%s AND id=%s""",
        (bid, snapshot_id),
    ).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目下没有明确选择的已保存快照", 404)
    bounded_size(row["manifest_bytes"])
    members = c.execute(
        """SELECT ss.bid_id::text AS binding_bid,ss.draft_id::text AS binding_draft,ss.ordinal,
        r.id::text,r.bid_id::text,r.draft_id::text,r.section_id::text,r.revision,r.schema_digest,r.digest,
        octet_length(r.content::text) AS content_bytes
        FROM design.draft_snapshot_sections ss LEFT JOIN design.section_revisions r ON r.id=ss.section_revision_id
        WHERE ss.snapshot_id=%s ORDER BY ss.ordinal LIMIT 501""",
        (snapshot_id,),
    ).fetchall()
    policy.check(len(members) <= 500)
    policy.check(all(item["content_bytes"] is not None for item in members))
    bounded_size(row["manifest_bytes"] + sum(item["content_bytes"] for item in members))
    manifest = c.execute(
        "SELECT manifest FROM design.draft_snapshots WHERE bid_id=%s AND id=%s",
        (bid, snapshot_id),
    ).fetchone()["manifest"]
    policy.check(
        isinstance(manifest, dict)
        and set(manifest)
        <= {"draft_id", "revision", "title", "sections", "authoring_structure", "authoring_images"}
        and {"draft_id", "revision", "title", "sections"} <= set(manifest)
        and manifest["draft_id"] == row["draft_id"]
        and manifest["revision"] == row["revision"]
        and sha(manifest) == row["digest"]
        and len(manifest["sections"]) == len(members)
        and len({item["section_id"] for item in members}) == len(members)
        and all(
            item["ordinal"] == ordinal
            and item["binding_bid"] == item["bid_id"] == bid
            and item["binding_draft"] == item["draft_id"] == row["draft_id"]
            and set(saved) == {"id", "revision_id", "revision", "digest", "ordinal"}
            and saved["id"] == item["section_id"]
            and saved["revision_id"] == item["id"]
            and saved["revision"] == item["revision"]
            and saved["digest"] == item["digest"]
            for ordinal, (item, saved) in enumerate(zip(members, manifest["sections"], strict=True))
        ),
        "快照清单与每条原生章节、版本、顺序或项目绑定不一致",
    )
    native = snapshot_content(c, bid, snapshot_id)
    sections = []
    for index, (item, content) in enumerate(zip(members, native["sections"], strict=True)):
        validate_for_schema(content, item["schema_digest"])
        policy.check(
            sha(content) == item["digest"]
            and content["attrs"]["ordinal"] == manifest["sections"][index]["ordinal"]
        )
        sections.append(
            {
                "section_id": item["section_id"],
                "section_revision_id": item["id"],
                "section_revision": item["revision"],
                "schema_digest": item["schema_digest"],
                "digest": item["digest"],
                "ordinal": index,
                "title": content["attrs"]["title"],
                "content": deepcopy(content),
            }
        )
    extension = native.get("authoring_structure")
    outline = (
        [
            {key: item[key] for key in ("section_id", "parent_id", "ordinal", "node_type")}
            for item in ordered(extension["nodes"])
        ]
        if extension is not None
        else None
    )
    images, heads = _images(c, bid, native)
    selection = {
        "kind": "draft_snapshot",
        "bid_id": bid,
        "draft_id": row["draft_id"],
        "draft_revision": row["revision"],
        "snapshot_id": snapshot_id,
        "snapshot_digest": row["digest"],
    }
    return {
        "selection": selection,
        "metadata": {
            **{key: value for key, value in selection.items() if key != "kind"},
            "title": native["title"],
            "created_at": clean(row["created_at"]),
            "section_count": len(sections),
        },
        "document": {"sections": sections, "outline": outline, "images": images, "editable": False},
        "native": native,
        "image_heads": heads,
    }


def build(c, bid, build_id):
    row = c.execute(
        """SELECT b.*,i.draft_snapshot_id,i.manifest,s.draft_id,s.revision AS draft_revision,
        s.digest AS snapshot_digest,o.input_digest,o.kind AS operation_kind,o.state AS operation_state,
        o.handler_version AS operation_handler,o.created_at AS operation_created_at
        FROM design.builds b LEFT JOIN design.build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
        LEFT JOIN design.draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
        LEFT JOIN design.operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
        WHERE b.bid_id=%s AND b.id=%s""",
        (bid, build_id),
    ).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目下没有明确选择的构建", 404)
    policy.check(row["draft_snapshot_id"] is not None and row["operation_kind"] == "build")
    identity = build_views.identity(row)
    manifest = row["manifest"]
    formats = manifest["formats"]
    policy.check(
        row["operation_handler"] == "export/1"
        and row["input_digest"] == sha({"id": str(row["input_id"]), "manifest": manifest})
        and manifest["artifact_kind"] == "bid_body"
        and isinstance(formats, list)
        and 1 <= len(formats) <= 2
        and len(set(formats)) == len(formats)
        and set(formats) <= {"docx", "pdf"}
    )
    saved = snapshot(c, bid, str(row["draft_snapshot_id"]))
    policy.check(
        saved["selection"]["snapshot_digest"] == identity["snapshot_digest"]
        and saved["selection"]["draft_id"] == identity["draft_id"]
        and saved["selection"]["draft_revision"] == identity["draft_revision"]
    )
    outputs = c.execute(
        "SELECT format,state,document_version_id::text,gaps FROM design.build_outputs WHERE bid_id=%s AND build_id=%s ORDER BY format",
        (bid, build_id),
    ).fetchall()
    by_format = {item["format"]: item for item in outputs}
    required_formats = set(formats) | {"docx"}
    policy.check(len(by_format) == len(outputs) and set(by_format) <= required_formats)
    if row["operation_state"] == "succeeded":
        policy.check(
            set(by_format) == required_formats and by_format["docx"]["state"] == "succeeded"
        )
    else:
        policy.check(not outputs, "未成功的构建不能拥有已发布输出记录")
    exposed = []
    for fmt in sorted(required_formats):
        output: Any = by_format.get(fmt)
        document = None
        state = (
            output["state"]
            if output
            else (
                "not_published" if row["operation_state"] in {"failed", "cancelled"} else "pending"
            )
        )
        if state == "succeeded":
            packet = package_outputs.capture(c, bid, build_id, output["document_version_id"])
            proof = packet["proof"]
            policy.check(
                proof["format"] == fmt
                and proof["build_identity"]["snapshot_id"] == identity["snapshot_id"]
            )
            document = {
                "document_version_id": proof["document_version_id"],
                "sha256": proof["sha256"],
                "byte_size": proof["byte_size"],
                "media_type": "application/pdf"
                if fmt == "pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "publication_proof_digest": proof["publication_receipt_digest"],
            }
        elif output:
            policy.check(output["document_version_id"] is None)
        exposed.append(
            {
                "format": fmt,
                "requested": fmt in formats,
                "state": state,
                "document": document,
                "gaps": clean(output["gaps"]) if output else [],
            }
        )
    selection = {
        "kind": "build",
        "build_id": build_id,
        **{key: value for key, value in identity.items() if key not in {"protocol", "request"}},
    }
    return {
        "selection": selection,
        "snapshot": saved,
        "details": {
            "operation_id": str(row["operation_id"]),
            "operation_state": row["operation_state"],
            "created_at": clean(row["operation_created_at"]),
            "outputs": exposed,
        },
    }
