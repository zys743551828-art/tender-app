# 施组工作台 · 部署手册（Docker Compose）

适用对象：负责把系统部署到一台 Linux 服务器并长期运维的工程师。本手册假设你**不熟悉本项目**，照着做即可；
凡是我们在沙箱里无法验证的地方，都在文末“[未验证项](#10-未验证项)”如实列出，首次上线前请逐项在真机上确认。

目录：[1 总览](#1-总览) · [2 先决条件](#2-先决条件) · [3 阿里云 OSS 准备](#3-阿里云-oss-准备) · [4 部署步骤](#4-部署步骤) ·
[5 TLS 终止](#5-tls-终止) · [6 验证清单](#6-验证清单) · [7 日常运维](#7-日常运维) · [8 故障排查](#8-故障排查) ·
[9 安全注意事项](#9-安全注意事项) · [10 未验证项](#10-未验证项) · [11 文件清单与约定](#11-文件清单与约定)

---

## 1. 总览

### 1.1 组成

项目 AI 问答由 API 调用与 worker 相同的 `LLM_BASE_URL`／`LLM_MODEL` 和 `llm_api_key` secret；仅在用户发送问题时调用。未配置时只返回明确标注的项目状态提示。问答不写业务决定，确认卡提交复用正式接口。

一台主机上用 Docker Compose 运行 13 个常驻/一次性服务，OSS 与大模型为外部服务：

| 服务 | 作用 | 镜像 | 网络 | 备注 |
| --- | --- | --- | --- | --- |
| `web` | nginx：静态前端 + `/api` 反向代理 + 限流 + 安全头 | 自建 `bidwb-web` | edge | 唯一对宿主机发布端口的服务 |
| `api` | FastAPI 业务 API | 自建 `bidwb-backend` | edge、data、egress | 健康检查 `/healthz`，就绪 `/readyz` |
| `migrate` | 一次性：`alembic upgrade head` | 同上 | data | 用库属主角色 |
| `kafka-init` | 一次性：创建 Kafka 主题 | 同上 | data | `bidwb-admin ensure-topics` |
| `relay` / `reaper` | 发件箱中继 / 租约回收器（兼自动评审的兜底推进） | 同上 | relay：data；reaper：data、egress | relay 不出网；reaper 开启自动评审时要写 OSS，持有 OSS 凭据 |
| `worker-parse` / `-ai` / `-experiment` / `-export` | 四类计算 worker | 同上 | data、egress | 需要访问 OSS、模型；当前只注册了 parse、rules、diagnosis、revision、prediction 处理器，experiment、export 类暂无任务入队（见 11.2） |
| `postgres` | PostgreSQL 16：业务库 `bidwb` + LangGraph 库 `bidwb_runtime` + MLflow 库 `mlflow` | 官方 | data | 数据卷 `pgdata` 是备份真值 |
| `kafka` | Kafka KRaft 单节点 | 官方 `apache/kafka` | data | 派生数据，不备份 |
| `milvus` | Milvus standalone（内嵌 etcd + 本地存储） | 官方 | data | 派生索引，不备份；后端当前只实现关键词检索，不连接它 |
| `mlflow` | MLflow Tracking | 自建 `bidwb-mlflow` | data、egress | 界面只绑 `127.0.0.1:5000` |
| `admin`（profile `tools`） | 一次性运维命令（`bidwb-admin`：创建成员、创建主题） | 同后端 | data | 不随 `up` 启动 |

三个网络：`edge`（对外）、`data`（`internal: true`，不能出网，宿主机也无法直连）、`egress`（出网，只有需要访问 OSS/模型/IdP 的服务加入）。

```
浏览器 ──https──> [SLB 或 nginx 自带 TLS] ──> web:8080 ──> api:8000 ──> postgres / kafka
                                                         └─> OSS（API 分片转传／读取）
worker-*  <── kafka <── relay <── postgres（发件箱）          worker-*、reaper ──> OSS；worker-* ──> 大模型 API
```

### 1.2 几个设计取舍（为什么这样做）

- **Milvus 用单容器 standalone（内嵌 etcd + 本地存储）**：Milvus 官方 standalone 有“milvus + etcd + minio 三件套”和“单容器内嵌 etcd”两种形态。索引是由解析产物可重建的派生数据（架构文档 8.3），
  不值得为它再运维一套 minio 与 etcd；一期约 20 项目/月的数据量也远小于需要它们的规模。代价是该形态官方定位为单机，出现稳定性/性能问题时先改用三件套（参考 Milvus 官方
  `deployments/docker/standalone/docker-compose.yml`）。检索默认走关键词通道（BM25，`retrieval.py`）；后端当前没有连接 Milvus 的代码，`BIDWB_RETRIEVAL_BACKEND=milvus` 与 `BIDWB_MILVUS_URI` 只被配置读取，Milvus 通道须评测胜过基线后才会接入业务路径。
- **Kafka 单节点**：规模远低于 Kafka 设计量级，价值在解耦与独立限流；Kafka 丢失可由任务表与回收器补发。单节点无冗余，故障恢复靠“重启 + 回收器重发”，不承诺高可用。
- **三个库放一个 PostgreSQL 实例**：逻辑隔离（独立库、独立属主、互不授权）足够，一次备份覆盖；规模或恢复目标变严时再拆实例/用托管库。
- **一个后端镜像跑所有后端进程**：保证 API 与 worker 版本一致，不会出现灰度错配。
- **自动评审流水线**：`BIDWB_AUTO_ANALYSIS`（`.env` 中为 `AUTO_ANALYSIS`，默认 `true`）开启时，资料上传完成后自动依次解析、提取规则、冻结输入并评审，worker 在任务结束时推进下一步，reaper 周期性兜底推进仍处于“分析中”的项目；设为 `false` 则各步骤只由人工触发（模型服务故障或需要控制调用成本时使用）。评审报告的 Word/PDF 导出由 API 进程同步生成（依赖 `python-docx`、`pypdfium2`，均已在 `pyproject.toml` 声明并装入后端镜像），不经过任务队列。
- **MLflow 只绑回环地址**：MLflow 没有业务授权模型（架构文档 ADR-0015），研究员通过 SSH 隧道访问。
- **资源限额是估计值**：宿主假定 8 vCPU / 32 GiB / 500 GB SSD（架构文档 8.1 的假设，未在真机核对），`compose.yml` 里的 `mem_limit` / `cpus` 是未实测估计，用真实 PDF 压测后再调整。

---

## 2. 先决条件

### 本机 Docker Desktop 联调（真实 OSS）

在 `deploy/` 中填写 `.env` 与 OSS／模型密钥后，运行 `scripts/gen-secrets.sh` 生成缺失的数据库凭据。Windows 可用 Git Bash 执行该脚本；已存在的非空文件保留。仓库 `.gitattributes` 要求 Dockerfile 和 Shell 脚本为 LF。

```bash
docker compose build api web
docker compose -f compose.yml -f compose.local-oss.yml up -d web relay reaper worker-parse worker-ai worker-experiment worker-export
```

访问 `http://localhost:8080`。覆盖文件仅把 web 发布在 `127.0.0.1:8080`，API 使用开发环境的 HTTP 会话配置，数据库不发布端口，可与测试数据库并存。该命令启动核心评审服务，不启动尚未接入业务代码的 Milvus 和 MLflow；生产部署不要使用此覆盖文件。登录成员通过第 4 节的建号流程创建。

外部 Word 转换可加 `-f compose.word.yml`。先按 `deploy/word/README.md` 核对并构建 `WORD_IMAGE`，登记实际 `WORD_RENDERER_FINGERPRINT`，备份业务库并执行 0004 迁移，再统一更新后端和前端。完整本机核心命令：

```bash
docker compose -f compose.yml -f compose.local-oss.yml -f compose.word.yml up -d web relay reaper worker-parse worker-ai worker-experiment worker-export word-converter
```

输入解析身份保护需要 0005 迁移：升级前备份并在独立数据库演练恢复与迁移，随后运行 `migrate`，统一更新后端和前端。新评审冻结 `input-v2` 的解析、证据集合与缺口；旧快照保留原校验值和历史报告，标记未冻结身份，不按时间补写。旧输入的新检索／重跑会被拒绝，应由用户发起新版评审；已登记的提交与成绩保留。详见[解析身份契约](../contracts/snapshot-parse-identity.md)。

只有解析 worker 挂载输入可写、输出只读队列；API 仅拿到方法指纹。转换器非 root、无网络／端口／业务密钥、只读根、逐任务 Landlock 隔离。不加载此覆盖文件时仍可保存 Word 并逐稿补交 PDF，不能自动转换。成功转换、复杂版式核对、失败补交与历史身份规则见 `contracts/word-materials.md`。普通页码、目录等动态域同样需要补交 PDF；生成 PDF 不等于 Word 原稿合格。

阿里云 OSS 的 boto3 兼容配置使用 `OSS_SIGNATURE_VERSION=s3`；AWS S3 等服务可设置 `s3v4`，MinIO 开发覆盖文件固定使用 `s3v4`。依据：[阿里云 AWS SDK 接入说明](https://www.alibabacloud.com/help/en/oss/developer-reference/use-aws-sdks-to-access-oss)。

本机验证范围与未完成项统一见 tender-docs《验证报告》第 2.9 节。

上传统一走同源 API，不需要配置存储桶 CORS，也不需要为 CSP 增加 OSS 域名。

本机覆盖文件启用本地 OCR／原生表格候选，要求同级研究仓库已备妥 `.runtime/parsing/cache/rapidocr/` 中的三个 ONNX 模型；覆盖文件将其只读挂载到解析 worker，模型及其哈希见 `contracts/parsing-artifacts.md` 和 `backend/src/bidwb/parse_enrichment.py`。先检查已有缓存，不在运行时下载。后端镜像安装已锁定的 `parsing` 可选依赖；生产基础编排默认不启用本地识别，需要显式设置 `BIDWB_PARSE_ENRICHMENT_ENABLED=true`、`BIDWB_PARSE_MODEL_DIR` 及只读模型挂载后使用。

OCR／表格候选仍待核验，不能自动当作业务证据。部署此能力时须统一更新 API 与全部后端 worker，确保业务证据过滤逻辑一致；不要只更新解析 worker。原件哈希、识别预算、超时、坐标和恢复约定以解析产物契约为准。

### 2.1 服务器

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 配置 | 8 vCPU / 32 GiB 内存 / 500 GB SSD | 架构文档 8.1 的假设，**非实测**。Milvus 官方单机最低 4 核 8 GB、推荐 16 GB 内存并要求 SSD；`mem_limit` 之和 26.75 GiB，余量偏紧 |
| 系统 | 64 位 Linux（x86_64 已验证依赖可安装；aarch64 未验证） | 内核启用 cgroup v2/v1 均可；服务器时间必须用 NTP 同步（任务租约以服务端时间为准） |
| Docker Engine | ≥ 24（建议最新稳定版） | 本编排通过了 Docker 29.4.3 / Compose 5.1.3 的 `docker compose config` 语法校验；更低版本未逐一验证 |
| Docker Compose | v2 插件，≥ 2.24 | 需要 `depends_on.condition`、`service_completed_successfully`、`init`、profiles、嵌套变量默认值 |
| 其它工具 | `openssl`、`curl`、`bash` ≥ 4、`sha256sum`、`flock`（备份防并发）、`git` | 脚本使用 |
| 磁盘规划 | Docker 数据目录（默认 `/var/lib/docker`）≥ 100 GiB 可用；备份目录放**另一块盘** | 容量复审线：磁盘/连接数达 70% |

### 2.2 域名与证书

- 一个对外域名（例如 `tender.example.com`），解析到 SLB 或本机。
- 证书：由公司负载均衡/SLB 终止 TLS（推荐，见 5.1），或把证书链与私钥交给 nginx（5.2）。
- 浏览器只连接站点域名；OSS 地址仅由服务端访问（第 3.3 节）。

### 2.3 防火墙与端口

| 方向 | 端口 | 说明 |
| --- | --- | --- |
| 入站 | `8080/tcp` | 默认模式（前面有 SLB）：**只放行 SLB 的来源地址** |
| 入站 | `80/tcp`、`443/tcp` | 仅 TLS 模式（5.2）：对办公网/公网开放 |
| 入站 | `22/tcp` | SSH 运维，限制来源 |
| 仅本机 | `127.0.0.1:5000` | MLflow 界面，用 SSH 隧道访问（`ssh -L 5000:127.0.0.1:5000 <服务器>`） |
| **不得开放** | `5432`、`9092/9093`、`19530/9091/2379`、`3306` 等 | 数据服务在 internal 网络内，本来就不发布端口 |
| 出站 | `443/tcp` | OSS 端点、大模型 API；构建时还需要镜像仓库、PyPI、npm（或其国内镜像） |

注意：Docker 发布的端口会绕过 `ufw` / `firewalld` 的普通规则（走 iptables 的 DOCKER 链）。本编排只发布 web 与回环地址的 MLflow，风险有限；要限制 web 的来源，
请用云安全组，或在 `.env` 设 `WEB_BIND_ADDR=<内网IP>`，或在 `DOCKER-USER` 链加规则。

### 2.4 内网/国内网络提示

服务器若访问不了 Docker Hub / PyPI / npm：在能联网的机器上构建镜像后 `docker save | docker load` 或推到私有仓库；`.env` 里的镜像名可直接改成私有仓库地址，
构建参数 `PIP_INDEX_URL`、`NPM_REGISTRY`、`PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 可指向内部镜像。

---

## 3. 阿里云 OSS 准备

原件与不可变产物存阿里云 OSS，浏览器通过同源 API 分片上传，服务端用 S3 兼容接口转传（架构文档 INF-004）。

### 3.1 建桶

- 地域选择与服务器同地域（服务端走内网端点可省流量费）；读写权限 **私有**，不要开公共读；
- 版本控制：**建议开启**（恢复到备份时间点需要对象历史；是否启用及跨地域复制，是否启用由运维按公司保留要求决定；未启用时恢复只能回到对象的当前状态）；
- 记下：桶名、地域（如 `cn-hangzhou`）。

### 3.2 RAM 子账号与最小权限策略

创建一个 RAM 用户（仅编程访问），生成 AccessKey，把下面的策略授予它（把 `your-bucket-name` 换成桶名）。
权限覆盖：服务端分片上传（创建、上传、完成、中止、列分片）、读取与复制对象、清理暂存前缀。**不授予删除其它前缀对象的权限**，原件与正式产物因此不可被应用删除。

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "oss:GetObject",
        "oss:PutObject",
        "oss:AbortMultipartUpload",
        "oss:ListParts"
      ],
      "Resource": ["acs:oss:*:*:your-bucket-name/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:ListObjects", "oss:ListMultipartUploads", "oss:GetBucketInfo"],
      "Resource": ["acs:oss:*:*:your-bucket-name"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:your-bucket-name/staging/*"]
    }
  ]
}
```

说明：

- 动作名与资源格式（`acs:oss:*:*:<桶名>[/*]`、`"Version": "1"`）取自阿里云“RAM Policy 常见示例”文档（2026-10-07 查阅）。
  OSS 的分片上传各步骤在 RAM 里主要归属 `oss:PutObject`、`oss:AbortMultipartUpload`、`oss:ListParts`、`oss:ListMultipartUploads`；缺权限会在上传完成/复制时报 `AccessDenied`。
- 后端的对象键见 `storage.py`：API 转传分片落在 `staging/<上传ID>`；校验通过后复制到内容寻址键 `objects/<sha256 前两位>/<sha256>`；worker 产物写 `artifacts/<产物ID>`。本策略与 3.4 的生命周期规则里的 `staging/` 即该前缀。
- 复制到最终键用 CopyObject（需要源的 `GetObject` 与目标的 `PutObject`）。后端不依赖 OSS 的“禁止覆盖”选项：写入前先 HEAD 目标键，已存在则跳过，同键即同内容（架构文档 INF-004）。CopyObject / CompleteMultipartUpload 在 OSS 上的实际行为未验证（见 10.2）。
- MLflow 默认把产物写到同一桶的 `mlflow-artifacts/` 前缀，复用同一对 AccessKey；想进一步隔离可单独建 RAM 用户并拆分前缀权限。

### 3.3 同源分片上传

浏览器通过本站 `PUT /api/v1/uploads/{upload_id}/parts/{part_number}` 上传，携带会话与 CSRF。API 校验上传人、项目访问、会话状态与有效期，以及分片编号和字节数后，使用服务端 OSS 凭据转传并返回 ETag。分片地址始终是本站相对路径，不含对象存储凭据或签名。

nginx 的专用上传 location 允许每片最多 8 MiB，关闭请求落盘缓冲；普通 JSON API 保持原上限。API 按会话声明限制读取大小，单个请求只缓存一个分片，不缓存整份 100 MiB 文件。浏览器无需 OSS 的 CORS 规则，CSP 的 `connect-src` 仅为 `'self'`，桶仍保持私有。

### 3.4 生命周期：清理暂存前缀与未完成分片

浏览器上传中断会留下未完成的分片上传与暂存对象，占用存储。对 `staging/` 前缀配置：

```xml
<LifecycleConfiguration>
  <Rule>
    <ID>cleanup-staging</ID>
    <Prefix>staging/</Prefix>
    <Status>Enabled</Status>
    <AbortMultipartUpload><Days>1</Days></AbortMultipartUpload>
    <Expiration><Days>7</Days></Expiration>
  </Rule>
</LifecycleConfiguration>
```

- `AbortMultipartUpload` 清理未完成分片（最小 1 天）；`Expiration` 清理超期的暂存对象。**只配置在 `staging/` 前缀**，原件与正式产物前缀绝不能配置过期删除。
- 开启版本控制时，`Expiration` 对暂存对象会产生删除标记，历史版本需另配“非当前版本过期”规则（未验证：规则写法；验证方法：在测试桶创建规则后核对执行结果）。
- 上线后定期检查：暂存前缀残留量、生命周期执行情况（架构文档 8.2 监测项）。

### 3.5 填入配置

| 内容 | 位置 |
| --- | --- |
| 桶名、地域、端点 | `.env`：`OSS_BUCKET`、`OSS_REGION`、`OSS_ENDPOINT_URL`、`OSS_PUBLIC_ENDPOINT_URL`（compose 映射为 `BIDWB_STORAGE_*`） |
| AccessKey | `secrets/oss_access_key_id`、`secrets/oss_secret_access_key` |

S3 兼容端点格式为 `https://s3.oss-<地域>.aliyuncs.com`（阿里云“用 Amazon S3 SDK 访问 OSS”文档）；OSS **只支持 virtual-hosted 寻址**，`OSS_ADDRESSING_STYLE` 保持默认 `virtual`。
该文档还提到 boto3 的 V4 签名默认带分块编码（aws-chunked），OSS 不支持，官方示例改用 `signature_version='s3'`（V2）。后端使用 `s3v4`（`storage.py` 的 `S3ObjectStore`，签名版本不可通过环境变量切换）。未验证：服务端 PutObject / CopyObject / CompleteMultipartUpload 在 OSS 上是否受此影响；验证方法：首次部署时上传一个多片文件并触发解析，观察 api 与 worker 日志中的 OSS 错误码（见 10.2 第 8 项）。

---

## 4. 部署步骤

约定：以下命令都在本目录（`deploy`）执行，工作目录里没有 `.env` 时 compose 会报变量缺失。

### 4.1 拉代码与准备

```bash
git clone <仓库地址> /opt/tender-app && cd /opt/tender-app/deploy
```

### 4.2 构建或获取镜像

```bash
# 方式 A：在服务器上构建（需要能访问 PyPI/npm/基础镜像，或在 .env 配置镜像源）
cp .env.example .env            # 先拷贝，下面 4.4 再改
docker compose build api web mlflow

# 方式 B：从私有镜像仓库拉取（在 .env 里把 APP_IMAGE 等改成仓库地址）
docker compose pull
```

`api` 构建出 `APP_IMAGE`，worker/relay/reaper/migrate 复用它；`web` 构建前端（`npm ci` + `npm run build`）；`mlflow` 构建自带 PostgreSQL 驱动与 boto3 的镜像。

### 4.3 生成 secrets

```bash
scripts/gen-secrets.sh
```

然后手工填写 `oss_access_key_id`、`oss_secret_access_key`（必填）、`llm_api_key`（建议），方法见 [`secrets/README.md`](secrets/README.md)。**把整个 `secrets/` 目录离线加密备份。**

### 4.4 填写 `.env`

编辑 `.env`，逐项阅读注释。**必须修改**的有：`PUBLIC_BASE_URL`（https）、`OSS_*`（端点、地域、桶名）、
默认模式下的 `WEB_SET_REAL_IP_FROM`（SLB 网段）；以及确认各 `*_IMAGE` 标签、`KAFKA_CLUSTER_ID`。

```bash
scripts/preflight.sh            # 检查版本、资源、.env、secrets、compose 语法；全部通过再继续
```

### 4.5 起库

```bash
docker compose up -d postgres
docker compose ps postgres      # 等到 healthy（首次初始化约十几秒）
```

首次启动时 `postgres/initdb/10-roles-and-databases.sh` 自动创建角色 `bidwb_owner / bidwb_api / bidwb_worker / bidwb_runtime / mlflow` 与数据库 `bidwb / bidwb_runtime / mlflow`
（口令来自 secrets）。**这个脚本只在数据目录为空时执行一次**；之后改口令请用 `ALTER ROLE`（见 `secrets/README.md`）。

### 4.6 迁移

```bash
docker compose up --no-deps --exit-code-from migrate migrate
```

成功时最后一行是 `migrate ... exited with code 0`。迁移用库属主角色 `bidwb_owner`，并按 `schema.sql` 对 `app_api` / `app_worker` 授权。
（也可跳过这一步：4.8 的 `up -d` 会因 `depends_on` 自动先跑迁移；单独跑只是为了在创建管理员前看到迁移结果。）

### 4.7 创建首个账号

```bash
docker compose up -d kafka kafka-init   # 创建管理员本身不需要 Kafka；此处顺手确认 Kafka 与主题就绪
scripts/create-admin.sh                 # 登录名 ADMIN_LOGIN，口令在 secrets/admin_initial_password
```

脚本调用 `bidwb-admin create-member --login … --display-name … --password-file … --if-not-exists`（`admin.py`；`--if-not-exists` 使重复执行时登录名已存在视为成功，口令只从文件或标准输入读取）。
登录后**立即修改口令**，并清空 `secrets/admin_initial_password`。系统只有登录一道门，登录后的成员可以访问全部项目；其他成员同样用 `bidwb-admin create-member` 创建。

### 4.8 启动全部服务

```bash
docker compose up -d
docker compose ps               # 常驻服务应全部 running（healthy），migrate / kafka-init 为 exited (0)
```

启动顺序由 `depends_on` 保证：`postgres` healthy → `migrate` 成功 → `kafka` healthy → `kafka-init` 成功 → api / relay / reaper / worker-* → `web`。

### 4.9 验证

```bash
scripts/healthcheck.sh
```

再按[第 6 节](#6-验证清单)做人工验收；然后配置备份（7.3）并做第一次恢复演练。

---

## 5. TLS 终止

提供两种方式，默认是 5.1（compose 保持简单）。

### 5.1 方式 b（默认）：前面有公司负载均衡 / 阿里云 SLB 终止 TLS

- nginx 只监听容器内 `8080` 明文，发布到宿主机 `WEB_HTTP_PORT`（默认 8080）。SLB 的后端服务器组指向本机 `8080`；
- SLB 必须传递 `X-Forwarded-For`（客户端真实 IP）与 `X-Forwarded-Proto`（`https`）。nginx **只信任来自 `WEB_SET_REAL_IP_FROM` 网段的这两个头**，请把它收紧为 SLB 的私网网段；
  填错的后果：所有用户被当成同一个 IP，登录限流（`10r/m`）会误伤全体用户；
- 健康检查：HTTP `GET /nginx-health` → 200；
- **SSE 超时**：任务进度走 SSE 长连接（`/api/v1/tasks/<id>/events`），SLB 监听器的空闲超时必须大于后端心跳间隔：API 每 15 秒发一次 SSE 注释行心跳（`routes_tasks.py`），单次连接最长保持 600 秒后由服务端结束，浏览器用 `Last-Event-ID` 续传；nginx 对该路径的读超时为 3600 秒。SLB 的默认空闲超时可能只有几十秒，请调到 60 秒以上（未验证：所用 SLB 的默认值；验证方法：在监听器配置页核对，并保持一个任务进度页面打开数分钟观察是否被重连）；
- HSTS 头仅在 `X-Forwarded-Proto: https`（且来自可信代理）时由 nginx 下发。

### 5.2 方式 a：nginx 自己终止 TLS（`compose.tls.yml`）

```bash
mkdir -p secrets/tls && chmod 700 secrets/tls
cp /path/to/fullchain.pem secrets/tls/fullchain.pem        # 证书 + 中间证书
cp /path/to/privkey.pem   secrets/tls/privkey.pem
chmod 444 secrets/tls/*.pem                                # 容器内 nginx(101) 需要读取，原因见 secrets/README.md
```

在 `.env` 中设置并追加一行（compose 自己读取 `COMPOSE_FILE`，之后所有 `docker compose` 命令与 `scripts/*.sh` 都会自动叠加 TLS 文件）：

```
WEB_HTTP_PORT=80
WEB_HTTPS_PORT=443
WEB_PUBLIC_HOST=tender.example.com
COMPOSE_FILE=compose.yml:compose.tls.yml
```

```bash
docker compose up -d web
curl -I http://tender.example.com        # 应 301 到 https://tender.example.com/
curl -I https://tender.example.com/nginx-health
```

证书续期后：替换 `secrets/tls/*.pem`，执行 `docker compose exec web nginx -s reload`（若 bind mount 的文件被“删除重建”导致容器仍看到旧文件，则 `docker compose up -d --force-recreate web`）。
该模式下 nginx 不信任客户端传来的 `X-Forwarded-*`（自己就是边界）；协议 TLS 1.2/1.3，HSTS 一年（含子域名，**确认全站都能走 HTTPS 再上线**）。

---

## 6. 验证清单

上线验收逐项确认（✓ 的前提是第 10 节的“未验证项”已在真机核对过）：

- [ ] `scripts/preflight.sh` 无失败
- [ ] `docker compose ps`：常驻服务 running；`migrate`、`kafka-init` exited (0)；数据服务无 `ports`（`docker compose ps` 的端口列只有 web 与 mlflow 的回环地址）
- [ ] `scripts/healthcheck.sh` 无 FAIL（若有 WARN，逐条判断）
- [ ] 浏览器打开站点首页，使用管理员登录；直接打开一个深层前端路由并刷新（SPA 回退正常）
- [ ] 浏览器开发者工具：无 CSP 报错；响应头含 `Content-Security-Policy`、`X-Content-Type-Options`、（https 下）`Strict-Transport-Security`；无 `Server: nginx/x.y.z` 版本号
- [ ] 创建测试项目并**上传一个多片大文件**（> 8 MiB 触发多分片）：浏览器只请求本站分片接口、API 转传成功，完成后服务端校验通过；核实会话、CSRF 与 RAM 权限
- [ ] 用 Range 请求读取原件：`curl -H 'Range: bytes=0-99' -b <登录 cookie> https://<站点>/api/v1/files/<版本ID>/content -i` 返回 `206`
- [ ] 创建一个任务，页面进度（SSE）实时更新；任务最终 `succeeded`；`docker compose logs worker-parse` 无异常
- [ ] 登录接口限流：连续快速错误登录 > 6 次返回 429（`WEB_LOGIN_RATE`）
- [ ] `docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` 含 `job.parse`、`job.ai`、`job.experiment`、`job.export`、`domain.events` 及各自死信主题
- [ ] MLflow：`ssh -L 5000:127.0.0.1:5000 <服务器>` 后浏览器打开 `http://127.0.0.1:5000`；跑一个实验确认产物写入 OSS `mlflow-artifacts/`
- [ ] 手动执行一次 `scripts/backup.sh`，再执行 `scripts/restore.sh --backup latest`（恢复演练）全部通过
- [ ] 重启演练：`docker compose restart worker-parse`（任务中途）→ 任务由租约/回收器恢复；`sudo reboot` 后所有服务自动恢复（`restart: unless-stopped`，且 Docker 服务开机自启）

---

## 7. 日常运维

### 7.1 日志

- 容器日志为 `json-file`，每服务 `20m × 5` 轮转（约 100 MB 上限/服务）：
  `docker compose logs -f --tail 200 api`、`docker compose logs --since 1h worker-ai`。
- 后端日志是 JSON 单行（`logs.py`，输出到 stdout），包含 request / project / job / attempt 等业务 ID，**不应出现口令、预签名地址、令牌**（对常见敏感键名另有兜底脱敏）；API 访问日志只记录路径，不记录查询串；发现敏感信息立即按安全事件处理。
- nginx 访问日志用 `$uri`（不含查询串），避免把查询串中的令牌、回调参数写入日志。
- 日志是排障用，**不是审计记录**：人工审核与发布是业务记录，在 PostgreSQL 里（架构文档 8.2）。需要长期留存日志时，在宿主机配置日志采集。

### 7.2 常用命令

```bash
docker compose ps                         # 状态
scripts/healthcheck.sh                    # 整体检查（可放 cron，--quiet 只输出异常）
docker compose restart worker-ai          # 重启单个服务
docker compose exec postgres psql -U postgres -d bidwb     # 进数据库（超级用户，慎用）
docker compose top / docker stats         # 资源占用
```

扩容消费者：worker 单进程一次只算 1 个重任务。要更大吞吐，**复制 `compose.yml` 中对应 worker 服务段并改服务名与 `BIDWB_WORKER_ID`**，不要用 `--scale`（`BIDWB_WORKER_ID` 是静态的）。
训练/大回测使用独立的 `worker-experiment`，不挤占截止前的业务队列（后端没有注册 experiment 处理器）。

### 7.3 备份

备份范围：业务库 `bidwb`、LangGraph 运行库 `bidwb_runtime`、MLflow 元数据库 `mlflow`（逻辑导出 `pg_dump -Fc`）。**不含** OSS 对象、Kafka、Milvus、`secrets/`。

```bash
scripts/backup.sh                         # 手工备份
scripts/backup.sh --label before-change   # 带备注
```

定时（cron，每天 02:30；`BACKUP_DIR` 必须在另一块盘或挂载点）：

```
30 2 * * * cd /opt/tender-app/deploy && scripts/backup.sh >> /var/log/bidwb-backup.log 2>&1
```

- 每个批次一个目录 `BACKUP_DIR/<UTC时间>/`：`*.dump`、`manifest.txt`（版本、迁移版本、表数与行数、镜像、OSS 桶）、`SHA256SUMS`；`latest` 指向最近成功批次。
- 保留策略：近 30 份 + 近 12 个月各月最早一份（`BACKUP_KEEP_DAILY` / `BACKUP_KEEP_MONTHLY`，架构文档 8.3 初始策略；公司保留要求改变时调整，**不自动删除正式投标原件**——它们在 OSS，不在本备份范围）。
- 脚本每个转储都用 `pg_restore --list` 校验可读；失败的批次被丢弃，退出码非 0（接入监控/邮件）。退出码 3 表示数据库备份成功但 OSS 清单命令失败。
- **与 OSS 配对**：架构文档要求同一备份批次的数据库与对象引用配对。本脚本只在 manifest 记录桶名与时间点；对象本身的保护依赖 OSS 版本控制 / 跨地域复制 / 复制到备份桶（是否启用由运维决定，本编排不替你开启）。
  可在 `.env` 配置 `BACKUP_OSS_MANIFEST_CMD`（如 `ossutil ls oss://<桶>/ --short-format`），其输出作为 `oss-manifest.txt` 存入批次。
- 备份含全部业务数据（未加密）：`BACKUP_DIR` 所在磁盘应加密，并**异地**保存（如定时同步到另一个桶/机房）；仅放在本机同一块盘上不算备份。
- 初始恢复目标：RPO ≤ 24 小时，RTO ≤ 4 小时；这是设计目标，须首次恢复演练与稳定运营阶段验收后才能承诺。要缩小 RPO 可另行启用基础备份 + WAL 归档（本编排默认不启用）。

### 7.4 恢复演练（每月一次，重要迁移后追加）

```bash
scripts/restore.sh --backup latest                 # 默认：恢复到临时库 restore_<库>_<时间>，核验后删除，不影响线上
scripts/restore.sh --backup 20261007-023000 --db bidwb --keep   # 保留临时库供人工抽查
```

脚本核验：校验和、`pg_restore` 无错误、表数量与迁移版本与清单一致、总行数对比。结束时会打印**业务恢复核对清单**（核对 OSS 对象、抽样打开原页与提交稿、核对快照/结果/发布关联、确认检索通道、任务租约处理）——
“备份存在、下载成功或 SQL 导入成功均不单独算业务恢复成功”（架构文档 8.3），请完成清单后把结果与耗时记入运维台账。

**灾难恢复（危险，覆盖线上数据）**：

```bash
scripts/restore.sh --backup <批次> --in-place --yes
```

会先做一次 pre-restore 备份，停止应用与 MLflow，删除并重建选定数据库，导入后再核验；完成后服务保持停止，确认后 `docker compose up -d`。
换新主机的流程：恢复 `secrets/`（若丢失则重新 `gen-secrets.sh` 并 `ALTER ROLE` 对齐）→ 起 `postgres`（初始化脚本建角色与空库）→ `scripts/restore.sh --backup <批次> --in-place --yes` → `docker compose up -d` →
按核对清单验收。Kafka 主题由 `kafka-init` 重建，未完成任务由回收器重发。

**Milvus 索引（范围外 / 未实现）**：后端没有 `rebuild-index` 之类的索引重建命令（`bidwb-admin` 只有 `create-member` 与 `ensure-topics`），也没有写入 Milvus 的代码；当前检索只走关键词通道，直接读取库里的解析产物，因此恢复数据库后无需重建任何索引，丢失 `milvusdata` 卷不影响业务。影响：Milvus 通道上线前不存在可恢复的向量数据；通道接入时须同时提供重建命令并更新本节。替代做法：如有人在 Milvus 里手工做过评测，数据从解析产物重新导入，不属于本系统的恢复范围。

### 7.5 升级与回退

1. 备好新版本镜像（构建或拉取），在 `.env` 修改 `APP_IMAGE`、`WEB_IMAGE`、`MLFLOW_IMAGE`（及要升级的第三方镜像）为新标签；
2. `scripts/upgrade.sh --build`（或 `--pull`）：预检 → 获取镜像 → 记录当前镜像 → **升级前备份** → 创建主题 → 迁移 → 逐个重启（relay、reaper、worker-*、mlflow、api、web）→ `healthcheck.sh --strict`；
3. 任一步失败，脚本打印回退指引；镜像回退：`scripts/upgrade.sh rollback`（回到 `.upgrade-state/previous.env` 记录的镜像，随后把 `.env` 标签也改回旧值）。

要点（架构文档 8.3）：

- **迁移只进不退**：追加保存的表有触发器禁止改写，初始迁移不提供降级。升级策略是“先加字段/双读过渡，再迁移历史并校验，最后停旧写入”；已应用的迁移不改写。因此旧程序必须兼容新结构；若新迁移不向后兼容，回退必须恢复升级前备份（`restore.sh --backup <升级前批次> --in-place --yes`）。
- 内容语义、解析或特征变化会生成新方法包并重评；回退要同时恢复兼容的 worker、配置与发布路由，**不撤销已经发生的业务事件**。
- 单机单副本，API 重建的几秒内会短暂不可用，请安排在低峰期。
- MLflow 升级大版本后，库结构需要升级：`docker compose run --rm --no-deps mlflow mlflow db upgrade "$(cat secrets/db_url_mlflow)"`（未验证：命令形式；验证方法：升级前在备份恢复出的副本上执行一次）。
- 第三方镜像（postgres 小版本、kafka、milvus）升级前先看各自发行说明；**Milvus 跨大版本、PostgreSQL 跨大版本不能只改标签**（PostgreSQL 大版本需要 dump/restore 或 pg_upgrade；Milvus 需按官方升级文档）。
- 定期（建议每月）重建镜像以获取基础镜像的安全补丁，并走同样的升级流程。

### 7.6 清理

`docker image prune`（只删悬空镜像）可以；**不要执行 `docker volume prune` 或 `docker compose down -v`**——会删除数据库卷。`docker compose down`（不带 `-v`）只停止并删除容器，数据卷保留。

---

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `docker compose` 报 `required variable XXX is missing` | `.env` 缺变量 | 对照 `.env.example` 补齐；运行 `scripts/preflight.sh` |
| 容器内 `Permission denied: /run/secrets/...` | secrets 文件权限不对（非 0444/0644）或不在 0700 目录内的 bind mount 异常 | `ls -l secrets/`；文件改回 `chmod 444`；目录 `chmod 700` |
| `postgres` 一直 unhealthy，日志显示初始化脚本失败 | secret 缺失/为空，或数据目录已存在导致脚本不执行 | 看 `docker compose logs postgres`；首次初始化失败后卷里已有半成品，**确认没有数据**后才能 `docker compose down` 并删除卷 `bidwb_pgdata` 重来 |
| 改了 `db_password_*` 但连不上库 | 初始化脚本只在首次运行；改口令没同步到数据库 | 按 `secrets/README.md` 的轮换步骤 `ALTER ROLE` 并同步口令文件与连接串文件 |
| `migrate` 失败：`未设置 BIDWB_MIGRATION_DATABASE_URL` 或认证失败 | `secrets/db_url_owner` 为空/口令不一致 | `scripts/preflight.sh` 会检查连接串与口令一致；修正后 `docker compose up --no-deps --exit-code-from migrate migrate` |
| `migrate` 失败：权限错误 | 库属主角色不对，或库被手工改过 | 确认连接串是 `bidwb_owner` 且库属主是它：`\l`；不要用超级用户跑迁移 |
| `api` 或 relay / reaper / worker 退出，日志提示“生产环境必须…” | 后端生产配置校验（`config.py`）：`cookie_secure` 关闭、`PUBLIC_BASE_URL` 非 https、会话 Cookie 不是 `__Host-` 前缀；relay / reaper / worker 另要求配置 `BIDWB_WORKER_DATABASE_URL(_FILE)` | 修正 `.env` / compose；注意 `PUBLIC_BASE_URL` 必须 `https://`（结尾 `/` 会被去掉） |
| `api` 启动失败，找不到 `bidwb-api` / `bidwb-admin` | 镜像不是由当前后端源码构建，入口脚本（`pyproject.toml` 的 `[project.scripts]`）未安装 | 确认镜像由当前源码构建；`docker compose run --rm --no-deps api bidwb-admin --help` |
| 浏览器 502/504 | api 不健康或重建中 | `docker compose ps api`、`logs api`；nginx 用 Docker DNS 动态解析，api 恢复后自动恢复 |
| 页面能开但登录一直 429 | 限流命中；在 SLB 后面所有用户共用一个来源 IP | 正确设置 `WEB_SET_REAL_IP_FROM`；确认 SLB 传了 `X-Forwarded-For`；必要时调大 `WEB_LOGIN_RATE` |
| 登录后马上掉线/Cookie 不生效 | 用户不是通过 https 访问（生产会话 Cookie 为 `__Host-sid` 且带 Secure，浏览器不会在 http 下保存） | 保证用户通过 https 访问，且访问地址与 `PUBLIC_BASE_URL` 一致；Secure 属性由后端的 `cookie_secure`（默认开启）决定，与转发协议头无关；SLB 仍应传 `X-Forwarded-Proto: https` 供 nginx 下发 HSTS |
| 分片上传 HTTP 413／422 | 分片超过 8 MiB 或与会话声明大小不符 | 检查 nginx 专用上传 location，浏览器使用会话返回的 part_bytes 拆分 |
| 分片上传 HTTP 401／403 | 登录会话或 CSRF 失效 | 重新登录；客户端会自动刷新 CSRF 并重试一次 |
| 上传完成时报 403 / `AccessDenied` | RAM 策略缺动作或前缀不一致 | 对照 3.2；看 api 日志里的 OSS 错误码 |
| 服务端访问 OSS 报签名/`aws-chunked` 错误 | boto3 V4 分块编码与 OSS 不兼容（未验证是否会发生） | 见 3.5。可先在出错服务的 environment 里加 `AWS_REQUEST_CHECKSUM_CALCULATION=when_required`（botocore 读取该变量，mlflow 服务已如此设置；未验证对 OSS 有效）；仍不通则需调整 `storage.py` 的客户端配置，属后端改动 |
| 任务进度页不更新 / 频繁重连 | SLB 或中间代理的空闲超时过短；nginx 缓冲 | 调大 SLB 空闲超时；SSE 路径在 nginx 已关缓冲（`proxy_buffering off`） |
| 任务一直 `queued` | relay 不工作、Kafka 不可用或 worker 没消费 | `healthcheck.sh`；`logs relay worker-*`；`kafka-init` 是否成功；reaper 会在 120 秒后重发未被领取的 queued 任务 |
| 任务卡在 `running` | worker 崩溃/卡死 | 租约（300 秒）到期后 reaper 自动回收：重排或标 `failed`；`docker compose restart worker-xxx` 可加速 |
| `kafka` 启动失败，日志 `file not writable` | Docker < 20.10.4 或数据卷属主不对（Kafka 以 uid 1000 运行） | 升级 Docker；`docker run --rm -v bidwb_kafkadata:/d alpine chown -R 1000:1000 /d` |
| `kafka` 重启后无法加入/报 cluster id 不匹配 | 数据卷里的 cluster id 与 `KAFKA_CLUSTER_ID` 不一致（改过 .env） | 改回原值；Kafka 是派生数据，确认无积压后可删 `kafkadata` 卷重建（任务靠回收器重发） |
| `milvus` 启动慢/unhealthy | 首次启动需要约 90 秒；内存不足 | 看 `logs milvus`、`docker stats`；当前后端不连接 Milvus，检索恒走关键词通道，Milvus 不健康不影响业务；资源紧张时可先停掉该服务 |
| `mlflow` 报 `Invalid Host header` | 访问时用了未放行的主机名 | `MLFLOW_SERVER_ALLOWED_HOSTS` 已含 `mlflow`、`localhost`；经隧道访问用 `127.0.0.1:5000` |
| 磁盘告警 | 日志/备份/WAL/Kafka 日志/镜像累积 | `docker system df`；清理旧备份（保留策略）；Kafka 日志保留 168 小时；检查 PostgreSQL 的 WAL 与大表 |
| 时间相关异常（租约、会话过期） | 主机时钟漂移 | 启用 chrony/ntpd |

排障信息收集：`docker compose ps -a`、`docker compose logs --tail 200 <服务>`、`scripts/healthcheck.sh`、`docker stats --no-stream`。**贴日志给他人前先检查是否含敏感信息。**

---

## 9. 安全注意事项

- **机密**：口令/密钥只放 `secrets/`；`.env` 与 compose 不含明文凭据（`check_compose.py` 在 CI 中检查）；`secrets/` 单独加密备份；轮换步骤见 `secrets/README.md`。
  secrets 文件为 `0444`、目录 `0700`，只在“宿主机仅受信任运维人员可登录、且 docker 组成员等同 root”的前提下成立。
- **能执行 `docker` 命令的人等同于 root**，并且能读到所有 secrets 与容器环境。限制 `docker` 组成员，运维账号用个人账号，不共享。
- **网络隔离**：数据服务在 `internal` 网络，不发布端口；不要为了调试把 `5432`、`9092`、`19530` 发布到宿主机（开发用 `compose.dev.yml`，只绑 127.0.0.1）。MLflow 界面只绑回环地址，经 SSH 隧道访问，并限制可访问的研究组成员。
- **容器加固**：非 root、`cap_drop: ALL`、`no-new-privileges`、只读根文件系统、`tmpfs` 临时目录、`pids_limit`、内存/CPU 限额；例外只有 Kafka（写配置目录）与 Milvus（root、seccomp:unconfined，未实测前不收紧），均记录在 `compose.yml` 头部并由 `check_compose.py` 白名单约束。
- **数据库角色分权**：迁移用库属主 `bidwb_owner`；API 用 `bidwb_api`；worker/relay/reaper 用 `bidwb_worker`（不读身份、会话、上传与成员表）；LangGraph 运行库与 MLflow 库各有独立属主，互不授权。不要把属主或超级用户连接串交给应用。
- **站点安全头**：CSP、`X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy`、`Permissions-Policy`、HSTS（https 下）；登录限流；隐藏 nginx 版本；隐藏文件不可访问。CSP 中 `style-src 'unsafe-inline'` 与 `'wasm-unsafe-eval'` 是为兼容 React/PDF.js 而放宽，是否都需要未验证（见 10.2 第 11 项）。
- **OSS**：桶私有；RAM 子账号最小权限，无删除原件权限；浏览器不访问桶；API 校验会话与 CSRF 后转传。
- **备份**：含全部业务数据，磁盘加密 + 异地保存 + 限制访问；演练恢复时临时库会含真实数据，用完删除。
- **日志**：后端不记录口令、令牌、预签名地址、文档全文、思考过程（`logs.py` 的约定与兜底脱敏）；对外分享日志前自查。
- **更新**：定期重建镜像取得基础镜像安全补丁；关注 Docker、PostgreSQL、Kafka、Milvus、nginx 的安全公告。
- **模型调用**：worker 出网访问大模型 API，文档内容会发送到该供应商——**这是数据出境/供应商合规问题，需公司法务/信息安全确认**后才可对真实招投标资料启用。

---

## 10. 未验证项

本机 Windows Docker Desktop 的核心镜像构建、服务启动、迁移、同源上传、真实模型合成评审、导出与故障恢复已有实测。完整方法和结果统一见同级 `tender-docs/04-验证与测试/验证报告.md`；不能用本机合成场景替代生产主机和真实标书验收。

### 10.1 已验证（含方法）

| 项 | 方法与边界 |
| --- | --- |
| 编排 | `check_compose.py` 及 `docker compose config -q`，包含本机、TLS、开发与 Word 覆盖的结构检查；不等同真实证书及公网运行 |
| 后端／web 构建 | 实际 Docker 多阶段构建，后端纯 wheel 依赖安装、前端构建及核心服务健康检查通过；MLflow 不在当前运行栈 |
| 核心运行链路 | PostgreSQL 16.15、迁移至 0004、Kafka、API、relay、reaper、全部业务 worker 与 web；真实 OSS、模型、同源分片上传、合成评审与 Word／PDF 导出；大文件容量另测 |
| Word 隔离 | 无网络、输入只读、非 root、只读根目录、Landlock 子进程隔离、转换方法指纹、逐稿补交与崩溃队列回收；真实复杂版式准确率另测 |
| 数据库恢复副本 | 既有迁移前备份恢复至一次性 PostgreSQL 库、前进迁移、旧记录行数、外键、只追加保护和角色读取权限，见验证报告 2.28 节；未恢复原属主或 OSS 对象 |
| 静态脚本与配置 | shellcheck／bash 语法、配置白名单、变量对应、敏感信息检查及命令入口核对；具体启动和恢复结果见验证报告 |

### 10.2 未验证（必须在目标环境核对）

1. 正式 Linux 主机上的资源限额、数百页解析／导出、长时间并发评审、检索规模与磁盘容量。当前 CPU／内存限制仍是估计值。
2. 正式 TLS 证书、续期与热加载、域名／反向代理、实际来源 IP、生产 cookie 与安全头的整轮浏览器验证。
3. Milvus 镜像、内嵌 etcd、存储及只读例外；MLflow 镜像构建、数据库升级、工件代理、实验队列及其资源容量。当前均未启用，不得由核心服务健康推断已验证。
4. 完整灾难恢复：原属主与全局角色、密钥、OSS 实际对象、历史原页／稿件／快照／结果与发布关联、任务租约，以及真实数据量下的 RPO ≤ 24h／RTO ≤ 4h。独立数据库恢复通过不能替代它。
5. `upgrade.sh` 的完整编排与失败回退、`backup.sh`／`restore.sh` 的定时生产流程、保留策略和实际对象存储断连场景；不得在正式库直接试验覆盖恢复。
6. 开发覆盖组合中的 MinIO `mc` 初始化、Vite 热更新、全部绑定挂载权限及共享开发资源隔离。
7. 浏览器交互与视觉、真实标书检测准确率、官方技术分独立配对精度。组件／API／合成模型测试不代替这些验收。

---

## 11. 文件清单与约定

### 11.1 文件清单

```
backend/Dockerfile, .dockerignore          后端镜像（多阶段、非 root uid 10001、预编译 venv、HEALTHCHECK 工具）
frontend/Dockerfile, .dockerignore         前端镜像（node:22-alpine 构建 → nginx-unprivileged）
frontend/nginx/templates/*.template        nginx 配置模板（envsubst 渲染，WEB_* 变量）
deploy/
  compose.yml                                  生产编排
  compose.tls.yml                              覆盖：nginx 自己终止 TLS
  compose.dev.yml                              覆盖：开发环境（MinIO、vite、热重载、本地管理员）
  compose.local-oss.yml                        覆盖：本机 HTTP、真实 OSS、仅发布回环端口
  .env.example                                 环境变量模板
  secrets/README.md, .gitkeep                  机密说明（其余内容不入库）
  postgres/initdb/10-roles-and-databases.sh    角色与数据库初始化
  milvus/embedEtcd.yaml, user.yaml             Milvus 内嵌 etcd 与用户配置
  mlflow/Dockerfile, aws-config                MLflow 镜像与 S3 寻址配置
  dev/dev-init.sh                              开发环境：建桶 + 创建本地管理员
  scripts/lib.sh                               公共函数
  scripts/gen-secrets.sh                       生成 secrets
  scripts/preflight.sh                         部署前检查
  scripts/create-admin.sh                      创建首个账号
  scripts/healthcheck.sh                       整体健康检查
  scripts/backup.sh, restore.sh                备份与恢复（演练 / 就地）
  scripts/upgrade.sh                           升级与镜像回退
  check_compose.py                             编排静态校验（CI）
  README.md                                    本手册
```

CI 建议：`python3 deploy/check_compose.py`（需要 PyYAML；有 `docker compose` CLI 时自动追加语法校验；有 `shellcheck` 时自动检查脚本）。

### 11.2 后端提供的运行约定

以下均以 `backend/` 源码为准（出处列只写文件名，除注明外位于 `backend/src/bidwb/`）。

| 项 | 事实 | 出处 |
| --- | --- | --- |
| 命令入口 | `bidwb-api`、`bidwb-relay`、`bidwb-reaper`、`bidwb-worker`、`bidwb-admin`，由后端镜像的 venv 提供 | `pyproject.toml`、`entrypoints.py`、`admin.py` |
| API 监听 | 监听 `BIDWB_API_HOST`:`BIDWB_API_PORT`；配置默认 `127.0.0.1:8000`，后端镜像通过 `ENV BIDWB_API_HOST=0.0.0.0` 监听 `0.0.0.0:8000`，对外暴露范围由编排层决定（API 只在 `edge`/`data`/`egress` 网络内，不发布端口） | `config.py`、`entrypoints.py`、`backend/Dockerfile` |
| 健康检查 | `GET /healthz` 存活，返回 `{"status":"ok","version":…}`；`GET /readyz` 就绪，执行 `SELECT 1`，数据库不可用返回 503。容器健康用 `/healthz`，`scripts/healthcheck.sh` 用 `/readyz`；worker/relay/reaper 无 HTTP 端口，只检查进程存活（`bidwb-healthcheck proc`） | `api/app.py`、`backend/Dockerfile` |
| 接口文档 | `BIDWB_ENVIRONMENT=production` 时 `/api/docs` 与 `/api/openapi.json` 关闭 | `api/app.py` |
| worker 选择 | `BIDWB_WORKER_CLASS` 取 `parse`、`ai`、`experiment`、`export`，其它值以退出码 2 退出；消费主题 `job.<类别>`，消费组 `bidwb-<类别>`。任务种类到类别：`parse`、`rules` → parse；`diagnosis`、`revision`、`recheck`、`prediction` → ai；`experiment` → experiment；`export` → export。`BIDWB_WORKER_ID` 默认 `worker-local`，部署时静态且每服务唯一 | `entrypoints.py`、`tasks.py` |
| 已注册的处理器 | `parse`、`rules`、`diagnosis`、`revision`、`prediction`；其它种类（`recheck`、`experiment`、`export`）以 `kind_not_implemented` 失败，且通用入口 `POST /projects/{id}/tasks` 目前不接受任何种类，因此 experiment、export 类 worker 空转 | `ai/handlers.py`、`workers/handlers.py`、`workers/runner.py`、`tasks.py` |
| `bidwb-admin ensure-topics` | 幂等创建 `job.parse`(3 分区)、`job.ai`(3)、`job.experiment`(1)、`job.export`(1)、`domain.events`(3) 及各自 `.dlq` 死信主题(1 分区)；参数 `--replication-factor`（默认 1）；读 `BIDWB_KAFKA_*`，主题名带 `BIDWB_KAFKA_TOPIC_PREFIX` | `admin.py`、`messaging.py` |
| `bidwb-admin create-member` | 参数 `--login`、`--display-name`、`--password-file`（缺省读标准输入，不接受命令行明文口令）、`--if-not-exists`（登录名已存在时输出提示并以 0 退出）；使用 `BIDWB_DATABASE_URL`（API 角色） | `admin.py`、`access.py` |
| admin 的其它子命令 | `register-scoring-model`、`register-anchor-pack`、`unroute-scoring-model`、`unroute-anchor-pack`、`list-scoring-models`、`list-anchor-packs`、`export-score-pairs`；参数以 `bidwb-admin <子命令> --help` 为准。数据库角色由 PostgreSQL 初始化脚本创建 | `admin.py` |
| 迁移 | `alembic upgrade head`，工作目录 `/backend`；`migrations/env.py` 直接读环境变量 `BIDWB_MIGRATION_DATABASE_URL`，**不经 `*_FILE`**，所以 migrate 服务用 `sh -c` 从 secret 文件读入；只有初始迁移 `0001`，`downgrade` 直接报错，回退靠备份恢复 | `backend/migrations/env.py`、`0001_initial.py`、`backend/Dockerfile` |
| 配置读取 | 环境变量前缀 `BIDWB_`，未知变量忽略；凭据类变量支持 `BIDWB_<NAME>_FILE=/run/secrets/…`，进程启动时读取文件（去除首尾空白）并作为 `BIDWB_<NAME>`；同时设置 `X` 与 `X_FILE` 会报错；每个 `*_FILE` 指向的文件必须被该服务挂载 | `config.py` |
| 运行库连接串 | `BIDWB_RUNTIME_DATABASE_URL`（及 `_FILE`）对应 `bidwb_runtime` 库，可选；配置项存在，但当前没有代码使用 LangGraph 检查点，该库只做初始化与备份 | `config.py` |
| 数据库连接串 | API/admin 用 `BIDWB_DATABASE_URL`（`bidwb_api`）；relay/reaper/worker 用 `BIDWB_WORKER_DATABASE_URL`（`bidwb_worker`） | `config.py`、`runtime.py` |
| 生产环境校验 | `BIDWB_ENVIRONMENT=production` 时要求 `cookie_secure` 开启、`PUBLIC_BASE_URL` 以 `https://` 开头、会话 Cookie 名以 `__Host-` 开头，否则拒绝启动；`lease_renew_seconds` 不得超过 `lease_seconds` 的一半（对所有环境生效）。`worker_database_url` 只在 relay/reaper/worker 启动时校验，api、admin、kafka-init 无需配置 | `config.py`、`runtime.py` |
| 空值语义 | 配置按“空字符串等同未设置”处理（`env_ignore_empty`），所以未配置模型时 compose 传入的空 `BIDWB_LLM_*`、`BIDWB_KAFKA_TOPIC_PREFIX` 按默认值/未配置处理；内容为空的 `*_FILE` 同理。未配置模型时 AI 类任务以 `llm_not_configured` 明确失败 | `config.py`、`ai/llm.py` |
| 认证 | 账号加口令登录（口令以 Argon2id 哈希保存），账号由 `bidwb-admin create-member` 创建；没有单点登录 | `services/auth.py`、`api/routes_auth.py` |
| 开发热重载 | `BIDWB_API_RELOAD=true` 时 uvicorn 以 reload 方式启动；`PYTHONPATH=/app/backend/src` 优先于已安装包（`compose.dev.yml`） | `entrypoints.py` |
| 代理头 | uvicorn 以 `proxy_headers=True` 运行，信任 `BIDWB_FORWARDED_ALLOW_IPS` 列出的代理（默认 `127.0.0.1`，compose 设为 `*`，因为只有 web 能访问 api）。会话 Cookie 的 Secure 属性由 `BIDWB_COOKIE_SECURE`（默认 true）决定，与转发协议无关 | `entrypoints.py`、`config.py`、`api/routes_auth.py` |
| 对象存储 | 变量 `BIDWB_STORAGE_*`；键前缀 `staging/`（API 分片转传落点）、`objects/<sha256 前两位>/<sha256>`（内容寻址最终位置）、`artifacts/`（worker 产物）；签名由 `OSS_SIGNATURE_VERSION` 配置，OSS 用 `s3`，MinIO 用 `s3v4`；字节只经服务端读写。验证范围见 tender-docs《验证报告》 | `storage.py`、`config.py` |
| 自动评审流水线 | `BIDWB_AUTO_ANALYSIS`（默认 true，`.env` 中为 `AUTO_ANALYSIS`）：上传完成时 API 推进、任务结束时 worker 推进、reaper 周期兜底；因 reaper 要写 OSS，编排给它配置了 OSS 凭据与 egress 网络。关闭后只由人工触发各步骤 | `config.py`、`api/routes_files.py`、`workers/runner.py`、`workers/loops.py`、`services/pipeline.py` |
| 评审报告导出 | `GET /api/v1/projects/{id}/report.docx` 与 `GET /api/v1/projects/{id}/body.annotated.pdf` 在 API 进程内同步生成，依赖 `python-docx`、`pypdfium2`（`pyproject.toml` 已声明）；响应头 `Cache-Control: private, no-store`，不经任务队列与 worker-export | `api/routes_report.py`、`services/export.py`、`pyproject.toml` |
| 任务进度 SSE | `GET /api/v1/tasks/{id}/events`：每 15 秒心跳，单连接最长 600 秒，支持 `Last-Event-ID` 续传 | `api/routes_tasks.py` |
| 检索与 MLflow | 默认 keyword，可选 pgvector＋本地 BGE；语义通道要求完整匹配的项目／版本索引，否则回退关键词。Milvus 配置保留兼容但未连接；MLflow 范围外 | `retrieval.py`、`embeddings.py`、`services/vector_index.py`、`config.py` |
| 日志 | stdout JSON 单行；访问日志只记路径与状态码；对 password、secret、token、authorization、cookie、signature、api_key、dsn 等键名做兜底脱敏 | `logs.py`、`api/app.py` |

### 11.3 前端提供的构建与运行约定

| 项 | 事实 | 出处 |
| --- | --- | --- |
| 构建 | `npm ci && npm run build` 生成 `dist/`（`build` 脚本含 `tsc --noEmit`）；`package-lock.json` 已提交，镜像构建严格按锁文件安装 | `frontend/package.json`、`frontend/Dockerfile` |
| 路由 | history 路由，nginx 回退到 `index.html`；资源路径使用 `/assets/` 前缀（Vite 默认） | `frontend/nginx/templates/app-locations.inc.template` |
| 资源 | PDF.js worker 随应用打包；中文原件所需的 CMap 与标准字体在构建时复制到 `dist/pdfjs/`，不引用外部 CDN、字体与脚本 | `frontend/vite.config.ts` |
| API | 全部走同源 `/api/v1/...`；SSE `/api/v1/tasks/<id>/events`；文件内容 `/api/v1/files/<id>/content` 支持 Range；报告下载链接直接指向 `report.docx` 与 `body.annotated.pdf` | `frontend/src/api/endpoints.ts` |
| 超时与限流 | nginx 对 SSE 读超时 3600 秒并关闭缓冲，对文件内容 300 秒，对其余 `/api/` 120 秒（报告导出属于后者），登录单独限流 | `app-locations.inc.template` |
| CSP | `script-src 'self' 'wasm-unsafe-eval'`、`style-src 'self' 'unsafe-inline'`、`img-src 'self' data: blob:`、`worker-src 'self' blob:`、无 `frame-src`（回退到 `default-src 'self'`）；如前端新增内联脚本、`eval`、外部域名或 iframe 预览，须同步调整 `security-headers.inc.template` | `security-headers.inc.template` |
| 开发 | `vite dev` 的 `/api` 代理使用环境变量 `API_TARGET`（缺省 `http://localhost:8000`，`compose.dev.yml` 设为 `http://api:8000`） | `frontend/vite.config.ts`、`compose.dev.yml` |

### 可选 pgvector 检索

默认保留 keyword。固定开发参考集存在页码召回退化，不能据部分摘录改善默认切换；结果见研究仓库 results/hybrid-retrieval-1。详细运行契约见 ../contracts/retrieval.md。

增量迁移 0002 只创建可重建的 REAL[] 索引表，纯 PostgreSQL 也能迁移；API 只读，worker 可回填。升级前备份业务库，统一更新 API、relay、reaper 和所有 worker；不修改已部署的初始迁移。正式业务库仍使用 PostgreSQL 16.15 和 keyword。

要在独立验证环境启用，先预备与 bidwb/embeddings.py 固定摘要一致的 model.onnx、tokenizer.json，放入 compose.pgvector.yml 声明的只读路径。该组合固定 pgvector 0.8.7 / PG16 Bookworm 镜像摘要，已实测其 PostgreSQL 为 16.15；其他架构仍应核对，不能升级主版本或删除数据卷。由数据库管理员在业务库执行 CREATE EXTENSION IF NOT EXISTS vector，再加载 compose.pgvector.yml。扩展安装不使用 API 或 worker 凭据。

新资料启用后自动生成向量；既有项目用具备 worker 凭据并挂载模型的 parse worker 执行：

```bash
docker compose -f compose.yml -f compose.pgvector.yml exec worker-parse bidwb-admin rebuild-vectors --project <项目ID>
```

回填分批提交、可重跑；未完全回填的查询保留关键词结果并声明缺口。索引可重建，不替代原件或核验结论。大库性能、真实工程检索质量与 Milvus 退出尚未验收。
