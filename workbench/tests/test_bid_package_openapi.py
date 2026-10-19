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
