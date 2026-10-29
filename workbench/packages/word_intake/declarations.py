"""An uploaded PDF declares correspondence only; it always starts an independent PDF file."""

from packages.domain.runtime import DomainError


def require_new_file(target):
    if target.get("kind") != "new_file":
        raise DomainError(
            "WORD_PDF_NEW_FILE_REQUIRED",
            "此PDF声明对应原Word修改稿，须独立新建文件，不能绑定既有PDF版本链",
            409,
        )


def view(c, bid, upload):
    ready = c.execute(
        "SELECT to_regclass('design.word_pdf_declarations') IS NOT NULL AS ready"
    ).fetchone()["ready"]
    if not ready:
        return None
    row = c.execute(
        """SELECT d.source_document_version_id,source.role AS fixed_role,original.role AS actual_role
        FROM word_pdf_declarations d JOIN uploads original ON original.id=d.upload_id AND original.bid_id=d.bid_id
        LEFT JOIN word_intake_receipts w ON w.document_version_id=d.source_document_version_id AND w.bid_id=d.bid_id
        LEFT JOIN uploads source ON source.id=w.upload_id AND source.bid_id=d.bid_id
        WHERE d.bid_id=%s AND d.upload_id=%s""",
        (bid, upload),
    ).fetchone()
    if row is None:
        return None
    if not row["fixed_role"] or row["actual_role"] != row["fixed_role"]:
        raise DomainError("WORD_PDF_ROLE_MISMATCH", "PDF对应声明须保留原Word的项目与资料角色", 409)
    return {
        "source_document_version_id": row["source_document_version_id"],
        "role": row["fixed_role"],
        "required_target_kind": "new_file",
        "relation_kind": "user_declared_same_draft",
        "verification_status": "unverified",
    }


def assert_target(c, bid, upload, target):
    declaration = view(c, bid, upload)
    if declaration:
        require_new_file(target)
    return declaration


def assert_commit_file(c, upload, file):
    if view(c, upload["bid_id"], upload["id"]) and (
        file["head_version_id"] is not None
        or file["revision"] != 1
        or upload["expected_file_revision"] != 1
    ):
        # Existing successful commands replay before this guard. Uncommitted old bindings must
        # explicitly choose a fresh file; known PDF history cannot silently gain a declared copy.
        raise DomainError(
            "WORD_PDF_NEW_FILE_REQUIRED", "此声明PDF尚未入库，须先重绑定为独立新文件", 409
        )
