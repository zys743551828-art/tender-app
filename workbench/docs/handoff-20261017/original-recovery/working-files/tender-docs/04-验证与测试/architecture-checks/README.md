# 技术方案隔离验证

这些程序从零编写，不导入旧应用。它们验证关键机制与故障反例，不是产品实现，也不代表真实评分或生产能力。

## 依赖

使用 Python 3.12，创建独立虚拟环境并安装本目录的 requirements.lock.txt。包版本为本次实际环境快照；供应链或平台兼容变更时重新核验，勿直接放进产品运行依赖。

需要独立 PostgreSQL 17 测试实例，pgvector 实验要求安装 vector 扩展；账号需要创建与删除临时数据库权限。只允许使用专门的开发实例。默认管理连接是本机测试容器的无口令连接，不是生产配置。

Temporal实验需要真实开发服务。使用官方CLI并核对发布校验和；具体归档和摘要见 run-manifest.json。开发服务绑定本机，使用独立SQLite文件，不能用于生产。

## 运行

在本目录运行，python指向独立虚拟环境：

~~~sh
python probe_langgraph.py --output langgraph-result.json
python probe_postgres.py --admin-dsn 'host=127.0.0.1 port=55437 dbname=postgres user=postgres' --output postgres-result.json
python probe_pgvector.py --admin-dsn 'host=127.0.0.1 port=55437 dbname=postgres user=postgres' --output pgvector-result.json
python probe_scoring.py --output scoring-result.json
~~~

启动Temporal开发服务，再执行实验：

~~~sh
temporal server start-dev --ip 127.0.0.1 --port 17233 --headless --db-filename /tmp/tender-temporal-proof.sqlite
~~~

在另一终端执行：

~~~sh
python probe_temporal.py --address 127.0.0.1:17233 --admin-dsn 'host=127.0.0.1 port=55437 dbname=postgres user=postgres' --output temporal-result.json
~~~

SQL程序创建 architecture_ 前缀的随机临时库，正常结束或断言失败均在finally中清理。Temporal活动故意在业务提交后失败，日志中的该异常是故障注入；最终结果和退出码决定实验是否符合预期。

重新运行会更换结果，不自动证明旧 run-manifest.json 仍对应当前证据。需要由执行者记录本次程序、结果、环境和时间，再更新清单；检查器发现内容不一致应报失败，不能悄悄改清单。

## 静态证据检查

在文档仓库根目录执行：

~~~sh
python 04-验证与测试/architecture-checks/check_design_assets.py --output /tmp/design-assets-result.json
~~~

加 --source-cache 指向调研缓存的 sources 目录时，还会重新核对取得的原文；没有缓存则明确记为未复核，不自动联网。可重复检查不替代各实验和完整产品验收。

需要取回原文时运行下列命令。它只访问清单中的固定官方URL，沿用代理与TLS校验；内容摘要不一致则失败，不自行更新清单：

~~~sh
python 04-验证与测试/architecture-checks/fetch_official_sources.py --cache /tmp/tender-official-sources
python 04-验证与测试/architecture-checks/check_design_assets.py --source-cache /tmp/tender-official-sources --output /tmp/design-assets-result.json
~~~

执行路线专项与相似产品使用各自的固定来源清单。以下命令验证或取回原文，不执行下载的源码、不安装产品、不改变清单：

~~~sh
python 04-验证与测试/architecture-checks/fetch_official_sources.py --manifest 04-验证与测试/architecture-checks/orchestration-sources.json --cache /tmp/tender-orchestration-sources
python 04-验证与测试/architecture-checks/fetch_official_sources.py --manifest 04-验证与测试/architecture-checks/product-architecture-sources.json --cache /tmp/tender-product-sources
python 04-验证与测试/architecture-checks/check_design_assets.py --source-cache /tmp/tender-official-sources --orchestration-source-cache /tmp/tender-orchestration-sources --product-source-cache /tmp/tender-product-sources --output /tmp/design-assets-result.json
~~~

专项资料的取得与缓存摘要核验不表示Agent Server、Dify、Celery、Onyx或Refly已经部署或通过生产测试。产品清单中的官网403和配置草稿过期是实际访问限制，不能从未取得页面推断内部技术栈。
