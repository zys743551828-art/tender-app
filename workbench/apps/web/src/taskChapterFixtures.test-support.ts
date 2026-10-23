import actual from "./test-fixtures/task-chapter-http.json";
import type {
  AssistantAction,
  Operation,
  RunView,
  TemplateVersionView,
} from "./contracts";

export type TaskChapterHTTP = {
  run: RunView;
  template_version: TemplateVersionView;
  operation: Operation;
  operation_etag: string;
  proposal: AssistantAction | null;
};
/** Original response bodies from isolated PG17/ASGI/Worker, with explicit mock model HTTP. */
export function taskChapterFixtures() {
  return structuredClone(actual) as unknown as Record<
    keyof typeof actual,
    TaskChapterHTTP
  >;
}
