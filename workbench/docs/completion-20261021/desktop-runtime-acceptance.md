# Windows 完整 Compose 文件链验收

## 结论与范围

独立完整 Compose 在 Docker Desktop 本机实际通过，最终候选 `tender-fusion-full-84f162c8966d`，回环入口 5189，43 项 SQL、157 张 design 表。12 个默认常驻服务运行；configure／init／publish 成功退出。验收结束后整组停止，数据卷保留，收费模型和自动任务服务均未启动。普通 5188 预览仍健康，1149 运行输入和 65 项生产 JS／CSS 资源逐字节匹配，实际登录／会话／退出通过，业务项目 0，研究可选扩展准确返回 503。

这证明本机容器装配与合成文件链，不证明生产主机、复杂版式、转换沙箱、真实模型效果或正式评分资格。前端没有变更，1731 项前端与 4 项实际 OpenAPI 生成仍沿用本轮早段结果，不重复计作本切片重跑。内置浏览器加载器在页面控制前引用缺失的 `browser/26.1016.62342/scripts/browser-service.mjs`，本切片没有截图或视觉通过。

## 实际检查

- 最终固定 Linux checks：**191 项通过，12.38 秒，0 跳过**；包含 162 项已有配置／协议检查、22 项桌面装配与路径反例、7 项 POSIX 私有文件检查。Windows 22 项也通过，与 Linux 套件重叠，不相加。Ruff 检查和 9 文件格式检查、6 个实现文件 mypy（Linux 目标）、4 个新实现 Bandit 通过。
- 独立 checks profile 以 UID 65532 通过真实 nginx HTTP 登录，合成两页 PDF 同源上传，经真实 Kafka relay 和独立 document Worker 完成校验、批次提交及明确独立解析。下载原件与上传字节完全一致。默认覆盖保持 partial，当前正文和核查指针仍为空。
- 上传授权刷新后旧票据拒绝；匿名上传／下载拒绝；同账号不同会话的上传票据拒绝。对象存储的匿名访问、错误密钥、其他桶写入拒绝；指定桶实际 PUT／GET 字节一致。模型调用、助手任务和自动定义均为 0；验收仅保留 1 个明确标记的合成项目。
- 在真实运行的 API、Worker、relay、reconcile、controller 中分别读取画像并验证：UID 65532、目录 700、文件 600、数据库非 owner、原 readiness 通过。实际 Docker 挂载均只读使用自身画像，业务服务没有 operator 挂载；源码只读。基础设施不发布主机端口，Web 只发布 `127.0.0.1:5189`。

证据见[回执](evidence/desktop-runtime/receipt.json)、[真实角色和挂载](evidence/desktop-runtime/runtime-isolation.json)、[文件链](evidence/desktop-runtime/verify-final.log)、[191 项 JUnit](evidence/desktop-runtime/desktop-pure.xml)与[5188 实测](evidence/desktop-runtime/preview-http-runtime.json)。操作见[运行手册](desktop-runtime-runbook.md)，权限和身份契约见[桌面运行协议](../../packages/contracts/fusion-desktop-runtime.md)。

## 修复依据与保留失败

完整运行原配置的 SeaweedFS digest 实际为 3.97，不支持自动建桶及额外协议端口参数，且 `s3.iam` 名称不正确。固定替换为实际核过公开 OCI 标签和二进制帮助的 4.48 内容 digest `sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`。保留 IAM 禁用、Iceberg／Lance 端口 0、禁止自动建桶和非空桶删除，并增加结构拒绝反例；没有通过删除安全参数使启动通过。[实际帮助](evidence/desktop-runtime/object-image-help.log)只包含公开选项，不含凭据。

早期候选失败依次为 Windows 环境正向列表漏掉 Docker 插件发现所需标准目录、Linux 公共 SQL 路径在 Windows 误比较分隔符、PostgreSQL 密钥文件的横线／下划线不一致、旧存储镜像参数不兼容、新 Linux 状态卷 755 被既有严格初始化器拒绝。修复后只对空新卷设 700，非空权限异常仍拒绝。增加原始结构核验时有过 WindowsPath 引起的 11 失败／11 通过，改用 Linux 内部 PurePosixPath 后最终 22／191 通过。各候选原本地日志和冻结卷保留，失败组全部停止，不修复旧身份或把旧失败结果改写成通过。

首次完整成功候选 check5 经实际文件链通过后停止；将本次修改的 Python 原文件规范为 Git LF，再以最终 check6 重新初始化和复验，避免旧私有计划被重写。原 admin 口令策略保持不变；新验收口令在 Linux 私有卷内部强随机生成，登录只交给独立验收卷，不输出到主机描述、日志或 Git。没有安装新的 Python／Node，不启动已关闭的 dev／Claude 容器，不改正常 Word 服务。

## 发布字节与后续边界

9 项新改部署输入逐项核对验收文件、冻结计划和 Git 暂存字节；43 项 SQL 单独记录验收原始 SHA、Git SHA 和实际 `read_text()` 执行文本 SHA。3 份既有 CRLF SQL 与 Git LF 字节不同，但执行文本相同：`bid-package-review-inputs.sql`、`bid-package-review-input-runtime-grants.sql`、`packages/word_intake/schema.sql`。不重新格式化这些旧来源，也不宣称整树原始字节完全一致。证据目录固定 `-text`，回执逐项记录原始 SHA，历史证据不改写。

检查组 checks／checks-postgres 已停止。完整候选卷包含独立合成库和原件，保留用于复核，不含现有业务迁移。下一项为项目整包摘要和六级主要动作；正式图文三评、受控发布、转换隔离、完整视觉和真实业务验收继续独立实施。用户已说明真实评分配对暂无，不重复索取，后台自动接续保持关闭。
