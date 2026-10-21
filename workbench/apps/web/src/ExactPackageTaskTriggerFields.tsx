import type {
  PackageTaskTriggerCapabilities,
  TemplateRequest,
} from "./taskTriggerContracts";
import { isExactPackageTask } from "./taskState";

export function ExactPackageTaskTriggerFields({
  input,
  change,
  capability,
}: {
  input: TemplateRequest;
  change: (input: TemplateRequest) => void;
  capability: PackageTaskTriggerCapabilities | null;
}) {
  const trigger = input.trigger ?? {
    mode: "manual",
    cron: null,
    timezone: "Asia/Shanghai",
  };
  return (
    <>
      <label>
        触发方式
        <select
          aria-label="触发方式"
          value={trigger.mode}
          onChange={(event) => {
            if (!isExactPackageTask(input)) return;
            const mode = event.target.value as
              | "manual"
              | "material_updated"
              | "schedule";
            change({
              ...input,
              source_selection: {
                mode:
                  mode === "manual"
                    ? "exact_package_review"
                    : "exact_package_trigger",
                input: input.source_selection.input,
              },
              trigger: {
                mode,
                cron:
                  mode === "schedule" ? (trigger.cron ?? "0 9 * * *") : null,
                timezone: trigger.timezone ?? "Asia/Shanghai",
              },
            });
          }}
        >
          <option value="manual">仅手动运行（默认）</option>
          <option value="material_updated" disabled={!capability?.available}>
            资料入库后核对这份输入
          </option>
          <option value="schedule" disabled={!capability?.available}>
            按计划核对这份输入
          </option>
        </select>
      </label>
      {trigger.mode === "schedule" && (
        <>
          <label>
            定时表达式
            <input
              aria-label="定时表达式"
              required
              maxLength={200}
              value={trigger.cron ?? ""}
              onChange={(event) =>
                change({
                  ...input,
                  trigger: { ...trigger, cron: event.target.value },
                })
              }
            />
          </label>
          <p className="small-note">
            按分钟、小时、日、月、星期填写五段。例如 0 9 * * * 为所选时区每天
            9:00；日期与星期不能同时限制。
          </p>
          <label>
            计划时区
            <input
              aria-label="计划时区"
              required
              maxLength={100}
              value={trigger.timezone ?? "Asia/Shanghai"}
              onChange={(event) =>
                change({
                  ...input,
                  trigger: { ...trigger, timezone: event.target.value },
                })
              }
            />
          </label>
        </>
      )}
      {trigger.mode !== "manual" && (
        <p className="notice neutral">
          仅唤醒上方明确选择的原输入。独立调度服务启用后才处理后续事件或时刻，届时可能请求模型并产生费用；错过时段会跳过，需重新核对后选择手动运行。
        </p>
      )}
      {!capability?.available && (
        <p className="small-note">
          当前服务尚未开放整包事件或定时触发；手动模板仍可保存。
        </p>
      )}
    </>
  );
}
