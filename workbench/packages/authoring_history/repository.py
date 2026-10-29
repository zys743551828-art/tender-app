"""Read original immutable section/asset rows, never current content or authority."""

from packages.authoring.content import validate_for_schema
from packages.authoring_history import permissions
from packages.domain.runtime import DomainError, clean, sha

MAX_CONTENT_BYTES = 16 * 1024 * 1024


def check(condition):
    if not condition:
        raise DomainError(
            "AUTHORING_HISTORY_CORRUPT", "历史章节、正文摘要或图片原生版本不能核验", 500
        )


def image_identities(content):
    result: dict[str, tuple[str, int, str]] = {}

    def walk(node):
        if node["type"] == "image":
            attrs = node["attrs"]
            identity = (attrs["asset_id"], attrs["asset_revision"], attrs["asset_version_id"])
            prior = result.setdefault(identity[2], identity)
            check(prior == identity)
        for child in node.get("content", []):
            walk(child)

    walk(content)
    return result


def images(c, bid, content):
    expected = image_identities(content)
    if not expected:
        return []
    permissions.tables(c, permissions.IMAGE_TABLES)
    rows = c.execute(
        """SELECT v.*,a.id AS native_asset_id,a.bid_id AS native_asset_bid,
        original.digest AS original_digest,original.media_type AS original_media,
        normalized.digest AS normalized_digest,normalized.media_type AS normalized_media,
        normalized.byte_size AS normalized_size
        FROM design.authoring_image_versions v
        LEFT JOIN design.authoring_image_assets a ON a.id=v.asset_id AND a.bid_id=v.bid_id
        LEFT JOIN design.blobs original ON original.id=v.original_blob_id
        LEFT JOIN design.blobs normalized ON normalized.id=v.normalized_blob_id
        WHERE v.id=ANY(%s::uuid[]) AND v.bid_id=%s ORDER BY v.id""",
        (list(expected), bid),
    ).fetchall()
    check(len(rows) == len(expected))
    result = []
    for row in rows:
        asset, revision, version = expected[str(row["id"])]
        proof = row["normalization_proof"]
        check(
            str(row["bid_id"]) == bid
            and str(row["native_asset_bid"]) == bid
            and str(row["asset_id"]) == asset
            and str(row["native_asset_id"]) == asset
            and row["revision"] == revision
            and row["state"] == "active"
            and isinstance(proof, dict)
        )
        check(
            proof.get("protocol") == "authoring-raster-normalization/1"
            and proof.get("input_digest") == row["original_digest"]
            and proof.get("input_media_type") == row["original_media_type"] == row["original_media"]
            and proof.get("output_digest") == row["normalized_digest"]
            and proof.get("output_media_type") == row["normalized_media"] == "image/png"
            and type(proof.get("output_byte_size")) is int
            and 0 < proof["output_byte_size"] <= MAX_CONTENT_BYTES
            and proof["output_byte_size"] == row["normalized_size"]
            and type(row["width_px"]) is int
            and type(row["height_px"]) is int
            and 1 <= row["width_px"] <= 10000
            and 1 <= row["height_px"] <= 10000
            and row["width_px"] * row["height_px"] <= 16000000
            and proof.get("width_px") == row["width_px"]
            and proof.get("height_px") == row["height_px"]
        )
        # Active asset revisions are immutable native records. Current asset
        # heads, withdrawal, current model code or a newer image never replace it.
        check(
            row["digest"]
            == sha(
                {
                    key: row[key]
                    for key in (
                        "bid_id",
                        "asset_id",
                        "revision",
                        "original_blob_id",
                        "normalized_blob_id",
                        "normalization_proof",
                        "source_refs",
                        "state",
                        "reason",
                    )
                }
            )
        )
        result.append(
            {
                "asset_id": asset,
                "asset_revision": revision,
                "asset_version_id": version,
                "version_digest": row["digest"],
                "normalized_sha256": row["normalized_digest"],
                "media_type": "image/png",
            }
        )
    return result


def section(c, bid, draft, section_id, revision, expected_digest):
    row = c.execute(
        """SELECT r.id,r.bid_id,r.draft_id,r.section_id,r.revision,r.schema_digest,r.digest,
        r.created_by,r.created_at,octet_length(r.content::text) AS content_bytes
        FROM design.section_revisions r JOIN design.sections s
          ON s.id=r.section_id AND s.bid_id=r.bid_id AND s.draft_id=r.draft_id
        JOIN design.drafts d ON d.id=s.draft_id AND d.bid_id=s.bid_id
        WHERE r.bid_id=%s AND r.draft_id=%s AND r.section_id=%s AND r.revision=%s""",
        (bid, draft, section_id, revision),
    ).fetchone()
    if row is None:
        raise DomainError("AUTHORING_HISTORY_NOT_FOUND", "该项目与草稿下没有所选章节原修订", 404)
    if row["content_bytes"] > MAX_CONTENT_BYTES:
        raise DomainError(
            "AUTHORING_HISTORY_TOO_LARGE", "所选完整历史章节超过本次16MiB读取预算，未截断正文", 413
        )
    content = c.execute(
        "SELECT content FROM design.section_revisions WHERE id=%s AND bid_id=%s AND draft_id=%s AND section_id=%s AND revision=%s",
        (row["id"], bid, draft, section_id, revision),
    ).fetchone()["content"]
    check(sha(content) == row["digest"])
    validate_for_schema(content, row["schema_digest"])
    if row["digest"] != expected_digest:
        raise DomainError(
            "AUTHORING_HISTORY_DIGEST_CHANGED",
            "返回正文摘要与所选历史记录不一致，请保留原选择后重读目录",
            412,
        )
    return clean(
        {
            "version": "authoring-historical-section/1",
            "bid_id": row["bid_id"],
            "draft_id": row["draft_id"],
            "section_id": row["section_id"],
            "section_revision_id": row["id"],
            "revision": row["revision"],
            "schema_digest": row["schema_digest"],
            "digest": row["digest"],
            "content": content,
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "images": images(c, bid, content),
            "read_only": True,
            "source_qualification_assessed": False,
            "restoration_authorized": False,
        }
    )
