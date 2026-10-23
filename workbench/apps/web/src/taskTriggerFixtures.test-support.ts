import actual from "./test-fixtures/task-package-triggers-http.json";
import type { RunView, TaskNotificationPage } from "./contracts";
import type { TaskPackageHTTPFixture } from "./taskPackageFixtures.test-support";
import type {
  PackageTriggerIntentPage,
  PackageTriggerIntentView,
  TaskKindPage,
  TaskScheduleRecoveryPage,
  TemplateView,
} from "./taskTriggerContracts";

type Fixtures = {
  "event-template": TaskPackageHTTPFixture<TemplateView>;
  "schedule-template": TaskPackageHTTPFixture<TemplateView>;
  "task-kinds": TaskPackageHTTPFixture<TaskKindPage>;
  "event-pending": TaskPackageHTTPFixture<PackageTriggerIntentView>;
  "event-accepted": TaskPackageHTTPFixture<PackageTriggerIntentView>;
  "event-intents": TaskPackageHTTPFixture<PackageTriggerIntentPage>;
  "event-succeeded-run": TaskPackageHTTPFixture<RunView>;
  "event-notifications": TaskPackageHTTPFixture<TaskNotificationPage>;
  "cancel-pending": TaskPackageHTTPFixture<PackageTriggerIntentView>;
  cancelled: TaskPackageHTTPFixture<PackageTriggerIntentView>;
  "schedule-missed": TaskPackageHTTPFixture<TaskScheduleRecoveryPage>;
} & Record<
  `blocked-${"template" | "pause" | "close" | "source" | "event"}`,
  TaskPackageHTTPFixture<PackageTriggerIntentView>
>;

/** Unmodified response data from the isolated PG17/ASGI/Worker run, with synthetic originals and mock model HTTP. */
export function taskTriggerFixtures(): Fixtures {
  return structuredClone(actual) as unknown as Fixtures;
}
