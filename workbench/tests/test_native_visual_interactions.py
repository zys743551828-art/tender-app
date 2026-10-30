"""Bounded real App/native HTTP checks in an explicitly disposable PG/S3 run."""
# ruff: noqa: F401,F811

import os
import secrets

import pytest
from test_package_pricing_native_s3 import (
    api,
    browser_history,
    database,
    native,
    priced,
    world,
)
from test_stable_lot_identity import catalog, post, uid

from apps.api.auth import password_hash
from packages.domain.runtime import sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PRICING_NATIVE_S3") != "1",
    reason="explicit disposable native PG17/private S3 browser acceptance required",
)


class Private(dict):
    """Keep disposable credentials out of pytest argument representations."""

    def __repr__(self):
        return "<synthetic browser credentials redacted>"


def test_limited_real_visual_interactions(native):
    w = native
    login = "synthetic-visual-" + secrets.token_hex(8)
    password = secrets.token_urlsafe(24)
    owner = w["database"]["owner"]
    owner.execute(
        "UPDATE design.members SET display_name=%s WHERE id=%s",
        ("Synthetic browser member", w["actor"]),
    )
    owner.execute(
        "UPDATE design.credentials SET login_name=%s,password_hash=%s WHERE member_id=%s",
        (login, password_hash(password), w["actor"]),
    )
    project, lot, round_value, bidder = catalog(w)
    empty = post(
        w,
        "/bids",
        {
            "title": "Synthetic empty project",
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    # Append an explicit failure receipt, preserving the original immutable parse.
    owner.execute(
        "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) SELECT gen_random_uuid(),bid_id,document_version_id,parser_digest,config_digest,0,'failed','[\"synthetic persisted failure; no parser execution\"]' FROM design.parse_runs WHERE id=%s",
        (w["member"].parse.parse_run_id,),
    )
    material = uid()
    owner.execute(
        "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,'{}',%s)",
        (material, w["scope"].bid_id, sha({})),
    )
    owner.execute(
        "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'body',0)",
        (material, w["scope"].bid_id, w["member"].document_version_id),
    )
    owner.execute(
        "UPDATE design.bid_profiles SET current_material_id=%s,current_body_id=%s WHERE bid_id=%s",
        (material, w["member"].document_version_id, w["scope"].bid_id),
    )
    receipt = browser_history(
        w,
        [],
        journeys=Private(
            phase="visual",
            login=login,
            password=password,
            empty_bid=empty["id"],
            evidence=os.environ.get("FUSION_VISUAL_BROWSER_EVIDENCE", "/evidence"),
        ),
        browser_script="scripts/native-visual-interactions.mjs",
    )
    assert receipt["name"] == "limited_visual_interactions"
