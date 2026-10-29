# 阶段：全新检出的测试可复现性

## 问题与修复

从 `462ec226` 全新检出并按原锁安装依赖后，默认后端测试首轮为 22 通过、7 跳过、1 失败后停止。失败来自旧应用恢复测试硬编码的 `/workspace/tender-docs/.../protocol-02/baseline-inputs.json`。该固定 308 份源码／15 份 SQL 的历史验收包没有保存在当前两个 Git 仓库中，不能用当前源码生成一个替代包并称为原验收。

六项依赖这个外部历史包的测试现在共用 `tests/archived_recovery_inputs.py`：

- 普通检出明确显示历史档案验收跳过及其原因；其余恢复权限、凭据隔离、拒绝未知资源、原始字节等本地反例继续运行。
- 只有显式设置 `RUN_ARCHIVED_RECOVERY=1` 才执行原档案验收。显式启用后缺原文件会失败，仍核对生产恢复代码中原始固定 SHA，不降级为跳过，也不放宽原输入守卫。
- 历史档案的挂载位置仍按原协议，原记录不重写。

另有两个纯正文生成测试误依赖外部 Word03 profile 路径。它们现在默认读取已经在同库保存、也由现有富内容测试使用的 `docs/authoring-rich-static-checks/word03-base-profile.json`。`AUTHORING_GENERATED_BASE_PROFILE_FIXTURE` 显式覆盖保持；原 profile 摘要及三份 Word03 源码身份校验保持。测试仍禁止 Docker、网络和模型调用，不以此宣布真实 PDF 转换通过。

## 已执行验证

```sh
.venv/bin/python -m pytest -q \
  tests/test_application_recovery.py \
  tests/test_application_recovery_binding.py \
  tests/test_application_recovery_fixture.py \
  tests/test_authoring_generated.py
```

结果为 **71 通过、6 跳过、0 失败，1.17 秒**，仅有既有 Starlette／AnyIO 弃用警告。六项跳过全部对应上述未归档的固定历史包，不能计为恢复通过。

额外的 CI 回归覆盖显式开启却缺文件必须失败，以及未开启时明确返回 skipped；见 `tests/test_ci_checks.py`。改动文件 Ruff／格式通过。生产恢复实现、原资格判断和原摘要常量均未修改。

## 未取得的证据

原固定历史包没有因此恢复，旧应用恢复正向验收仍需该包；本修复没有替代当前结构的真实数据库／原件恢复、生产 RPO／RTO 或转换隔离验收。
