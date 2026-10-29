# 材料费用预留试算

`package_material_cost.py` 只计算固定策略下的费用预留，不联网发现价格、不改变账本、不发送模型请求，也不授予输入或执行资格。报价对象独立拥有完整 `/3` context 与费用策略，不能借旧聊天预算端口加载业务环境。

`bind_policy` 接收调用方独立固定的策略摘要。策略字段闭合为 `version=package-material-cost-policy/1`、`policy_id`、`profile_digest`、`model_alias`、`currency`、`minor_per_unit`、`input_per_million_minor`、`output_per_million_minor`、`context_token_capacity`、`provider_output_token_capacity`、`source_observation_digest`、`source_observed_at`、`valid_from`、`valid_until`、`reservation_basis=full_context_capacity_no_discount`。策略只支持当前固定图文 profile，币种为 USD 或 CNY，不作隐式汇率转换。

每货币单位使用 1000000 个最小单位，单价表示每百万 token 的最小单位整数。所有数值拒绝浮点、布尔和负值；最终可序列化金额不超过 9007199254740991。输出容量须覆盖当前 profile 的 4096 输出上限，且不超过声明上下文容量。来源观察及有效期均须带时区；有效区间不超过来源观察后 24 小时，试算时点由受控调用方明确给定，不读取隐式环境或当前机器时间。

单次调用预留按完整声明上下文容量计输入，按请求输出上限计输出；即使上下文容量已经包含输出，也不扣掉输出，采用保守预留。输入与输出分别乘固定单价后合并，除以百万 token 并向上取整。每次调用先取整，再乘全部纳入条款的三个槽位及明确每槽 1—5 次的总尝试容量。重试容量不表示自动重试或保证得到三次有效结果。

试算不接受调用方条款子集；纳入条款来自完整 context，引用不完整或没有纳入条款时拒绝。预算不足仍返回完整所需预留与 `budget_sufficient_under_policy=false`，供界面解释；`require_budget` 重建验证并重新要求受控当前时点、独立固定的当前策略摘要，拒绝过期／换策略／时钟倒退及不足额度，不能缩成部分任务。历史试算仍可重建查看，但不凭旧试算时点通过当前预算闸门。重算摘要后删条款、降低金额或伪造账本／token／资格状态也会被重建验证拒绝。

试算明确 `reservation_is_not_invoice_cap=true`。`price_policy_native_verified`、`model_context_fit_proven`、`request_body_limit_verified`、`fee_ledger_reserved`、`automatic_retry`、`native_binding_verified`、`execution_authorized` 均 false。固定来源摘要只绑定策略声明，不证明供应商合同、当前账户价格、模型容量或发送时仍有效；正式发送仍需原生策略／预算锁及完整请求预检。实际费用不能被试算值截断，超出、未知计费和价格变化须在独立账本／对账流程记录。

公开来源核对仅用于设计依据：DeepSeek [价格说明](https://api-docs.deepseek.com/quick_start/pricing/)列有峰时／非峰时与缓存差异，并保留调整价格权利；[模型元数据文档](https://api-docs.deepseek.com/api/list-models/)的示例声明 1048576 上下文、393216 输出容量，示例不是本账户实时模型目录；[token 说明](https://api-docs.deepseek.com/quick_start/token_usage/)明确字符换算及图像计数为近似、实际 usage 为准。实现没有把示例、字数比例、原图像素或未接入的 tokenizer 当作输入可装入模型的证明。

范围外：原生价格注册表、实际账户策略确认、精确图文 token 预检、原生资金预留／结算／未知费用对账、发送许可、模型调用和实际账单保证。测试价格显式为合成策略，公开来源观察不是已启用生产价格。
