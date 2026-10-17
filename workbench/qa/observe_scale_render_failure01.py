import json,os
from pathlib import Path
from packages.domain.runtime import connection,clean
with connection() as c:
 rows=c.execute("SELECT r.outcome FROM word_render_runs r JOIN document_versions v ON v.id=r.source_document_version_id JOIN members m ON m.id=v.created_by WHERE m.display_name='独立助手合成成员' AND v.original_name='独立技术满分招标.docx' ORDER BY r.created_at DESC LIMIT 1").fetchall()
r=Path(os.environ['QA_ASSISTANT_ROOT']);(r/'primary-execution/render-failure.json').write_text(json.dumps(clean(rows),ensure_ascii=False,indent=2)+'\n');print(json.dumps([dict(error=x['outcome'].get('error_code'),state=x['outcome']['state'],gaps=x['outcome']['gaps']) for x in rows]))
