"""Deployment regression: old six-topic cluster must support all real transport routes."""

import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.worker import engine
from deploy.initialize_topics import DEFAULT_POLICY, initialize, topic_specifications
from packages.assistant.transport import TOPIC as GLOBAL_TOPIC
from packages.research.batches import TOPIC as RESEARCH_TOPIC

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def completed(value):
    future = Future()
    future.set_result(value)
    return future


class MetadataAdmin:
    def __init__(self):
        self.cluster_id = "synthetic-cluster"
        # The pre-existing six were created under the old target policy, never modified.
        self.configs = topic_specifications(
            load(ROOT / "packages/contracts/policies/execution-policy.json")
        )
        self.requests = []
        self.bad_topology = None

    def list_topics(self, timeout):
        topics = {
            name: SimpleNamespace(
                error=None, partitions={i: SimpleNamespace(replicas=[1]) for i in range(6)}
            )
            for name in self.configs
        }
        if self.bad_topology:
            topics[self.bad_topology].partitions.pop(5)
        return SimpleNamespace(cluster_id=self.cluster_id, topics=topics)

    def create_topics(self, topics):
        self.requests.extend(topics)
        for topic in topics:
            assert topic.topic not in self.configs
            assert topic.num_partitions == 6 and topic.replication_factor == 1
            self.configs[topic.topic] = dict(topic.config)
        return {topic.topic: completed(None) for topic in topics}

    def describe_configs(self, resources):
        return {
            resource: completed(
                {k: SimpleNamespace(value=v) for k, v in self.configs[resource.name].items()}
            )
            for resource in resources
        }


def test_default_policy_covers_actual_worker_research_and_independent_global_routes():
    policy = load(DEFAULT_POLICY)
    topics = set(topic_specifications(policy))
    actual = {engine.task_topic(handler) for handler in engine.ORDINARY_HANDLERS} | {
        RESEARCH_TOPIC,
        GLOBAL_TOPIC,
    }
    assert actual <= topics and len(topics) == 9
    assert GLOBAL_TOPIC not in {engine.task_topic(handler) for handler in engine.ORDINARY_HANDLERS}
    assert policy["ordinary_handler_bindings"] == {
        handler: engine.task_topic(handler) for handler in engine.ORDINARY_HANDLERS
    }
    assert {name: set(lane["handlers"]) for name, lane in policy["consumer_lanes"].items()} == {
        name: set(handlers) for name, handlers in engine.LANE_HANDLERS.items()
    }
    old = set(
        topic_specifications(load(ROOT / "packages/contracts/policies/execution-policy.json"))
    )
    assert actual - old == {
        "tender.task.assistant.v1",
        "tender.task.assistant-global.v1",
        "tender.task.comparison.v1",
    }


def test_upgrade_old_six_only_adds_missing_routes_and_recheck_never_mutates():
    admin = MetadataAdmin()
    old = dict(admin.configs)
    result = initialize(admin, load(DEFAULT_POLICY), expected_cluster_id="synthetic-cluster")
    assert set(result["topics_created"]) == {
        "tender.task.assistant.v1",
        "tender.task.assistant-global.v1",
        "tender.task.comparison.v1",
    }
    assert result["topics_verified"] == 9
    assert {name: admin.configs[name] for name in old} == old
    assert len(admin.requests) == 3
    second = initialize(admin, load(DEFAULT_POLICY), create_missing=False)
    assert second["topics_created"] == [] and len(admin.requests) == 3


def test_read_only_incomplete_and_wrong_cluster_reject_before_creation():
    admin = MetadataAdmin()
    with pytest.raises(RuntimeError, match="incomplete"):
        initialize(admin, load(DEFAULT_POLICY), create_missing=False)
    with pytest.raises(RuntimeError, match="identity does not match"):
        initialize(admin, load(DEFAULT_POLICY), expected_cluster_id="other-cluster")
    assert admin.requests == [] and len(admin.configs) == 6


def test_explicit_old_snapshot_remains_supported_and_topology_or_retention_is_not_silently_fixed():
    admin = MetadataAdmin()
    old = load(ROOT / "packages/contracts/policies/execution-policy.json")
    assert initialize(admin, old)["topics_verified"] == 6 and admin.requests == []
    topic = next(iter(admin.configs))
    admin.configs[topic]["retention.ms"] = "1"
    with pytest.raises(RuntimeError, match="configuration mismatch"):
        initialize(admin, old, create_missing=False)
    admin.configs[topic]["retention.ms"] = topic_specifications(old)[topic]["retention.ms"]
    admin.bad_topology = topic
    with pytest.raises(RuntimeError, match="topology mismatch"):
        initialize(admin, old, create_missing=False)
    assert admin.requests == []


def test_inconsistent_declared_policy_cannot_hide_a_real_lane():
    policy = load(DEFAULT_POLICY)
    policy["all_topics"].remove("tender.task.comparison.v1")
    with pytest.raises(ValueError, match="does not match"):
        topic_specifications(policy)
    policy = load(DEFAULT_POLICY)
    policy["consumer_lanes"]["comparison"]["topic"] = "tender.task.review.v1"
    with pytest.raises(ValueError, match="lane and topic"):
        topic_specifications(policy)
