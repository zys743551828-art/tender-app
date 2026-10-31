"""Real OOXML/PDF checks and deterministic lifecycle failures; no Docker/network."""

import io
import json
import subprocess
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import pytest

from packages.domain.errors import DomainError
from packages.word_intake import execution_transport, prebuilt

REAL_CALL = prebuilt._call


def test_pdf_inspector_change_invalidates_the_old_qualification_profile(monkeypatch):
    identity = prebuilt._fixed()
    old = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    monkeypatch.setattr(prebuilt, "version", lambda package: "synthetic-different-inspector")
    changed = prebuilt._fixed()
    assert identity["image_reference"] == changed["image_reference"]
    assert identity["fontset_digest"] == changed["fontset_digest"]
    assert identity["renderer_digest"] != changed["renderer_digest"]
    assert old["profile_digest"] != prebuilt.digest(changed)
    with pytest.raises(prebuilt.PrebuiltError, match="WORD_PREBUILT_PROFILE_CHANGED"):
        prebuilt.validate_profile(old)


@pytest.fixture(autouse=True)
def no_external_processes(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not invoke Docker or external services")

    monkeypatch.setattr(prebuilt, "_call", blocked)
    monkeypatch.setattr(prebuilt, "_Run", blocked)
    monkeypatch.setattr(execution_transport, "enabled", lambda: False)


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

    def isolation(identity):
        expected, temporary = prebuilt._isolation_requirements()
        return expected | {
            "image_id": prebuilt.IMAGE_ID,
            "user": "65534:65534",
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "tmpfs": temporary,
            "checks": {
                key: key != "own_job_cleanup_confirmed" for key in prebuilt.ISOLATION_CHECKS
            },
        }

    monkeypatch.setattr(prebuilt, "_start", lambda run: ("owned-container", isolation("owned")))
    monkeypatch.setattr(prebuilt, "_isolation", isolation)
    monkeypatch.setattr(
        prebuilt,
        "_font_facts",
        lambda identity, names: {
            "matches": [{"requested": name, "families": name} for name in names],
            "charset": "0-10ffff\n",
        },
    )

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
    assert result["chain"]["renderer_digest"] == runtime.profile["identity"]["renderer_digest"]
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
    image = {
        "Id": prebuilt.IMAGE_ID,
        "RepoDigests": [prebuilt.REPOSITORY_DIGEST],
        "Architecture": "amd64",
        "Os": "linux",
        "Config": {},
    }
    image[field] = value
    monkeypatch.setattr(
        prebuilt, "_successful", lambda *args, **kwargs: json.dumps([image]).encode()
    )
    with pytest.raises(prebuilt.PrebuiltError, match="IMAGE_MISMATCH"):
        prebuilt._image()


@pytest.mark.parametrize("observed_id", [prebuilt.IMAGE_ID, prebuilt.MANIFEST_DIGEST])
def test_standard_docker_and_containerd_image_ids_require_exact_repository_digest(
    monkeypatch, observed_id
):
    image = {
        "Id": observed_id,
        "RepoDigests": [prebuilt.REPOSITORY_DIGEST],
        "Architecture": "amd64",
        "Os": "linux",
        "Config": {},
    }
    monkeypatch.setattr(
        prebuilt, "_successful", lambda *args, **kwargs: json.dumps([image]).encode()
    )
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
    result = {
        "Image": prebuilt.IMAGE_ID,
        "Config": {
            "User": "65534:65534",
            "Image": prebuilt.IMAGE,
            "Env": ["HOME=/tmp", "TMPDIR=/tmp", "LANG=C.UTF-8"],
        },
        "HostConfig": host,
    }
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


def remote(monkeypatch, runtime, tmp_path):
    source = docx()
    facts = prebuilt.convert_in_isolation(source, [], receipt=tmp_path / "raw.json")
    assert facts["error_code"] is None and facts["cleanup_confirmed"]
    runtime.events.clear()
    requests = []

    def exchange(data, names):
        assert data == source
        requests.append(list(names))
        return deepcopy(facts)

    def forbidden(*args, **kwargs):
        raise AssertionError("Worker must not invoke local Docker in remote mode")

    monkeypatch.setattr(execution_transport, "enabled", lambda: True)
    monkeypatch.setattr(execution_transport, "call_conversion", exchange, raising=False)
    monkeypatch.setattr(prebuilt, "convert_in_isolation", forbidden)
    monkeypatch.setattr(prebuilt, "_Run", forbidden)
    return source, facts, requests


def test_fixed_helper_returns_raw_facts_without_business_qualification(runtime, tmp_path):
    source = docx()
    facts = prebuilt.convert_in_isolation(
        source, ["Noto Sans", "Noto Sans"], receipt=tmp_path / "raw.json"
    )
    assert set(facts) == {
        "pdf",
        "font_facts",
        "isolation",
        "conversion_attempted",
        "error_code",
        "source_docx_digest",
        "image_reference",
        "image_id",
        "cleanup_confirmed",
    }
    assert facts["source_docx_digest"] == prebuilt.digest(source)
    assert facts["pdf"] == pdf() and facts["cleanup_confirmed"]
    assert (
        facts["font_facts"]["matches"] == [{"requested": "Noto Sans", "families": "Noto Sans"}] * 2
    )
    assert runtime.events == ["enter", "cleanup"]


@pytest.mark.parametrize("fonts", [["-option"], ["bad/font"], ["$(command)"], [None], "not a list"])
def test_helper_rejects_nonexecutable_font_names_before_container(runtime, tmp_path, fonts):
    facts = prebuilt.convert_in_isolation(docx(), fonts, receipt=tmp_path / "raw.json")
    assert facts["error_code"] == "WORD_FONT_NAME_UNSUPPORTED"
    assert not facts["conversion_attempted"] and facts["cleanup_confirmed"]
    assert facts["pdf"] is None and runtime.events == []


def test_remote_worker_parses_actual_pdf_and_preserves_receipt(runtime, monkeypatch, tmp_path):
    source, facts, requests = remote(monkeypatch, runtime, tmp_path)
    facts["resource_receipt"] = {
        "closed": True,
        "receipts": [{"receipt": "conversion-synthetic.json", "closed": True, "run_id": "1" * 32}],
    }
    outcome = prebuilt.render(source, runtime.profile, receipt=tmp_path / "unused.json")
    assert outcome["coverage"] == "complete" and outcome["gaps"] == []
    assert outcome["chain"]["pdf_digest"] == prebuilt.digest(pdf())
    assert outcome["resource_receipt"] == facts["resource_receipt"]
    assert requests == [[]] and runtime.events == []


def test_remote_pdf_text_is_verified_by_worker_not_host_verdict(runtime, monkeypatch, tmp_path):
    source, facts, requests = remote(monkeypatch, runtime, tmp_path)
    facts["pdf"] = pdf("Synthetic 124")
    outcome = prebuilt.render(source, runtime.profile, receipt=tmp_path / "unused.json")
    assert outcome["coverage"] == "partial"
    assert "WORD_TEXT_CORRESPONDENCE_UNVERIFIED" in outcome["gaps"]
    assert requests == [[]] and runtime.events == []


@pytest.mark.parametrize(
    "attack,expected",
    [
        ("source", "WORD_PREBUILT_CONVERSION_FACTS_INVALID"),
        ("image", "WORD_PREBUILT_CONVERSION_FACTS_INVALID"),
        ("image_id", "WORD_PREBUILT_CONVERSION_FACTS_INVALID"),
        ("business_verdict", "WORD_PREBUILT_CONVERSION_FACTS_INVALID"),
        ("missing_fonts", "WORD_PREBUILT_FONT_FACTS_INVALID"),
        ("extra_fonts", "WORD_PREBUILT_FONT_FACTS_INVALID"),
        ("pdf", "WORD_PDF_INVALID"),
        ("cleanup", "WORD_PREBUILT_CLEANUP_UNCONFIRMED"),
        ("isolation", "WORD_PREBUILT_ISOLATION_MISMATCH"),
        ("receipt", "WORD_PREBUILT_CLEANUP_UNCONFIRMED"),
    ],
)
def test_remote_wrong_identity_missing_facts_and_unclean_results_never_complete(
    runtime, monkeypatch, tmp_path, attack, expected
):
    source, facts, _ = remote(monkeypatch, runtime, tmp_path)
    if attack == "source":
        facts["source_docx_digest"] = "0" * 64
    elif attack == "image":
        facts["image_reference"] = "other:latest"
    elif attack == "image_id":
        facts["image_id"] = "sha256:" + "0" * 64
    elif attack == "business_verdict":
        facts["coverage"] = "complete"
    elif attack == "missing_fonts":
        facts["font_facts"] = None
    elif attack == "extra_fonts":
        facts["font_facts"]["matches"] = [{"requested": "other", "families": "other"}]
    elif attack == "pdf":
        facts["pdf"] = b"not PDF"
    elif attack == "cleanup":
        facts["cleanup_confirmed"] = False
    elif attack == "isolation":
        facts["isolation"]["checks"]["network_none"] = False
    else:
        facts["resource_receipt"] = {"closed": True, "receipts": [{"closed": False}]}
    outcome = prebuilt.render(source, runtime.profile, receipt=tmp_path / "unused.json")
    assert outcome["state"] == "failed" and outcome["pdf"] is None
    assert outcome["error_code"] == expected and runtime.events == []


def test_worker_keeps_original_invalid_name_substitution_and_glyph_gaps(
    runtime, monkeypatch, tmp_path
):
    source, facts, requests = remote(monkeypatch, runtime, tmp_path)
    names = ["Requested", "bad/font", "-option", "Requested"]
    facts["font_facts"] = {
        "matches": [{"requested": "Requested", "families": "Replacement"}] * 2,
        "charset": "20-7e\n",
    }
    outcome = prebuilt._render_generated(
        source,
        runtime.profile,
        receipt=tmp_path / "unused.json",
        admit=lambda: {
            "proof": {"source_docx_digest": prebuilt.digest(source)},
            "font_inspection": {"requested_fonts": names, "paragraphs": ["中文123"]},
        },
        inspect_pdf=lambda data, prepared: {"page_count": 1, "gaps": []},
    )
    assert requests == [["Requested", "Requested"]]
    assert outcome["gaps"] == [
        "WORD_FONT_SUBSTITUTED",
        "WORD_FONT_NAME_UNSUPPORTED",
        "WORD_FONT_GLYPH_UNAVAILABLE",
    ]
    assert outcome["coverage"] == "partial"


@pytest.mark.parametrize("attack", ["profile", "active_field", "source_proof"])
def test_remote_request_cannot_precede_worker_admission(runtime, monkeypatch, tmp_path, attack):
    source, _, requests = remote(monkeypatch, runtime, tmp_path)
    profile = deepcopy(runtime.profile)
    if attack == "profile":
        profile["identity"]["image_id"] = "other"
        profile["profile_digest"] = prebuilt.digest(profile["identity"])
        outcome = prebuilt.render(source, profile, receipt=tmp_path / "unused.json")
    elif attack == "active_field":
        outcome = prebuilt.render(docx(field=True), profile, receipt=tmp_path / "unused.json")
    else:
        outcome = prebuilt._render_generated(
            source,
            profile,
            receipt=tmp_path / "unused.json",
            admit=lambda: {"proof": {"source_docx_digest": "0" * 64}},
            inspect_pdf=lambda *args: pytest.fail("must not inspect"),
        )
    assert outcome["state"] == "failed" and not outcome["conversion_attempted"]
    assert requests == [] and runtime.events == []


def test_transport_timeout_propagates_without_generic_retry_regression(
    runtime, monkeypatch, tmp_path
):
    source, _, _ = remote(monkeypatch, runtime, tmp_path)
    error = DomainError("WORD_EXECUTION_TIMEOUT", "synthetic", 503, retryable=True)

    def timeout(*args):
        raise error

    monkeypatch.setattr(execution_transport, "call_conversion", timeout)
    with pytest.raises(DomainError) as actual:
        prebuilt.render(source, runtime.profile, receipt=tmp_path / "unused.json")
    assert actual.value is error and actual.value.retryable


def test_nontransport_domain_error_keeps_native_failure_semantics(runtime, tmp_path):
    def admit():
        raise DomainError("SYNTHETIC_ADMISSION_FAILURE", "synthetic", 422)

    outcome = prebuilt._render_generated(
        docx(),
        runtime.profile,
        receipt=tmp_path / "unused.json",
        admit=admit,
        inspect_pdf=lambda *args: pytest.fail("must not inspect"),
    )
    assert outcome["error_code"] == "WORD_PREBUILT_CONVERSION_FAILED"
    assert runtime.events == []


def test_native_unconfirmed_cleanup_cannot_return_raw_pdf_or_complete(
    runtime, monkeypatch, tmp_path
):
    class Unclosed:
        closed = False

        def __init__(self, receipt):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(prebuilt, "_Run", Unclosed)
    facts = prebuilt.convert_in_isolation(docx(), [], receipt=tmp_path / "raw.json")
    assert not facts["cleanup_confirmed"] and facts["pdf"] is None
    assert facts["error_code"] == "WORD_PREBUILT_CLEANUP_UNCONFIRMED"
    outcome = prebuilt.render(docx(), runtime.profile, receipt=tmp_path / "run.json")
    assert outcome["state"] == "failed" and outcome["pdf"] is None
