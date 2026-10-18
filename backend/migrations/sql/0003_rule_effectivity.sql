-- 补遗效力与规则版本一起追加保存；不通过改写旧规则或删除原件来结束要求。
ALTER TABLE rule_packages ADD COLUMN effectivity_json JSONB NOT NULL DEFAULT '{}'::jsonb
 CHECK(jsonb_typeof(effectivity_json)='object');
