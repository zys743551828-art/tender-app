"""Trusted wrapper around the existing dispatcher; no payload-controlled purpose."""

from dataclasses import dataclass
from typing import Any

import httpx
from psycopg.rows import dict_row

from packages.domain.errors import DomainError
from packages.model_governance import material_execution_runtime as runtime
from packages.model_governance import material_live_sender as live
from packages.package_model_live import producer


@dataclass(frozen=True, repr=False)
class Delivery:
    delivery: runtime.DeliveryResult
    capture_id: str
    capture_completed: bool


@dataclass(frozen=True, repr=False)
class Host:
    transactions: Any
    enabled: bool = False

    async def deliver(self, actor, connection, message, *, qualified_ports, expected_method_digest):
        # Host and ports are code-owned objects, never parsed from message/config JSON.
        if self.enabled is not True or type(qualified_ports) is not runtime.QualifiedPorts:
            raise ValueError("BUSINESS_SHADOW_DISABLED")
        sender = qualified_ports.sender
        live.validate(sender, sender.profile_id, sender.profile_digest)
        kind = "live" if sender.transport is None else "synthetic"
        if sender.transport is not None and type(sender.transport) is not httpx.MockTransport:
            raise ValueError("UNTRUSTED_TRANSPORT")
        job = runtime.dispatch.message(message)["job_id"]
        with qualified_ports.execution.transaction():
            with qualified_ports.execution.cursor(row_factory=dict_row) as cursor:
                executor_pid = cursor.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        # Native begin refuses any pre-existing attempt. Crash recovery retains the
        # original mode; it never relabels a historic/partially executed job as live.
        with self.transactions() as tx:
            capture = tx.begin_capture(
                actor, job, sender.profile_id, producer.method_digest(), kind, executor_pid
            )
        result = await runtime.deliver(
            connection,
            message,
            expected_method_digest=expected_method_digest,
            qualified_ports=qualified_ports,
        )
        if result.observation.metadata["state"] != "qualified_completed":
            return Delivery(result, capture, False)
        try:
            with self.transactions() as tx:
                tx.finish_capture(actor, capture, producer.method_digest())
        except DomainError:
            # Mirror failure never reclassifies financial state or permits another send.
            return Delivery(result, capture, False)
        return Delivery(result, capture, True)
