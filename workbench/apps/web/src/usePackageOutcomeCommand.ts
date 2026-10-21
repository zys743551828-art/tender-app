import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { PackageSubmissionView } from "./contracts";
import {
  definitiveOutcomeFailure,
  packageOutcomePath,
  validPendingOutcome,
  validateOutcomeAck,
  type PackageOutcomeScope,
  type PendingPackageOutcome,
} from "./packageOutcomeProtocol";
import {
  readOutcomeRecovery,
  writeOutcomeRecovery,
} from "./packageOutcomeRecovery";

/** One original command survives refresh, view closure, a lost response and a changed head. */
export function usePackageOutcomeCommand(
  scope: PackageOutcomeScope,
  submission: PackageSubmissionView,
  onSaved: (id: string) => void,
  onRejected: () => void,
) {
  const [initial] = useState(() => {
    try {
      return {
        pending: readOutcomeRecovery(scope, submission),
        error: null as unknown,
      };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState(initial.pending),
    [error, setError] = useState<unknown>(initial.error),
    [busy, setBusy] = useState(false),
    [rejected, setRejected] = useState(false);
  const active = useRef(false),
    running = useRef(false),
    record = useRef(initial.pending);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function send(p: PendingPackageOutcome, recovering: boolean) {
    if (
      !active.current ||
      running.current ||
      initial.error ||
      (!recovering && record.current)
    )
      return;
    if (!validPendingOutcome(p, scope, submission)) {
      setError(new Error("成绩请求与原整包实交不符，未发送。"));
      return;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    setRejected(false);
    try {
      writeOutcomeRecovery(scope, p);
      record.current = p;
      setPending(p);
      const result = await api<unknown>(packageOutcomePath(scope, p), {
        method: "POST",
        body: p.body,
        etag: p.etag,
        key: p.key,
      });
      const value = await validateOutcomeAck(
        result.data,
        result.etag,
        p,
        scope,
        submission,
      );
      if (!active.current) return;
      writeOutcomeRecovery(scope, null);
      record.current = null;
      setPending(null);
      onSaved(value.id);
    } catch (failure) {
      if (!active.current) return;
      setError(failure);
      if (definitiveOutcomeFailure(failure)) {
        try {
          writeOutcomeRecovery(scope, null);
          record.current = null;
          setPending(null);
          setRejected(true);
          onRejected();
        } catch (storageError) {
          setError(storageError);
        }
      }
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    pending,
    error,
    busy,
    rejected,
    blocked: !!initial.error,
    reviewed: () => setRejected(false),
    run: (p: PendingPackageOutcome) => send(p, false),
    retry: () =>
      record.current ? send(record.current, true) : Promise.resolve(),
  };
}
