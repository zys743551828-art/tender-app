"""Page/crop metadata only; no formal authority or image-readability grant."""

from copy import deepcopy


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
ID = {"type": "string", "format": "uuid", "pattern": "^[0-9a-f-]{36}$"}
POINT = {"type": "string", "maxLength": 40, "pattern": r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$"}
BOX = {"type": "array", "items": POINT, "minItems": 4, "maxItems": 4}
PIXEL = {"type": "integer", "minimum": 0, "maximum": 8192}
RECTANGLE = {"type": "array", "items": PIXEL, "minItems": 4, "maxItems": 4}
TIME = {"type": "string", "format": "date-time", "maxLength": 40}
ASSET = obj(
    {
        "id": SHA,
        "sha256": SHA,
        "byte_size": {"type": "integer", "minimum": 1, "maximum": 32 * 1024 * 1024},
        "width": {"type": "integer", "minimum": 1, "maximum": 8192},
        "height": {"type": "integer", "minimum": 1, "maximum": 8192},
        "media_type": {"const": "image/png"},
    }
)
REGIONS = {
    "type": "array",
    "minItems": 1,
    "maxItems": 128,
    "items": obj(
        {
            "physical_page": {"type": "integer", "minimum": 1, "maximum": 128},
            "parent_image_digest": SHA,
            "rectangle": RECTANGLE,
        }
    ),
}
SCHEMA = obj(
    {
        "version": {"const": "package-technical-page-assets/2"},
        "document_version_id": ID,
        "source_digest": SHA,
        "source_byte_size": {"type": "integer", "minimum": 1, "maximum": 32 * 1024 * 1024},
        "render_method_digest": SHA,
        "crop_method_digest": {"anyOf": [SHA, {"type": "null"}]},
        "parent_manifest_digest": {"anyOf": [SHA, {"type": "null"}]},
        "rendered_at": TIME,
        "cropped_at": {"anyOf": [TIME, {"type": "null"}]},
        "pixel_format": {"const": "rgb8-filter0/1"},
        "render_scope": {"const": "all_pdfium_page_viewports"},
        "page_count": {"type": "integer", "minimum": 1, "maximum": 128},
        "pages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 128,
            "items": obj(
                {
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 128},
                    "rotation": {"type": "integer", "enum": [0, 90, 180, 270]},
                    "canvas_width": POINT,
                    "canvas_height": POINT,
                    "media_box": BOX,
                    "crop_box": {"anyOf": [BOX, {"type": "null"}]},
                    "asset": ASSET,
                }
            ),
        },
        "details": {
            "type": "array",
            "maxItems": 128,
            "items": obj(
                {
                    "physical_page": {"type": "integer", "minimum": 1, "maximum": 128},
                    "parent_asset_id": SHA,
                    "parent_image_digest": SHA,
                    "rectangle": RECTANGLE,
                    "asset": ASSET,
                }
            ),
        },
        "full_pages_retained": {"type": "boolean", "const": True},
        **{
            key: {"type": "boolean", "const": False}
            for key in (
                "input_authority_granted",
                "visual_readability_verified",
                "historical_byte_existence_verified",
                "isolated_execution_verified",
                "font_reproducibility_verified",
            )
        },
        "limitations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
            "uniqueItems": True,
        },
        "digest": SHA,
    }
)


def schema():
    return deepcopy(SCHEMA)


def regions_schema():
    return deepcopy(REGIONS)
