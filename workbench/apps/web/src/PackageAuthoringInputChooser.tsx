import { useState } from "react";
import { AuthoringPackageCapture } from "./AuthoringPackageCapture";
import { PackageAuthoringInputPicker } from "./PackageAuthoringInput";
import type { VerifiedAuthoringInput } from "./packageAuthoringInputProtocol";

/** Explicit capture stays mounted while hidden so unsaved work keeps its guard. */
export function PackageAuthoringInputChooser({
  bidId,
  memberId,
  disabled = false,
  onSelect,
}: {
  bidId: string;
  memberId: string;
  disabled?: boolean;
  onSelect: (input: VerifiedAuthoringInput) => void;
}) {
  const [capturing, setCapturing] = useState(false);
  const [opened, setOpened] = useState(false);
  return (
    <section aria-label="选择或采集固定编写输入">
      <PackageAuthoringInputPicker
        bidId={bidId}
        disabled={disabled || capturing}
        onSelect={onSelect}
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
      {opened && (
        <div hidden={!capturing}>
          <AuthoringPackageCapture
            key={`${memberId}:${bidId}`}
            bidId={bidId}
            memberId={memberId}
            disabled={disabled}
            onSaved={(input) => {
              onSelect(input);
              setCapturing(false);
            }}
          />
        </div>
      )}
    </section>
  );
}
