#!/usr/bin/env bash
# =============================================================================
# 整体健康检查：容器状态、入口与 API 就绪、Kafka 主题、数据库连接数、磁盘、备份新鲜度。
# 可用于上线验证、定时巡检（cron）与升级后的自动验证。
#
# 输出：每项 [ OK ] / [WARN] / [FAIL]；退出码 0 = 没有 FAIL；--strict 时 WARN 也算失败；1 = 有失败
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="healthcheck"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：scripts/healthcheck.sh [--strict] [--quiet] [-h]

  --strict   警告也视为失败（用于升级后的验收）
  --quiet    只输出 WARN / FAIL 与最后的汇总
USAGE
}
STRICT=0; QUIET=0
while (( $# > 0 )); do
  case "$1" in
    --strict) STRICT=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

n_ok=0; n_warn=0; n_fail=0
r_ok()   { n_ok=$(( n_ok + 1 ));     (( QUIET == 1 )) || printf '[ OK ] %s\n' "$*"; }
r_warn() { n_warn=$(( n_warn + 1 )); printf '%s[WARN] %s%s\n' "${C_YEL}" "$*" "${C_OFF}"; }
r_fail() { n_fail=$(( n_fail + 1 )); printf '%s[FAIL] %s%s\n' "${C_RED}" "$*" "${C_OFF}"; }

require_cmd docker curl df
docker info >/dev/null 2>&1 || { r_fail "无法连接 Docker 守护进程"; exit 1; }

# ---- 1. 容器状态 ----------------------------------------------------------------------
# 长期运行服务必须 running 且（定义了健康检查的）healthy；一次性服务必须以 0 退出
long_running=(postgres kafka milvus mlflow api web relay reaper worker-parse worker-ai worker-experiment worker-export)
oneshot=(migrate kafka-init)
declare -A state health exitcode
while read -r svc st hl ec; do
  state["${svc}"]="${st}"; health["${svc}"]="${hl}"; exitcode["${svc}"]="${ec}"
done < <(dc ps -a --format '{{.Service}} {{.State}} {{if .Health}}{{.Health}}{{else}}-{{end}} {{.ExitCode}}' 2>/dev/null || true)

for s in "${long_running[@]}"; do
  st="${state[${s}]:-missing}"; hl="${health[${s}]:--}"
  if [[ "${st}" != running ]]; then r_fail "服务 ${s}：状态 ${st}"
  elif [[ "${hl}" == unhealthy ]]; then r_fail "服务 ${s}：unhealthy"
  elif [[ "${hl}" == starting ]]; then r_warn "服务 ${s}：健康检查仍在 starting"
  else r_ok "服务 ${s}：running${hl:+ / ${hl}}"; fi
done
for s in "${oneshot[@]}"; do
  st="${state[${s}]:-missing}"; ec="${exitcode[${s}]:--}"
  if [[ "${st}" == exited && "${ec}" == 0 ]]; then r_ok "一次性任务 ${s}：已成功完成"
  else r_fail "一次性任务 ${s}：状态 ${st}，退出码 ${ec}（查看 docker compose logs ${s}）"; fi
done

# ---- 2. 入口与 API ---------------------------------------------------------------------
port="$(env_get WEB_HTTP_PORT 8080)"
if curl -fsS -m 5 -o /dev/null "http://127.0.0.1:${port}/nginx-health"; then r_ok "web：/nginx-health 可达（宿主机 127.0.0.1:${port}）"
else r_fail "web：/nginx-health 不可达（宿主机 127.0.0.1:${port}）"; fi

if dc exec -T api bidwb-healthcheck http http://127.0.0.1:8000/readyz >/dev/null 2>&1; then r_ok "api：/readyz 就绪（含数据库）"
else r_fail "api：/readyz 未就绪（数据库不可用或进程异常）"; fi

# 经 nginx 反代访问 API：未登录应返回 401（证明 web → api 链路通；返回 502/504 即链路故障）
code="$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/api/v1/me" || echo 000)"
case "${code}" in
  200|401|403) r_ok "web → api 反向代理正常（/api/v1/me 返回 ${code}）" ;;
  *) r_fail "web → api 反向代理异常（/api/v1/me 返回 ${code}）" ;;
esac
# SPA 回退：任意前端路由应返回 index.html
code="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/projects/healthcheck-probe" || echo 000)"
if [[ "${code}" == 200 ]]; then r_ok "前端 SPA 路由回退正常"; else r_fail "前端 SPA 路由回退异常（返回 ${code}）"; fi

# ---- 3. MLflow / Milvus -------------------------------------------------------------------
if dc exec -T mlflow python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4).status==200 else 1)" >/dev/null 2>&1; then
  r_ok "mlflow：/health 正常"
else r_warn "mlflow：/health 无响应（研究侧副记录，不影响业务判断）"; fi

# ---- 4. Kafka 主题 --------------------------------------------------------------------------
prefix="$(env_get KAFKA_TOPIC_PREFIX)"
topics="$(dc exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>/dev/null || true)"
missing=()
for t in job.parse job.ai job.experiment job.export domain.events; do
  grep -qx "${prefix}${t}" <<< "${topics}" || missing+=("${prefix}${t}")
done
if [[ -z "${topics}" ]]; then r_fail "Kafka：无法列出主题"
elif (( ${#missing[@]} > 0 )); then r_fail "Kafka：缺少主题 ${missing[*]}（重新执行 docker compose up -d kafka-init 或 docker compose run --rm kafka-init）"
else r_ok "Kafka：业务主题齐全"; fi

# ---- 5. PostgreSQL 连接数与大小 ---------------------------------------------------------------
if conn="$(pg_psql postgres -At -F ' ' -c "SELECT (SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'), current_setting('max_connections')::int" 2>/dev/null)"; then
  read -r used maxc <<< "${conn}"
  if (( used * 100 >= maxc * 70 )); then r_warn "PostgreSQL 连接数 ${used}/${maxc} ≥ 70%（按架构文档 8.1 应触发容量复审）"
  else r_ok "PostgreSQL 连接数 ${used}/${maxc}"; fi
else r_fail "PostgreSQL：无法查询"; fi

# ---- 6. 磁盘 ------------------------------------------------------------------------------------
check_disk() {   # 参数：描述 路径
  local desc="$1" path="$2" pct
  [[ -d "${path}" ]] || { r_warn "${desc}：目录 ${path} 不存在"; return; }
  pct="$(df -Pk "${path}" | awk 'NR==2 {gsub("%","",$5); print $5}')"
  if (( pct >= 85 )); then r_fail "${desc}（${path}）已用 ${pct}% ≥ 85%"
  elif (( pct >= 70 )); then r_warn "${desc}（${path}）已用 ${pct}% ≥ 70%（容量复审线）"
  else r_ok "${desc}（${path}）已用 ${pct}%"; fi
}
check_disk "Docker 数据盘" "$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
BDIR="$(backup_base_dir)"
check_disk "备份盘" "${BDIR}"

# ---- 7. 备份新鲜度 ------------------------------------------------------------------------------------
if [[ -f "${BDIR}/.last-success" ]]; then
  age=$(( $(date +%s) - $(file_mtime "${BDIR}/.last-success") ))
  if (( age > 50 * 3600 )); then r_fail "最近一次成功备份在 $(human_age "${age}") 前（RPO 目标 24 小时）"
  elif (( age > 26 * 3600 )); then r_warn "最近一次成功备份在 $(human_age "${age}") 前（>26 小时）"
  else r_ok "最近一次成功备份在 $(human_age "${age}") 前"; fi
else
  r_warn "没有任何成功备份记录（${BDIR}/.last-success）"
fi

# ---- 汇总 -------------------------------------------------------------------------------------------------
printf '\n汇总：%d 通过，%d 警告，%d 失败\n' "${n_ok}" "${n_warn}" "${n_fail}"
if (( n_fail > 0 )); then exit 1; fi
if (( STRICT == 1 && n_warn > 0 )); then exit 1; fi
exit 0
