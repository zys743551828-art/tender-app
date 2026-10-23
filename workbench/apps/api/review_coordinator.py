"""独立API能力控制面；即使无浏览器轮询也推进已持久化的评审请求。"""

import argparse
import json
import signal
import threading

import psycopg
from psycopg import sql

from packages.domain.bounded_sweep import KeysetSweep
from packages.domain.reviews import _locked, _write_intent, tick
from packages.domain.runtime import DomainError, assert_role, connection
from packages.tasks.review_runtime import configure_review_guard

configure_review_guard()

STOP = threading.Event()


def run(once=False):
    assert_role()
    sweep = KeysetSweep(("bid_id",))
    while not STOP.is_set():
        with connection() as c:
            ids = sweep.read(
                c,
                sql.SQL(
                    "SELECT bid_id FROM review_slots WHERE pending_intent->>'state' IN('preparing','queued','running','cancel_requested')"
                ),
            )
        for item in ids:
            try:
                tick(item["bid_id"])
            except DomainError as error:
                if error.retryable:
                    continue
                with connection() as c:
                    _, slot = _locked(c, item["bid_id"])
                    intent = slot["pending_intent"]
                    if intent and intent["state"] == "preparing":
                        intent.update(state="blocked", error_code=error.code, gaps=[error.message])
                        _write_intent(c, item["bid_id"], intent)
            except psycopg.Error:
                print(json.dumps({"event": "review_controller_dependency_failure"}), flush=True)
        if once:
            return
        STOP.wait(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    run(args.once)


if __name__ == "__main__":
    main()
