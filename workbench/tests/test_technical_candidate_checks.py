"""Synthetic packages validating candidate-level blocking and review gaps."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from PIL import Image, PngImagePlugin

from packages.authoring.build import assemble_docx
from packages.authoring.content import empty_content
from packages.authoring.technical_candidate_checks import inspect_candidate_docx
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


def check(data, *, name="技术标.docx", prohibited=(NAME,)):
    return inspect_candidate_docx(data, filename=name, prohibited_names=prohibited)


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
