"""Synthetic packages validating candidate-level blocking and review gaps."""

from copy import deepcopy
from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image, PngImagePlugin

from packages.authoring.build import assemble_docx
from packages.authoring.content import empty_content
from packages.authoring.technical_candidate_checks import (
    MARGIN_MISMATCH,
    MARGIN_NO_BASIS,
    MARGIN_UNINSPECTABLE,
    FrozenPageMargins,
    frozen_page_margins,
    inspect_candidate_docx,
)
from packages.domain.runtime import DomainError, sha
from packages.word_intake.inspection import CONTENT_NS, DOCX, REL_NS

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NAME = "示例施工单位"


def fixture(*, body="", footer="", properties="", extra_rels="", binary=None, archive_comment=""):
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CONTENT_NS}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            f'<Override PartName="/word/document.xml" ContentType="{DOCX}.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{REL_NS}">'
            f'<Relationship Id="main" Type="{R}/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
        "word/_rels/document.xml.rels": (
            f'<Relationships xmlns="{REL_NS}">{extra_rels}</Relationships>'
        ),
    }
    if properties:
        parts["docProps/core.xml"] = f"<coreProperties>{properties}</coreProperties>"
    if footer:
        parts["word/footer.xml"] = f'<w:ftr xmlns:w="{W}">{footer}</w:ftr>'
    if binary:
        name, data = binary
        parts[name] = data
    target = BytesIO()
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.comment = archive_comment.encode()
        for name, item in parts.items():
            archive.writestr(name, item)
    return target.getvalue()


def png(text=None):
    data = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    if text:
        metadata.add_text("description", text)
    with Image.new("RGB", (2, 2)) as image:
        image.save(data, format="PNG", pnginfo=metadata)
    return data.getvalue()


def check(data, *, name="技术标.docx", prohibited=(NAME,), margins=None):
    return inspect_candidate_docx(
        data, filename=name, prohibited_names=prohibited, page_margins=margins
    )


def margin_snapshot(*field_values):
    rule, decision, evidence, source, document = (str(UUID(int=i)) for i in range(1, 6))
    ref = {
        "source_id": source,
        "source_revision": 1,
        "evidence_id": evidence,
        "document_version_id": document,
    }
    basis = {
        "rule_id": rule,
        "rule_semantic_digest": "a" * 64,
        "decision_id": decision,
        "decision_revision": 1,
        "evidence_basis": {"references": [ref], "source_closure_digest": "b" * 64},
    }
    declared = [
        {"rule_id": rule, "field": field, "value": value, "source_refs": [ref], "reason": "合成值"}
        for field, value in field_values
    ]
    frozen = [
        deepcopy(row)
        | {
            "basis": deepcopy(basis),
            "interpretation": "human_bound_field_semantics_not_automatically_verified",
        }
        for row in declared
    ]
    return {
        "authoring_structure": {
            "metadata": {
                "format_bindings": declared,
                "format_binding_manifest": frozen,
                "format_review_ack": "c" * 64,
                "effective_style": dict(field_values),
            }
        }
    }


def section(top="1440", right="720"):
    return f'<w:sectPr><w:pgMar w:top="{top}" w:right="{right}"/></w:sectPr>'


def test_frozen_margin_basis_vs_no_project_requirement_and_policy_identity():
    generated = assemble_docx({"sections": [empty_content("编制范围", 0)]})
    unbound = check(
        generated, margins=frozen_page_margins(margin_snapshot(("font_size_halfpoints", 24)))
    )
    assert MARGIN_NO_BASIS in unbound.manual_check_codes
    assert unbound.blocking_codes == ()
    assert frozen_page_margins({}) == FrozenPageMargins()
    assert unbound.policy_sha256 != check(generated).policy_sha256

    snapshot = margin_snapshot(("margin_top_twips", 1440))
    bound = frozen_page_margins(snapshot)
    assert bound.expected_twips == (("top", 1440),)
    assert bound.basis_digest is not None and not bound.malformed_basis
    exact = check(generated, margins=bound)
    assert exact.blocking_codes == () and MARGIN_NO_BASIS not in exact.manual_check_codes
    assert "FORMAT_AND_RENDER_REVIEW" in exact.manual_check_codes
    snapshot["authoring_structure"]["metadata"]["format_review_ack"] = "d" * 64
    retraced = check(generated, margins=frozen_page_margins(snapshot))
    assert exact.artifact_sha256 == retraced.artifact_sha256
    assert exact.policy_sha256 != retraced.policy_sha256


@pytest.mark.parametrize("broken", ["ack", "ref", "style", "duplicate", "missing", "fractional"])
def test_invalid_or_incomplete_frozen_basis_is_not_a_template_default(broken):
    snapshot = margin_snapshot(("margin_top_twips", 1440))
    metadata = snapshot["authoring_structure"]["metadata"]
    frozen = metadata["format_binding_manifest"]
    if broken == "ack":
        metadata["format_review_ack"] = None
    if broken == "ref":
        frozen[0]["basis"]["evidence_basis"]["references"] = []
    if broken == "style":
        metadata["effective_style"]["margin_top_twips"] = 800
    if broken == "duplicate":
        frozen.append(deepcopy(frozen[0]))
    if broken == "missing":
        frozen.clear()
    if broken == "fractional":
        frozen[0]["value"] = 1440.0
    basis = frozen_page_margins(snapshot)
    assert basis.malformed_basis and basis.basis_digest is None
    result = check(fixture(body=section()), margins=basis)
    assert result.blocking_codes == (MARGIN_UNINSPECTABLE,)
    assert MARGIN_NO_BASIS not in result.manual_check_codes


@pytest.mark.parametrize(
    ("body", "codes"),
    [
        (f"<w:p><w:pPr>{section()}</w:pPr></w:p>{section()}", ()),
        (f"<w:p><w:pPr>{section(right='721')}</w:pPr></w:p>{section()}", (MARGIN_MISMATCH,)),
        (f"<w:p><w:pPr>{section(top='1cm')}</w:pPr></w:p>{section()}", (MARGIN_UNINSPECTABLE,)),
        (
            f"<w:sdt><w:p><w:pPr>{section()}</w:pPr></w:p></w:sdt>{section()}",
            (MARGIN_UNINSPECTABLE,),
        ),
        ('<w:sectPr><w:pgMar w:top="1440"/></w:sectPr>', (MARGIN_UNINSPECTABLE,)),
        ("<w:sectPr/>", (MARGIN_UNINSPECTABLE,)),
        (section() + section(), (MARGIN_UNINSPECTABLE,)),
        (section() + "<w:p/>", (MARGIN_UNINSPECTABLE,)),
        ("<w:p/>", (MARGIN_UNINSPECTABLE,)),
    ],
)
def test_word_margin_scalars_are_read_in_each_supported_section(body, codes):
    basis = frozen_page_margins(
        margin_snapshot(("margin_top_twips", 1440), ("margin_right_twips", 720))
    )
    checked = check(fixture(body=body), margins=basis)
    assert checked.blocking_codes == codes
    assert "FORMAT_AND_RENDER_REVIEW" in checked.manual_check_codes


def test_generated_word_output_remains_editable_and_has_unchecked_dimensions():
    data = assemble_docx({"title": "技术标", "sections": [empty_content("编制范围", 0)]})
    result = check(data)
    assert result.artifact_sha256 == sha(data)
    assert result.blocking_codes == ()
    assert result.manual_check_codes == (
        "CONTENT_AND_PROJECT_RULE_REVIEW",
        "FORMAT_AND_RENDER_REVIEW",
    )
    assert result == check(data, prohibited=(NAME, "示例 施工单位"))


def test_split_cased_text_checked_by_paragraph_and_project_policy():
    data = fixture(body="<w:p><w:r><w:t>ＡＢ</w:t></w:r><w:r><w:t> c</w:t></w:r></w:p>")
    assert check(data, prohibited=("ab c",)).blocking_codes == ("PROHIBITED_NAME_CONTENT",)
    allowed = check(data, prohibited=())
    assert allowed.blocking_codes == ()
    assert allowed.policy_sha256 != check(data, prohibited=("abc",)).policy_sha256
    separate = fixture(body="<w:p><w:t>ＡＢ</w:t></w:p><w:p><w:t> c</w:t></w:p>")
    assert check(separate, prohibited=("abc",)).blocking_codes == ()


def test_footer_alternative_text_author_and_filename_report_only_codes():
    data = fixture(
        body=f'<w:p><w:drawing descr="{NAME}"/></w:p>',
        footer=f"<w:p><w:r><w:t>{NAME}</w:t></w:r></w:p>",
        properties=f"<creator>{NAME}</creator>",
    )
    result = check(data, name=f"{NAME}.docx")
    assert result.blocking_codes == (
        "AUTHOR_METADATA",
        "PROHIBITED_NAME_ALT_TEXT",
        "PROHIBITED_NAME_FILENAME",
        "PROHIBITED_NAME_HEADER_FOOTER",
        "PROHIBITED_NAME_METADATA",
    )
    assert NAME not in repr(result)


def test_unqualified_word_and_render_features_are_not_treated_as_safe():
    data = fixture(
        body=(
            '<w:p><w:commentReference w:id="1"/><w:ins><w:r><w:rPr><w:vanish/>'
            "</w:rPr><w:t>施工段</w:t></w:r></w:ins></w:p>"
        ),
        extra_rels=(
            f'<Relationship Id="ref" Type="{R}/hyperlink" '
            'Target="https://example.invalid/reference" TargetMode="External"/>'
        ),
        binary=("word/media/image.png", png()),
    )
    result = check(data)
    assert result.blocking_codes == (
        "COMMENT_CONTENT",
        "EXTERNAL_RELATIONSHIP",
        "HIDDEN_CONTENT",
        "TRACKED_CHANGES",
    )
    assert "IMAGE_VISUAL_AND_METADATA_REVIEW" in result.manual_check_codes
    assert check(fixture(binary=("word/vba/vbaProject.bin", b"synthetic"))).blocking_codes == (
        "ACTIVE_OR_EMBEDDED_CONTENT",
        "UNSUPPORTED_BINARY_PART",
    )


def test_embedded_png_validation_does_not_claim_to_have_read_the_pixels():
    clean = check(fixture(binary=("word/media/image.png", png())))
    assert clean.blocking_codes == ()
    assert "IMAGE_VISUAL_AND_METADATA_REVIEW" in clean.manual_check_codes
    assert check(fixture(binary=("word/media/image.png", png(NAME)))).blocking_codes == (
        "EMBEDDED_IMAGE_METADATA",
    )
    assert check(fixture(binary=("word/media/image.png", b"broken"))).blocking_codes == (
        "EMBEDDED_IMAGE_INVALID",
    )


def test_archive_comment_is_not_allowed_even_without_prohibited_names():
    result = check(fixture(archive_comment=NAME), prohibited=())
    assert result.blocking_codes == ("ARCHIVE_METADATA",)
    assert NAME not in repr(result)


def test_malformed_and_wrong_media_fail_closed_and_policy_is_not_silently_ignored():
    assert check(b"not a document").blocking_codes == ("CANDIDATE_DOCX_INVALID",)
    assert check(fixture(), name="技术标.pdf").blocking_codes == ("CANDIDATE_FILENAME_INVALID",)
    with pytest.raises(DomainError) as error:
        check(fixture(), prohibited=(" ",))
    assert error.value.code == "TECHNICAL_CANDIDATE_NAMES_INVALID"


def test_all_fields_except_exact_trusted_footer_page_are_blocked():
    page = '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
    assert check(fixture(footer="<w:p>" + page + "</w:p>")).blocking_codes == ()
    assert check(fixture(body="<w:p>" + page + "</w:p>")).blocking_codes == (
        "FIELD_EVALUATION_UNSUPPORTED",
    )
    assert check(
        fixture(footer="<w:p>" + page.replace(" PAGE ", " NUMPAGES ") + "</w:p>")
    ).blocking_codes == ("FIELD_EVALUATION_UNSUPPORTED",)


@pytest.mark.parametrize(
    "data",
    [
        fixture(body="<w:p><w:r><w:t>工期：{{原始</w:t></w:r><w:r><w:t>日期}}</w:t></w:r></w:p>"),
        fixture(
            body="<w:tbl><w:tr><w:tc><w:p><w:r><w:t>［待填写］</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        ),
        fixture(footer="<w:p><w:r><w:t>【待补充】</w:t></w:r></w:p>"),
        fixture(body="<w:p><w:r><w:t>合同工期：{{ }}</w:t></w:r></w:p>"),
        fixture(
            binary=(
                "word/footnotes.xml",
                (
                    f'<w:footnotes xmlns:w="{W}">'
                    '<w:footnote w:id="2"><w:p><w:r><w:t>[TODO]</w:t></w:r></w:p></w:footnote>'
                    "</w:footnotes>"
                ).encode(),
            ),
        ),
    ],
)
def test_explicit_placeholders_in_exact_word_text_produce_a_bounded_advisory_code(data):
    result = check(data, prohibited=())
    assert result.blocking_codes == ("DOCX_EXPLICIT_PLACEHOLDER",)
    assert result.artifact_sha256 == sha(data)
    assert "CONTENT_AND_PROJECT_RULE_REVIEW" in result.manual_check_codes
    assert "原始日期" not in repr(result)
    assert result.policy_sha256 == sha(
        {
            "filename": "技术标.docx",
            "prohibited_names": (),
            "placeholder_policy": "literal-markers/1",
        }
    )


def test_ordinary_tender_prose_and_split_paragraphs_do_not_become_placeholder_claims():
    data = fixture(
        body=(
            "<w:p><w:r><w:t>模版例子 {{</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>字段}}</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>按规定待补充招标答疑。TODO 为词条示例。</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>单花括号{日期}或正常备注[鉴定结果]。</w:t></w:r></w:p>"
        ),
        properties="<title>【待填写】</title>",
    )
    assert check(data, prohibited=()).blocking_codes == ()
    assert "CONTENT_AND_PROJECT_RULE_REVIEW" in check(data, prohibited=()).manual_check_codes


def test_technical_word_from_real_assembler_flags_only_the_unchanged_marker():
    section = empty_content("施工进度计划", 0)
    section["content"][0]["content"] = [{"type": "text", "text": "计划开工日期：【待核实】"}]
    unfilled = assemble_docx({"sections": [section]})
    section["content"][0]["content"][0]["text"] = "计划开工日期：12 月 10 日（示例）"
    filled = assemble_docx({"sections": [section]})
    assert check(unfilled).blocking_codes == ("DOCX_EXPLICIT_PLACEHOLDER",)
    assert check(filled).blocking_codes == ()
