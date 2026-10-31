"""Opt-in privilege regression against a disposable, empty local PostgreSQL database."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest

DSN = os.environ.get("WORD_RECEIPT_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires isolated word_receipt_test database")


def test_worker_receipt_view_scope_and_denials():
    assert DSN
    target = urlsplit(DSN)
    assert target.hostname == "127.0.0.1" and target.path == "/word_receipt_test"
    with psycopg.connect(DSN) as connection:
        assert connection.execute("SELECT current_database()").fetchone() == ("word_receipt_test",)
        assert not connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='design')"
        ).fetchone()[0]
        assert not connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('tender_api','tender_worker'))"
        ).fetchone()[0]
        connection.execute("CREATE ROLE tender_api NOLOGIN")
        connection.execute("CREATE ROLE tender_worker NOLOGIN")
        connection.execute("CREATE SCHEMA design")
        connection.execute("GRANT USAGE ON SCHEMA design TO tender_api,tender_worker")
        connection.execute(
            "CREATE TABLE design.commands(id uuid,actor_id uuid,command_kind text,"
            "target_id uuid,request_digest text,response jsonb)"
        )
        connection.execute(
            "CREATE TABLE design.audit_entries(command_id uuid,actor_id uuid,event_type text,payload jsonb)"
        )
        source = (
            Path(__file__).resolve().parents[1] / "deploy/sql/word-adoption-command-receipts.sql"
        )
        statements = source.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
        connection.execute(statements)
        connection.execute(
            """INSERT INTO design.commands VALUES
            ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',
             'adopt_word_render','00000000-0000-0000-0000-000000000003','digest',
             '{"body":{"state":"adopted"},"private":"hidden"}'),
            ('00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000002',
             'other_command','00000000-0000-0000-0000-000000000003','digest','{"body":{}}')"""
        )
        connection.execute(
            """INSERT INTO design.audit_entries VALUES
            ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',
             'word.material_adoption_recorded',
             '{"state":"adopted","source_document_version_id":"00000000-0000-0000-0000-000000000003"}')"""
        )
        connection.execute("SET LOCAL ROLE tender_worker")
        assert connection.execute(
            "SELECT response FROM design.word_adoption_command_receipts"
        ).fetchall() == [({"body": {"state": "adopted"}},)]
        for query in (
            "SELECT * FROM design.commands",
            "DELETE FROM design.word_adoption_command_receipts",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(query)
        connection.execute("RESET ROLE")
        connection.execute(
            "UPDATE design.audit_entries SET actor_id='00000000-0000-0000-0000-000000000005'"
        )
        connection.execute("SET LOCAL ROLE tender_worker")
        assert connection.execute(
            "SELECT count(*) FROM design.word_adoption_command_receipts"
        ).fetchone() == (0,)
        connection.rollback()
