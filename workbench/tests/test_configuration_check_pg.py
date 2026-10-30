"""Opt-in real launcher/PG smoke; only an explicitly disposable nonowner database."""

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

import pytest

DSN = os.environ.get("CONFIGURATION_CHECK_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN, reason="requires isolated configuration_check PostgreSQL LOGIN"
)


def test_launcher_opens_real_database_as_selected_nonowner(tmp_path):
    assert DSN
    target = urlsplit(DSN)
    assert target.hostname == "127.0.0.1" and target.path == "/configuration_check"
    path = tmp_path / "smoke.env"
    path.write_text("API_DATABASE_DSN=" + DSN + "\nOWNER_DATABASE_DSN=synthetic-forbidden\n")
    path.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "deploy/run.py",
            "--env-file",
            str(path),
            "--role",
            "api",
            "--",
            sys.executable,
            "-c",
            "import os,json,psycopg;assert 'OWNER_DATABASE_DSN' not in os.environ;"
            "c=psycopg.connect(os.environ['API_DATABASE_DSN']);"
            "r=c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone();"
            "assert r == (False,False,False);"
            "assert c.execute('SELECT datdba <> (SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_database WHERE datname=current_database()').fetchone() == (True,);"
            "c.close();print(json.dumps({'passed':True,'nonowner':True}))",
        ],
        env={"PATH": os.defpath},
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, (
        "launcher/isolated database smoke failed; private details suppressed"
    )
    assert json.loads(result.stdout) == {"passed": True, "nonowner": True}
