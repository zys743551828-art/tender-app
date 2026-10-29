import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { jsonDigest } from "./editorSchema";
import { validateAuthoringInputRequest } from "./packageAuthoringInputProtocol";
import {
  captureCommandKey,
  captureDefinitelyRejected,
  captureRequestPath,
  readCaptureRecovery,
  validateCaptureAck,
  verifyCaptureRecovery,
  type CaptureCommandScope,
  type CaptureRecovery,
} from "./authoringCaptureCommandProtocol";

type Status = {
  pending: CaptureRecovery | null;
  busy: boolean;
  checking: boolean;
  error: unknown;
  blocked: boolean;
  rejected: boolean;
};
type Session = {
  scope: CaptureCommandScope;
  storageKey: string;
  raw: string | null;
  recovery: CaptureRecovery | null;
  status: Status;
  active: boolean;
  running: boolean;
  epoch: number;
};
const changed = () =>
  new Error("成员、采集范围或原恢复记录已经变化，迟到回执没有写回旧会话。");
function initial(scope: CaptureCommandScope): Session {
  const s: Session = {
    scope,
    storageKey: "",
    raw: null,
    recovery: null,
    active: false,
    running: false,
    epoch: 0,
    status: {
      pending: null,
      busy: false,
      checking: false,
      error: null,
      blocked: false,
      rejected: false,
    },
  };
  try {
    s.storageKey = captureCommandKey(scope);
    s.raw = sessionStorage.getItem(s.storageKey);
    if (s.raw !== null) {
      s.recovery = readCaptureRecovery(s.raw, scope);
      s.status.pending = s.recovery;
      s.status.checking = true;
      s.status.rejected = s.recovery.state === "rejected";
    }
  } catch (error) {
    s.status = { ...s.status, blocked: true, error };
  }
  return s;
}
/** Independent B1 recovery. The original body, actor, project, key and ACK are all bound. */
export function useAuthoringCaptureCommand(scope: CaptureCommandScope) {
  const { memberId, bidId } = scope;
  const s = useMemo(() => initial({ memberId, bidId }), [memberId, bidId]);
  const current = useRef(s);
  current.current = s;
  const [rendered, render] = useState({ session: s, status: s.status });
  const status = rendered.session === s ? rendered.status : s.status;
  function live(epoch: number) {
    return s.active && current.current === s && s.epoch === epoch;
  }
  function update(patch: Partial<Status>) {
    s.status = { ...s.status, ...patch };
    if (s.active && current.current === s)
      render({ session: s, status: s.status });
  }
  function owns(raw: string | null, epoch: number) {
    if (!live(epoch)) return false;
    try {
      if (sessionStorage.getItem(s.storageKey) === raw) return true;
    } catch {
      /* An unreadable record cannot authorize sending or cleanup. */
    }
    update({ blocked: true, error: changed() });
    return false;
  }
  function persist(value: CaptureRecovery | null, expected: string | null) {
    if (sessionStorage.getItem(s.storageKey) !== expected) throw changed();
    const raw = value === null ? null : JSON.stringify(value);
    if (raw !== null && new TextEncoder().encode(raw).length > 2 * 1024 * 1024)
      throw new Error("完整采集请求超过本机恢复记录预算，未发送。");
    if (raw === null) sessionStorage.removeItem(s.storageKey);
    else sessionStorage.setItem(s.storageKey, raw);
    if (sessionStorage.getItem(s.storageKey) !== raw)
      throw new Error("浏览器没有可靠保存完整原请求，未确认成功。");
    s.raw = raw;
    s.recovery = value;
    return raw;
  }
  useEffect(() => {
    s.active = true;
    const epoch = ++s.epoch;
    render({ session: s, status: s.status });
    if (s.recovery && !s.status.blocked) {
      const raw = s.raw;
      void verifyCaptureRecovery(s.recovery)
        .then(() => {
          if (!s.active || current.current !== s || epoch !== s.epoch) return;
          if (sessionStorage.getItem(s.storageKey) !== raw) throw changed();
          s.status = { ...s.status, checking: false };
          render({ session: s, status: s.status });
        })
        .catch((error: unknown) => {
          if (!s.active || current.current !== s || epoch !== s.epoch) return;
          s.status = { ...s.status, checking: false, blocked: true, error };
          render({ session: s, status: s.status });
        });
    }
    return () => {
      s.active = false;
      ++s.epoch;
    };
  }, [s]);
  async function send(raw: string, epoch: number) {
    let sent = false;
    try {
      const recovery = await verifyCaptureRecovery(
        readCaptureRecovery(raw, s.scope),
      );
      if (recovery.state !== "pending") throw changed();
      if (!owns(raw, epoch)) return null;
      const r = recovery.request;
      sent = true;
      const response = await api<unknown>(r.path, {
        method: r.method,
        body: r.body,
        etag: r.etag,
        key: r.key,
      });
      const input = await validateCaptureAck(response, recovery);
      if (!owns(raw, epoch)) return null;
      persist(null, raw);
      update({ pending: null, error: null, rejected: false });
      return input;
    } catch (error) {
      if (!owns(raw, epoch)) return null;
      update({ error, ...(!sent ? { blocked: true } : {}) });
      if (sent && captureDefinitelyRejected(error)) {
        try {
          const value: CaptureRecovery = {
            ...readCaptureRecovery(raw, s.scope),
            state: "rejected",
          };
          persist(value, raw);
          update({ pending: value, rejected: true });
        } catch (failure) {
          update({ blocked: true, error: failure });
        }
      }
      return null;
    } finally {
      s.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  function eligible() {
    return (
      s.active &&
      current.current === s &&
      !s.running &&
      !s.status.checking &&
      !s.status.blocked
    );
  }
  async function run(body: unknown) {
    if (!eligible() || s.recovery) return null;
    s.running = true;
    update({ busy: true, error: null });
    const epoch = s.epoch;
    try {
      const request = {
        method: "POST" as const,
        path: captureRequestPath(bidId),
        etag: "" as const,
        key: crypto.randomUUID(),
        body: validateAuthoringInputRequest(JSON.parse(JSON.stringify(body))),
      };
      const recovery: CaptureRecovery = {
        version: 1,
        scope: s.scope,
        state: "pending",
        request,
        request_digest: await jsonDigest({ scope: s.scope, request }),
      };
      if (!owns(null, epoch)) return null;
      const raw = persist(recovery, null)!;
      update({ pending: recovery, rejected: false });
      return await send(raw, epoch);
    } catch (error) {
      if (live(epoch)) update({ error, blocked: true });
      return null;
    } finally {
      s.running = false;
      if (live(epoch)) update({ busy: false });
    }
  }
  async function retry() {
    if (!eligible() || s.recovery?.state !== "pending" || s.raw === null)
      return null;
    const epoch = s.epoch;
    if (!owns(s.raw, epoch)) return null;
    s.running = true;
    update({ busy: true, error: null });
    return send(s.raw, epoch);
  }
  function acknowledgeRejection() {
    if (
      !eligible() ||
      s.recovery?.state !== "rejected" ||
      !owns(s.raw, s.epoch)
    )
      return false;
    try {
      persist(null, s.raw);
      update({ pending: null, rejected: false, error: null });
      return true;
    } catch (error) {
      update({ blocked: true, error });
      return false;
    }
  }
  return {
    ...status,
    busy: status.busy || status.checking,
    run,
    retry,
    acknowledgeRejection,
  };
}
