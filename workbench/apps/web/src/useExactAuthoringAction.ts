import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type ApiResult } from "./api";
import {
  exactKeys,
  executionId as uuid,
  recordObject as object,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  verifyExactAction,
  verifyExactActionACK,
  verifyExactCandidateInput,
  exactActionSaved,
  type ExactActionDecision,
  type ExactPackageAction,
} from "./authoringExactProtocol";
import type { VerifiedAuthoringInput } from "./packageAuthoringInputProtocol";

type Scope = { memberId: string; actionId: string };
type Pending = {
  key: string;
  etag: string;
  decision: ExactActionDecision;
  original: ExactPackageAction | null;
  targetDraftId: string | null;
};
type Recovery = {
  version: 1;
  scope: Scope;
  state: "pending" | "conflict";
  pending: Pending;
};
type Snapshot = {
  busy: boolean;
  pending: boolean;
  conflict: boolean;
  blocked: boolean;
  error: unknown;
};
const damaged = () =>
  new Error(
    "候选操作的原恢复记录无法核对，已保留记录并暂停新操作；请先核对服务器上的实际处理历史。",
  );
const limit = 4 * 1024 * 1024;
export const exactActionStorageKey = (scope: Scope) =>
  recordedCommandStorageKey("assistant-action", scope.memberId, scope.actionId);
function read(raw: string, scope: Scope): Recovery {
  const value: unknown = JSON.parse(raw);
  if (new TextEncoder().encode(raw).length > limit || !object(value))
    throw damaged();
  // B2 used the shared action command record. Keep its exact old request/key
  // and bind it to a verified live action before replaying it after upgrade.
  if (!Object.hasOwn(value, "version")) {
    if (
      !exactKeys(value, [
        "path",
        "body",
        "etag",
        "key",
        ...(Object.hasOwn(value, "method") ? ["method"] : []),
      ]) ||
      value.path !== `/assistant/actions/${scope.actionId}/resolve` ||
      (value.method !== undefined && value.method !== "POST") ||
      !object(value.body) ||
      !exactKeys(value.body, ["decision"]) ||
      !["confirm", "reject"].includes(String(value.body.decision)) ||
      !uuid(value.key) ||
      typeof value.etag !== "string" ||
      !new RegExp(`^"assistant-action:${scope.actionId}:[0-9a-f]{64}"$`).test(
        value.etag,
      )
    )
      throw damaged();
    return {
      version: 1,
      scope,
      state: "pending",
      pending: {
        key: value.key,
        etag: value.etag,
        decision: value.body.decision as ExactActionDecision,
        original: null,
        targetDraftId: null,
      },
    };
  }
  if (
    !exactKeys(value, ["version", "scope", "state", "pending"]) ||
    value.version !== 1 ||
    !object(value.scope) ||
    !exactKeys(value.scope, ["memberId", "actionId"]) ||
    value.scope.memberId !== scope.memberId ||
    value.scope.actionId !== scope.actionId ||
    !["pending", "conflict"].includes(String(value.state)) ||
    !object(value.pending)
  )
    throw damaged();
  const p = value.pending;
  if (
    !exactKeys(p, [
      "key",
      "etag",
      "decision",
      "original",
      ...(Object.hasOwn(p, "targetDraftId") ? ["targetDraftId"] : []),
    ]) ||
    !uuid(p.key) ||
    !["confirm", "reject"].includes(String(p.decision)) ||
    typeof p.etag !== "string" ||
    !new RegExp(`^"assistant-action:${scope.actionId}:[0-9a-f]{64}"$`).test(
      p.etag,
    ) ||
    (p.original !== null &&
      (!object(p.original) || p.original.action_id !== scope.actionId)) ||
    (p.targetDraftId !== undefined &&
      p.targetDraftId !== null &&
      !uuid(p.targetDraftId))
  )
    throw damaged();
  return {
    ...value,
    pending: { ...p, targetDraftId: p.targetDraftId ?? null },
  } as unknown as Recovery;
}

/** A durable request owns its original ETag, body and key. Current reads are
 * never substituted into an uncertain request, including after account change. */
export function useExactAuthoringAction(scope: Scope) {
  const { memberId, actionId } = scope;
  const session = useMemo(() => {
    const s = {
      scope: { memberId, actionId },
      key: "",
      raw: null as string | null,
      recovery: null as Recovery | null,
      active: false,
      running: false,
      epoch: 0,
      snapshot: {
        busy: false,
        pending: false,
        conflict: false,
        blocked: false,
        error: null,
      } as Snapshot,
    };
    try {
      if (!uuid(memberId) || !uuid(actionId)) throw damaged();
      s.key = exactActionStorageKey(s.scope);
      s.raw = sessionStorage.getItem(s.key);
      if (s.raw) {
        s.recovery = read(s.raw, s.scope);
        s.snapshot.pending = s.recovery.state === "pending";
        s.snapshot.conflict = s.recovery.state === "conflict";
      }
    } catch (error) {
      s.snapshot.blocked = true;
      s.snapshot.error = error;
    }
    return s;
  }, [memberId, actionId]);
  const current = useRef(session);
  current.current = session;
  const [rendered, render] = useState({ session, snapshot: session.snapshot });
  const snapshot =
    rendered.session === session ? rendered.snapshot : session.snapshot;
  useEffect(() => {
    session.active = true;
    ++session.epoch;
    return () => {
      session.active = false;
      ++session.epoch;
    };
  }, [session]);
  function live(epoch: number) {
    return (
      session.active && current.current === session && epoch === session.epoch
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
      if (sessionStorage.getItem(session.key) === raw) return true;
    } catch {
      update({
        blocked: true,
        error: new Error(
          "本机暂时无法核对原操作恢复记录，原请求保留，暂停处理回执。",
        ),
      });
      return false;
    }
    update({
      blocked: true,
      error: new Error("登录或原恢复记录已变化，停止接收旧操作回执。"),
    });
    return false;
  }
  function persist(value: Recovery | null, expected: string | null) {
    if (sessionStorage.getItem(session.key) !== expected) throw damaged();
    const raw = value ? JSON.stringify(value) : null;
    if (raw && new TextEncoder().encode(raw).length > limit)
      throw new Error(
        "完整候选超过本机恢复记录容量，尚未发送采纳操作；请保留原稿。",
      );
    if (raw === null) sessionStorage.removeItem(session.key);
    else sessionStorage.setItem(session.key, raw);
    if (sessionStorage.getItem(session.key) !== raw) throw damaged();
    session.raw = raw;
    session.recovery = value;
    return raw;
  }
  async function send(
    raw: string,
    epoch: number,
  ): Promise<ApiResult<ExactPackageAction> | null> {
    let sent = false,
      acknowledged = false;
    try {
      const recovery = read(raw, session.scope),
        p = recovery.pending;
      if (recovery.state !== "pending") throw damaged();
      let original = p.original;
      if (original) await verifyExactAction(original, p.etag, actionId);
      else {
        const current = await api<unknown>(`/assistant/actions/${actionId}`);
        original = await verifyExactAction(
          current.data,
          current.etag,
          actionId,
        );
      }
      if (!owns(raw, epoch)) return null;
      sent = true;
      const response = await api<unknown>(
        `/assistant/actions/${actionId}/resolve`,
        {
          method: "POST",
          body: { decision: p.decision },
          etag: p.etag,
          key: p.key,
        },
      );
      acknowledged = true;
      const data = await verifyExactActionACK(
        response.data,
        response.etag,
        original,
      );
      if (
        p.targetDraftId &&
        exactActionSaved(data)?.draft_id !== undefined &&
        exactActionSaved(data)?.draft_id !== p.targetDraftId
      )
        throw new Error("采纳回执指向另一份正文草稿，原候选与请求均保留。");
      if (!owns(raw, epoch)) return null;
      persist(null, raw);
      update({ pending: false, conflict: false, error: null });
      return { ...response, data };
    } catch (error) {
      if (!owns(raw, epoch)) return null;
      update({ error, ...(!sent ? { blocked: true } : {}) });
      // An untrusted 2xx, unknown conflict, 401/403, service error or uncertain
      // outcome always retains the original request. Only a real CAS rejection
      // may move to an explicitly acknowledged conflict state.
      if (
        sent &&
        !acknowledged &&
        error instanceof ApiError &&
        error.status === 412 &&
        [
          "REVISION_CONFLICT",
          "DRAFT_REVISION_CONFLICT",
          "SECTION_REVISION_CONFLICT",
        ].includes(error.code)
      ) {
        try {
          persist({ ...read(raw, session.scope), state: "conflict" }, raw);
          update({ pending: false, conflict: true });
        } catch (failure) {
          update({ blocked: true, error: failure });
        }
      }
      return null;
    } finally {
      session.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  function ready() {
    return (
      session.active &&
      current.current === session &&
      !session.running &&
      !session.snapshot.blocked
    );
  }
  async function run(
    action: ExactPackageAction,
    etag: string,
    decision: ExactActionDecision,
    input: VerifiedAuthoringInput | null = null,
  ) {
    if (!ready() || session.recovery) return null;
    session.running = true;
    update({ busy: true, error: null });
    const epoch = session.epoch;
    try {
      await verifyExactAction(action, etag, actionId);
      if (decision === "confirm") {
        if (!input)
          throw new Error("固定编写输入尚未核验，尚未发送新采纳请求。");
        await verifyExactCandidateInput(input, action);
      }
      if (!live(epoch) || action.state !== "pending") return null;
      const recovery: Recovery = {
        version: 1,
        scope: session.scope,
        state: "pending",
        pending: {
          key: crypto.randomUUID(),
          etag,
          decision,
          original: structuredClone(action),
          targetDraftId:
            input?.manifest.selection.target_section.draft_id ?? null,
        },
      };
      const raw = persist(recovery, null)!;
      update({ pending: true });
      return await send(raw, epoch);
    } catch (error) {
      update({ error });
      return null;
    } finally {
      session.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  async function retry() {
    if (!ready() || session.recovery?.state !== "pending" || !session.raw)
      return null;
    const epoch = session.epoch;
    if (!owns(session.raw, epoch)) return null;
    session.running = true;
    update({ busy: true, error: null });
    return send(session.raw, epoch);
  }
  async function acknowledgeConflict(action: ExactPackageAction, etag: string) {
    if (!ready() || session.recovery?.state !== "conflict" || !session.raw)
      return false;
    const raw = session.raw,
      epoch = session.epoch;
    try {
      await verifyExactAction(action, etag, actionId);
      if (!owns(raw, epoch)) return false;
      persist(null, raw);
      update({ conflict: false, error: null });
      return true;
    } catch (error) {
      update({ error });
      return false;
    }
  }
  return { ...snapshot, run, retry, acknowledgeConflict };
}
