# 转换请求顺序

Word转换受理在项目行锁之后进行，`word_render_runs.created_at`由数据库`clock_timestamp()`默认值赋予。最新请求按该时间与operation_id稳定排序，较早开始的长事务后受理时也必须成为最新请求。API保持原有五个输入列的INSERT权限，不能传入或改写受理时间。

初始化计划在Word schema之后执行`packages/word_intake/request_order.sql`。只用于全新独立库初始化，不对现有运行数据库热补。原Word03 schema、预检及renderer profile保持原字节，转换输出仍由普通Worker在fence事务内写入。

`baseline-result.json`保存旧默认值下真实非owner双事务反例。`explicit-column-result.json`保存API列权限对直接写时间的拒绝，不能用owner业务账号绕过。修复必须由新库默认值通过同一探针确认，并核验最新失败/未完成不能返回旧成功PDF。
