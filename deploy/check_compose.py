#!/usr/bin/env python3
"""生产编排静态校验（供 CI 运行，不启动任何容器）。

承接 design/verify_deploy.py 对参考编排的检查思路，并扩展到生产文件：
解析 compose.yml、compose.tls.yml、compose.dev.yml，合并出三种实际使用的组合
（生产 / 生产+TLS / 生产+开发），逐条断言安全与稳定性约束；再核对 .env.example 与 compose、脚本使用的变量是否一致（双向）。

用法：
    python3 deploy/check_compose.py                 # 在任意目录运行
    python3 deploy/check_compose.py --json          # 机器可读输出
    python3 deploy/check_compose.py --max-mem-gib 28

依赖：Python 3.9+ 与 PyYAML。若本机有 `docker compose`（只需要 CLI，不需要守护进程），
额外用 `docker compose --env-file .env.example config -q` 校验三种组合的语法；没有则跳过并在结果里说明。

【能证明什么 / 不能证明什么】
能证明：编排文件的结构性安全约束成立（见各检查项）。不能证明：镜像存在或可运行、容器内进程确实以非 root 运行、
只读根文件系统下第三方镜像能正常启动、资源限额合理、网络隔离在真实 Docker 上生效。这些需要真机验证（见 README“未验证项”）。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少 PyYAML：pip install pyyaml（或 pip install pyyaml --break-system-packages）")

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 白名单：每一条例外都必须写明理由，并与 compose.yml 文件头“例外清单”一致
# ---------------------------------------------------------------------------
# 不要求 read_only 的服务
READ_ONLY_EXEMPT = {
    "kafka": "官方 apache/kafka 镜像启动时要写入 /opt/kafka/config（生成 server.properties）",
    "milvus": "官方 Milvus 镜像的写入路径未文档化，未经实测前不启用只读根文件系统",
}
# 不要求显式非 root user 的服务
ROOT_EXEMPT = {
    "milvus": "官方 Milvus 镜像默认以 root 运行；已 cap_drop ALL 并只在 internal 网络",
}
# 允许 seccomp:unconfined 的服务
SECCOMP_EXEMPT = {
    "milvus": "Milvus 官方示例要求 seccomp:unconfined（未验证：当前版本是否仍必要）",
}
# 一次性任务：不要求 healthcheck，restart 必须是 "no"
ONESHOT = {"migrate", "kafka-init", "admin", "dev-init"}
# 数据服务：不得发布端口，只能在 data 网络
DATA_SERVICES = {"postgres", "kafka", "milvus"}
# 允许绑定回环地址发布端口的服务（生产）：MLflow 界面经 SSH 隧道访问
LOOPBACK_PUBLISH_PROD = {"mlflow"}
# 必须依赖 migrate 完成才能启动的服务
NEED_MIGRATE = {"api", "relay", "reaper", "worker-parse", "worker-ai", "worker-experiment", "worker-export", "admin"}
NEED_TOPICS = {"relay", "reaper", "worker-parse", "worker-ai", "worker-experiment", "worker-export"}
# 变量名白名单：由 compose 自身识别，不属于 .env.example 的约定变量
COMPOSE_NATIVE_VARS = {"COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES"}

SENSITIVE_KEY = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)")
URL_WITH_CREDS = re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@$]+:[^/\s@$]+@")
VAR_REF = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}")
SIMPLE_VAR_REF = re.compile(r"(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)")

# compose 合并语义里“追加而不是替换”的列表字段
APPEND_LISTS = {"ports", "volumes", "tmpfs", "cap_add", "cap_drop", "security_opt", "profiles", "expose", "extra_hosts", "dns"}


# ---------------------------------------------------------------------------
# 载入与合并
# ---------------------------------------------------------------------------
def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def normalize_service(svc: dict) -> dict:
    """把 compose 里允许的多种写法统一成一种，便于断言与合并。"""
    s = copy.deepcopy(svc)
    env = s.get("environment")
    if isinstance(env, list):
        s["environment"] = {k: v for k, _, v in (e.partition("=") for e in env)}
    dep = s.get("depends_on")
    if isinstance(dep, list):
        s["depends_on"] = {name: {"condition": "service_started"} for name in dep}
    nets = s.get("networks")
    if isinstance(nets, list):
        s["networks"] = {name: {} for name in nets}
    secs = s.get("secrets")
    if isinstance(secs, list):
        s["secrets"] = [x if isinstance(x, str) else x.get("source") for x in secs]
    return s


def merge_dict(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for key, bval in b.items():
        aval = out.get(key)
        if isinstance(aval, dict) and isinstance(bval, dict):
            out[key] = merge_dict(aval, bval)
        elif key in APPEND_LISTS and isinstance(aval, list) and isinstance(bval, list):
            out[key] = aval + [x for x in bval if x not in aval]
        else:
            out[key] = copy.deepcopy(bval)
    return out


def merge_compose(*docs: dict) -> dict:
    merged: dict = {}
    for doc in docs:
        doc = {k: v for k, v in doc.items() if not str(k).startswith("x-")}
        services = {n: normalize_service(s) for n, s in (doc.get("services") or {}).items()}
        merged_services = merged.get("services", {})
        for name, svc in services.items():
            merged_services[name] = merge_dict(merged_services.get(name, {}), svc)
        rest = {k: v for k, v in doc.items() if k != "services"}
        merged = merge_dict(merged, rest)
        merged["services"] = merged_services
    return merged


def parse_mem(value) -> float:
    """mem_limit → 字节。"""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*([\d.]+)\s*([kmgt]?)b?\s*", str(value).lower())
    if not m:
        raise ValueError(f"无法解析内存值 {value!r}")
    return float(m.group(1)) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}[m.group(2)]


# ---------------------------------------------------------------------------
# 检查框架
# ---------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def check(self, name: str, fn) -> None:
        try:
            problems = fn()
        except Exception as exc:  # 检查代码自身出错也算失败，避免静默通过
            problems = [f"检查执行出错：{type(exc).__name__}: {exc}"]
        problems = list(problems or [])
        self.items.append({"name": name, "status": "failed" if problems else "passed", "problems": problems})

    def skip(self, name: str, reason: str) -> None:
        self.items.append({"name": name, "status": "skipped", "problems": [reason]})

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if i["status"] == "failed")


def image_problem(svc_name: str, image: str, *, require_required_form: bool) -> str | None:
    if not image:
        return f"{svc_name}：没有 image"
    if "@sha256:" in image:
        return None
    refs = VAR_REF.findall(image)
    if not refs:
        return f"{svc_name}：镜像 {image!r} 没有使用变量标签，也不是固定摘要"
    for var, op in refs:
        if require_required_form and not op.startswith(":?"):
            return f"{svc_name}：镜像变量 ${{{var}{op}}} 应使用必填形式 ${{{var}:?提示}}"
        if op.startswith(":-") and re.search(r":latest(\b|$)", op[2:]):
            return f"{svc_name}：镜像默认值使用了 latest"
    if re.search(r":latest(\b|$)", image):
        return f"{svc_name}：镜像使用 latest"
    return None


def published_ports(svc: dict) -> list[str]:
    return [str(p) for p in svc.get("ports", []) or []]


def is_loopback_port(spec: str) -> bool:
    return spec.startswith("127.0.0.1:") or spec.startswith("[::1]:")


def env_names_in_text(text: str) -> set[str]:
    """文本里被引用的环境变量名（${VAR...} 与 $VAR，忽略 $$ 转义）。"""
    names = {m[0] for m in VAR_REF.findall(text)}
    names |= set(SIMPLE_VAR_REF.findall(text))
    return names


def parse_env_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--max-mem-gib", type=float, default=28.0, help="各服务 mem_limit 之和上限（GiB，默认 28，给宿主留 4 GiB）")
    ap.add_argument("--no-docker", action="store_true", help="不调用 docker compose config")
    args = ap.parse_args()

    base_raw = load_yaml(HERE / "compose.yml")
    tls_raw = load_yaml(HERE / "compose.tls.yml")
    dev_raw = load_yaml(HERE / "compose.dev.yml")
    env_example = parse_env_example(HERE / ".env.example")

    prod = merge_compose(base_raw)
    prod_tls = merge_compose(base_raw, tls_raw)
    prod_dev = merge_compose(base_raw, dev_raw)
    base_names = set(prod["services"])
    dev_only = set(prod_dev["services"]) - base_names

    rep = Report()
    variants = {"生产": prod, "生产+TLS": prod_tls, "生产+开发": prod_dev}

    # ---- 1. 结构 ------------------------------------------------------------------------------
    def structure():
        probs = []
        expected = {"web", "api", "migrate", "relay", "reaper", "worker-parse", "worker-ai", "worker-experiment",
                    "worker-export", "postgres", "kafka", "kafka-init", "milvus", "mlflow", "admin"}
        missing = expected - base_names
        if missing:
            probs.append(f"缺少服务：{sorted(missing)}")
        if base_raw.get("name") != "bidwb":
            probs.append("顶层 name 应为 bidwb（固定项目名，卷与网络名不随目录变化）")
        return probs

    rep.check("生产编排包含全部预期服务且固定项目名", structure)

    # ---- 2. 镜像 ------------------------------------------------------------------------------
    def images():
        probs = []
        for name, svc in prod["services"].items():
            p = image_problem(name, svc.get("image", ""), require_required_form=True)
            if p:
                probs.append(p)
        for name in dev_only:
            p = image_problem(name, prod_dev["services"][name].get("image", ""), require_required_form=False)
            if p:
                probs.append("[开发] " + p)
        for name in set(prod_dev["services"]) & base_names:
            img = prod_dev["services"][name].get("image", "")
            if img and image_problem(name, img, require_required_form=False):
                probs.append(f"[开发] {name}：{image_problem(name, img, require_required_form=False)}")
        # 构建参数里的基础镜像默认值也不允许 latest
        for doc_name, doc in (("compose.yml", base_raw), ("compose.dev.yml", dev_raw)):
            text = (HERE / doc_name).read_text(encoding="utf-8")
            if re.search(r"[A-Za-z0-9_./-]+:latest\b", text):
                probs.append(f"{doc_name}：出现 :latest")
        return probs

    rep.check("所有镜像使用变量标签（生产为必填形式）或固定摘要，不使用 latest", images)

    def env_images():
        probs = []
        for var, val in env_example.items():
            if var.endswith("_IMAGE"):
                if not val:
                    probs.append(f".env.example：{var} 为空")
                elif val.endswith(":latest") or (":" not in val.split("/")[-1] and "@sha256:" not in val):
                    probs.append(f".env.example：{var}={val} 没有固定标签")
        return probs

    rep.check(".env.example 中的镜像变量都带固定版本标签", env_images)

    # ---- 3. 端口与网络 -------------------------------------------------------------------------
    def ports():
        probs = []
        for vname, doc in (("生产", prod), ("生产+TLS", prod_tls)):
            for name, svc in doc["services"].items():
                pp = published_ports(svc)
                if not pp:
                    continue
                if name == "web":
                    continue
                if name in LOOPBACK_PUBLISH_PROD and all(is_loopback_port(p) for p in pp):
                    continue
                probs.append(f"[{vname}] {name} 发布了端口 {pp}（只有 web 可以对外发布；{sorted(LOOPBACK_PUBLISH_PROD)} 仅限回环地址）")
        for name in DATA_SERVICES:
            if published_ports(prod_tls["services"][name]):
                probs.append(f"数据服务 {name} 不得发布端口")
        for name, svc in prod_dev["services"].items():
            if name == "web":
                continue  # 开发组合里 web 被 profile 关闭（改用 vite），其端口声明来自生产文件
            for p in published_ports(svc):
                if not is_loopback_port(p):
                    probs.append(f"[开发] {name} 发布端口 {p} 未绑定 127.0.0.1")
        return probs

    rep.check("数据服务不发布端口；只有 web 对外，MLflow 与开发端口只绑回环地址", ports)

    def networks():
        probs = []
        nets = prod.get("networks", {})
        if not (nets.get("data") or {}).get("internal"):
            probs.append("data 网络必须 internal: true")
        if (nets.get("edge") or {}).get("internal") or (nets.get("egress") or {}).get("internal"):
            probs.append("edge / egress 不应是 internal（web 要发布端口，egress 要出网）")
        for name in DATA_SERVICES | {"migrate", "kafka-init", "relay", "admin"}:
            used = set((prod["services"][name].get("networks") or {}).keys())
            if used != {"data"}:
                probs.append(f"{name} 应只在 data 网络，实际 {sorted(used)}")
        # reaper 在自动评审开启时要写 OSS（冻结输入快照），需要出网；其余内部服务不出网
        reaper_nets = set((prod["services"]["reaper"].get("networks") or {}).keys())
        if reaper_nets != {"data", "egress"}:
            probs.append(f"reaper 应在 data 与 egress 网络，实际 {sorted(reaper_nets)}")
        web_nets = set(prod["services"]["web"].get("networks", {}))
        if web_nets != {"edge"}:
            probs.append(f"web 应只在 edge 网络，实际 {sorted(web_nets)}")
        for name, svc in prod["services"].items():
            if svc.get("network_mode"):
                probs.append(f"{name} 使用了 network_mode={svc['network_mode']}")
        return probs

    rep.check("data 网络 internal；数据服务与内部任务只在 data 网络；web 只在 edge", networks)

    # ---- 4. 加固 ------------------------------------------------------------------------------
    def hardening(doc: dict, label: str):
        probs = []
        for name, svc in doc["services"].items():
            if svc.get("privileged"):
                probs.append(f"[{label}] {name} privileged")
            if svc.get("pid") == "host" or svc.get("ipc") == "host":
                probs.append(f"[{label}] {name} 使用宿主机 pid/ipc 命名空间")
            if svc.get("cap_add"):
                probs.append(f"[{label}] {name} cap_add={svc['cap_add']}")
            for v in svc.get("volumes", []) or []:
                spec = v if isinstance(v, str) else v.get("source", "")
                if "docker.sock" in str(spec):
                    probs.append(f"[{label}] {name} 挂载了 docker.sock")
            if name in dev_only:
                continue
            caps = [str(c).upper() for c in svc.get("cap_drop", []) or []]
            if "ALL" not in caps:
                probs.append(f"[{label}] {name} 缺少 cap_drop: [ALL]")
            sec = [str(s) for s in svc.get("security_opt", []) or []]
            if "no-new-privileges:true" not in sec:
                probs.append(f"[{label}] {name} 缺少 no-new-privileges:true")
            for s in sec:
                if s.startswith("seccomp") and "unconfined" in s and name not in SECCOMP_EXEMPT:
                    probs.append(f"[{label}] {name} 关闭了 seccomp 但不在白名单")
            if not svc.get("read_only") and name not in READ_ONLY_EXEMPT:
                probs.append(f"[{label}] {name} 缺少 read_only: true 且不在白名单")
            if name not in ROOT_EXEMPT:
                user = str(svc.get("user", ""))
                uid = user.split(":")[0]
                if not user or not uid.isdigit() or int(uid) == 0:
                    probs.append(f"[{label}] {name} 必须显式以非 root 数字 uid 运行，实际 user={user!r}")
        return probs

    for vname, doc in variants.items():
        rep.check(f"[{vname}] 非 root、cap_drop ALL、no-new-privileges、只读根文件系统（白名单外无例外）", lambda d=doc, v=vname: hardening(d, v))

    def whitelist_valid():
        probs = []
        for table_name, table in (("READ_ONLY_EXEMPT", READ_ONLY_EXEMPT), ("ROOT_EXEMPT", ROOT_EXEMPT), ("SECCOMP_EXEMPT", SECCOMP_EXEMPT)):
            for name, reason in table.items():
                if name not in base_names:
                    probs.append(f"{table_name} 里的 {name} 已不在编排中，请清理白名单")
                if not reason.strip():
                    probs.append(f"{table_name}[{name}] 缺少理由")
        # 白名单里的服务确实偏离了规则（否则白名单是多余的）
        for name in READ_ONLY_EXEMPT:
            if prod["services"][name].get("read_only"):
                probs.append(f"{name} 已是 read_only，应从 READ_ONLY_EXEMPT 移除")
        return probs

    rep.check("例外白名单逐条有理由且仍然必要", whitelist_valid)

    # ---- 5. 健康检查 / 重启 / 日志 / 资源 -------------------------------------------------------------
    def health_restart():
        probs = []
        for name, svc in prod["services"].items():
            if name in ONESHOT:
                if str(svc.get("restart")) != "no":
                    probs.append(f"一次性任务 {name} 的 restart 应为 \"no\"")
                continue
            if "healthcheck" not in svc or not svc["healthcheck"].get("test"):
                probs.append(f"{name} 缺少 healthcheck")
            if svc.get("restart") != "unless-stopped":
                probs.append(f"{name} 的 restart 应为 unless-stopped，实际 {svc.get('restart')!r}")
        return probs

    rep.check("长期运行服务都有 healthcheck 且 restart: unless-stopped；一次性任务 restart: \"no\"", health_restart)

    def logging_rotation():
        probs = []
        for name, svc in prod_dev["services"].items():
            lg = svc.get("logging") or {}
            opts = lg.get("options") or {}
            if lg.get("driver") != "json-file" or not opts.get("max-size") or not opts.get("max-file"):
                probs.append(f"{name} 缺少 json-file 日志轮转（max-size / max-file）")
        return probs

    rep.check("全部服务（含开发服务）配置 json-file 日志轮转", logging_rotation)

    def resources():
        probs = []
        total_mem = 0.0
        total_cpu = 0.0
        for name, svc in prod["services"].items():
            if "mem_limit" not in svc or "cpus" not in svc:
                probs.append(f"{name} 缺少 mem_limit 或 cpus")
                continue
            if name not in ONESHOT:   # 一次性任务只在启动/升级时短暂运行，不计入常驻总量
                total_mem += parse_mem(svc["mem_limit"])
                total_cpu += float(svc["cpus"])
        gib = total_mem / 1024**3
        if gib > args.max_mem_gib:
            probs.append(f"mem_limit 之和 {gib:.1f} GiB 超过上限 {args.max_mem_gib} GiB")
        print(f"  （信息）常驻服务 mem_limit 之和 {gib:.2f} GiB，cpus 之和 {total_cpu:.2f}（宿主假定 8 vCPU / 32 GiB，未实测）", file=sys.stderr)
        return probs

    rep.check("每个服务有 mem_limit 与 cpus，且内存限额之和不超过宿主预算", resources)

    # ---- 6. secrets ---------------------------------------------------------------------------------
    def secrets():
        probs = []
        for vname, doc in variants.items():
            defined = doc.get("secrets", {}) or {}
            used: set[str] = set()
            for name, svc in doc["services"].items():
                for s in svc.get("secrets", []) or []:
                    used.add(s)
                    if s not in defined:
                        probs.append(f"[{vname}] {name} 引用了未定义的 secret {s}")
            for s, spec in defined.items():
                if "file" not in (spec or {}) or "environment" in (spec or {}):
                    probs.append(f"[{vname}] secret {s} 必须是 file 形式（不得用 environment）")
                elif not str(spec["file"]).startswith("./secrets/"):
                    probs.append(f"[{vname}] secret {s} 的 file 应位于 ./secrets/ 下，实际 {spec['file']}")
                if s not in used and vname == "生产":
                    probs.append(f"[{vname}] secret {s} 已定义但没有任何服务使用")
        # *_FILE 环境变量必须指向 /run/secrets，且文件名对应该服务实际挂载的 secret
        for vname, doc in variants.items():
            for name, svc in doc["services"].items():
                mounted = set(svc.get("secrets", []) or [])
                for k, v in (svc.get("environment") or {}).items():
                    if re.fullmatch(r"(BIDWB|POSTGRES|MINIO)_.*_FILE", str(k)):
                        m = re.fullmatch(r"/run/secrets/([a-z0-9_]+)", str(v))
                        if not m:
                            probs.append(f"[{vname}] {name}.{k}={v} 不是 /run/secrets/<名称>")
                        elif m.group(1) not in mounted:
                            probs.append(f"[{vname}] {name}.{k} 指向 {m.group(1)}，但该服务没有挂载这个 secret（后端启动时会读不到文件）")
        return probs

    rep.check("secrets 全部为文件；定义与使用一致；*_FILE 变量只指向本服务已挂载的 secret", secrets)

    # ---- 7. depends_on ------------------------------------------------------------------------------
    def depends():
        probs = []
        for vname, doc in (("生产", prod), ("生产+开发", prod_dev)):
            svcs = doc["services"]
            for name, svc in svcs.items():
                for dep, spec in (svc.get("depends_on") or {}).items():
                    if dep not in svcs:
                        if not any(dep in (s.get("profiles") or []) or True for s in []):
                            probs.append(f"[{vname}] {name} 依赖不存在的服务 {dep}")
                        continue
                    cond = (spec or {}).get("condition", "service_started")
                    target = svcs[dep]
                    if dep in ONESHOT:
                        if cond != "service_completed_successfully":
                            probs.append(f"[{vname}] {name}→{dep}：一次性任务必须用 service_completed_successfully")
                    elif target.get("healthcheck") and cond != "service_healthy":
                        probs.append(f"[{vname}] {name}→{dep}：目标有 healthcheck，应使用 service_healthy（实际 {cond}）")
            for name in NEED_MIGRATE & set(svcs):
                dep = (svcs[name].get("depends_on") or {}).get("migrate", {})
                if dep.get("condition") != "service_completed_successfully":
                    probs.append(f"[{vname}] {name} 必须等待 migrate 成功完成")
                if (svcs[name].get("depends_on") or {}).get("postgres", {}).get("condition") != "service_healthy":
                    probs.append(f"[{vname}] {name} 必须等待 postgres healthy")
            for name in NEED_TOPICS & set(svcs):
                dep = (svcs[name].get("depends_on") or {}).get("kafka-init", {})
                if dep.get("condition") != "service_completed_successfully":
                    probs.append(f"[{vname}] {name} 必须等待 kafka-init 完成")
        return probs

    rep.check("depends_on 全部带 condition：健康检查用 service_healthy，一次性任务用 service_completed_successfully", depends)

    def migrate_role():
        probs = []
        mig = prod["services"]["migrate"]
        if mig.get("secrets") != ["db_url_owner"]:
            probs.append("migrate 应只挂载库属主连接串 db_url_owner")
        cmd = " ".join(str(c) for c in (mig.get("command") or []))
        if "alembic upgrade head" not in cmd or "db_url_owner" not in cmd:
            probs.append("migrate 命令应为在 db_url_owner 下执行 alembic upgrade head")
        for name in ("api", "relay", "reaper", "worker-parse", "worker-ai", "worker-experiment", "worker-export"):
            if "db_url_owner" in (prod["services"][name].get("secrets") or []):
                probs.append(f"{name} 不应拿到库属主连接串")
        api_secrets = set(prod["services"]["api"].get("secrets") or [])
        if "db_url_worker" in api_secrets:
            probs.append("api 不应拿到 worker 的数据库凭据")
        for name in ("worker-parse", "worker-ai", "worker-experiment", "worker-export", "relay", "reaper"):
            if "db_url_api" in (prod["services"][name].get("secrets") or []):
                probs.append(f"{name} 不应拿到 API 的数据库凭据")
        return probs

    rep.check("迁移只用库属主角色；api 与 worker 数据库凭据互不相通", migrate_role)

    # ---- 8. 明文口令 -----------------------------------------------------------------------------------
    def plaintext():
        probs = []
        for vname, doc in variants.items():
            for name, svc in doc["services"].items():
                for k, v in (svc.get("environment") or {}).items():
                    sv = "" if v is None else str(v)
                    if URL_WITH_CREDS.search(sv):
                        probs.append(f"[{vname}] {name}.{k} 的值含 用户:口令@ 形式的连接串")
                    if SENSITIVE_KEY.search(str(k)) and not str(k).endswith("_FILE") and sv and not sv.startswith("${"):
                        probs.append(f"[{vname}] {name}.{k} 是敏感变量名且有字面值（应改用 *_FILE + secrets）")
                cmd = svc.get("command")
                cmd_text = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd or "")
                if URL_WITH_CREDS.search(cmd_text) or re.search(r"(?i)(password|secret)=\S{4,}", cmd_text.replace("$$(", "")):
                    probs.append(f"[{vname}] {name} 的 command 含明文凭据")
        for fname in ("compose.yml", "compose.tls.yml", "compose.dev.yml"):
            text = (HERE / fname).read_text(encoding="utf-8")
            if URL_WITH_CREDS.search(text):
                probs.append(f"{fname} 文本中出现 用户:口令@ 形式的连接串")
        for var, val in env_example.items():
            if SENSITIVE_KEY.search(var) and not var.endswith("_FILE") and val:
                probs.append(f".env.example：{var} 是敏感变量名却有值（口令只允许放在 secrets/）")
            if URL_WITH_CREDS.search(val):
                probs.append(f".env.example：{var} 含 用户:口令@ 形式的连接串")
        return probs

    rep.check("compose、.env.example 中没有明文口令或带口令的连接串", plaintext)

    # ---- 9. 变量双向一致 --------------------------------------------------------------------------------------
    def env_consistency():
        probs = []
        compose_text = "\n".join((HERE / f).read_text(encoding="utf-8") for f in ("compose.yml", "compose.tls.yml", "compose.dev.yml"))
        # 去掉 YAML 注释行里的 ${...} 示例，避免把说明文字当成引用
        code_text = "\n".join(line for line in compose_text.splitlines() if not line.lstrip().startswith("#"))
        used_in_compose = {n for n in env_names_in_text(code_text) if n not in COMPOSE_NATIVE_VARS}
        script_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((HERE / "scripts").glob("*.sh")))
        defined = set(env_example)
        for var in sorted(used_in_compose - defined):
            probs.append(f"compose 使用了 ${{{var}}}，但 .env.example 没有定义")
        for var in sorted(defined - used_in_compose):
            if not re.search(rf"\b{re.escape(var)}\b", script_text):
                probs.append(f".env.example 定义了 {var}，但 compose 与 scripts/ 都没有使用")
        return probs

    rep.check(".env.example 与 compose / 脚本使用的变量双向一致", env_consistency)

    # ---- 10. Dockerfile 与 nginx 模板的基本约束 ----------------------------------------------------------------------
    def dockerfiles():
        probs = []
        backend = (HERE.parent / "backend" / "Dockerfile")
        if backend.exists():
            text = backend.read_text(encoding="utf-8")
            last_stage = text.split("\nFROM ")[-1]
            if not re.search(r"^USER\s+\S*10001", last_stage, re.M) and "USER ${APP_UID}" not in last_stage:
                probs.append("backend/Dockerfile 运行阶段应以 uid 10001 运行（USER）")
            for needle in ("HEALTHCHECK", "PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1"):
                if needle not in last_stage:
                    probs.append(f"backend/Dockerfile 运行阶段缺少 {needle}")
            if re.search(r"\b(gcc|build-essential|apt-get install)\b", last_stage):
                probs.append("backend/Dockerfile 运行阶段不应安装编译器或系统包")
        else:
            probs.append("缺少 backend/Dockerfile")
        web = HERE.parent / "frontend" / "Dockerfile"
        if web.exists():
            text = web.read_text(encoding="utf-8")
            if "nginx-unprivileged" not in text:
                probs.append("frontend/Dockerfile 运行阶段应基于 nginx-unprivileged（非 root）")
            if "npm ci" not in text:
                probs.append("frontend/Dockerfile 应使用 npm ci")
        else:
            probs.append("缺少 frontend/Dockerfile")
        for f in (HERE.parent / "backend" / ".dockerignore", HERE.parent / "frontend" / ".dockerignore"):
            if not f.exists():
                probs.append(f"缺少 {f.relative_to(HERE.parent)}")
        return probs

    rep.check("Dockerfile：后端非 root/健康检查/不装编译器，前端基于 nginx-unprivileged；.dockerignore 齐全", dockerfiles)

    def nginx_templates():
        probs = []
        tdir = HERE.parent / "frontend" / "nginx" / "templates"
        text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(tdir.glob("*.template")))
        for needle, why in (
            ("server_tokens off", "隐藏版本号"), ("limit_req zone=web_login", "登录限流"), ("Content-Security-Policy", "CSP"),
            ("Strict-Transport-Security", "HSTS"), ("try_files $uri /index.html", "SPA 回退"), ("proxy_buffering off", "SSE/流式不缓冲"),
            ("client_max_body_size", "请求体上限"), ("gzip on", "gzip"), ("immutable", "静态资源长缓存"), ("connect-src 'self'", "CSP 限制同源连接"),
        ):
            if needle not in text:
                probs.append(f"nginx 模板缺少 {why}（{needle}）")
        return probs

    rep.check("nginx 模板包含必需的安全与性能配置", nginx_templates)

    # ---- 11. 脚本约束 ---------------------------------------------------------------------------------------------------------
    def scripts_check():
        probs = []
        for p in sorted((HERE / "scripts").glob("*.sh")):
            text = p.read_text(encoding="utf-8")
            if p.name != "lib.sh" and "set -Eeuo pipefail" not in text:
                probs.append(f"{p.name} 缺少 set -Eeuo pipefail")
            if p.name != "lib.sh" and "--help" not in text:
                probs.append(f"{p.name} 缺少 --help")
            if p.name != "lib.sh":
                if os.name == "nt":
                    mode = subprocess.run(
                        ["git", "ls-files", "--stage", "--", f"scripts/{p.name}"],
                        capture_output=True, text=True, cwd=HERE, check=False,
                    )
                    executable = mode.returncode == 0 and mode.stdout.startswith("100755 ")
                else:
                    executable = bool(p.stat().st_mode & 0o111)
                if not executable:
                    probs.append(f"{p.name} 没有可执行权限（Windows 检查 Git 索引中的权限）")
        sc = shutil.which("shellcheck")
        if sc:
            res = subprocess.run([sc, "-x", *map(str, sorted((HERE / "scripts").glob("*.sh")))], capture_output=True, text=True, cwd=HERE / "scripts")
            if res.returncode != 0:
                probs.append("shellcheck 未通过：\n" + res.stdout[-1500:])
        return probs

    rep.check("scripts/*.sh：严格模式、--help、可执行；shellcheck（若已安装）干净", scripts_check)

    # ---- 12. docker compose config（可选）-----------------------------------------------------------------------------------------
    def docker_config():
        probs = []
        combos = {"生产": ["compose.yml"], "生产+TLS": ["compose.yml", "compose.tls.yml"], "生产+开发": ["compose.yml", "compose.dev.yml"]}
        for label, files in combos.items():
            cmd = ["docker", "compose", "--env-file", ".env.example"]
            for f in files:
                cmd += ["-f", f]
            cmd += ["config", "-q"]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
            if res.returncode != 0:
                probs.append(f"[{label}] docker compose config 失败：{(res.stderr or res.stdout).strip()[:600]}")
        return probs

    if args.no_docker or not shutil.which("docker"):
        rep.skip("docker compose config 语法校验", "未安装 docker 或指定了 --no-docker")
    else:
        ver = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if ver.returncode != 0:
            rep.skip("docker compose config 语法校验", "docker compose 不可用")
        else:
            rep.check(f"docker compose config -q 语法校验（{ver.stdout.strip()}）", docker_config)

    # ---- 输出 ------------------------------------------------------------------------------------------------------------------------------------
    if args.json:
        print(json.dumps({"checks": rep.items, "failed": rep.failed}, ensure_ascii=False, indent=2))
    else:
        for item in rep.items:
            mark = {"passed": "通过", "failed": "失败", "skipped": "跳过"}[item["status"]]
            print(f"[{mark}] {item['name']}")
            for p in item["problems"]:
                print(f"        - {p}")
        passed = sum(1 for i in rep.items if i["status"] == "passed")
        print(f"\n汇总：{passed} 通过，{rep.failed} 失败，{sum(1 for i in rep.items if i['status'] == 'skipped')} 跳过")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
