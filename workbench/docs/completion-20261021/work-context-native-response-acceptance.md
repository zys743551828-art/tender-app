# 原生工作上下文响应与前端协议实喂验收

日期：2026-10-21。本批仅新增原生合成响应采集测试、可运行的前端校验脚本与独立证据；不修改已冻结 A/B 后端产品或其测试，也不修改根代理负责的前端产品。最终文件与摘要见 `work-context-native-response-manifest.json`。

## 1. 实际验证结果

| 检查                                    | 本次结果               | 具体范围                                                                         |
| --------------------------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| 隔离 PostgreSQL 17.11 原生测试          | 2 通过，0 失败，0 跳过 | 新集群、新非 owner API/Worker、真实路由及 session；结束已停库                    |
| 当前前端 TS validators 直接读取原生响应 | 11/11 接受             | 核查、实交、普通原稿、稀疏序号原稿、富内容原稿、构建、四阶段目录、构建采用关系   |
| 图片元数据与保存绑定                    | 通过                   | bid、asset/version、revision、version digest、规范图摘要、尺寸及规范化证明       |
| 合成规范 PNG 字节                       | 通过                   | fixture 原生规范化字节的 SHA256、长度、PNG IHDR 尺寸与保存绑定一致               |
| 非法章节序号反例                        | 按预期退出 1           | 独立副本仅将原生正文 ordinal 改为 500，未重封 digest；对应协议检查拒绝           |
| 错误图片字节反例                        | 按预期退出 1           | 独立副本仅改变规范 PNG base64 的首字节，未改 metadata 或摘要；字节一致性检查拒绝 |
| 静态检查                                | 通过                   | Python 新测试 ruff check/format；Node 脚本 ESLint/Prettier                       |

当前脚本共 13 项检查，其中 11 项调用产品中实际的 TS validators，另两项是图片绑定和字节的一致性检查。两个负向副本各只有目标项失败，不能当作真实原生返回；原始 bundle 保持字节不变。

本批原生测试是 A/B 冻结候选上的独立追加验证。A 的 49 项、B 的 28 项结果及原生权限／并发反例见各自验收，不把重复使用夹具累加为新的独立产品覆盖。

## 2. 原始响应来源与固定候选

`tests/test_work_context_native_bundle_pg.py` 复用既有原生夹具，实际建立保存稿、Word/PDF 构建、Word 采用关系、整包核查和明确绑定核查的实交。源文件及模型响应均是显式合成测试数据；没有真实客户材料、付费模型调用或旧库连接。

采集使用真实 FastAPI 路由、已认证 session 和非 owner 数据库连接。每次 `client.get()` 必须返回 200，`response.json()` 的值原样写入 bundle；不替换 UUID、时间、摘要、输出证明或正文。该额外采集测试使用 ASGI TestClient；真实环回 Uvicorn 的 401/200 与缓存头验证属于此前 B 批，不能把两种传输混为一谈。

原始 bundle 含 12 条响应：11 条工作上下文、目录、关系响应，加 1 条历史图片元数据。富内容原稿有 **180000 字符**合成正文、原生合并表格和固定图片版本。此前 B 批另有 240000 字符测试，二者不是同一份数据。图片 base64 来自实际规范化函数处理后的合成 PNG 字节，不是通过图片 bytes GET 抓取。

- 原生追加候选：`/tmp/tender-review-work-context-native-responses/candidate/workbench`
- 候选 manifest SHA256：`daba37ef51de056c1ecfa5ed3733def250861c8c2760530152e40ca25ac29412`
- 原生测试收据：`/tmp/tender-review-work-context-native-responses/work-context-pg-r1ox8vdl-receipt.json`
- 原始响应：`/tmp/tender-review-work-context-native-responses/native-responses.json`
- 原始响应 SHA256：`c4045efba7eab1f09dd53a0b40f0602e01f327f68681aa84de221852773ac1a1`
- 原始响应大小：609364 字节。

采集仅在显式设置绝对路径 `WORK_CONTEXT_SYNTHETIC_RESPONSE_BUNDLE` 时写文件；普通测试不会额外落盘。文件不包含 session/cookie/token/DSN、幂等键或私有对象路径。原生正文 bundle 保留在临时验收目录，Git 证据仅存脚本、测试与无正文收据／摘要。

## 3. 确认的跨端缺陷与修复闭合

首次将原生响应直接送入前端时为 10 接受、1 拒绝。原生旧保存路径允许不同章节的原始 ordinal 不连续；实际返回的旧原稿是 `outline=null`、连续展示序号 `section.ordinal=0`、原始正文 `content.attrs.ordinal=7`。原稿 hash 和 schema 均有效，前端误将正文内序号等同展示下标，导致无法读取。

根代理已移除这项错误等同约束，继续保留正文 schema、原文 digest、连续展示顺序和活动目录 DFS 核验。本次没有修改或重新封装该 API 返回，原来失败的同一条原生响应现已通过。最初的失败 JSON 与当时实际编译的 validators 均保留，修复后的新收据另存，不覆盖旧证据。

只读审查还发现图片二次 metadata 没有绑定保存记录中的 version/normalized digest，以及生成采用关系未核对已验证构建的同格式成功输出。根代理已修复产品并负责组件反例。本次脚本将关系显式传给 `validateWorkContextRelations(data, verifiedBuild.selection, verifiedBuild.build.outputs)`，并核对真实图片 metadata 与保存稿绑定，原生样本均通过。离线脚本不替代根代理的图片组件与实际浏览器测试。

成员／项目／阶段 remount、请求 ticket、目录观察与总数／重复／游标循环、成员隔离恢复、草稿导航守卫、明确旧核查和实交原记录边界也已只读核对；本次未找到额外可复现缺陷。这是有限审查结果，不是整个应用无缺陷的声明。

## 4. 仓库脚本与复现

在 `workbench/apps/web` 安装既有锁定依赖后运行：

```sh
node scripts/check-work-context-native.mjs \
  /tmp/tender-review-work-context-native-responses/native-responses.json \
  /tmp/tender-review-work-context-native-responses/new-frontend-receipt.json
```

脚本要求输入 bundle 与新的输出收据路径，不覆盖已有收据。它用 esbuild 编译当前仓库实际 TS validators；逐份原样传入冻结 JSON，对其使用原始 URL 中的 bid/对象 ID 作为预期身份。构建先完成验证，关系仅接收它的成功输出。所有 body 在内存中冻结，前后比较均要求值不变；不重封选择、观察或正文摘要。

脚本记录 esbuild 实际加载的源码字节摘要、依赖锁摘要、Node/esbuild 版本、输入摘要、检查结果与限制，并在收据旁保存实际执行的 `.validators.mjs`。源码与输入在运行结束必须仍匹配；有任意失败则退出 1。不会访问网络、数据库、对象存储或付费接口。

当前成功收据为 `frontend-current-receipt.json`（同临时目录），13 项通过。`work-context-native-response-checks.json` 包含原生、前端和负向反例收据内容及外部文件摘要；首次失败证据单独保留。

重新采集须在明确的一次性新 PG 集群中配置 `FUSION_REQUIREMENTS_ADMIN_DSN`，并通过环境变量提供目标绝对路径，然后从 `workbench` 执行：

```sh
python -m pytest -q --tb=short tests/test_work_context_native_bundle_pg.py
```

未配置 PG 时产生的 skip 不算通过。本次已使用隔离 runner 实际完成两个测试并停库；没有为了重采响应重复启动旧库或改变产品权限。原生 runner 与完整命令、退出码、静态检查和文件摘要见 checks。

## 5. 证明边界

这份收据证明当前前端协议能够接受所列真实原生合成 API JSON，且固定图片的元数据与规范字节一致。它不证明图片 bytes HTTP 传输、浏览器解码、视觉布局、用户导航、生产权限、真实标书质量或预测效果。原稿与关系中的 `original_bytes_reverified=false`、`qualification_assessed=false` 未改变；没有因此把正式预测、整包风险或通过结论从 null 升级为有效值。完整前端交互和浏览器证据由根代理独立归档。
