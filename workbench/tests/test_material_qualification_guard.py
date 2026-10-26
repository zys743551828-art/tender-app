"""Catalog tampering rejects the optional path before independent native I/O."""

from copy import deepcopy

import pytest

from packages.domain.errors import DomainError
from packages.model_governance import material_qualification_guard as guard


def catalog():
    row = {
        "prosrc": guard.SQL.read_text().split("$qualification_enforce$")[1],
        "prosecdef": True,
        "provolatile": "v",
        "proconfig": [
            "search_path=pg_catalog, material_qualification, design, pg_temp",
            "TimeZone=UTC",
        ],
        "proowner": 42,
        "native_owner": 42,
        "lanname": "plpgsql",
        "returns": "trigger",
        "caller_owner": False,
        "caller_execute": False,
    }
    triggers = [
        {
            "nspname": schema,
            "relname": table,
            "tgname": name,
            "tgtype": kind,
            "tgenabled": "O",
            "tgqual": None,
            "tgnargs": 0,
            "relowner": 42,
            "proowner": 42,
        }
        for schema, table, name, kind in (
            ("material_judgment_job", "jobs", "qualified_material_job", 5),
            ("material_execution", "attempts", "qualified_material_attempt", 7),
        )
    ]
    return row, triggers


def audit(row, triggers):
    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return deepcopy(self.value)

        def fetchall(self):
            return deepcopy(self.value)

    class Connection:
        def execute(self, sql, params=None):
            return Result(
                triggers
                if "FROM pg_trigger" in sql
                else [{"relowner": 42, "nspowner": 42}] * 5
                if "FROM pg_class" in sql
                else row
            )

    guard.audit(Connection())


def test_exact_boundary():
    audit(*catalog())


@pytest.mark.parametrize(
    "field,value",
    [
        ("prosrc", "RETURN NEW;"),
        ("caller_execute", True),
        ("caller_owner", True),
        ("proowner", 43),
        ("proconfig", []),
        ("prosecdef", False),
    ],
)
def test_changed_function(field, value):
    row, triggers = catalog()
    row[field] = value
    with pytest.raises(DomainError):
        audit(row, triggers)


@pytest.mark.parametrize(
    "field,value", [("tgenabled", "D"), ("tgqual", "conditional"), ("tgtype", 7), ("relowner", 43)]
)
def test_missing_or_weakened_trigger(field, value):
    row, triggers = catalog()
    triggers[0][field] = value
    with pytest.raises(DomainError):
        audit(row, triggers)
