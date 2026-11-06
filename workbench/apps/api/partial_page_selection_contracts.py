"""Document only registered partial-page-selection operations."""


def extend_openapi(actual):
    base = "/api/v1/bids/{bid_id}/partial-page-selections"
    for path, method, operation_id in (
        (base, "post", "confirmPartialPageSelection"),
        (base, "get", "listPartialPageSelections"),
        (base + "/{selection_id}", "get", "getPartialPageSelection"),
        (base + "/{selection_id}/evidence", "get", "getPartialPageSelectionEvidence"),
        (base + "/candidates", "get", "listPartialComparisonCandidates"),
        (base + "/{selection_id}/compare/{other_id}", "get", "comparePartialPageSelections"),
    ):
        operation = actual.get("paths", {}).get(path, {}).get(method)
        if operation is None:
            continue
        operation["operationId"] = operation_id
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"]["default"] = {"$ref": "#/components/responses/DomainError"}
        if method == "post":
            operation.setdefault("parameters", []).extend(
                {"$ref": "#/components/parameters/" + name} for name in ("IdempotencyKey", "CSRF")
            )
