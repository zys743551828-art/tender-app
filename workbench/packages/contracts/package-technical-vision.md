# 完整图文请求与单次响应端口

序列化器只消费owned冻结的`package-technical-input/2`、明确规则ID及独立预期输入／序列化方法摘要。供应商profile和判断方法必须与冻结绑定相符。逐字展开全部材料、整页及裁片，顺序为冻结整页后裁片，每张图有明确文档、解析、页号、来源矩形与资产标识。图像仅使用经字节核验的inline PNG，没有远程URL、file_id、工具、检索、聊天或前次输出。三次调用使用相同请求字节，槽位／attempt／nonce留在外部账本，不能往模型输入添加前次答案。

当前profile固定DeepSeek官方HTTPS、`deepseek-flash`、非流式、thinking关闭、temperature 0、输出4096 tokens；模型别名不冒不可变权重。上限48MiB实际JSON请求、单图32MiB、图像总64MiB，最多384图，单边8192像素；包含15图及以上时单边4096。超限明确拒绝，不缩放、不删页、不只传摘要。base64展开前先计算精确请求长度，再核最终发送字节和摘要。当前协议及限制依据见[官方Vision](https://api-docs.deepseek.com/guides/vision/)与[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。供应商推理前仍会缩放图像，`detail=original`不能证明细字或工程图可读。

响应端口需要显式凭据及预留请求／profile摘要，目标地址固定，不从环境加载密钥或代理，不自动重发、跟随跳转或修复输出。可注入显式MockTransport；不注入时使用真实HTTPS端口，当前未装配到API／Worker或启动任何真实调用。独立native权限、发送意图、预算／租约和当前来源复核必须在安装执行路径时另行保证，不能将本端口当作授权器。

总deadline覆盖连接、上传及慢响应，响应上限1MiB。保留实际原响应字节与摘要、request ID、response ID、实际model、system fingerprint（有则记录）及usage；raw数据和凭据不进入repr、异常details或日志。JSON拒绝重复键、非有限数及不合封闭输出Schema的内容。当前模型必须与profile明确预期值相同；别名映射变化需新profile，不能悄悄接纳其他身份。

非200、网络超时、非法响应身份或usage保留unknown计费状态；完整合法usage但输出截断／Schema非法，保留usage_reported及原响应。过大／中断只保留有界响应前缀并标记不完整，不能把前缀当完整回执。每次外部尝试只发送一次，不因无效判断或未知费用自动补发。模型输出valid只是原始声明，后续引文语义、三个有效槽位和费用持久化仍由独立publisher验证。

输入实际必要范围与原字节权限、独立可读性、token容量／费用上界、原生持久化、硬隔离与正式执行仍未验收。请求回执的完整序列化只指冻结投影实际进入字节；model token容量、视觉可读性与执行资格均false。独立JSON辅助模块只承接既有纯解码／Schema／标识核验，原纯文字客户端仍拒绝图像消息；本端口不改旧scope、报告、/1机制或历史资格。

独立图文端口及JSON协议只从纯错误模块导入`DomainError`／`ProviderError`，导入链不进入业务runtime或旧文字客户端，不读取业务`.env`。旧导出路径保留同一个类对象，实际API异常处理器继续识别这些异常，原响应字节不进入公开错误。新判断方法同时绑定两个纯错误源码摘要，序列化方法随依赖绑定新身份；原输入、资产、特征方法及旧回执保持原值。
