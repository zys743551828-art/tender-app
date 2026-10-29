"""Explicit synthetic transport fault barriers around the actual ordinary engine.

This is a test subprocess, never an application entry point. Barriers do not
replace Kafka, S3, PostgreSQL, computation, leases, or result publication.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from pathlib import Path

from apps.worker import engine
from packages.domain.runtime import clean


def record(path, value):
    temporary = path.with_suffix(".partial")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(clean(value), stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("relay-once", "relay-after-ack", "worker", "worker-after-compute", "reconcile"),
    )
    parser.add_argument("operation")
    parser.add_argument("marker", type=Path)
    args = parser.parse_args()
    if os.environ.get("FUSION_SYNTHETIC_FAULT_CHILD") != "1":
        raise SystemExit("explicit synthetic fault subprocess required")
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: engine.STOP.set())
    if args.mode.startswith("relay"):
        actual_producer = engine.producer

        class ObservedProducer:
            def __init__(self):
                self.client = actual_producer()

            def produce(self, topic, *, key, value, on_delivery):
                payload = json.loads(value)

                def delivered(error, message):
                    if error is None and payload["operation_id"] == args.operation:
                        record(
                            args.marker,
                            {
                                "operation_id": args.operation,
                                "topic": message.topic(),
                                "partition": message.partition(),
                                "offset": message.offset(),
                                "actual_broker_ack": True,
                            },
                        )
                        if args.mode == "relay-after-ack":
                            # The broker has ACKed. The engine has not yet entered
                            # its PostgreSQL ack_outbox transaction.
                            threading.Event().wait()
                    on_delivery(error, message)

                self.client.produce(topic, key=key, value=value, on_delivery=delivered)

            def poll(self, timeout):
                return self.client.poll(timeout)

        engine.producer = ObservedProducer
        engine.relay(once=True)
        return
    if args.mode == "reconcile":
        engine.reconcile()
        return
    if args.mode == "worker-after-compute":
        actual_compute = engine.run_compute

        def computed(message, lease):
            outcome = actual_compute(message, lease)
            if message["operation_id"] == args.operation:
                record(
                    args.marker,
                    {
                        "operation_id": args.operation,
                        "message": message,
                        "lease": lease,
                        "parsed_digest": outcome["parsed_digest"],
                        "page_count": len(outcome["parsed"]["pages"]),
                        "actual_original_computed": True,
                    },
                )
                # The normal heartbeat remains active until the parent sends
                # SIGKILL; no result transaction has started.
                threading.Event().wait()
            return outcome

        engine.run_compute = computed
    engine.consume("document")


if __name__ == "__main__":
    main()
