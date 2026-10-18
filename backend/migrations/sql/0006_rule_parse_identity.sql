-- 原规则包缺少精确解析来源时保留未知，不根据证据时间或后来解析推断。
ALTER TABLE rule_packages ADD COLUMN parse_inputs_json JSONB CHECK(parse_inputs_json IS NULL OR jsonb_typeof(parse_inputs_json)='object');
