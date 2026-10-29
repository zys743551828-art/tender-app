"""Explicit operator acceptance for the named Compose renderer, synthetic bytes only.

No public request mode or Worker hook invokes this module. It deliberately starts
a detached synthetic child to test cleanup of the complete container namespace.
"""

import argparse
import io
import json
import subprocess  # nosec B404
import sys
from uuid import UUID

from reportlab.pdfgen import canvas

from deploy.fusion_asset_runtime import (
    ROOT,
    AssetRuntimeError,
    FusionAssetRuntime,
    exclusive,
)
from packages.model_governance import technical_png as png


def synthetic_pdf():
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(300, 400), invariant=1)
    pdf.drawString(20, 360, "Synthetic isolated current page")
    pdf.setFillColorRGB(1, 0, 0)
    pdf.rect(20, 250, 100, 50, fill=1, stroke=0)
    pdf.showPage()
    pdf.setPageRotation(90)
    pdf.drawString(20, 220, "Second physical source page")
    pdf.save()
    return output.getvalue()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def stopped(runtime):
    identity = (
        runtime._command(runtime._compose(["ps", "--all", "--quiet", "asset-renderer"]))
        .decode()
        .strip()
    )
    state = runtime._inspect(identity)["State"]
    if state["Running"] or state["Pid"] != 0:
        raise ValueError("ASSET_ACCEPTANCE_CLEANUP_FAILED")
    return {"container_id": identity, "stopped_verified": True, "container_pid": 0}


def expect_failure(runtime, action, code):
    try:
        action()
    except AssetRuntimeError as error:
        if str(error) != code:
            raise ValueError("ASSET_ACCEPTANCE_WRONG_FAILURE") from None
    else:
        raise ValueError("ASSET_ACCEPTANCE_FAILURE_NOT_OBSERVED")
    return {"error_code": code, **stopped(runtime)}


def controller_crash(runtime, directory, expected_image_id, expected_source_digest):
    source = """import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from deploy.fusion_asset_runtime import FusionAssetRuntime
r=FusionAssetRuntime(expected_image_id=sys.argv[2],expected_source_digest=sys.argv[3])
with r._session() as (identity,_,receipt):
    r._command(["exec","--detach",identity,"python","-I","-c","from pathlib import Path; import time; Path('/tmp/synthetic_orphan_marker').write_text('synthetic'); time.sleep(300)"])
    observed=r._command(["exec",identity,"python","-I","-c","from pathlib import Path; import time; p=Path('/tmp/synthetic_orphan_marker'); end=time.monotonic()+3;\\nwhile not p.exists() and time.monotonic()<end: time.sleep(0.01)\\nprint(p.exists())"]).decode().strip()
    if observed != 'True': raise ValueError('synthetic child marker not created')
    Path(sys.argv[4]).write_text(json.dumps({'container_id':identity}),encoding='utf-8')
    os._exit(17)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            source,
            str(ROOT),
            expected_image_id,
            expected_source_digest,
            str(directory / "orphan.json"),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )  # nosec B603
    if result.returncode != 17:
        raise ValueError("ASSET_ACCEPTANCE_CONTROLLER_CRASH_NOT_OBSERVED")
    identity = json.loads((directory / "orphan.json").read_bytes())["container_id"]
    if not runtime._inspect(identity)["State"]["Running"]:
        raise ValueError("ASSET_ACCEPTANCE_ORPHAN_NOT_RUNNING")
    with runtime._session() as (fresh, _, receipt):
        absent = (
            runtime._command(
                [
                    "exec",
                    fresh,
                    "python",
                    "-I",
                    "-c",
                    "from pathlib import Path; print(Path('/tmp/synthetic_orphan_marker').exists())",
                ]
            )
            .decode()
            .strip()
        )  # nosec B108
        if fresh == identity or absent != "False":
            raise ValueError("ASSET_ACCEPTANCE_ORPHAN_RECOVERY_FAILED")
    remaining = runtime._command(["ps", "--all", "--quiet", "--filter", "id=" + identity]).strip()
    if remaining:
        raise ValueError("ASSET_ACCEPTANCE_OLD_CONTAINER_REMAINS")
    return {
        "controller_exit_code": 17,
        "orphan_container_id": identity,
        "orphan_running_after_controller_crash": True,
        "old_container_removed_before_next_original": True,
        "next_tmpfs_marker_absent": True,
        "recovery_receipt": receipt,
    }


def native(directory, *, expected_image_id, expected_source_digest):
    runtime = FusionAssetRuntime(
        expected_image_id=expected_image_id, expected_source_digest=expected_source_digest
    )
    profile = runtime.describe()
    write_json(directory / "runtime-description.json", profile)
    data = synthetic_pdf()
    arguments = {
        "document_version_id": str(UUID(int=9111)),
        "expected_source_digest": png.digest_bytes(data),
        "expected_source_size": len(data),
        "expected_render_method_digest": profile["render_method_digest"],
        "expected_crop_method_digest": profile["crop_method_digest"],
    }
    baseline = runtime.render(data, regions=[], **arguments)
    first = baseline.bundle.manifest["pages"][0]["asset"]
    regions = [
        {
            "physical_page": 1,
            "parent_image_digest": first["sha256"],
            "rectangle": [45, 250, 390, 480],
        }
    ]
    detail = runtime.render(data, regions=regions, **arguments)
    for before, after in zip(
        baseline.bundle.manifest["pages"], detail.bundle.manifest["pages"], strict=True
    ):
        if (
            baseline.bundle.blobs[before["asset"]["id"]]
            != detail.bundle.blobs[after["asset"]["id"]]
        ):
            raise ValueError("ASSET_ACCEPTANCE_FULL_PAGE_CHANGED")
    render_proof = {
        "profile_receipt": profile["execution_receipt"],
        "baseline_receipt": baseline.execution_receipt,
        "crop_receipt": detail.execution_receipt,
        "full_pages_retained_and_byte_equal_across_fresh_containers": True,
        "physical_pages": 2,
        "details": 1,
        "image_readability_or_input_authority_granted": False,
    }
    write_json(directory / "native-render-proof.json", render_proof)
    (directory / "synthetic-source.pdf").write_bytes(data)
    for row in detail.bundle.manifest["pages"]:
        (directory / f"page-{row['physical_page']}.png").write_bytes(
            detail.bundle.blobs[row["asset"]["id"]]
        )
    (directory / "detail.png").write_bytes(
        detail.bundle.blobs[detail.bundle.manifest["details"][0]["asset"]["id"]]
    )
    write_json(directory / "manifest.json", detail.bundle.manifest)

    bad = b"%PDF-synthetic-invalid-original"
    invalid = expect_failure(
        runtime,
        lambda: runtime.render(
            bad,
            regions=[],
            **{
                **arguments,
                "expected_source_digest": png.digest_bytes(bad),
                "expected_source_size": len(bad),
            },
        ),
        "ASSET_RENDER_REJECTED",
    )
    method = expect_failure(
        runtime,
        lambda: runtime.render(
            data, regions=[], **{**arguments, "expected_render_method_digest": "0" * 64}
        ),
        "ASSET_WORKER_METHOD_MISMATCH",
    )
    short = FusionAssetRuntime(
        expected_image_id=expected_image_id,
        expected_source_digest=expected_source_digest,
        hard_timeout_ms=1,
    )
    timeout = expect_failure(
        runtime, lambda: short.render(data, regions=[], **arguments), "ASSET_EXEC_WALL_TIMEOUT"
    )
    timeout.update(deadline_ms=1, native_pdf_parse_started_not_asserted=True)
    with exclusive():
        try:
            runtime.describe()
        except AssetRuntimeError as error:
            if str(error) != "ASSET_RUNTIME_BUSY":
                raise ValueError("ASSET_ACCEPTANCE_WRONG_LOCK_FAILURE") from None
        else:
            raise ValueError("ASSET_ACCEPTANCE_LOCK_NOT_EXCLUSIVE")
    with runtime._session() as (identity, _, old_receipt):
        runtime._command(
            [
                "exec",
                "--detach",
                identity,
                "python",
                "-I",
                "-c",
                "from pathlib import Path; import time; Path('/tmp/synthetic_cross_job_marker').write_text('synthetic'); time.sleep(300)",
            ]
        )  # nosec B108
        # The detached child must actually create its marker before cleanup.
        marker = (
            runtime._command(
                [
                    "exec",
                    identity,
                    "python",
                    "-I",
                    "-c",
                    "from pathlib import Path; import time; p=Path('/tmp/synthetic_cross_job_marker'); end=time.monotonic()+3;\nwhile not p.exists() and time.monotonic()<end: time.sleep(0.01)\nprint(p.exists())",
                ]
            )
            .decode()
            .strip()
        )  # nosec B108
        if marker != "True":
            raise ValueError("ASSET_ACCEPTANCE_CHILD_NOT_OBSERVED")
        old_identity = identity
    with runtime._session() as (identity, _, new_receipt):
        marker = (
            runtime._command(
                [
                    "exec",
                    identity,
                    "python",
                    "-I",
                    "-c",
                    "from pathlib import Path; print(Path('/tmp/synthetic_cross_job_marker').exists())",
                ]
            )
            .decode()
            .strip()
        )  # nosec B108
        if identity == old_identity or marker != "False":
            raise ValueError("ASSET_ACCEPTANCE_CROSS_JOB_RESIDUE")
    crash = controller_crash(runtime, directory, expected_image_id, expected_source_digest)
    faults = {
        "invalid_pdf": invalid,
        "wrong_method": method,
        "wall_timeout": timeout,
        "controller_crash": crash,
        "exclusive_controller": {"error_code": "ASSET_RUNTIME_BUSY"},
        "cross_job_reset": {
            "detached_child_marker_created_before_stop": True,
            "old_receipt": old_receipt,
            "new_receipt": new_receipt,
            "fresh_container_id_different": True,
            "next_tmpfs_marker_absent": True,
        },
    }
    write_json(directory / "native-fault-proof.json", faults)
    identifiers = [
        profile["execution_receipt"]["container_id"],
        baseline.execution_receipt["container_id"],
        detail.execution_receipt["container_id"],
        invalid["container_id"],
        method["container_id"],
        timeout["container_id"],
        old_receipt["container_id"],
        new_receipt["container_id"],
        crash["orphan_container_id"],
        crash["recovery_receipt"]["container_id"],
    ]
    if len(set(identifiers)) != 10:
        raise ValueError("ASSET_ACCEPTANCE_CONTAINER_REUSED")
    return {
        "actual_named_compose_sessions": 10,
        "all_renderer_containers_stopped": True,
        "controller_crash_recovery_verified": True,
        "actual_failure_paths": 3,
        "detached_child_reset_and_next_tmpfs": True,
        "business_writes": 0,
        "paid_calls": 0,
        "standalone_debug_containers_created": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-source-digest", required=True)
    parser.add_argument("--evidence-dir", default=".local/asset-runtime/final-native")
    args = parser.parse_args()
    directory = (ROOT / args.evidence_dir).resolve()
    private = (ROOT / ".local").resolve()
    if not private.is_relative_to(ROOT.resolve()) or not directory.is_relative_to(private):
        raise ValueError("ASSET_ACCEPTANCE_OUTPUT_OUTSIDE_WORKSPACE")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        result = native(
            directory,
            expected_image_id=args.expected_image_id,
            expected_source_digest=args.expected_source_digest,
        )
    finally:
        with exclusive():
            cleanup = FusionAssetRuntime(
                expected_image_id=args.expected_image_id,
                expected_source_digest=args.expected_source_digest,
            )
            cleanup._check_project()
            identity = (
                cleanup._command(cleanup._compose(["ps", "--all", "--quiet", "asset-renderer"]))
                .decode()
                .strip()
            )
            if identity:
                cleanup._stop(identity)
    write_json(directory / "summary.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
