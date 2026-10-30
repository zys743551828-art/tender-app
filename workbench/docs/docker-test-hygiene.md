# 本机 Docker 测试资源规则

新测试必须使用唯一 run ID 与资源名称，给容器、网络及数据卷标记 `tender.test.run` 和 `tender.test.disposable=true`。源码只读挂载，合成数据放本轮新建卷或 tmpfs，不连接业务库，不继承模型或对象存储凭据。

`deploy.disposable_docker.DockerTestRun` 是脚本共用的资源上下文。创建前写入精确目标，创建后记录实际资源 ID；收尾逐项 inspect 核对本轮标签和 ID，再按依赖逆序精确删除。镜像仅使用已有本地缓存，禁止隐式 pull。镜像声明的数据目录默认使用 tmpfs，避免匿名卷。证据文件只保留资源身份及清理状态，不记录环境变量值、命令输出或秘密。

```python
from pathlib import Path
from deploy.disposable_docker import DockerTestRun

with DockerTestRun(Path(".local/checks/<new-run>/resources.json")) as run:
    identity = run.container(
        "sha256:<existing-local-python-image-id>",
        ["--network", "none", "--read-only", "--entrypoint", "python"],
        ["-c", "print('synthetic local check')"],
    )
    run.start(identity, attach=True)
```

把服务启动也放在 `with` 内。正常结束、异常、超时与 Python 取消均执行收尾；创建结果不确定时只按已写入的唯一名称核对标签。所有权或 ID 变化、Docker 不可访问、删除失败时不继续猜测删除，回执保持 `closed=false` 并记录待处理资源。进程被强杀、断电或 Docker 不可用无法保证自动收尾；应根据该回执逐项复核，不调用 prune。

真实本机清理验收使用 `tests/test_disposable_docker_native.py`。显式设置 `DISPOSABLE_DOCKER_TEST_IMAGE` 为已核验本地 Python 镜像，及全新 `DISPOSABLE_DOCKER_TEST_EVIDENCE` 目录，执行该文件。三个用例分别实际创建容器、隔离网络和合成数据卷，覆盖成功、失败、取消，并复查资源不存在。未提供镜像时跳过，不能计为通过。

`fusion_desktop prepare/up` 用于保留的开发环境，不能用来代替一次性测试入口。`fusion_checks` 复用已指定环境执行检查，不负责清理该开发环境。不要为了运行测试删除或重启既有 `bidwb` / `tender-fusion` 环境。

旧资源处理独立于本轮自动清理：先列精确 Compose 项目、容器 ID、状态和数据挂载。用户按具体范围批准后才能删除历史容器。保留所有未知卷、镜像和宿主目录；即使保留挂载卷，删除容器仍会丢失其可写层中的未挂载文件。禁止 `docker system prune`、`volume prune`、批量猜测删除以及把旧资源收编为本轮资源。
