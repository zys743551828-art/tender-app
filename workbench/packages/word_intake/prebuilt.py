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
from pathlib import Path
from typing import Any

from deploy.disposable_docker import DockerTestRun

PROTOCOL = "word-prebuilt-gotenberg/1"
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


def _isolation(identity: str) -> dict:
    value = json.loads(_successful(["container", "inspect", identity]))[0]
    host = value["HostConfig"]
    expected_environment = dict(item.split("=", 1) for item in _image()["Config"].get("Env", []))
    # These paths refer to the inspected private container tmpfs.
    expected_environment.update(HOME="/tmp", TMPDIR="/tmp", LANG="C.UTF-8")  # nosec B108
    actual_environment = dict(item.split("=", 1) for item in value["Config"].get("Env", []))
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
    return {
        "protocol": PROTOCOL,
        "image_reference": IMAGE,
        "image_id": IMAGE_ID,
        "platform": "linux/amd64",
        "options": dict(OPTIONS),
        "adapter_source_digest": adapter,
        "renderer_digest": digest({"image": IMAGE, "adapter": adapter}),
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


def _font_gaps(identity: str, inspection: dict) -> list[str]:
    gaps = []
    for name in inspection["requested_fonts"]:
        if not re.fullmatch(r"[\w ,.-]{1,128}", name) or name.startswith("-"):
            gaps.append("WORD_FONT_NAME_UNSUPPORTED")
            continue
        families = _successful(
            ["exec", identity, "fc-match", "--format=%{family}", "--", name]
        ).decode("utf-8")
        if name.casefold() not in {part.strip().casefold() for part in families.split(",")}:
            gaps.append("WORD_FONT_SUBSTITUTED")
    charset = _successful(["exec", identity, "fc-match", "-s", "--format=%{charset}\\n"]).decode(
        "ascii"
    )
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
                pieces.append(textpage.get_text_range())
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
    """Internal port for fixed generators after their own immutable-source proof.

    No API accepts these callbacks. External DOCX always uses render() below.
    """
    attempted = False
    try:
        validate_profile(provider_profile)
        if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE:
            raise PrebuiltError("WORD_SOURCE_SIZE_INVALID")
        prepared = admit()
        if prepared.get("proof", {}).get("source_docx_digest") != digest(source):
            raise PrebuiltError("WORD_GENERATED_SOURCE_IDENTITY_CHANGED")
        with _Run(receipt) as run:
            identity, isolation = _start(run)
            gaps = _font_gaps(identity, prepared["font_inspection"])
            attempted = True
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
            isolation = _isolation(identity)
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
                    "renderer_digest": digest(
                        {
                            "image": IMAGE,
                            "adapter": provider_profile["identity"]["adapter_source_digest"],
                        }
                    ),
                    "fontset_digest": digest({"image": IMAGE, "policy": OPTIONS["font_policy"]}),
                    "options_digest": digest(OPTIONS),
                    "image_reference": IMAGE,
                },
            }
        if not run.closed:
            raise PrebuiltError("WORD_PREBUILT_CLEANUP_UNCONFIRMED")
        outcome["isolation"]["own_job_cleanup_confirmed"] = True
        outcome["isolation"].setdefault("checks", {})["own_job_cleanup_confirmed"] = True
        return outcome
    except subprocess.TimeoutExpired:
        return _failure(source, provider_profile, "WORD_CONVERSION_TIMEOUT", attempted)
    except PrebuiltError as error:
        return _failure(source, provider_profile, str(error), attempted)
    except Exception:
        return _failure(source, provider_profile, "WORD_PREBUILT_CONVERSION_FAILED", attempted)


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
