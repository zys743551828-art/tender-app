import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  BidPackageStoredView,
  PackageRequirementInventoryPage,
  PackageRequirementInventoryView,
  PackageRuleCorrectionPreviewView,
  PackageRuleCorrectionRequest,
} from "./contracts";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import { PackageRuleCorrectionDiff } from "./PackageRuleCorrectionDiff";
import {
  PackageRuleCorrectionForm,
  type CorrectionDraftChange,
} from "./PackageRuleCorrectionForm";
import { PackageRuleCorrectionHistory } from "./PackageRuleCorrectionHistory";
import {
  correctionInventoryMatches,
  sameCorrectionValue,
  validateCorrectionApplied,
  validateCorrectionPreview,
} from "./packageRuleCorrectionProtocol";
import {
  correctionBase,
  correctionEtag,
  correctionInventoryPath,
  correctionPath,
  definitiveCorrectionFailure,
  readCorrectionRecovery,
  validCorrectionRequest,
  writeCorrectionRecovery,
  type CorrectionRecovery,
  type CorrectionScope,
  type PendingCorrection,
} from "./packageRuleCorrectionRecovery";
import "./PackageRuleCorrections.css";

type Props = {
  bidId: string;
  memberId: string;
  packageView: BidPackageStoredView;
  inventory: PackageRequirementInventoryView | null;
  inventoryEtag: string | null;
  currentInventoryId: string | null;
  currentKnown: boolean;
  disabled?: boolean;
  onPendingChange: (value: boolean) => void;
  onDirtyChange?: (value: boolean) => void;
  onApplied: (inventoryId: string) => void;
  onRefresh: () => void;
};
function DraftCorrection({
  scope,
  inventory,
  etag,
  disabled,
  current,
  rejection,
  onBusy,
  onDirty,
  onApply,
}: {
  scope: CorrectionScope;
  inventory: PackageRequirementInventoryView;
  etag: string | null;
  disabled: boolean;
  current: boolean;
  rejection: number;
  onBusy: (busy: boolean) => void;
  onDirty?: (dirty: boolean) => void;
  onApply: (pending: PendingCorrection) => Promise<void>;
}) {
  const base = correctionBase(inventory);
  const [changes, setChanges] = useState<CorrectionDraftChange[]>([]),
    [reason, setReason] = useState("");
  const [editing, setEditing] = useState(false),
    [preview, setPreview] = useState<{
      value: PackageRuleCorrectionPreviewView;
      rejection: number;
    } | null>(null);
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const [formVersion, setFormVersion] = useState(0);
  const dirty = changes.length > 0 || reason.length > 0 || editing;
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  const request: PackageRuleCorrectionRequest = {
    base_inventory_digest: base.inventoryDigest,
    base_rule_set_digest: base.ruleSetDigest,
    reason: reason.trim(),
    changes: changes.map((item) => item.change),
  };
  const writable =
    !disabled &&
    !busy &&
    current &&
    correctionEtag(etag) &&
    etag === `"requirement-inventory:${scope.revisionId}:${inventory.digest}"`;
  const allowed =
    writable && !editing && validCorrectionRequest(request, scope.bidId);
  const previewCurrent =
    preview &&
    preview.rejection === rejection &&
    sameCorrectionValue(preview.value.manifest.request, request);
  const onEditing = useCallback((value: boolean) => {
    setEditing(value);
    setConfirmed(false);
  }, []);
  async function checkHead() {
    const { data: head, etag: headEtag } =
      await api<PackageRequirementInventoryPage>(
        `${correctionInventoryPath(scope)}?limit=20`,
      );
    if (head.current_inventory_id !== base.inventoryId || headEtag !== etag)
      throw new Error(
        "当前清单已变化。本次修订仍绑定原清单；请读取新清单并重新核对，不能自动套用到新版。",
      );
    const exact = await api<PackageRequirementInventoryView>(
      `${correctionInventoryPath(scope)}/${base.inventoryId}`,
    );
    if (
      !correctionInventoryMatches(exact.data, scope) ||
      exact.etag !== etag ||
      exact.data.digest !== inventory.digest ||
      !sameCorrectionValue(exact.data, inventory) ||
      (await jsonDigest(exact.data.manifest)) !== exact.data.digest
    )
      throw new Error(
        "原清单的内容、摘要或版本条件无法核对，请保留修订内容并重新读取。",
      );
  }
  async function prepare() {
    if (!allowed || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setPreview(null);
    setConfirmed(false);
    const captured = structuredClone(request);
    try {
      await checkHead();
      if (!active.current) return;
      const { data } = await api<unknown>(
        `${correctionPath(scope, base.inventoryId)}/preview`,
        { method: "POST", body: captured },
      );
      const checked = await validateCorrectionPreview(
        data,
        scope,
        inventory,
        captured,
      );
      // A preview may only cite the exact source identities explicitly selected in this editor.
      checked.manifest.changes.forEach((change, index) =>
        change.quotes.forEach((quote, quoteIndex) => {
          const selected = changes[index].quotes[quoteIndex];
          const source = selected?.detail.evidence;
          if (
            !source ||
            selected.quote !== quote.quote ||
            source.evidence_id !== quote.evidence_id ||
            source.member_id !== quote.member_id ||
            source.document_version_id !== quote.document_version_id ||
            source.parse_run_id !== quote.parse_run_id ||
            source.physical_page !== quote.physical_page ||
            source.evidence_digest !== quote.evidence_digest ||
            !sameCorrectionValue(source.part_ids, quote.part_ids)
          )
            throw new Error("预览引用与本次选择的冻结原页身份不符，不能确认。");
        }),
      );
      if (active.current) setPreview({ value: checked, rejection });
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function apply() {
    if (!allowed || !previewCurrent || !confirmed || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await checkHead();
      if (!active.current) return;
      await onApply({
        key: crypto.randomUUID(),
        etag: etag!,
        base,
        body: {
          request: structuredClone(preview.value.manifest.request),
          preview_digest: preview.value.digest,
        },
      });
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div className="rule-correction-draft">
      <p>
        基于清单修订 {inventory.manifest.revision} ·{" "}
        {inventory.manifest.requirements.length}{" "}
        条原始记录。新条款和替换条款的检查计划需要重新声明。
      </p>
      {!current && (
        <p className="notice neutral">
          这是历史清单或当前清单尚未读妥。可以核对内容，不能据此发起新的修订。
        </p>
      )}
      {!correctionEtag(etag) && (
        <p role="alert">清单缺少准确版本条件，修订暂不可用。</p>
      )}
      <PackageRuleCorrectionForm
        key={formVersion}
        scope={scope}
        base={base}
        inventory={inventory}
        value={changes}
        disabled={!writable}
        onEditing={onEditing}
        onChange={(value) => {
          setChanges(value);
          setPreview(null);
          setConfirmed(false);
          setError(null);
        }}
      />
      <label>
        本次修订理由
        <textarea
          maxLength={2000}
          rows={3}
          disabled={!writable}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
            setPreview(null);
            setConfirmed(false);
          }}
          placeholder="说明补漏、替换或撤销的依据及影响"
        />
      </label>
      <div className="rule-correction-toolbar">
        <button
          type="button"
          disabled={
            !allowed ||
            !supportsApi(
              "POST",
              `${correctionPath(scope, base.inventoryId)}/preview`,
            )
          }
          onClick={() => void prepare()}
        >
          {busy ? "正在核对原清单…" : "预览本次修订"}
        </button>
        {dirty && (
          <button
            type="button"
            className="secondary"
            disabled={disabled || busy}
            onClick={() => {
              setChanges([]);
              setReason("");
              setEditing(false);
              setPreview(null);
              setConfirmed(false);
              setError(null);
              setFormVersion((value) => value + 1);
            }}
          >
            放弃未发送或已明确失败的规则修订
          </button>
        )}
        {editing && (
          <p className="small-note">
            先将正在编辑的条款加入本次修订，或取消该项编辑。
          </p>
        )}
      </div>
      {error != null && <ErrorNotice error={error} />}
      {preview && (
        <>
          <PackageRuleCorrectionDiff
            scope={scope}
            base={base}
            preview={preview.value}
          />
          {!previewCurrent && (
            <p role="alert">
              本次预览尚不能再次提交。请保留内容，核对当前清单后重新预览。
            </p>
          )}
          <label className="rule-correction-check">
            <input
              type="checkbox"
              checked={confirmed && !!previewCurrent}
              disabled={!allowed || !previewCurrent}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              我已核对全部前后差异、逐字引用与适用范围，确认按本次预览生成新清单；完整性和正式审查资格仍需后续核验。
            </span>
          </label>
          <button
            type="button"
            disabled={!allowed || !previewCurrent || !confirmed}
            onClick={() => void apply()}
          >
            确认修订并生成新清单
          </button>
        </>
      )}
    </div>
  );
}

export function PackageRuleCorrections({
  bidId,
  memberId,
  packageView,
  inventory,
  inventoryEtag,
  currentInventoryId,
  currentKnown,
  disabled = false,
  onPendingChange,
  onDirtyChange,
  onApplied,
  onRefresh,
}: Props) {
  const scope: CorrectionScope = {
    bidId,
    memberId,
    packageId: packageView.manifest.package_id,
    revisionId: packageView.manifest.revision_id,
    packageDigest: packageView.digest,
  };
  const [initial] = useState(() => {
    try {
      return { recovery: readCorrectionRecovery(scope), error: null };
    } catch (error) {
      return {
        recovery: {
          version: 1,
          scope,
          pending: null,
          last: null,
        } as CorrectionRecovery,
        error,
      };
    }
  });
  const [recovery, setRecovery] = useState(initial.recovery),
    [opened, setOpened] = useState(
      !!initial.recovery.pending || !!initial.error,
    );
  const [busy, setBusy] = useState(false),
    [draftBusy, setDraftBusy] = useState(false),
    [error, setError] = useState<unknown>(initial.error);
  const [notice, setNotice] = useState(""),
    [rejection, setRejection] = useState(0),
    [historyVersion, setHistoryVersion] = useState(0);
  const active = useRef(false),
    running = useRef(false),
    record = useRef(recovery);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const pending = recovery.pending;
  const onDraftBusy = useCallback((value: boolean) => setDraftBusy(value), []);
  useEffect(() => {
    onPendingChange(busy || draftBusy || !!pending || !!initial.error);
    return () => onPendingChange(false);
  }, [busy, draftBusy, pending, initial.error, onPendingChange]);
  function remember(value: CorrectionRecovery) {
    writeCorrectionRecovery(value);
    record.current = value;
    setRecovery(value);
  }
  async function send(operation: PendingCorrection) {
    if (
      running.current ||
      initial.error ||
      (!record.current.pending && disabled)
    )
      return;
    running.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      if (
        record.current.pending &&
        !sameCorrectionValue(record.current.pending, operation)
      )
        throw new Error("存在尚未核对的原请求，不能另发修订。");
      if (!record.current.pending)
        remember({ ...record.current, pending: operation });
      const result = await api<unknown>(
        correctionPath(scope, operation.base.inventoryId),
        {
          method: "POST",
          body: operation.body,
          etag: operation.etag,
          key: operation.key,
        },
      );
      const checked = await validateCorrectionApplied(
        result.data,
        scope,
        { base: operation.base, pending: operation },
        result.etag,
      );
      if (!active.current) return;
      remember({
        ...record.current,
        pending: null,
        last: {
          inventoryId: operation.base.inventoryId,
          correctionId: checked.correction.manifest.id,
        },
      });
      setNotice(
        "已生成新清单并保留原记录。旧覆盖记录没有变成新清单的核查结果；请重新声明新条款的检查计划。",
      );
      setHistoryVersion((value) => value + 1);
      onApplied(checked.inventory.manifest.id);
    } catch (failure) {
      if (!active.current) return;
      if (record.current.pending && definitiveCorrectionFailure(failure)) {
        try {
          remember({ ...record.current, pending: null });
          setRejection((value) => value + 1);
          onRefresh();
        } catch (storageFailure) {
          setError(storageFailure);
          return;
        }
      }
      setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  const valid = correctionInventoryMatches(inventory, scope);
  const historyInventoryId =
    inventory?.manifest.id ??
    pending?.base.inventoryId ??
    recovery.last?.inventoryId ??
    null;
  return (
    <section
      className="panel rule-correction-panel"
      aria-label="整包有据规则修订"
    >
      <div className="section-heading">
        <div>
          <h3>有据修订整包条款</h3>
          <p className="muted">
            补漏、替换或撤销均保留原清单与冻结原页，确认后生成新版本。
          </p>
        </div>
        <button
          type="button"
          className="secondary"
          aria-expanded={opened}
          onClick={() => setOpened((value) => !value)}
        >
          {opened ? "收起规则修订" : "打开规则修订"}
        </button>
      </div>
      {(!!pending || !!initial.error) && !opened && (
        <p role="alert">
          规则修订仍有未核对记录，其他清单写入保持锁定。请打开面板恢复原操作。
        </p>
      )}
      <div hidden={!opened} className="rule-correction-body">
        {notice && (
          <p className="notice success" role="status">
            {notice}
          </p>
        )}
        {error != null && <ErrorNotice error={error} />}
        {pending && (
          <section className="notice neutral" aria-label="恢复未决规则修订">
            <strong>修订结果尚未核对</strong>
            <p>
              原请求、幂等键和版本条件已保留。读取历史不会结束未决状态；请使用原操作恢复回执。
            </p>
            <p>
              本次 {pending.body.request.changes.length} 项修订 ·{" "}
              {pending.body.request.reason}
            </p>
            <details>
              <summary>原操作身份</summary>
              <p>基线清单 {pending.base.inventoryId}</p>
              <p>预览摘要 {pending.body.preview_digest}</p>
              <p>操作键 {pending.key}</p>
            </details>
            <button
              type="button"
              disabled={busy}
              onClick={() => void send(pending)}
            >
              {busy ? "正在核对原修订…" : "恢复原规则修订"}
            </button>
          </section>
        )}
        {!inventory && (
          <p>
            先从要求清单历史选择一个明确版本。未选择清单时不会读取当前资料来代替。
          </p>
        )}
        {inventory && !valid && (
          <p className="notice neutral">
            此清单尚未绑定可核对的精确抽取结果，不能直接补改为完整清单。请先在确切招标／补遗来源上完成抽取；已有历史仍可读取。
          </p>
        )}
        {valid && inventory && (
          <DraftCorrection
            key={`${inventory.manifest.id}:${inventory.digest}:${historyVersion}`}
            scope={scope}
            inventory={inventory}
            etag={inventoryEtag}
            disabled={disabled || !!pending || !!initial.error || busy}
            current={
              currentKnown && currentInventoryId === inventory.manifest.id
            }
            rejection={rejection}
            onBusy={onDraftBusy}
            onDirty={onDirtyChange}
            onApply={send}
          />
        )}
        {historyInventoryId && (
          <PackageRuleCorrectionHistory
            key={`${historyInventoryId}:${historyVersion}`}
            scope={scope}
            inventoryId={historyInventoryId}
            last={recovery.last}
          />
        )}
      </div>
    </section>
  );
}
