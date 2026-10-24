# 完整图文评审任务登记

任务只消费准确原生续验及批准配置，不接正文、图片、规则子集、官方成绩或资格布尔。服务端沿原封存的准入核验追到最初已持久化程序请求，以其逻辑command作为任务intent；新续验、新报价调用nonce不能创建第二份同intent任务。独立登记LOGIN／OID是受控服务身份，原请求LOGIN／OID另存，不冒业务用户已完成正式提交或授权付费。

批准profile固定登记主体、允许的原请求主体、准确续验profile及摘要、origin、接口／SQL方法、数据库与有效期。原请求case的有效期、启用状态及修订须匹配原持久请求，不能借另一个有效新核验case绕过原授权撤销。新续验必须同原input／quote／context／scope／报告；当前续验者、核验、封存、价格和完整来源均独立核对。不能跨purpose复用包含session身份的旧布尔。

start原子保存不可变job、原intent、完整原报价与输入引用、全部纳入规则及每条三个原生槽位、初始续验证据和只含job_id／generation的准备事件。完整预算不足拒绝，不削减规则或只预付一部分。槽位UUID不是模型调用ID；准备事件尚未运输或授发送。job初始generation=1、status=awaiting_budget_reservation，资金、lease、执行、账户价格、token fit及请求体资格均false。

同command准确恢复优先；引用变化冲突。同intent的新command明确INTENT_ALREADY_REGISTERED，不创建第二份job／槽／事件。不能把重新核验或另一报价ID当新付费意图。

refresh在同一job下附加同根新续验，带准确job摘要、预期证据revision和command。旧job、输入、报价、原intent和槽位不改；新证据另存不可变事件并推进head。重放原命令返回同事件；旧revision冲突，过期／撤销／异根拒绝。当前证据不等于任务执行租约，后续Worker／账本仍须在其事务内复核。

read只读本登记主体及OID，固定job及准确当前证据分别返回；撤销或到期保留历史，当前准备资格false。仅在全新独立检查库安装，不进入BASE／业务库／公开HTTP或自动消费者。原始内容、locator、密钥及DSN不入记录或Outbox。
