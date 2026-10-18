"""Word 按原稿先后排序，只有显式采用且仍为最新的实际 PDF 才能替代它进入分析。"""

from __future__ import annotations

from sqlalchemy import Connection

from bidwb import db


def heads(conn: Connection, project_id: str) -> list[db.Row]:
    return db.all_(
        conn,
        """
      WITH originals AS (
        SELECT DISTINCT ON (f.id) fv.*,f.role FROM file_versions fv JOIN files f ON f.id=fv.file_id
        JOIN artifacts a ON a.id=fv.artifact_id
        WHERE fv.project_id=:p AND a.status='committed' AND NOT EXISTS (
          SELECT 1 FROM word_pdf_links l JOIN file_versions pv ON pv.id=l.pdf_version_id WHERE pv.file_id=f.id)
        ORDER BY f.id,fv.obtained_at DESC,fv.id DESC
      )
      SELECT COALESCE(pdf.id,o.id) AS id,COALESCE(pdf.original_name,o.original_name) AS original_name,o.role,
        o.id AS source_id,o.obtained_at AS source_obtained_at,
        CASE WHEN pdf.id IS NOT NULL AND link.method='user_declared' THEN pdf.obtained_at ELSE o.obtained_at END AS obtained_at,
        (SELECT coverage FROM parses ps WHERE ps.file_version_id=COALESCE(pdf.id,o.id)
          ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1) AS coverage
      FROM originals o LEFT JOIN LATERAL (
        SELECT ad.* FROM word_pdf_adoptions ad WHERE ad.source_version_id=o.id ORDER BY ad.created_at DESC,ad.id DESC LIMIT 1
      ) adoption ON true
      LEFT JOIN word_pdf_links link ON link.id=adoption.link_id
      LEFT JOIN file_versions pdf ON pdf.id=adoption.pdf_version_id AND NOT EXISTS (
        SELECT 1 FROM file_versions newer WHERE newer.file_id=pdf.file_id AND (newer.obtained_at,newer.id)>(pdf.obtained_at,pdf.id))
      ORDER BY o.obtained_at,o.id
    """,
        {"p": project_id},
    )


def active_body(conn: Connection, project_id: str) -> str | None:
    bodies = [r for r in heads(conn, project_id) if r["role"] == "body"]
    return str(bodies[-1]["id"]) if bodies else None


def lineage(conn: Connection, project_id: str, version_ids: list[str]) -> list[db.Row]:
    return db.all_(
        conn,
        """SELECT l.source_version_id,l.pdf_version_id,l.method,l.id AS link_id,ad.id AS adoption_id,
         original.sha256 AS source_sha256,actual.sha256 AS pdf_sha256,c.report_json->>'renderer_fingerprint' AS renderer_fingerprint
       FROM word_pdf_links l JOIN word_pdf_adoptions ad ON ad.link_id=l.id
       JOIN file_versions w ON w.id=l.source_version_id JOIN artifacts original ON original.id=w.artifact_id
       JOIN file_versions p ON p.id=l.pdf_version_id JOIN artifacts actual ON actual.id=p.artifact_id
       LEFT JOIN word_conversions c ON c.id=l.conversion_id
       WHERE l.project_id=:p AND l.pdf_version_id=ANY(:v)
         AND ad.id=(SELECT x.id FROM word_pdf_adoptions x WHERE x.source_version_id=l.source_version_id ORDER BY x.created_at DESC,x.id DESC LIMIT 1)
       ORDER BY l.pdf_version_id""",
        {"p": project_id, "v": version_ids},
    )
