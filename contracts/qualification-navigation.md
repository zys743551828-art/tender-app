# 否决与强制问题的优先入口

报告与项目清单的 `handle_disqualification` 下一步，以及登记提交前的资格风险检查，覆盖 `disqualification` 和 `response` 两类待处理问题。前端入口为 `/projects/{id}/findings?priority=qualification`，按钮为“处理否决／强制风险”。

页面等待当前报告后，按报告 `categories[].open` 选择落点：有否决问题时进入 `disqualification`；否则有强制问题时进入 `response`；两类均无待处理时进入否决分类查看记录。解析入口后使用 replace 将 URL 固定为明确的 `category`，审核或刷新统计不会自行切换分类。用户显式指定的分类及正常分类切换优先；读取报告失败时显示可重试错误，不在未知状态下请求错误分类。

这个参数只决定前端页面导航，问题查询仍使用既有 API 分类；不增加服务端枚举、修改风险级别或改变提交拦截规则。
