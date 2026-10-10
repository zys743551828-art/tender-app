# 投标工作台后端

FastAPI 模块化单体 + PostgreSQL 16 + S3 兼容对象存储（阿里云 OSS）+ Kafka。同一镜像按入口分为 API、发件箱中继、回收器和四类 worker（`parse` / `ai` / `experiment` / `export`）。设计依据见《系统架构与数据契约》。

## 结构

| 目录 | 内容 |
| --- | --- |
| `src/bidwb/api/` | 路由与请求级依赖（会话、CSRF、幂等键、If-Match） |
| `src/bidwb/services/` | 领域用例：认证、项目、上传、快照、证据检索、规则、问题复核、改稿建议、提交与结果；自动评审流水线（`pipeline`）、响应矩阵（`compliance`）、评分预测读取与在线对照（`predictions`）、打分模型（`scoring_models`）与锚点包（`anchor_packs`）、研究产出的登记与路由（`model_registry`）、评分配对导出（`score_pairs`）、报价方案（`price`）、评审报告（`report`）、导出（`export`）、中标导向度量（`metrics`） |
| `src/bidwb/tasks.py` | 任务协议：入队与发件箱、租约领取/续租/提交、回收、取消与重试 |
| `src/bidwb/workers/` | worker 运行器（任务结束后推进流水线）与解析处理器；回收器循环兜底推进 |
| `src/bidwb/ai/` | 模型适配器、提示词、证据落地校验；规则提取、核对、评分预测（`predict`：正文章节 `sections`、特征 `features`、比较式锚定 `anchors`）、改稿处理器 |
| `src/bidwb/checks/` | 不调用模型的确定性检测：正文数值前后矛盾与大段重复、超范围残留 |
| `src/bidwb/pricing.py` | 报价模拟（评标基准价与价格分），纯函数 |
| `migrations/` | Alembic；只有一个迁移，内容即 `contracts/schema.sql`，二者逐字一致（测试守护） |
| `tools/export_contracts.py` | 由代码生成 `contracts/openapi.json`，并写入 `contracts/domain.schema.json` 中由代码定义的部分；`--check` 只比对（测试调用） |
| `tools/batch/` | 系统批量预测 `predict_dataset`：评分配对集（格式 A）逐份跑产品流水线，输出格式 B（见“系统批量预测”）；锚点包构建 `build_anchor_pack` |

## 运行与测试

```bash
pip install -e '.[dev]'
export BIDWB_MIGRATION_DATABASE_URL=postgresql+psycopg://…   # 库属主角色
alembic upgrade head
pytest                      # 需要可连接的 PostgreSQL；没有时集成测试自动跳过
ruff check . && ruff format --check . && mypy src && bandit -r src -ll
python tools/export_contracts.py   # 接口或数据结构变化后重新生成契约文件
```

测试在真实 PostgreSQL 上跑，worker 相关用例使用只有 `app_worker` 权限的角色，所以授权遗漏会直接暴露。`BIDWB_AUTO_ANALYSIS=false` 关闭“资料入库后自动评审”（模型服务故障或需要控制成本时使用），此时各步骤只由人工触发；集成测试默认关闭它以便逐步断言，`tests/test_auto_pipeline.py` 打开它验证完整链路。

## 联调冒烟

`tools/smoke/` 是开发辅助：`smoke_server.py` 起真实 PostgreSQL + API + 进程内 worker（脚本化模型、内存对象存储），`e2e.py` 用浏览器走完“登录 → 查看报告 → 处理废标风险 → 报价”。它不依赖 Kafka、OSS、真实模型，也不覆盖上传（上传走预签名直传）。

## 系统批量预测

`tools/batch/predict_dataset.py` 是评分预测准备流程的第二步（开发辅助，不属于产品代码）：读入评分配对集（交接格式 A，`score-pairs/1`），对每份样本用产品本身的流水线跑一遍“解析 → 提取规则 → 冻结输入 → 逐条核对与确定性检测 → 评分预测”，每份样本写一个 `<out>/<sample_id>.json`（交接格式 B，`system-prediction/1`）。

```bash
export BIDWB_LLM_BASE_URL=… BIDWB_LLM_MODEL=… BIDWB_LLM_API_KEY=…
export BIDWB_BATCH_ADMIN_DSN=postgresql+psycopg://postgres@localhost:5432/postgres   # 有建库权限
python -m tools.batch.predict_dataset 评分配对集.json --out results/system-pred --cache-dir .llm-cache --estimate-only \
    --price-per-mtok-in 2 --price-per-mtok-out 8                          # 先粗估调用量与费用，不调用模型
python -m tools.batch.predict_dataset 评分配对集.json --out results/system-pred --cache-dir .llm-cache --limit 10   # 试点
python -m tools.batch.predict_dataset 评分配对集.json --out results/system-pred --cache-dir .llm-cache               # 全量（可随时中断重跑）
```

* **运行环境**：每次运行新建一个独立的 PostgreSQL 库并跑 Alembic 迁移，worker 以只有 `app_worker` 权限的角色登录；API、发件箱中继、回收器与 worker 都在进程内（内存对象存储、内存总线）。资料经真实上传接口入库（分片会话 → 写分片 → 完成并由服务端复算校验值），状态经 `GET /projects/{id}/pipeline` 轮询，结果读自规则、报告、预测接口与预测明细产物。结束时删除临时库（`--keep-db` 保留）。
* **只上传招标文件、补遗（按发布顺序）与正文**；格式 A 里不含成绩来源文件，工具也从不读取它；项目不设截止时间。默认不跑 `exclusion` 为 `duplicate_body`、`missing_files` 的样本（`--include-excluded` 时也跑）；没有标签的样本照常跑。
* **并发与内存**：`--concurrency N`（默认 2）为同时在途的样本数，ai worker 开 N 个线程；解析只开一个线程，因为 pdfium 不是线程安全的。上传经一把锁串行（内存对象存储的分片会话不是线程安全的）。每份样本结束（成功、失败或超时）立即从内存对象存储删除该项目的全部对象：按库结构找出带 `project_id` 的表里所有 `*artifact_id` 列引用的产物，资料原件按内容寻址，仍被其他在途样本使用时保留。
* **模型缓存**（`--cache-dir`）：键为 sha256(model, system, user, max_tokens)，命中直接返回、用量记为 0。提示词里的证据、规则等标识每个项目随机生成，计算键之前按出现顺序换成占位符，命中时换回本次的标识；因此同一招标文件被多家样本复用时规则提取只付一次费，中断后重跑也不重复付费。
* **续跑**：已有结果文件且输入指纹（招标与正文 SHA、模型、提示词版本、`src/bidwb` 与本工具代码的摘要）一致、状态为成功的样本跳过；失败的默认重跑（`--skip-failed` 一并跳过）。`--only`、`--limit` 选择样本。
* **失败隔离**：每份样本有总超时（`--sample-timeout`，分钟，默认 30；超时会取消该项目仍在进行的任务）；缺文件、校验值不符、解析失败、任一环节失败都写 `status=failed` 与原因，不中断全批。
* **格式 B 的 `items`** 原样透传预测明细产物里每条的全部键（数值转十进制字符串），再补齐 `statement`、`max_points`、`estimate`、`low`、`high`、`evidence_count`、`rule_basis`、`failed`；产物除 `items`、`usage` 之外的顶层键放在 `artifact_extra`。`usage` 是该样本实际付费的调用量与缓存命中次数。
* **粗估口径**（`--estimate-only`，误差可达 ±50%）：招标资料按产品同样的解析切成证据块；规则提取每 20 块一次调用，同一组招标文件只计一次；规则条数取含要求性措辞或“N分”写法的招标块数（上限 200），每条规则一次核对调用；评分条款数 S 取同时含分值写法与评分措辞的招标块数（上限 40），预测为 1 次章节对应调用加 S × 重复次数次逐项判断（每次带对应章节，按正文平均章节篇幅估算，上限 14000 字）；给出 `--anchor-pack` 时另计 min(S, 6) × 锚点数次比较。输入 token 按字符数 × 0.7 计；调用次数与 token 再乘 1.1 计入结构修复重发。

锚定（`--anchor-pack 锚点包.json`）：直接使用给出的锚点包，与本样本同一项目（`project_key`）或同一模板组的锚点一律不用，防止样本自己的成绩经锚点泄漏进特征。格式 B 另带 `run_id`、`repeat_index`（`--repeat-index N` 做稳定性复跑，进入指纹与缓存键）与失败类型 `failure_kind`（`infrastructure`／`model`／`input`）。

## 打分模型、锚点包与数据回流

评分预测的第三、四层依赖研究侧用官方成绩产出的两样东西，登记后按环境路由生效（库表 `dataset_snapshots → experiments → model_bundles → validations → releases → release_routes` 记下完整追溯链，路由切换写审计）：

```bash
# 打分模型：tender-research 的 score_eval 输出 calibration_bundle.json 与 report.json；业务环境只接受评估结论为“通过”的模型
bidwb-admin register-scoring-model calibration_bundle.json --report report.json --reviewer <登录名> --environment business
bidwb-admin register-scoring-model calibration_bundle.json --report report.json --reviewer <登录名> --environment shadow   # 影子：只计算不展示
bidwb-admin list-scoring-models
bidwb-admin unroute-scoring-model --environment business --reviewer <登录名>     # 撤下，界面回到未校准

# 锚点包：由评分配对集里有官方分的样本构建（正文按与产品相同的方式切章节）
python -m tools.batch.build_anchor_pack --pairs 评分配对集.json --out 锚点包.json
bidwb-admin register-anchor-pack 锚点包.json --reviewer <登录名> --environment business

# 数据回流：产品里登记了技术分的提交导出为格式 A／B，与历史数据合并后重新训练
bidwb-admin export-score-pairs --out 回流导出/
```

再次登记同一模型（`model_id` 相同）不做改动；登记新模型时新发布指向上一次发布，便于回退（重新登记旧模型即回到旧模型）。打分模型的适用范围（工程类型、训练数据出现过的地区）写在模型里，项目不在范围内时界面如实标为“超出校准范围”。

## 自动评审流水线

资料齐了（至少一份招标文件＋一份技术标正文）就依次执行：解析 → 提取规则 → 冻结输入 → 逐条核对规则（响应矩阵）＋确定性检测 → 评分预测。`pipeline.advance` 是幂等的状态推进：每次只做“下一步”（入队一个任务或冻结一次输入），入队与冻结都带确定的幂等键，并发调用在项目行锁上串行。触发点有三处：上传完成、任一任务结束（worker 运行器在结果提交之后单独开事务推进，推进失败不影响已提交的结果）、回收器定期兜底（只处理仍在“分析中”的项目）。

* 资料更新（新版本招标文件、补遗或正文）自动开新一轮；规则或事实的更正不自动开新一轮——`GET /projects/{id}/pipeline` 的 `stale_reasons` 如实提示，由人调用 `POST /projects/{id}/analysis` 决定何时重新评审（项目关闭 `auto_start` 时，资料更新同样等人开始）。同一接口也用于失败环节的重试：失败的环节用新的幂等键重新入队，已完成的环节不重做。
* 项目状态由流水线与问题对账共同维护：`materials_pending` →（手动开始时 `ready_to_analyze` →）`analyzing` → `issues_open` ⇄ `ready_to_submit`；某环节失败为 `analysis_failed`。

## 项目级功能开关

用户只用自己需要的部分。`projects.settings_json`（`schemas.ProjectSettings`，缺省的键取默认值）通过 `PATCH /projects/{id}` 的 `settings` 整体替换，改动写审计 `project.update`。默认全部开启，只有“规则按原文接受”默认关闭；废标／否决检测、响应矩阵与证据溯源没有开关。

| 键 | 作用 |
| --- | --- |
| `auto_start` | 关闭后资料照常解析（不调用模型），新一轮评审等人调用 `POST /projects/{id}/analysis`（记录 `analysis_requested_at`，晚于最近一次输入冻结才允许开新一轮）；首轮前项目状态为 `ready_to_analyze`，流水线为 `waiting_start`，报告“下一步”为 `start_analysis` |
| `accept_rules_as_written` | 未确认的废标／否决／强制类规则不再阻止登记提交，报告不催确认，Word 报告注明；问题与判定里的 `rule_basis` 仍如实为 `unconfirmed` |
| `consistency_check` / `scope_check` | 核对时是否运行对应的确定性检测；核对产物的 `checks` 记录本次实际执行了哪些 |
| `show_score` | 关闭后 Word 报告只列“可能的失分点”（前端同样处理）；预测照常进行，用于校准 |
| `price` | 关闭后报告与 Word 报告不含报价，“下一步”不提示填写报价 |
| `outcome_tracking` | 关闭后提交后不提示登记开标结果 |

## AI 约定

模型只产出候选；每条候选必须引用本次提供给它的证据，引文必须能在证据原文中逐字找到（忽略空白），冲突类问题需要正文与规则两侧的引文，改稿的 `original` 必须是原文、`replacement` 里不得出现来源（原文与允许使用的事实）中没有的阿拉伯数字。不满足的候选被丢弃，原因写进产物的 `dropped`，不会静默消失。已知限制：以汉字书写的数字（如“一百八十”）不在数字守卫范围内。

* **响应矩阵**：核对每条规则时模型先给出整体判定（`satisfied` / `violated` / `unclear`）。“满足”必须引用本次提供的正文片段，否则降为“无法判断”；模型判定违反但没有任何一条通过落地校验的问题，同样降为“无法判断”；模型输出多次不合结构的规则记为“检查失败”。判定与规则依据状态（`confirmed` / `unconfirmed`）一并追加保存在 `rule_verdicts`。
* **评分预测**（`ai/predict.py`，四层）：
  1. 读懂两份文件：正文按目录与标题切成章节（`ai/sections.py`）；一次调用把每条带分值的评分条款对应到正文里回应它的章节（每条最多 4 节，没有专门回应的为空），输出不合格时整体改用关键词检索。
  2. 逐项判断：每条评分条款带上对应章节的全文（上限 14000 字；超长时每节保留开头 40% 的配额，其余按条文检索补块，保持文档顺序），按评委的做法先读评分标准定档次、再在档内给分，逐条判断得分要点（覆盖、部分、缺失，前两者必须引用正文）与正文针对性。每条判断 `BIDWB_PREDICTION_REPEATS` 次（默认 3；第 1 次温度 0，其余 0.7），取均值，区间取各次得分与所定档次的并集；全部不可用的条款按 0 到满分全幅计入区间。没有引文支持的“覆盖”降为“缺失”。
  3. 打分模型：按特征规格 `pf-1`（`ai/features.py`，产品与研究共用的唯一定义）算出本轮特征，若业务环境路由了打分模型（契约 `scoring-model/1`，研究侧用官方成绩训练）且项目在其适用范围内，分数与约 80% 区间由模型给出（`validation_status=validated_in_scope`，保留一位小数）；没有模型或不适用时给出逐项评估合计并如实标为未校准（`not_validated`／`out_of_scope`）。影子环境的模型照样计算、写入明细产物，不展示，供对照。
  4. 比较式锚定（`ai/anchors.py`）：路由了锚点包（契约 `anchor-pack/1`，历史标书及其官方分）时，按工程类型、评分办法和分数分位挑 `BIDWB_PREDICTION_ANCHORS` 份锚点（默认 6），对分值合计占七成的前几条评分条款（最多 6 条）逐份比较“哪份更好”（偶数锚点放 A 位、奇数放 B 位以抵消位置偏好），再用一维 Bradley–Terry 拟合（τ=`BIDWB_PREDICTION_ANCHOR_TAU`，默认 6）得到 `anchor_pct` 等特征交给打分模型。正文与锚点相同时不用该锚点。
  评分条款都没有分值时 `status=abstained`。明细产物保存对应关系、逐项判断、特征、校准与影子结果。
* **在线对照**：已登记的官方技术分与对应提交快照上的预测（即界面显示的分数）配对，按满分折算为百分制；样本不足 20 组时只给组数，不给误差。它是上线后的持续监控，打分模型的训练与验收在研究侧完成（见 tender-research 的 `score_eval`）。
* **确定性检测**：同一个量（按“型号限定＋属性名”归并，单位相同）在正文不同位置取值不同；不同页的大段重复；正文出现而招标文件及补遗没有的工程对象（泵站、沉井、调度平台等）。检测只给带出处的候选，由人确认。

## 产品逻辑约定

* **有效规则**：评审使用人工确认的规则和还没有人看过的规则（后者在报告里标“依据未确认”），驳回与暂缓的不用。评审引用的规则包不可变：一个决定改变了参与评审的规则集合（确认→驳回／暂缓，或驳回／暂缓→确认）时，系统复制出新规则包（条款相同、决定沿用）并把更正落在新包上；只是把“未审核”确认下来不改变集合，直接追加审核。
* **规则重新提取的决定沿用**：新规则包里（性质，去空白后的条文）与紧邻的上一版规则包中某条已有人工决定的规则相同，则在新规则下写一条同决定的审核记录（审核人为原审核人，理由为“沿用自上一版规则集：”＋原理由，已带前缀的不重复叠加），并在 `rule_items.carried_from_rule_id` 记下旧规则；条文或性质有变化的保持待定。提取不出任何规则时规则任务以 `no_rules_extracted` 失败，不留空的候选包。
* **事实撤回**：`POST /projects/{id}/facts/{fact_id}/withdraw`，请求体 `{reason}`（必填、非空），锁项目行后生成不含该事实的新事实集（其余条目取新 ID，旧集不变）。`fact_id` 必须属于最新事实集（项目内不存在 404 `fact_not_found`，属于旧事实集 409 `fact_not_current`）。已冻结的输入不受影响。
* **问题**：来源 `rule`（规则核对，带规则与规则依据状态）、`consistency`、`scope`；分类 `disqualification`（与否决／废标项冲突）、`response`（强制性要求未满足）、`consistency`、`scope`、`improvement`。同一输入内以（规则、性质、证据 ID 集合）或检测键为去重键（`UNIQUE(snapshot_id, dedupe_key)`），重跑核对时已有问题原样保留（含人工复核）。所需事实已被已确认事实覆盖的 `needs_confirmation` 候选不会产生问题。
* **项目状态对账**（`issues_open` / `ready_to_submit`）只数“最近一个做过核对的快照”上的未处理问题；核对覆盖度（`Task.coverage`：`complete` / `partial` / `empty`）不是 `complete` 时任务仍为成功，但项目不会进入 `ready_to_submit`，`Task.message` 给出中文说明，重新评审且完整后才放行。
* **问题状态流转**：`candidate` 可确认/驳回/暂缓；`deferred` 可确认/驳回/`reopen`；`confirmed` 可 `resolve`；`revision_pending`（改稿已采纳）可驳回或人工 `resolve`；`rejected`、`resolved` 可 `reopen` 回到 `candidate`；所有决定都必须写理由。对旧轮次（非最新快照）的问题审核返回 409 `snapshot_superseded`。
* **输入快照**：各资料是所属文件的最新版本、已解析（失败或未解析 409 `input_not_parsed`），规则包是最新的（409 `stale_inputs`）；必须含招标文件（409 `tender_missing`）并覆盖项目里每个招标文件/补遗的最新版本（409 `tender_inputs_incomplete`）；规则包的 `source_versions` 必须恰好等于快照里的招标/补遗版本（409 `rules_source_mismatch`）；项目已有事实集时必须带上最新事实集（409 `fact_set_required` / `stale_inputs`）。自动流水线冻结时 `actor_id` 为空，审计里记为系统。
* **提交登记闸门**：快照是项目最新快照（409 `snapshot_not_latest`）；所依据的规则包／事实集／资料仍是当前的（409 `snapshot_stale`）；做过成功且覆盖完整的核对（409 `snapshot_not_diagnosed` / `diagnosis_incomplete`）；没有未确认的废标／否决／强制类规则（409 `qualification_rules_unconfirmed`）；没有未处理的关键问题或废标／强制响应类问题（候选/已确认/暂缓/待修改/待复检，409 `critical_findings_open`）；`submitted_at` 必须带时区且不晚于当前（422 `submitted_at_naive` / `submitted_at_in_future`）；回执必须是本项目已上传的文件（422 `receipt_artifact_invalid`）。登记本身就是对“提交这一版”的确认，同一事务写入一条 `submission` 类确认记录；正文版本须是快照里的正文并仍是最新版本；成绩的取代必须指向同一提交下尚未被取代的记录。
* **改稿建议**：没有任何通过校验的修改时不能采纳（409 `revision_empty`）；采纳只记录“接受建议，相关问题进入待修改”，系统不改写 PDF，`edited_diff_artifact_id` 必须为 null。
* **报价**：保存评标价规则、竞争对手报价估计与候选报价时每次追加一个版本；`POST /projects/{id}/price:simulate` 不保存，只计算。金额与分数全程使用十进制，不涉及成本、利润或人工费。
* **导出**：`GET /projects/{id}/report.docx` 生成 Word 评审报告；`GET /projects/{id}/body.annotated.pdf` 在正文 PDF 上用标准高亮批注标出未关闭的问题（页面有旋转、没有坐标的证据只在页面左上角做标记，不画虚构的高亮位置）。批注版要求正文是 PDF 且不超过 60 MB。
* 通用入口 `POST /projects/{id}/tasks` 不接受任何任务种类（422 `kind_not_creatable_here`）：解析、规则提取、核对、预测由流水线入队，改稿使用专用接口。原件下载响应 `Cache-Control: private, no-store`。
* **文件版本**：上传初始化请求可带 `version_of_file_id`（可空）。给出时必须是本项目内同一用途的文件（否则 422 `version_of_invalid`），本次上传成为该文件的下一版本；不给时总是新的逻辑文件。唯一的隐式规则是字节去重：内容与某文件的最新版本完全相同则直接返回该版本、不新建版本、不再解析。

## 与契约（contracts/）的关系

`contracts/openapi.json` 与 `domain.schema.json` 中由代码定义的部分由 `tools/export_contracts.py` 生成，`tests/test_contract_conformance.py` 校验它们与代码一致，并校验其余手工维护的领域结构与实现的字段集合、必填性一致。有意的差异：`Task.snapshot_id` / `bundle_id` 可为 null（解析、规则提取没有快照；核对、预测、改稿使用内置方法，不绑定方法包，见 `jobs` 的 CHECK 约束）。`POST /auth/login` 是账号口令登录；OIDC 未实现。

## 范围外与未验证

* 评分研究线的接口端点（数据集、实验、方法包、验证与放行由 `bidwb-admin` 登记，没有浏览器端点）；`experiment` / `export` 任务以 `kind_not_implemented` 明确失败（Word／PDF 导出是同步接口，不走任务）。
* 事实录入直接以“已确认”入库（录入本身就是人工确认）；录入时锁项目行，避免并发录入互相覆盖。
* 复检（recheck）、Milvus 混合检索（目前仅关键词通道，混合模式如实降级并说明）、OCR 与表格结构识别。
* 未对真实 Kafka、阿里云 OSS（其对 SigV4 的兼容性）、真实模型输出做过验证；S3 适配器仅对 moto 做过对照测试；浏览器直传（预签名 URL）未在浏览器里验证过。确定性检测与评分预测尚未在真实标书上评估误报率与误差；评分预测四层的流程（批量预测、训练与评估、登记、产品内校准）只在合成数据上跑通，精度结论要等真实成绩到位后由 tender-research 的 `score_eval` 给出。
