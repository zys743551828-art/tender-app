# 独立完整本机运行配置

本配置把 API、对象存储、消息传输、Worker 和协调器放在一个**显式选择的新环境**中。入口为 `deploy/compose.fusion-full.yaml`，运行配置协议为 `fusion-full-local/1`。它不修改或接管现有 `tender-fusion / fusion_v12`，不复用其数据库、卷、账号或初始化凭据，也不是旧数据库升级工具。

## 服务与启用边界

| 服务 | 默认启动 | 运行职责与边界 |
| --- | --- | --- |
| PostgreSQL 17 + pgvector | 是 | 新数据库；API、Worker 各自使用非 owner LOGIN。数据库端口不发布到宿主机。 |
| Kafka | 是 | 独立单 broker 本机集群，固定集群 ID；校核 9 个已实现主题、分区数和保留配置。不作为生产高可用证明。 |
| SeaweedFS S3 | 是 | 私有的新 bucket；初始化、API、Worker 三套独立凭据。API/Worker 权限限制在此 bucket。S3 端口不发布。 |
| API + Web | 是 | 仅 Web 绑定 `127.0.0.1`，默认 5189。原件上传、授权刷新和下载使用同源 Cookie + 短票据。 |
| outbox relay、reconcile | 是 | 实际数据库与 Kafka 传输、既有阶段协调和重试协议。relay 不获得对象存储凭据。 |
| document、export、comparison Worker | 是 | 各自固定消息通道；使用 Worker LOGIN，不继承 API/owner 凭据，也不获得模型密钥。 |
| build、Word 协调器 | 是 | 执行已有明确选择后的协调与采用。缺少合格的转换环境时保留不可用状态。 |
| review、assistant Worker 及相应协调器 | 否 | 先在配置时显式提供真实受支持的模型配置，再在启动时加 `--model`。缺密钥、有效官方价格或全局预算时拒绝相应执行进程；每次调用仍受既有项目/成员预算、来源及账本守卫约束。 |
| task runner | 否 | 配置时加 `--enable-task-runner`，启动时另加 `--automation`。初始化不创建任务、模板、定时器或通知接收人。 |

“task runner 默认不启动”和项目的 `auto_review` 偏好是不同概念。项目创建时的既有自动评审偏好保持原协议；本配置没有改成 false。未启动付费通道、缺少模型/费用配置或资料资格不足时，不能据此宣称评审已经执行。

全局助手独立运输通道、研究训练/评估/正式评分消费者不在本配置内。启动本组不会赋予训练、正式计分或标准提交资格。

## 新库安装内容

初始化按 `deploy/schema_plan.py` 当前 `BASE_SQL` 的精确字节顺序执行，然后追加以下 6 个已经存在的扩展。配置文件冻结每个 SQL 的路径与 SHA-256；同一初始化过程中不重新读取另一版 SQL。

1. `packages/word_intake/schema.sql`
2. `packages/knowledge/sql/rag.sql`
3. `packages/assistant/sql/assistant.sql`
4. `packages/assistant/sql/live-facts.sql`
5. `packages/assistant/sql/intent-budget.sql`
6. `packages/assistant/sql/generation-batches.sql`

当前完整主应用配置为**43个SQL**：37个BASE，加上上述6个扩展，数量按实际schema_plan核对。默认v14预览只安装37个BASE，不能当作本完整组。先前主链原生验收的39个SQL／170张表以及可选研究恢复收据保持各自当时范围，不把后来增加的SQL算作旧运行中已安装，也不表示本组启动了研究消费者。

PostgreSQL的Compose执行配置明确为`postgres -c jit=off`，结构校验拒绝覆盖。指定训练导出在本机已比较开／关JIT的同一内容摘要与耗时，见[派发及执行配置验收](package-history-dispatch-acceptance.md)；该结果不代表整体吞吐或生产容量通过。

Word 原件接收显式启用。Word→Rich 导入继续使用真实 OOXML 解析与损失确认。Word→PDF、Rich 导出所需的隔离渲染配置、OCR 服务、语义检索模型资产不会被伪造或自动下载。缺少这些配置时，应用继续返回准确的不可用/部分覆盖状态。默认 PDFium 物理页文字读取不等同于表格、图纸和视觉完整理解。

## 准备新的私有配置

使用 Linux 或 WSL 的本机工作目录。需要已有 Docker Compose、允许本机使用的三个固定基础设施镜像，以及明确的 Python 和 nginx 镜像内容摘要。配置工具不会下载镜像或启动容器。

Python 镜像须安装 `deploy/fusion_full_requirements.txt`：原有 `requirements.lock.txt` 全部精确版本，加 Rich/OOXML 所需的 Pillow 固定版本。初始化实际核对已安装版本；单纯传入一个镜像名字不会通过依赖检查。`--python-image` 和 `--web-image` 必须采用 `repository@sha256:...` 形式，且已在本机可用。Compose 使用 `pull_policy: never`。

先用终端交互方式将管理员口令写入一个新的权限 600 文件，避免口令出现在命令行、环境展开、Git 或日志中。口令至少 8 字符。然后执行以下模板，将镜像和文件位置替换为自己的实际选择：

```bash
python -m deploy.fusion_full_configure \
  --directory "$PWD/.local/full-preview-v1" \
  --name full_preview_v1 \
  --origin http://127.0.0.1:5189 \
  --python-image "$APP_IMAGE_WITH_SHA256" \
  --web-image "$NGINX_IMAGE_WITH_SHA256" \
  --admin-password-file "$PRIVATE_ADMIN_PASSWORD_FILE"

python -m deploy.fusion_full_control validate \
  --directory "$PWD/.local/full-preview-v1"
```

配置目录必须是新目录，名称使用简单路径字符；环境名以 `full_` 开头，总长不超过 20 字符。工具生成的新 owner 密码、S3 凭据、会话密钥和私有配置权限均为 600，目录权限为 700。`compose.env` 只含路径、镜像与公开集群身份，没有数据库密码、模型密钥或 S3 密钥。

Compose 项目名由环境名和本次 `deployment_id` 的前 12 位共同组成。同样的显示名称在两个新目录中生成不同的项目名与卷命名空间；控制命令必须使用对应目录，不能仅凭显示名称去停止另一个实例。两个实例同时运行时还应选择不同的 loopback Web 端口。

配置同时冻结后端源码、SQL、执行策略、前端产物与镜像摘要。若源码、SQL 或前端在配置后改变，启动校验会拒绝使用原配置。应明确生成新候选配置/新空环境并完成验收；本入口不会修改旧数据库、替换旧回执或自动“修好”部分初始化。

## 显式启动与检查

```bash
python -m deploy.fusion_full_control up \
  --directory "$PWD/.local/full-preview-v1"

python -m deploy.fusion_full_control status \
  --directory "$PWD/.local/full-preview-v1"
```

`up` 先做结构和身份校验，再执行真实 `docker compose config --quiet`，最后启动所选服务。没有 Docker 时明确退出，不把静态 YAML 检查当作容器执行通过。

初始化只允许空目标。它建立新数据库与账号、Kafka 主题、S3 绑定标记、管理员账号和独立运行 profile，最后才写初始化回执。若发现已经存在目标数据库但缺少完整回执、运行 profile 只写了一部分或 bucket 已被使用，会拒绝继续修补。保留私有状态供排查，选择另一个明确的新环境；不要删除现有数据库或覆盖文件来绕过检查。

成功初始化后，以 `admin` 和创建时的管理员口令登录所选 loopback 地址。启动器会清除继承的其他 DSN、模型配置、代理、测试适配器、渲染配置等变量，只向每个固定组件传入其允许的值。API 不挂载初始化状态目录。原件临时对象核对日志单独放在 API 专用可写目录。

初始化器单独以 UID 0 运行，先移除全部 capabilities，再仅增加 `CHOWN` 与 `DAC_OVERRIDE`：前者把新业务 profile 交给 UID 65532，后者让初始化器读取普通宿主用户创建的 0700 目录和 0600 文件。仅 `CHOWN` 不能读取这类目录，真实 Linux 权限测试覆盖了该反例。业务进程和 Web 均保持 UID/GID 65532、只读根文件系统、`cap_drop: ALL` 和 `no-new-privileges`；初始化器权限不传递给业务组件。

Web 使用仓库提供的完整 `nginx-fusion-full-main.conf`，显式加载本组 server 配置，不依赖镜像默认的 PID、缓存路径或用户切换。主配置没有 `user` 指令，PID 与所有临时路径都位于独立 `/tmp`，静态文件和两个配置文件只读挂载。普通 JSON、单次源文件和分片分别采用既有的 5 MiB、100 MiB、8 MiB 限制；仅实际源文件传输入口获得更大的请求体上限。

每个 Python 组件启动前、运行 healthcheck 时，会验证：

- 当前源码、SQL 计划和执行策略与所选配置一致；Python、已安装依赖与实际 libpq、librdkafka、PDFium/Pillow 编解码身份保持一致。
- 数据库登录身份正确，不是 owner/superuser，不具有额外角色、建库、创建角色、复制或绕过 RLS 权限；必要功能表存在。
- 需要对象存储的组件以自己的真实凭据读取初始化标记，检查实际长度和 SHA-256。
- 需要 Kafka 的组件检查真实集群 ID、9 个主题及其配置，检查期间不创建缺失主题。
- 付费通道另核实际官方价格和有效全局预算。此检查不会调用模型，也不代表特定业务请求已经获准发送。
- API healthcheck 还直接访问容器内固定的 `127.0.0.1:8000/health/ready`，要求真实 200 与准确的健康响应。依赖检查成功但 HTTP 尚未监听时，API 不会被标为健康；此探测不使用继承代理或调用者提供的 URL。

数据库健康检查的 SQL 身份边界是“初始化按冻结 SQL 字节执行，并核对必要表和角色”；它不是对运行库所有对象逐一进行的持续 DDL 审计。当前完整对象、ACL 与原件恢复比对由独立备份恢复验收覆盖。

HTTP 访问日志和代理错误日志避免记录带票据的 URL。故障定位应使用健康检查的固定错误码、非敏感组件启动信息、数据库既有操作/阶段回执，而不是收集私有原文、Cookie、签名票据或完整连接字符串。

## 模型和任务必须分别选择

模型配置使用权限 600 的严格 JSON，只允许 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL` 三个字段，且型号和端点必须被当前真实 provider 端口支持。配置时用 `--model-profile` 指向这个文件。不会接受 Mock 模型或任意代理地址来冒充真实服务。

官方价格和预算由已有专用预算管理工具登记；初始化生成的预算管理员 profile 留在私有初始化状态中，业务服务不会得到它。不要用 owner 执行业务或费用配置来绕过权限检查。费用未核清、缺少价格或预算时，保留系统返回的阻断，不人为填入合成“官方”价格。

有真实配置且明确决定启动相关通道后，才使用：

```bash
python -m deploy.fusion_full_control up \
  --directory "$PWD/.local/full-preview-with-model" --model
```

任务运行还需要配置时的 `--enable-task-runner` 和启动时的 `--automation`。这两个选择不会替代每个模板、来源、项目生命周期和调用费用的既有校验。自动化可与模型选择分开；没有模型时涉及模型的任务会保持不可执行状态。

## 停止和数据保留

```bash
python -m deploy.fusion_full_control down \
  --directory "$PWD/.local/full-preview-v1"
```

停止命令不带 `--volumes`，不会要求删除数据库或对象卷。曾使用额外 profile 时，停止命令应保留相同的 `--model` / `--automation` 选择。私有配置和初始化回执应与卷一起妥善保管；不要把凭据复制进问题单或 Git。

本配置只面向显式本机使用。单 broker、私有 loopback、未配置外部渲染/OCR/RAG 以及未验证的真实模型业务效果，均不能由一次容器健康检查升级为生产可用或业务审查完整性。

## 本机验收入口与证据

实际主链、平台权限和配置回归的范围见 [完整运行配置验收记录](full-runtime-acceptance.md)。原生验收使用明确指定的已有 PostgreSQL、Kafka、SeaweedFS 二进制，每次创建独立目录、端口、账号、数据库和 bucket，结束后清理自己的进程；它不连接共享测试端口 55441，也不调用模型。

```bash
python -m deploy.fusion_full_native \
  --pg-bin "$EXISTING_PG_BIN" \
  --weed "$EXISTING_WEED_BINARY" \
  --kafka-dir "$EXISTING_KAFKA_DIRECTORY" \
  --receipt "$NEW_PRIVATE_RECEIPT_PATH"
```

默认只执行固定的原生主链测试模块。另一个明确选择为 `--suite transport-faults`，仅可执行固定的真实故障恢复测试模块，使用同样隔离的新环境和较长超时；测试自行验证本轮进程身份后才注入故障。启动器不接受任意测试文件或 shell 命令。故障测试输出固定阶段标签，不输出连接字符串或私有进程配置。

本次已实际执行原生服务和独立 nginx。当前机器没有 Docker/容器运行时，因此没有宣称执行了 Compose 容器；结构校验、原生服务测试和容器实测是分别记录的证据。
