# 开发交接：2026-10-17

用户要求立即整理源码并提交 GitHub；已停止开发、新测试及服务启动。以下是开发自测证据，不代替独立验收。

## 当前状态与精确输入

Word 声明 PDF/保留字节增量03 **尚未最终冻结**。已保存可接手的 WIP 清单：

- `/workspace/tender-workbench/docs/word-pdf-declaration-development-checks/handoff-wip-03.json`，SHA256 `56a0c210b091ba06738e85f9916ca52aa81634275170b321b4ee3cf3b7e76578`。
- 完整 preview：`/workspace/tender-workbench/docs/word-pdf-declaration-development-checks/runtime-preview-03`，435源，9自有源；源清单 `/workspace/tender-workbench/docs/word-pdf-declaration-development-checks/source-preview-03.json`，SHA256 `6e51016cde0ea7f821d32b2f902a3c26e9078f7ba839174fcfd6a3ac47a35c24`。
- actual：`/workspace/tender-workbench/docs/word-pdf-declaration-development-checks/actual-03.openapi.json`，SHA256 `c2ac41880bfd60c183df3228d22c9c3c9881eb15226d26e818c027e850fb523f`；227路径/258操作/407Schemas。最后已完成的重新导出 `actual-final-check.json` 与其逐字相同。
- 基础应用02 candidate：`/workspace/tender-workbench/docs/application-composition-development-checks/candidate-02.json`，SHA256 `18b173dd1496994c180ef6c4bd16e8a1a05679e2020255c5a9b7e08d36479061`。原432固定根保持作为独立输入；本片最后的435全源与原432/Word335完整性总核尚未执行，不能把preview叫最终验收包。

## 本片变更与复审入口

9个自有源及逐文件SHA全部列于 WIP 清单。生产入口如下：

- `apps/api/main.py`：single初始目标、rebind、commit 对已有声明强制原Word角色/独立new_file；成功Command重放先行。
- `packages/uploads/service.py`：multipart创建在原生初始化前同样限制；原已保存ACK仍可重放。
- `packages/word_intake/declarations.py`：统一声明查询和目标/提交守卫。
- `apps/api/views.py`、`apps/api/upload_contracts.py`：UploadView新增可选nullable只读 `word_pdf_declaration`；current GET总返null或真实对象，旧不可变ACK允许缺该字段。字段为 exact source_document_version_id、固定role、required_target_kind=new_file、relation_kind=user_declared_same_draft、verification_status=unverified。前端Owner已接受此形状。
- `apps/api/retained_upload_routes.py`：新复用upload独立staging定位身份，解决同原SHA二次复用 UNIQUE 冲突；203—220行同事务冻结原version/upload、SHA、size、batch、command和verify operation。并无虚构该staging对象或对新key HEAD。
- `packages/domain/retained_uploads.py`：6—51行受限Worker解析精确不可变原blob；核同bid/command/op/upload/batch/digest/size/role/来源保留期限和非abort状态。
- `apps/worker/handlers.py`：25—40行实际 GET 原blob后核大小与SHA；publish约200—213行在engine的bid/fence/lifecycle/batch守卫内重新核对来源并比较实际读取key。不给人工确认/受控转换资格。
- 测试：`tests/test_word_pdf_declaration_bindings.py`。

所有声明保持 user_declared/unverified；独立PDF格式文件，不授controlled_render。普通非声明PDF重绑仍允许。旧成功ACK不因新守卫失效；旧未提交不合规binding须显式新文件重绑。

## 已完成验证

- `pg-07.xml`：9/9真实非owner PG+Cookie/CSRF/ASGI，显式内存对象传输、真实Worker读字节与SHA，不用真实provider/Docker。覆盖新浏览器读取、初始single/multipart/绑定/commit/旧ACK、同一原bytes两次不同新batch、不可变audit篡改拒绝、source version/expiry在I/O后变化、cancel与terminate迟到。失败路径保留明确失败收据且不登记新版本，取消无成功effect。
- `word-affected-regression-04.xml`：6/6旧Word路径，5个不相关/需Docker用例明确未选。
- `contracts-04.xml`：6/6组合契约检查；实际导出SHA一致。
- `quality-03.json`：ruff、format --check、8生产文件mypy、默认规则bandit完成通过。最初显式bandit规则列表含两个无效rule警告；随后默认规则重跑退出0，已记录。
- 当前未独立QA/架构；未执行真实原生OSS/Kafka/browser组合、生产恢复或模型效果验收。没有新SQL/grant、付费调用或consumer。

## 保留的失败与配置错误

- `baseline-02.xml` + `baseline-observation-02.json`：正确固定旧02 root执行，声明PDF重绑既有PDF链实际200，断言失败。更早 `docs/word-pdf-declaration-baseline-02.xml` 因pytest外部测试选错配置载入moving源，不能当旧02证据。
- `pg-04.xml` / `retained-probe-03.xml`：同SHA二次retained返回503 DATABASE_TRANSACTION_FAILED；结合 uploads.staging_key UNIQUE 及旧blob locator复用识别冲突。未对外输出数据库参数，不冒称捕获原始constraint异常。
- `pg-05.xml`：6过3败，三败是测试误将明确持久失败收据当作零收据；校正为错误码/result_ref断言后pg07全过。
- `pg-06.xml`：9setup错误，命令漏网络权限且同步脚本cwd错；没有产品结论。
- `contracts-03.xml`：引用不存在测试文件，未运行；contracts04正确6过。
- 第一次export使用-P未配PYTHONPATH失败；随后明确固定root重新导出成功。失败历史未覆盖。

## 复现命令（接手后按授权执行，当前未再运行）

```bash
cd /workspace/tender-workbench/docs/word-pdf-declaration-development-checks/runtime-preview-03
RUN_WORD_DECLARATION_BINDINGS=1 /workspace/tender-workbench/.venv/bin/python \
  /workspace/tender-workbench/deploy/run.py --env-file /workspace/tender-workbench/.local/app_composition02-runtime.env -- \
  /workspace/tender-workbench/.venv/bin/python -P -m pytest --assert=plain --tb=short -q tests/test_word_pdf_declaration_bindings.py
```

需当前执行环境允许PG及ASGI socketpair网络；不要打印env。旧02反例使用旧固定root，外部测试需 `-c <oldroot>/pyproject.toml --import-mode=importlib`，否则可能导入moving源。所有新的结果使用新文件名，勿覆盖现有证据。preview大量硬链依赖，编辑必须copy-on-write，format只--check，勿覆盖原候选。

## 部署主题工具：已冻结独立候选

`docs/deployment-topics-development-checks/candidate-01.json` SHA256 `344bce0730d83c5209ca870623e074f24d76b9f6d5e30fa748d650db19ad808b`。工具默认实施07九topic策略，保留旧六topic目标；支持--policy/--check-only/--expected-cluster-id。5项有意义工具测试及质量通过。仅获授权的新native Kafka19098已真实由6增3、校验全部9、consumer groups=0；未触旧19093—97、未删topic/offset。

此工具/README是独立增量，**不在Word435 preview内**；PM组合时须显式叠加该候选，不能报435全含新部署工具。

## 边界、TODO与运行环境

- 原API8806/5176、8808等未修改；新native **8818/5186尚未由本Owner部署/启动**。PM配置交接前不得从本WIP宣称运行通过。
- 先完成435源/原432及Word335输入完整性核对和最终candidate冻结，再独立QA/架构检查特别是retained audit解析/I/O后二次校验；按PM计划新隔离库/profile部署，旧DB不得热补DDL。
- 源过期/无效：失败收据保留，可从原件仍可用时显式新批次重选，否则重传；项目终止须明确reopen才允许新普通工作，不能自动复活旧失败任务。未知来源不要静默回退。
- 无新费用/消费者/真实对象网络；真实OSS迟到竞争和浏览器恢复仍待独立验证。
- 仅配置路径：`.local/app_composition02-runtime.env`（此片机制）、`.local/app_composition02-model_{train,evaluate,score}.env`（本片未用）、`.local/word-render-profile-dev06.json`（本片禁用renderer）。凭据不写文档/报告/Git；其他native新profile由PM掌握，不猜文件名。
- authoring结构/研究/前端/价格其他Owner的移动源不在本片编辑范围。主前端已收到actual c2ac…，需PM统一发布后重生联调。

所有自有WIP已保存，当前源码静止，可由PM继续无损GitHub整理。本文不声称已push；GitHub提交由主会话执行。
