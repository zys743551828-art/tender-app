"""Actual RICH schemas and independent image routes; target snapshot unchanged."""

from copy import deepcopy

from packages.authoring.rich_schema import BUILD
from packages.authoring.structure_contracts import DIGEST, JSON, arr, ref
from packages.authoring.structure_schema import ID, NID, REV, obj

TEXT = {"type": "string"}
TIME = {"type": "string", "format": "date-time"}


def extend_openapi(actual):
    if not any(
        path == "/api/v1/authoring/rich-capabilities" or "/authoring-images" in path
        for path in actual["paths"]
    ):
        return
    schemas = actual["components"]["schemas"]
    schemas["AuthoringRichBuildRequest"] = deepcopy(BUILD)
    previous_build = deepcopy(schemas["BuildRequest"])
    schemas["BuildRequest"] = {"oneOf": [previous_build, ref("AuthoringRichBuildRequest")]}
    schemas["AuthoringBuildLayout"] = obj(
        {
            "scope": {"const": "navigation_only"},
            "pagination_mode": BUILD["properties"]["pagination_mode"],
            "state": {"enum": ["pending", "partial", "complete"]},
            "fixed_point": {"type": "boolean"},
            "page_count": {"type": ["integer", "null"], "minimum": 1},
            "iteration_count": {"type": "integer", "minimum": 0, "maximum": 3},
            "entries": arr(
                obj(
                    {
                        "section_id": ID,
                        "start_page": {"type": ["integer", "null"], "minimum": 1},
                        "end_page": {"type": ["integer", "null"], "minimum": 1},
                        "printed_toc_page": {"type": ["integer", "null"], "minimum": 1},
                        "gaps": arr(TEXT),
                    }
                )
            ),
            "gaps": arr(TEXT),
        }
    )
    schemas["BuildView"]["properties"]["layout"] = {
        "oneOf": [ref("AuthoringBuildLayout"), {"type": "null"}]
    }
    schemas["AuthoringRichCapabilities"] = obj(
        {
            "schema_digest": DIGEST,
            "schema": JSON,
            "build_schema_digest": DIGEST,
            "image_upload_max_bytes": {"const": 8 * 1024 * 1024},
            "renderer_configured": {"type": "boolean"},
            "runtime_verified_by_this_read": {"const": False},
            "table_pdf_geometry": {"const": "unverified"},
            "pagination_modes": arr(
                obj(
                    {
                        "mode": BUILD["properties"]["pagination_mode"],
                        "page_count_impact": TEXT,
                    }
                )
            ),
        }
    )
    node_id = {"type": "string", "minLength": 1, "maxLength": 128}
    schemas["AuthoringRichImage"] = obj(
        {
            "type": {"const": "image"},
            "attrs": obj(
                {
                    "id": node_id,
                    "asset_id": ID,
                    "asset_revision": REV,
                    "asset_version_id": ID,
                    "width_twips": {"type": "integer", "minimum": 1, "maximum": 20000},
                    "height_twips": {"type": "integer", "minimum": 1, "maximum": 20000},
                    "alt": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "caption": {"type": "string", "maxLength": 1000},
                }
            ),
        }
    )
    cell_blocks = {
        "oneOf": [
            ref(name)
            for name in ["AuthoringParagraph", "AuthoringBulletList", "AuthoringOrderedList"]
        ]
    }
    schemas["AuthoringRichCell"] = obj(
        {
            "type": {"const": "tableCell"},
            "attrs": obj(
                {
                    "id": node_id,
                    "colspan": {"type": "integer", "minimum": 1, "maximum": 100},
                    "rowspan": {"type": "integer", "minimum": 1, "maximum": 200},
                    "header": {"type": "boolean"},
                }
            ),
            "content": {"type": "array", "items": cell_blocks, "minItems": 1},
        }
    )
    schemas["AuthoringRichRow"] = obj(
        {
            "type": {"const": "tableRow"},
            "attrs": obj({"id": node_id}),
            "content": arr(ref("AuthoringRichCell")),
        }
    )
    schemas["AuthoringRichTable"] = obj(
        {
            "type": {"const": "table"},
            "attrs": obj(
                {
                    "id": node_id,
                    "column_widths_twips": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "items": {"type": "integer", "minimum": 1, "maximum": 20000},
                    },
                    "caption": {"type": "string", "maxLength": 1000},
                }
            ),
            "content": {
                "type": "array",
                "minItems": 1,
                "maxItems": 200,
                "items": ref("AuthoringRichRow"),
            },
        }
    )
    table_attrs = schemas["AuthoringRichTable"]["properties"]["attrs"]
    table_attrs["properties"]["pagination"] = obj(
        {
            "protocol": {"const": "authoring-table-pagination/1"},
            "repeat_header_rows": {"type": "integer", "const": 1},
        }
    )
    schemas["AuthoringRichDocument"] = deepcopy(schemas["AuthoringDocument"])
    schemas["AuthoringRichDocument"]["properties"]["content"] = arr(
        {"oneOf": [ref("AuthoringBlock"), ref("AuthoringRichTable"), ref("AuthoringRichImage")]}
    )
    document = {"anyOf": [ref("AuthoringDocument"), ref("AuthoringRichDocument")]}
    schemas["SectionChange"]["properties"]["content"] = document
    schemas["SectionView"]["properties"]["content"] = document
    schemas["AuthoringSnapshot"]["properties"]["sections"] = arr(document)
    schemas["AuthoringSnapshot"]["properties"]["authoring_images"] = JSON
    for name in ["AuthoringPreview"]:
        for field in ["before", "after"]:
            if field in schemas[name]["properties"]:
                schemas[name]["properties"][field] = document
    schemas["AuthoringImageUpload"] = obj(
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
            "media_type": {"enum": ["image/png", "image/jpeg"]},
            "content_base64": {
                "type": "string",
                "minLength": 1,
                "maxLength": 11184812,
                "contentEncoding": "base64",
            },
            "source_refs": arr(ref("AuthoringSourceReference")),
        }
    )
    schemas["AuthoringImageView"] = obj(
        {
            "id": ID,
            "bid_id": ID,
            "asset_id": ID,
            "revision": REV,
            "previous_revision": {"type": ["integer", "null"], "minimum": 1},
            "previous_version_id": NID,
            "state": {"enum": ["active", "withdrawn"]},
            "reason": TEXT,
            "original_blob_id": ID,
            "normalized_blob_id": ID,
            "original_media_type": {"enum": ["image/png", "image/jpeg"]},
            "width_px": {"type": "integer", "minimum": 1, "maximum": 10000},
            "height_px": {"type": "integer", "minimum": 1, "maximum": 10000},
            "normalization_proof": JSON,
            "source_refs": arr(ref("AuthoringSourceReference")),
            "digest": DIGEST,
            "created_by": ID,
            "created_at": TIME,
            "title": TEXT,
            "head_revision": REV,
            "head_version_id": ID,
            "is_current": {"type": "boolean"},
            "etag": TEXT,
        }
    )
    schemas["AuthoringImageCreated"] = deepcopy(schemas["AuthoringImageView"])
    schemas["AuthoringImageCreated"]["properties"]["upload_id"] = DIGEST
    schemas["AuthoringImageCreated"]["required"].append("upload_id")
    schemas["AuthoringImagePage"] = obj(
        {"items": arr(ref("AuthoringImageView")), "next_cursor": NID}
    )
    schemas["AuthoringImageWithdraw"] = obj(
        {"reason": {"type": "string", "minLength": 1, "maxLength": 1000}}
    )
    schemas["AuthoringImageUploadStatus"] = obj(
        {
            "upload_id": DIGEST,
            "state": {"enum": ["prepared", "unconfirmed", "rejected", "completed"]},
            "asset_id": NID,
            "asset_version_id": NID,
            "error_code": {"type": ["string", "null"]},
            "automatic_retry": {"const": False},
            "retry_requires_same_input": {"const": True},
            "updated_at": TIME,
        }
    )
    root = "/api/v1/bids/{bid_id}"
    entries = [
        (
            "get",
            "/api/v1/authoring/rich-capabilities",
            "getAuthoringRichCapabilities",
            None,
            "AuthoringRichCapabilities",
            "200",
        ),
        (
            "post",
            root + "/authoring-images",
            "uploadAuthoringImage",
            "AuthoringImageUpload",
            "AuthoringImageCreated",
            "201",
        ),
        (
            "get",
            root + "/authoring-images",
            "listAuthoringImages",
            None,
            "AuthoringImagePage",
            "200",
        ),
        (
            "get",
            root + "/authoring-image-uploads/{upload_id}",
            "getAuthoringImageUploadStatus",
            None,
            "AuthoringImageUploadStatus",
            "200",
        ),
        (
            "get",
            root + "/authoring-images/{asset_id}",
            "getAuthoringImage",
            None,
            "AuthoringImageView",
            "200",
        ),
        (
            "get",
            root + "/authoring-images/{asset_id}/versions/{version_id}",
            "getAuthoringImageVersion",
            None,
            "AuthoringImageView",
            "200",
        ),
        (
            "post",
            root + "/authoring-images/{asset_id}/withdraw",
            "withdrawAuthoringImage",
            "AuthoringImageWithdraw",
            "AuthoringImageView",
            "200",
        ),
    ]
    for method, path, operation, request, output, status in entries:
        if method not in actual["paths"].get(path, {}):
            continue
        parameters = [
            {
                "name": key,
                "in": "path",
                "required": True,
                "schema": DIGEST if key == "upload_id" else ID,
            }
            for key in ["bid_id", "asset_id", "version_id", "upload_id"]
            if "{" + key + "}" in path
        ]
        if request:
            parameters += [
                {"name": "Idempotency-Key", "in": "header", "required": True, "schema": TEXT},
                {"name": "X-CSRF-Token", "in": "header", "required": True, "schema": TEXT},
            ]
        if operation == "withdrawAuthoringImage":
            parameters.append(
                {"name": "If-Match", "in": "header", "required": True, "schema": TEXT}
            )
        if operation == "listAuthoringImages":
            parameters += [
                {"name": "cursor", "in": "query", "schema": ID},
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                },
            ]
        spec = {
            "operationId": operation,
            "tags": ["authoring-rich"],
            "security": [{"SessionCookie": []}],
            "parameters": parameters,
            "responses": {
                status: {
                    "description": "实际响应",
                    "content": {"application/json": {"schema": ref(output)}},
                }
            },
        }
        if request:
            spec["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": ref(request)}},
            }
        actual["paths"].setdefault(path, {})[method] = spec
    path = root + "/authoring-images/{asset_id}/versions/{version_id}/bytes/{variant}"
    if "get" not in actual["paths"].get(path, {}):
        return
    actual["paths"][path] = {
        "get": {
            "operationId": "downloadAuthoringImageVersion",
            "tags": ["authoring-rich"],
            "security": [{"SessionCookie": []}],
            "parameters": [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"enum": ["original", "normalized"]} if name == "variant" else ID,
                }
                for name in ["bid_id", "asset_id", "version_id", "variant"]
            ],
            "responses": {
                "200": {
                    "description": "鉴权还原精确原图或规范PNG，不授当前新用资格",
                    "content": {
                        mime: {"schema": {"type": "string", "format": "binary"}}
                        for mime in ["image/png", "image/jpeg"]
                    },
                }
            },
        }
    }
