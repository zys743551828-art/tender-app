# 无新增权限的原件GET完整字节验收

[受限GET传输](../../packages/contracts/package-original-get.md)只消费已有授权控制器在私有进程内提供的地址及owned冻结的项目／scope／文档／摘要／长度。无数据库、凭据发现或签名器，URL及正文不进入repr或公开metadata。读取端固定一次GET、identity原始响应、30秒内总async deadline、32MiB上限，拒绝跳转、部分响应、编码转换、矛盾长度、超限、中断和SHA-256错配；请求和方法摘要错配或读取中方法变化也拒绝。

最终Linux Compose54项2.55秒通过（35传输、7隔离导入／实际错误兼容、12编排），Windows42项2.77秒通过，范围重叠。四文件Ruff／format、两实现mypy／Bandit通过。显式MockTransport覆盖拒绝和超时，真实回环HTTP完成GET及签名日志保护，另有结构化43字节真实TCP读取回执；没有外部OSS／S3对象读取、真实标书或付费调用。

私有URL异常上下文反例在修复前实际失败：HTTPX格式错误保存了合成签名文字。URL解析退出异常处理后才抛安全码，最终异常上下文为空；网络失败同样不附URL或上下文。源文件异常出口明确NoReturn，收紧类型检查的可空路径；原失败与最终日志见[证据回执](evidence/original-get/receipt.json)。独立读取进程抑制HTTPX／HTTPCORE请求日志，不在API安装读取器。

只有`complete_requested_bytes_verified=true`，不授native权限、必要范围、输入权威、执行或历史原件存在性。原页、来源／范围观察、输入、图文判断及特征方法均保持，旧manifest／报告／回执不改。5188为1193输入／68资源逐字节匹配，登录／会话／退出与错误响应通过，三服务健康，业务项目／付费0；检查库／临时LOGIN／新原件角色0，checks／检查PG／renderer停止，正常Word及其他环境保留。无前端变化和新增视觉验收，浏览器缺模块仍保留。

## 需要明确许可的后续

自动审批拒绝新增原件定位SECURITY DEFINER RPC、角色继承和私有locator返回能力，理由是现有授权没有明确覆盖此访问边界。被拒SQL和类型补丁没有执行，没有新增数据库权限；本传输不绕过或代替该授权。具体角色、参数、返回值、风险及仅在独立检查库验证后清理的范围见[权限审批方案](original-locator-permission-review.md)。批准后才能继续该入口；必要范围、独立原生核验binding、发送前CAS／lease、token／费用、持久化及正式Worker仍分别接线，真实配对仍暂无。
