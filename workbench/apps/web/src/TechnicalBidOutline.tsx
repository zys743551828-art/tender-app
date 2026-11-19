import { useCallback, useState } from "react";
import { AuthoringCapturePackagePicker } from "./AuthoringCapturePackagePicker";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import {
  captureInventoryDirectory,
  captureInventoryView,
  capturePackageView,
} from "./authoringCaptureDirectoryProtocol";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import {
  sameLot,
  technicalOutline,
  type OutlineBasis,
} from "./technicalBidOutlinePlan";
import {
  useAuthoringCaptureDirectory,
  useAuthoringCaptureRead,
} from "./useAuthoringCaptureRead";

type Outline = ReturnType<typeof technicalOutline>;
type Props = {
  bidId: string;
  disabled: boolean;
  onPackages?: () => void;
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
      {open && <OutlineWorkspace {...props} />}
    </section>
  );
}

function OutlineWorkspace({ bidId, disabled, onPackages, onPreview }: Props) {
  const [target, setTarget] = useState<CapturePackageReference | null>(null);
  const [authority, setAuthority] = useState<CapturePackageReference | null>(
    null,
  );
  const [selection, setSelection] = useState<OutlineBasis["inventory"] | null>(
    null,
  );
  const [excluded, setExcluded] = useState<string[]>([]);
  const verifyTarget = useCallback(
    (v: unknown) => {
      if (!target) throw new Error("请选择明确的目标投标包修订。");
      return capturePackageView(v, bidId, "target", target);
    },
    [bidId, target],
  );
  const verifyAuthority = useCallback(
    (v: unknown) => {
      if (!authority) throw new Error("请选择明确的招标依据包修订。");
      return capturePackageView(v, bidId, "authority", authority);
    },
    [bidId, authority],
  );
  const targetPath =
    target &&
    `/bids/${bidId}/packages/${target.package_id}/revisions/${target.revision_id}`;
  const sourcePath =
    authority &&
    `/bids/${bidId}/packages/${authority.package_id}/revisions/${authority.revision_id}`;
  const targetView = useAuthoringCaptureRead(targetPath, verifyTarget);
  const authorityView = useAuthoringCaptureRead(sourcePath, verifyAuthority);
  const ready = !!(
    targetView.ready &&
    authorityView.ready &&
    targetView.value &&
    authorityView.value
  );
  const matchingScope = !!(
    targetView.value &&
    authorityView.value &&
    sameLot(targetView.value.manifest.scope, authorityView.value.manifest.scope)
  );
  const directoryPath =
    ready && matchingScope
      ? `/bids/${bidId}/packages/${target!.package_id}/revisions/${target!.revision_id}/requirement-inventories`
      : null;
  const directory = useAuthoringCaptureDirectory(
    directoryPath && directoryPath + "?limit=20",
    captureInventoryDirectory,
  );
  const current =
    directory.ready && selection?.id === directory.page?.current_inventory_id;
  const verifyInventory = useCallback(
    (v: unknown) => {
      if (!targetView.value || !authorityView.value || !selection)
        throw new Error("清单没有明确的目标包或依据包。");
      return captureInventoryView(
        v,
        targetView.value,
        authorityView.value,
        selection,
      );
    },
    [targetView.value, authorityView.value, selection],
  );
  const inventoryPath =
    directoryPath && current && selection
      ? `/bids/${bidId}/packages/${target!.package_id}/revisions/${target!.revision_id}/requirement-inventories/${selection.id}`
      : null;
  const inventory = useAuthoringCaptureRead(inventoryPath, verifyInventory);
  const result =
    inventory.ready && inventory.value
      ? technicalOutline(inventory.value)
      : null;

  function clearSelection() {
    setSelection(null);
    setExcluded([]);
  }

  const chosen =
    result?.chapters.filter(({ key }) => !excluded.includes(key)) ?? [];
  return (
    <div className="authoring-technical-outline">
      <h4>单标段施工组织设计</h4>
      <p className="small-note">
        按已确认且适用的技术要求建议空章节。不会生成正文、核定覆盖、调用模型或改动现有内容。
      </p>
      <AuthoringCapturePackagePicker
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
        <p role="alert">投标包与依据包不属于同一项目、标段和轮次，不能混用。</p>
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
                  setExcluded([]);
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
          <details>
            <summary>
              展开建议依据与待映射技术条款（{result.rows.length}）
            </summary>
            <ul>
              {result.rows.map((row) => (
                <li key={row.ruleId}>
                  <p>{row.statement}</p>
                  <small>
                    {result.chapters
                      .filter((chapter) => row.suggested.includes(chapter.key))
                      .map((chapter) => chapter.title)
                      .join("、") || "待人工映射"}
                  </small>
                  <EvidenceLinks ids={row.evidenceIds} />
                </li>
              ))}
            </ul>
          </details>
          <p className="small-note">
            目录应用后，请在“章节计划”补写条款与引用，再到项目任务中保存固定编写输入；此步骤不代表已取得生成资格。
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
