"""Explicitly synthetic evidence from a test key; never represents real authority."""

import base64
import io
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image

from packages.model_governance.package_history_proofs import canonical, digest, sha


def evidence(context, adapter_id, key, originals, *, template_keys=(), near_duplicate_keys=()):
    values = []

    def add(kind, value, *, identity=None):
        identity = identity or str(uuid4())
        raw = value if isinstance(value, bytes) else canonical(value)
        values.append(
            {
                "id": identity,
                "kind": kind,
                "source_locator": "fixture://source/" + identity,
                "sha256": sha(raw),
                "byte_size": len(raw),
                "data_base64": base64.b64encode(raw).decode(),
            }
        )
        return identity

    documents = []
    boundary = context["submission"]["submitted_at"]
    issued = datetime.now(timezone.utc).isoformat()
    for original in context["originals"]:
        at = original["obtained_at"]
        row = {k: original[k] for k in ("document_version_id", "digest", "byte_size")}
        row["original_resource"] = add("original_bytes", originals[original["digest"]])
        for event in ("exists", "acquired", "published", "effective"):
            if event in {"published", "effective"} and not original["requires_effective_proof"]:
                row[event] = None
                continue
            row[event] = add(
                "byte_event",
                {
                    "schema": "historical-original-byte-event/1",
                    "event": event,
                    "original_sha256": original["digest"],
                    "byte_size": original["byte_size"],
                    "at": at,
                    "valid_until": None,
                    "party_id": context["identity"]["bidder_id"] if event == "acquired" else None,
                    "recorded_at": at,
                },
            )
        documents.append(row)
    submission = add(
        "actual_submission",
        {
            "schema": "actual-package-submission-receipt/1",
            "at": boundary,
            "recorded_at": boundary,
            "identity_digest": context["identity"]["digest"],
            "package_digest": context["basis"]["package_digest"],
            "files": context["target_files"],
            "platform_reference": "synthetic-platform-receipt-not-real",
        },
    )
    stream = io.BytesIO()
    Image.new("RGB", (120, 120), "white").save(stream, format="PNG")
    pages = []
    for doc in context["documents"]:
        for page in doc["pages"]:
            blocks = [b for b in doc["blocks"] if b["physical_page"] == page["physical_page"]]
            pages.append(
                {
                    "document_version_id": doc["document_version_id"],
                    "original_sha256": doc["file_digest"],
                    "parse_id": doc["parse"]["parse_run_id"],
                    "physical_page": page["physical_page"],
                    "blocks_digest": digest(blocks),
                    "image_resource": add("page_render_png", stream.getvalue()),
                }
            )
    coverage = add(
        "coverage",
        {
            "schema": "full-package-coverage-review/1",
            "reviewed_at": issued,
            "reviewer_reference": "synthetic-evidence-port-not-a-real-inspection",
            "scope_digest": context["scope"]["digest"],
            "inventory_digest": context["basis"]["inventory_digest"],
            "parts": context["technical_part_ids"],
            "rules": context["rule_scopes"],
            "pages": pages,
        },
    )
    block = next(
        b
        for d in context["documents"]
        if d["package_role"] == "authority"
        for b in d["blocks"]
        if b["text_content"].startswith("技术总分满分为")
    )
    scale = add(
        "scale",
        {
            "schema": "package-technical-scale-evidence/1",
            "reviewed_at": issued,
            "reviewer_reference": "synthetic-scale-source-port",
            "evidence_id": block["id"],
            "quote": block["text_content"],
            "maximum": "20",
            "scale_description": "未加权原始分",
            "aggregation": "published_final_technical_total",
        },
    )
    grouping = add(
        "grouping",
        {
            "schema": "package-related-content-review/1",
            "reviewed_at": issued,
            "reviewer_reference": "synthetic-group-review-port",
            "scope_digest": context["scope"]["digest"],
            "method": "evidence-backed-template-and-near-duplicate-review/1",
            "source_references": ["fixture://complete-original-review/" + context["scope"]["id"]],
            "template_keys": list(template_keys),
            "near_duplicate_keys": list(near_duplicate_keys),
        },
    )
    label_original = add("original_bytes", originals[context["label"]["file_digest"]])
    payload = {
        "schema": "package-history-proof/1",
        "receipt_id": str(uuid4()),
        "issued_at": issued,
        "context_digest": digest(context),
        "documents": documents,
        "submission_resource": submission,
        "coverage_resource": coverage,
        "scale_resource": scale,
        "grouping_resource": grouping,
        "label_original_resource": label_original,
        "resources_manifest": sorted(
            ({k: v for k, v in row.items() if k != "data_base64"} for row in values),
            key=lambda r: r["id"],
        ),
    }
    return {
        "schema": "package-history-signed-evidence/1",
        "key_id": str(adapter_id),
        "payload": payload,
        "signature_base64": base64.b64encode(key.sign(canonical(payload))).decode(),
        "resources": values,
    }


def revise(envelope, key, identity, transform):
    row = next(r for r in envelope["resources"] if r["id"] == identity)
    import json

    value = json.loads(base64.b64decode(row["data_base64"]))
    transform(value)
    raw = canonical(value)
    row.update(sha256=sha(raw), byte_size=len(raw), data_base64=base64.b64encode(raw).decode())
    envelope["payload"]["resources_manifest"] = sorted(
        ({k: v for k, v in row.items() if k != "data_base64"} for row in envelope["resources"]),
        key=lambda r: r["id"],
    )
    envelope["signature_base64"] = base64.b64encode(
        key.sign(canonical(envelope["payload"]))
    ).decode()
    return envelope
