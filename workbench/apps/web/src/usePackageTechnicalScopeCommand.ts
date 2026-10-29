import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import {
  definitiveTechnicalFailure,
  technicalScopePath,
  validateTechnicalACK,
  verifyTechnicalPending,
  type TechnicalCommand,
  type TechnicalPending,
  type TechnicalScope,
} from "./packageTechnicalScopeProtocol";
import {
  readTechnicalRecovery,
  writeTechnicalRecovery,
} from "./packageTechnicalScopeRecovery";

/** A verified acknowledgement, rather than a successful HTTP status, releases the request. */
export function usePackageTechnicalScopeCommand(scope: TechnicalScope) {
  const [initial] = useState(() => {
    try {
      return { pending: readTechnicalRecovery(scope), error: null as unknown };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState(initial.pending);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(initial.error);
  const [result, setResult] = useState<PackageTechnicalScopeView | null>(null);
  const record = useRef(pending),
    running = useRef(false),
    active = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const path = `${technicalScopePath(scope)}/technical-scopes`;
  function persist(value: TechnicalPending | null) {
    writeTechnicalRecovery(scope, value);
    record.current = value;
    if (active.current) setPending(value);
  }
  async function send(value: TechnicalPending) {
    if (!active.current || running.current || initial.error) return null;
    if (!supportsApi("POST", path)) {
      setError(new Error("当前服务尚未开放技术范围保存；原请求与输入保留。"));
      return null;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await verifyTechnicalPending(value, scope);
      if (!active.current) return null;
      persist(value);
      const response = await api<unknown>(path, {
        method: "POST",
        body: value.body,
        etag: value.etag,
        key: value.key,
      });
      if (!active.current) return null;
      const ack = await validateTechnicalACK(
        response.data,
        response.etag,
        value,
        scope,
      );
      if (!active.current) return null;
      persist(null);
      setResult(ack.scope);
      return ack.scope;
    } catch (failure) {
      if (active.current) {
        if (definitiveTechnicalFailure(failure)) {
          try {
            persist(null);
          } catch (storageFailure) {
            setError(storageFailure);
            return null;
          }
        }
        setError(failure);
      }
      return null;
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    pending,
    busy,
    error,
    result,
    blocked: !!initial.error,
    async save(value: TechnicalCommand) {
      if (record.current || running.current || initial.error) return null;
      return send({ ...structuredClone(value), key: crypto.randomUUID() });
    },
    retry() {
      return record.current ? send(record.current) : Promise.resolve(null);
    },
  };
}
