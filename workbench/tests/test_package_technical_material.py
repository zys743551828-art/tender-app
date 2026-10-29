"""Explicit synthetic /3 material, full multi-source payload and zero paid calls."""

import asyncio
import base64
import io
import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import httpx
import pytest
from reportlab.pdfgen import canvas

from packages.domain.errors import DomainError
from packages.domain.providers import deepseek_complete_vision as provider
from packages.domain.providers.deepseek_vision import VisionProviderError, parse_response
from packages.domain.review_identity import digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as inputs
from packages.model_governance.technical_png import digest_bytes


def uid(number):
    return str(UUID(int=number))


def reseal(origin):
    m = origin.material
    preview = m["scope"]["manifest"]["preview"]
    preview["digest"] = digest(preview["manifest"])
    m["scope"]["digest"] = digest(m["scope"]["manifest"])
    meta = origin.metadata
    meta["scope_digest"] = m["scope"]["digest"]
    meta["material_digest"] = digest(m)
    meta["digest"] = digest({k: v for k, v in meta.items() if k != "digest"})
    return origin


@pytest.fixture(scope="module")
def synthetic():
    documents = []
    native = []
    originals = {}
    bundles = {}
    members = {}
    for index, role in ((1, "target"), (2, "authority")):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(100, 150), invariant=1)
        pdf.drawString(3, 60, "Synthetic complete material " + role)
        pdf.save()
        raw = stream.getvalue()
        doc = uid(index)
        parse = uid(index + 10)
        bundle = assets.render_static_pdf(
            raw,
            document_version_id=doc,
            expected_source_digest=digest_bytes(raw),
            expected_source_size=len(raw),
            expected_method_digest=assets.render_method_digest(),
        )
        if index == 1:
            first = bundle.manifest["pages"][0]["asset"]
            bundle = assets.crop_page_assets(
                bundle,
                [
                    {
                        "physical_page": 1,
                        "parent_image_digest": first["sha256"],
                        "rectangle": [0, 0, 15, 15],
                    }
                ],
                expected_manifest_digest=bundle.manifest["digest"],
                expected_method_digest=assets.crop_method_digest(),
            )
        bundles[doc] = bundle
        originals[doc] = raw
        pages = [
            {
                "physical_page": 1,
                "printed_label": None,
                "width": "100",
                "height": "150",
                "rotation": 0,
                "quality": "usable",
                "gaps": "[]",
            }
        ]
        blocks = [
            {
                "id": uid(index * 100 + j),
                "physical_page": 1,
                "ordinal": j,
                "kind": "text" if j < 3 else "table",
                "text_content": f"Synthetic {role} source {j}",
                "bbox": None,
                "structure": None if j < 3 else '{"rows": [["zero", "0"]]}',
                "digest": digest_bytes(f"Synthetic {role} source {j}".encode()),
            }
            for j in (1, 2, 3)
        ]
        parse_digest = digest(
            {
                "identity_version": "package-parse-evidence/1",
                "parse_run_id": parse,
                "pages": pages,
                "blocks": blocks,
            }
        )
        identity = {
            "status": "frozen",
            "parse_run_id": parse,
            "parser_digest": "b" * 64,
            "config_digest": "c" * 64,
            "evidence_digest": parse_digest,
            "reason": None,
        }
        native.append(
            {
                "document_version_id": doc,
                "source_digest": digest_bytes(raw),
                "source_byte_size": len(raw),
                "parse_run_id": parse,
                "parse_digest": parse_digest,
                "parser_digest": "b" * 64,
                "config_digest": "c" * 64,
                "page_count": 1,
                "pages": pages,
                "blocks": blocks,
            }
        )
        member = {
            "member_id": role,
            "document_version_id": doc,
            "file_digest": digest_bytes(raw),
            "parse": identity,
            "page_count": 1,
            "parts": [
                {
                    "part_id": role,
                    "category": "technical",
                    "first_page": 1,
                    "last_page": 1,
                    "shared_attachment": False,
                    "heading_path": [1],
                }
            ],
        }
        members[role] = member
        documents.append(
            {
                "package_role": role,
                "member_id": role,
                "document_version_id": doc,
                "file_digest": digest_bytes(raw),
                "byte_size": len(raw),
                "parse": identity,
                "page_count": 1,
                "pages": [{"physical_page": 1, "quality": "usable", "gaps": []}],
                "blocks": [
                    {
                        **{k: v for k, v in b.items() if k not in {"bbox", "structure"}},
                        "bbox_json": b["bbox"],
                        "structure_json": b["structure"],
                    }
                    for b in blocks
                ],
            }
        )
    identity = {"binding_status": "confirmed", "digest": digest("synthetic identity")}
    packages = {}
    for role in ("target", "authority"):
        manifest = {"members": [members[role]], "revision_id": uid(50 if role == "target" else 51)}
        packages[role] = {"manifest": manifest, "digest": digest(manifest)}
    inventory = {"manifest": {"requirements": []}, "digest": digest({"requirements": []})}
    refs = [
        {
            "member_id": "authority",
            "document_version_id": uid(2),
            "file_digest": native[1]["source_digest"],
            "parse_run_id": uid(12),
            "physical_page": 1,
            "evidence_id": b["id"],
            "evidence_digest": b["digest"],
            "text_content": b["text_content"],
            "part_ids": ["authority"],
        }
        for b in native[1]["blocks"]
    ]
    rules = []
    for index, selection in ((61, "include"), (62, "exclude")):
        snapshot = {
            "id": uid(index),
            "kind": "scoring",
            "statement": "Synthetic complete clause",
            "conditions": ["all sections apply"],
            "exceptions": ["except explicit omission"],
            "max_points": "10",
            "evidence_ids": [r["evidence_id"] for r in refs],
            "bands": [
                {"label": "same label", "description": "complete", "points": "10"},
                {"label": "same label", "description": "partial", "points": "0"},
            ],
            "provenance_status": "effective",
        }
        rules.append(
            {
                "rule_id": uid(index),
                "rule_digest": digest(snapshot),
                "selection": selection,
                "part_ids": ["target"] if selection == "include" else [],
                "reason": "Synthetic declared scope",
                "rule_snapshot": snapshot,
                "requirement_digest": digest("synthetic requirement"),
                "declared_target_part_ids": ["target"],
                "source_evidence": deepcopy(refs),
            }
        )
    preview = {
        "manifest": {
            "scope": {"bid_id": uid(40)},
            "documents": documents,
            "rules": rules,
            "parts": [
                {
                    "part": members["target"]["parts"][0],
                    "document_version_id": uid(1),
                    "selected": True,
                }
            ],
            "basis": {
                "package_digest": packages["target"]["digest"],
                "authority_digest": packages["authority"]["digest"],
                "inventory_digest": inventory["digest"],
                "identity_digest": identity["digest"],
            },
            "coverage": {"required_range_completeness": "unproven"},
        }
    }
    scope = {
        "manifest": {
            "id": uid(41),
            "preview": preview,
            "original_verification": {
                "files": [
                    {
                        "document_version_id": d["document_version_id"],
                        "digest": d["source_digest"],
                        "byte_size": d["source_byte_size"],
                    }
                    for d in native
                ]
            },
        }
    }
    material = {
        "version": "package-current-material-projection/1",
        "scope": scope,
        **packages,
        "inventory": inventory,
        "current_identity": identity,
        "native_documents": native,
        "page_asset_manifests": {k: b.manifest for k, b in bundles.items()},
    }
    meta = {
        "version": "package-current-material-observation/1",
        "method_digest": current.method_digest(),
        "bid_id": uid(40),
        "scope_id": uid(41),
        "input_authority_granted": False,
        "execution_authorized": False,
        "necessary_scope_verified": False,
        "historical_existence_verified": False,
    }
    return reseal(current.CurrentMaterial(meta, material, originals, bundles))


def context(origin):
    return inputs.build_context(
        origin,
        expected_observation_digest=origin.metadata["digest"],
        expected_material_digest=origin.metadata["material_digest"],
        expected_method_digest=inputs.context_method_digest(),
        provider_profile_digest=vision.profile_digest(),
        judgment_method_digest=vision.judgment_method_digest(),
        input_as_of="2026-10-24T00:00:00Z",
    )


def bound(origin):
    ctx = context(origin)
    binding = {
        "version": "package-technical-verification-binding/3",
        "verification_id": uid(90),
        "verification_receipt_digest": "a" * 64,
        "context_digest": ctx.metadata["digest"],
        "context_method_digest": inputs.context_method_digest(),
    }
    return inputs.bind_input(
        ctx,
        binding,
        expected_context_digest=ctx.metadata["digest"],
        expected_binding_digest=digest(binding),
        expected_method_digest=inputs.method_digest(),
    )


def prepared(bundle):
    return vision.prepare_request(
        bundle,
        uid(61),
        expected_input_digest=bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )


def judgment(bundle):
    m = bundle.context.metadata
    rule = next(r for r in m["rules"] if r["selection"] == "include")
    e = m["evidence_catalog"][0]
    return {
        "status": "valid",
        "coverage": "complete",
        "band_id": rule["bands"][0]["band_id"],
        "reason": "Synthetic explicit support",
        "covered_part_ids": ["target"],
        "dimensions": {
            "specificity": "supported",
            "validity": "supported",
            "consistency": "uncertain",
        },
        "evidence": [
            {
                "evidence_id": e["id"],
                "document_version_id": e["document_version_id"],
                "parse_run_id": e["parse_run_id"],
                "physical_page": e["physical_page"],
                "page_image_digest": e["page_image_digest"],
                "quote": e["text_content"],
                "region": None,
            }
        ],
    }


def response(data, **changes):
    return json.dumps(
        {
            "id": "synthetic-response",
            "model": vision.profile()["expected_response_model"],
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(data)},
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            **changes,
        }
    ).encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, raw, delay=0):
        self.raw = raw
        self.delay = delay

    async def __aiter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.raw

    async def aclose(self):
        pass


def send(request, raw, *, status=200, headers=None, timeout=60, delay=0):
    count = []

    async def transport(wire):
        assert str(wire.url) == vision.profile()["endpoint"] and wire.method == "POST"
        assert wire.content == request.body and wire.headers["accept-encoding"] == "identity"
        count.append(1)
        return httpx.Response(
            status,
            headers=headers or {"x-request-id": "synthetic-request"},
            stream=Stream(raw, delay),
        )

    client = provider.DeepSeekCompleteVisionClient(
        api_key="explicit-synthetic-test-key",
        total_timeout=timeout,
        transport=httpx.MockTransport(transport),
    )
    return client, count


def test_full_multi_source_bands_exclusions_and_actual_inline_bytes(synthetic):
    bundle = bound(deepcopy(synthetic))
    request = prepared(bundle)
    payload = json.loads(request.body)
    texts = payload["messages"][1]["content"]
    material = json.loads(texts[0]["text"])
    rule = material["rule_packet"]
    assert len(rule["frozen_rule"]["source_evidence"]) == 3
    assert len(rule["bands"]) == 2 and rule["bands"][1]["source"]["points"] == "0"
    assert rule["bands"][0]["band_id"] != rule["bands"][1]["band_id"]
    assert material["all_rule_declarations"][1]["selection"] == "exclude"
    assert rule["frozen_rule"]["rule_snapshot"]["exceptions"] == ["except explicit omission"]
    assert material["material"] == bundle.context.origin.material
    images = bundle.context.metadata["images"]
    assert len(images) == 3
    for index, row in enumerate(images):
        actual = base64.b64decode(texts[2 + index * 2]["image_url"]["url"].split(",", 1)[1])
        assert digest_bytes(actual) == row["asset"]["sha256"]
    assert "image/png;base64" not in repr(request)
    assert len(request.body) == request.receipt["body_byte_count"]
    assert bundle.metadata["native_binding_verified"] is False


def test_context_is_acyclic_and_cannot_be_sent(synthetic):
    ctx = context(deepcopy(synthetic))
    assert (
        "binding_reference" not in ctx.metadata
        and "verification_receipt_digest" not in ctx.metadata
    )
    with pytest.raises(inputs.MaterialInputError):
        vision.prepare_request(
            ctx,
            uid(61),
            expected_input_digest=ctx.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )


@pytest.mark.parametrize(
    "field", ["context_digest", "context_method_digest", "verification_receipt_digest"]
)
def test_wrong_native_reference_or_zero_receipt_rejects(synthetic, field):
    ctx = context(deepcopy(synthetic))
    ref = {
        "version": "package-technical-verification-binding/3",
        "verification_id": uid(90),
        "verification_receipt_digest": "a" * 64,
        "context_digest": ctx.metadata["digest"],
        "context_method_digest": inputs.context_method_digest(),
    }
    ref[field] = "0" * 64
    with pytest.raises(inputs.MaterialInputError):
        inputs.bind_input(
            ctx,
            ref,
            expected_context_digest=ctx.metadata["digest"],
            expected_binding_digest=digest(ref),
            expected_method_digest=inputs.method_digest(),
        )


@pytest.mark.parametrize(
    "mutation", ["original", "image", "material", "context_false_to_zero", "binding_extra"]
)
def test_private_mutation_and_extra_fields_are_rejected(synthetic, mutation):
    b = bound(deepcopy(synthetic))
    if mutation == "original":
        b.context.origin.originals[uid(1)] = b"changed"
    elif mutation == "image":
        key = next(iter(b.context.origin.page_bundles[uid(1)].blobs))
        b.context.origin.page_bundles[uid(1)].blobs[key] = b"changed"
    elif mutation == "material":
        b.context.metadata["material"]["scope"]["manifest"]["preview"]["manifest"]["rules"][0][
            "reason"
        ] = "changed"
    elif mutation == "context_false_to_zero":
        b.context.metadata["native_binding_verified"] = 0
    else:
        b.metadata["binding_reference"]["extra"] = "unexpected"
    with pytest.raises((inputs.MaterialInputError, ValueError)):
        prepared(b)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_source",
        "wrong_source_parse",
        "source_quote",
        "source_digest",
        "rule_snapshot",
        "private_locator",
    ],
)
def test_rehashed_incomplete_or_misbound_material_is_not_accepted(synthetic, mutation):
    origin = deepcopy(synthetic)
    rule = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"][0]
    if mutation == "missing_source":
        rule["source_evidence"].pop()
    elif mutation == "wrong_source_parse":
        rule["source_evidence"][0]["parse_run_id"] = uid(99)
    elif mutation == "source_quote":
        rule["source_evidence"][0]["text_content"] = "fabricated"
    elif mutation == "source_digest":
        rule["source_evidence"][0]["file_digest"] = "d" * 64
    elif mutation == "rule_snapshot":
        rule["rule_snapshot"]["bands"].pop()
    else:
        origin.material["object_key"] = "synthetic-private-key"
    reseal(origin)
    with pytest.raises(inputs.MaterialInputError):
        context(origin)


def test_excluded_rule_is_retained_but_cannot_prepare_call(synthetic):
    b = bound(deepcopy(synthetic))
    with pytest.raises(inputs.MaterialInputError, match="RULE_NOT_EXECUTABLE"):
        vision.prepare_request(
            b,
            uid(62),
            expected_input_digest=b.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )


def test_body_limit_rejects_without_truncation(synthetic, monkeypatch):
    b = bound(deepcopy(synthetic))
    monkeypatch.setattr(vision, "MAX_BODY_BYTES", 1)
    with pytest.raises(inputs.MaterialInputError, match="BODY_LIMIT"):
        prepared(b)


def test_explicit_single_post_response_and_citation_check(synthetic):
    b = bound(deepcopy(synthetic))
    request = prepared(b)
    client, count = send(request, response(judgment(b)))
    generated = client.generate(
        request,
        expected_request_digest=request.receipt["request_digest"],
        expected_profile_digest=vision.profile_digest(),
    )
    checked = vision.check_judgment(
        b,
        request,
        generated,
        expected_input_digest=b.metadata["digest"],
        expected_request_digest=request.receipt["request_digest"],
    )
    assert len(count) == 1 and checked["valid_slot"] is True
    assert generated.usage == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
    assert checked["execution_authorized"] is False


@pytest.mark.parametrize(
    "mutation",
    ["band", "quote", "parse", "page_image", "region", "missing_parts", "raw_data_mismatch"],
)
def test_invalid_model_semantics_or_mutable_generation_cannot_be_counted(synthetic, mutation):
    b = bound(deepcopy(synthetic))
    request = prepared(b)
    data = judgment(b)
    if mutation == "band":
        data["band_id"] = "fabricated"
    elif mutation == "quote":
        data["evidence"][0]["quote"] = "fabricated"
    elif mutation == "parse":
        data["evidence"][0]["parse_run_id"] = uid(99)
    elif mutation == "page_image":
        data["evidence"][0]["page_image_digest"] = "d" * 64
    elif mutation == "region":
        data["evidence"][0]["region"] = [0, 0, 10000, 10000]
    elif mutation == "missing_parts":
        data["covered_part_ids"] = []
    generated = parse_response(
        response(data), "synthetic-request", request.receipt["request_digest"]
    )
    if mutation == "raw_data_mismatch":
        generated.data["reason"] = "tampered parsed object"
    with pytest.raises(inputs.MaterialInputError):
        vision.check_judgment(
            b,
            request,
            generated,
            expected_input_digest=b.metadata["digest"],
            expected_request_digest=request.receipt["request_digest"],
        )


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_failure_has_one_attempt_and_no_retry(synthetic, status):
    b = bound(deepcopy(synthetic))
    request = prepared(b)
    client, count = send(request, b"{}", status=status)
    with pytest.raises(VisionProviderError, match="COMPLETE_VISION_HTTP_ERROR"):
        client.generate(
            request,
            expected_request_digest=request.receipt["request_digest"],
            expected_profile_digest=vision.profile_digest(),
        )
    assert len(count) == 1


def test_timeout_preserves_unknown_without_retry(synthetic):
    b = bound(deepcopy(synthetic))
    request = prepared(b)
    client, count = send(request, b"{}", timeout=0.01, delay=0.1)
    with pytest.raises(VisionProviderError, match="COMPLETE_VISION_TIMEOUT") as caught:
        client.generate(
            request,
            expected_request_digest=request.receipt["request_digest"],
            expected_profile_digest=vision.profile_digest(),
        )
    assert len(count) == 1 and caught.value.details["billing_state"] == "unknown"
    assert caught.value.__context__ is None


@pytest.mark.parametrize("mutation", ["body", "extra", "flag_zero"])
def test_request_tamper_fails_before_any_send(synthetic, mutation):
    b = bound(deepcopy(synthetic))
    request = prepared(b)
    if mutation == "body":
        request = replace(request, body=request.body + b" ")
    elif mutation == "extra":
        request.receipt["extra"] = "unexpected"
    else:
        request.receipt["native_binding_verified"] = 0
    client, count = send(request, b"{}")
    with pytest.raises(DomainError, match="COMPLETE_VISION_REQUEST_MISMATCH"):
        client.generate(
            request,
            expected_request_digest=request.receipt["request_digest"],
            expected_profile_digest=vision.profile_digest(),
        )
    assert len(count) == 0


def test_response_receipt_cannot_be_rebound_to_another_included_rule(synthetic):
    origin = deepcopy(synthetic)
    second = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"][1]
    second["selection"] = "include"
    second["part_ids"] = ["target"]
    bundle = bound(reseal(origin))
    request = prepared(bundle)
    actual_digest = request.receipt["request_digest"]
    generated = parse_response(response(judgment(bundle)), "synthetic-request", actual_digest)
    another = vision.prepare_request(
        bundle,
        uid(62),
        expected_input_digest=bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    request.receipt.update(another.receipt)
    request.receipt["request_digest"] = actual_digest
    request.receipt["body_byte_count"] = len(request.body)
    with pytest.raises(inputs.MaterialInputError, match="RESPONSE_BINDING_MISMATCH"):
        vision.check_judgment(
            bundle,
            request,
            generated,
            expected_input_digest=bundle.metadata["digest"],
            expected_request_digest=actual_digest,
        )
