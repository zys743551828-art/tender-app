import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  exactKeys,
  executionId as uuid,
  recordObject as object,
} from "./executionInputValidation";
import {
  verifyTextEditACK,
  verifyTextEditBase,
  verifyTextEditPending,
  type ExactTextEditBase,
  type ExactTextEditPending,
  type ExactTextEditScope,
} from "./authoringExactTextEditProtocol";
import type { AuthoringExactTextEditRequest } from "./contracts";

type Recovery = {
  version: 1;
  scope: ExactTextEditScope;
  state: "pending" | "conflict";
  pending: ExactTextEditPending;
};
type Snapshot = {
  busy: boolean;
  pending: boolean;
  conflict: boolean;
  blocked: boolean;
  error: unknown;
};
const limit = 4 * 1024 * 1024;
const damaged = () =>
  new Error("原文字修订的本地恢复记录无法核对，记录继续保留，暂停新保存。");
export const exactTextEditStorageKey = (s: ExactTextEditScope) =>
  recordedCommandStorageKey(
    "authoring-exact-text-edit",
    s.memberId,
    s.bidId,
    s.draftId,
  );
function read(raw: string, scope: ExactTextEditScope): Recovery {
  if (new TextEncoder().encode(raw).length > limit) throw damaged();
  const v: unknown = JSON.parse(raw);
  if (
    !object(v) ||
    !exactKeys(v, ["version", "scope", "state", "pending"]) ||
    v.version !== 1 ||
    !object(v.scope) ||
    !exactKeys(v.scope, ["memberId", "bidId", "draftId"]) ||
    v.scope.memberId !== scope.memberId ||
    v.scope.bidId !== scope.bidId ||
    v.scope.draftId !== scope.draftId ||
    !["pending", "conflict"].includes(String(v.state)) ||
    !object(v.pending) ||
    !exactKeys(v.pending, ["key", "etag", "base", "body"]) ||
    !uuid(v.pending.key) ||
    typeof v.pending.etag !== "string" ||
    !object(v.pending.base) ||
    !object(v.pending.body) ||
    typeof v.pending.body.replacement_text !== "string" ||
    typeof v.pending.body.reason !== "string"
  )
    throw damaged();
  return v as unknown as Recovery;
}

/** A durable original request survives current-head changes and unknown outcomes.
 * No mount, capability refresh or reconnection automatically sends it. */
export function useExactAuthoringTextEdit(scope: ExactTextEditScope) {
  const { memberId, bidId, draftId } = scope;
  const session = useMemo(() => {
    const s = {
      scope: { memberId, bidId, draftId },
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
      if (![memberId, bidId, draftId].every(uuid)) throw damaged();
      s.key = exactTextEditStorageKey(s.scope);
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
  }, [memberId, bidId, draftId]);
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
      if (sessionStorage.getItem(session.key) === raw) return true;
    } catch {
      /* fail closed */
    }
    update({ blocked: true, error: damaged() });
    return false;
  }
  function persist(value: Recovery | null, expected: string | null) {
    if (sessionStorage.getItem(session.key) !== expected) throw damaged();
    const raw = value ? JSON.stringify(value) : null;
    if (raw && new TextEncoder().encode(raw).length > limit)
      throw new Error("原稿超出本机恢复容量，尚未发送文字修订；请保留原稿。");
    if (raw === null) sessionStorage.removeItem(session.key);
    else sessionStorage.setItem(session.key, raw);
    if (sessionStorage.getItem(session.key) !== raw) throw damaged();
    session.raw = raw;
    session.recovery = value;
    return raw;
  }
  async function send(raw: string, epoch: number) {
    let sent = false,
      acknowledged = false;
    try {
      const recovery = read(raw, session.scope);
      if (recovery.state !== "pending") throw damaged();
      const pending = await verifyTextEditPending(
        recovery.pending,
        session.scope,
      );
      if (!owns(raw, epoch)) return null;
      sent = true;
      const response = await api<unknown>(
        `/bids/${bidId}/authoring/drafts/${draftId}/exact-text-edits`,
        {
          method: "POST",
          body: pending.body,
          etag: pending.etag,
          key: pending.key,
        },
      );
      acknowledged = true;
      const data = await verifyTextEditACK(
        response.data,
        response.etag,
        pending,
        session.scope,
      );
      if (!owns(raw, epoch)) return null;
      persist(null, raw);
      update({ pending: false, conflict: false, error: null });
      return { ...response, data };
    } catch (error) {
      if (!owns(raw, epoch)) return null;
      update({ error, ...(!sent ? { blocked: true } : {}) });
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
    base: ExactTextEditBase,
    body: AuthoringExactTextEditRequest,
    etag: string,
  ) {
    if (!ready() || session.recovery) return null;
    const epoch = session.epoch;
    session.running = true;
    update({ busy: true, error: null });
    try {
      const pending = await verifyTextEditPending(
        {
          key: crypto.randomUUID(),
          etag,
          base: structuredClone(base),
          body: structuredClone(body),
        },
        session.scope,
      );
      if (!live(epoch)) return null;
      const raw = persist(
        { version: 1, scope: session.scope, state: "pending", pending },
        null,
      )!;
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
  async function acknowledgeConflict(base: ExactTextEditBase) {
    if (!ready() || session.recovery?.state !== "conflict" || !session.raw)
      return null;
    const raw = session.raw,
      epoch = session.epoch;
    try {
      await verifyTextEditBase(base, session.scope);
      const old = await verifyTextEditPending(
        session.recovery.pending,
        session.scope,
      );
      if (
        base.section.id !== old.base.section.id ||
        base.status.draft_revision <= old.base.status.draft_revision ||
        !owns(raw, epoch)
      )
        return null;
      persist(null, raw);
      update({ conflict: false, error: null });
      return old.body;
    } catch (error) {
      update({ error });
      return null;
    }
  }
  return {
    ...snapshot,
    original: session.recovery?.pending ?? null,
    run,
    retry,
    acknowledgeConflict,
  };
}
