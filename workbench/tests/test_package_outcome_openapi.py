"""Package outcome/submission dependencies follow real mounted operations."""

from copy import deepcopy

import pytest
from fastapi import FastAPI

from apps.api.bid_package_submission_routes import BASE
from apps.api.bid_package_submission_routes import router as package_router
from apps.api.export_openapi import implemented_openapi
from apps.api.research_routes import router as research_router
from apps.api.submission_routes import router as submission_router
from packages.contracts.openapi_dependencies import schema_closure, schema_references


def partial(*selections):
    app = FastAPI()
    for router, path, method in selections:
        routes = [
            route
            for route in router.routes
            if route.path == path and method.upper() in route.methods
        ]
        assert len(routes) == 1
        app.router.routes.extend(routes)
    return implemented_openapi(app)


def assert_references_resolve(actual, value=None):
    """Walk reachable references, including response/parameter components."""
    pending = [actual if value is None else value]
    seen = set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            reference = item.get("$ref")
            if reference is not None and reference not in seen:
                assert reference.startswith("#/")
                seen.add(reference)
                target = actual
                for part in reference[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                pending.append(target)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def test_empty_app_registers_neither_new_package_feature_catalog():
    actual = implemented_openapi(FastAPI())
    assert actual["paths"] == {}
    schemas = actual["components"]["schemas"]
    assert (
        not {
            "CreateBidPackage",
            "CreatePackageRequirementInventory",
            "PackageOutcomeContext",
            "PackageOutcomeVerificationRequest",
            "PackageSubmissionRequest",
            "PackageSubmissionView",
        }
        & schemas.keys()
    )
    assert "x-research-runtime" not in actual


@pytest.mark.parametrize(
    ("path", "method", "expected", "absent"),
    [
        (
            "/api/v1/research/capabilities",
            "get",
            {"ResearchCapabilities"},
            {"PackageOutcomeContext", "PackageOutcomeVerificationRequest"},
        ),
        (
            "/api/v1/bids/{bid_id}/outcome-context",
            "get",
            {"ResearchOutcomeContext", "PackageOutcomeContext", "PackageSubmissionBindingView"},
            {"PackageOutcomeVerificationRequest", "ResearchDatasetRequest"},
        ),
        (
            "/api/v1/outcomes/{outcome_id}/verification",
            "post",
            {
                "ResearchOutcomeVerification",
                "PackageOutcomeVerificationRequest",
                "PackageOutcomeVerificationDetails",
            },
            {"PackageOutcomeContext", "PackageSubmissionBindingView", "ResearchDatasetRequest"},
        ),
    ],
)
def test_partial_research_routes_publish_only_their_dependencies(path, method, expected, absent):
    actual = partial((research_router, path, method))
    assert set(actual["paths"]) == {path}
    schemas = actual["components"]["schemas"]
    assert expected <= schemas.keys()
    assert not absent & schemas.keys()
    assert (
        not {
            "CreateBidPackage",
            "CreatePackageRequirementInventory",
            "PackageSubmissionRequest",
            "PackageSubmissionAppliedView",
        }
        & schemas.keys()
    )
    assert_references_resolve(actual, actual["paths"])


@pytest.mark.parametrize(
    "path", ["/api/v1/submissions/{submission_id}", "/api/v1/bids/{bid_id}/submissions"]
)
def test_shared_submission_get_alone_resolves_package_subject_without_write_catalog(path):
    actual = partial((submission_router, path, "get"))
    schemas = actual["components"]["schemas"]
    assert {"PackageSubmissionView", "PackageSubmissionBindingView"} <= schemas.keys()
    assert schemas["PackageSubmissionView"]["properties"]["body_version_id"] == {"type": "null"}
    assert (
        not {
            "CreateBidPackage",
            "CreatePackageRequirementInventory",
            "PackageSubmissionRequest",
            "PackageSubmissionAppliedView",
            "PackageOutcomeContext",
        }
        & schemas.keys()
    )
    assert_references_resolve(actual)


def test_package_preview_alone_has_no_unmounted_write_request_or_ack():
    actual = partial((package_router, BASE + "/submission-preview", "post"))
    schemas = actual["components"]["schemas"]
    assert {"PackageSubmissionSelection", "PackageSubmissionPreview"} <= schemas.keys()
    assert (
        not {
            "CreateBidPackage",
            "CreatePackageRequirementInventory",
            "PackageSubmissionRequest",
            "PackageSubmissionAppliedView",
            "PackageOutcomeContext",
        }
        & schemas.keys()
    )
    assert_references_resolve(actual, actual["paths"])


def test_route_registration_order_does_not_change_dependency_publication():
    selected = (
        (submission_router, "/api/v1/submissions/{submission_id}", "get"),
        (research_router, "/api/v1/bids/{bid_id}/outcome-context", "get"),
        (package_router, BASE + "/submission-preview", "post"),
    )
    forward, reverse = partial(*selected), partial(*reversed(selected))
    assert forward == reverse
    assert_references_resolve(forward)


def test_complete_app_schema_references_remain_closed():
    from apps.api.main import app

    assert_references_resolve(implemented_openapi(app))


def test_dependency_closure_handles_cycles_without_mutating_the_catalog():
    catalog = {
        "First": {"$ref": "#/components/schemas/Second/properties/value"},
        "Second": {"properties": {"value": {"$ref": "#/components/schemas/First"}}},
        "Unrelated": {"type": "string"},
    }
    before = deepcopy(catalog)
    closed = schema_closure(catalog, schema_references({"$ref": "#/components/schemas/First"}))
    assert set(closed) == {"First", "Second"}
    closed["Second"]["properties"]["value"] = {}
    assert catalog == before
    with pytest.raises(ValueError, match="missing: Absent"):
        schema_closure(catalog, ["Absent"])
