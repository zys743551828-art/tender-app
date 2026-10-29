# 前端10冻结交接

候选已冻结，等待独立QA／产品／用户复验，不代表整FR、真实模型效果或生产验收。前端本轮结束，固定服务保留；不得把主源码后续修改混入本候选。

- [候选清单](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/frontend-candidate.json)：SHA `d1be8aa67adfa75adaf7f904efcc626b720e5931b694adec8fca115126af3aee`，128个固定源／215个固定资产；源树 `c132a6e5a958be877e2c60a46e0429d52bde8051239ecbf6edfc2a61f427d763`，资产树 `7c997502173f27c218cfe528980f1528a98772df18762ff58e937796f7f66f5b`。
- 固定源：`/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/frozen-inputs`；固定编译资产：`/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/frozen-dist`。主源码保留相同实现，未回写候选05—09。
- [助手实际浏览器](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/assistant-mock-browser-result.json)：6组，API真实、独立显式Mock模型／分进程Worker与publisher。global发布刷新、可信@项目+PDF→知识Action一次确认、跨成员收据与全局隐私、取消请求与实际终态、project engine发布、unknown恢复禁重复付费；0真实provider／0收费。此助手执行证据来自固定task04；下面05冷绑定验证其旧消息／收据／账本保留。
- [任务05实际浏览器](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/tasks-browser-result.json)：8组原生链，四类模板保存、默认manual、登记补遗本地运行、event／cron新版本／暂停、可信章节、评分拒运行、NL未明确仍可编辑／刷新、仅存草案、单次save只一个模板、跨成员私有草案与共享模板。仅执行本地登记关系任务，没有模型任务运行。
- [8808无费持久层](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/assistant-live-result.json)：讨论保存／刷新、private global／shared project、会话状态、侧栏全屏草稿、390px、Escape。此项是正确Origin5178的开发资产overlay；没有向8808发模型命令，不当原生10部署。
- [冷启与实际资产绑定](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/cold-runtime-binding.json)：SHA `4271b46736627248f9d99a8f1f31eb7d7f2185af49439e5218ed62c82379d0f7`。128源／215资产运行前后精确核对，浏览器实际加载的主JS／CSS／TaskPanel三资产SHA匹配，后续304按缓存响应另记，不虚构body。原生5184无overlay／无HMR、正确代理8816；任务固定草案+运行、已执行Action、unknown、390px和侧栏Escape只读通过，0业务写／0pageerror。

## 固定运行方式与身份

Web `http://127.0.0.1:5184`，API `http://127.0.0.1:8816`。前端PID `2979532`／UID1000／工具会话25465，完整argv已在冷绑定记录中，不停其他端口。前端从上述固定根运行Vite preview，dist指向固定资产，node_modules复用现有依赖；锁SHA `240dcc9e8a081687a2395f7e04de78cbe7e71ae0897dd966e2743c620db17210`。不能把它当moving Vite或再向该服务写主源码。

后端为task05候选 `4f91d6aafcc397e89c19acbf626631853663a5c53e8ed95db300bc802856d650`（317源）＋固定隔离设施。actual与前端绑定的04／05文件同字节 `4af4b5d611539485be74aeed8b98f07d95fb4bc4e9c16572a781f219e5877ae2`，164路径／193操作／325schema。HTTP compact与冻结indent原始字节格式不同，但JSON对象逐字段一致；冷绑定记录并指向[后端设施最终绑定](/workspace/tender-docs/04-验证与测试/assistant-browser-environment01/fixture05/final-result.json)。没有Kafka、收费consumer或自动TaskRunner。私有测试成员文件由PM按既有600路径提供，不在此复制口令；控制当前hold，独立复验前由PM明确交接，不清账、不重seed。

自有任务项目 `d62284e0-f41c-41e8-8c95-134760df3e19`（auto_review=false），运行 `9e1e635c-f988-41c5-989a-c51401194893`，草案 `6f0b6199-3429-432b-b7b4-deca9d0be9f6`。示例固定页面：`/bids/d62284e0-f41c-41e8-8c95-134760df3e19/tasks?run=9e1e635c-f988-41c5-989a-c51401194893&task_draft=6f0b6199-3429-432b-b7b4-deca9d0be9f6`。旧模板版本／已保存草案／未知账本均保留，不改独立用户原报价或资料项目。

## 复验边界

主会话全屏／侧栏共用真实服务器身份。可信@来源只接受服务器reference/version，知识从实际trace进入，不输入UUID；旧来源不会自动改新头。对话结束／归档不取消任务；会话过期收起侧栏并保留输入。Action仅一次显式确认，文字“好的”不执行；原请求方法、body、幂等键和CAS跨刷新保留，412重新读取基准后明确继续。

费用unknown／reserved本批采取保守做法：当前主会话暂停新付费提问，仍可编辑草稿／查旧回答。两既有成员的global会话都保留合成unknown；若独立用户需要新global正向链，请设施登记独立新测试成员，不能清账或换nonce绕过。project正向主会话可用。此限制交产品判断，不把与未知意图无关的新提问能力宣称已放开。

通知与漏时记录本轮真实为空，只验诚实空态，未验正向投递或真实事件／cron运输。PM可后续对明确local succeeded run通过固定源`runs.notify`补正规通知投影，不能手写audit或tick全库；此后另绑delta证据。补遗始终只处理已登记关系，语义未知；正式评分不可执行；章节候选不自动应用，任务不替人确认规则、提交、核成绩或发布知识。

[8项质量结果](/workspace/tender-workbench/apps/web/qa-previews/assistant-task-10/final-quality-result.json)：精确契约重生、format、lint、typecheck、122测试／28文件、build、生成器ruff检查与格式全部通过。08报价两源与09知识主文件逐字保留；05—09冻结源及可用资产逐字复核。独立实走应据清单和冷绑定核摘要，勿拿早期moving截屏当最终证据。
