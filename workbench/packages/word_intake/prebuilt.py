"""Opt-in, per-document official prebuilt LibreOffice candidate; no business wiring.

The image is never built or pulled here. No request can choose an image, URL,
command, font directory or host mount. Existing Word03 profiles remain separate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess  # nosec B404
import tempfile
import unicodedata
from importlib.metadata import version
from pathlib import Path
from typing import Any

from deploy.disposable_docker import DockerTestRun
from packages.domain.errors import DomainError

PROTOCOL = "word-prebuilt-gotenberg/2"
IMAGE = "gotenberg/gotenberg:8.39.0-libreoffice@sha256:298c3989049baf530afe7137b64374c22810bb863ef1ed91d256e33f335af161"
IMAGE_ID = "sha256:e3d196d893aa14a70057f9b6e33c11f6120cb2f721fc6ee4f85150a48686060e"
MANIFEST_DIGEST = IMAGE.rsplit("@", 1)[1]
REPOSITORY_DIGEST = "gotenberg/gotenberg@" + MANIFEST_DIGEST
MAX_SOURCE = 100 * 1024 * 1024
MAX_PDF = 50 * 1024 * 1024
OPTIONS = {
    "network": "none",
    "ipc": "none",
    "user": "65534:65534",
    "read_only": True,
    "memory": 512 * 1024 * 1024,
    "cpus": 1,
    "pids": 64,
    "timeout": 50,
    "max_pdf_bytes": MAX_PDF,
    "update_indexes": False,
    "lossless_image_compression": True,
    "export_bookmarks": True,
    "export_bookmarks_to_pdf_destination": True,
    "font_policy": "image_fonts_by_standard_image_digest; per_document_font_and_glyph_checks",
}
ISOLATION_CHECKS = frozenset(
    {
        "immutable_image",
        "network_none",
        "ipc_none",
        "pid_private",
        "uts_private",
        "nonroot",
        "read_only",
        "not_privileged",
        "capabilities_dropped",
        "no_new_privileges",
        "memory_limited",
        "cpu_limited",
        "pids_limited",
        "no_daemon_document_logs",
        "clean_environment",
        "no_host_binds_or_ports",
        "no_anonymous_persistent_volumes",
        "bounded_tmpfs_output",
        "own_job_cleanup_confirmed",
    }
)
COMMAND = (
    "gotenberg",
    "--api-disable-download-from=true",
    "--webhook-disable=true",
    "--libreoffice-deny-list=.*",
    "--api-timeout=50s",
    "--libreoffice-start-timeout=20s",
    "--libreoffice-auto-start=true",
    "--libreoffice-max-queue-size=1",
    "--api-body-limit=106MB",
)
ARGUMENTS = (
    "--network",
    "none",
    "--ipc",
    "none",
    "--read-only",
    "--user",
    "65534:65534",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    "--memory",
    "512m",
    "--memory-swap",
    "512m",
    "--cpus",
    "1",
    "--pids-limit",
    "64",
    "--log-driver",
    "none",
    "--ulimit",
    "nofile=256:256",
    "--ulimit",
    "core=0:0",
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777",  # nosec B108 - private container tmpfs
    "--tmpfs",
    "/input:rw,noexec,nosuid,nodev,size=104857600,mode=1777",
    "--tmpfs",
    "/output:rw,noexec,nosuid,nodev,size=67108864,mode=1777",
    "--env",
    "HOME=/tmp",
    "--env",
    "TMPDIR=/tmp",
    "--env",
    "LANG=C.UTF-8",
)
# Only fixed shell scripts run. The untrusted DOCX is stdin, never shell text.
READY = (
    "curl",
    "--silent",
    "--fail",
    "--noproxy",
    "*",
    "--max-time",
    "2",
    "--retry",
    "20",
    "--retry-delay",
    "1",
    "--retry-connrefused",
    "--retry-max-time",
    "25",
    "http://127.0.0.1:3000/health",
)
CONVERT = """set -eu
umask 077
cat > /input/source.docx
status=$(curl --silent --noproxy '*' --max-time 40 --max-filesize 52428800 \
  --output /output/result.pdf --write-out '%{http_code}' \
  --form 'files=@/input/source.docx;filename=source.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document' \
  --form 'updateIndexes=false' --form 'losslessImageCompression=true' \
  --form 'exportBookmarks=true' --form 'exportBookmarksToPdfDestination=true' http://127.0.0.1:3000/forms/libreoffice/convert) || { code=$?; if [ "$code" = 28 ]; then exit 72; fi; exit 71; }
printf '%s\\n' "$status"
if [ "$status" = 200 ]; then cat /output/result.pdf; fi
"""


class PrebuiltError(RuntimeError):
    """Safe stable code only; never propagate Docker/provider stderr."""


def digest(value: Any) -> str:
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    return hashlib.sha256(raw).hexdigest()


def _environment() -> dict[str, str]:
    # Local Docker transport and executable discovery only. No provider/DSN/proxy
    # environment is inherited by the subprocess or passed into the container.
    allowed = {
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _docker_prefix() -> list[str]:
    host = (
        "npipe:////./pipe/dockerDesktopLinuxEngine"
        if os.name == "nt"
        else "unix:///var/run/docker.sock"
    )
    return ["docker", "--host", host]


class _Run(DockerTestRun):
    @staticmethod
    def _call(*args, timeout=60, env=None):
        result = _call(list(args), timeout=timeout)
        return subprocess.CompletedProcess(
            result.args,
            result.returncode,
            result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"),
        )


def _call(arguments, *, data=None, timeout=30):
    with tempfile.TemporaryDirectory(prefix="word-prebuilt-docker-") as directory:
        environment = _environment()
        environment["DOCKER_CONFIG"] = directory
        return subprocess.run(  # nosec B603
            [*_docker_prefix(), *arguments],
            input=data,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
        )


def _successful(arguments, *, data=None, timeout=30) -> bytes:
    result = _call(arguments, data=data, timeout=timeout)
    if result.returncode:
        raise PrebuiltError("WORD_PREBUILT_COMMAND_FAILED")
    return result.stdout


def _image() -> dict:
    try:
        image = json.loads(_successful(["image", "inspect", IMAGE]))[0]
        if (
            image["Id"] not in {IMAGE_ID, MANIFEST_DIGEST}
            or REPOSITORY_DIGEST not in image.get("RepoDigests", [])
            or image["Os"] != "linux"
            or image["Architecture"] != "amd64"
            or image["Config"].get("Volumes")
        ):
            raise PrebuiltError("WORD_PREBUILT_IMAGE_MISMATCH")
        return image
    except (KeyError, IndexError, TypeError, ValueError) as from_error:
        raise PrebuiltError("WORD_PREBUILT_IMAGE_MISMATCH") from from_error


def _isolation_requirements():
    expected = {
        "NetworkMode": "none",
        "IpcMode": "none",
        "ReadonlyRootfs": True,
        "Memory": OPTIONS["memory"],
        "MemorySwap": OPTIONS["memory"],
        "NanoCpus": 1_000_000_000,
        "PidsLimit": 64,
    }
    expected_tmpfs = {
        "/tmp": "rw,noexec,nosuid,nodev,size=134217728,mode=1777",  # nosec B108 - private container tmpfs
        "/input": "rw,noexec,nosuid,nodev,size=104857600,mode=1777",
        "/output": "rw,noexec,nosuid,nodev,size=67108864,mode=1777",
    }
    return expected, expected_tmpfs


def _isolation(identity: str) -> dict:
    value = json.loads(_successful(["container", "inspect", identity]))[0]
    host = value["HostConfig"]
    expected_environment = dict(item.split("=", 1) for item in _image()["Config"].get("Env", []))
    # These paths refer to the inspected private container tmpfs.
    expected_environment.update(HOME="/tmp", TMPDIR="/tmp", LANG="C.UTF-8")  # nosec B108
    actual_environment = dict(item.split("=", 1) for item in value["Config"].get("Env", []))
    expected, expected_tmpfs = _isolation_requirements()
    if (
        value["Image"] not in {IMAGE_ID, MANIFEST_DIGEST}
        or value["Config"].get("Image") != IMAGE
        or value["Config"]["User"] != "65534:65534"
        or any(host.get(key) != item for key, item in expected.items())
        or host.get("Privileged")
        or host.get("CapAdd")
        or host.get("Binds")
        or host.get("PortBindings")
        or host.get("Devices")
        or host.get("PidMode", "") != ""
        or host.get("UTSMode", "") != ""
        or actual_environment != expected_environment
        or host.get("LogConfig", {}).get("Type") != "none"
        or host.get("CapDrop") != ["ALL"]
        or "no-new-privileges" not in host.get("SecurityOpt", [])
        or host.get("Tmpfs") != expected_tmpfs
        or any(item.get("Type") != "tmpfs" for item in value.get("Mounts", []))
    ):
        raise PrebuiltError("WORD_PREBUILT_ISOLATION_MISMATCH")
    checks = {key: key != "own_job_cleanup_confirmed" for key in ISOLATION_CHECKS}
    return {
        **expected,
        "image_id": IMAGE_ID,
        "user": "65534:65534",
        "cap_drop": "ALL",
        "no_new_privileges": True,
        "tmpfs": expected_tmpfs,
        "checks": checks,
    }


def _fixed() -> dict:
    # Docker's immutable manifest/config identities cover bundled tools and fonts.
    # These two source identities qualify behavior (OOXML rejection and output
    # checks), not the upstream release; they do not scan the repository/assets.
    adapter = digest(Path(__file__).read_bytes())
    pdf_inspector = {"package": "pypdfium2", "version": version("pypdfium2")}
    return {
        "protocol": PROTOCOL,
        "image_reference": IMAGE,
        "image_id": IMAGE_ID,
        "platform": "linux/amd64",
        "options": dict(OPTIONS),
        "adapter_source_digest": adapter,
        "renderer_digest": digest(
            {"image": IMAGE, "adapter": adapter, "pdf_inspector": pdf_inspector}
        ),
        "pdf_inspector": pdf_inspector,
        "fontset_digest": digest({"image": IMAGE, "policy": OPTIONS["font_policy"]}),
        "options_digest": digest(OPTIONS),
        "inspection_source_digest": digest(Path(__file__).with_name("inspection.py").read_bytes()),
    }


def validate_profile(profile: dict) -> None:
    try:
        if not isinstance(profile, dict) or not isinstance(profile.get("identity"), dict):
            raise PrebuiltError("WORD_PREBUILT_PROFILE_CHANGED")
        identity = profile["identity"]
        if (
            set(profile) != {"identity", "profile_digest"}
            or digest(identity) != profile["profile_digest"]
            or set(identity) != set(_fixed())
            or any(identity.get(key) != value for key, value in _fixed().items())
        ):
            raise PrebuiltError("WORD_PREBUILT_PROFILE_CHANGED")
    except (KeyError, TypeError, ValueError) as error:
        raise PrebuiltError("WORD_PREBUILT_PROFILE_CHANGED") from error


def _start(run: DockerTestRun) -> tuple[str, dict]:
    _image()
    identity = run.container(IMAGE, ARGUMENTS, COMMAND, env=_environment())
    isolation = _isolation(identity)
    run.start(identity)
    _successful(["exec", identity, *READY], timeout=30)
    return identity, isolation


def build_profile(*, receipt: Path) -> dict:
    with _Run(receipt) as run:
        _image()
        value = _fixed()
    if not run.closed:
        raise PrebuiltError("WORD_PREBUILT_CLEANUP_UNCONFIRMED")
    return {"identity": value, "profile_digest": digest(value)}


def _valid_font_name(name):
    return (
        isinstance(name, str)
        and re.fullmatch(r"[\w ,.-]{1,128}", name) is not None
        and not name.startswith("-")
    )


def _font_facts(identity: str, requested_fonts: list[str]) -> dict:
    matches = []
    for name in requested_fonts:
        families = _successful(
            ["exec", identity, "fc-match", "--format=%{family}", "--", name]
        ).decode("utf-8")
        matches.append({"requested": name, "families": families})
    charset = _successful(["exec", identity, "fc-match", "-s", "--format=%{charset}\\n"]).decode(
        "ascii"
    )
    return {"matches": matches, "charset": charset}


def _font_gaps_from_facts(inspection: dict, facts: dict) -> list[str]:
    expected = [name for name in inspection["requested_fonts"] if _valid_font_name(name)]
    if (
        not isinstance(facts, dict)
        or set(facts) != {"matches", "charset"}
        or not isinstance(facts["matches"], list)
        or len(facts["matches"]) != len(expected)
        or not isinstance(facts["charset"], str)
        or any(
            not isinstance(item, dict)
            or set(item) != {"requested", "families"}
            or item["requested"] != name
            or not isinstance(item["families"], str)
            for item, name in zip(facts["matches"], expected, strict=True)
        )
    ):
        raise PrebuiltError("WORD_PREBUILT_FONT_FACTS_INVALID")
    # Keep the original requested-name ordering, substitution and glyph rules.
    gaps, index = [], 0
    for name in inspection["requested_fonts"]:
        if not _valid_font_name(name):
            gaps.append("WORD_FONT_NAME_UNSUPPORTED")
            continue
        families = facts["matches"][index]["families"]
        index += 1
        if name.casefold() not in {part.strip().casefold() for part in families.split(",")}:
            gaps.append("WORD_FONT_SUBSTITUTED")
    charset = facts["charset"]
    charset.encode("ascii")
    ranges = []
    for token in charset.split():
        bounds = token.split("-")
        ranges.append((int(bounds[0], 16), int(bounds[-1], 16)))
    if any(
        not any(left <= ord(c) <= right for left, right in ranges)
        for paragraph in inspection["paragraphs"]
        for c in paragraph
        if not c.isspace()
    ):
        gaps.append("WORD_FONT_GLYPH_UNAVAILABLE")
    return list(dict.fromkeys(gaps))


def _font_gaps(identity: str, inspection: dict) -> list[str]:
    return _font_gaps_from_facts(
        inspection,
        _font_facts(
            identity, [name for name in inspection["requested_fonts"] if _valid_font_name(name)]
        ),
    )


def convert_in_isolation(source: bytes, requested_fonts: list[str], *, receipt: Path) -> dict:
    """Fixed Docker conversion and raw font facts only; never business qualification.

    The Worker admits the source and evaluates these facts/PDF. Host callers
    cannot select image, executable, URL, mount, profile or inspection callback.
    """
    raw: dict[str, Any] = {
        "pdf": None,
        "font_facts": None,
        "isolation": None,
        "conversion_attempted": False,
        "error_code": None,
        "source_docx_digest": digest(source) if isinstance(source, bytes) else "",
        "image_reference": IMAGE,
        "image_id": IMAGE_ID,
        "cleanup_confirmed": False,
    }
    run = None
    try:
        if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE:
            raise PrebuiltError("WORD_SOURCE_SIZE_INVALID")
        if not isinstance(requested_fonts, list) or any(
            not _valid_font_name(name) for name in requested_fonts
        ):
            raise PrebuiltError("WORD_FONT_NAME_UNSUPPORTED")
        with _Run(receipt) as run:
            identity, _ = _start(run)
            raw["font_facts"] = _font_facts(identity, requested_fonts)
            raw["conversion_attempted"] = True
            conversion = _call(
                ["exec", "-i", identity, "/bin/sh", "-c", CONVERT], data=source, timeout=50
            )
            if conversion.returncode == 72:
                raise PrebuiltError("WORD_CONVERSION_TIMEOUT")
            if conversion.returncode:
                raise PrebuiltError("WORD_PREBUILT_COMMAND_FAILED")
            status, separator, pdf = conversion.stdout.partition(b"\n")
            if status != b"200" or not separator:
                raise PrebuiltError("WORD_PREBUILT_HTTP_REJECTED")
            if not pdf.startswith(b"%PDF-") or not 0 < len(pdf) <= MAX_PDF:
                raise PrebuiltError("WORD_PDF_INVALID")
            raw["isolation"] = _isolation(identity)
            raw["pdf"] = pdf
        if not run.closed:
            raise PrebuiltError("WORD_PREBUILT_CLEANUP_UNCONFIRMED")
        raw["isolation"]["own_job_cleanup_confirmed"] = True
        raw["isolation"]["checks"]["own_job_cleanup_confirmed"] = True
    except subprocess.TimeoutExpired:
        raw["error_code"] = "WORD_CONVERSION_TIMEOUT"
    except PrebuiltError as error:
        raw["error_code"] = str(error)
    except Exception:
        raw["error_code"] = "WORD_PREBUILT_CONVERSION_FAILED"
    finally:
        raw["cleanup_confirmed"] = run is None or run.closed
        if not raw["cleanup_confirmed"]:
            raw["error_code"] = "WORD_PREBUILT_CLEANUP_UNCONFIRMED"
        if raw["error_code"] is not None:
            raw["pdf"] = None
    return raw


def _conversion_facts(source, raw):
    required = {
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
    if (
        not isinstance(raw, dict)
        or set(raw) not in (required, required | {"resource_receipt"})
        or raw["source_docx_digest"] != digest(source)
        or raw["image_reference"] != IMAGE
        or raw["image_id"] != IMAGE_ID
        or type(raw["conversion_attempted"]) is not bool
        or type(raw["cleanup_confirmed"]) is not bool
    ):
        raise PrebuiltError("WORD_PREBUILT_CONVERSION_FACTS_INVALID")
    if raw["cleanup_confirmed"] is not True:
        raise PrebuiltError("WORD_PREBUILT_CLEANUP_UNCONFIRMED")
    if "resource_receipt" in raw:
        record = raw["resource_receipt"]
        if (
            not isinstance(record, dict)
            or set(record) != {"closed", "receipts"}
            or record["closed"] is not True
            or not isinstance(record["receipts"], list)
            or not record["receipts"]
            or any(
                not isinstance(item, dict) or item.get("closed") is not True
                for item in record["receipts"]
            )
        ):
            raise PrebuiltError("WORD_PREBUILT_CLEANUP_UNCONFIRMED")
    if raw["error_code"] is not None:
        if (
            not isinstance(raw["error_code"], str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", raw["error_code"]) is None
            or raw["pdf"] is not None
        ):
            raise PrebuiltError("WORD_PREBUILT_CONVERSION_FACTS_INVALID")
        raise PrebuiltError(raw["error_code"])
    pdf, isolation = raw["pdf"], raw["isolation"]
    if (
        raw["conversion_attempted"] is not True
        or not isinstance(pdf, bytes)
        or not pdf.startswith(b"%PDF-")
        or not 0 < len(pdf) <= MAX_PDF
    ):
        raise PrebuiltError("WORD_PDF_INVALID")
    expected, expected_tmpfs = _isolation_requirements()
    expected.update(
        image_id=IMAGE_ID,
        user="65534:65534",
        cap_drop="ALL",
        no_new_privileges=True,
        tmpfs=expected_tmpfs,
        own_job_cleanup_confirmed=True,
    )
    if (
        not isinstance(isolation, dict)
        or any(isolation.get(key) != value for key, value in expected.items())
        or not isinstance(isolation.get("checks"), dict)
        or set(isolation["checks"]) != ISOLATION_CHECKS
        or any(value is not True for value in isolation["checks"].values())
    ):
        raise PrebuiltError("WORD_PREBUILT_ISOLATION_MISMATCH")
    return pdf, isolation


def inspect_pdf(data: bytes, inspection: dict, gaps: list[str]) -> tuple[int, list[str]]:
    import pypdfium2

    if not data.startswith(b"%PDF-") or not 0 < len(data) <= MAX_PDF:
        raise PrebuiltError("WORD_PDF_INVALID")
    pieces = []
    document = pypdfium2.PdfDocument(data)
    try:
        count = len(document)
        if not 0 < count <= 1000:
            raise PrebuiltError("WORD_PDF_PAGE_LIMIT")
        for index in range(count):
            page = document[index]
            textpage = page.get_textpage()
            try:
                pieces.append(textpage.get_text_bounded())
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()

    def normalize(text):
        return "".join(unicodedata.normalize("NFKC", text).split())

    output = "".join(pieces)
    if normalize("".join(inspection["paragraphs"])) != normalize(output) or any(
        c in output for c in "\ufffd\u25a1\u25a0"
    ):
        gaps.append("WORD_TEXT_CORRESPONDENCE_UNVERIFIED")
    if inspection["unsupported_layout_features"]:
        gaps.append("WORD_COMPLEX_LAYOUT_UNVERIFIED")
    if not "".join(inspection["paragraphs"]).strip():
        gaps.append("WORD_TEXT_SCOPE_EMPTY")
    return count, list(dict.fromkeys(gaps))


def _failure(source: bytes, profile: dict, code: str, attempted: bool) -> dict:
    return {
        "state": "failed",
        "coverage": "failed",
        "conversion_attempted": attempted,
        "error_code": code,
        "retryable": code in {"WORD_CONVERSION_TIMEOUT", "WORD_PREBUILT_COMMAND_FAILED"},
        "gaps": [code],
        "chain": {
            "source_docx_digest": digest(source) if isinstance(source, bytes) else None,
            "profile_digest": profile.get("profile_digest") if isinstance(profile, dict) else None,
        },
        "pdf": None,
        "protocol": PROTOCOL,
    }


def _render_generated(
    source: bytes, provider_profile: dict, *, receipt: Path, admit, inspect_pdf
) -> dict:
    """Worker-local admission and qualification around a narrow conversion port.

    No API accepts these callbacks. External DOCX always uses render() below.
    Remote execution supplies facts, never an admitted source or coverage verdict.
    """
    attempted = False
    raw = None
    try:
        validate_profile(provider_profile)
        if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE:
            raise PrebuiltError("WORD_SOURCE_SIZE_INVALID")
        prepared = admit()
        if prepared.get("proof", {}).get("source_docx_digest") != digest(source):
            raise PrebuiltError("WORD_GENERATED_SOURCE_IDENTITY_CHANGED")
        inspection = prepared["font_inspection"]
        names = [name for name in inspection["requested_fonts"] if _valid_font_name(name)]
        from packages.word_intake import execution_transport

        if execution_transport.enabled():
            raw = execution_transport.call_conversion(source, names)
        else:
            raw = convert_in_isolation(source, names, receipt=receipt)
        attempted = isinstance(raw, dict) and raw.get("conversion_attempted") is True
        pdf, isolation = _conversion_facts(source, raw)
        gaps = _font_gaps_from_facts(inspection, raw["font_facts"])
        measurements = inspect_pdf(pdf, prepared)
        if not 0 < measurements["page_count"] <= 1000:
            raise PrebuiltError("WORD_PDF_PAGE_LIMIT")
        gaps = list(dict.fromkeys([*gaps, *measurements["gaps"]]))
        outcome = {
            "state": "succeeded",
            "coverage": "partial" if gaps else "complete",
            "conversion_attempted": True,
            "error_code": None,
            "retryable": False,
            "gaps": gaps,
            "pdf": pdf,
            "protocol": PROTOCOL,
            "isolation": isolation,
            "measurements": measurements,
            "chain": {
                "source_docx_digest": digest(source),
                "pdf_digest": digest(pdf),
                "profile_digest": provider_profile["profile_digest"],
                "page_count": measurements["page_count"],
                "renderer_digest": provider_profile["identity"]["renderer_digest"],
                "fontset_digest": digest({"image": IMAGE, "policy": OPTIONS["font_policy"]}),
                "options_digest": digest(OPTIONS),
                "image_reference": IMAGE,
            },
        }
    except subprocess.TimeoutExpired:
        outcome = _failure(source, provider_profile, "WORD_CONVERSION_TIMEOUT", attempted)
    except PrebuiltError as error:
        outcome = _failure(source, provider_profile, str(error), attempted)
    except DomainError as error:
        if str(error.code).startswith("WORD_EXECUTION_"):
            raise
        outcome = _failure(source, provider_profile, "WORD_PREBUILT_CONVERSION_FAILED", attempted)
    except Exception:
        outcome = _failure(source, provider_profile, "WORD_PREBUILT_CONVERSION_FAILED", attempted)
    if isinstance(raw, dict) and "resource_receipt" in raw:
        outcome["resource_receipt"] = raw["resource_receipt"]
    return outcome


def render(source: bytes, profile: dict, *, receipt: Path) -> dict:
    from packages.word_intake.inspection import inspect_docx

    def admit():
        inspection = inspect_docx(source)
        if not inspection["conversion_eligible"]:
            raise PrebuiltError("WORD_PACKAGE_ACTIVE_CONTENT_BLOCKED")
        return {
            "proof": {"source_docx_digest": digest(source)},
            "font_inspection": inspection,
            "inspection": inspection,
        }

    def inspect_output(pdf, prepared):
        pages, gaps = inspect_pdf(pdf, prepared["inspection"], [])
        return {"page_count": pages, "gaps": gaps}

    return _render_generated(
        source, profile, receipt=receipt, admit=admit, inspect_pdf=inspect_output
    )


def capabilities() -> dict:
    return {
        "protocol": PROTOCOL,
        "image_reference": IMAGE,
        "image_id": IMAGE_ID,
        "platform": "linux/amd64",
        "old_word03_unchanged": True,
        "business_wiring": False,
        "model_calls": 0,
        "options": dict(OPTIONS),
        "formats": ["OOXML DOCX"],
        "external_fields_macros_links": "blocked_by_existing_inspection",
        "layout_qualification": "existing_complex_layout_gaps_preserved; HTTP200 is not complete",
        "fonts": "frozen image fonts only; custom runtime font installation not implemented",
        "generated_PAGE_RICH": "not connected or qualified by this candidate module",
        "native_status": "requires explicit per-platform real acceptance; unit tests do not qualify it",
        "transport": "fixed local daemon, per-document network-none container; in-image curl over loopback",
    }
