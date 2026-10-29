"""Exact database observations for authoring; current heads only reject changed inputs."""

import json
from uuid import UUID

from packages.assistant.intent_identity import IDENTITY_FACTS, association_key
from packages.authoring import content, repository, snapshot_structure
from packages.domain import bid_package_requirement_repository as inventories
from packages.domain import package_rule_corrections
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_inventory_proof import _receipt
from packages.domain.bid_package_review_documents import read_member
from packages.domain.bid_package_service import historical, view
from packages.domain.package_fact_validation import assess
from packages.domain.package_inventory_proof import _page_count, _receipt_matches
from packages.domain.package_review_context import read_decision_basis
from packages.domain.review_data import effective_at, source_closure
from packages.domain.review_identity import digest
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import DomainError, clean, fetch
from packages.rag.indexing import original_source_id, parse_source_id


def require(condition, code, message="固定整包、章节或证明身份不一致"):
    if not condition:
        raise DomainError(code, message, 409)


def selected_packages(c, bid, body):
    chosen = body["package_context"]
    output = {}
    for role, kind in (("target", "bid"), ("authority", "authority")):
        ref = chosen[role]
        package = historical(c, bid, ref["package_id"], ref["revision_id"])
        require(
            package.kind.value == kind and package.manifest_digest == ref["manifest_digest"],
            "AUTHORING_PACKAGE_SELECTION_CHANGED",
        )
        output[role] = view(c, package)
    require(
        output["target"]["manifest"]["scope"] == output["authority"]["manifest"]["scope"]
        and output["target"]["identity"] == output["authority"]["identity"],
        "AUTHORING_PACKAGE_SCOPE_MISMATCH",
    )
    identity = fetch(c, "SELECT design.identity_snapshot_v2(%s) AS value", (bid,))["value"]
    require(
        identity["binding_status"] == "confirmed" and identity == output["target"]["identity"],
        "AUTHORING_PACKAGE_IDENTITY_CHANGED",
    )
    return output, identity


def documents(c, bid, selection):
    result = []
    for role in ("target", "authority"):
        for member in selection[role]["manifest"]["members"]:
            kind = fetch(
                c,
                "SELECT artifact_kind FROM design.document_versions WHERE bid_id=%s AND id=%s",
                (bid, member["document_version_id"]),
            )["artifact_kind"]
            require(
                c.execute(
                    "SELECT 1 FROM design.build_outputs WHERE bid_id=%s AND document_version_id=%s",
                    (bid, member["document_version_id"]),
                ).fetchone()
                is None,
                "AUTHORING_PACKAGE_GENERATED_MEMBER_UNSUPPORTED",
                "本阶段只支持原始文件；生成正文的精确修订资格须在构建阶段接通",
            )
            row = read_member(c, bid, member)
            uploads = c.execute(
                """SELECT u.id,u.role,u.declared_digest,u.declared_size
                FROM design.uploads u JOIN design.document_file_versions v
                ON v.bid_id=u.bid_id AND v.version_id=u.verified_version_id
                JOIN design.document_files f ON f.bid_id=v.bid_id AND f.id=v.file_id
                WHERE u.bid_id=%s AND u.verified_version_id=%s AND u.state='verified'
                AND u.role=f.role AND u.declared_digest=%s AND u.declared_size=%s""",
                (bid, member["document_version_id"], row["digest"], row["byte_size"]),
            ).fetchall()
            require(
                kind in {"source_original", "bid_body"} and len(uploads) == 1,
                "AUTHORING_PACKAGE_UPLOAD_UNPROVEN",
            )
            row["qualification"] = {"kind": "verified_upload", "upload": clean(uploads[0])}
            require(
                _page_count(member["parts"], row["page_count"]) == row["page_count"],
                "AUTHORING_PACKAGE_PHYSICAL_RANGE_GAP",
                "整包成员未明确覆盖全部物理页，未截取部分范围",
            )
            # Preserve PostgreSQL's exact geometry text, not a float round trip.
            row["pages"] = c.execute(
                """SELECT physical_page,printed_label,width::text,height::text,rotation,
                quality,gaps::text AS gaps_jsonb_text FROM design.pages
                WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page""",
                (bid, row["parse_id"]),
            ).fetchall()
            row["blocks"] = c.execute(
                """SELECT id,physical_page,ordinal,kind,text_content,bbox::text AS bbox_jsonb_text,
                structure::text AS structure_jsonb_text,digest FROM design.evidence_blocks
                WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id""",
                (bid, row["parse_id"]),
            ).fetchall()
            require(bool(row["blocks"]), "AUTHORING_PACKAGE_EVIDENCE_EMPTY")
            result.append(clean(row) | {"package_role": role})
    return result


def sources(c, bid, docs, at):
    selected = {str(parse_source_id(UUID(doc["parse_id"]))): doc for doc in docs}
    for source_id, doc in selected.items():
        bound = c.execute(
            """SELECT n.id FROM retrieval.source_nodes n
            JOIN retrieval.source_heads h ON h.source_id=n.id
            JOIN retrieval.lineage_edges e ON e.child_id=n.id
            JOIN retrieval.source_nodes root ON root.id=e.parent_id
            WHERE n.id=%s AND n.kind='document' AND n.document_version_id=%s AND n.digest=%s
            AND root.id=%s AND root.kind='document' AND root.document_version_id=n.document_version_id
            AND root.digest=n.digest""",
            (
                source_id,
                doc["document_version_id"],
                doc["digest"],
                original_source_id(UUID(doc["document_version_id"])),
            ),
        ).fetchone()
        require(bound is not None, "AUTHORING_PACKAGE_SOURCE_BINDING_UNPROVEN")
    closure = source_closure(c, [{"id": key} for key in sorted(selected)])
    require(
        all(row["revision"] and row["known_at"] and row["valid_from"] for row in closure),
        "AUTHORING_PACKAGE_SOURCE_BINDING_UNPROVEN",
    )
    effective_at(closure, at)
    versions = {d["document_version_id"]: d["digest"] for d in docs}
    require(
        all(
            row["kind"] == "document"
            and row["document_version_id"] in versions
            and row["digest"] == versions[row["document_version_id"]]
            for row in closure
        ),
        "AUTHORING_PACKAGE_SOURCE_OUTSIDE_SELECTION",
    )
    return closure


def inventory(c, bid, body, selection, docs):
    chosen = body["package_context"]
    ref = chosen["inventory"]
    target = chosen["target"]
    packet = inventories.load_inventory(
        c, bid, target["package_id"], target["revision_id"], ref["id"]
    )
    manifest = packet["manifest"]
    head = inventories.head(c, target["revision_id"])
    require(
        packet["digest"] == ref["digest"]
        and manifest["rule_set_id"] == ref["rule_set_id"]
        and manifest["package_digest"] == chosen["target"]["manifest_digest"]
        and manifest["authority_revision_id"] == chosen["authority"]["revision_id"]
        and manifest["authority_digest"] == chosen["authority"]["manifest_digest"]
        and manifest["identity_digest"] == selection["target"]["identity"]["digest"]
        and head is not None
        and head["id"] == ref["id"],
        "AUTHORING_PACKAGE_INVENTORY_CHANGED",
    )
    current_rules = fetch(
        c, "SELECT current_rule_set_id FROM design.bid_profiles WHERE bid_id=%s", (bid,)
    )["current_rule_set_id"]
    require(str(current_rules) == ref["rule_set_id"], "AUTHORING_PACKAGE_RULES_CHANGED")
    members: list[dict] = []
    parts: list[dict] = []
    for member in selection["authority"]["manifest"]["members"]:
        parse = member["parse"]
        members.append(
            {
                key: member[key]
                for key in (
                    "member_id",
                    "document_version_id",
                    "file_digest",
                    "page_count",
                    "parts",
                )
            }
            | {
                key: parse[key]
                for key in ("parse_run_id", "parser_digest", "config_digest", "evidence_digest")
            }
        )
        parts.extend(
            {
                "member_id": member["member_id"],
                "document_version_id": member["document_version_id"],
                "parse_run_id": parse["parse_run_id"],
            }
            | {
                key: part[key]
                for key in ("part_id", "first_page", "last_page", "shared_attachment")
            }
            for part in member["parts"]
        )
    receipt = _receipt(c, (bid, target["package_id"], target["revision_id"], ref["id"]), manifest)
    require(receipt is not None, "AUTHORING_PACKAGE_EXTRACTION_UNPROVEN")
    original = manifest
    if manifest["version"] == "bid-package-requirements/3":
        package_rule_corrections.verify_derivation(
            packet,
            receipt["derivation"],
            selection["authority"],
            package_rule_corrections.evidence_rows(selection["authority"], docs),
        )
        original = receipt["derivation"]["root_inventory"]["manifest"]
    try:
        result = _receipt_matches(receipt, {"bid_id": bid, **selection}, original, members, parts)
    except (ValueError, TypeError, KeyError) as error:
        raise DomainError(
            "AUTHORING_PACKAGE_EXTRACTION_UNPROVEN", "清单原生抽取身份不一致", 409
        ) from error
    evidence = {b["id"] for d in docs if d["package_role"] == "authority" for b in d["blocks"]}
    require(
        result["extraction_coverage"] == "complete"
        and result["read_evidence_ids_digest"] == digest(sorted(evidence)),
        "AUTHORING_PACKAGE_EXTRACTION_INCOMPLETE",
    )
    actual = c.execute(
        """SELECT to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text) AS value
        FROM design.rule_items r WHERE r.bid_id=%s AND r.rule_set_id=%s ORDER BY r.id""",
        (bid, ref["rule_set_id"]),
    ).fetchall()
    rows = {r["value"]["id"]: r["value"] for r in actual}
    require(
        bool(rows)
        and len(rows) == len(manifest["requirements"])
        and set(rows) == {r["rule_id"] for r in manifest["requirements"]},
        "AUTHORING_PACKAGE_RULES_CHANGED",
    )
    for row in manifest["requirements"]:
        decision = current_decision(c, bid, "rule", row["rule_id"])
        actual_decision = (
            fetch(
                c,
                "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE id=%s",
                (decision["id"],),
            )["value"]
            if decision
            else None
        )
        require(
            row["rule_snapshot"] == rows[row["rule_id"]]
            and row["rule_digest"] == digest(row["rule_snapshot"])
            and row["requirement_digest"] == digest(row["requirement"])
            and row["source_bound"]
            and row["rule_snapshot"]["provenance_status"] == "effective"
            and actual_decision is not None
            and actual_decision["decision"] == "confirmed"
            and row["decision_snapshot"] == actual_decision
            and row["decision_id"] == actual_decision["id"]
            and bool(row["rule_snapshot"]["evidence_ids"])
            and set(row["rule_snapshot"]["evidence_ids"]) <= evidence,
            "AUTHORING_PACKAGE_RULES_CHANGED",
        )
    return {"record": packet, "native_receipt": receipt}


def facts(c, bid, body, docs, identity, at):
    selection = body["facts"]
    head = fetch(
        c,
        """SELECT h.fact_set_id,h.revision,s.digest AS fact_set_digest FROM design.fact_heads h
        JOIN design.fact_sets s ON s.id=h.fact_set_id AND s.bid_id=h.bid_id WHERE h.bid_id=%s""",
        (bid,),
    )
    require(
        str(head["fact_set_id"]) == selection["fact_set_id"]
        and head["revision"] == selection["fact_head_revision"],
        "AUTHORING_PACKAGE_FACT_HEAD_CHANGED",
    )
    ids = sorted(
        set(selection["identity_fact_ids"]) | {item["fact_id"] for item in selection["uses"]}
    )
    # The selected set is an explicit SQL predicate, independent of fact_heads.
    rows = c.execute(
        """SELECT f.id,f.bid_id,f.fact_set_id,f.subject,f.scope,f.name,
        f.value::text AS value_jsonb_text,f.unit,f.evidence_ids,s.digest AS fact_set_digest
        FROM design.fact_items f JOIN design.fact_sets s ON s.bid_id=f.bid_id AND s.id=f.fact_set_id
        WHERE f.bid_id=%s AND f.fact_set_id=%s AND f.id=ANY(%s::uuid[]) ORDER BY f.id""",
        (bid, selection["fact_set_id"], ids),
    ).fetchall()
    require(len(rows) == len(ids), "AUTHORING_PACKAGE_FACT_SCOPE_MISMATCH")
    parses = {(d["document_version_id"], d["parse_id"]) for d in docs}
    result = []
    for row in rows:
        decision = current_decision(c, bid, "fact", row["id"])
        evidence = c.execute(
            """SELECT e.id::text,e.parse_id::text,p.document_version_id::text,e.physical_page,e.digest
            FROM design.evidence_blocks e JOIN design.parse_runs p ON p.bid_id=e.bid_id AND p.id=e.parse_id
            WHERE e.bid_id=%s AND e.id=ANY(%s::uuid[]) ORDER BY e.id""",
            (bid, row["evidence_ids"]),
        ).fetchall()
        item = {
            "fact": clean(row),
            "decision": clean(decision),
            "decision_basis_jsonb_text": read_decision_basis(c, bid, decision, at),
            "evidence": clean(evidence),
            "scope_binding": "selected_frozen_parse"
            if evidence
            and len(evidence) == len(set(row["evidence_ids"]))
            and all((e["document_version_id"], e["parse_id"]) in parses for e in evidence)
            else "unproven",
        }
        proof = read_proof(c, bid, item, at)
        require(
            assess(item, proof)["provenance_status"] == "verified",
            "AUTHORING_PACKAGE_FACT_UNPROVEN",
        )
        result.append(
            {
                "item": item,
                "item_digest": digest(item),
                "proof": proof,
                "proof_digest": digest(proof),
            }
        )
    selected = {r["item"]["fact"]["id"]: r for r in result}
    names = {}
    for fact_id in selection["identity_fact_ids"]:
        row = selected[fact_id]["item"]["fact"]
        require(
            row["name"] in IDENTITY_FACTS and row["name"] not in names,
            "AUTHORING_PACKAGE_IDENTITY_UNPROVEN",
        )
        value = json.loads(row["value_jsonb_text"])
        require(
            isinstance(value, str) and bool(value.strip()), "AUTHORING_PACKAGE_IDENTITY_UNPROVEN"
        )
        names[row["name"]] = value
    require(set(names) == set(IDENTITY_FACTS), "AUTHORING_PACKAGE_IDENTITY_UNPROVEN")
    subjects = {
        "engineering_project": "engineering_project_id",
        "lot": "lot_id",
        "round": "round_id",
        "bidder": "bidder_id",
    }
    for use in selection["uses"]:
        require(
            use["fact_item_digest"] == selected[use["fact_id"]]["item_digest"]
            and use["subject"]["id"] == identity[subjects[use["subject"]["kind"]]],
            "AUTHORING_PACKAGE_FACT_DECLARATION_MISMATCH",
        )
    return {"head": clean(head), "items": result, "canonical_project_key": association_key(names)}


def target(c, bid, body, docs):
    selected = body["target_section"]
    snapshot = fetch(
        c,
        "SELECT * FROM design.draft_snapshots WHERE bid_id=%s AND id=%s",
        (bid, selected["snapshot_id"]),
    )
    draft = fetch(
        c,
        "SELECT revision FROM design.drafts WHERE bid_id=%s AND id=%s",
        (bid, selected["draft_id"]),
    )
    require(
        str(snapshot["draft_id"]) == selected["draft_id"]
        and snapshot["revision"] == selected["base_draft_revision"] == draft["revision"]
        and snapshot["digest"] == selected["snapshot_digest"],
        "AUTHORING_PACKAGE_DRAFT_CHANGED",
    )
    frozen = repository.snapshot_content(c, UUID(bid), UUID(selected["snapshot_id"]))
    rows = c.execute(
        """SELECT r.id,r.section_id,r.revision,r.schema_digest,r.content,r.digest,s.head_revision
        FROM design.draft_snapshot_sections link JOIN design.section_revisions r ON r.id=link.section_revision_id
        AND r.bid_id=link.bid_id AND r.draft_id=link.draft_id
        JOIN design.sections s ON s.id=r.section_id AND s.bid_id=r.bid_id AND s.draft_id=r.draft_id
        WHERE link.bid_id=%s AND link.draft_id=%s AND link.snapshot_id=%s ORDER BY link.ordinal""",
        (bid, selected["draft_id"], selected["snapshot_id"]),
    ).fetchall()
    require(
        all(r["head_revision"] == r["revision"] for r in rows), "AUTHORING_PACKAGE_SECTION_CHANGED"
    )
    matches = [r for r in rows if str(r["section_id"]) == selected["section_id"]]
    require(len(matches) == 1, "AUTHORING_PACKAGE_SECTION_SCOPE_MISMATCH")
    row = matches[0]
    require(
        str(row["id"]) == selected["section_revision_id"]
        and row["revision"] == selected["base_section_revision"]
        and row["digest"] == selected["section_digest"]
        and row["schema_digest"] == selected["schema_digest"],
        "AUTHORING_PACKAGE_SECTION_CHANGED",
    )
    require(
        not any(content.has_rich(r["content"]) for r in rows),
        "AUTHORING_PACKAGE_RICH_TARGET_UNSUPPORTED",
    )
    extension = snapshot_structure.snapshot_extension(snapshot["manifest"])
    if extension:
        require(
            not extension["plans"]
            and not extension["metadata"].get("format_bindings")
            and not extension["metadata"].get("word_import_sources"),
            "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED",
        )
        bound = fetch(
            c,
            "SELECT id,digest FROM design.authoring_structure_versions WHERE bid_id=%s AND snapshot_id=%s",
            (bid, selected["snapshot_id"]),
        )
        require(
            str(bound["id"]) == extension["id"] and bound["digest"] == extension["digest"],
            "AUTHORING_PACKAGE_STRUCTURE_CHANGED",
        )
    blocks = {block["id"]: doc for doc in docs for block in doc["blocks"]}
    rules = body["package_context"]["inventory"]["rule_set_id"]
    for revision in rows:
        for ref in revision["content"]["attrs"]["source_refs"]:
            doc = blocks.get(ref["evidence_id"])
            require(
                doc is not None
                and ref["document_version_id"] == doc["document_version_id"]
                and ref["source_id"] == str(parse_source_id(UUID(doc["parse_id"]))),
                "AUTHORING_PACKAGE_TARGET_SOURCE_OUTSIDE_SELECTION",
            )
            head = fetch(
                c,
                "SELECT revision FROM retrieval.source_heads WHERE source_id=%s",
                (ref["source_id"],),
            )
            require(
                head["revision"] == ref["source_revision"],
                "AUTHORING_PACKAGE_TARGET_SOURCE_CHANGED",
            )
        for rule in revision["content"]["attrs"]["rule_ids"]:
            require(
                c.execute(
                    "SELECT 1 FROM design.rule_items WHERE id=%s AND bid_id=%s AND rule_set_id=%s",
                    (rule, bid, rules),
                ).fetchone()
                is not None,
                "AUTHORING_PACKAGE_TARGET_RULE_OUTSIDE_SELECTION",
            )
    from packages.assistant.generation import nodes

    node = [n for n in nodes(row["content"]) if n["node_id"] == selected["node_id"]]
    require(
        len(node) == 1
        and node[0]["before_digest"] == selected["before_node_digest"]
        and node[0]["node"]["type"] in {"paragraph", "heading"},
        "AUTHORING_PACKAGE_TARGET_NODE_CHANGED",
    )
    return {"snapshot_manifest": snapshot["manifest"], "snapshot": frozen, "sections": clean(rows)}
