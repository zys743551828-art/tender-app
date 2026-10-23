/** Task-only import surface; every wire type is generated from the actual server OpenAPI. */
export type {
  ExactPackageTriggerSelection,
  PackageTaskTriggerCapabilities,
  PackageTriggerIntentPage,
  PackageTriggerIntentView,
  TaskDraftInterpretation,
  TaskDraftPage,
  TaskDraftRequest,
  TaskDraftView,
  TaskKindPage,
  TaskKindView,
  TaskScheduleRecovery,
  TaskScheduleRecoveryPage,
  TaskScheduleRecoveryPayload,
  TemplatePage,
  TemplateRequest,
  TemplateView,
} from "./contracts";

export type TaskSourceSelection = NonNullable<
  import("./contracts").TemplateRequest["source_selection"]
>;
