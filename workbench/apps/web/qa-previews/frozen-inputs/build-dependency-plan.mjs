import { buildFixture } from "./build-fixture.mjs";
await buildFixture(
  "qa-previews/frozen-inputs/dependencyPlanFixture.tsx",
  "dependency-plan",
  "依赖计划保存与恢复合成验收",
);
