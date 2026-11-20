import { useEffect, useMemo, useState } from "react";
import { AuthoringCapturePackagePicker } from "./AuthoringCapturePackagePicker";
import { ErrorNotice } from "./components";
import type { AuthoringTreeView } from "./contracts";
import { TechnicalDraftTrace } from "./TechnicalDraftTrace";
import {
  recoverOutlineSelection,
  storeOutlineSelection,
} from "./technicalOutlineSelection";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import { technicalOutline, type OutlineBasis } from "./technicalBidOutlinePlan";
import { useTechnicalOutlineSources } from "./useTechnicalOutlineSources";

type Outline = ReturnType<typeof technicalOutline>;
type Props = {
  bidId: string;
  memberId: string;
  draftId: string;
  disabled: boolean;
  onPackages?: () => void;
  tree: AuthoringTreeView | null;
  chapterNavigationDisabled: boolean;
  onOpenSection: (sectionId: string) => Promise<void>;
  onPreview: (chapters: Outline["chapters"], basis: OutlineBasis) => void;
};

export function TechnicalBidOutline(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="生成技术标大纲">
      <button
        className="button secondary"
        type="button"
        aria-expanded={open}
        disabled={props.disabled}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起技术标大纲" : "生成技术标大纲"}
      </button>
      {open && (
        <OutlineWorkspace
          key={JSON.stringify([props.memberId, props.bidId, props.draftId])}
          {...props}
        />
      )}
    </section>
  );
}

function OutlineWorkspace({
  bidId,
  memberId,
  draftId,
  disabled,
  onPackages,
  onPreview,
  tree,
  chapterNavigationDisabled,
  onOpenSection,
}: Props) {
  const scope = useMemo(
    () => ({ memberId, bidId, draftId }),
    [memberId, bidId, draftId],
  );
  const [initial] = useState(() => recoverOutlineSelection(scope));
  const [restored, setRestored] = useState(!!initial);
  const [resetEpoch, setResetEpoch] = useState(0);
  const [target, setTarget] = useState<CapturePackageReference | null>(
    initial?.target ?? null,
  );
  const [authority, setAuthority] = useState<CapturePackageReference | null>(
    initial?.authority ?? null,
  );
  const [selection, setSelection] = useState<OutlineBasis["inventory"] | null>(
    initial?.inventory ?? null,
  );
  const [excluded, setExcluded] = useState<string[]>([]);
  const {
    targetView,
    authorityView,
    ready,
    matchingScope,
    directoryPath,
    directory,
    current,
    inventory,
    checkedInventory,
  } = useTechnicalOutlineSources(bidId, target, authority, selection);
  const result = checkedInventory ? technicalOutline(checkedInventory) : null;

  useEffect(() => {
    if (checkedInventory && target && authority && selection) {
      storeOutlineSelection(scope, { target, authority, inventory: selection });
    }
  }, [checkedInventory, target, authority, selection, scope]);

  function clearSelection() {
    setSelection(null);
    setExcluded([]);
    setRestored(false);
    storeOutlineSelection(scope, null);
  }

  const chosen =
    result?.chapters.filter(({ key }) => !excluded.includes(key)) ?? [];
  return (
    <div className="authoring-technical-outline">
      <h4>单标段施工组织设计</h4>
      <p className="small-note">
        按已确认且适用的技术要求建议空章节。不会生成正文、核定覆盖、调用模型或改动现有内容。
      </p>
      {restored && (
        <p role="status" className="small-note">
          {checkedInventory
            ? "已按原身份重新核对本次会话记住的包和清单。"
            : "已恢复本次会话上次明确选择，须重新核对原包和清单，不自动换成当前版本。"}
        </p>
      )}
      {restored &&
        (targetView.error != null || authorityView.error != null) && (
          <p className="small-note">
            原包修订可能不再是当前版本或无法核验，请在目录里明确重新选择。
          </p>
        )}
      {(target || authority) && (
        <button
          type="button"
          className="text-button"
          disabled={disabled}
          onClick={() => {
            clearSelection();
            setTarget(null);
            setAuthority(null);
            setResetEpoch((value) => value + 1);
          }}
        >
          清除已记住的选择
        </button>
      )}
      <AuthoringCapturePackagePicker
        key={`target:${resetEpoch}`}
        bidId={bidId}
        kind="bid"
        selected={target}
        disabled={disabled}
        onSelect={(value) => {
          clearSelection();
          setTarget(value);
        }}
      />
      <AuthoringCapturePackagePicker
        key={`authority:${resetEpoch}`}
        bidId={bidId}
        kind="authority"
        selected={authority}
        disabled={disabled}
        onSelect={(value) => {
          clearSelection();
          setAuthority(value);
        }}
      />
      {ready && !matchingScope && (
        <p role="alert">
          投标包与依据包的项目、标段、轮次或主体不一致，不能混用。
        </p>
      )}
      <ErrorNotice
        error={
          targetView.error ??
          authorityView.error ??
          directory.error ??
          inventory.error
        }
      />
      {directoryPath && (
        <fieldset disabled={disabled}>
          <legend>依据要求清单</legend>
          {selection && directory.ready && !current && (
            <p role="status" className="small-note">
              先前清单不是目前核到的版本，不会沿用其章节对照。请明确选择当前清单。
            </p>
          )}
          <button
            type="button"
            className="text-button"
            disabled={directory.busy}
            onClick={() => {
              clearSelection();
              void directory.load();
            }}
          >
            刷新要求清单
          </button>
          {directory.items
            .filter((item) => item.id === directory.page?.current_inventory_id)
            .map((item) => (
              <button
                type="button"
                className="button secondary"
                key={item.id}
                disabled={!directory.ready}
                aria-pressed={selection?.id === item.id}
                onClick={() => {
                  clearSelection();
                  setSelection({ id: item.id, digest: item.digest });
                }}
              >
                核对当前清单 · {item.id.slice(0, 8)}
              </button>
            ))}
          {directory.ready && !directory.page?.current_inventory_id && (
            <p className="small-note">
              尚无当前要求清单，请先在资料包中确认适用范围和技术分类。
            </p>
          )}
          {directory.page?.has_more && (
            <button
              type="button"
              className="text-button"
              disabled={!directory.ready}
              onClick={() => void directory.load(true)}
            >
              加载更多清单
            </button>
          )}
        </fieldset>
      )}
      {result && (
        <>
          <p className="small-note">
            以下只供目录定位；{result.pending}{" "}
            项未确认或未分类，仍待核对。建议不代表招标指定目录或正文已响应。
          </p>
          <fieldset disabled={disabled}>
            <legend>选择拟追加的章节</legend>
            {result.chapters.length === 0 && (
              <p className="small-note">
                没有足够依据自动建议章节，可在目录中手工新增。
              </p>
            )}
            {result.chapters.map(({ key, title }) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={!excluded.includes(key)}
                  onChange={(event) =>
                    setExcluded((old) =>
                      event.target.checked
                        ? old.filter((v) => v !== key)
                        : [...old, key],
                    )
                  }
                />
                {title}
              </label>
            ))}
            <button
              type="button"
              className="button primary"
              disabled={!chosen.length}
              onClick={() => {
                if (target && authority && selection)
                  onPreview(chosen, {
                    target,
                    authority,
                    inventory: selection,
                  });
              }}
            >
              预览追加大纲
            </button>
          </fieldset>
          {inventory.value && authorityView.value && (
            <TechnicalDraftTrace
              key={inventory.value.digest}
              inventory={inventory.value}
              authority={authorityView.value}
              outline={result}
              bidId={bidId}
              tree={tree}
              navigationDisabled={chapterNavigationDisabled}
              onOpenSection={onOpenSection}
            />
          )}
          <p className="small-note">
            要固定输入并生成本章，应用目录后先沿用现有流程核对版式，再打开本章的“准备生成本章技术标候选”，暂不要在这份草稿保存章节计划。要按计划手工编写，可以照常使用“章节计划”。大纲不是生成授权。
          </p>
        </>
      )}
      {onPackages && (
        <button
          type="button"
          className="text-button"
          disabled={disabled}
          onClick={onPackages}
        >
          前往资料包与要求清单
        </button>
      )}
    </div>
  );
}
