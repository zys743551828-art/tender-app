"""导出实际实现路由与其协议形状，目标快照仅提供被引用定义。"""

import argparse
import gzip
import io
import json
import sys
from copy import deepcopy
from pathlib import Path

from fastapi.openapi.utils import get_openapi

from apps.api.comparison_contracts import extend_openapi as extend_comparisons
from apps.api.human_contracts import extend_openapi as extend_human
from apps.api.report_contracts import extend_openapi as extend_reports
from apps.api.review_contracts import extend_openapi as extend_reviews
from apps.api.source_effectivity_contracts import extend_openapi as extend_effectivity
from apps.api.submission_contracts import extend_openapi as extend_submissions
from apps.api.upload_contracts import extend_openapi as extend_uploads
from packages.assistant.contracts import extend_openapi as extend_assistant
from packages.authoring.contracts import extend_openapi as extend_authoring
from packages.authoring.package_adoption_contracts import (
    extend_openapi as extend_authoring_packages,
)
from packages.contracts.authoring_history_api import extend_openapi as extend_authoring_history
from packages.contracts.bid_package_api import extend_openapi as extend_bid_packages
from packages.contracts.bid_package_requirements_api import (
    BASE as REQUIREMENTS_BASE,
)
from packages.contracts.bid_package_requirements_api import (
    extend_openapi as extend_bid_package_requirements,
)
from packages.contracts.document_parses_api import extend_openapi as extend_document_parses
from packages.contracts.package_historical_research_api import (
    extend_openapi as extend_package_historical_research,
)
from packages.contracts.package_history_directory_api import (
    extend_openapi as extend_package_history_directory,
)
from packages.contracts.package_retrospectives_api import (
    extend_openapi as extend_package_retrospectives,
)
from packages.contracts.package_review_comparisons_api import (
    extend_openapi as extend_package_review_comparisons,
)
from packages.contracts.package_review_decisions_api import (
    extend_openapi as extend_package_review_decisions,
)
from packages.contracts.package_review_reports_api import (
    extend_openapi as extend_package_review_reports,
)
from packages.contracts.package_review_runs_api import extend_openapi as extend_package_review_runs
from packages.contracts.package_technical_eligibility_api import (
    extend_openapi as extend_package_technical_eligibility,
)
from packages.contracts.package_technical_execution_api import (
    extend_openapi as extend_package_technical_execution,
)
from packages.contracts.package_technical_scope_api import (
    extend_openapi as extend_package_technical_scopes,
)
from packages.contracts.work_context_api import extend_openapi as extend_work_contexts
from packages.contracts.work_context_catalog_api import (
    extend_openapi as extend_work_context_catalog,
)
from packages.domain.runtime import ROOT
from packages.identity.contracts import extend_openapi as extend_identity
from packages.knowledge.contracts import extend_openapi as extend_knowledge
from packages.knowledge.rag_contracts import extend_openapi as extend_knowledge_rag
from packages.metrics.contracts import extend_openapi as extend_metrics
from packages.pricing.contracts import extend_openapi as extend_pricing
from packages.research.contracts import extend_openapi as extend_research


def implemented_openapi(app):
    target = json.loads((ROOT / "packages/contracts/openapi/openapi.json").read_text())
    actual = get_openapi(title=app.title, version="0.1.0", routes=app.routes)
    # 以实际注册路径为分母，不能把目标计划接口标作已实现。
    generated_schemas = actual.get("components", {}).get("schemas", {})
    actual["components"] = deepcopy(target["components"])
    for name, schema in generated_schemas.items():
        actual["components"]["schemas"].setdefault(name, schema)
    schemas = actual["components"]["schemas"]
    schemas["DocumentEvidenceView"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["document_version_id", "parse_run_id", "coverage", "gaps", "items"],
        "properties": {
            "document_version_id": {"type": "string", "format": "uuid"},
            "parse_run_id": {"type": ["string", "null"], "format": "uuid"},
            "coverage": {"enum": ["pending", "complete", "partial", "failed"]},
            "gaps": {"type": "array", "items": {"type": "string"}},
            "items": {"type": "array", "items": {"$ref": "#/components/schemas/EvidenceView"}},
        },
    }
    for path, methods in actual["paths"].items():
        short = path.removeprefix("/api/v1")
        for method, operation in methods.items():
            planned = target["paths"].get(short, {}).get(method)
            if planned:
                actual_parameters = operation.get("parameters", [])
                methods[method] = deepcopy(planned)
                # 实际查询参数是本切片支持的参数；目标尚未实现的筛选不提前承诺。
                if method == "get":
                    methods[method]["parameters"] = actual_parameters + [
                        parameter
                        for parameter in planned.get("parameters", [])
                        if parameter.get("in") == "header" or "Header" in parameter.get("$ref", "")
                    ]
            elif path in [
                "/api/v1/auth/session",
                "/api/v1/documents/{document_version_id}/evidence",
                "/api/v1/documents/{document_version_id}",
            ]:
                name = (
                    "AuthView"
                    if path.endswith("/session")
                    else ("DocumentEvidenceView" if path.endswith("/evidence") else "DocumentView")
                )
                operation["operationId"] = (
                    "getSession"
                    if name == "AuthView"
                    else (
                        "getDocumentEvidence" if name == "DocumentEvidenceView" else "getDocument"
                    )
                )
                operation["security"] = [{"SessionCookie": []}]
                operation["responses"] = {
                    "200": {
                        "description": "实际实现的只读资源",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/" + name}}
                        },
                    },
                    "default": {"$ref": "#/components/responses/DomainError"},
                }
    events = actual["paths"].get("/api/v1/streams/{stream_id}/events", {}).get("get")
    if events:
        events["responses"]["410"] = {
            "description": "游标已超出7天保留窗口，请重新读取服务器快照",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        }
    transfer = actual["paths"].get("/api/v1/object-transfers/uploads/{upload_id}", {}).get("put")
    if transfer:
        transfer["parameters"] += [
            {"in": "header", "name": name, "required": True, "schema": definition}
            for name, definition in [
                ("Origin", {"type": "string", "format": "uri"}),
                ("X-CSRF-Token", {"type": "string"}),
                ("Content-Length", {"type": "integer", "minimum": 1}),
            ]
        ]
    extend_reviews(actual)
    extend_assistant(actual)
    extend_comparisons(actual)
    extend_authoring(actual)
    extend_authoring_history(actual)
    extend_research(actual)
    extend_human(actual)
    extend_uploads(actual)
    extend_effectivity(actual)
    extend_knowledge(actual)
    extend_knowledge_rag(actual)
    extend_identity(actual)
    package_base = "/api/v1/bids/{bid_id}/packages"
    package_paths = {
        package_base + suffix
        for suffix in (
            "",
            "/{package_id}",
            "/{package_id}/revisions",
            "/{package_id}/revisions/{revision_id}",
            "/{package_id}/revisions/{revision_id}/manifest",
            "/{package_id}/revisions/{revision_id}/evidence",
        )
    } | {
        "/api/v1/bids/{bid_id}/package-documents",
        "/api/v1/bids/{bid_id}/package-documents/{document_version_id}/parses",
    }
    if package_paths.intersection(actual["paths"]):
        # Partial apps need no package contracts; registered package routes still
        # undergo the extender's complete operation/schema checks.
        extend_bid_packages(actual)
    if any(
        path == REQUIREMENTS_BASE or path.startswith(REQUIREMENTS_BASE + "/")
        for path in actual["paths"]
    ):
        extend_bid_package_requirements(actual)
    extend_package_review_runs(actual)
    extend_package_review_decisions(actual)
    extend_package_review_comparisons(actual)
    extend_package_review_reports(actual)
    extend_package_technical_scopes(actual)
    extend_package_technical_eligibility(actual)
    extend_package_technical_execution(actual)
    extend_authoring_packages(actual)
    extend_document_parses(actual)
    extend_pricing(actual)
    extend_submissions(actual)
    extend_reports(actual)
    extend_metrics(actual)
    extend_package_retrospectives(actual)
    extend_work_contexts(actual)
    extend_work_context_catalog(actual)
    extend_package_historical_research(actual)
    extend_package_history_directory(actual)
    from packages.word_intake.contracts import extend_openapi as extend_word

    extend_word(actual)
    from apps.api.word_material_routes import extend_openapi as extend_word_materials

    extend_word_materials(actual)
    from apps.api.composition import extend_openapi as extend_composition

    extend_composition(actual)
    return actual


def snapshot_bytes(actual, *, compressed=False):
    """Keep the complete JSON; gzip adds neither a filename nor a build time."""
    data = (json.dumps(actual, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if not compressed:
        return data
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as archive:
        archive.write(data)
    return buffer.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Write complete JSON, or deterministic gzip for a .gz path"
    )
    args = parser.parse_args(argv)
    from apps.api.main import app

    data = snapshot_bytes(
        implemented_openapi(app), compressed=bool(args.output and args.output.suffix == ".gz")
    )
    if args.output:
        args.output.write_bytes(data)
    else:
        # Preserve the original plain-JSON stdout interface and trailing newline.
        sys.stdout.write(data.decode("utf-8"))


if __name__ == "__main__":
    main()
