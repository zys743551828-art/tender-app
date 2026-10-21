"""One immutable build projection for history, recovery and exact output selection."""

from packages.authoring.rich_build import layout_view
from packages.domain.build_followups import follow_up_view
from packages.domain.runtime import DomainError, clean, fetch, sha, validate


def identity(row):
    manifest = row["manifest"]
    if (
        row["operation_kind"] != "build"
        or row["snapshot_digest"] != manifest.get("snapshot_digest")
        or type(row["draft_revision"]) is not int
        or row["draft_revision"] < 1
    ):
        raise DomainError("BUILD_INPUT_CORRUPT", "固定构建与草稿快照身份不一致", 409)
    request = {
        "draft_id": str(row["draft_id"]),
        "draft_revision": row["draft_revision"],
        "formats": manifest["formats"],
        "follow_up": manifest["follow_up"],
    }
    if manifest.get("directory_template_version_id") is not None:
        request.update(
            directory_template_version_id=manifest["directory_template_version_id"],
            style_template_version_id=manifest["style_template_version_id"],
        )
    else:
        request["template_version_id"] = manifest["template_version_id"]
    if manifest.get("writer_kind") == "generated_rich/3":
        request["pagination_mode"] = manifest["pagination_mode"]
    return clean(
        {
            "protocol": "authoring-build-identity/1",
            "bid_id": row["bid_id"],
            "draft_id": row["draft_id"],
            "draft_revision": row["draft_revision"],
            "snapshot_id": row["draft_snapshot_id"],
            "snapshot_digest": row["snapshot_digest"],
            "build_input_id": row["input_id"],
            "input_digest": row["input_digest"],
            "manifest_digest": sha(manifest),
            "writer_kind": manifest.get("writer_kind", "strict_text/1"),
            "request": request,
        }
    )


def build_view(c, build_id):
    row = fetch(
        c,
        """SELECT b.*,i.draft_snapshot_id,i.manifest,s.draft_id,
        s.revision AS draft_revision,s.digest AS snapshot_digest,
        o.input_digest,o.kind AS operation_kind
        FROM builds b JOIN build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
        JOIN draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
        JOIN operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id WHERE b.id=%s""",
        (build_id,),
    )
    outputs = c.execute(
        "SELECT format,state,document_version_id,gaps FROM build_outputs WHERE build_id=%s ORDER BY format",
        (build_id,),
    ).fetchall()
    by_format = {item["format"]: dict(item) for item in outputs}
    for fmt in list(dict.fromkeys(["docx"] + row["manifest"]["formats"])):
        by_format.setdefault(
            fmt, {"format": fmt, "state": "pending", "document_version_id": None, "gaps": []}
        )
    value = clean(
        {
            "id": row["id"],
            "draft_snapshot_id": row["draft_snapshot_id"],
            "operation_id": row["operation_id"],
            "outputs": list(by_format.values()),
        }
    )
    # The frozen target validates its original fields; implementation extensions
    # are projected below without mutating that target contract.
    validate("BuildView", value)
    return value | {
        "identity": identity(row),
        "follow_up": follow_up_view(c, build_id, row["manifest"]),
        "layout": layout_view(c, build_id, row["manifest"]),
    }
