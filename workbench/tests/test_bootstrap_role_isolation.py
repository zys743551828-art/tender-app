"""Offline role-graph/permission guards; these do not claim actual PG ACL acceptance."""

import pytest

from deploy import bootstrap_fresh as fresh


class Catalog:
    def __init__(self, *, ancestors=(), memberships=None, forbidden=False):
        self.ancestors = list(ancestors)
        self.memberships = (
            [("tender_assistant_budget_admin", False)] if memberships is None else memberships
        )
        self.forbidden = forbidden
        self.statements = []

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if "WITH RECURSIVE ancestors" in statement:
            rows = self.ancestors
        elif "WHERE m.member=(SELECT oid" in statement:
            rows = self.memberships
        else:
            assert statement.startswith("SELECT EXISTS")
            rows = [] if self.forbidden is None else [(self.forbidden,)]
        return type(
            "Result",
            (),
            {"fetchall": lambda _: rows, "fetchone": lambda _: rows[0] if rows else None},
        )()


@pytest.mark.parametrize(
    "ancestors",
    [
        [("tender_api",)],
        [("intermediate_nologin",), ("tender_api",)],
        [("unrelated_safe_flags",)],
        [("tender_assistant_budget_admin",)],
    ],
)
def test_upstream_role_paths_are_rejected_before_login_checks(ancestors):
    catalog = Catalog(ancestors=ancestors)
    with pytest.raises(fresh.BootstrapError, match="GROUP_HAS_UPSTREAM_MEMBERSHIP"):
        fresh.verify_budget_login_isolation(catalog)
    assert len(catalog.statements) == 1
    # Traverse all membership edges, never filter inherit_option/set_option.
    statement = catalog.statements[0][0]
    assert "UNION\n" in statement
    assert "inherit_option" not in statement and "set_option" not in statement


@pytest.mark.parametrize(
    "memberships",
    [
        [],
        [("tender_api", False)],
        [("tender_assistant_budget_admin", False), ("tender_worker", False)],
        [("tender_assistant_budget_admin", True)],
    ],
)
def test_login_cannot_have_missing_or_additional_memberships(memberships):
    catalog = Catalog(memberships=memberships)
    with pytest.raises(fresh.BootstrapError, match="LOGIN_MEMBERSHIP_NOT_EXACT"):
        fresh.verify_budget_login_isolation(catalog)
    assert len(catalog.statements) == 2


@pytest.mark.parametrize("forbidden", [True, None])
def test_effective_public_direct_or_inherited_permission_fails_closed(forbidden):
    with pytest.raises(fresh.BootstrapError, match="FORBIDDEN_EFFECTIVE_BUSINESS_PRIVILEGES"):
        fresh.verify_budget_login_isolation(Catalog(forbidden=forbidden))


def test_expected_role_and_bounded_effective_rights_pass_offline_catalog():
    catalog = Catalog()
    fresh.verify_budget_login_isolation(catalog)
    statement = catalog.statements[-1][0]
    assert "has_any_column_privilege" in statement
    assert "has_sequence_privilege" in statement
    assert "has_function_privilege" in statement
    assert "has_schema_privilege" in statement
    assert "assistant_reconcile_budget(uuid,text,bigint,text,design.sha256)" in statement


def test_admin_dsn_is_never_copied_into_business_profile():
    values = {
        "API_DATABASE_DSN": "synthetic-api",
        "ASSISTANT_BUDGET_ADMIN_DATABASE_DSN": "synthetic-admin",
    }
    assert fresh.business_configuration(values) == {"API_DATABASE_DSN": "synthetic-api"}
