"""Create/verify the implemented Kafka topic set without starting any consumers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, ConfigResource, NewTopic


def default_bootstrap():
    if __package__:
        from .initialize_database import local_configuration

        return local_configuration()["KAFKA_BOOTSTRAP_SERVERS"]
    from initialize_database import local_configuration as script_configuration

    return script_configuration()["KAFKA_BOOTSTRAP_SERVERS"]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "apps/worker/execution-policy-11.json"


def topic_specifications(policy):
    bindings = policy["topic_bindings"]
    names = {entry["topic"] for entry in bindings.values()}
    names.update((policy["domain_event_topic"], policy["dead_letter_topic"]))
    if any(
        not isinstance(n, str) or n in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]{1,249}", n)
        for n in names
    ):
        raise ValueError("Invalid Kafka topic in the selected policy")
    if "all_topics" in policy and sorted(policy["all_topics"]) != sorted(names):
        raise ValueError("all_topics does not match the selected policy bindings")
    for lane, entry in policy.get("consumer_lanes", {}).items():
        if entry["topic"] != bindings[lane]["topic"]:
            raise ValueError("Consumer lane and topic binding disagree")
        if entry["group"] != bindings[lane]["consumer_group"]:
            raise ValueError("Consumer group and topic binding disagree")
    global_lane = policy.get("assistant_global")
    if global_lane and (
        global_lane["topic"] != bindings["assistant_global"]["topic"]
        or global_lane["core_engine"] is not False
    ):
        raise ValueError("Global assistant must use its independent transport")
    return {
        name: {
            "cleanup.policy": "delete",
            "retention.ms": str(
                (
                    30
                    if name == policy["dead_letter_topic"]
                    else 14
                    if name == policy["domain_event_topic"]
                    else 7
                )
                * 86400000
            ),
            "min.insync.replicas": "1",
            "max.message.bytes": "262144",
        }
        for name in sorted(names)
    }


def initialize(admin, policy, *, create_missing=True, expected_cluster_id=None):
    specifications = topic_specifications(policy)
    before = admin.list_topics(timeout=20)
    if expected_cluster_id is not None and before.cluster_id != expected_cluster_id:
        raise RuntimeError("Kafka cluster identity does not match; no mutation performed")
    missing = sorted(set(specifications) - set(before.topics))
    if missing and not create_missing:
        raise RuntimeError("Kafka topic set incomplete: " + ", ".join(missing))
    created = []
    if missing:
        futures = admin.create_topics(
            [
                NewTopic(name, num_partitions=6, replication_factor=1, config=specifications[name])
                for name in missing
            ]
        )
        for name in missing:
            try:
                futures[name].result(timeout=30)
                created.append(name)
            except KafkaException as error:
                if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
    deadline = time.monotonic() + 20
    while True:
        metadata = admin.list_topics(timeout=20)
        if expected_cluster_id is not None and metadata.cluster_id != expected_cluster_id:
            raise RuntimeError("Kafka cluster identity changed during verification")
        if set(specifications) <= set(metadata.topics):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Kafka topic creation was not visible in metadata")
        time.sleep(0.2)
    for name, wanted in specifications.items():
        topic = metadata.topics[name]
        if (
            topic.error
            or len(topic.partitions) != 6
            or any(len(p.replicas) != 1 for p in topic.partitions.values())
        ):
            raise RuntimeError("Development topic topology mismatch: " + name)
        resource = ConfigResource(ConfigResource.Type.TOPIC, name)
        deadline = time.monotonic() + 20
        while True:
            try:
                actual = admin.describe_configs([resource])[resource].result(timeout=10)
                break
            except KafkaException as error:
                if (
                    error.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.2)
        for key, value in wanted.items():
            if key not in actual or actual[key].value != value:
                raise RuntimeError(
                    f"Development topic configuration mismatch: {resource.name}:{key}"
                )
    return {
        "cluster_id": metadata.cluster_id,
        "topics_verified": len(specifications),
        "topic_names": sorted(specifications),
        "topics_created": created,
        "scope": "development single-broker metadata only; no consumers started",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap")
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY,
        help="Implemented policy by default; choose an explicit snapshot when needed",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="Read-only verification; missing topics fail"
    )
    parser.add_argument(
        "--expected-cluster-id", help="Reject a different cluster before creating topics"
    )
    arguments = parser.parse_args()
    raw = arguments.policy.read_bytes()
    policy = json.loads(raw)
    topic_specifications(policy)  # fail locally before connecting on inconsistent policy
    admin = AdminClient({"bootstrap.servers": arguments.bootstrap or default_bootstrap()})
    result = initialize(
        admin,
        policy,
        create_missing=not arguments.check_only,
        expected_cluster_id=arguments.expected_cluster_id,
    )
    result.update(
        policy_path=str(arguments.policy.resolve()), policy_sha256=hashlib.sha256(raw).hexdigest()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
