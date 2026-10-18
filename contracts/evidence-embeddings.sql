-- 可重建的证据向量索引；不改变原件、证据或人工核验状态。
-- REAL[] 允许纯 PostgreSQL 安装完成迁移；启用 pgvector 通道时由管理员预装 vector 扩展，查询转为 vector(512)。
CREATE TABLE evidence_embeddings (
 evidence_id TEXT NOT NULL, project_id TEXT NOT NULL,
 model_fingerprint TEXT NOT NULL CHECK(model_fingerprint ~ '^[0-9a-f]{64}$'),
 quote_sha256 TEXT NOT NULL CHECK(quote_sha256 ~ '^[0-9a-f]{64}$'),
 embedding REAL[] NOT NULL CHECK(array_ndims(embedding)=1 AND cardinality(embedding)=512
   AND array_lower(embedding,1)=1 AND array_position(embedding,NULL) IS NULL
   AND array_position(embedding,'NaN'::REAL) IS NULL
   AND array_position(embedding,'Infinity'::REAL) IS NULL AND array_position(embedding,'-Infinity'::REAL) IS NULL),
 truncated BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(evidence_id,model_fingerprint),
 FOREIGN KEY(evidence_id,project_id) REFERENCES evidence(id,project_id)
);
CREATE INDEX idx_evidence_embeddings_scope ON evidence_embeddings(project_id,model_fingerprint);
GRANT SELECT ON evidence_embeddings TO app_api;
GRANT SELECT,INSERT,UPDATE ON evidence_embeddings TO app_worker;
