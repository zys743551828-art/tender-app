"""Import-to-generation mechanism; synthetic PDFs do not prove Word conversion."""

from uuid import uuid4

import pytest
import test_authoring_docx_import_parser as imports
import test_authoring_repeated_headers as repeated
import test_authoring_rich_table_pdf as pdf_cases

from packages.authoring import content, rich_content, rich_docx, rich_table_pdf, rich_verification
from packages.authoring import docx_import_parser as parser
from packages.authoring import docx_import_service as service
from packages.domain.runtime import DomainError


def table(*, rows=4, headers=(0,), value="1"):
    return (
        '<w:tbl><w:tblPr><w:tblLayout w:type="fixed"/></w:tblPr>'
        "<w:tblGrid>"
        + '<w:gridCol w:w="1800"/>' * 3
        + "</w:tblGrid>"
        + "".join(
            "<w:tr>"
            + (f'<w:trPr><w:tblHeader w:val="{value}"/></w:trPr>' if r in headers else "")
            + "".join("<w:tc>" + imports.paragraph(f"R{r}C{c}:120") + "</w:tc>" for c in range(3))
            + "</w:tr>"
            for r in range(rows)
        )
        + "</w:tbl>"
    )


def parse(body):
    return parser.parse_docx(imports.package(imports.heading("Table") + body))


@pytest.mark.parametrize("value", ["1", "true", "on"])
def test_import_plan_generation_and_pdf_consumer_preserve_explicit_header(value):
    result = parse(table(value=value))
    assert result["can_apply"], result["issues"]
    planned = service.planned_sections(uuid4(), parser.public_result(result))
    block = planned[0]["content"]["content"][0]
    assert block["attrs"]["pagination"] == rich_content.SCHEMA["table_pagination"]
    assert content.schema_digest_for(planned[0]["content"]) == rich_content.SCHEMA_DIGEST
    with pytest.raises(DomainError):
        content.validate_for_schema(planned[0]["content"], rich_content.LEGACY_SCHEMA_DIGEST)
    snapshot, docx, roots = pdf_cases.source([block])
    manifest = rich_verification.manifest(docx, snapshot, [])
    rich_verification.verify(docx, snapshot, [], manifest, rich_docx.sha(rich_docx.identity()))
    good = rich_table_pdf.inspect_tables(
        repeated.render_pages(block), snapshot, roots, pdf_cases.STYLE
    )
    assert good["coverage"] == "complete", good
    bad = rich_table_pdf.inspect_tables(
        repeated.render_pages(block, attack=None), snapshot, roots, pdf_cases.STYLE
    )
    assert bad["coverage"] != "complete"
    again = parser.parse_docx(docx)
    assert (
        next(
            node
            for section in again["sections"]
            for node in section["content"]["content"]
            if node["type"] == "table"
        )["attrs"]["pagination"]
        == block["attrs"]["pagination"]
    )


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_explicit_false_never_creates_pagination(value):
    result = parse(table(value=value))
    assert result["can_apply"]
    assert "pagination" not in result["sections"][0]["content"]["content"][0]["attrs"]


@pytest.mark.parametrize(
    "body",
    [
        table(headers=(0, 1)),
        table(headers=(1,)),
        table(rows=1),
        table(rows=13),
        imports.merged_table(repeat=True),
        table().replace('<w:tblHeader w:val="1"/>', "<w:tblHeader/><w:tblHeader/>"),
        table().replace('<w:tblHeader w:val="1"/>', '<w:tblHeader unknown="1"/>'),
        table().replace('<w:tblHeader w:val="1"/>', "<w:tblHeader><w:x/></w:tblHeader>"),
        table().replace("</w:trPr>", "</w:trPr><w:trPr/>"),
    ],
)
def test_unsupported_repeat_is_blocked_in_existing_import_entry(body):
    result = parse(body)
    assert not result["can_apply"]
    assert "TABLE_HEADER_REPEAT_UNSUPPORTED" in imports.codes(result)
