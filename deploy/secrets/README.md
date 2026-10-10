# secrets/ 目录说明

本目录存放部署所需的全部机密文件，由 `compose.yml` 以 Docker secrets（文件形式）挂载到容器的 `/run/secrets/<名称>`。
**除本 README 与 `.gitkeep` 外，本目录的内容永远不进版本库**（`.gitignore` 已用 `secrets/*` 忽略）。

## 快速开始

```bash
scripts/gen-secrets.sh            # 生成可自动生成的文件；已存在的文件不会被覆盖
# 然后手工填写下表“手工”一栏的文件，例如：
printf '%s' 'LTAI...你的AccessKeyId' > secrets/oss_access_key_id
printf '%s' '你的AccessKeySecret'    > secrets/oss_secret_access_key
printf '%s' 'sk-...你的模型密钥'       > secrets/llm_api_key
scripts/preflight.sh              # 检查是否齐全、连接串与口令是否一致
```

写文件用 `printf '%s'`（不要 `echo`，避免多出换行与转义）；内容为单行，不要加引号。

## 文件清单

| 文件 | 来源 | 用途 | 使用者 |
| --- | --- | --- | --- |
| `postgres_password` | 自动 | PostgreSQL 超级用户 `postgres` 口令（只用于初始化与运维，应用不使用） | postgres |
| `db_password_owner` | 自动 | 库属主 `bidwb_owner` 口令（只给迁移用） | postgres（初始化） |
| `db_password_api` | 自动 | 登录角色 `bidwb_api`（IN ROLE app_api） | postgres（初始化） |
| `db_password_worker` | 自动 | 登录角色 `bidwb_worker`（IN ROLE app_worker） | postgres（初始化） |
| `db_password_runtime` | 自动 | LangGraph 检查点库 `bidwb_runtime` 的属主 | postgres（初始化） |
| `db_password_mlflow` | 自动 | MLflow 元数据库 `mlflow` 的属主 | postgres（初始化） |
| `db_url_owner` | 自动（由上面口令派生） | 迁移连接串 `postgresql+psycopg://bidwb_owner:…@postgres:5432/bidwb` | migrate |
| `db_url_api` | 自动 | `bidwb_api` 连接串 | api、admin |
| `db_url_worker` | 自动 | `bidwb_worker` 连接串 | worker-*、relay、reaper |
| `db_url_runtime` | 自动 | LangGraph 运行库连接串 | worker-ai、worker-experiment |
| `db_url_mlflow` | 自动 | MLflow 后端库连接串（`postgresql://`，psycopg2） | mlflow |
| `admin_initial_password` | 自动 | 首个管理员的初始口令。创建管理员并改密后清空 | admin（一次性） |
| `oss_access_key_id` | **手工** | 阿里云 RAM 子账号的 AccessKey ID（最小权限，见 README 第 3 节） | api、worker-*、mlflow |
| `oss_secret_access_key` | **手工** | 对应的 AccessKey Secret | 同上 |
| `llm_api_key` | **手工** | 模型服务 API Key；不填则 AI 任务不可用 | worker-ai、worker-experiment |
| `tls/fullchain.pem`、`tls/privkey.pem` | 手工 | 仅 `compose.tls.yml`（nginx 自己终止 TLS）使用 | web |
| `minio_root_user`、`minio_root_password` | 自动（`gen-secrets.sh --dev`） | 仅开发环境 MinIO | minio（开发） |

为什么每个角色有“口令文件 + 连接串文件”两份：后端配置（`BIDWB_DATABASE_URL`）要的是完整连接串，PostgreSQL 初始化脚本要的是口令本身。
两份由 `gen-secrets.sh` 同步生成，轮换时必须一起改（见下）。口令只含 `0-9a-f`，直接嵌入连接串无需转义。

## 权限：为什么是“目录 700 + 文件 444”而不是 600

secrets 以 bind mount 方式挂进容器，容器里的非 root 用户（postgres 999、应用 10001、nginx 101、mlflow 10002）必须能读文件；
Docker Compose（非 Swarm）不会改写挂载文件的属主和权限，所以 600 会导致容器内 `Permission denied`。
因此采用：

- `secrets/` 目录 `0700`：只有部署用户能进入目录，宿主机上的其他普通用户读不到；
- 文件 `0444`（需要你手工填写的文件为 `0644`）：只给容器内用户读取用。

这个做法成立的前提是：**宿主机上只有受信任的运维人员**，并且能执行 `docker` 命令的人（等价于 root）都是可信的。
如果你的环境不满足，请不要把 secrets 放在这里，改用 Docker Swarm secrets 或外部密钥管理系统。可用 `scripts/gen-secrets.sh --mode 0440` 调整文件权限，但需自行保证容器内用户的组能读取。

## 备份与交接

- 整个 `secrets/` 目录必须**另行加密备份**到受控位置（不要放进 `scripts/backup.sh` 的备份目录，也不要与数据库备份存在同一处且未加密）。
  丢失后果：数据库角色口令只能重置（`ALTER ROLE`），OSS 与模型密钥需重新签发。
- 密钥通过服务端配置交接，不写进文档、工单或聊天。

## 轮换

数据库口令（以 `bidwb_api` 为例，其余角色同理）：

```bash
NEW=$(openssl rand -hex 24)
# 1) 在数据库里改口令（本地套接字，无需旧口令）
docker compose exec -T postgres psql -U postgres -c "ALTER ROLE bidwb_api PASSWORD '$NEW'"
# 2) 同时改口令文件和连接串文件（文件是 0444，先加属主写权限，改完恢复）
chmod u+w secrets/db_password_api secrets/db_url_api
printf '%s' "$NEW" > secrets/db_password_api
printf 'postgresql+psycopg://bidwb_api:%s@postgres:5432/bidwb' "$NEW" > secrets/db_url_api
chmod 0444 secrets/db_password_api secrets/db_url_api
# 3) 重启使用该连接串的服务
docker compose up -d --force-recreate api
```

`oss_*`、`llm_api_key`：在阿里云/供应商处签发新密钥 → 写入文件 → `docker compose up -d --force-recreate api worker-parse worker-ai worker-experiment worker-export mlflow` → 确认正常后再作废旧密钥。

`postgres_password`：只在初始化时生效；之后改它需要 `ALTER ROLE postgres PASSWORD ...` 并同步文件。
