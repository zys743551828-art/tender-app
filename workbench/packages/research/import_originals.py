"""Exact import bytes outside transactions, followed by per-record metadata checks.

This proves readable originals at confirmation, not platform acceptance, effective
sources, historical identity or formal research qualification.
"""

from dataclasses import dataclass

from pydantic import ValidationError

from packages.domain import original_verification
from packages.domain.runtime import DomainError, clean, now, sha
from packages.research.import_contracts import HistoricalImportRequest

MAX_VERIFICATION_BYTES = 1024 * 1024 * 1024
VERSION = "historical-import-originals/1"


def documents(c, record):
    ids = sorted(
        {
            record["actual_document_version_id"],
            record["evidence_ref"],
            *([record["source_version_id"]] if record["source_version_id"] else []),
        }
    )
    rows = c.execute(
        "SELECT d.id AS document_version_id,d.bid_id,d.blob_id,d.artifact_kind,"
        "b.digest,b.byte_size,b.media_type,b.object_key FROM design.document_versions d "
        "JOIN design.blobs b ON b.id=d.blob_id WHERE d.bid_id=%s AND d.id=ANY(%s::uuid[]) "
        "ORDER BY d.id",
        (record["bid_id"], ids),
    ).fetchall()
    values = clean(rows)
    if [row["document_version_id"] for row in values] != ids:
        raise DomainError("IMPORT_ORIGINAL_MISSING", "该记录的实际文件或提交依据缺失", 409)
    return values


def observe(c, batch_id, manifest):
    """Only pending rows need byte checks; committed ACKs bypass this path."""
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "records"}
        or manifest["schema"] != "historical-import/1"
    ):
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次清单用途或形状不符合导入协议", 409)
    try:
        HistoricalImportRequest.model_validate({"records": manifest["records"]})
    except ValidationError:
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次记录不符合导入协议", 409) from None
    rows = c.execute(
        "SELECT external_record_id,source_digest FROM design.import_records "
        "WHERE batch_id=%s AND state='pending' ORDER BY external_record_id",
        (batch_id,),
    ).fetchall()
    incoming = {row["external_record_id"]: row for row in manifest["records"]}
    if len(incoming) != len(manifest["records"]):
        raise DomainError("IMPORT_MANIFEST_INVALID", "原批次记录编号重复", 409)
    observed = {}
    for row in rows:
        record = incoming.get(row["external_record_id"])
        if record is None:
            raise DomainError("IMPORT_MANIFEST_INVALID", "原清单与预检查记录不一致", 409)
        try:
            exact, error = documents(c, record), None
        except DomainError as failure:
            if failure.code != "IMPORT_ORIGINAL_MISSING":
                raise
            exact, error = [], failure.code
        observed[row["external_record_id"]] = {
            "record_digest": sha(record),
            "source_digest": row["source_digest"],
            "documents": exact,
            "error": error,
        }
    unique = {
        document["blob_id"]: document
        for observation in observed.values()
        for document in observation["documents"]
    }
    if sum(document["byte_size"] for document in unique.values()) > MAX_VERIFICATION_BYTES:
        raise DomainError(
            "IMPORT_ORIGINAL_BUDGET_EXCEEDED",
            "本批待核原件超过 1 GiB，请拆分待导入记录后重新预检查",
            422,
        )
    return {"batch_id": str(batch_id), "manifest_digest": sha(manifest), "records": observed}


@dataclass(frozen=True)
class VerifiedOriginals:
    observation: dict
    errors: dict[str, str]
    verified_at: str


def verify(observation):
    """Caller has closed the observation connection. Read each exact blob once."""
    blobs: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for identity, record in observation["records"].items():
        if record["error"]:
            errors[identity] = record["error"]
            continue
        for document in record["documents"]:
            blob = document["blob_id"]
            if blob not in blobs:
                try:
                    original_verification.verify(document)
                    blobs[blob] = None
                except DomainError as error:
                    if error.code not in {"ORIGINAL_NOT_AVAILABLE", "ORIGINAL_BYTES_CORRUPTED"}:
                        raise
                    blobs[blob] = {
                        "ORIGINAL_NOT_AVAILABLE": "IMPORT_ORIGINAL_MISSING",
                        "ORIGINAL_BYTES_CORRUPTED": "IMPORT_ORIGINAL_CORRUPTED",
                    }[error.code]
            failure = blobs[blob]
            if failure:
                errors[identity] = failure
    return VerifiedOriginals(observation, errors, now().isoformat())


def assert_batch(value, batch_id, manifest):
    if (
        not isinstance(value, VerifiedOriginals)
        or value.observation["batch_id"] != str(batch_id)
        or value.observation["manifest_digest"] != sha(manifest)
    ):
        raise DomainError("IMPORT_ORIGINAL_CHECK_REQUIRED", "确认需要本批原件的实际字节核验", 409)


def receipt(c, value, record, stored):
    """Under existing import/bid locks, compare metadata before fact insertion."""
    identity = record["external_record_id"]
    before = value.observation["records"].get(identity)
    if (
        before is None
        or before["record_digest"] != sha(record)
        or before["source_digest"] != stored["source_digest"]
    ):
        raise DomainError("IMPORT_ORIGINAL_CHANGED", "本条原件依据已变化，请重新预检查", 409)
    if identity in value.errors:
        raise DomainError(value.errors[identity], "本条实际原件缺失或字节校验失败", 409)
    if documents(c, record) != before["documents"]:
        raise DomainError("IMPORT_ORIGINAL_CHANGED", "原件定位或字节身份已变化，请重新预检查", 409)
    return {
        "version": VERSION,
        "verified_at": value.verified_at,
        "documents": [
            {key: item[key] for key in item if key != "object_key"} for item in before["documents"]
        ],
        "platform_submission_verified": False,
    }
