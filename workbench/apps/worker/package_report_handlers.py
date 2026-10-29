"""Render and publish a frozen report copy through the ordinary export lane."""

import os

from psycopg.types.json import Jsonb

from packages.authoring.build import render_pdf
from packages.contracts.package_review_runs_api import BASE
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_reports as policy
from packages.domain import storage
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import DomainError, audit, clean, connection, fetch, sha, uid


def _record(c, message):
    row = clean(
        fetch(
            c,
            "SELECT * FROM design.bid_package_report_exports WHERE bid_id=%s AND id=%s",
            (message["bid_id"], message["payload_ref"]),
        )
    )
    if (
        row["operation_id"] != message["operation_id"]
        or row["input_digest"] != message["input_digest"]
        or digest(row["input_manifest"]) != row["input_digest"]
    ):
        raise DomainError("PACKAGE_REPORT_TASK_CHANGED", "报告任务与冻结申请不一致", 409)
    context = row["input_manifest"]["context"]
    scope = tuple(
        context["scope"][key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    )
    run = runs.load(
        c, scope, context["frozen_input_id"], context["execution_input_id"], context["run_id"]
    )
    policy.check(row["input_manifest"], run)
    if any(context["method"][key] != value for key, value in policy.source_profile().items()):
        raise DomainError(
            "PACKAGE_REPORT_METHOD_CHANGED", "报告生成方法已变化，请按当前方法重新生成", 409
        )
    return row, run


def compute(message, lease=None):
    if message["handler_version"] != policy.HANDLER or message["step_key"] != policy.STEP:
        raise DomainError("PACKAGE_REPORT_STAGE_INVALID", "整包报告任务阶段无效", 409)
    with connection(True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        record, run = _record(c, message)
    snapshot = record["input_manifest"]
    data = policy.document(
        snapshot, run, export_id=record["id"], captured_at=utc(record["created_at"])
    )
    gaps, chain = [], {}
    if snapshot["format"] == "pdf":
        rendered = render_pdf(
            data,
            executable=os.environ.get("AUTHORING_RENDERER", "soffice"),
            font_path=os.environ.get(
                "AUTHORING_FONT_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            ),
            expected_identity=snapshot["context"]["method"]["pdf_renderer"],
            sandbox_attested=False,
        )
        if rendered.pdf is None:
            raise DomainError(
                "PACKAGE_REPORT_PDF_FAILED",
                "PDF报告转换未完成，可先生成Word报告",
                503,
                {"gaps": list(rendered.gaps)},
            )
        data, gaps, chain = rendered.pdf, list(rendered.gaps), rendered.chain
    blob_digest = sha(data)
    key = "blobs/" + blob_digest
    media = policy.MEDIA[snapshot["format"]]
    storage.put(key, data, media)
    persisted = storage.get(key)
    if len(persisted) != len(data) or sha(persisted) != blob_digest:
        raise DomainError("PACKAGE_REPORT_OBJECT_CORRUPT", "报告对象保存后的字节核验失败", 503)
    return {
        "export_id": record["id"],
        "report_input_digest": record["input_digest"],
        "context_digest": snapshot["context_digest"],
        "blob_digest": blob_digest,
        "byte_size": len(data),
        "object_key": key,
        "media_type": media,
        "gaps": gaps,
        "conversion_chain": chain,
    }


def publish(c, message, outcome):
    record, run = _record(c, message)
    snapshot = record["input_manifest"]
    if (
        outcome["export_id"] != record["id"]
        or outcome["report_input_digest"] != record["input_digest"]
        or outcome["context_digest"] != snapshot["context_digest"]
        or outcome["object_key"] != "blobs/" + outcome["blob_digest"]
        or outcome["media_type"] != policy.MEDIA[snapshot["format"]]
        or type(outcome["byte_size"]) is not int
        or outcome["byte_size"] <= 0
    ):
        raise DomainError("PACKAGE_REPORT_RESULT_CHANGED", "报告文件与冻结生成任务不一致", 409)
    c.execute(
        "INSERT INTO design.blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(digest) DO NOTHING",
        (
            uid(),
            outcome["blob_digest"],
            outcome["object_key"],
            outcome["byte_size"],
            outcome["media_type"],
        ),
    )
    blob = fetch(c, "SELECT * FROM design.blobs WHERE digest=%s", (outcome["blob_digest"],))
    if blob["byte_size"] != outcome["byte_size"] or blob["media_type"] != outcome["media_type"]:
        raise DomainError(
            "PACKAGE_REPORT_BLOB_CONFLICT", "已有对象的文件元数据不一致，未发布报告", 409
        )
    version, logical = uid(), uid()
    filename = f"整包核查报告-{run['id'][:8]}-{record['id'][:8]}.{snapshot['format']}"
    c.execute(
        "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,%s,clock_timestamp(),'review_report',%s)",
        (version, message["bid_id"], blob["id"], filename, record["actor_id"]),
    )
    c.execute(
        "INSERT INTO design.document_files(id,bid_id,role,revision) VALUES(%s,%s,'other',1)",
        (logical, message["bid_id"]),
    )
    c.execute(
        "INSERT INTO design.document_file_versions(bid_id,file_id,version_id,revision,previous_version_id) VALUES(%s,%s,%s,1,NULL)",
        (message["bid_id"], logical, version),
    )
    c.execute(
        "UPDATE design.document_files SET head_version_id=%s,revision=2 WHERE id=%s",
        (version, logical),
    )
    c.execute(
        "INSERT INTO design.bid_package_report_artifacts(export_id,bid_id,operation_id,document_version_id,blob_digest,gaps,conversion_chain) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (
            record["id"],
            message["bid_id"],
            message["operation_id"],
            version,
            outcome["blob_digest"],
            Jsonb(outcome["gaps"]),
            Jsonb(outcome["conversion_chain"]),
        ),
    )
    result_ref = (
        BASE.format(
            **run["scope"],
            input_id=run["frozen_input_id"],
            execution_input_id=run["execution_input_id"],
        )
        + f"/{run['id']}/report-exports/{record['id']}"
    )
    output = {
        "result_ref": result_ref,
        "export_id": record["id"],
        "document_version_id": str(version),
        "blob_digest": outcome["blob_digest"],
        "report_input_digest": record["input_digest"],
        "artifact_kind": "review_report",
        "gaps": outcome["gaps"],
    }
    audit(
        c,
        record["actor_id"],
        message["bid_id"],
        "package.scope_report.published",
        {key: value for key, value in output.items() if key != "result_ref"},
    )
    return output
