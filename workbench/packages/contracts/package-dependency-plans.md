# 整包人工依赖计划

机器协议为 [package-dependency-plan.schema.json](schemas/package-dependency-plan.schema.json)，持久化为 [bid-package-dependency-plans.sql](sql/bid-package-dependency-plans.sql)。内部保存与读取用例分别为 `bid_package_dependency_plans.save`／`read`；公开 HTTP、历史发现与显式界面另行接入。只读 `dependency-check` 继续不保存。

调用方明确给出准确 prepared 摘要、用途、实际消费事实 ID、逐条依赖、刚核对的 assessment 摘要和保存理由。服务端在项目锁下读取准确冻结输入及 prepared，重新构造私有 usage 并核对当前依赖政策产生的评估；与刚确认的摘要不同返回409，不静默存另一份计划。字段错误422、缺少幂等键428、同键不同请求409；失败回滚命令、计划、审计及事件。当前项目结束／归档拒绝新保存。

每次明确保存追加独立计划 ID，不设置活动 head、不自动覆盖另一份计划，也不宣称解决多人草稿合并。201 ACK 绑定完整请求摘要、操作者、命令、准确 prepared、原 assessment、原 usage、理由和记录时间。数据库延迟约束在提交时核对同一命令的201回执及唯一准确审计；API仅 SELECT／INSERT、Worker仅 SELECT，UPDATE／DELETE被撤销并有追加保护。历史读取核对原命令、唯一审计、整份记录 SHA、原冻结／prepared 与 usage 投影；更改或重复审计不得当作可信历史。

历史保留原评估和政策 SHA，**不调用当前依赖评估器重新生成**。读历史不读取当前事实头／来源状态、不做对象 IO、不授新执行资格；项目归档或政策改变后仍可读取原计划、按同键恢复原ACK。用另一键保存须重新核对当前政策摘要。协议内嵌固定 `/1` 的依赖与 usage 定义；后续协议变化须保留原读取语义，不将历史记录按当前算法重封装。

计划仅复制实际选用事实 ID 和条目摘要，不复制未用公司事实池或私有事实值。Worker后续必须从绑定的原 prepared 按该选择读取投影，再独立核对当前事实资格、原件、生命周期、预算、租约和发布条件。人工依赖声明完整、要求清单完整、事实真实性、原件字节验证和正式执行资格分别判断；允许保存有 unknown／missing 的计划，全部整体资格仍 false。没有创建任务、阶段或 Outbox，没有模型／外部调用。

职责：纯领域负责新计划绑定与历史完整性；用例负责显式意图、项目锁、事务和幂等；仓储负责追加和原 ACK／审计交叉核；SQL负责行绑定、回执、追加及权限。历史完整性检查依赖可信保存回执，不能把任意重封装的客户端 JSON 当成服务端历史。
