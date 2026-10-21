import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageReviewHumanDecisionCurrent,
  PackageReviewHumanDecisionView,
} from "./contracts";
import type { PackageReviewRow } from "./packageReviewProtocol";
import type {
  PackageReviewDecisionProps,
  PackageReviewDecisionState,
  PendingPackageReviewDecision,
} from "./packageReviewDecisionProtocol";
import {
  packageReviewDecisionQuotes,
  packageReviewDecisionsPath,
  validatePackageReviewDecision,
  validatePackageReviewDecisionCurrent,
} from "./packageReviewDecisionProtocol";
import type {
  PackageReviewDecisionDraft,
  PackageReviewDecisionRecord,
} from "./packageReviewDecisionRecovery";
import {
  loadPackageReviewDecisionRecord,
  storePackageReviewDecisionRecord,
} from "./packageReviewDecisionRecovery";
import { definitelyRejectedPackageReview } from "./packageReviewRecovery";
import { frozenManifestDigest } from "./packageFrozenInput";
import { usePackageScopeGuard } from "./packageScopeGuard";

type Head = PackageReviewHumanDecisionCurrent["items"][number]["current"];
const emptyDraft: PackageReviewDecisionDraft = { reason: "", quoteIndexes: [] };

export function usePackageReviewDecisions(p: PackageReviewDecisionProps) {
  const [loaded] = useState(() => {
    try {
      return { record: loadPackageReviewDecisionRecord(p), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<PackageReviewDecisionRecord | null>(
      loaded.record,
    ),
    recordRef = useRef(record);
  const [heads, setHeads] = useState<PackageReviewHumanDecisionCurrent | null>(
      null,
    ),
    [receipt, setReceipt] = useState<PackageReviewHumanDecisionView | null>(
      null,
    ),
    [reading, setReading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    writing = useRef(false),
    readingRef = useRef(false),
    ticket = useRef(0),
    headsRef = useRef<PackageReviewHumanDecisionCurrent | null>(null),
    observedHeads = useRef(new Map<string, NonNullable<Head>>());
  usePackageScopeGuard(`decisions:${p.scope.memberId}:${p.run.id}`, {
    busy,
    pending: !!record?.pending || !!loaded.error,
    dirty:
      !record?.pending &&
      Object.values(record?.drafts ?? {}).some(
        (value) => !!value.reason || !!value.quoteIndexes.length,
      ),
  });
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function updateRecord(next: PackageReviewDecisionRecord, required = true) {
    // Before a POST, persistence must succeed. Draft editing can remain in memory if storage is full.
    if (required) storePackageReviewDecisionRecord(next);
    recordRef.current = next;
    setRecord(next);
    if (!required) storePackageReviewDecisionRecord(next);
  }
  function remember(requirementId: string, head: NonNullable<Head>) {
    const previous = observedHeads.current.get(requirementId);
    if (!previous || previous.sequence_no < head.sequence_no)
      observedHeads.current.set(requirementId, head);
  }
  async function readCurrent(preserveError = false) {
    if (!active.current || writing.current || readingRef.current) return;
    const request = ++ticket.current;
    readingRef.current = true;
    setReading(true);
    if (!preserveError) setError(null);
    try {
      const { data } = await api<unknown>(packageReviewDecisionsPath(p));
      const received = await validatePackageReviewDecisionCurrent(data, p.run);
      if (!active.current || request !== ticket.current) return;
      for (const item of received.items) {
        const before = observedHeads.current.get(item.requirement_id),
          next = item.current;
        if (
          before &&
          (!next ||
            next.sequence_no < before.sequence_no ||
            (next.sequence_no === before.sequence_no &&
              (next.id !== before.id || next.digest !== before.digest)))
        )
          throw new Error(
            "人工状态返回了早于已确认记录的版本，保留原记录，请重读当前状态。",
          );
      }
      received.items.forEach((item) => {
        if (item.current) remember(item.requirement_id, item.current);
      });
      headsRef.current = received;
      setHeads(received);
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        readingRef.current = false;
        setReading(false);
      }
    }
  }
  function draft(row: PackageReviewRow) {
    return recordRef.current?.drafts[row.requirement_id] ?? emptyDraft;
  }
  function changeDraft(
    row: PackageReviewRow,
    next: PackageReviewDecisionDraft,
  ) {
    const previous = recordRef.current;
    if (!active.current || !previous || previous.pending || writing.current)
      return;
    if (
      Array.from(next.reason).length > 2000 ||
      next.quoteIndexes.length > 40
    ) {
      setError(new Error("人工理由最多 2000 字，原引用最多选择 40 条。"));
      return;
    }
    try {
      updateRecord(
        {
          ...previous,
          drafts: { ...previous.drafts, [row.requirement_id]: next },
        },
        false,
      );
    } catch (failure) {
      setError(failure);
    }
  }
  async function save(
    row: PackageReviewRow,
    state: PackageReviewDecisionState,
    recover = false,
  ) {
    const previous = recordRef.current;
    if (
      !active.current ||
      writing.current ||
      !previous ||
      (!recover && (previous.pending || readingRef.current))
    )
      return;
    let pending: PendingPackageReviewDecision;
    if (recover) {
      if (!previous.pending) return;
      pending = previous.pending;
      row = p.run.result!.manifest.matrix.find(
        (item) => item.requirement_id === pending.requirementId,
      )!;
    } else {
      const item = headsRef.current?.items.find(
          (item) => item.requirement_id === row.requirement_id,
        ),
        d = draft(row);
      if (!item) {
        setError(new Error("请先读取当前人工状态，再保存此项判断。"));
        return;
      }
      if (!d.reason.trim()) {
        setError(new Error("请填写本次人工判断的理由。"));
        return;
      }
      if (item.current?.sequence_no === Number.MAX_SAFE_INTEGER) {
        setError(new Error("此项人工版本已到上限，请核对服务器记录。"));
        return;
      }
      const quotes = packageReviewDecisionQuotes(row);
      pending = {
        key: crypto.randomUUID(),
        requirementId: row.requirement_id,
        previousSequence: item.current?.sequence_no ?? null,
        body: {
          result_digest: p.run.result!.digest,
          row_digest: item.row_digest,
          expected_head: item.current
            ? { id: item.current.id, digest: item.current.digest }
            : null,
          state,
          reason: d.reason.trim(),
          selected_quotes: d.quoteIndexes.map((index) => quotes[index]),
        },
      };
    }
    writing.current = true;
    setBusy(true);
    setError(null);
    const request = ++ticket.current;
    readingRef.current = false;
    setReading(false);
    let refresh = false;
    try {
      updateRecord({ ...previous, pending });
      if (pending.body.row_digest !== (await frozenManifestDigest(row)))
        throw new Error(
          "原人工请求的条款摘要不符，未发送其他版本；请保留恢复记录核对。",
        );
      if (!active.current || request !== ticket.current) return;
      const { data } = await api<unknown>(
        packageReviewDecisionsPath(p, pending.requirementId),
        { method: "POST", key: pending.key, body: pending.body },
      );
      const received = await validatePackageReviewDecision(
        data,
        p.run,
        row,
        pending,
        p.scope.memberId,
      );
      if (!active.current || request !== ticket.current) return;
      const m = received.manifest;
      setReceipt(received);
      remember(m.requirement_id, {
        id: m.id,
        digest: received.digest,
        sequence_no: m.sequence_no,
        actor_id: m.actor_id,
        created_at: m.created_at,
        state: m.state,
        reason: m.reason,
      });
      // An exact replay may be an old receipt. It is never adopted as the current head.
      headsRef.current = null;
      setHeads(null);
      const drafts = { ...recordRef.current!.drafts };
      delete drafts[pending.requirementId];
      updateRecord({ ...recordRef.current!, pending: null, drafts });
      refresh = true;
    } catch (failure) {
      if (active.current && request === ticket.current) {
        if (definitelyRejectedPackageReview(failure)) {
          headsRef.current = null;
          setHeads(null);
          try {
            updateRecord({ ...recordRef.current!, pending: null });
            refresh = true;
          } catch (storageError) {
            setError(storageError);
            return;
          }
        }
        setError(failure);
      }
    } finally {
      if (active.current && request === ticket.current) {
        writing.current = false;
        setBusy(false);
      }
      if (refresh && active.current && request === ticket.current)
        void readCurrent(true);
    }
  }
  function recover() {
    const pending = recordRef.current?.pending;
    if (!pending) return;
    const row = p.run.result!.manifest.matrix.find(
      (item) => item.requirement_id === pending.requirementId,
    );
    if (row) void save(row, pending.body.state, true);
  }
  return {
    record,
    heads,
    receipt,
    reading,
    busy,
    error: error ?? loaded.error,
    initialError: loaded.error,
    readCurrent,
    draft,
    changeDraft,
    save,
    recover,
  };
}
