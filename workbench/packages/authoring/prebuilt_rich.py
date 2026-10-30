"""Prebuilt RICH producer adapter preserving the existing full PDF acceptance rules.

The old Word03/PAGE/RICH profiles and results are never upgraded implicitly.
Each measured TOC iteration uses a distinct conversion receipt and container.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from packages.authoring import (
    generated_renderer,
    page_navigation,
    prebuilt_generated,
    prebuilt_pdf,
    rich_docx,
    rich_renderer,
    rich_verification,
)
from packages.domain.errors import DomainError
from packages.domain.runtime import sha
from packages.word_intake import prebuilt

PROTOCOL = "authoring-prebuilt-rich/1"
MAX_LAYOUT_PASSES = rich_renderer.MAX_LAYOUT_PASSES
NAVIGATION_PROTOCOL = "authoring-prebuilt-page-navigation/1"


def converge_navigation(iterations, *, context_digest, mode, style):
    """Qualify the final fixed point, retaining a narrowly defined bootstrap.

    The old checker still validates every byte, structure and measurement link.
    Only the first all-unknown TOC may have expected intermediate number gaps;
    rerunning the old checker over the tail prevents masking any later mismatch.
    """
    full = page_navigation.converge_navigation(
        iterations, context_digest=context_digest, mode=mode, style=style
    )
    result = full | {"protocol": NAVIGATION_PROTOCOL, "legacy_proof_digest": full["proof_digest"]}
    if len(iterations) >= 2:
        first = iterations[0]
        entries = first["entries"]
        initial = page_navigation.inspect_navigation(
            first["pdf_bytes"], entries, mode=mode, style=style
        )
        measured = {row["node_id"]: row["start_page"] for row in initial["entries"]}
        allowed = {"NAV_TOC_NUMBERS_NOT_AT_FIXED_POINT", "NAV_TOC_PRINTED_VALUE_MISMATCH"}
        bootstrap = (
            bool(entries)
            and all(entry["expected_start_page"] is None for entry in entries)
            and initial["navigation_coverage"] == "complete"
            and set(measured) == {entry["node_id"] for entry in entries}
            and len(measured) == len(initial["entries"]) == len(entries)
            and all(
                type(page) is int and 1 <= page <= initial["page_count"]
                for page in measured.values()
            )
            and set(initial["gaps"]) <= allowed
        )
        if bootstrap:
            tail = page_navigation.converge_navigation(
                iterations[1:], context_digest=context_digest, mode=mode, style=style
            )
            gaps = sorted((set(full["gaps"]) - set(initial["gaps"])) | set(tail["gaps"]))
            # Full-history structural and predecessor-link errors remain in
            # full.gaps. Tail validation adds back every later numeric error.
            qualified = not gaps and tail["fixed_point"]
            result.update(
                {
                    "coverage": "complete" if qualified else "partial",
                    "fixed_point": qualified,
                    "gaps": gaps,
                    "bootstrap": {
                        "iteration": 1,
                        "expected_unknown": True,
                        "measured_starts": measured,
                        "intermediate_gaps": initial["gaps"],
                    },
                }
            )
    result.pop("proof_digest", None)
    result["proof_digest"] = sha(result)
    return result


def profile_for(provider_profile: dict) -> dict:
    prebuilt.validate_profile(provider_profile)
    # The unchanged rich_renderer source binds every existing inspector policy;
    # rich_docx.identity binds the generator and its admitted source dependencies.
    identity = {
        "protocol": PROTOCOL,
        "provider_profile": deepcopy(provider_profile),
        "adapter_digest": sha(Path(__file__).read_bytes()),
        "generator_digest": sha(rich_docx.identity()),
        "validator_digest": sha(Path(rich_verification.__file__).read_bytes()),
        "pdf_inspector_digest": sha(Path(rich_renderer.__file__).read_bytes()),
        "provider_pdf_inspector_digest": sha(Path(prebuilt_pdf.__file__).read_bytes()),
        "provider_pdf_policy": prebuilt_pdf.PROTOCOL,
        "stroke_cap_model": prebuilt_pdf.STROKE_CAP_MODEL,
        "pdf_inspectors": {
            module.__name__: sha(Path(str(module.__file__)).read_bytes())
            for module in (
                rich_renderer.rich_pdf,
                page_navigation,
                rich_renderer.rich_table_pdf,
                rich_renderer.rich_repeated_headers,
                rich_renderer.rich_caption_pdf,
                rich_renderer.rich_layout,
            )
        },
        "page_inspector_digest": sha(Path(generated_renderer.__file__).read_bytes()),
        "dynamic_field_policy": "one_canonical_footer_PAGE_only",
        "navigation_policy": "stable_internal_bookmarks_and_TOC_hyperlinks_only",
        "correspondence_policy": "unchanged_rich_sandbox_7_full_inspect_pdf",
        "max_layout_passes": MAX_LAYOUT_PASSES,
    }
    return {"identity": identity, "profile_digest": sha(identity)}


def validate_profile(profile: dict) -> None:
    try:
        if profile != profile_for(profile["identity"]["provider_profile"]):
            raise ValueError("profile changed")
    except (KeyError, TypeError, ValueError, prebuilt.PrebuiltError):
        raise DomainError(
            "AUTHORING_PREBUILT_RICH_PROFILE_CHANGED", "表图预构建转换资格已变化", 409
        ) from None


def prepare(source, snapshot, materials, manifest, profile, *, pagination=None):
    validate_profile(profile)
    proof = rich_verification.verify(
        source,
        snapshot,
        materials,
        manifest,
        profile["identity"]["generator_digest"],
        pagination=pagination,
    )
    extension = snapshot["authoring_structure"]
    config = extension["metadata"].get("effective_style", extension["style_template"]["config"])
    roots = rich_verification.verify_container(source, materials, page_number=config["page_number"])
    return {
        "proof": proof,
        "config": config,
        "roots": roots,
        "snapshot": snapshot,
        "materials": materials,
        "pagination": pagination,
        "font_inspection": {
            "requested_fonts": [config["font"]],
            "paragraphs": [
                generated_renderer.expected_body(roots),
                config["header_text"],
                config["footer_text"],
            ],
        },
    }


def render_once(source, snapshot, materials, manifest, profile, *, pagination=None, receipt: Path):
    snapshot, materials, manifest, profile, pagination = deepcopy(
        (snapshot, materials, manifest, profile, pagination)
    )
    try:
        validate_profile(profile)
        admitted = {}

        def admit():
            prepared = prepare(
                source, snapshot, materials, manifest, profile, pagination=pagination
            )
            admitted.update(prepared["proof"])
            return prepared

        result = prebuilt._render_generated(
            source,
            profile["identity"]["provider_profile"],
            receipt=receipt,
            admit=admit,
            inspect_pdf=prebuilt_pdf.inspect_pdf,
        )
        result["protocol"] = PROTOCOL
        if "measurements" in result:
            result["correspondence"] = result["measurements"]
        result["chain"] = (
            admitted
            | result["chain"]
            | {
                "profile_digest": profile["profile_digest"],
                "provider_profile_digest": profile["identity"]["provider_profile"][
                    "profile_digest"
                ],
                "render_protocol": PROTOCOL,
            }
        )
        return result
    except DomainError as error:
        return prebuilt_generated.failure(source, profile, error.code) | {"protocol": PROTOCOL}


def render(snapshot, materials, profile, *, mode, receipt: Path):
    """Preserve the old bounded measurement/fixed-point loop with fresh receipts."""
    snapshot, materials, profile = deepcopy((snapshot, materials, profile))
    if mode not in {"chapter_start_new_page", "continuous"}:
        raise DomainError("AUTHORING_PAGINATION_INVALID", "请选择明确的章页排版模式", 422)
    entries = rich_docx.navigation_entries(snapshot)
    pagination = {"mode": mode, "toc_start_pages": {entry["node_id"]: None for entry in entries}}
    iterations, summaries = [], []
    final = None
    for index in range(MAX_LAYOUT_PASSES):
        source = rich_docx.assemble(snapshot, materials, pagination=pagination)
        manifest = rich_verification.manifest(source, snapshot, materials, pagination=pagination)
        rich_verification.verify(
            source, snapshot, materials, manifest, sha(rich_docx.identity()), pagination=pagination
        )
        if profile is None:
            final = prebuilt_generated.failure(source, {}, "AUTHORING_RICH_RENDER_NOT_CONFIGURED")
            final["protocol"] = PROTOCOL
        else:
            iteration_receipt = receipt.with_name(
                f"{receipt.stem}-pass-{index + 1}{receipt.suffix}"
            )
            final = render_once(
                source,
                snapshot,
                materials,
                manifest,
                profile,
                pagination=pagination,
                receipt=iteration_receipt,
            )
        final["docx"] = source
        final["producer_manifest"] = manifest
        final["pagination"] = pagination
        if final["state"] != "succeeded" or not isinstance(final.get("pdf"), bytes):
            break
        entries = rich_docx.navigation_entries(snapshot, pagination)
        iterations.append({"pdf_bytes": final["pdf"], "docx_bytes": source, "entries": entries})
        navigation = final["correspondence"]["navigation"]
        summaries.append(
            {
                "iteration": index + 1,
                "docx_digest": sha(source),
                "pdf_digest": sha(final["pdf"]),
                "pagination": pagination,
                "navigation": navigation,
                "gaps": final["gaps"],
            }
        )
        # A first render deliberately contains unknown TOC numbers. Complete
        # measured destinations authorize another measurement pass, not final
        # qualification; converge_navigation still requires printed TOC values.
        if navigation["navigation_coverage"] != "complete":
            break
        measured = {entry["node_id"]: entry["start_page"] for entry in navigation["entries"]}
        if (
            set(measured) != set(pagination["toc_start_pages"])
            or len(measured) != len(navigation["entries"])
            or any(
                type(page) is not int or not 1 <= page <= navigation["page_count"]
                for page in measured.values()
            )
            or measured == pagination["toc_start_pages"]
        ):
            break
        pagination = {"mode": mode, "toc_start_pages": measured}
    if final is None:
        raise RuntimeError("RICH render loop did not produce an admitted DOCX")
    final["render_iterations"] = iterations
    final["iteration_summaries"] = summaries
    if iterations:
        extension = snapshot["authoring_structure"]
        style = extension["metadata"].get("effective_style", extension["style_template"]["config"])
        context_digest = sha(
            {
                "snapshot_digest": snapshot["snapshot_digest"],
                "sections_digest": sha(snapshot["sections"]),
                "structure_digest": extension["digest"],
                "materials": [
                    {k: v for k, v in item.items() if k != "bytes"} for item in materials
                ],
                "renderer_profile": profile,
                "mode": mode,
            }
        )
        fixed = converge_navigation(
            iterations, context_digest=context_digest, mode=mode, style=style
        )
        final_matches_iteration = (
            final["state"] == "succeeded"
            and final.get("pdf") == iterations[-1]["pdf_bytes"]
            and final["docx"] == iterations[-1]["docx_bytes"]
        )
        final["navigation_proof" if final_matches_iteration else "navigation_history_proof"] = fixed
        final["gaps"] = list(dict.fromkeys(final["gaps"] + fixed["gaps"]))
        if not fixed["fixed_point"] and len(iterations) == MAX_LAYOUT_PASSES:
            final["gaps"].append("AUTHORING_TOC_LAYOUT_DID_NOT_CONVERGE")
            final["adjustment_hint"] = (
                "目录数字仍引起分页变化；请缩短长目录标题、调整字体或版心后重新生成，勿使用计划页数替代。"
            )
        if final["state"] == "succeeded":
            final["coverage"] = "partial" if final["gaps"] else "complete"
    return final
