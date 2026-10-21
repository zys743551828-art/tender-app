import { useEffect, useState } from "react";
import type { DraftView } from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalSame } from "./historicalImportProtocol";
import { readExactDraftStatus } from "./authoringExactProtocol";
import { useResource } from "./useResource";

/** Read the exact saved snapshot first. Ordinary drafts do not depend on the
 * optional B3 schema; a snapshot carrying exact sources must never silently
 * fall back to ordinary editing if that schema/status is unavailable. */
export function useAuthoringExactDraft(
  bidId: string,
  draftId: string,
  head?: DraftView,
) {
  const snapshot = useResource<unknown>(
    head ? `/bids/${bidId}/draft-snapshots/${head.snapshot_id}` : null,
  );
  const [read, setRead] = useState<{
    value: unknown;
    digest: string;
    bindings: unknown[] | null;
  } | null>(null);
  const [validationError, setValidationError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    setRead(null);
    setValidationError(null);
    if (!head || !snapshot.data)
      return () => {
        active = false;
      };
    void (async () => {
      const v = snapshot.data;
      if (
        !object(v) ||
        v.snapshot_id !== head.snapshot_id ||
        !sha(v.snapshot_digest) ||
        !Array.isArray(v.sections)
      )
        throw new Error(
          "保存快照身份尚未核验，原稿保留，暂不进行新编辑或构建。",
        );
      let bindings: unknown[] | null = null;
      if (Object.hasOwn(v, "authoring_exact_sections")) {
        const e = v.authoring_exact_sections;
        if (
          !object(e) ||
          !exactKeys(e, ["protocol", "sections", "digest"]) ||
          e.protocol !== "authoring-exact-snapshot/1" ||
          !Array.isArray(e.sections) ||
          !e.sections.length ||
          e.sections.length > 1000 ||
          e.digest !==
            (await jsonDigest({ protocol: e.protocol, sections: e.sections }))
        )
          throw new Error("快照中的固定整包来源资格无法核验，已暂停新操作。");
        bindings = e.sections;
      }
      if (active) setRead({ value: v, digest: v.snapshot_digest, bindings });
    })().catch((error: unknown) => {
      if (active) setValidationError(error);
    });
    return () => {
      active = false;
    };
  }, [head, snapshot.data]);
  const verified = read?.value === snapshot.data && !!read;
  const hasExact = verified && read.bindings !== null;
  const qualification = useResource<unknown>(
    hasExact
      ? `/bids/${bidId}/authoring/drafts/${draftId}/exact-qualification`
      : null,
  );
  let status: ReturnType<typeof readExactDraftStatus> | null = null,
    statusError: unknown = null;
  if (hasExact && qualification.data && head) {
    try {
      status = readExactDraftStatus(qualification.data, bidId, draftId);
      if (
        status.draft_revision !== head.revision ||
        status.snapshot_id !== head.snapshot_id ||
        status.snapshot_digest !== read.digest ||
        !historicalSame(status.exact_sections, read.bindings)
      )
        throw new Error(
          "来源资格对应另一份草稿修订，未替换当前正文或生成版本。",
        );
    } catch (error) {
      status = null;
      statusError = error;
    }
  }
  const snapshotReady =
    verified && !snapshot.loading && !snapshot.error && !validationError;
  const statusReady =
    !!status && !qualification.loading && !qualification.error && !statusError;
  return {
    hasExact,
    status,
    checking:
      !!head &&
      (!snapshotReady || (hasExact && !statusReady)) &&
      !snapshot.error &&
      !snapshot.unavailable &&
      !validationError &&
      !qualification.error &&
      !qualification.unavailable &&
      !statusError,
    ordinaryEditBlocked: !!head && (!snapshotReady || hasExact),
    buildBlocked:
      !!head &&
      (!snapshotReady ||
        (hasExact && (!statusReady || !status?.build_available))),
    error:
      validationError ?? snapshot.error ?? statusError ?? qualification.error,
    unavailable:
      snapshot.unavailable || (hasExact && qualification.unavailable),
    refresh: async () => {
      await snapshot.reload();
      if (hasExact) await qualification.reload();
    },
  };
}
