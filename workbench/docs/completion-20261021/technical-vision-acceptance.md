# 完整图文序列化与单次供应商端口验收

## 实现

[请求与响应契约](../../packages/contracts/package-technical-vision.md)固定官方HTTPS、单模型profile、独立判断方法和完整材料输入。每条规则实际展开全部原文、整页和裁片，PNG逐字节内嵌，图前标明文档／解析／原页／区域身份；没有远程URL、file_id、工具、检索或前次答案。三次调用使用完全相同的请求字节，分别记录实际响应，不把temperature或别名当作统计独立或不可变权重证明。

先计算包含base64和全部JSON的准确请求长度，再核最终字节；超限拒绝，不删页、不缩放。图像限制参照[DeepSeek官方Vision](https://api-docs.deepseek.com/guides/vision/)，当前384图上限比官方更严，15图起使用4096单边上限。官方仍说明推理前会缩放，`detail=original`不授细字可读性。消息结构与响应字段参照[官方Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。当前不证明token容量／费用上界，正式执行仍待独立预算与租约。

新端口显式接收密钥和预留请求／profile摘要；没有环境凭据加载、重定向或自动重发。总deadline覆盖整个HTTP交换，响应上限1MiB。保留原始响应及摘要、实际model／request ID／response ID／可选fingerprint和usage；过大／中断只留有界前缀并标记不完整。未知费用和已有usage分开；非法／截断输出不会被自动补发。原始数据在内存结果／异常属性中供后续受限持久化，未写日志或Git，repr和异常details不展示正文或凭据。

纯JSON解码／Schema／安全标识抽到共享辅助模块；原文字客户端、Generation及错误类AST相同，三辅助函数除命名外AST相同，仍拒绝图像消息。新方法冻结序列化器、供应商端口、共享codec、旧错误端口源字节、输出Schema、profile及实际依赖；旧输入和特征方法身份不变。

## 验证

- 最终固定Compose `technical-vision-pure` **272项通过、2.21秒、0跳过**：37项图文、26项原provider、51输入、50资产、54特征、42旧评分协议／恢复、12编排。主机图文与原provider共63项1.12秒通过，属于Linux子集，不相加。保留OSS UTC及PDFium两条既有依赖警告。
- 实际ReportLab／PDFium合成PDF、整页与同像素裁片进入完整输入，序列化后由实际HTTPX MockTransport接收，逐字节解码所有图片核对原资产；正文和原文目录全部相同，Content为唯一system＋user，无前次输出。三次不同响应ID、完整raw／usage可追溯；实际响应送入特征处理器，三个有效槽得到complete，伪造引文被拒绝。
- 反例覆盖错误owned输入／请求／profile／方法摘要、缺图／改图／改原文、精确body／图数／单图上限、14图与15图尺寸边界、HTTP跳转／401／403／429／5xx、连接失败、deadline、响应过大、重复JSON、非法usage／model／fingerprint、截断及Schema失败、非法密钥字符；错误无重发、不泄露标记，完整或前缀及计费状态准确。
- 六文件Ruff／format、四实现mypy／Bandit及Compose配置通过。前端未改，未重跑1786项，也无新公开HTTP或SQL契约。旧端口的共享辅助抽取由原26项和42项评分隔离覆盖。

主机最初两次在受限Windows `asyncio`的回环socketpair初始化阻塞，尚未到达HTTP。实际faulthandler栈及仅结束本任务测试进程的记录保留；在已授权本机环境重跑完成，未改系统或容器隔离。首次完整主机49过／7失败是异常子类str仅有code却按message正则断言；修正为结构化code／计费／次数后通过。新增特征反例初轮62过／1失败为捕获DomainError而实际返回纯特征异常；改为准确类型和错误码后最终通过。两轮均未放宽产品守卫，270项Linux阶段证据不当最终值。

API已重启加载共享端口，5188实际1177运行输入／68生产资源匹配，三服务健康，登录退出与只读接口通过，业务项目／写入／付费调用0。默认仍37 BASE SQL／136表，可选研究503；检查非系统库／临时LOGIN均0，checks停止。8项修改输入及原始证据核Git字节，见[收据](evidence/technical-vision/receipt.json)。内置浏览器仍缺启动模块，无本批截图／视口验收；本项不交付新的PDF或UI样式。

当前仅有可调用的显式端口与零外部请求机制验证，尚未装配原生API／Worker、独立输入权威、token与价格上界、发送账本、租约和受限资产执行，不能宣称正式三评或真实模型效果通过。下一项按这些依赖继续；真实配对暂无，后台自动接续保持关闭。
