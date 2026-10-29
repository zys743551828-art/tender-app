"""Actual loopback TCP SSE smoke; private test access remains in ignored local config."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx


def first_change(client, path, cursor=None):
    headers = {"Last-Event-ID": cursor} if cursor is not None else {}
    with client.stream("GET", path, headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        identity = None
        for line in response.iter_lines():
            if line.startswith("id: "):
                identity = line[4:]
            if line.startswith("data: "):
                assert identity is not None
                return identity, json.loads(line[6:])
    raise AssertionError("No actual stream change delivered")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", type=Path, default=Path(".local/external-test-members.json"))
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    assert not options.members.stat().st_mode & 0o077
    account = json.loads(options.members.read_text())[0]
    origin = "http://127.0.0.1:5175"
    # Literal verified loopback destination; never send local session tokens through an HTTP proxy.
    with httpx.Client(base_url="http://127.0.0.1:8802", trust_env=False, timeout=20) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"login_name": account["login"], "password": account["password"]},
            headers={"Origin": origin},
        )
        assert login.status_code == 200
        headers = {
            "Origin": origin,
            "X-CSRF-Token": login.json()["csrf_token"],
            "Idempotency-Key": str(uuid4()),
        }
        bid = client.post("/api/v1/bids", json={"title": "SSE真实TCP开发验证"}, headers=headers)
        assert bid.status_code == 201
        project = bid.json()
        path = f"/api/v1/streams/{project['stream_id']}/events"
        first_id, first = first_change(client, path)
        assert first["event_type"] == "bid.created" and first["object_ref"]["id"] == project["id"]
        settings_path = f"/api/v1/bids/{project['id']}/settings"
        settings = client.get(settings_path)
        headers |= {"Idempotency-Key": str(uuid4()), "If-Match": settings.headers["etag"]}
        changed = client.patch(settings_path, json={"show_prediction": False}, headers=headers)
        assert changed.status_code == 200
        second_id, second = first_change(client, path, first_id)
        assert second_id != first_id and second["seq"] == first["seq"] + 1
        assert second["event_type"] == "settings.updated"
        assert set(second) == {"stream_id", "seq", "event_type", "object_ref", "revision"}
        invalid = client.get(path, headers={"Last-Event-ID": f"{project['stream_id']}:999999"})
        assert invalid.status_code == 410 and invalid.json()["code"] == "RESET_REQUIRED"
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get(path).status_code == 401
    report = {
        "passed": True,
        "scope": "Actual loopback8802 TCP/session/SSE reconnect; developer smoke, independent QA pending",
        "created_project_id": project["id"],
        "received_event_types": [first["event_type"], second["event_type"]],
        "resume_without_duplicate": True,
        "invalid_cursor_410": True,
        "logout_401": True,
        "payload_allowlist_only": True,
        "paid_model_calls": 0,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        {
            k: report[k]
            for k in (
                "passed",
                "resume_without_duplicate",
                "invalid_cursor_410",
                "logout_401",
                "paid_model_calls",
            )
        }
    )


if __name__ == "__main__":
    main()
