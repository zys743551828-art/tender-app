import { useState } from "react";
import { AuthoringPackageCapture } from "./AuthoringPackageCapture";
import { PackageAuthoringInputPicker } from "./PackageAuthoringInput";
import {
  matchesFixedAuthoringChapter,
  type FixedAuthoringChapter,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";

/** Explicit capture stays mounted while hidden so unsaved work keeps its guard. */
export function PackageAuthoringInputChooser({
  bidId,
  memberId,
  disabled = false,
  onSelect,
  targetChapter,
}: {
  bidId: string;
  memberId: string;
  disabled?: boolean;
  onSelect: (input: VerifiedAuthoringInput) => void;
  targetChapter?: FixedAuthoringChapter;
}) {
  const [capturing, setCapturing] = useState(false);
  const [opened, setOpened] = useState(false);
  const [mismatch, setMismatch] = useState(false);
  const accepts = targetChapter
    ? (input: VerifiedAuthoringInput) =>
        matchesFixedAuthoringChapter(input, targetChapter)
    : undefined;
  function select(input: VerifiedAuthoringInput) {
    if (accepts && !accepts(input)) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    onSelect(input);
  }
  return (
    <section aria-label="选择或采集固定编写输入">
      <PackageAuthoringInputPicker
        bidId={bidId}
        disabled={disabled || capturing}
        onSelect={select}
        accept={accepts}
      />
      <button
        type="button"
        className="button secondary"
        disabled={disabled}
        aria-expanded={capturing}
        onClick={() => {
          setOpened(true);
          setCapturing(!capturing);
        }}
      >
        {capturing ? "收起采集表单，保留选择" : "采集新的固定编写输入"}
      </button>
      {mismatch && (
        <p role="alert">
          采集回执已保存，但它并非当前章节和修订，未作为本章编写输入。请重新明确选择当前草稿快照、章节和稳定节点。
        </p>
      )}
      {opened && (
        <div hidden={!capturing}>
          <AuthoringPackageCapture
            key={`${memberId}:${bidId}`}
            bidId={bidId}
            memberId={memberId}
            disabled={disabled}
            targetChapter={targetChapter}
            onSaved={(input) => {
              select(input);
              setCapturing(false);
            }}
          />
        </div>
      )}
    </section>
  );
}
