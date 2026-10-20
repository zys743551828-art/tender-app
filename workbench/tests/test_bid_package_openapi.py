"""Actual package contracts follow the registered router, including partial apps."""

from fastapi import FastAPI

from apps.api.bid_package_requirement_routes import router as requirements_router
from apps.api.bid_package_routes import discovery_router, router
from apps.api.export_openapi import implemented_openapi


def test_app_without_package_router_does_not_publish_package_operations():
    actual = implemented_openapi(FastAPI())
    assert actual["paths"] == {}
    assert "CreateBidPackage" not in actual["components"]["schemas"]
    assert "CreatePackageRequirementInventory" not in actual["components"]["schemas"]


def test_requirements_only_app_does_not_require_unregistered_package_routes():
    app = FastAPI()
    app.include_router(requirements_router)
    actual = implemented_openapi(app)
    operations = {
        operation["operationId"]
        for methods in actual["paths"].values()
        for operation in methods.values()
    }
    assert operations == {
        "createPackageRequirementInventory",
        "listPackageRequirementInventories",
        "getPackageRequirementInventory",
        "createPackageCoverageAttempt",
        "listPackageCoverageAttempts",
        "getPackageCoverageAttempt",
        "previewPackageReviewInput",
        "verifyPackageReviewOriginals",
        "freezePackageReviewInput",
        "getFrozenPackageReviewInput",
        "checkFrozenPackageReviewEligibility",
        "savePackageExecutionInput",
        "getPackageExecutionInput",
        "checkPackageExecutionFacts",
        "changePackageFactScope",
        "getPackageFactScope",
        "getPackageFactScopeObservation",
        "listPackagePreparedFacts",
        "listFrozenPackageReviewInputs",
        "confirmPackageFact",
        "withdrawPackageFact",
        "getPackageFactChange",
        "listPackageCurrentFacts",
        "getPackageCurrentFact",
    }


def test_package_only_app_exports_all_registered_operations_and_schemas():
    app = FastAPI()
    app.include_router(router)
    app.include_router(discovery_router)
    actual = implemented_openapi(app)
    operations = {
        operation["operationId"]
        for methods in actual["paths"].values()
        for operation in methods.values()
    }
    assert operations == {
        "createBidPackage",
        "appendBidPackageRevision",
        "getBidPackageHead",
        "getBidPackageRevision",
        "getBidPackageManifest",
        "listBidPackages",
        "listBidPackageRevisions",
        "listBidPackageDocuments",
        "listBidPackageParses",
        "listBidPackageFrozenEvidence",
    }
    base = "/api/v1/bids/{bid_id}/packages"
    for path, request_schema in (
        (base, "CreateBidPackage"),
        (base + "/{package_id}/revisions", "AppendBidPackage"),
    ):
        operation = actual["paths"][path]["post"]
        assert operation["requestBody"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/" + request_schema
        }
        assert request_schema in actual["components"]["schemas"]
        assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/BidPackageStoredView"
        }


def test_current_fact_and_change_operations_publish_exact_auth_and_request_contracts():
    app = FastAPI()
    app.include_router(requirements_router)
    actual = implemented_openapi(app)
    base = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories/{inventory_id}/frozen-review-inputs/{input_id}"
    for suffix, name in (
        ("/fact-confirmations", "ConfirmPackageFact"),
        ("/fact-withdrawals", "WithdrawPackageFact"),
    ):
        op = actual["paths"][base + suffix]["post"]
        assert op["security"] == [{"SessionCookie": []}]
        assert op["requestBody"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/" + name
        }
        assert op["responses"]["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/PackageFactChangeView"
        }
        assert {
            p["name"] for p in op["parameters"] if p.get("in") == "header" and p.get("required")
        } == {"Origin", "X-CSRF-Token", "Idempotency-Key"}
    for suffix in ("/fact-context", "/facts/{fact_id}", "/fact-changes/{command_id}"):
        op = actual["paths"][base + suffix]["get"]
        assert op["security"] == [{"SessionCookie": []}] and "200" in op["responses"]
        assert not any(p.get("in") == "header" and p.get("required") for p in op["parameters"])
        if suffix != "/fact-changes/{command_id}":
            assert any(
                p.get("in") == "query" and p["name"] == "frozen_digest" and p["required"]
                for p in op["parameters"]
            )
