"""Exact package evidence discovery shape; no quote, latest-run or write capability."""

from copy import deepcopy
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import SCHEMAS


def page():
    return {
        "revision_id": str(uuid4()),
        "package_digest": "a" * 64,
        "items": [
            {
                "id": str(uuid4()),
                "document_version_id": str(uuid4()),
                "parse_run_id": str(uuid4()),
                "physical_page": 1,
                "part_ids": ["shared-technical", "shared-business"],
            }
        ],
        "has_more": False,
        "next_cursor": None,
    }


def validator():
    return Draft202012Validator(SCHEMAS["PackageEvidencePage"], format_checker=FormatChecker())


def test_exact_page_has_explicit_frozen_parse_and_shared_parts_without_content():
    value = page()
    validator().validate(value)
    value["items"] = []
    validator().validate(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "quote",
        "no-parse",
        "zero-page",
        "duplicate-parts",
        "empty-parts",
        "invalid-revision",
        "invalid-digest",
    ],
)
def test_malformed_or_content_bearing_page_is_not_the_discovery_contract(mutation):
    value = deepcopy(page())
    if mutation == "quote":
        value["items"][0]["quote"] = "must use explicit evidence GET"
    elif mutation == "no-parse":
        del value["items"][0]["parse_run_id"]
    elif mutation == "zero-page":
        value["items"][0]["physical_page"] = 0
    elif mutation == "duplicate-parts":
        value["items"][0]["part_ids"] = ["one", "one"]
    elif mutation == "empty-parts":
        value["items"][0]["part_ids"] = []
    elif mutation == "invalid-revision":
        value["revision_id"] = "latest"
    else:
        value["package_digest"] = "unknown"
    assert not validator().is_valid(value)


def test_actual_registered_get_contract_and_session_auth_only():
    from apps.api.main import app

    operation = app.openapi()["paths"][
        "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/evidence"
    ]
    assert set(operation) == {"get"}
    assert operation["get"]["security"] == [{"SessionCookie": []}]
    assert operation["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PackageEvidencePage"
    }
