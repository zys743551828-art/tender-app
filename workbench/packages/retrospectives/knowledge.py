"""Small integration ports preserving retrospective lineage in every knowledge version."""

from copy import deepcopy
from uuid import UUID

from packages.domain.runtime import DomainError
from packages.retrospectives import observations, repository


def _link(c, item):
    if (
        c.execute(
            "SELECT to_regclass('design.package_retrospective_knowledge_links') AS name"
        ).fetchone()["name"]
        is None
    ):
        return None
    return c.execute(
        "SELECT * FROM design.package_retrospective_knowledge_links WHERE knowledge_id=%s", (item,)
    ).fetchone()


def inherit(c, item, categories, metadata, parents, policy):
    """Called by knowledge.insert_version before inserting its immutable source."""
    linked = _link(c, item)
    if linked is None:
        return categories, metadata, parents, policy
    if "company_fact" in categories:
        raise DomainError(
            "KNOWLEDGE_RETROSPECTIVE_NOT_COMPANY_FACT",
            "事后复盘不能改为事前公司事实；候选仍保留",
            409,
        )
    frozen = repository.load(c, str(linked["bid_id"]), str(linked["retrospective_id"]))
    if not observations.current(c, frozen)["unchanged"]:
        raise DomainError(
            "KNOWLEDGE_RETROSPECTIVE_SOURCE_CHANGED",
            "原复盘依据已变化，请先建立新的待核复盘；原知识版本保留",
            409,
        )
    result = deepcopy(metadata)
    result["retrospective_origin"] = repository.origin(frozen, linked["source_id"])
    return (
        sorted(set(categories) | {"retrospective"}),
        result,
        sorted(set(parents) | {UUID(str(linked["source_id"]))}, key=str),
        "derived_mixed",
    )


def unchanged(c, item):
    """Called by knowledge.lifecycle so stale associations cannot turn green later."""
    linked = _link(c, item)
    if linked is None:
        return True
    frozen = repository.load(c, str(linked["bid_id"]), str(linked["retrospective_id"]))
    return observations.current(c, frozen)["unchanged"]
