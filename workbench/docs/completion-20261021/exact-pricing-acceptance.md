# 精确整包报价来源与方案：验收记录

日期：2026-10-21。范围为 F10-01 的整包条款来源接线，以及 F10-02 的固定公式、情景、保存与失效恢复。保留既有两种 Decimal 公式，不扩大支持的计分规则，不据本记录关闭 F10 全部任务。

## 本次实际接通

用户分别选择本方投标包和招标补遗包的确切修订，随后读取这一选择的报价依据、核对完整原页条款、登记固定公式、试算并显式保存方案。四个必填身份为 `package_id`、`revision_id`、`authority_package_id`、`authority_revision_id`；没有“使用最新解析”的替代分支。包目录仍仅提供当前修订，旧方案可通过“独立报价与全部历史”回看。

新增三个 API：

| 操作     | 实际路径                                                    | 行为                                                                         |
| -------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 读取依据 | `GET /api/v1/bids/{bid_id}/package-pricing-context`         | 四个包身份为必填查询参数；返回固定绑定、来源摘要及强 ETag                    |
| 选择条款 | `GET /api/v1/bids/{bid_id}/package-pricing-formula-sources` | 仅列出明确选择的权威包冻结解析，保留分页、原页和完整证据块                   |
| 登记公式 | `POST /api/v1/bids/{bid_id}/package-pricing-formulas`       | 必须携带 `package_binding`、原 ETag 与幂等键；复用原授权、暂存与最终发布链路 |

原试算、保存、详情和历史列表 API 继续使用。整包公式为 `pricing-formula/2`，旧独立公式保持 `pricing-formula/1`。旧登记请求仍拒绝附加整包身份，新登记请求拒绝省略身份。现有不可变公式对象、来源图、`pricing_simulations`、`pricing_plans` 和命令回执承载这条路径；**未新增表、SQL 迁移或另一套方案头**。

实现文件：`packages/pricing/package_models.py`、`package_sources.py`、`repository.py`、`contracts.py`；`apps/api/package_pricing_routes.py`；前端 `PackagePricingScope.tsx`、`packagePricing.ts`、`PricingPanel.tsx`、`PricingFormulaEditor.tsx`。主应用 router、实际 OpenAPI 和生成的 TypeScript 契约已由主代理挂接。

## 来源、数值与过期条件

两份包必须属于同一已确认的工程、标段、轮次和投标主体，并且仍为该包当前头。当前身份摘要须等于包保存时的摘要。权威包必须具备完整冻结解析和全部物理页的声明范围；所选成员的精确解析、页和完整证据摘要再次核对。

包内原件、所选冻结解析及其祖先需要已登记的规范来源节点和血缘，必须处于本项目、事前内容用途、已发布且当前生效的范围。条款只允许取所选权威包中角色为招标文件或补遗的文档，引用必须是对应冻结解析、对应物理页的完整证据块。不能用衍生特征代替条款原件。新建但尚未选择的解析不会把原公式的出处换成“最新解析”。

公式同时冻结两包摘要、身份摘要、当前来源头摘要、当前规则集 ID，以及存在时的整包要求清单 ID／摘要。登记在对象暂存后重新检查上述条件；试算、方案保存和写操作重放也检查当前适用性。包头、规则集、要求清单或来源效力变化使旧公式只能供历史查看，原始公式、输入和已算出的数值不会回写。报价读写统一按 bid → graph 顺序取得锁，避免历史列表与写入形成反向锁等待。

计分仍采用 `lowest_valid_ratio`、`mean_valid_deviation` 两种受限 Decimal 方法。币种、金额单位、最终两位取整、最低／最高边界、有效报价数量、上下方向系数和完整解释仍需按原文确认。不执行隐式货币或元／万元换算；缺少必需参数、税价／单位歧义、随机系数、去极值、分段和中间取整等不支持条件继续拒绝。无效候选和无法确定的分数为 `null`，不补成零；真实零分与未知保持不同。

## 前端恢复行为

新服务器开放整包接口时，报价页提供明确的双包选择；旧接口模式仍可使用。公式、草稿、选中项和待恢复请求按成员、项目及四个包身份隔离，身份对象的属性顺序不会改变恢复键。目录缺少包名称时，界面显示包种类、修订号和短 ID，不生成不存在的名称。

切换报价模式或重新选包不会把原范围的迟到回包显示到新范围；返回原范围可以继续原草稿，并使用原 body／If-Match／幂等键恢复不确定请求。旧修订和旧独立公式在全部历史入口仍可查看。情景试算保留已有输入摘要、固定公式摘要与迟到响应守卫，试算不自动保存方案。

本轮同时修复通用 `useRecordedCommand` 的一个缺陷：原实现会在调用者核验 ACK 身份之前清除恢复记录。现在提供可选 `validateResponse`，先完成核验再清除记录。核验抛错，包括抛出客户端 `ApiError`，都保留原请求；API 已明确拒绝的旧处理语义保持。调用者未卸载但 scope 改变、网络返回较迟，以及异步核验期间切换 scope，均不会清除旧范围或覆盖新范围状态。其他调用者不提供验证函数时保持原调用协议。

## 已观察到的验证

### 真实隔离 PostgreSQL 与实际 API

执行 `tests/test_package_pricing_pg.py`，原生 PostgreSQL 17.11、全新临时集群、随机本地端口、真实独立非 owner API／Worker LOGIN。业务通过实际 FastAPI 应用和认证／CSRF／版本条件处理，使用 ASGI TestClient；没有把 HTTP socket 部署列入此证据。

测试原文和文档记录为明确合成输入，公式对象存储为内存适配器。数据库、事务、权限、约束、幂等、当前头核验与并发锁均为真实 PostgreSQL 行为。没有连接旧业务库，没有调用模型、OCR 或付费服务。集群在运行结束后停止，临时 owner 口令不进入输出或仓库。

最终运行结果：**9 passed，31.80 秒，退出码 0**。九项均在同一全新隔离环境重新执行，包含最后补入的规则版本变化和并发锁序用例。此次临时回执为 `/tmp/tender-review-pricing/pricing-pg-b_yu4i4s/test-receipt.json`，它是 harness 运行摘要，不是完整原始 stdout；本记录的通过数和耗时来自实际工具输出。

九项用例覆盖：

1. 不依赖旧 `current_material_id`，完成明确上下文 → 精确出处 → 固定公式 → `25.00` 试算 → 保存及历史绑定。
2. 投标包头变化后拒绝迟到试算和保存，旧模拟值仍为 `25.00`，适用性变为 false。
3. 规则集由明确版本切到另一版本后，旧公式／结果不重写，新试算拒绝。
4. 并发读取公式等待 bid 锁时没有先占 graph 锁，随后真实 API 读取成功。
5. 祖先撤回后，新保存和同 key 保存重放均拒绝；此前保存方案的原值继续可读。
6. 引用未选择的解析，或把本方包当权威包，均在公式对象写入前拒绝。
7. 公式对象暂存期间包头变化，最终发布拒绝，目录不出现半个公式。
8. 同一文档新建未选择解析后，出处仍为原冻结解析，原公式仍可适用。
9. 无效候选 `0` 的分数为 null；缺少必要参数的登记请求被拒绝。

最初一次隔离运行曾因测试夹具试图 UPDATE 不可变文档类型而在 setup 失败；夹具已改为追加正确类型的合成原件、解析、页和证据。失败轮次没有计入通过数，没有放宽生产不可变约束来让夹具通过。

### 定向回归与静态检查

| 范围                                                                                            | 已观察结果                                               | 证据边界                                                                                                                             |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `test_pricing_contracts.py`、`test_pricing_calculator.py`、`test_pricing_method_evidence.py`    | **38 passed，0.84 秒**                                   | 两种公式手算、均值／舍入边界、未知值、原文单位规则以及新增严格接口契约；不代表真实报价条款语义覆盖                                   |
| `useRecordedCommand.test.tsx`、`PackagePricingScope.test.tsx`、原报价面板／编辑器与实交面板回归 | **21 passed，4.38 秒**，5 个文件                         | React/jsdom、合成 fetch；覆盖坏 ACK 保留恢复键、原请求恢复、跨范围迟到、实际面板切模式／重选同包保稿、原报价和旧实交协议             |
| Ruff check／format                                                                              | 通过                                                     | 本轮 pricing Python 实现和测试                                                                                                       |
| Mypy                                                                                            | **5 个实现文件无错误**                                   | 新包模型、来源、repository、contracts、API                                                                                           |
| Bandit                                                                                          | 通过，退出码 0                                           | 同上 5 个 Python 实现文件                                                                                                            |
| 定向 ESLint                                                                                     | 通过，退出码 0                                           | 包报价、编辑器、通用恢复 hook 与新增测试                                                                                             |
| 项目 TypeScript typecheck                                                                       | 中间轮通过；最终复跑因并发新文件报错，未计作最终全树通过 | 本轮 pricing／hook 文件无报错；并发新增 `packageTechnicalEligibilityProtocol.ts` 存在 unknown 类型收窄及隐式 any，已交给该文件负责方 |
| `git diff --check`                                                                              | 通过                                                     | 检查时的共享工作树                                                                                                                   |

根集成补充：检查点 10 的隔离最终候选已修正并发技术范围类型错误，完整 130 个前端文件／1,200 项、全项目 TypeScript 与生产构建全部通过；详见 `technical-pricing-retrieval-theme-regression-receipt.json`。上表保留各定向执行当时的实际状态。

Python 结果仅出现既有 Starlette／AnyIO 弃用提示。最终共享树的前端完整测试、构建、统一集成及发布检查由主代理汇总，本记录不把未执行检查列为通过。

## 可复跑入口

工作目录为 `workbench/`。PG 用例需要独立可销毁环境的 `FUSION_REQUIREMENTS_ADMIN_DSN`，未配置时明确跳过；禁止把此变量指向业务数据库。测试会使用并清理独立 fixture 数据库和临时业务角色。此次本地 harness 位于 `/tmp/tender-review-pricing/run_pg.py`，复用了已构建的 PostgreSQL 17 前缀，但创建独立集群，不操作此前实例。

```bash
python -m pytest -q tests/test_package_pricing_pg.py
python -m pytest -q tests/test_pricing_contracts.py \
  tests/test_pricing_calculator.py tests/test_pricing_method_evidence.py
python -m ruff check packages/pricing/package_models.py \
  packages/pricing/package_sources.py packages/pricing/repository.py \
  packages/pricing/contracts.py apps/api/package_pricing_routes.py \
  tests/test_pricing_contracts.py tests/test_package_pricing_pg.py
```

前端工作目录为 `workbench/apps/web/`：

```bash
npx vitest run src/useRecordedCommand.test.tsx src/PackagePricingScope.test.tsx \
  src/PricingPanel.test.tsx src/PricingFormulaEditor.test.tsx \
  src/SubmissionPanel.test.tsx
npm run typecheck
```

## 尚未验收和明确边界

- 没有真实工程招标／补遗及人工标注条款的语义质量验收；参数核对依靠有据的受限规则和人工确认，不宣称通用自动公式抽取。
- 本方投标包参与身份与当前来源绑定，不由本次报价入口授予完整评审、合格投标、技术评分或提交资格。公式中的有效报价集合为声明的数值情景假设，不能视为官方资格结果。
- 本次没有读取或重验真实原件字节，没有真实 S3、浏览器至运行服务器、模型运输或生产容量验收。完整权威解析核验是数据库保存身份与证据摘要的核验，不能冒充真实原稿质量。
- 来源祖先仍须满足本项目事前内容权限；跨项目衍生材料等尚未取得此报价入口资格时会保守拒绝，不能为通过演示放宽用途或祖先校验。
- F10-03 的整包正式结果登记另见原实交／成绩验收。报价模拟不推算中标概率，不自动推出技术分换算、不接公司内部成本模块。F10-04 指标分母／可比趋势、F10-05 复盘流转未由本次交付完成。
