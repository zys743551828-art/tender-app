"""The actual application mounts one exact route and advertises its closed DTO."""

from fastapi.routing import APIRoute

from apps.api.authoring_history_routes import historical_section
from apps.api.main import app
from packages.contracts.authoring_history_api import PATH, SCHEMAS


def test_actual_main_mounts_one_exact_history_get_and_matching_closed_schema():
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == PATH and "GET" in route.methods
    ]
    assert len(routes) == 1 and routes[0].endpoint is historical_section
    assert not any(
        isinstance(route, APIRoute)
        and route.path == "/api/v1/sections/{section_id}/revisions/{revision}"
        and "GET" in route.methods
        for route in app.routes
    )
    actual = app.openapi()
    operation = actual["paths"][PATH]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AuthoringHistoricalSectionView"
    }
    digest_query = [item for item in operation["parameters"] if item["in"] == "query"]
    assert len(digest_query) == 1
    assert digest_query[0]["name"] == "expected_digest" and digest_query[0]["required"]
    assert operation["security"] == [{"SessionCookie": []}]
    for name, definition in SCHEMAS.items():
        assert actual["components"]["schemas"][name] == definition
