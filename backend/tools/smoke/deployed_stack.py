"""真实已部署栈的合成资料冒烟：登录、同源分片转传 OSS、自动评审和导出。

在 backend 中运行：python -m tools.smoke.deployed_stack --password-file ../deploy/secrets/admin_initial_password --out <目录>
会调用已部署 worker 配置的真实模型，保留带“合成冒烟”名称的项目，不确认规则、不登记提交。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
import uuid
import zipfile
from pathlib import Path

import httpx
import pypdfium2 as pdfium

from tests.pdfs import make_pdf


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base_url, timeout=180, trust_env=False) as api:

        def request(method: str, path: str, body: object = None) -> httpx.Response:
            headers = {"Idempotency-Key": str(uuid.uuid4())} if method != "GET" else {}
            response = api.request(method, "/api/v1" + path, json=body, headers=headers)
            if response.is_error:
                try:
                    code = response.json().get("code", "unknown")
                except ValueError:
                    code = "non_json_response"
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}, code={code}")
            return response

        login = request(
            "POST",
            "/auth/login",
            {
                "username": args.login,
                "password": args.password_file.read_text(encoding="utf-8").strip(),
            },
        ).json()
        api.headers["X-CSRF-Token"] = login["csrf_token"]
        assert request("GET", "/me").json()["member_id"] == login["member_id"]
        print("登录与会话验证通过", flush=True)
        if args.project_id:
            pid = args.project_id
            project = request("GET", f"/projects/{pid}").json()
            if not project["title"].startswith("合成冒烟："):
                raise RuntimeError("只允许复用合成冒烟项目")
            save(args.out / "project.json", project)
        else:
            project = request(
                "POST",
                "/projects",
                {
                    "title": f"合成冒烟：真实 OSS 与 DeepSeek {uuid.uuid4().hex[:8]}",
                    "tender_number": None,
                    "lot": "测试标段",
                    "round": 1,
                    "region": "合肥",
                    "engineering_type": "市政道路",
                    "deadline": None,
                },
            ).json()
            pid = project["project_id"]
            save(args.out / "project.json", project)
        tender = make_pdf(
            [
                ["第一章 工期要求", "总工期不得超过一百八十日历天，超过的按废标处理。"],
                ["第二章 质量要求", "工程质量必须达到合格标准。"],
                ["第三章 评标办法", "施工进度计划合理可行的得8分，计划不合理的得0分。", "技术标满分为8分。"],
            ]
        )
        body = make_pdf(
            [
                ["第一章 施工进度计划", "本工程计划总工期为二百四十日历天。"],
                ["第二章 质量保证", "本工程质量目标为合格，满足设计及验收规范。"],
                ["第三章 施工方法", "本工程为市政道路施工，分段施工，安排专业班组组织流水作业。"],
            ]
        )
        existing_roles = {row["role"] for row in request("GET", f"/projects/{pid}/files").json()}
        for role, data in (("tender", tender), ("body", body)):
            if role in existing_roles:
                continue
            digest = hashlib.sha256(data).hexdigest()
            upload = request(
                "POST",
                f"/projects/{pid}/uploads",
                {
                    "original_name": f"合成冒烟-{role}.pdf",
                    "role": role,
                    "byte_size": len(data),
                    "sha256": digest,
                    "media_type": "application/pdf",
                },
            ).json()
            parts = []
            for part in upload["parts"]:
                n = part["part_number"]
                if part["url"] != f"/api/v1/uploads/{upload['upload_id']}/parts/{n}":
                    raise RuntimeError("服务端未返回同源分片地址")
                chunk = data[(n - 1) * upload["part_bytes"] : n * upload["part_bytes"]]
                response = api.put(part["url"], content=chunk, headers={"Content-Type": "application/octet-stream"})
                if response.is_error:
                    raise RuntimeError(f"同源分片 PUT: HTTP {response.status_code}")
                parts.append({"part_number": n, "etag": response.headers["ETag"]})
            request("POST", f"/uploads/{upload['upload_id']}/complete", {"sha256": digest, "parts": parts})
            print(f"{role} 真实 OSS 分片上传与提交通过", flush=True)
        print(f"项目 {pid}", flush=True)
        if args.restart:
            request("POST", f"/projects/{pid}/analysis", {})
        end = time.monotonic() + args.timeout
        previous = None
        while time.monotonic() < end:
            pipeline = request("GET", f"/projects/{pid}/pipeline").json()
            save(args.out / "pipeline.json", pipeline)
            state = [(step["key"], step["state"]) for step in pipeline["steps"]]
            if state != previous:
                print(json.dumps({"stage": pipeline["stage"], "steps": state}, ensure_ascii=False), flush=True)
                previous = state
            if any(step["state"] == "failed" for step in pipeline["steps"]):
                for step in pipeline["steps"]:
                    if step["task_id"]:
                        save(args.out / f"task-{step['key']}.json", request("GET", f"/tasks/{step['task_id']}").json())
                raise RuntimeError("评审步骤失败，详情见 pipeline.json")
            if all(step["state"] == "done" for step in pipeline["steps"]):
                break
            time.sleep(5)
        else:
            raise RuntimeError("等待评审超时，详情见 pipeline.json")
        report = request("GET", f"/projects/{pid}/report").json()
        save(args.out / "report.json", report)
        save(args.out / "rules.json", request("GET", f"/projects/{pid}/rules").json())
        save(args.out / "findings.json", request("GET", f"/projects/{pid}/findings?limit=100").json())
        for step in pipeline["steps"]:
            if step["task_id"]:
                save(args.out / f"task-{step['key']}.json", request("GET", f"/tasks/{step['task_id']}").json())
        word = request("GET", f"/projects/{pid}/report.docx").content
        with zipfile.ZipFile(io.BytesIO(word)) as archive:
            assert "word/document.xml" in archive.namelist()
        (args.out / "report.docx").write_bytes(word)
        pdf = request("GET", f"/projects/{pid}/body.annotated.pdf").content
        with pdfium.PdfDocument(pdf) as document:
            assert len(document) == 3
        (args.out / "body.annotated.pdf").write_bytes(pdf)
        print(
            json.dumps(
                {
                    "result": "passed",
                    "project_id": pid,
                    "prediction_status": report["prediction"]["status"],
                    "categories": report["categories"],
                    "exports": ["docx", "pdf"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        request("POST", "/auth/logout")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--login", default="local-admin")
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-id", help="复用合成冒烟项目，补传缺少的角色并等待评审")
    parser.add_argument("--restart", action="store_true", help="重试已有项目的失败步骤")
    parser.add_argument("--timeout", type=int, default=900)
    options = parser.parse_args()
    try:
        raise SystemExit(run(options))
    except (httpx.HTTPError, OSError) as exc:
        raise SystemExit(f"联调连接或文件操作失败：{type(exc).__name__}（不输出可能含签名的 URL）") from None
