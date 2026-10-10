#!/usr/bin/env bash
# =============================================================================
# 升级：预检 → 获取新镜像 → 备份 → 迁移 → 按序滚动重启 → 验证；失败给出回退指引。
#
# 前提：你已在 .env 里把 APP_IMAGE / WEB_IMAGE / MLFLOW_IMAGE（及需要升级的第三方镜像）改成新版本标签。
# 流程中的“滚动”是指逐个服务重建并等待健康，而不是整栈同时重启；单机单副本的 API 在重建的几秒内仍会短暂不可用。
#
# 迁移是前进式的（0001 起，追加保存表有触发器，不提供降级）。因此：
#   - 迁移失败或升级后发现问题，镜像可以用 `upgrade.sh rollback` 回到旧版本；
#   - 但已执行的迁移不会回退。旧版本程序必须兼容新结构（升级策略：先加字段、双读过渡，再迁移历史，最后停旧写入）；
#     如果新迁移不向后兼容，必须恢复升级前的备份：scripts/restore.sh --backup <升级前批次> --in-place --yes
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="upgrade"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：
  scripts/upgrade.sh [--pull | --build] [--skip-backup] [--yes]
  scripts/upgrade.sh rollback [--yes]

选项：
  --pull          docker compose pull 获取新镜像（镜像来自镜像仓库时用）
  --build         docker compose build api web mlflow（在本机构建时用）
  （二者都不给）  假定新镜像已经在本机（比如已 docker load），脚本只做存在性检查
  --skip-backup   跳过升级前备份（强烈不建议）
  --yes           不询问确认（用于自动化）
  rollback        把镜像回退到上次升级前记录的版本（不回退数据库，见脚本头注释）
USAGE
}

MODE=upgrade; FETCH=none; SKIP_BACKUP=0; YES=0
if [[ "${1:-}" == rollback ]]; then MODE=rollback; shift; fi
while (( $# > 0 )); do
  case "$1" in
    --pull) FETCH=pull ;;
    --build) FETCH=build ;;
    --skip-backup) SKIP_BACKUP=1 ;;
    --yes) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

require_cmd docker
STATE_DIR="${DEPLOY_DIR}/.upgrade-state"
STATE_FILE="${STATE_DIR}/previous.env"

# 服务 → 镜像变量
declare -A IMAGE_VAR=(
  [api]=APP_IMAGE [web]=WEB_IMAGE [mlflow]=MLFLOW_IMAGE
  [postgres]=POSTGRES_IMAGE [kafka]=KAFKA_IMAGE [milvus]=MILVUS_IMAGE
)
# 重启顺序：基础设施 → 一次性任务 → 后台进程 → 研究侧 → API → 入口
INFRA=(postgres kafka milvus)
BACKGROUND=(relay reaper worker-parse worker-ai worker-experiment worker-export)

confirm() {
  (( YES == 1 )) && return 0
  [[ -t 0 ]] || die "非交互环境必须加 --yes"
  local ans; read -r -p "$1 [y/N] " ans
  [[ "${ans}" == y || "${ans}" == Y ]] || die "已取消"
}

wait_ready() {   # 参数：服务 [超时秒]
  local svc="$1" timeout="${2:-180}" waited=0 st hl
  while (( waited < timeout )); do
    st="$(dc ps --format '{{.State}}' "${svc}" 2>/dev/null | head -n1)"
    hl="$(dc ps --format '{{.Health}}' "${svc}" 2>/dev/null | head -n1)"
    if [[ "${st}" == running && ( -z "${hl}" || "${hl}" == healthy ) ]]; then return 0; fi
    if [[ "${st}" == exited || "${hl}" == unhealthy ]]; then break; fi
    sleep 3; waited=$(( waited + 3 ))
  done
  warn "${svc} 未在 ${timeout} 秒内就绪（状态 ${st:-?}/${hl:-?}）；日志：docker compose logs --tail 80 ${svc}"
  return 1
}

restart_service() {   # 重建（配置/镜像变化才会真的重建）并等待就绪
  info "更新 $1 ..."
  dc up -d --no-deps "$1" >/dev/null
  wait_ready "$1"
}

run_oneshot() {       # 参数：服务名。用 up 而不是 run，保证容器以新镜像重建并留下可查询的退出状态
  info "执行一次性任务 $1 ..."
  dc up --no-deps --force-recreate --exit-code-from "$1" "$1"
}

rolling_restart() {
  local s
  dc up -d "${INFRA[@]}" >/dev/null
  for s in "${INFRA[@]}"; do wait_ready "${s}" 240 || return 1; done
  run_oneshot kafka-init || return 1
  run_oneshot migrate || return 1
  for s in "${BACKGROUND[@]}" mlflow api web; do restart_service "${s}" || return 1; done
}

record_previous_images() {
  mkdir -p "${STATE_DIR}"
  : > "${STATE_FILE}"
  local svc cid img
  for svc in "${!IMAGE_VAR[@]}"; do
    cid="$(dc ps -q "${svc}" 2>/dev/null | head -n1)"
    if [[ -n "${cid}" ]]; then
      img="$(docker inspect -f '{{.Config.Image}}' "${cid}")"
      echo "PREV_${IMAGE_VAR[${svc}]}=${img}" >> "${STATE_FILE}"
    fi
  done
  echo "RECORDED_AT=$(date -u +%FT%TZ)" >> "${STATE_FILE}"
}

rollback_guidance() {
  cat >&2 <<GUIDE

${C_RED}升级未完成。回退指引：${C_OFF}
  1. 先看原因：docker compose ps -a；docker compose logs --tail 100 <服务>
  2. 镜像回退（不动数据库）：  scripts/upgrade.sh rollback
  3. 如果失败发生在「迁移」之后，且旧版本程序与新结构不兼容：
       scripts/restore.sh --backup ${BACKUP_ID:-<升级前批次>} --in-place --yes
     恢复后再执行 scripts/upgrade.sh rollback 使镜像与数据一致。
  4. 回退同时要恢复兼容的 worker、配置与发布路由；回退不撤销已经发生的业务事件（架构文档 8.3）。
  升级前备份批次：${BACKUP_ID:-（本次未备份）}
GUIDE
}

# ================================ rollback ================================
if [[ "${MODE}" == rollback ]]; then
  [[ -f "${STATE_FILE}" ]] || die "没有升级记录（${STATE_FILE}），无法自动回退；请手工把 .env 中的镜像标签改回旧版本后 docker compose up -d"
  cat "${STATE_FILE}" >&2
  warn "将把上面记录的镜像标签覆盖 .env 后重启服务；数据库不会被回退"
  confirm "确认回退镜像？"
  while IFS='=' read -r k v; do
    case "${k}" in PREV_*) export "${k#PREV_}=${v}" ;; *) ;; esac
  done < "${STATE_FILE}"
  # 注意：这里导出的环境变量优先于 .env，只对本次脚本内启动的容器生效；
  # 回退成功后请把 .env 里的标签也改回旧值，否则下次 docker compose up 会再次使用新标签。
  rolling_restart || die "回退过程中有服务未就绪，请人工检查"
  ok "镜像已回退。请把 .env 中的镜像标签改回上面记录的旧值，并执行 scripts/healthcheck.sh 验证"
  exit 0
fi

# ================================ upgrade =================================
info "1/7 预检 ..."
"$(dirname "${BASH_SOURCE[0]}")/preflight.sh"

info "2/7 获取新镜像 ..."
case "${FETCH}" in
  pull) dc pull ;;
  build) dc build api web mlflow ;;
  none) info "未指定 --pull / --build，只检查镜像是否已在本机" ;;
esac
missing=0
for svc in "${!IMAGE_VAR[@]}"; do
  var="${IMAGE_VAR[${svc}]}"
  img="$(env_get "${var}")"
  if ! docker image inspect "${img}" >/dev/null 2>&1; then warn "本机没有镜像 ${img}（${var}）"; missing=1; fi
done
(( missing == 0 )) || die "有镜像不在本机，请使用 --pull / --build 或先 docker load"

info "3/7 记录当前运行的镜像（用于回退）"
record_previous_images
cat "${STATE_FILE}" >&2
confirm "确认升级？（将备份、迁移并逐个重启服务）"

BACKUP_ID=""
if (( SKIP_BACKUP == 0 )); then
  info "4/7 升级前备份 ..."
  "$(dirname "${BASH_SOURCE[0]}")/backup.sh" --label "pre-upgrade" --no-prune
  BACKUP_ID="$(basename "$(readlink -f "$(backup_base_dir)/latest")")"
  echo "PRE_UPGRADE_BACKUP=${BACKUP_ID}" >> "${STATE_FILE}"
else
  warn "4/7 已跳过备份（--skip-backup）"
fi

info "5/7 按序更新服务（基础设施 → 创建主题 → 迁移 → 后台进程 → MLflow → API → 入口）"
if ! rolling_restart; then rollback_guidance; exit 1; fi

info "6/7 验证 ..."
sleep 5
if ! "$(dirname "${BASH_SOURCE[0]}")/healthcheck.sh" --strict; then rollback_guidance; exit 1; fi

info "7/7 完成"
ok "升级成功。升级前备份批次：${BACKUP_ID:-无}。请在 24 小时内观察任务失败率与日志；确认稳定前保留旧镜像。"
