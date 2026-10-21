// Standalone recovery records use this registry for both their keys and account cleanup.
const memberCommandKinds = [
  "fact-change",
  "fact-scope",
  "package-freeze",
  "package-execution",
  "dependency-plan",
  "package-review-run",
  "package-review-decision",
  "package-review-report-export",
  "package-rule-correction",
  "package-technical-scope",
  "historical-import",
  "package-submission",
  "package-official-outcome",
  "package-retrospective",
  "package-retrospective-knowledge",
  "document-parse",
  "submission",
  "report",
  "pricing-formula",
  "pricing-simulate",
  "pricing-save",
  "knowledge-search",
  "knowledge-unit",
  "knowledge-index",
  "business-result",
  "business-verification",
  "assistant-main",
  "assistant-state",
  "assistant-turn",
  "assistant-note",
  "assistant-cancel",
  "assistant-action",
  "task-template",
  "task-package-template",
  "task-package-run",
  "task-package-authoring-template",
  "task-package-authoring-run",
  "task-pause",
  "task-run",
  "task-draft",
  "authoring-structure",
  "authoring-resolve",
  "authoring-plan",
  "word-retry",
  "authoring-template",
  "authoring-package-capture",
] as const;
const memberCommands: ReadonlySet<string> = new Set(memberCommandKinds);

export function recordedCommandStorageKey(
  kind: (typeof memberCommandKinds)[number],
  memberId: string,
  ...scope: [string, ...string[]]
) {
  return `tender:command-record:${kind}:${memberId}:${scope.join(":")}`;
}

export function clearRecordedCommands(keepMemberId?: string) {
  for (const key of Object.keys(sessionStorage)) {
    const draft = key.match(
      /^tender:retrospective-(?:draft|handoff|selection):([^:]+):/,
    );
    if (draft && (!keepMemberId || draft[1] !== keepMemberId)) {
      sessionStorage.removeItem(key);
      continue;
    }
    const match = key.match(/^tender:command(?:-record)?:([^:]+):([^:]+):/);
    if (
      match &&
      memberCommands.has(match[1]) &&
      (!keepMemberId || match[2] !== keepMemberId)
    )
      sessionStorage.removeItem(key);
  }
}
