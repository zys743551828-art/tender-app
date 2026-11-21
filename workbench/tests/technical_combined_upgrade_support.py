"""Fixture helper for offline replay of queued V1/V2/V3 work across V4 installation."""

from test_authoring_exact_builds_pg import adopted
from test_authoring_exact_revisions_pg import published
from test_technical_bid_generation_journey_pg import build_structured_word
from test_technical_bound_format_upgrade_pg import original_records

from packages.authoring import combined_authoring_scope
from packages.domain.runtime import ROOT, connection


def keep_queued_original(w, *, plan=False, layout=False):
    before = original_records(w)
    frozen = before["input_manifest"]["plan"]["execution_policy"]
    assert ("saved_plan_method" in frozen) is plan
    assert ("bound_format_method" in frozen) is layout
    assert "combined_scope_method" not in frozen
    with connection() as c:
        assert not combined_authoring_scope.installed(c)
    w["database"]["owner"].execute((ROOT / combined_authoring_scope.DDL).read_text())
    assert original_records(w) == before
    for worker in (False, True):
        with connection(worker) as c:
            assert combined_authoring_scope.installed(c)
    ready = adopted.__wrapped__(published.__wrapped__(w))
    assert len(w["calls"]) == 1
    _, word, body = build_structured_word(
        ready, gate_state="structure_not_supported" if plan else "structured_layout_rechecked"
    )
    assert word["format"] == "docx" and w["raw"]["replacement_text"] in body
    assert original_records(w) == before
