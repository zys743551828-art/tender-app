"""实际报价契约闭包及边界，防止把目标未实现路径当成actual。"""

import pytest
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from apps.api.package_pricing_routes import router as package_router
from apps.api.pricing_routes import router
from packages.pricing.contracts import extend_openapi
from packages.pricing.models import RegisterFormula
from packages.pricing.package_models import PackagePricingBinding, RegisterPackageFormula


def actual_contract():
    app = FastAPI()
    app.include_router(router)
    actual = app.openapi()
    actual.setdefault("components", {}).setdefault("schemas", {})
    return extend_openapi(actual)


def validate(name, value):
    actual = actual_contract()
    Draft202012Validator(
        {"$ref": "#/components/schemas/" + name, "components": actual["components"]}
    ).validate(value)


def test_actual_pricing_contract_is_closed_and_only_extends_registered_operations():
    actual = actual_contract()
    operations = [
        operation
        for path in actual["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len(operations) == 10
    assert actual["components"]["schemas"]["PricingSimulationView"]["properties"]["price_score"][
        "type"
    ] == ["string", "null"]
    assert {"eligible", "notes", "input_digest", "formula_snapshot"} <= set(
        actual["components"]["schemas"]["PricingSimulationView"]["required"]
    )
    for name, schema in actual["components"]["schemas"].items():
        Draft202012Validator.check_schema(schema)
        if name.startswith("Pric") and schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, name
    empty = {"paths": {}, "components": {"schemas": {}}}
    extend_openapi(empty)
    assert empty["paths"] == {}


def test_actual_exact_package_routes_have_explicit_closed_binding_contracts():
    app = FastAPI()
    app.include_router(router)
    app.include_router(package_router)
    actual = extend_openapi(app.openapi())
    operations = [
        operation
        for path in actual["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len(operations) == 13
    for name in ("package-pricing-context", "package-pricing-formula-sources"):
        path = actual["paths"][f"/api/v1/bids/{{bid_id}}/{name}"]["get"]
        required = {value["name"] for value in path["parameters"] if value.get("required")}
        assert set(PackagePricingBinding.model_fields) <= required
    schema = actual["components"]["schemas"]["PricingRegisterPackageFormula"]
    assert "package_binding" in schema["required"]
    assert schema["additionalProperties"] is False
    assert "package_binding" not in RegisterFormula.model_fields
    for value in actual["components"]["schemas"].values():
        Draft202012Validator.check_schema(value)


def test_exact_binding_cannot_be_omitted_or_smuggled_into_legacy_registration():
    from test_pricing_integration import formula_request

    uuid = "11111111-1111-4111-8111-111111111111"
    request = formula_request({"doc": uuid, "parse": uuid, "evidence": uuid})
    with pytest.raises(ValidationError):
        RegisterPackageFormula.model_validate(request)
    binding = dict.fromkeys(PackagePricingBinding.model_fields, uuid)
    with pytest.raises(ValidationError):
        RegisterFormula.model_validate(request | {"package_binding": binding})
    assert RegisterPackageFormula.model_validate(request | {"package_binding": binding})
    with pytest.raises(ValidationError):
        RegisterPackageFormula.model_validate(
            request | {"package_binding": binding | {"use_latest": True}}
        )
