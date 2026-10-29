"""Expand only independently proven physical repetitions for RICH body comparison.

The immutable source and the frozen PAGE inspector remain untouched. Never remove
matching strings from PDF text: duplicates elsewhere must still fail exact equality.
"""

from copy import deepcopy

from packages.authoring.build import W


def body_roots(roots, proof):
    if proof["coverage"] != "complete":
        return roots
    result = dict(roots)
    result["word/document.xml"] = deepcopy(roots["word/document.xml"])
    native = list(result["word/document.xml"].iter("{" + W + "}tbl"))
    if len(native) != len(proof["tables"]):
        raise ValueError("REPEATED_HEADER_TABLE_COUNT")
    for table, matched in zip(native, proof["tables"], strict=True):
        parts = matched.get("fragments", [])
        if len(parts) != 2 or not any(c.get("repeated_header") for c in parts[1]["cells"]):
            continue
        rows = table.findall("{" + W + "}tr")
        if rows[0].find("{" + W + "}trPr/{" + W + "}tblHeader") is None:
            raise ValueError("REPEATED_HEADER_SOURCE_REQUIRED")
        split = parts[1]["source_rows"][0]
        table.insert(list(table).index(rows[split]), deepcopy(rows[0]))
    return result
