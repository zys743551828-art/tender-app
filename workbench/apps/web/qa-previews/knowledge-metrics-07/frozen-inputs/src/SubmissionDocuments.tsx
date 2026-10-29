import { sizeLabel } from "./api";
import type { SubmissionDocumentView } from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useSubmissionDocuments } from "./useSubmissionDocuments";
export function SubmissionDocumentChoices({
  resource,
  value,
  onChange,
  label,
  disabled = false,
}: {
  resource: ReturnType<typeof useSubmissionDocuments>;
  value: string;
  onChange: (id: string) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="submission-document-picker">
      <label>
        {label}
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          required
        >
          <option value="">选择本项目已核验原件</option>
          {resource.items.map((item) => (
            <option
              key={item.document_version_id}
              value={item.document_version_id}
            >
              {documentLabel(item)}
            </option>
          ))}
        </select>
      </label>
      <ResourceState
        {...resource}
        hasData={!!resource.data}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={resource.moreError} />
      {resource.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={resource.moreBusy}
          onClick={() => void resource.more()}
        >
          {resource.moreBusy ? "正在读取更多原件…" : "加载更多已核验原件"}
        </button>
      )}
    </div>
  );
}

function documentLabel(document: SubmissionDocumentView) {
  return `${document.original_name} · ${document.document_version_id.slice(0, 8)} · ${sizeLabel(document.byte_size)}`;
}
