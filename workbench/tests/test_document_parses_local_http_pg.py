"""Opt-in real loopback parser HTTP + nonowner PG + ordinary Worker publication.

Uses real local OCR assets and synthetic PDFs. Object storage is an explicitly
in-memory fixture; Kafka transport and business document quality are not tested.
Run serially with FUSION_REAL_LOCAL_PARSER=1 and FUSION_REQUIREMENTS_ADMIN_DSN.
"""
# ruff: noqa: F401,F811

import copy
import io
import os
import secrets
import socket
import subprocess  # nosec B404
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import CheckViolation
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from test_authoring_package_adoptions_pg import database, env
from test_bid_package_api import attach
from test_document_parses_pg import assert_unchanged_heads, request, task

from apps.worker import document_parse_handlers as handler
from apps.worker import engine
from packages.contracts.document_parses_api import validate
from packages.domain import document_parses as service
from packages.domain.runtime import DomainError, connection, sha
from packages.parsing.http_port import ParsingHttp

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_REAL_LOCAL_PARSER") != "1"
    or not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires explicit isolated loopback parser/OCR/PG technical fixture",
)


@pytest.fixture(scope="module", autouse=True)
def local_parser_server(tmp_path_factory):
    """Starts only the existing local parser CLI; secrets never enter argv/logs."""
    admin = conninfo_to_dict(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"])
    assert admin.get("host") == "127.0.0.1" and admin.get("dbname") == "postgres"
    assets = Path(os.environ.get("PARSING_ASSET_DIRECTORY", ROOT / ".local/parsing-models"))
    assert assets.is_dir(), "explicit locally installed OCR assets are required"
    directory = tmp_path_factory.mktemp("document-parse-local-http")
    directory.chmod(0o700)
    token = secrets.token_urlsafe(48)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "WORKBENCH_ENV_FILE": "explicit-local-parser-no-business-profile",
        "PARSING_RUNTIME_TOKEN": token,
        "PARSING_ASSET_DIRECTORY": str(assets.resolve()),
        "OMP_THREAD_LIMIT": "2",
        "OPENBLAS_NUM_THREADS": "1",
    }
    log_path = directory / "server.log"
    log_path.touch(mode=0o600)
    with log_path.open("wb") as log:
        # Fixed module and loopback port; only the private, explicit env is inherited.
        process = subprocess.Popen(  # nosec B603
            [sys.executable, "-m", "packages.parsing.server", "--port", str(port)],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 45
            with httpx.Client(timeout=1, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        pytest.fail(
                            "local parser exited before readiness; inspect private server log"
                        )
                    try:
                        response = client.get(
                            url + "/identity", headers={"Authorization": "Bearer " + token}
                        )
                    except httpx.HTTPError:
                        time.sleep(0.1)
                        continue
                    if response.status_code == 200:
                        metadata = response.json()
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail("local parser did not become ready within 45 seconds")
                assert client.get(url + "/identity").status_code == 401
            assert metadata["identity"]["profile"] == "pdfium-pdfplumber-tesseract-cpu-v1"
            assert metadata["identity"]["visual_understanding"] is False
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("PARSING_RUNTIME_URL", url)
                patch.setenv("PARSING_RUNTIME_TOKEN", token)
                patch.setenv("WORKBENCH_ENV_FILE", "explicit-local-parser-no-business-profile")
                patch.delenv("DEEPSEEK_API_KEY", raising=False)
                yield metadata
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def synthetic_pdf(kind):
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=(420, 595))
    if kind in {"text", "heading"}:
        title = "1. Project requirements" if kind == "heading" else "Project requirements"
        page.drawString(30, 550, title)
        page.drawString(30, 520, "Project duration 120 days")
        page.showPage()
        page.setPageRotation(90)
        page.drawString(30, 250, "Rotated physical page")
    elif kind in {"table", "numbered_table"}:
        for x in (30, 180, 330):
            page.line(x, 400, x, 500)
        for y in (400, 450, 500):
            page.line(30, y, 330, y)
        for x, y, text in (
            (40, 470, "1. Item" if kind == "numbered_table" else "Item"),
            (190, 470, "Days"),
            (40, 420, "Road"),
            (190, 420, "120"),
        ):
            page.drawString(x, y, text)
    elif kind == "diagram":
        page.drawString(30, 550, "Construction diagram")
        page.circle(200, 200, 70)
        page.line(50, 200, 350, 200)
    elif kind == "scan":
        image = Image.new("RGB", (1400, 1800), "white")
        painter = ImageDraw.Draw(image)
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
        painter.text((100, 160), "Project duration 120 days", font=font, fill="black")
        painter.text((100, 280), "Quality requirements", font=font, fill="black")
        page.drawImage(ImageReader(image), 0, 0, width=420, height=595)
        image.close()
    else:
        raise AssertionError("unknown synthetic PDF kind")
    page.save()
    return output.getvalue() + f"\n% isolated synthetic PDF {uuid4()}\n".encode()


def attach_original(fixture, raw):
    document, blob = uuid4(), uuid4()
    key = f"explicit-local-parser/{blob}"
    with fixture["database"]["owner"].transaction():
        owner = fixture["database"]["owner"]
        owner.execute("SET LOCAL search_path TO design,public")
        owner.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
            (blob, sha(raw), key, len(raw)),
        )
        owner.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic local parser.pdf',now(),'bid_body',%s)",
            (document, fixture["bid"], blob, fixture["actor"]),
        )
        attach(
            owner,
            str(fixture["bid"]),
            str(fixture["actor"]),
            SimpleNamespace(document_version_id=str(document), file_digest=sha(raw)),
        )
    fixture["objects"][key] = raw
    return fixture | {"document": document, "object_key": key}


@pytest.mark.parametrize("kind", ["text", "table", "diagram", "scan", "heading", "numbered_table"])
def test_actual_configured_http_result_is_published_exactly_and_closed(
    env, local_parser_server, monkeypatch, kind
):
    fixture = attach_original(env, synthetic_pdf(kind))
    active, responses = {"count": 0}, []

    @contextmanager
    def observed_connection(*args, **kwargs):
        with connection(*args, **kwargs) as current:
            active["count"] += 1
            try:
                yield current
            finally:
                active["count"] -= 1

    real_call = ParsingHttp._call

    def actual_http(self, method, path, data=None):
        assert active["count"] == 0, "parser HTTP must happen after closing DB transactions"
        result = real_call(self, method, path, data)
        if path == "/parse":
            responses.append(copy.deepcopy(result))
        return result

    monkeypatch.setattr(service, "connection", observed_connection)
    monkeypatch.setattr(handler, "connection", observed_connection)
    monkeypatch.setattr(ParsingHttp, "_call", actual_http)
    ack, _ = request(fixture)
    method = ack["request"]["context"]["method"]
    assert method["mode"] == "configured_local"
    assert method["parser_digest"] == local_parser_server["parser_digest"]
    message = task(ack)
    lease = engine.acquire(message)
    assert lease is not None
    try:
        outcome = engine.run_compute(message, lease)
    except DomainError as error:
        if responses:
            kinds = [block["kind"] for page in responses[-1]["pages"] for block in page["blocks"]]
            error.add_note(
                f"Actual local HTTP coverage={responses[-1]['coverage']}; block kinds={kinds}"
            )
        raise
    assert len(responses) == 1
    raw = responses[0]
    expected = "partial" if kind in {"diagram", "scan"} else "complete"
    assert raw["coverage"] == ("usable" if expected == "complete" else "partial")
    assert raw["quality_benchmark"] == "not_business_validated"
    assert raw["coordinate_system"] == "rotated_page_top_left_points"
    assert engine.finish(message, lease, outcome)
    result = service.read(fixture["bid"], fixture["document"], ack["request"]["id"])
    validate("DocumentParseView", result)
    assert result["operation"]["state"] == "succeeded"
    assert result["result"]["coverage"] == expected
    assert result["result"]["word_coverage_claimed"] is False
    assert result["result"]["source_digest"] == raw["source_digest"]
    assert result["result"]["config_digest"] == raw["config_digest"]
    parse = result["result"]["parse_run_id"]
    with connection(True) as current:
        saved_pages = current.execute(
            "SELECT physical_page,width,height,rotation,quality,gaps FROM pages WHERE parse_id=%s ORDER BY physical_page",
            (parse,),
        ).fetchall()
        saved_blocks = current.execute(
            "SELECT physical_page,ordinal,kind,text_content,digest,bbox,structure FROM evidence_blocks WHERE parse_id=%s ORDER BY physical_page,ordinal",
            (parse,),
        ).fetchall()
        assert (
            current.execute(
                "SELECT count(*) AS n FROM model_calls WHERE operation_id=%s",
                (message["operation_id"],),
            ).fetchone()["n"]
            == 0
        )
    assert len(saved_pages) == raw["page_count"] == result["result"]["page_count"]
    for saved, original in zip(saved_pages, raw["pages"], strict=True):
        assert dict(saved) == {
            name: original[name]
            for name in ("physical_page", "width", "height", "rotation", "quality", "gaps")
        }
    originals = [block for page in raw["pages"] for block in page["blocks"]]
    assert len(saved_blocks) == len(originals) == result["result"]["evidence_count"]
    for saved, original in zip(saved_blocks, originals, strict=True):
        for name in ("physical_page", "ordinal", "text_content", "digest", "bbox"):
            assert saved[name] == original[name]
        assert saved["kind"] == original["kind"]
        for name in ("method", "chapter_path", "confidence"):
            assert saved["structure"][name] == original[name]
    if kind in {"table", "numbered_table"}:
        table = next(block for block in saved_blocks if block["kind"] == "table")
        assert table["structure"]["tables"] == raw["pages"][0]["tables"]
        first = "1. Item" if kind == "numbered_table" else "Item"
        assert table["structure"]["tables"][0]["rows"] == [[first, "Days"], ["Road", "120"]]
        assert len(table["structure"]["tables"][0]["cells"]) == 4
    elif kind == "diagram":
        assert "VECTOR_GRAPHICS_NOT_UNDERSTOOD" in raw["pages"][0]["gaps"]
    elif kind == "scan":
        assert raw["pages"][0]["method"] == "tesseract_ocr"
        assert "120" in raw["pages"][0]["text"]
        assert "SCAN_LAYOUT_TABLES_AND_VISUALS_UNVERIFIED" in raw["pages"][0]["gaps"]
    elif kind == "heading":
        assert originals[0]["kind"] == "text"
        assert raw["chapters"][0]["inferred"] is True
        assert saved_blocks[0]["structure"]["chapter_path"] == ["1. Project requirements"]
    with pytest.raises(CheckViolation, match="document_parse_output_closed"), connection(True) as c:
        c.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,%s,420,595,0,'usable','[]')",
            (fixture["bid"], parse, len(saved_pages) + 1),
        )
    assert (
        service.read(fixture["bid"], fixture["document"], ack["request"]["id"])["result"]
        == result["result"]
    )
    assert_unchanged_heads(fixture)
