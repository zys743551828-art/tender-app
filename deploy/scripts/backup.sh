#!/usr/bin/env bash
# =============================================================================
# 逻辑备份：业务库 bidwb、LangGraph 运行库 bidwb_runtime、MLflow 元数据库 mlflow
#
# 做什么
#   1. 对三个库分别 pg_dump -Fc（自定义格式，可选择性恢复），写入 BACKUP_DIR/<批次ID>/
#   2. 每个转储立即用 pg_restore --list 校验可读，并记录目录项数量、sha256
#   3. 记录清单 manifest.txt：批次时间、数据库版本、Alembic 版本、各库表数与总行数、镜像标签、OSS 桶
#      （这是“与对象存储配对”的依据：恢复时按同一批次的数据库与 OSS 对象版本一起核对）
#   4. 可选：执行 BACKUP_OSS_MANIFEST_CMD，把 OSS 对象清单一并存入批次目录
#   5. 按保留策略清理旧批次（近 N 份每日 + 近 M 个月的月度，默认 30 + 12）
#
# 不做什么（务必理解）
#   - 不备份 OSS 里的原件与产物本身：它们由 OSS 自己的版本控制 / 跨地域复制 / 定期复制到备份桶负责（架构文档 8.3）。
#   - 不备份 Kafka 与 Milvus：它们是派生数据，可由任务表与解析产物重建。
#   - 三个库依次转储，不是同一时刻的快照；各库之间没有跨库外键，业务库内部是一致快照。
#   - 备份成功 ≠ 可恢复：请定期用 scripts/restore.sh 做恢复演练（默认只恢复到新库，不影响线上）。
#   - 不包含 secrets 目录：它必须另行加密备份（见 README）。
#
# 退出码：0 成功；1 失败（批次被丢弃）；3 数据库备份成功但 OSS 清单命令失败（批次保留，需人工处理）
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="backup"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：scripts/backup.sh [选项]

选项：
  --label TEXT        批次备注，写入 manifest（例如 pre-upgrade）
  --dir DIR           备份目录（默认取 .env 的 BACKUP_DIR，缺省 ./backups）
  --keep-daily N      保留最近 N 份（默认取 .env 的 BACKUP_KEEP_DAILY，缺省 30）
  --keep-monthly M    另外保留最近 M 个月各月最早的一份（默认 BACKUP_KEEP_MONTHLY，缺省 12）
  --no-prune          本次不清理旧批次
  -h, --help          显示本帮助

示例（cron，每天 02:30）：
  30 2 * * * cd /opt/tender-app/deploy && scripts/backup.sh >> /var/log/bidwb-backup.log 2>&1
USAGE
}

LABEL=""
PRUNE=1
BACKUP_DIR_ARG=""
KEEP_DAILY_ARG=""
KEEP_MONTHLY_ARG=""
while (( $# > 0 )); do
  case "$1" in
    --label) LABEL="${2:?--label 需要参数}"; shift ;;
    --dir) BACKUP_DIR_ARG="${2:?--dir 需要参数}"; shift ;;
    --keep-daily) KEEP_DAILY_ARG="${2:?}"; shift ;;
    --keep-monthly) KEEP_MONTHLY_ARG="${2:?}"; shift ;;
    --no-prune) PRUNE=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "未知参数：$1" ;;
  esac
  shift
done

require_cmd docker sha256sum df
BACKUP_DIR="${BACKUP_DIR_ARG:-$(backup_base_dir)}"
[[ "${BACKUP_DIR}" = /* ]] || BACKUP_DIR="${DEPLOY_DIR}/${BACKUP_DIR#./}"
KEEP_DAILY="${KEEP_DAILY_ARG:-$(env_get BACKUP_KEEP_DAILY 30)}"
KEEP_MONTHLY="${KEEP_MONTHLY_ARG:-$(env_get BACKUP_KEEP_MONTHLY 12)}"
[[ "${KEEP_DAILY}" =~ ^[0-9]+$ && "${KEEP_DAILY}" -ge 1 ]] || die "keep-daily 必须是 >=1 的整数"
[[ "${KEEP_MONTHLY}" =~ ^[0-9]+$ ]] || die "keep-monthly 必须是整数"

umask 077
mkdir -p "${BACKUP_DIR}"

# 同一时刻只允许一个备份（避免 cron 与手工重叠）
if command -v flock >/dev/null 2>&1; then
  exec 9>"${BACKUP_DIR}/.lock"
  flock -n 9 || die "另一个备份正在运行（${BACKUP_DIR}/.lock）"
else
  warn "系统没有 flock，无法防止并发备份"
fi

require_postgres_running

BATCH_ID="$(date -u +%Y%m%d-%H%M%S)"
PARTIAL="${BACKUP_DIR}/.partial-${BATCH_ID}"
FINAL="${BACKUP_DIR}/${BATCH_ID}"
[[ ! -e "${FINAL}" ]] || die "批次目录已存在：${FINAL}"
mkdir -p "${PARTIAL}"
DONE=0
# shellcheck disable=SC2329  # 通过 trap 调用
cleanup() {
  if (( DONE == 0 )); then
    warn "备份未完成，丢弃临时目录 ${PARTIAL}"
    rm -rf -- "${PARTIAL}"
  fi
}
trap cleanup EXIT

# ---- 磁盘空间预检：可用空间至少要大于全部数据库总大小（转储经压缩通常更小，这里取保守值） ----
total_bytes="$(pg_psql postgres -At -c "SELECT COALESCE(sum(pg_database_size(datname)),0) FROM pg_database WHERE datname IN ('bidwb','bidwb_runtime','mlflow')")"
avail_kb="$(df -Pk "${BACKUP_DIR}" | awk 'NR==2 {print $4}')"
if (( avail_kb * 1024 < total_bytes )); then
  die "备份目录可用空间不足：可用 $(( avail_kb / 1024 )) MiB < 数据库总大小 $(( total_bytes / 1024 / 1024 )) MiB"
fi

info "开始备份批次 ${BATCH_ID}（目录 ${BACKUP_DIR}）"
started_epoch="$(date +%s)"

pg_version="$(pg_psql postgres -At -c 'SHOW server_version')"
alembic_rev="$(pg_psql bidwb -At -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo unknown)"

manifest="${PARTIAL}/manifest.txt"
{
  echo "# bidwb 备份清单（key=value；由 scripts/backup.sh 生成）"
  echo "batch_id=${BATCH_ID}"
  echo "created_at_utc=$(date -u +%FT%TZ)"
  echo "label=${LABEL}"
  echo "host=$(hostname)"
  echo "postgres_version=${pg_version}"
  echo "alembic_revision=${alembic_rev}"
  echo "app_image=$(env_get APP_IMAGE)"
  echo "web_image=$(env_get WEB_IMAGE)"
  echo "oss_bucket=$(env_get OSS_BUCKET)"
  echo "oss_endpoint=$(env_get OSS_ENDPOINT_URL)"
  echo "databases=${BIDWB_DATABASES[*]}"
} > "${manifest}"

for db in "${BIDWB_DATABASES[@]}"; do
  file="${PARTIAL}/${db}.dump"
  info "转储 ${db} ..."
  # pg_dump 在容器内以超级用户经本地套接字运行，输出经 docker exec 流回宿主机文件
  dc exec -T postgres pg_dump -U postgres -Fc --no-password "${db}" > "${file}"
  [[ -s "${file}" ]] || die "${db} 转储为空"

  # 目录读取校验：pg_restore --list 必须成功并带有归档头；空库（如 LangGraph/MLflow 尚未建表）目录项可以为 0
  toc="$(dc exec -T postgres pg_restore --list < "${file}")" || die "${db} 转储无法被 pg_restore 读取"
  grep -q '^; Archive created at' <<< "${toc}" || die "${db} 转储缺少归档头，文件异常"
  toc_entries="$(grep -vc '^;' <<< "${toc}" || true)"
  if (( toc_entries == 0 )); then warn "${db} 是空库（没有任何对象）；对尚未使用过的 LangGraph 运行库或 MLflow 属正常"; fi

  read -r tables rows < <(db_table_stats "${db}")
  size="$(stat -c %s "${file}")"
  sum="$(sha256sum "${file}" | awk '{print $1}')"
  {
    echo "db.${db}.file=${db}.dump"
    echo "db.${db}.bytes=${size}"
    echo "db.${db}.sha256=${sum}"
    echo "db.${db}.toc_entries=${toc_entries}"
    echo "db.${db}.tables=${tables}"
    echo "db.${db}.total_rows_at_backup=${rows}"
  } >> "${manifest}"
  ok "  ${db}：$(( size / 1024 )) KiB，目录项 ${toc_entries}，表 ${tables}，行 ${rows}"
done

# ---- OSS 对象清单（可选，由运维配置命令）----------------------------------------------
exit_code=0
oss_cmd="$(env_get BACKUP_OSS_MANIFEST_CMD)"
if [[ -n "${oss_cmd}" ]]; then
  info "生成 OSS 对象清单：${oss_cmd}"
  if bash -c "${oss_cmd}" > "${PARTIAL}/oss-manifest.txt" 2> "${PARTIAL}/oss-manifest.err"; then
    echo "oss_manifest=ok" >> "${manifest}"
    echo "oss_manifest_sha256=$(sha256sum "${PARTIAL}/oss-manifest.txt" | awk '{print $1}')" >> "${manifest}"
    rm -f "${PARTIAL}/oss-manifest.err"
  else
    warn "OSS 清单命令失败（详见 ${FINAL}/oss-manifest.err）；数据库备份仍保留"
    echo "oss_manifest=failed" >> "${manifest}"
    exit_code=3
  fi
else
  echo "oss_manifest=not_configured" >> "${manifest}"
  warn "未配置 BACKUP_OSS_MANIFEST_CMD：本批次没有 OSS 对象清单。请确认 OSS 已启用版本控制或另有复制备份，并记录本批次时间 $(date -u +%FT%TZ) 以便与对象配对"
fi

( cd "${PARTIAL}" && sha256sum ./*.dump manifest.txt > SHA256SUMS )
mv "${PARTIAL}" "${FINAL}"
DONE=1
ln -sfn "${FINAL}" "${BACKUP_DIR}/latest"
date -u +%FT%TZ > "${BACKUP_DIR}/.last-success"
info "批次 ${BATCH_ID} 完成，用时 $(( $(date +%s) - started_epoch )) 秒"

# ---- 保留策略 ----------------------------------------------------------------------
prune() {
  local -a all asc reps
  local -A keep seen
  local b m i start

  mapfile -t all < <(find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
                       -regex '.*/[0-9]{8}-[0-9]{6}' -printf '%f\n' | sort -r)   # 新 → 旧
  for i in "${!all[@]}"; do
    if (( i < KEEP_DAILY )); then keep["${all[$i]}"]=1; fi
  done
  # 月度：每个月最早的一份，保留最近 KEEP_MONTHLY 个月
  mapfile -t asc < <(printf '%s\n' "${all[@]}" | sort)
  reps=()
  for b in "${asc[@]}"; do
    m="${b:0:6}"
    if [[ -z "${seen[${m}]:-}" ]]; then seen["${m}"]=1; reps+=("${b}"); fi
  done
  if (( KEEP_MONTHLY > 0 && ${#reps[@]} > 0 )); then
    start=$(( ${#reps[@]} - KEEP_MONTHLY )); (( start < 0 )) && start=0
    for (( i = start; i < ${#reps[@]}; i++ )); do keep["${reps[$i]}"]=1; done
  fi
  keep["${BATCH_ID}"]=1
  local removed=0
  for b in "${all[@]}"; do
    if [[ -z "${keep[${b}]:-}" ]]; then
      info "清理过期批次 ${b}"
      rm -rf -- "${BACKUP_DIR:?}/${b}"
      removed=$(( removed + 1 ))
    fi
  done
  info "保留策略：每日 ${KEEP_DAILY} 份 + 月度 ${KEEP_MONTHLY} 个月；本次清理 ${removed} 个批次"
}
if (( PRUNE == 1 )); then prune; fi

ok "备份成功：${FINAL}"
exit "${exit_code}"
