"""Bounded qualified launcher with explicit trusted injection, never secret discovery."""

from contextlib import ExitStack
from dataclasses import dataclass
from typing import Callable

import httpx

from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import material_execution_runtime as runtime
from packages.model_governance import material_live_sender as live
from packages.model_governance import material_qualification as policy

PURPOSES = ("dispatch", "preparation", "store", "scope", "original", "parse", "execution")
FIELDS = {
    "version",
    "enabled",
    "account_id",
    "execution_profile_id",
    "execution_profile_digest",
    "dispatch_method_digest",
    "storage_profile",
    "max_messages",
}


@dataclass(frozen=True, repr=False)
class Host:
    """Host callbacks are code-owned, never deserialized/imported from config."""

    connection: Callable
    consumer: Callable
    credential: Callable
    url_for_locator: Callable
    transport: httpx.MockTransport | None = None


def validate(config, host):
    if (
        type(config) is not dict
        or set(config) != FIELDS
        or config.get("version") != "material-qualified-worker-config/1"
    ):
        raise ValueError("CONFIGURATION_INVALID")
    if config["enabled"] is not True or type(host) is not Host:
        raise ValueError("QUALIFIED_WORKER_DISABLED")
    if any(
        not callable(getattr(host, k))
        for k in ("connection", "consumer", "credential", "url_for_locator")
    ):
        raise ValueError("HOST_INVALID")
    if any(not policy.identity(config[k]) for k in ("account_id", "execution_profile_id")) or any(
        not policy.is_digest(config[k])
        for k in ("execution_profile_digest", "dispatch_method_digest")
    ):
        raise ValueError("CONFIGURATION_INVALID")
    if (
        config["dispatch_method_digest"] != dispatch.method_digest()
        or config["storage_profile"] not in {"development_s3", "oss_hangzhou"}
        or type(config["max_messages"]) is not int
        or not 1 <= config["max_messages"] <= 1000
    ):
        raise ValueError("CONFIGURATION_INVALID")
    sender = live.Sender(
        config["account_id"],
        config["execution_profile_id"],
        config["execution_profile_digest"],
        host.credential,
        enabled=True,
        transport=host.transport,
    )
    live.validate(sender, config["execution_profile_id"], config["execution_profile_digest"])
    return sender


def run(config, host=None):
    """Open purpose-isolated resources and consume bounded messages; default refuses.

    No configuration is persisted and no DSN/key is read by this interface.
    Native qualification, profile, input and budget checks remain in the consumer.
    Returned receipts contain no capabilities, provider data or exception messages.
    """
    try:
        sender = validate(config, host)
        with ExitStack() as stack:
            connections = [stack.enter_context(host.connection(p)) for p in PURPOSES]
            ports = runtime.QualifiedPorts(
                preparation=connections[1],
                store=connections[2],
                scope=connections[3],
                original=connections[4],
                parse=connections[5],
                execution=connections[6],
                profile=config["storage_profile"],
                url_for_locator=host.url_for_locator,
                sender=sender,
            )
            runtime._validate_ports(connections[0], ports, qualified=True)
            broker = host.consumer()
            stack.callback(broker.close)
            broker.subscribe([runtime.TOPIC])
            receipts = []
            for _ in range(config["max_messages"]):
                result = runtime.consume_once(
                    connections[0],
                    broker,
                    expected_method_digest=config["dispatch_method_digest"],
                    qualified_ports=ports,
                    timeout=1,
                )
                if result is not None:
                    d = result.observation.metadata["lease"]["document"]
                    receipts.append(
                        {
                            "event_id": d["event_id"],
                            "job_id": d["job_id"],
                            "state": result.observation.metadata["state"],
                            "acknowledged": result.acknowledge,
                            "send_authorized": False,
                        }
                    )
            return {"ok": True, "receipts": receipts}
    except Exception:
        return {"ok": False, "code": "QUALIFIED_WORKER_UNAVAILABLE"}


def read_config(path):
    """Bounded, no-follow configuration containing identities only."""
    import json
    import os
    import stat

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_CONFIG_FIELD")
            result[key] = value
        return result

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
            raise ValueError("CONFIGURATION_INVALID")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError("CONFIGURATION_INVALID")
        return json.loads(raw, object_pairs_hook=pairs)
    finally:
        os.close(fd)
