// Generated from implementation source preview: qa-previews/multipart-knowledge-05/implemented-source-04.openapi.json. Run python scripts/generate-contracts.py.

export type UploadBatchPage = {
  items: UploadBatchView[];
  has_more: boolean;
  next_cursor: string | null;
};

export type UploadBatchView = {
  id: string;
  bid_id: string;
  revision: number;
  state: "open" | "verifying" | "committed" | "failed";
  uploads: UploadView[];
};

export type UploadView = {
  id: string;
  bid_id: string;
  batch_id: string;
  filename: string;
  state:
    | "authorized"
    | "uploaded"
    | "verifying"
    | "verified"
    | "quarantined"
    | "expired"
    | "aborted";
  document_version_id: string | null;
  error_code: string | null;
  file_id: string;
  revision: number;
  session_expires_at: string;
  binding_id: string;
  verified_retain_until: string | null;
};
