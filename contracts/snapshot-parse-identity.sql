-- 旧快照保持 NULL：没有证据证明当时冻结过哪次解析，不按时间回填。
-- 新快照的同名清单字段参与 SHA-256，行级只追加触发器继续保护这两列。
ALTER TABLE input_snapshots ADD COLUMN parse_inputs_json JSONB CHECK(parse_inputs_json IS NULL OR jsonb_typeof(parse_inputs_json)='object');
ALTER TABLE input_snapshots ADD COLUMN coverage_gaps_json JSONB CHECK(coverage_gaps_json IS NULL OR jsonb_typeof(coverage_gaps_json)='array');
