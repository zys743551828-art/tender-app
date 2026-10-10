import type { FactRequest } from '../../api/types';

export interface FactDraft {
  name: string;
  subject: string;
  scope: string;
  value: string;
  unit: string;
  statement: string;
  evidenceIds: string;
}

export type FactErrors = Partial<Record<keyof FactDraft, string>>;

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** 证据 ID 支持空白、逗号、顿号、分号分隔；去重并保持顺序。 */
export function parseEvidenceIds(text: string): string[] {
  return [...new Set(text.split(/[\s,，、;；]+/).filter((s) => s !== ''))];
}

export function validateFact(d: FactDraft): FactErrors {
  const e: FactErrors = {};
  if (!d.name.trim()) e.name = '请填写事实名称';
  if (!d.subject.trim()) e.subject = '请填写事实主体';
  if (!d.scope.trim()) e.scope = '请填写适用范围';
  if (!d.statement.trim()) e.statement = '请填写事实陈述';
  if (d.value.trim() && !DECIMAL.test(d.value.trim()))
    e.value = '数值须为十进制数，例如 180 或 12.5';
  if (parseEvidenceIds(d.evidenceIds).length === 0) e.evidenceIds = '至少填写一个证据 ID';
  return e;
}

export function toFactRequest(d: FactDraft): FactRequest {
  return {
    name: d.name.trim(),
    subject: d.subject.trim(),
    scope: d.scope.trim(),
    value_decimal: d.value.trim() || null,
    unit: d.unit.trim() || null,
    statement: d.statement.trim(),
    evidence_ids: parseEvidenceIds(d.evidenceIds),
  };
}
