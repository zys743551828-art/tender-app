# 无新增权限的受限原件GET传输

`original_bytes.prepare_get`只接已有已授权控制器在私有进程内提供的GET地址、固定profile、项目／scope／文档身份及预期原件摘要和长度，不读取数据库、环境配置、凭据或签名器。URL及正文位于repr关闭的私有对象，metadata只保留URL摘要。此对象不是原生授权、核验binding或公开HTTP请求。

profile只接受指定杭州OSS HTTPS源，或明确development_s3的Docker内部object-store:8333／127.0.0.1测试地址；无任意外部主机、userinfo、fragment、控制字符或无限URL。URL最多8192字节，原件最多32MiB，布尔不能冒整数。调用方必须提供owned冻结的请求及方法摘要；读取前重建封闭metadata并按canonical字节比较，不能改URL、补字段或将false换成0。

读取只有一次GET，无重定向、环境代理或自动重试。总async deadline最多30秒，固定identity编码、只接受200，拒绝编码转换、Content-Range、矛盾／非法长度、超限、中断或字节摘要不匹配。按64KiB原始响应块读取，最终长度与完整SHA-256同时匹配才返回私有字节对象，读取后方法变化也拒绝。公开异常只有安全错误码；网络异常不附URL或异常上下文。独立字节进程禁止HTTPX／HTTPCORE普通请求日志输出私有key和签名查询，不在API进程安装该读取器。

回执只有`complete_requested_bytes_verified=true`，其含义是实际取得字节与控制器提供的预期值匹配。`native_permission_verified/necessary_scope_verified/input_authority_granted/execution_authorized/historical_existence_verified`均false。没有当前权限数据库证明、原件历史存在性、完整输入或正式评分资格，也不把旧快照登记时间当成这次读取时间。

独立原件locator的SECURITY DEFINER／角色继承扩展仍未实施，须按[具体权限方案](../../docs/completion-20261021/original-locator-permission-review.md)取得明确许可。当前传输不创建或代替该授权入口，不接真实OSS凭据、真实标书或模型执行。
