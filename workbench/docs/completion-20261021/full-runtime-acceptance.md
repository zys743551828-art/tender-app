# 独立完整运行配置：本机验收记录

日期：2026-10-21。范围为独立 `fusion-full-local/1` 配置、同源对象传输和显式本机验收入口。所有输入均为合成夹具，模型调用、付费调用及新建定时任务均为零；没有连接生产环境。

## 已交付的运行路径

本组提供一个与现有 API-only `fusion_v12` 分开的运行入口。默认组包含独立 PostgreSQL、Kafka、私有 S3、API/Web、outbox relay、reconcile、document/export/comparison Worker，以及 build/Word 协调器。模型通道和任务 runner 分别要求配置与启动两次明确选择，不能从宿主环境借用模型密钥或把测试适配器解释为真实 provider。

配置、初始化、检查和控制入口分别为 `deploy/fusion_full_configure.py`、`fusion_full_init.py`、`fusion_full_probe.py`、`fusion_full_control.py`。`fusion_full_runtime.py` 为各个固定组件生成正向环境白名单并执行既有业务进程。完整操作步骤见 [运行说明](full-runtime-runbook.md)。

每个业务角色只得到自己的非 owner 数据库登录和必要凭据。API、Worker 对象凭据不同，均限定于本环境 bucket；relay 不拿对象存储密钥。API 单独挂载可写的临时对象登记目录，不挂载初始化 owner 状态。每次部署的项目名带随机部署身份，同名的新目录也不会共享项目名与卷命名空间。

对象传输保持现有 Cookie、CSRF、短期票据与授权修订协议。`packages/domain/object_transfer_mode.py` 允许显式选择配置好的 S3/OSS 的 `same_origin` 模式；默认行为保持原协议。实际 API 的创建上传、刷新授权和下载入口使用该选择，不把内部 S3 主机名返回给浏览器。

## 证据与实际结果

| 验收 | 实际结果 | 证据范围 |
| --- | --- | --- |
| 配置及旧部署回归 | 115 passed / 17.43 秒 | 新配置、角色/环境白名单、来源/SQL/依赖漂移、项目隔离、HTTP 健康响应、旧 Compose/bootstrap、同源选择边界 |
| 原生 PG + Kafka + S3 主链 | 5 passed / 12.04 秒 | 真正新库、真实角色、S3/Kafka、独立 Worker/协调器进程、API 授权与文件流转 |
| 原生 nginx 与 Linux 权限 | 3 passed / 0.81 秒 | 真实 nginx 二进制、UID/capabilities、只读配置、传输限制、反向代理和初始化器访问权限 |
| Ruff / format | 13 个文件通过 | 新运行脚本、辅助模块及相应测试 |
| mypy | 9 个源码文件通过 | 新运行脚本及同源选择模块 |
| Bandit | exit 0，无问题项 | 新运行脚本及同源选择模块；现有 nosec 注记产生的提示不等于安全扫描问题 |

运行配置纯回归命令为：

```bash
python -m pytest -q \
  tests/test_fusion_full_profile.py \
  tests/test_object_transfer_mode.py \
  tests/test_fusion_compose.py \
  tests/test_bootstrap_fresh.py
```

两个公开收据保留生成时的原始字节，不包含口令、DSN、Cookie、签名票据或业务原文：

| 文件 | SHA-256 |
| --- | --- |
| [原生主链收据](full-runtime-native-receipt.json) | `f42e6ce30705921c55829ffe72f883445924ce4dd76c201fe129c0547b8d1850` |
| [nginx 与权限收据](full-runtime-platform-receipt.json) | `3b6c79fdb51c7b9d5214a96fc3854ef1b1a12b10fc819aec57bbc73a9abcccc8` |

主链收据时间为 `2026-10-21T04:08:54.371748+00:00`，冻结计划摘要为 `43509ff9ba6ae637e408c9085a7c7192b718c61f42b605d469c759be96bcfd63`。当时真实初始化 **39 个 SQL、170 个表**。随后当前候选增加精确整包任务 SQL，计划变为 **34 个基础 SQL + 6 个扩展 = 40 个 SQL**；旧收据没有被改写为新计划证据。当前候选的真实故障恢复测试使用新环境独立执行，其结果由对应故障验收记录给出。

## 主链验证了什么

原生入口 `deploy/fusion_full_native.py` 仅接受明确给出的已有本地二进制。每次生成新的私有目录、PostgreSQL、Kafka 集群、S3 凭据与 bucket，选择自己的 loopback 端口，不使用共享 PG 55441。测试结束后关闭自己的子进程、停止自己的数据库并清理测试目录。原生测试的合成镜像名仅用于闭合配置结构，没有执行对应容器镜像。

真实初始化安装冻结 SQL、创建 9 个 Kafka 主题和 S3 绑定对象，生成 API、Worker、controller、relay、reconcile 五类独立 profile，并以非 owner 身份检查运行依赖。相同初始化回执重放没有发生新写入。数据库额外角色成员关系、错误 Kafka 集群 ID 均被拒绝；还原到原身份后重新就绪。

S3 验证实际使用 API 与 Worker 各自的凭据读写对象。两个角色分别尝试写入另一个 bucket，均被拒绝。错误密钥、损坏绑定对象和缺失绑定对象均使检查失败；恢复正确字节后重新通过。它没有只依靠对象 metadata 声称 SHA 已核实。

主流程通过真实 API 路由和真实数据库 Cookie 登录，创建项目和上传批次，取得同源上传授权，再刷新授权修订。旧修订票据被拒绝；未登录上传被拒绝；同一成员的另一独立会话持自己的有效 CSRF，仍不能使用原会话票据。合格请求把合成 PDF 原字节真正写入私有 S3，经授权完成、outbox、Kafka 和独立 document Worker 校验，随后提交批次、生成精确文档解析结果，最终认证下载得到相同字节。

该 PDF 共 1,860 字节，SHA-256 为 `86ebad9b389b96b4ee1852043f3ae00ed304a91472a2f7b741339c316af0c2b7`。解析结果如实保持 `partial`，没有生成虚假的完整覆盖或正式评分结果。未经认证的下载被拒绝。过程没有改变当前正式正文、没有 assistant job、没有模型调用。测试实际启动了 relay、reconcile、document/export/comparison Worker 和 build/Word 协调器七个独立进程；API 通过 ASGI TestClient 驱动真实路由和数据库，未把这一点描述为已经启动生产 HTTP 服务器。

使用的本地运行身份包括 CPython 3.12.14、PostgreSQL 17 系列、Kafka 4.1.2、SeaweedFS 4.48；完整 Python 包、libpq、librdkafka、PDFium/Pillow 编解码身份列于原生收据。三个执行二进制/主 jar 的 SHA 均被记录，避免只记录可变路径：

| 组件 | SHA-256 |
| --- | --- |
| PostgreSQL | `5d1c97318ff20152817ab9a52fd33593f3fe352f7128318e8c66276c9351021d` |
| SeaweedFS | `8c07a1ccc4ec058cd90989ac0533c30436832e41c63de2b26f37253d9f744c4d` |
| Kafka server jar | `7bb9b7db4d7877d2ab4c0a7ae40ad2cf96a4c5735b9f68432cce30157f4aeabd` |

## 平台复核发现与修正

独立审阅指出，任意固定摘要的 nginx 镜像仍可能使用需要 root 的默认 PID、缓存或用户配置。因此新增完整主配置，PID 和所有临时目录都写入 `/tmp`，只加载本组 server 配置、明确的静态 MIME 类型，无 `user` 指令。Web 指定 UID/GID 65532、零 capabilities、只读根和只读静态/配置挂载，不依赖镜像默认 entrypoint。

实际验证使用 Ubuntu 提供的 nginx 1.24.0 二进制，SHA-256 为 `1f16b72bea2f44e5d04fe6cf9e3e4b0dec53a82c50c7c1533c302a8ecaeccacf`。测试只将容器固定路径和上游地址换成自己的临时目录与 loopback 端口，其余配置保持一致：

- `nginx -t` 真实通过；master 的实际 UID 为 65532，`CapEff` 为 0，PID 位于私有临时目录。
- 静态 JavaScript 返回正确 MIME，SPA 路径回落到入口文件。
- 6 MiB 源文件与第 10,000 个 7 MiB 分片真实转发，字节 SHA 相同；超过源文件 100 MiB、分片 8 MiB 和普通 JSON 5 MiB 上限时分别返回 413。
- Host、Origin、CSRF 和 Cookie 原样到达合成 HTTP 上游；上游停止后返回 502。
- 含私有合成票据的请求经过成功和上游失败两种路径，进程日志均不含票据。

这里的上游为专用 HTTP 传输夹具。它验证真实 nginx 的反向代理行为，不冒充另一轮 API/Worker 业务主链。相关配置行为可对照 [nginx 命令行](https://nginx.org/en/docs/switches.html) 和 [反向代理模块](https://nginx.org/en/docs/http/ngx_http_proxy_module.html) 的官方说明。

权限复核还证明，初始化器仅有 `CHOWN` 时无法读取由宿主 UID 65532 创建的 0700 目录和 0600 文件。现在初始化器从 `cap_drop: ALL` 仅增加 `CHOWN` 与 `DAC_OVERRIDE`，实际子进程能力掩码为 `0x3`，能够读取原私有文件且没有放宽文件模式。业务进程仍无 capabilities。

第三个问题是相同显示名可能让两个配置目录共享 Compose 项目。现在项目名带本次部署 ID 的短后缀，控制器核对准确绑定；两目录同名的回归测试证明项目名不同。API readiness 同时增加固定 loopback HTTP 响应检查，覆盖监听尚未建立、错误状态/响应和重定向的拒绝路径。

## 限制与后续验收边界

本机没有 Docker 或其他可用容器运行时，所以本记录不声称 Compose 容器已经实际运行。已验证的是配置结构、真实原生 PG/Kafka/S3 业务路径及独立原生 nginx/权限路径。部署镜像本身的启动、卷挂载和网络命名空间仍应在明确的新容器环境中验收。

数据库 readiness 核对登录权限、必要表以及冻结初始化身份，未逐一审计运行库全部 DDL。完整表、ACL 和对象恢复比对属于独立的备份恢复记录。这里也没有执行 OCR、Office 隔离转换、语义检索、真实模型效果验证、正式评分或研究消费者；这些能力和资格保持各自已有的真实配置与业务守卫。

故障套件只允许 `native` 与 `transport-faults` 两个固定选择。后者使用本轮私有进程 ID/目录，先核对身份，再验证真实中断和自然租约恢复；它不能接收任意脚本，也不把缩短租约或直接改数据库状态当作自然恢复证据。
