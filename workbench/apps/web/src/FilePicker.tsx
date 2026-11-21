import { useId, useState, type ComponentPropsWithRef } from "react";
import { Icon } from "./components";

type Props = Omit<ComponentPropsWithRef<"input">, "type" | "value"> & {
  action: string;
  selection?: string;
};

export function FilePicker({ action, selection, onChange, ...input }: Props) {
  const [lastName, setLastName] = useState("");
  const selectionId = useId();
  const feedback = selection ?? (lastName && `已选择：${lastName}`);
  return (
    <span className="file-picker">
      <span className="file-picker-control">
        <input
          {...input}
          aria-label={input["aria-label"] ?? action}
          aria-describedby={
            [input["aria-describedby"], feedback && selectionId]
              .filter(Boolean)
              .join(" ") || undefined
          }
          type="file"
          onChange={(event) => {
            if (selection === undefined && event.target.files?.length)
              setLastName(event.target.files[0].name);
            onChange?.(event);
          }}
        />
        <span className="button secondary" aria-hidden="true">
          <Icon name="upload" />
          {action}
        </span>
      </span>
      <span className="file-picker-selection" id={selectionId} role="status">
        {feedback}
      </span>
    </span>
  );
}
