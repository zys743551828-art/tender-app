"""A fresh transfer identity may read exact immutable bytes selected by its own command."""

from packages.domain.runtime import DomainError, sha


def verification_object_key(c, message, upload):
    if (
        str(upload["bid_id"]) != str(message["bid_id"])
        or str(upload["id"]) != str(message["payload_ref"])
        or message["input_digest"] != sha({"id": upload["id"], "digest": upload["declared_digest"]})
    ):
        raise DomainError("RETAINED_SOURCE_INVALID", "上传执行身份与固定字节不一致", 409)
    expected = f"staging/{upload['bid_id']}/{upload['id']}/retained"
    if upload["staging_key"] != expected:
        return upload["staging_key"]
    # The API freezes this reference in the same transaction as the new upload and Outbox.
    # Never derive a cloud locator from an arbitrary caller string or from current file heads.
    row = c.execute(
        """SELECT b.object_key FROM operations o
        JOIN audit_entries a ON a.bid_id=o.bid_id AND a.command_id=o.command_id
          AND a.event_type='upload.retained_bytes_reselected'
        JOIN document_versions v ON v.id::text=a.payload->>'source_document_version_id'
          AND v.bid_id=o.bid_id
        JOIN uploads original ON original.id::text=a.payload->>'source_upload_id'
          AND original.bid_id=o.bid_id AND original.verified_version_id=v.id
        JOIN upload_transfers source_transfer ON source_transfer.upload_id=original.id
        JOIN blobs b ON b.id=v.blob_id
        WHERE o.id=%s AND o.bid_id=%s AND o.kind='verify-upload'
          AND a.payload->>'upload_id'=%s AND a.payload->>'verification_operation_id'=%s
          AND a.payload->>'sha256'=%s AND a.payload->>'batch_id'=%s
          AND a.payload->>'byte_size'=%s AND b.digest=%s AND b.byte_size=%s
          AND original.role=%s AND original.state='verified'
          AND source_transfer.aborted_at IS NULL AND original.verified_retain_until>clock_timestamp()""",
        (
            message["operation_id"],
            upload["bid_id"],
            str(upload["id"]),
            str(message["operation_id"]),
            upload["declared_digest"],
            str(upload["batch_id"]),
            str(upload["declared_size"]),
            upload["declared_digest"],
            upload["declared_size"],
            upload["role"],
        ),
    ).fetchall()
    if len(row) != 1:
        raise DomainError(
            "RETAINED_SOURCE_INVALID", "保留原件的固定字节依据不完整，未重新核验或提交", 409
        )
    return row[0]["object_key"]
