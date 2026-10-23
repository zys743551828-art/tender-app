"""A frozen font hash must bind the actual converter font set, not merely a path."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from packages.authoring import build
from packages.domain.runtime import sha


def test_fontconfig_is_private_and_includes_only_frozen_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("FONTCONFIG_FILE", "/untrusted/inherited-fonts.conf")
    monkeypatch.setenv("API_DATABASE_DSN", "synthetic-do-not-pass")
    monkeypatch.setenv("OBJECT_STORE_SECRET_KEY", "synthetic-do-not-pass")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-do-not-pass")
    raw = b"explicit synthetic font used only to inspect wiring"
    environment = build.isolated_font_environment(tmp_path, raw, ".otf")
    config = Path(environment["FONTCONFIG_FILE"])
    tree = ET.fromstring(config.read_bytes())
    assert tree.find("reset-dirs") is not None
    assert len(tree.findall("dir")) == 1 and not tree.findall("include")
    fonts = Path(tree.findtext("dir"))
    assert [file.name for file in fonts.iterdir()] == ["frozen.otf"]
    assert (fonts / "frozen.otf").read_bytes() == raw
    assert config.stat().st_mode & 0o077 == 0
    assert not any(
        environment.get(key)
        for key in ("API_DATABASE_DSN", "OBJECT_STORE_SECRET_KEY", "DEEPSEEK_API_KEY")
    )
    assert environment["FONTCONFIG_PATH"] == str(tmp_path)


def test_font_changed_after_probe_cannot_render_under_old_profile(tmp_path, monkeypatch):
    font = tmp_path / "font.ttf"
    original = b"synthetic first font"
    font.write_bytes(original)
    identity = {
        "fontset_digest": sha(original),
        "renderer_digest": sha("renderer"),
        "renderer_version": "synthetic",
        "options_digest": build.TEMPLATE_DIGEST,
    }

    def changed(*args):
        font.write_bytes(b"synthetic second font")
        return identity

    monkeypatch.setattr(build, "render_identity", changed)
    monkeypatch.setattr(
        build.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("changed font must not reach converter"),
    )
    result = build.render_pdf(
        b"unused synthetic docx",
        executable="synthetic",
        font_path=str(font),
        expected_identity=identity,
    )
    assert result.state == "failed" and result.pdf is None
    assert "RENDER_PROFILE_CHANGED" in result.gaps


def test_converter_receives_captured_font_bytes_even_if_original_changes(tmp_path, monkeypatch):
    font = tmp_path / "font.otf"
    original = b"synthetic frozen font"
    font.write_bytes(original)
    identity = {
        "fontset_digest": sha(original),
        "renderer_digest": sha("renderer"),
        "renderer_version": "synthetic",
        "options_digest": build.TEMPLATE_DIGEST,
    }
    monkeypatch.setattr(build, "render_identity", lambda *args: identity)
    observations = []

    class InspectProcess:
        def __init__(self, *args, env, cwd, **kwargs):
            font.write_bytes(b"later changed source font")
            tree = ET.fromstring(Path(env["FONTCONFIG_FILE"]).read_bytes())
            frozen = Path(tree.findtext("dir")) / "frozen.otf"
            observations.append(frozen.read_bytes())
            self.returncode = 0
            # Explicit malformed output preserves the ordinary conversion failure path.
            (Path(cwd) / "body.pdf").write_bytes(b"%PDF-1.7\ntruncated\n")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def communicate(self, **kwargs):
            return b"", b""

    monkeypatch.setattr(build.subprocess, "Popen", InspectProcess)
    result = build.render_pdf(
        b"synthetic docx", executable="synthetic", font_path=str(font), expected_identity=identity
    )
    assert observations == [original]
    assert result.pdf is None and "PDF_INVALID" in result.gaps
