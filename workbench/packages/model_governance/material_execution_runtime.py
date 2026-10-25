"""Dedicated material outbox relay and manually acknowledged Kafka consumer.

Production admission precedes every material read, reservation and provider
call. Only the separate, explicit synthetic lane assembles the existing native
recovery, complete-input preflight and once-only financial execution pipeline.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

import httpx
from confluent_kafka import Consumer, Producer
from psycopg.pq import TransactionStatus

from packages.domain.review_identity import canonical
from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import material_preparation_leases as preparation
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision

TOPIC = "tender.material.judgment.v1"
CONSUMER_GROUP = "tender-material-execution-v1"


@dataclass(frozen=True, repr=False)
class MechanismPorts:
    """Six independent purpose connections and an explicitly networkless model.

    These are process-owned configuration, never Kafka payload fields. Native
    audits independently bind each LOGIN and current source. The transport is
    checked with exact type, and the existing sender constructs its own client.
    """

    preparation: Any
    store: Any
    scope: Any
    original: Any
    parse: Any
    execution: Any
    profile: str
    url_for_locator: Callable
    transport: httpx.MockTransport


@dataclass(frozen=True, repr=False)
class DeliveryResult:
    observation: dispatch.DispatchObservation
    acknowledge: bool


def producer(bootstrap):
    return Producer(
        {
            "bootstrap.servers": bootstrap,
            "client.id": "material-outbox-relay",
            "enable.idempotence": True,
            "acks": "all",
            "delivery.timeout.ms": 30000,
            "request.timeout.ms": 10000,
            "message.max.bytes": 4096,
            "log_level": 0,
        }
    )


def consumer(bootstrap, *, group=CONSUMER_GROUP):
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "client.id": "material-execution-worker",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
            "max.poll.interval.ms": 3600000,
            "allow.auto.create.topics": False,
            "log_level": 0,
        }
    )


def relay_once(
    connection,
    kafka_producer,
    *,
    profile_id,
    expected_profile_digest,
    expected_method_digest,
    timeout=30,
):
    """Commit a native lease, publish its ID-only event, then persist the ACK.

    A broker timeout or a lost native ACK leaves the original event retryable
    after its bounded lease. Publication retries never acquire a model grant.
    """
    if type(timeout) not in {int, float} or not 0 < timeout <= 30:
        dispatch.fail("PUBLISH_TIMEOUT_INVALID")
    observed = dispatch.claim_publication(
        connection,
        profile_id=profile_id,
        expected_profile_digest=expected_profile_digest,
        command_id=str(uuid4()),
        expected_method_digest=expected_method_digest,
    )
    if observed is None:
        return None
    if not observed.metadata["new_claim"] or not observed.metadata["lease_current"]:
        dispatch.fail("PUBLICATION_NOT_OWNED")
    body = dispatch.message(observed.metadata["lease"]["document"]["message"])
    if connection.info.transaction_status != TransactionStatus.IDLE:
        dispatch.fail("IDLE_CONNECTION_REQUIRED")
    delivered = []

    def delivery(error, message):
        delivered.append(error is None)

    try:
        kafka_producer.produce(
            TOPIC,
            key=body["job_id"].encode("ascii"),
            value=canonical(body),
            on_delivery=delivery,
        )
        deadline = time.monotonic() + timeout
        while not delivered and time.monotonic() < deadline:
            kafka_producer.poll(min(0.2, max(0, deadline - time.monotonic())))
    except Exception:
        dispatch.fail("PUBLICATION_UNCONFIRMED")
    if delivered != [True]:
        dispatch.fail("PUBLICATION_UNCONFIRMED")
    return dispatch.ack_publication(
        connection, observed, expected_method_digest=expected_method_digest
    )


def _validate_ports(connection, ports):
    if type(ports) is not MechanismPorts or type(ports.transport) is not httpx.MockTransport:
        dispatch.fail("ISOLATED_TRANSPORT_REQUIRED")
    connections = (
        connection,
        ports.preparation,
        ports.store,
        ports.scope,
        ports.original,
        ports.parse,
        ports.execution,
    )
    if len({id(c) for c in connections}) != 7:
        dispatch.fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    if any(c.info.transaction_status != TransactionStatus.IDLE for c in connections):
        dispatch.fail("IDLE_CONNECTION_REQUIRED")


def production_admission():
    """Exercise the existing hard admission boundary without opening a client."""
    try:
        execution.execute_attempt()
    except execution.MaterialExecutionError as error:
        if str(error) == "MATERIAL_EXECUTION_LIVE_QUALIFICATION_UNAVAILABLE":
            return "LIVE_QUALIFICATION_UNAVAILABLE"
    # Unexpected future behavior cannot silently turn this transport into a live sender.
    dispatch.fail("LIVE_ADMISSION_CHANGED")


async def deliver(connection, value, *, expected_method_digest, mechanism_ports=None):
    """Run one ID-only delivery. Only durable terminal receipts permit Kafka ACK.

    An active delivery belongs to the original claimant. Another command does
    not borrow its token. After takeover, every previous execution slot remains
    once-only; in-flight and unknown financial states stop before preparation.
    """
    observed = dispatch.claim_delivery(
        connection, value, command_id=str(uuid4()), expected_method_digest=expected_method_digest
    )
    metadata = observed.metadata
    if metadata["state"] in dispatch.TERMINAL:
        return DeliveryResult(observed, True)
    if not metadata["new_claim"] or not metadata["lease_current"]:
        return DeliveryResult(observed, False)
    d = metadata["lease"]["document"]
    if d["mode"] == "production_admission":
        # No reader connection, recovery URL, wallet, provider or fixture is used here.
        failure = production_admission()
        completed = dispatch.finish(
            connection, observed, failure=failure, expected_method_digest=expected_method_digest
        )
        return DeliveryResult(completed, True)
    if mechanism_ports is None:
        completed = dispatch.finish(
            connection,
            observed,
            failure="CONFIGURATION_UNAVAILABLE",
            expected_method_digest=expected_method_digest,
        )
        return DeliveryResult(completed, True)
    _validate_ports(connection, mechanism_ports)
    ports = mechanism_ports
    owned = dispatch.owned_job(connection, observed, expected_method_digest=expected_method_digest)
    source = owned.metadata
    if source["financial_state"] not in {None, "ready"} or not source["source_current"]:
        completed = dispatch.finish(
            connection, observed, failure="NONE", expected_method_digest=expected_method_digest
        )
        return DeliveryResult(completed, True)
    job = source["job"]["document"]
    failure = "PREPARATION_FAILED"
    try:
        observed = dispatch.heartbeat(
            connection, observed, expected_method_digest=expected_method_digest
        )
        claimed = preparation.claim(
            ports.preparation,
            job_id=job["job_id"],
            expected_job_digest=source["job"]["digest"],
            profile_id=source["preparation_profile_id"],
            expected_profile_digest=source["preparation_profile_digest"],
            command_id=str(uuid4()),
            expected_method_digest=preparation.method_digest(),
        )
        p = claimed.metadata["document"]
        bundle, checked = await preflight.restore_and_preflight(
            ports.preparation,
            ports.store,
            ports.scope,
            ports.original,
            ports.parse,
            lease_id=p["lease_id"],
            expected_lease_digest=claimed.metadata["digest"],
            expected_input_digest=job["material_input_digest"],
            expected_preparation_method_digest=preparation.method_digest(),
            expected_serializer_digest=vision.serializer_digest(),
            expected_method_digest=preflight.method_digest(),
            store_command_id=source["store_command_id"],
            expected_packet_digest=source["packet_digest"],
            expected_storage_record_digest=source["storage_record_digest"],
            profile=ports.profile,
            url_for_locator=ports.url_for_locator,
        )
        failure = "EXECUTION_FAILED"
        for slot in job["slots"]:
            observed = dispatch.heartbeat(
                connection, observed, expected_method_digest=expected_method_digest
            )
            preparation.heartbeat(
                ports.preparation,
                lease_id=p["lease_id"],
                expected_lease_digest=claimed.metadata["digest"],
                command_id=str(uuid4()),
                expected_method_digest=preparation.method_digest(),
            )
            outcome = await execution.execute_mechanism_attempt(
                ports.preparation,
                ports.execution,
                bundle,
                checked,
                rule_id=slot["rule_id"],
                slot_id=slot["slot_id"],
                profile_id=source["execution_profile_id"],
                expected_profile_digest=source["execution_profile_digest"],
                command_id=str(uuid4()),
                expected_preflight_digest=checked.metadata["digest"],
                expected_method_digest=execution.method_digest(),
                transport=ports.transport,
            )
            if outcome.metadata["job_balance"]["state"] != "ready":
                break
        failure = "NONE"
    except (
        preparation.PreparationError,
        preflight.MaterialPreflightError,
        execution.MaterialExecutionError,
    ):
        # Native finish re-reads the financial truth. An exception cannot turn an
        # in-flight or unknown charge into a zero-cost failed delivery.
        pass
    completed = dispatch.finish(
        connection, observed, failure=failure, expected_method_digest=expected_method_digest
    )
    return DeliveryResult(completed, True)


def consume_once(
    connection, kafka_consumer, *, expected_method_digest, mechanism_ports=None, timeout=1
):
    """Manually commit only after a terminal native result has committed."""
    if type(timeout) not in {int, float} or not 0 <= timeout <= 30:
        dispatch.fail("POLL_TIMEOUT_INVALID")
    try:
        item = kafka_consumer.poll(timeout)
    except Exception:
        dispatch.fail("CONSUMPTION_UNAVAILABLE")
    if item is None:
        return None
    if item.error() is not None:
        dispatch.fail("CONSUMPTION_UNAVAILABLE")
    from confluent_kafka import TopicPartition

    position = TopicPartition(item.topic(), item.partition(), item.offset())
    try:
        if item.topic() != TOPIC or item.headers():
            dispatch.fail("MESSAGE_INVALID")
        body = dispatch.message(item.value())
        if item.key() != body["job_id"].encode("ascii"):
            dispatch.fail("MESSAGE_KEY_INVALID")
        result = asyncio.run(
            deliver(
                connection,
                body,
                expected_method_digest=expected_method_digest,
                mechanism_ports=mechanism_ports,
            )
        )
        if result.acknowledge:
            if connection.info.transaction_status != TransactionStatus.IDLE:
                dispatch.fail("IDLE_CONNECTION_REQUIRED")
            try:
                committed = kafka_consumer.commit(message=item, asynchronous=False)
                if (
                    type(committed) is not list
                    or len(committed) != 1
                    or committed[0].error is not None
                    or committed[0].topic != item.topic()
                    or committed[0].partition != item.partition()
                    or committed[0].offset != item.offset() + 1
                ):
                    dispatch.fail("OFFSET_UNCONFIRMED")
            except Exception:
                dispatch.fail("OFFSET_UNCONFIRMED")
        else:
            kafka_consumer.seek(position)
        return result
    except Exception:
        # Every unacknowledged message is rewound, including poison envelopes
        # and an offset ACK whose broker outcome is unknown. Later success must
        # never commit past this position. Terminal replay never resends a model.
        try:
            kafka_consumer.seek(position)
        except Exception:
            dispatch.fail("CONSUMER_RESTART_REQUIRED")
        raise
