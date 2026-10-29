# 下一片生命周期整合交接（待实施）

06人工决定P1已独立冻结，本文件只交接下一片，不修改06或暴露生命周期router。

依赖：PM lifecycle-intent02候选867708e6756280691661671477a7f2491febaa9033da7484fe0e5564129608b3；已审batch closure扩展仅在新delivery_protocols01机制库配置。归档业务口径见tender-docs/04-验证与测试/a1-delivery-plan/execution-backlog/归档写入意图边界.md。

## 接线矩阵

| 入口 | 计划守卫及例外 |
| --- | --- |
| 创建上传批次、上传授权/刷新、complete、binding、commit、single/multipart代理写入 | 同bid锁后核assert_work_writable；取得batch后核assert_batch_open及原state。网络I/O前短资格检查，网络后发布再次同bid锁核对；迟到对象隔离留收据，不进入work。旧ACK可重放，不产生新副作用。|
| 资料配置/设置、规则/事实/风险决定、规则补漏/效力更正、普通评审请求、比较、报告新生成 | 所有新业务写入同bid锁和普通work守卫；幂等旧ACK只还原原结果。读取历史和已有产物不受work写入守卫阻断。是否允许结束后新增历史报告需Owner明确，未明确时保守拒新生成。|
| 普通Worker acquire/finish、解析发布、build采用、准备/冻结控制面、事件自动触发 | 受限Worker锁或API bid锁后同一资格判断；不能因此前202/旧ticket/fence有效而绕过已结束状态。失败/取消收尾与使用量保留需能终结，拒业务publish不能使operation永久在途。|
| draft/save/patch/build、knowledge当前引用、pricing与后续assistant/tasks | 独立Owner源不并发覆盖；按各模块精确API/Worker发布点加入同bid锁守卫，或在共享可信入口集中，但不能仅靠UI/Command名称猜测。全局企业知识与全局会话不虚构bid归档范围。|
| 取消operation/upload、显式close batch、lifecycle reopen | 保留恢复/终结动作，不被普通work关闭守卫卡死；仍鉴权、幂等、CAS、审计。闭批次只保留暂存，不删除字节、不自动commit；重开不复活旧闭批次。|
| 专用线下实交补录/事实更正、官方结果/来源档案补录 | 单独明确例外，留不可变证据与审计，保持closed/terminated/archived_at，不能改为submitted或暗重开。普通旧上传完成入口不能冒充档案补录。|

尚需最小可实现闭合：闭批次保留的verified字节，重开后明确选择新batch/binding；旧batch不能直接复活。API锁序统一bid→Command/领域行→来源图/heads；先重放旧ACK后守卫新work，但不能先持Command锁再等待bid而与其它路径反序。须逐入口核查，不能仅修改共享Command而误拦补录/恢复。

## 必测

无active operation但存在authorized/verified upload及open/partial批次仍阻断归档；close保留真实暂存、重放无重复；archive与complete/commit/Worker publish真实并发只有合法一侧产生work；旧单片/分片ticket迟到、build/prepare迟到不能移动头；在途失败/取消仍可收尾；专用补录保持阶段；归档历史读取/产物取件保持可用。旧schema明确未配置或保守阻断，不热补权限/SQL。

## 其它独立后续片

comparison独立无费用topic/consumer，绝不启动通用收费review消费者或同组吞其它消息。assistant项目/生成和task guard/hook按Owner候选另接，当前06没有注册这些移动模块。
