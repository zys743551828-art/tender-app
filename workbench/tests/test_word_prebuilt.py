"""Real OOXML/PDF checks and deterministic lifecycle failures; no Docker/network."""

import io
import json
import subprocess
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import pytest

from packages.word_intake import prebuilt

REAL_CALL = prebuilt._call


@pytest.fixture(autouse=True)
def no_external_processes(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not invoke Docker or external services")

    monkeypatch.setattr(prebuilt, "_call", blocked)
    monkeypatch.setattr(prebuilt, "_Run", blocked)


def docx(text="Synthetic 123", *, field=False, complex_layout=False):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        stream.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        extra = '<w:fldSimple w:instr="PAGE"/>' if field else "<w:tbl/>" if complex_layout else ""
        stream.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            + text
            + "</w:t></w:r></w:p>"
            + extra
            + "</w:body></w:document>",
        )
    return archive.getvalue()


def pdf(text="Synthetic 123"):
    contents = f"BT /F1 12 Tf 40 750 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        f"<</Length {len(contents)}>>\nstream\n".encode() + contents + b"\nendstream",
    ]
    value = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(value))
        value += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    position = len(value)
    value += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode() for offset in offsets
    )
    return value + f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{position}\n%%EOF\n".encode()


@pytest.fixture
def runtime(monkeypatch):
    identity = prebuilt._fixed()
    profile = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    events = []

    class Run:
        closed = False

        def __init__(self, receipt):
            self.receipt = receipt

        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, *args):
            self.closed = True
            events.append("cleanup")

    monkeypatch.setattr(prebuilt, "_Run", Run)
    monkeypatch.setattr(prebuilt, "_start", lambda run: ("owned-container", {}))
    monkeypatch.setattr(prebuilt, "_isolation", lambda identity: {})
    monkeypatch.setattr(prebuilt, "_font_gaps", lambda identity, inspection: [])

    def convert(arguments, *, data=None, timeout=30):
        assert arguments == ["exec", "-i", "owned-container", "/bin/sh", "-c", prebuilt.CONVERT]
        assert data.startswith(b"PK")
        assert timeout == 50
        return SimpleNamespace(returncode=0, stdout=b"200\n" + pdf())

    monkeypatch.setattr(prebuilt, "_call", convert)
    return SimpleNamespace(profile=profile, events=events)


def test_real_ooxml_and_pdf_preserve_text_and_cleanup(runtime, tmp_path):
    result = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    assert result["coverage"] == "complete"
    assert result["chain"]["pdf_digest"] == prebuilt.digest(pdf())
    assert result["isolation"]["own_job_cleanup_confirmed"]
    assert runtime.events == ["enter", "cleanup"]


def test_complex_layout_is_partial_even_with_http_200(runtime, tmp_path):
    result = prebuilt.render(
        docx(complex_layout=True), runtime.profile, receipt=tmp_path / "run.json"
    )
    assert result["coverage"] == "partial"
    assert "WORD_COMPLEX_LAYOUT_UNVERIFIED" in result["gaps"]
    assert result["pdf"] is not None


def test_active_page_field_is_rejected_before_container(runtime, tmp_path):
    result = prebuilt.render(docx(field=True), runtime.profile, receipt=tmp_path / "run.json")
    assert result["error_code"] == "WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED"
    assert runtime.events == []


def test_rehashed_other_image_profile_cannot_select_arbitrary_image(runtime, tmp_path):
    profile = deepcopy(runtime.profile)
    profile["identity"]["image_reference"] = "arbitrary/image:latest"
    profile["profile_digest"] = prebuilt.digest(profile["identity"])
    result = prebuilt.render(docx(), profile, receipt=tmp_path / "run.json")
    assert result["error_code"] == "WORD_PREBUILT_PROFILE_CHANGED"
    assert runtime.events == []


@pytest.mark.parametrize(
    "response,expected",
    [(b"200\nnot a PDF", "WORD_PDF_INVALID"), (b"503\n", "WORD_PREBUILT_HTTP_REJECTED")],
)
def test_http_or_invalid_pdf_never_becomes_success(
    runtime, monkeypatch, tmp_path, response, expected
):
    monkeypatch.setattr(
        prebuilt, "_call", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=response)
    )
    result = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    assert result["error_code"] == expected
    assert result["pdf"] is None
    assert runtime.events[-1] == "cleanup"


def test_changed_text_never_becomes_complete(runtime, monkeypatch, tmp_path):
    monkeypatch.setattr(
        prebuilt,
        "_call",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=b"200\n" + pdf("Synthetic 124")
        ),
    )
    result = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    assert result["coverage"] == "partial"
    assert "WORD_TEXT_CORRESPONDENCE_UNVERIFIED" in result["gaps"]


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("synthetic", 50), KeyboardInterrupt()])
def test_timeout_or_cancellation_always_leaves_context(runtime, monkeypatch, tmp_path, error):
    def interrupted(*args, **kwargs):
        raise error

    monkeypatch.setattr(prebuilt, "_call", interrupted)
    if isinstance(error, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    else:
        result = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
        assert result["error_code"] == "WORD_CONVERSION_TIMEOUT"
    assert runtime.events[-1] == "cleanup"


def test_changed_behavior_source_rejects_qualification_before_container(
    runtime, monkeypatch, tmp_path
):
    changed = {**prebuilt._fixed(), "adapter_source_digest": "0" * 64}
    monkeypatch.setattr(prebuilt, "_fixed", lambda: changed)
    result = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    assert result["error_code"] == "WORD_PREBUILT_PROFILE_CHANGED"
    assert not result["conversion_attempted"]
    assert runtime.events == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("Id", "sha256:" + "0" * 64),
        ("Architecture", "arm64"),
        ("Os", "windows"),
        ("Config", {"Volumes": {"/persistent": {}}}),
    ],
)
def test_image_identity_platform_and_anonymous_volume_rejected(monkeypatch, field, value):
    image = {"Id": prebuilt.IMAGE_ID, "RepoDigests": [prebuilt.REPOSITORY_DIGEST], "Architecture": "amd64", "Os": "linux", "Config": {}}
    image[field] = value
    monkeypatch.setattr(
        prebuilt, "_successful", lambda *args, **kwargs: json.dumps([image]).encode()
    )
    with pytest.raises(prebuilt.PrebuiltError, match="IMAGE_MISMATCH"):
        prebuilt._image()


@pytest.mark.parametrize("observed_id", [prebuilt.IMAGE_ID, prebuilt.MANIFEST_DIGEST])
def test_standard_docker_and_containerd_image_ids_require_exact_repository_digest(monkeypatch, observed_id):
    image = {"Id": observed_id, "RepoDigests": [prebuilt.REPOSITORY_DIGEST], "Architecture": "amd64", "Os": "linux", "Config": {}}
    monkeypatch.setattr(prebuilt, "_successful", lambda *args, **kwargs: json.dumps([image]).encode())
    assert prebuilt._image()["Id"] == observed_id
    image["RepoDigests"] = ["untrusted/other@" + prebuilt.MANIFEST_DIGEST]
    with pytest.raises(prebuilt.PrebuiltError, match="IMAGE_MISMATCH"):
        prebuilt._image()


def test_body_is_stdin_and_transport_is_local_without_proxy_or_provider_env(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.invalid:2375")
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid")
    monkeypatch.setenv("API_DATABASE_DSN", "synthetic-sensitive")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    REAL_CALL(["exec", "-i", "owned", "/bin/sh", "-c", prebuilt.CONVERT], data=b"untrusted $(text)")
    argv, options = calls[0]
    assert argv[1] == "--host"
    assert "untrusted $(text)" not in " ".join(argv)
    assert options["input"] == b"untrusted $(text)"
    assert not {"DOCKER_HOST", "HTTPS_PROXY", "API_DATABASE_DSN"} & set(options["env"])


@pytest.mark.parametrize(
    "kind,value",
    [
        ("NetworkMode", "bridge"),
        ("ReadonlyRootfs", False),
        ("Privileged", True),
        ("Binds", ["/private:/private:ro"]),
        ("PortBindings", {"3000/tcp": [{"HostPort": "3000"}]}),
        ("NetworkMode", "none"),
    ],
)
def test_actual_runtime_isolation_drift_is_rejected(monkeypatch, kind, value):
    host = {
        "NetworkMode": "none",
        "IpcMode": "none",
        "ReadonlyRootfs": True,
        "Memory": 536870912,
        "MemorySwap": 536870912,
        "NanoCpus": 1000000000,
        "PidsLimit": 64,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "LogConfig": {"Type": "none"},
        "Tmpfs": {
            "/tmp": "rw,noexec,nosuid,nodev,size=134217728,mode=1777",
            "/input": "rw,noexec,nosuid,nodev,size=104857600,mode=1777",
            "/output": "rw,noexec,nosuid,nodev,size=67108864,mode=1777",
        },
    }
    host[kind] = value
    result = {"Image": prebuilt.IMAGE_ID, "Config": {"User": "65534:65534", "Image": prebuilt.IMAGE, "Env": ["HOME=/tmp", "TMPDIR=/tmp", "LANG=C.UTF-8"]}, "HostConfig": host}
    monkeypatch.setattr(prebuilt, "_image", lambda: {"Config": {"Env": []}})
    monkeypatch.setattr(
        prebuilt, "_successful", lambda *args, **kwargs: json.dumps([result]).encode()
    )
    if kind == "NetworkMode" and value == "none":
        observed = prebuilt._isolation("owned")
        assert set(observed["checks"]) == prebuilt.ISOLATION_CHECKS
        assert observed["checks"]["own_job_cleanup_confirmed"] is False
        return
    with pytest.raises(prebuilt.PrebuiltError, match="ISOLATION_MISMATCH"):
        prebuilt._isolation("owned")


def test_image_font_substitution_and_missing_glyphs_remain_gaps(monkeypatch):
    # Exercise the actual font check, not host fc-match or an arbitrary font mount.
    def output(args, **kwargs):
        assert args[:3] == ["exec", "owned", "fc-match"]
        return b"Replacement" if "--format=%{family}" in args else b"20-7e\n"

    monkeypatch.setattr(prebuilt, "_successful", output)
    gaps = prebuilt._font_gaps(
        "owned", {"requested_fonts": ["Requested"], "paragraphs": ["中文123"]}
    )
    assert gaps == ["WORD_FONT_SUBSTITUTED", "WORD_FONT_GLYPH_UNAVAILABLE"]


def test_cli_describe_never_uses_docker_or_business_configuration(capsys):
    from deploy.word_prebuilt import main

    assert main(["describe"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["old_word03_unchanged"]
    assert not value["business_wiring"]
    assert value["model_calls"] == 0


def test_cli_refuses_existing_outputs_before_runtime(tmp_path):
    from deploy.word_prebuilt import main

    output = tmp_path / "existing.pdf"
    output.write_bytes(b"keep")
    result = main(
        [
            "convert",
            "--profile",
            str(tmp_path / "profile.json"),
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--source",
            str(tmp_path / "source.docx"),
            "--output",
            str(output),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert result == 1
    assert output.read_bytes() == b"keep"
    assert not (tmp_path / "receipt.json").exists()
