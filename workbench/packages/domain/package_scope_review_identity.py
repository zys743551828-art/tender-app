"""Deduplicate actual declared-scope execution, independently of saved receipt IDs.

The full run input still records every prepared input, plan, admission and declaration
receipt. Re-saving equivalent receipts is not a new execution intent. This identity
retains the exact frozen root/context, all consumed model input, method, selected fact
decision/evidence semantics and explicit rerun intent. It never authorizes admission.
"""

from copy import deepcopy

from packages.domain import package_fact_scope as declarations
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError

VERSION = "package-scope-review-dedup/1"
NAVIGATION_BINDING_KEYS = frozenset({"execution_input_id", "execution_input_digest"})


def identify(input_manifest, fact_declaration_records):
    """Return a canonical, auditable key from an already admitted immutable input.

    Only declaration navigation/audit metadata is omitted. The entire original
    binding, fact item digest, provenance proof digest, action and subject remain.
    Original source/identity changes therefore never collapse into an earlier run.
    Callers must still freshly admit sources and current declaration heads before
    accepting a new command; this function is equally usable on historical data.
    """
    try:
        review.validate_input(input_manifest)
        m = input_manifest
        identity = m["execution_input"]["identity"]
        original = identity["binding"]
        refs = m["fact_admission"]["fact_declarations"]
        if (
            type(fact_declaration_records) is not list
            or len(fact_declaration_records) != len(refs)
            or bool(refs) == (m["selected_facts_digest"] == digest([]))
        ):
            raise ValueError("selected declaration count")
        records = {}
        for record in fact_declaration_records:
            verified = declarations.verify(record)
            record_id = verified["manifest"]["id"]
            if record_id in records:
                raise ValueError("duplicate declaration record")
            records[record_id] = verified
        bindings = []
        for ref in sorted(refs, key=lambda row: row["fact_id"]):
            record = records[ref["declaration_id"]]
            declaration = record["manifest"]
            binding = declaration["binding"]
            if (
                record["digest"] != ref["declaration_digest"]
                or declaration["action"] != "bind"
                or binding["fact_id"] != ref["fact_id"]
                or binding["execution_input_id"] != m["execution_input"]["id"]
                or binding["execution_input_digest"] != m["execution_input"]["digest"]
                or any(binding[key] != value for key, value in original.items())
            ):
                raise ValueError("declaration authority binding")
            bindings.append(
                {
                    "fact_id": ref["fact_id"],
                    "action": declaration["action"],
                    "subject": deepcopy(declaration["subject"]),
                    "binding": {
                        key: deepcopy(value)
                        for key, value in binding.items()
                        if key not in NAVIGATION_BINDING_KEYS
                    },
                }
            )
        semantic = {
            "version": VERSION,
            "purpose": m["purpose"],
            "original_binding": deepcopy(original),
            "model_input_digest": m["model_input_digest"],
            "method_digest": m["executor_method"]["digest"],
            "selected_facts_digest": m["selected_facts_digest"],
            "fact_admission_policy_digest": m["fact_admission"]["policy_digest"],
            "fact_scope_bindings": bindings,
            "rerun": deepcopy(identity["rerun"]),
        }
        return {"manifest": semantic, "digest": digest(semantic)}
    except (KeyError, TypeError, ValueError, DomainError) as error:
        raise DomainError(
            "PACKAGE_SCOPE_EXECUTION_KEY_INVALID",
            "核查执行语义与原选用事实声明无法一致核验",
            409,
        ) from error
