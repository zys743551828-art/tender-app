# 实施版 OpenAPI 快照存储与兼容验收

仓库中的完整实施版快照改为 `packages/contracts/fusion-implemented.openapi.json.gz`。这是存储表示变化：路由、schema、字段、约束与 API 行为均未删减。运行时 `/openapi.json` 继续动态返回普通 JSON。

导出使用 `gzip.GzipFile(filename="", mtime=0)`，不记录输出路径或构建时间；同一完整契约的输出字节固定。`python -m apps.api.export_openapi` 默认仍输出普通 JSON；`--output path.json` 输出可读文件，`--output path.json.gz` 输出确定性 gzip。默认前端生成器读取 gzip，`--openapi path.json` 继续支持普通 JSON。仅精确的本地可读导出路径被忽略，冻结 QA 历史快照保持原样。

## 实际验证

- 原完整 JSON 为 1,754,384 字节，gzip 为 101,055 字节；解压后与改造前 JSON 逐字节相同。
- 重新生成并格式化后的 `contracts.ts`，除首行来源注释外，与改造前逐字节相同，类型和能力清单未变。
- `tests/test_openapi_snapshot.py` 的 4 项回归验证完整实际 schema、gzip 往返和无路径／时间元数据、stdout／plain／gzip 兼容、两种输入生成相同完整类型及能力、已提交 TypeScript 与正式格式化生成结果一致。
- 与 `test_actual_contract.py`、`test_authoring_m1_composition.py` 同批执行：9 项通过，未跳过。新回归中的精确 TypeScript 比较要求已安装锁定的前端依赖；未安装时会明确跳过该项，不能记为通过。
- 导出器、生成器和新测试 Ruff／格式通过；两个实现文件 mypy 和 Bandit 通过。

当前 gzip 的 Git blob SHA 为 `b3ed6402ef43b309809d819d3fe228be6716e4f3`，SHA-256 为 `fd6432e05e88a502d98ab6297608590f9ff9badfc76701069e060deecdb52e31`。未来修改实际 API 后，按更新后的 README 重新生成快照和类型，再执行同一回归；这些摘要不会固定未来 API。

本变更不创建工作流，不授予权限，也不自动推送或执行远端任务。仓库存储验收不代表 GitHub 推送已经完成；远端状态由进度页另行记录。
