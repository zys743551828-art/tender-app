# 完整材料费用预留试算验收

纯费用试算按独立固定的策略、完整 context 中全部纳入条款、三个槽位及明确尝试容量计算预留；不接受任意条款子集、不发送模型请求、不写账本。每次调用向上取整后再乘总调用容量，拒绝布尔、浮点、负值、币种混用与安全整数溢出。

职责与字段见[费用契约](../../packages/contracts/package-material-cost.md)。预算不足仍显示完整所需金额，预算闸门拒绝启动部分任务。历史试算可以复算，但闸门必须另给当前受控时点及当前固定策略摘要，拒绝过期、更换策略或时钟倒退。

最终 **92 项 Linux 12.98 秒**通过：1 项原生费用链、57 项费用／时效反例、22 项端口隔离、12 项 Compose。**79 项 Windows 9.34 秒**为纯计算与隔离，套件重叠不相加；五文件格式／lint、一实现 Linux 目标 mypy／bandit 通过。54 项首轮与89项中间整链不累计。

原生合成材料经两次完整回环 GET 后按全部纳入条款试算，三个槽位及每槽两次尝试容量全部计入；纯夹具覆盖最多五次尝试容量、预算差一个最小单位、逐调用取整、无纳入条款、策略窗口、类型、金额溢出、伪造廉价试算与伪造账本／token／执行状态。没有自动重试或保证得到三个有效结果。

DeepSeek 官方[价格](https://api-docs.deepseek.com/quick_start/pricing/)、[模型元数据文档](https://api-docs.deepseek.com/api/list-models/)、[Vision](https://api-docs.deepseek.com/guides/vision/)与[token 说明](https://api-docs.deepseek.com/quick_start/token_usage/)已只读核对，提取事实及其准确限制见[来源观察](evidence/material-cost/official-source-observation.json)。该观察不保存整页正文、不等于供应商签名／合同或本账户实时目录，不自动启用生产价格。测试策略显式合成，数值示例不构成实际费用承诺。

预留按策略声明的完整上下文容量与请求输出上限保守计算，不扣缓存／时段优惠；不把字数、图像数量、原始像素或未接入 tokenizer 估算当作图文输入能装入模型的证明。`price_policy_native_verified`、`model_context_fit_proven`、`request_body_limit_verified`、`fee_ledger_reserved`、`native_binding_verified`、`execution_authorized` 均 false，`reservation_is_not_invoice_cap=true`。实际费用不能按试算截断，未知计费仍需独立账本与对账处理。

[源码及原始验收回执](evidence/material-cost/receipt.json)固定 12 份证据和七个修改输入原始 Git 字节。所有既有来源／材料／归档／恢复／登记／范围清单及 `/2`、`/3`、请求／特征方法不变，没有新 SQL／权限、HTTP 或前端改动。

本机 5188 为 1221 份运行输入／68 份实际资源，登录退出与端点边界通过，API／Web／PG 健康。正常库登记 schema／核验角色 0、design 136／BASE 37 保持；独立所有 `fusion_%` 库／LOGIN 和四类核验组 0，检查／渲染停止，正常 Word 保留。业务写入、费用账本预留、真实模型及付费调用均 0，开发源挂载不是不可变发布。

继续审核决定／主体与证据绑定、正向输入登记及当前价格注册表，再接原生资金预留、发送 CAS／lease、结算与未知费用对账及正式 Worker。核验方式选项已询问；该选择不阻塞本纯费用模块。真实评分配对暂无、精确图文 token 预检、生产根目录、Windows ACL 和浏览器视觉缺口保持。
