# Word 明确单行重复表头导入

## 本轮产品闭环

既有 Word 导入 prepare/preview/apply 入口调用同一 `docx_import_parser`，现在将原件首行明确的 `w:tblHeader` 转为现有 `authoring-table-pagination/1` 声明。导入候选、节点重映射、章节内容和后续 DOCX 输出保留该声明；既有 PDF 检查要求续页具有同一来源首行，漏掉表头不能算完整覆盖。没有新 API、角色、队列或绕过来源/权限/幂等的入口，UI 使用既有候选预览、阻断项和明确应用流程。

仅支持 2 至 12 行、明确列网格、无合并格、第一行全为只含段落的表头单元格。显式 false/0/off 不产生分页声明；没有源声明也不推断。多行或非首行重复、合并、超限、重复 trPr/tblHeader、未知属性/子结构不支持，candidate 为不可应用。以前合并示例同时声明重复表头，仅警告后丢失规则；现在该组合阻断。合并单元格本身仍支持，旧合并夹具移除分页声明，另有反例验证组合拒绝。

## 版本、固定来源与兼容

沿用既有导入 envelope `authoring-docx-import/1`，其结构未变；方法身份的支持项与源文件摘要变化，旧方法 pin 不能冒充新导入。沿用已版本化富内容 schema / 表格分页协议，旧章节 schema 明确拒绝 pagination。未改冻结契约或为旧候选自动升级，源原件与候选摘要、应用时方法/来源复验等原有约束保留。

测试使用原始合成 OOXML → 实际 parser → 业务候选 planned_sections → 实际 DOCX writer/verifier → 独立两页 PDF 检查，并检查生成 DOCX 再导入仍保留声明。该链证明机制连接，不证明真实 Word03 排版转换成功。实际数据库应用事务沿用已有实现/测试，本轮不连接原生库。

## 范围核对

`AGENTS.md` 明确全新工作台不承接旧库，未找到当前已部署系统的升级需求；已安装升级迁移降为有需求才开展的运维增强。本轮没有增加迁移代码或重封存 guard。正式整包评分权威装配仍是明确产品缺口；复杂格式按实际需求选择，不能无限扩张本轮。

## 验证记录

- 初轮 focused：80 passed、3 failed。新测试把生成文档的第一个标题节点误当表格，修正为定位表格后同范围 83 passed；保留初始日志，不修改生产校验来迁就测试。
- 默认完整后端：4197 passed、0 failed/errors、2410 skipped、5 个既有依赖警告，530.60 秒。跳过不计为验收通过。
- 首次 mypy 有 1 处共享 schema 被推断为 object 的类型错误；完整回归结束后加入 typing.cast（不改变运行行为），再跑完整静态检查与全部受影响导入/重复表头/表格 PDF 测试：182 passed、14 skipped。相关跳过为原生/转换环境未具备，未规避 skip；本轮未新增原生测试。
- 最终 ruff check、format（1110 文件）、mypy（688 文件）、bandit 与 git diff --check 全部通过。
- 前端全量 187 文件、1895 passed，120.76 秒；format/lint/typecheck/build 通过，build 保留既有大 chunk 警告。
- 本阶段起点 ea60caddb20bf2be08703c51d29231354468b914，提交前远端仍为该 SHA，fusion 仍为 462ec226013b011a40c204fe1c65541c4dbfbc25；没有覆盖并行分支。
- 原生 PG/S3、真实指定 Word03 转换、Compose 默认 .env、真实成对评分数据边界沿用既有记录；未部署、付费、连接生产或新增权限。
