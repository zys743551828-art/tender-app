export const historyTime = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
export const historyPurposeNames = {
  fit: "拟合",
  development: "开发选择",
  calibration: "区间校准",
  final: "最终评估",
  excluded: "排除",
} as const;
export const historyStateNames = {
  queued: "等待独立执行",
  running: "正在执行",
  paused: "已暂停",
  succeeded: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
} as const;
