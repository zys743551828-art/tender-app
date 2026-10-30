"""RICH build orchestration on existing export/1: no DB during compute/network."""

import re
from pathlib import Path

from packages.domain import storage
from packages.domain.runtime import DomainError, fetch, sha, uid

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def writer_digest():
    from packages.authoring import rich_docx, rich_renderer, rich_verification

    return sha(
        {
            "producer": rich_docx.identity(),
            "validator": sha(Path(rich_verification.__file__).read_bytes()),
            "renderer": sha(Path(rich_renderer.__file__).read_bytes()),
        }
    )


def read_checked(descriptor):
    size = descriptor["byte_size"]
    if type(size) is not int or not 0 < size <= 64 * 1024 * 1024:
        raise DomainError("BUILD_OBJECT_LIMIT", "构建对象大小超出冻结范围", 422)
    value = storage.client().get_object(Bucket=storage.bucket(), Key=descriptor["object_key"])
    try:
        data = value["Body"].read(size + 1)
    finally:
        value["Body"].close()
    if len(data) != size or sha(data) != descriptor["digest"]:
        raise DomainError("BUILD_OBJECT_CORRUPT", "构建对象实际字节与冻结摘要不符", 503)
    return data


def store(data, media):
    descriptor = {
        "digest": sha(data),
        "byte_size": len(data),
        "object_key": "blobs/" + sha(data),
        "media_type": media,
    }
    storage.put(descriptor["object_key"], data, media)
    read_checked(descriptor)
    return descriptor


def summary(value):
    """Audit metadata keeps IDs/pages/digests; chapter prose remains in the snapshot."""
    if isinstance(value, dict):
        return {
            key: summary(item)
            for key, item in value.items()
            if key not in {"title", "toc_display_title"}
        }
    if isinstance(value, list):
        return [summary(item) for item in value]
    return value


def compute(prepared):
    from packages.authoring import rich_docx, rich_snapshots

    info, snapshot = prepared["info"], prepared["snapshot"]
    manifest = info["manifest"]
    if (
        manifest["writer_digest"] != writer_digest()
        or manifest["generator_identity"] != rich_docx.identity()
    ):
        raise DomainError("BUILD_WRITER_CHANGED", "表图生产器已变化，请明确创建新构建", 409)
    if manifest["authoring_structure_digest"] != snapshot["authoring_structure"]["digest"]:
        raise DomainError("BUILD_INPUT_CORRUPT", "表图双模板快照不匹配", 409)
    images = rich_snapshots.checked(snapshot.get("authoring_images"), snapshot["sections"])
    if manifest["authoring_images_digest"] != (images["digest"] if images else None):
        raise DomainError("BUILD_INPUT_CORRUPT", "冻结图片清单摘要不匹配", 409)
    materials = []
    for item in images["items"] if images else []:
        descriptor = item["normalized_blob"]
        if descriptor["media_type"] != "image/png" or descriptor["byte_size"] > 16 * 1024 * 1024:
            raise DomainError("AUTHORING_IMAGE_SNAPSHOT_CORRUPT", "规范图片格式或大小超出范围", 409)
        materials.append(
            {
                "asset_id": item["asset_id"],
                "asset_revision": item["asset_revision"],
                "asset_version_id": item["asset_version_id"],
                "normalization_proof": item["normalization_proof"],
                "bytes": read_checked(descriptor),
            }
        )
    from packages.authoring.prebuilt_dispatch import rich as render_rich

    value = render_rich(
        snapshot, materials, manifest["renderer_identity"], mode=manifest["pagination_mode"]
    )
    docx, pdf = value["docx"], value.get("pdf")
    chain = value["chain"] | {
        "producer_manifest": value["producer_manifest"],
        "pagination_mode": manifest["pagination_mode"],
        "navigation_proof": summary(value.get("navigation_proof")),
        "navigation_history_proof": summary(value.get("navigation_history_proof")),
        "intermediate_artifacts": [],
    }
    auxiliary = []
    for index, iteration in enumerate(value["render_iterations"], start=1):
        pair = {"iteration": index}
        for name, data, media in [
            ("docx", iteration["docx_bytes"], DOCX),
            ("pdf", iteration["pdf_bytes"], "application/pdf"),
        ]:
            descriptor = store(data, media)
            auxiliary.append(descriptor)
            pair[name + "_digest"] = descriptor["digest"]
        chain["intermediate_artifacts"].append(pair)
    result = {
        "input_id": prepared["input_id"],
        "snapshot_id": str(info["draft_snapshot_id"]),
        "snapshot_digest": snapshot["snapshot_digest"],
        "manifest": manifest,
        "outputs": [],
        "render_coverage": value["coverage"],
        "render_isolation": value.get("isolation"),
        "render_correspondence": summary(value.get("correspondence")),
        "conversion_chain": chain,
        "auxiliary_artifacts": auxiliary,
    }
    gaps = list(value["gaps"])
    if re.search(r"\{\{[^}]*\}\}|待补充|待填写|\bTODO\b", str(snapshot["sections"])):
        gaps.append("PLACEHOLDER_CONTENT_PRESENT")
    navigation = (value.get("navigation_proof") or {}).get("final_navigation") or {}
    if not navigation.get("toc_values_verified"):
        gaps.append("TOC_PAGE_NUMBERS_UNKNOWN")
    if not navigation.get("entries") or any(
        entry.get("end_page") is None for entry in navigation.get("entries", [])
    ):
        gaps.append("ACTUAL_SECTION_PAGE_RANGES_UNKNOWN")
    config = snapshot["authoring_structure"]["metadata"].get(
        "effective_style", snapshot["authoring_structure"]["style_template"]["config"]
    )
    correspondence = value.get("correspondence") or {}
    if config["page_number"] and (
        not correspondence.get("pages")
        or not all(page.get("footer_matches") for page in correspondence["pages"])
    ):
        gaps.append("PAGE_CORRESPONDENCE_UNVERIFIED")
    chain["format_gaps"] = list(dict.fromkeys(gaps))
    for fmt in list(dict.fromkeys(["docx"] + manifest["formats"])):
        data = docx if fmt == "docx" else pdf
        notes = list(gaps)
        if data is None:
            result["outputs"].append({"format": fmt, "state": "failed", "gaps": notes})
            continue
        descriptor = store(data, DOCX if fmt == "docx" else "application/pdf")
        result["outputs"].append(descriptor | {"format": fmt, "state": "succeeded", "gaps": notes})
    return result


def layout_value(manifest, chain=None):
    """Navigation-only measurement; never promote it to full visual qualification."""
    if manifest.get("writer_kind") != "generated_rich/3":
        return None
    proof = (chain or {}).get("navigation_proof") or {}
    final = proof.get("final_navigation") or {}
    return {
        "scope": "navigation_only",
        "pagination_mode": manifest["pagination_mode"],
        "state": "pending"
        if chain is None
        else "complete"
        if proof.get("fixed_point")
        else "partial",
        "fixed_point": proof.get("fixed_point", False),
        "page_count": final.get("page_count"),
        "iteration_count": len(proof.get("iterations", [])),
        "entries": [
            {
                "section_id": entry["node_id"],
                "start_page": entry.get("start_page"),
                "end_page": entry.get("end_page"),
                "printed_toc_page": entry.get("printed_toc_page"),
                "gaps": entry["gaps"],
            }
            for entry in final.get("entries", [])
        ],
        "gaps": (chain or {}).get("format_gaps", []),
    }


def layout_view(c, build_id, manifest):
    if manifest.get("writer_kind") != "generated_rich/3":
        return None
    row = c.execute(
        "SELECT payload FROM audit_entries WHERE event_type='build.outputs_published' AND payload->>'build_id'=%s ORDER BY created_at,id LIMIT 1",
        (str(build_id),),
    ).fetchone()
    return layout_value(manifest, row["payload"]["conversion_chain"] if row else None)


def publish_auxiliary(c, computed):
    for item in computed.get("auxiliary_artifacts", []):
        c.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(digest) DO NOTHING",
            (uid(), item["digest"], item["object_key"], item["byte_size"], item["media_type"]),
        )
        row = fetch(c, "SELECT * FROM blobs WHERE digest=%s", (item["digest"],))
        if row["byte_size"] != item["byte_size"] or row["media_type"] != item["media_type"]:
            raise DomainError("BUILD_BLOB_IDENTITY_MISMATCH", "版面轮次实际对象身份冲突", 409)
