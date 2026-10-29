"""Actual inline serialization and explicit HTTP MockTransport; zero paid calls."""

import asyncio
import base64
import io
import json
from copy import deepcopy
from uuid import UUID

import httpx
import pytest
from reportlab.pdfgen import canvas

from packages.contracts.package_technical_input import BINDING
from packages.domain.providers import deepseek_vision as provider
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_features as features
from packages.model_governance import package_technical_input as inputs
from packages.model_governance import package_technical_vision as vision
from packages.model_governance import technical_png as png


def uid(number):
    return str(UUID(int=number))


def frozen_material(*, target_pages=1, size=(100, 150), crop=True):
    documents, bundles, evidence, parts = [], {}, [], []
    for index, role, count in ((1, "target", target_pages), (2, "authority", 1)):
        text = f"Synthetic exact source {index}"
        data = io.BytesIO()
        pdf = canvas.Canvas(data, pagesize=size, invariant=1)
        for _ in range(count):
            pdf.drawString(2, min(10, size[1] - 1), text)
            pdf.showPage()
        pdf.save()
        raw = data.getvalue()
        bundle = assets.render_static_pdf(
            raw,
            document_version_id=uid(index),
            expected_source_digest=png.digest_bytes(raw),
            expected_source_size=len(raw),
            expected_method_digest=assets.render_method_digest(),
        )
        first = bundle.manifest["pages"][0]["asset"]
        if crop and index == 1:
            bundle = assets.crop_page_assets(
                bundle,
                [
                    {
                        "physical_page": 1,
                        "parent_image_digest": first["sha256"],
                        "rectangle": [0, 0, 10, 10],
                    }
                ],
                expected_manifest_digest=bundle.manifest["digest"],
                expected_method_digest=assets.crop_method_digest(),
            )
        bundles[uid(index)] = bundle
        documents.append(
            {
                "document_version_id": uid(index),
                "package_role": role,
                "source_digest": png.digest_bytes(raw),
                "source_byte_size": len(raw),
                "parse_run_id": uid(index + 10),
                "parse_digest": "a" * 64,
                "page_count": count,
                "asset_manifest_digest": bundle.manifest["digest"],
            }
        )
        parts.append(
            {
                "part_id": role,
                "document_version_id": uid(index),
                "parent_part_id": None,
                "related_part_ids": [],
                "physical_pages": list(range(1, count + 1)),
            }
        )
        evidence.append(
            {
                "evidence_id": uid(index + 20),
                "document_version_id": uid(index),
                "parse_run_id": uid(index + 10),
                "physical_page": 1,
                "part_ids": [role],
                "text": text,
                "text_digest": png.digest_bytes(text.encode()),
                "page_image_digest": first["sha256"],
                "page_width": first["width"],
                "page_height": first["height"],
            }
        )
    binding = {key: "b" * 64 for key in BINDING["properties"]}
    binding.update(
        scope_id=uid(50),
        input_as_of="2026-10-23T00:00:00Z",
        provider_profile_digest=vision.profile_digest(),
        judgment_method_digest=vision.judgment_method_digest(),
    )
    projection = {
        "version": "package-technical-input-projection/2",
        "binding": binding,
        "documents": documents,
        "parts": parts,
        "rules": [
            {
                "rule_id": uid(99),
                "rule_digest": "c" * 64,
                "source_evidence_id": uid(22),
                "source_quote": evidence[1]["text"],
                "source_quote_digest": evidence[1]["text_digest"],
                "required_part_ids": ["target"],
                "band_ids": [],
            }
        ],
        "evidence_catalog": evidence,
    }
    return projection, bundles


def material(**kwargs):
    projection, bundles = frozen_material(**kwargs)
    return inputs.build_input(
        projection,
        bundles,
        expected_projection_digest=digest(projection),
        expected_method_digest=inputs.method_digest(),
    )


def prepare(bundle):
    return vision.prepare_request(
        bundle,
        uid(99),
        expected_input_digest=bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )


@pytest.fixture(scope="module")
def bundle():
    return material()


@pytest.fixture(scope="module")
def request_packet(bundle):
    return prepare(bundle)


def judgment():
    return {
        "status": "unable_to_judge",
        "coverage": "partial",
        "band_id": None,
        "reason": "Synthetic diagnostic",
        "covered_part_ids": [],
        "dimensions": {key: "uncertain" for key in ("specificity", "validity", "consistency")},
        "evidence": [],
    }


def envelope(content=None):
    return {
        "id": "synthetic-response",
        "model": vision.MODEL,
        "system_fingerprint": "synthetic-fingerprint",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(judgment()) if content is None else content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def client(handler, **kwargs):
    return provider.DeepSeekVisionClient(
        api_key="synthetic-no-real-key", transport=httpx.MockTransport(handler), **kwargs
    )


def send(port, request):
    return port.generate(
        request,
        expected_request_digest=request.receipt["request_digest"],
        expected_profile_digest=vision.profile_digest(),
    )


def test_wire_contains_every_text_page_and_exact_png_in_frozen_order(bundle, request_packet):
    body = json.loads(request_packet.body)
    assert body["model"] == "deepseek-flash" and body["thinking"] == {"type": "disabled"}
    assert not body["stream"] and body["temperature"] == 0 and body["max_tokens"] == 4096
    assert set(body) == {
        "model",
        "thinking",
        "stream",
        "temperature",
        "max_tokens",
        "messages",
        "response_format",
    }
    assert [row["role"] for row in body["messages"]] == ["system", "user"]
    blocks = body["messages"][1]["content"]
    material_text = json.loads(blocks[0]["text"])
    assert material_text["material"] == bundle.metadata["material"]
    rows = bundle.metadata["material"]["pages"] + bundle.metadata["material"]["details"]
    assert len(blocks) == 1 + 2 * len(rows)
    for index, row in enumerate(rows):
        reference = json.loads(blocks[1 + 2 * index]["text"])
        assert reference["asset"] == row["asset"] and reference["image_index"] == index + 1
        image = blocks[2 + 2 * index]["image_url"]
        assert image["detail"] == "original" and image["url"].startswith("data:image/png;base64,")
        assert (
            base64.b64decode(image["url"].split(",", 1)[1], validate=True)
            == bundle.blobs[row["asset"]["id"]]
        )
    assert request_packet.receipt["body_byte_count"] == len(request_packet.body)
    assert request_packet.receipt["request_digest"] == png.digest_bytes(request_packet.body)
    assert not request_packet.receipt["model_token_limit_verified"]
    assert (
        not request_packet.receipt["visual_readability_verified"]
        and not request_packet.receipt["execution_authorized"]
    )
    assert "Synthetic" not in repr(request_packet)


def test_three_calls_have_identical_body_without_previous_answers_and_keep_raw_response(
    request_packet,
):
    observed = []

    def handler(request):
        observed.append(request.content)
        value = envelope()
        value["id"] = f"synthetic-{len(observed)}"
        return httpx.Response(200, json=value, headers={"x-ds-request-id": f"req-{len(observed)}"})

    port = client(handler)
    results = [send(port, request_packet) for _ in range(3)]
    assert observed == [request_packet.body] * 3
    assert len({row.response_id for row in results}) == 3
    assert [row.request_id for row in results] == ["req-1", "req-2", "req-3"]
    assert all(
        row.raw_response_digest == png.digest_bytes(row.raw_response)
        and not row.formal_scoring_eligible
        for row in results
    )
    assert all(
        row.system_fingerprint == "synthetic-fingerprint" and row.usage["total_tokens"] == 30
        for row in results
    )
    assert "Synthetic" not in repr(results[0])


def test_serializer_and_input_digests_cannot_be_replaced(bundle):
    for input_digest, serializer_digest in (
        ("0" * 64, vision.serializer_digest()),
        (bundle.metadata["digest"], "0" * 64),
    ):
        with pytest.raises(vision.VisionRequestError, match="MISMATCH"):
            vision.prepare_request(
                bundle,
                uid(99),
                expected_input_digest=input_digest,
                expected_serializer_digest=serializer_digest,
            )
    with pytest.raises(vision.VisionRequestError, match="RULE_NOT_UNIQUE"):
        vision.prepare_request(
            bundle,
            uid(999),
            expected_input_digest=bundle.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )


@pytest.mark.parametrize(
    "change", ["text", "blob", "missing_blob", "profile", "semantic", "material_digest"]
)
def test_changed_input_or_bytes_rejected_before_any_http(bundle, change):
    bad = inputs.TechnicalInputBundle(deepcopy(bundle.metadata), dict(bundle.blobs))
    if change == "text":
        bad.metadata["material"]["evidence_catalog"][0]["text"] = "changed"
    elif change == "blob":
        bad.blobs[next(iter(bad.blobs))] = b"changed"
    elif change == "missing_blob":
        bad.blobs.pop(next(iter(bad.blobs)))
    elif change == "profile":
        bad.metadata["material"]["binding"]["provider_profile_digest"] = "0" * 64
    elif change == "semantic":
        bad.metadata["rule_packets"][0]["semantic_input_digest"] = "0" * 64
    else:
        bad.metadata["material_digest"] = "0" * 64
    with pytest.raises(vision.VisionRequestError, match="MISMATCH"):
        vision.prepare_request(
            bad,
            uid(99),
            expected_input_digest=bundle.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )


@pytest.mark.parametrize("limit", ["MAX_BODY_BYTES", "MAX_IMAGES", "MAX_IMAGE_BYTES"])
def test_preflight_limits_reject_instead_of_dropping_images_or_resampling(monkeypatch, limit):
    monkeypatch.setattr(vision, limit, 1)
    with pytest.raises(vision.VisionRequestError, match="LIMIT"):
        prepare(material())


def test_many_image_dimension_limit_uses_fifteen_including_every_overview():
    prepare(material(target_pages=13, size=(1401, 5), crop=False))
    with pytest.raises(vision.VisionRequestError, match="IMAGE_LIMIT"):
        prepare(material(target_pages=14, size=(1401, 5), crop=False))


@pytest.mark.parametrize("mismatch", ["body", "profile"])
def test_wire_must_match_owned_reserved_request_before_send(request_packet, mismatch):
    seen = []
    port = client(lambda request: seen.append(request))
    with pytest.raises(DomainError, match="图文请求未绑定"):
        port.generate(
            request_packet,
            expected_request_digest="0" * 64
            if mismatch == "body"
            else request_packet.receipt["request_digest"],
            expected_profile_digest="0" * 64 if mismatch == "profile" else vision.profile_digest(),
        )
    assert not seen


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_http_failure_does_not_follow_redirect_retry_or_echo_raw(request_packet, status):
    seen = []
    marker = "synthetic-private-response-marker"

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, text=marker, headers={"location": "https://outside.invalid/"})

    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(handler), request_packet)
    error = caught.value
    assert (
        seen == [vision.ENDPOINT]
        and not error.retryable
        and error.details["billing_state"] == "unknown"
    )
    assert error.raw_complete and error.raw_response.decode() == marker
    assert marker not in str(error) + repr(error) + str(error.details)


@pytest.mark.parametrize(
    "change,code,billing",
    [
        (lambda v: v.update(model="other-model"), "INVALID_RESPONSE", "unknown"),
        (
            lambda v: v.update(
                usage={"prompt_tokens": True, "completion_tokens": 10, "total_tokens": 11}
            ),
            "INVALID_RESPONSE",
            "unknown",
        ),
        (
            lambda v: v["choices"][0].update(finish_reason="length"),
            "OUTPUT_INCOMPLETE",
            "usage_reported",
        ),
        (
            lambda v: v["choices"][0]["message"].update(content='{"wrong":true}'),
            "OUTPUT_INVALID",
            "usage_reported",
        ),
        (
            lambda v: v["choices"][0]["message"].update(content='{"a":1,"a":2}'),
            "OUTPUT_INVALID",
            "usage_reported",
        ),
        (
            lambda v: v["choices"][0]["message"].update(content='{"a":NaN}'),
            "OUTPUT_INVALID",
            "usage_reported",
        ),
        (
            lambda v: v.update(system_fingerprint={"secret": "not identifier"}),
            "INVALID_RESPONSE",
            "unknown",
        ),
    ],
)
def test_invalid_response_preserves_raw_and_precise_billing_without_retry(
    request_packet, change, code, billing
):
    value = envelope()
    change(value)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=value)

    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(handler), request_packet)
    error = caught.value
    assert (
        error.code == "VISION_" + code
        and error.details["billing_state"] == billing
        and len(seen) == 1
    )
    assert error.raw_complete and json.loads(error.raw_response) == value
    assert error.raw_response_digest == png.digest_bytes(error.raw_response)


def test_total_timeout_and_response_size_keep_unknown_billing(request_packet, monkeypatch):
    seen = []

    async def slow(request):
        seen.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=envelope())

    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(slow, total_timeout=0.001), request_packet)
    assert (
        caught.value.code == "VISION_TIMEOUT" and not caught.value.raw_complete and len(seen) == 1
    )
    monkeypatch.setattr(provider, "MAX_RESPONSE_BYTES", 16)
    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(lambda request: httpx.Response(200, content=b"x" * 100)), request_packet)
    assert caught.value.code == "VISION_RESPONSE_TOO_LARGE" and len(caught.value.raw_response) == 16
    assert not caught.value.raw_complete and caught.value.details["billing_state"] == "unknown"


def test_configuration_is_explicit_and_sync_entry_refuses_running_loop(request_packet):
    with pytest.raises(DomainError):
        provider.DeepSeekVisionClient(api_key="")
    with pytest.raises(DomainError):
        provider.DeepSeekVisionClient(api_key="synthetic", total_timeout=True)

    async def inside():
        with pytest.raises(DomainError) as caught:
            send(client(lambda r: httpx.Response(200, json=envelope())), request_packet)
        assert caught.value.code == "VISION_CALL_CONTEXT_INVALID"

    asyncio.run(inside())


@pytest.mark.parametrize("key", ["hidden\nvalue", "hidden value", "私有口令", "x" * 1025])
def test_invalid_credentials_fail_safely_before_header_construction(key):
    with pytest.raises(DomainError) as caught:
        provider.DeepSeekVisionClient(api_key=key)
    assert key not in str(caught.value) + str(caught.value.details)


def test_network_failure_and_duplicate_envelope_never_retry(request_packet):
    seen = []

    def broken(request):
        seen.append(request)
        raise httpx.ConnectError("synthetic-private-connection-marker", request=request)

    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(broken), request_packet)
    assert len(seen) == 1 and caught.value.code == "VISION_NETWORK_ERROR"
    assert "private-connection-marker" not in str(caught.value) + str(caught.value.details)
    raw = b'{"usage":{},"usage":{}}'
    with pytest.raises(provider.VisionProviderError) as caught:
        send(client(lambda request: httpx.Response(200, content=raw)), request_packet)
    assert caught.value.raw_response == raw and caught.value.raw_complete
    assert caught.value.code == "VISION_INVALID_RESPONSE"


@pytest.mark.parametrize("bad_quote", [False, True])
def test_actual_wire_responses_feed_features_but_invalid_citations_cannot_pass(
    bundle, request_packet, bad_quote
):
    catalog = bundle.metadata["material"]["evidence_catalog"]
    source = catalog[0]
    cite = {
        key: source[key]
        for key in (
            "evidence_id",
            "document_version_id",
            "parse_run_id",
            "physical_page",
            "page_image_digest",
        )
    }
    cite.update(quote="not in the source" if bad_quote else source["text"], region=None)
    value = judgment()
    value.update(status="valid", coverage="complete", covered_part_ids=["target"], evidence=[cite])
    observed = []

    def handler(request):
        observed.append(request.content)
        response = envelope(json.dumps(value))
        response["id"] = f"response-{len(observed)}"
        return httpx.Response(200, json=response)

    port = client(handler)
    calls = [send(port, request_packet) for _ in range(3)]
    packet = bundle.metadata["rule_packets"][0]
    rule = {key: packet["rule"][key] for key in ("rule_id", "rule_digest", "band_ids")}
    rule.update(
        required_part_ids=packet["required_part_ids"],
        semantic_input_digest=packet["semantic_input_digest"],
        request_digest=request_packet.receipt["request_digest"],
    )
    binding = bundle.metadata["material"]["binding"]
    attempts = [
        {
            "rule_id": rule["rule_id"],
            "slot": index,
            "attempt": 1,
            "call_id": uid(700 + index),
            "semantic_input_digest": rule["semantic_input_digest"],
            "request_digest": call.request_digest,
            "judgment_method_digest": binding["judgment_method_digest"],
            "provider_profile_digest": binding["provider_profile_digest"],
            "state": "succeeded",
            "response_model": call.model,
            "response_id": call.response_id,
            "response_digest": call.raw_response_digest,
            "judgment_digest": digest(call.data),
            "judgment": call.data,
        }
        for index, call in enumerate(calls, 1)
    ]
    projection = {
        "version": "package-technical-feature-projection/2",
        "binding": binding,
        "provider": {
            "provider_id": "deepseek",
            "model_alias": vision.MODEL,
            "response_model": vision.MODEL,
        },
        "max_attempts_per_slot": 1,
        "rules": [rule],
        "evidence_catalog": catalog,
        "attempts": attempts,
    }
    assert observed == [request_packet.body] * 3
    if bad_quote:
        with pytest.raises(features.FeatureProjectionError, match="FEATURE_QUOTE_MISMATCH"):
            features.build_features(
                projection,
                expected_projection_digest=digest(projection),
                expected_method_digest=features.method_digest(),
            )
    else:
        result = features.build_features(
            projection,
            expected_projection_digest=digest(projection),
            expected_method_digest=features.method_digest(),
        )
        assert (
            result["feature_coverage"] == "complete" and result["items"][0]["valid_slot_count"] == 3
        )


def test_preverification_context_cannot_be_sent_and_reference_binding_has_no_cycle():
    projection, bundles = frozen_material()
    projection["version"] = "package-technical-context-projection/2"
    projection["binding"].pop("input_verification_digest")
    context = inputs.build_verification_context(
        projection,
        bundles,
        expected_projection_digest=digest(projection),
        expected_method_digest=inputs.context_method_digest(),
    )
    with pytest.raises(vision.VisionRequestError, match="VISION_INPUT_INVALID"):
        prepare(context)
    record = {
        "version": "package-technical-verification-binding/2",
        "verification_id": uid(800),
        "verification_receipt_digest": png.digest_bytes(b"synthetic independent receipt"),
        "context_digest": context.metadata["digest"],
        "context_method_digest": context.metadata["context_method_digest"],
    }
    bound = inputs.bind_input(
        context,
        record,
        expected_context_digest=context.metadata["digest"],
        expected_binding_digest=digest(record),
        expected_method_digest=inputs.method_digest(),
    )
    request = prepare(bound)
    result = send(client(lambda request: httpx.Response(200, json=envelope())), request)
    assert result.request_digest == request.receipt["request_digest"]
    assert not result.formal_scoring_eligible and not bound.metadata["input_authority_granted"]
    assert (
        bound.metadata["material"]["binding"]["input_verification_digest"]
        == record["verification_receipt_digest"]
    )
