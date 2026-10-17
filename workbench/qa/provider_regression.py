"""可重复provider回归编排；永不包含付费chat入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from qa.provider_preflight import ROOT, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["offline", "read-only", "oss-objects"], default="offline"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    modules = ["qa.provider_negative_probe"]
    if args.mode in ["read-only", "oss-objects"]:
        modules.append("qa.provider_preflight")
    if args.mode == "oss-objects":
        modules += ["qa.provider_oss_probe", "qa.provider_adapter_probe"]
    # 唯一付费chat刻意不在编排表内。offline不会读取providers.env。
    observed = [*ROOT.glob("packages/domain/providers/*.py"), *ROOT.glob("qa/provider*.py")]
    sources = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in observed
    }
    result = dict(
        scope="独立provider自动回归；不含任何chat或全局bucket写入",
        mode=args.mode,
        passed=True,
        paid_chat_requests=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        modules=[],
        sources_before=sources,
    )
    for module in modules:
        name = module.rsplit(".", 1)[1]
        target = args.output.resolve() / (name + ".json")
        print("Running", module, flush=True)
        child = subprocess.run(
            [sys.executable, "-m", module],
            cwd=ROOT,
            env=dict(os.environ, QA_PROVIDER_OUTPUT=str(target)),
            check=False,
        )
        payload = json.loads(target.read_text()) if target.exists() else {}
        passed = child.returncode == 0 and payload.get("passed") is True
        result["modules"].append(
            dict(
                module=module,
                passed=passed,
                result_path=target.name,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None,
            )
        )
        result["passed"] &= passed
        if not passed:
            break
    result["sources_stable"] = all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in sources.items()
    )
    result["passed"] &= result["sources_stable"]
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write(args.output / "result.json", result)
    print(dict(passed=result["passed"], modules=len(result["modules"]), paid_chat_requests=0))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
