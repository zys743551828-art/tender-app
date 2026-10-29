import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type ApiResult } from "./api";
import type { Bid } from "./contracts";
import type { PackageTriggerIntentView } from "./taskTriggerContracts";
import { exactKeys, recordObject } from "./executionInputValidation";
import { historicalSame } from "./historicalImportProtocol";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  assertTaskPackageScope,
  definitiveTaskPackageFailure,
  isTaskPackageCreationIdentity,
  validateRunACK,
  validateTaskTriggerCancelACK,
  validateTaskPackageBasis,
  validateTaskPackagePending,
  validateTemplateACK,
  verifyTaskPackagePending,
  type PendingTaskPackageCommand,
  type TaskPackageCommandRequest,
  type TaskPackageKind,
  type TaskPackageRunView,
  type TaskPackageScope,
  type TaskPackageTemplateView,
} from "./taskPackageProtocol";
import {
  validatePackageAuthoringTemplateACK,
  validatePackageAuthoringRunACK,
  type PackageAuthoringTemplateView,
  type PackageAuthoringRunView,
} from "./taskPackageAuthoringProtocol";

type Result<K extends TaskPackageKind> = K extends "template"
  ? TaskPackageTemplateView
  : K extends "run"
    ? TaskPackageRunView
    : K extends "authoring_template"
      ? PackageAuthoringTemplateView
      : K extends "authoring_run"
        ? PackageAuthoringRunView
        : PackageTriggerIntentView;
type Recovery = {
  version: 1;
  scope: TaskPackageScope;
  state: "pending" | "conflict";
  pending: PendingTaskPackageCommand;
};
type Snapshot = {
  pending: PendingTaskPackageCommand | null;
  busy: boolean;
  checking: boolean;
  error: unknown;
  blocked: boolean;
  conflict: boolean;
  rejected: boolean;
};
type Session = {
  scope: TaskPackageScope;
  storageKey: string;
  raw: string | null;
  recovery: Recovery | null;
  snapshot: Snapshot;
  active: boolean;
  running: boolean;
  epoch: number;
};
const recoveryLimit = 256 * 1024;
const damaged = () =>
  new Error(
    "整包任务恢复记录损坏或身份不符，已暂停新写入；请保留原记录并核对服务器历史。",
  );
const lostScope = () =>
  new Error(
    "登录、任务范围或原恢复记录已变化，已停止接收本次回执；不会重新写回旧记录。",
  );
const storageFailure = () =>
  new Error(
    "浏览器无法可靠保存整包任务的原请求，未确认操作成功；请保留输入并检查此站点存储空间。",
  );
export function taskPackageStorageKey(scope: TaskPackageScope) {
  assertTaskPackageScope(scope);
  if (scope.kind === "authoring_template" || scope.kind === "authoring_run")
    return recordedCommandStorageKey(
      scope.kind === "authoring_template"
        ? "task-package-authoring-template"
        : "task-package-authoring-run",
      scope.memberId,
      scope.bidId,
      scope.identity,
    );
  if (scope.kind === "trigger_cancel")
    return recordedCommandStorageKey(
      "task-package-run",
      scope.memberId,
      scope.bidId,
      "trigger-cancel",
      scope.identity,
    );
  return recordedCommandStorageKey(
    scope.kind === "template" ? "task-package-template" : "task-package-run",
    scope.memberId,
    scope.bidId,
    scope.identity,
  );
}
function parseRecovery(raw: string, scope: TaskPackageScope): Recovery {
  try {
    if (new TextEncoder().encode(raw).length > recoveryLimit) throw damaged();
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "state", "pending"]) ||
      value.version !== 1 ||
      !historicalSame(value.scope, scope) ||
      typeof value.state !== "string" ||
      !["pending", "conflict"].includes(value.state)
    )
      throw damaged();
    validateTaskPackagePending(value.pending, scope);
    return value as unknown as Recovery;
  } catch {
    throw damaged();
  }
}
function initial(scope: TaskPackageScope): Session {
  const session: Session = {
    scope,
    storageKey: "",
    raw: null,
    recovery: null,
    active: false,
    running: false,
    epoch: 0,
    snapshot: {
      pending: null,
      busy: false,
      checking: false,
      error: null,
      blocked: false,
      conflict: false,
      rejected: false,
    },
  };
  try {
    session.storageKey = taskPackageStorageKey(scope);
    session.raw = sessionStorage.getItem(session.storageKey);
    if (session.raw !== null) {
      const recovery = parseRecovery(session.raw, scope);
      session.recovery = recovery;
      const conflict = recovery.state === "conflict";
      session.snapshot = {
        ...session.snapshot,
        pending: conflict ? null : structuredClone(recovery.pending),
        checking: true,
        conflict,
        rejected: conflict,
        error: conflict
          ? new ApiError(
              "原请求遇到修订冲突。请明确重新读取并采用服务器基准，再保存新操作。",
              412,
              "REVISION_CONFLICT",
            )
          : null,
      };
    }
  } catch (error) {
    session.snapshot = { ...session.snapshot, blocked: true, error };
  }
  return session;
}

/** Exact package commands alone use this protocol; legacy task command behavior is unchanged. */
export function useTaskPackageCommand<K extends TaskPackageKind>(
  scope: TaskPackageScope<K>,
) {
  const { kind, memberId, bidId, identity } = scope;
  const session = useMemo(
    () => initial({ kind, memberId, bidId, identity }),
    [kind, memberId, bidId, identity],
  );
  const current = useRef(session);
  current.current = session;
  const [rendered, render] = useState({ session, snapshot: session.snapshot });
  const snapshot =
    rendered.session === session ? rendered.snapshot : session.snapshot;

  function live(epoch: number) {
    return (
      session.active && current.current === session && session.epoch === epoch
    );
  }
  function update(patch: Partial<Snapshot>) {
    session.snapshot = { ...session.snapshot, ...patch };
    if (session.active && current.current === session)
      render({ session, snapshot: session.snapshot });
  }
  function owns(raw: string | null, epoch: number) {
    if (!live(epoch)) return false;
    try {
      if (sessionStorage.getItem(session.storageKey) === raw) return true;
      update({ blocked: true, error: lostScope() });
    } catch {
      update({ blocked: true, error: storageFailure() });
    }
    return false;
  }
  function persist(recovery: Recovery | null, expectedRaw: string | null) {
    if (sessionStorage.getItem(session.storageKey) !== expectedRaw)
      throw lostScope();
    const raw = recovery ? JSON.stringify(recovery) : null;
    if (raw !== null && new TextEncoder().encode(raw).length > recoveryLimit)
      throw storageFailure();
    try {
      if (raw === null) sessionStorage.removeItem(session.storageKey);
      else sessionStorage.setItem(session.storageKey, raw);
      if (sessionStorage.getItem(session.storageKey) !== raw)
        throw storageFailure();
    } catch {
      throw storageFailure();
    }
    session.raw = raw;
    session.recovery = recovery;
    return raw;
  }

  useEffect(() => {
    session.active = true;
    const epoch = ++session.epoch;
    render({ session, snapshot: session.snapshot });
    if (session.recovery && !session.snapshot.blocked) {
      const raw = session.raw;
      void verifyTaskPackagePending(session.recovery.pending, session.scope)
        .then(() => {
          if (
            !session.active ||
            current.current !== session ||
            epoch !== session.epoch
          )
            return;
          if (sessionStorage.getItem(session.storageKey) !== raw)
            throw lostScope();
          session.snapshot = { ...session.snapshot, checking: false };
          render({ session, snapshot: session.snapshot });
        })
        .catch((error: unknown) => {
          if (
            !session.active ||
            current.current !== session ||
            epoch !== session.epoch
          )
            return;
          session.snapshot = {
            ...session.snapshot,
            checking: false,
            blocked: true,
            error,
          };
          render({ session, snapshot: session.snapshot });
        });
    }
    return () => {
      session.active = false;
      ++session.epoch;
    };
  }, [session]);

  async function send(
    raw: string,
    epoch: number,
  ): Promise<ApiResult<Result<K>> | null> {
    let sent = false;
    try {
      const recovery = parseRecovery(raw, session.scope);
      if (recovery.state !== "pending") throw damaged();
      const pending = await verifyTaskPackagePending(
        recovery.pending,
        session.scope,
      );
      if (!owns(raw, epoch)) return null;
      sent = true;
      const response = await api<unknown>(pending.path, {
        method: pending.method,
        body: pending.body,
        etag: pending.etag,
        key: pending.key,
      });
      const data =
        pending.expected.kind === "template"
          ? await validateTemplateACK(
              response.data,
              response.etag,
              pending,
              session.scope,
            )
          : pending.expected.kind === "run"
            ? await validateRunACK(
                response.data,
                response.etag,
                pending,
                session.scope,
              )
            : pending.expected.kind === "authoring_template"
              ? await validatePackageAuthoringTemplateACK(
                  response.data,
                  response.etag,
                  pending,
                  session.scope,
                )
              : pending.expected.kind === "authoring_run"
                ? await validatePackageAuthoringRunACK(
                    response.data,
                    response.etag,
                    pending,
                    session.scope,
                  )
                : await validateTaskTriggerCancelACK(
                    response.data,
                    response.etag,
                    pending,
                    session.scope,
                  );
      // Hashing is asynchronous too: check both component scope and the original
      // durable record after all ACK verification, before clearing or returning.
      if (!owns(raw, epoch)) return null;
      persist(null, raw);
      update({ pending: null, error: null, conflict: false, rejected: false });
      return { ...response, data: data as Result<K> };
    } catch (error) {
      if (!owns(raw, epoch)) return null;
      update({ error, ...(!sent ? { blocked: true } : {}) });
      if (sent && definitiveTaskPackageFailure(error, session.scope.kind)) {
        try {
          const conflict = error instanceof ApiError && error.status === 412;
          if (conflict)
            persist(
              { ...parseRecovery(raw, session.scope), state: "conflict" },
              raw,
            );
          else persist(null, raw);
          update({ pending: null, conflict, rejected: true });
        } catch (failure) {
          update({ error: failure, blocked: true });
        }
      }
      return null;
    } finally {
      session.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  function eligible() {
    return (
      session.active &&
      current.current === session &&
      !session.running &&
      !session.snapshot.checking &&
      !session.snapshot.blocked
    );
  }
  async function run(
    command: TaskPackageCommandRequest,
  ): Promise<ApiResult<Result<K>> | null> {
    if (!eligible()) return null;
    if (session.recovery || session.snapshot.conflict) {
      update({
        error: new Error(
          session.snapshot.conflict
            ? "请先明确重新读取并采用服务器基准；清除提示不会解除修订冲突。"
            : "上次操作尚未取得可信回执，请先按完整原请求恢复。",
        ),
      });
      return null;
    }
    try {
      // This immutable JSON copy is exactly what is persisted and sent; later
      // form edits cannot alter the body, precondition or expected snapshot.
      const pending = validateTaskPackagePending(
        JSON.parse(JSON.stringify({ ...command, key: crypto.randomUUID() })),
        session.scope,
      );
      const raw = persist(
        { version: 1, scope: session.scope, state: "pending", pending },
        null,
      )!;
      session.running = true;
      update({
        pending: structuredClone(pending),
        busy: true,
        error: null,
        rejected: false,
      });
      // Persist the complete original request before any asynchronous work.
      return send(raw, session.epoch);
    } catch (error) {
      update({ error });
      try {
        if (sessionStorage.getItem(session.storageKey) !== null)
          update({ blocked: true });
      } catch {
        update({ blocked: true });
      }
      return null;
    }
  }
  async function retry(): Promise<ApiResult<Result<K>> | null> {
    if (
      !eligible() ||
      session.snapshot.conflict ||
      session.recovery?.state !== "pending" ||
      session.raw === null
    )
      return null;
    const epoch = session.epoch;
    if (!owns(session.raw, epoch)) return null;
    session.running = true;
    update({ busy: true, error: null });
    return send(session.raw, epoch);
  }
  async function adoptBasis(): Promise<ApiResult<
    Bid | TaskPackageTemplateView | PackageAuthoringTemplateView
  > | null> {
    if (!eligible() || session.recovery?.state === "pending") return null;
    if (session.scope.kind === "trigger_cancel") {
      update({
        error: new Error("触发输入固定；请核对原触发记录，不能替换取消条件。"),
      });
      return null;
    }
    const epoch = session.epoch,
      raw = session.raw;
    if (!owns(raw, epoch)) return null;
    session.running = true;
    update({ busy: true });
    try {
      const path = isTaskPackageCreationIdentity(session.scope.identity)
        ? `/bids/${session.scope.bidId}`
        : `/bids/${session.scope.bidId}/task-definitions/${session.scope.identity}`;
      const response = await api<unknown>(path);
      const data = await validateTaskPackageBasis(
        response.data,
        response.etag,
        session.scope,
      );
      if (!owns(raw, epoch)) return null;
      if (raw !== null) persist(null, raw);
      update({ conflict: false, error: null, rejected: false });
      return { ...response, data };
    } catch (error) {
      if (owns(raw, epoch)) update({ error });
      return null;
    } finally {
      session.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  return {
    pending: snapshot.pending,
    busy: snapshot.busy || snapshot.checking,
    error: snapshot.error,
    conflict: snapshot.conflict,
    blocked: snapshot.blocked,
    rejected: snapshot.rejected,
    run,
    retry,
    adoptBasis,
    clearError: () => {
      if (eligible()) update({ error: null });
    },
  };
}
