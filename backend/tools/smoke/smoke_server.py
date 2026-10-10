"""联调冒烟服务（开发辅助，不属于产品代码；不被测试或镜像引用）：真实 PG + 真实 API（uvicorn）+ 进程内 worker（脚本化模型、内存对象存储）。

播种项目与两份资料后，自动评审流水线在进程内跑完，浏览器直接从评审报告开始操作。
"""
import os, subprocess, sys, threading, time, uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from bidwb import db, tasks
from bidwb.ai.handlers import build_handlers
from bidwb.api.app import create_app
from bidwb.config import Settings
from bidwb.messaging import InMemoryBus
from bidwb.runtime import Container
from bidwb.services import auth as auth_service
from bidwb.storage import MemoryObjectStore
from bidwb.workers.runner import WorkerRunner
from tests.conftest import ADMIN_DSN, PASSWORD
from tests.fakes import ScriptedLlm
from tests.pdfs import make_pdf
from tests.test_auto_pipeline import BODY, LATE, TENDER, _respond
from tests.test_files_and_parse import PROJECT, _upload

admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
name = f"bidwb_smoke_{uuid.uuid4().hex[:6]}"
with admin.connect() as c:
    c.execute(text(f'CREATE DATABASE "{name}"'))
url = make_url(ADMIN_DSN).set(database=name).render_as_string(hide_password=False)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env={**os.environ, "BIDWB_MIGRATION_DATABASE_URL": url}, check=True)
# 受限 worker 角色
with create_engine(url, isolation_level="AUTOCOMMIT").connect() as c:
    c.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='smoke_worker') THEN CREATE ROLE smoke_worker LOGIN PASSWORD 'w' IN ROLE app_worker; END IF; END $$"))
worker_url = make_url(url).set(username="smoke_worker", password="w").render_as_string(hide_password=False)

settings = Settings(
    environment="test", cookie_secure=False, session_cookie_name="sid", login_rate_limit_per_minute=1000, auto_analysis=True
)
store = MemoryObjectStore()
api_engine = db.make_engine(url, pool_size=5, application_name="smoke-api")
w_engine = db.make_engine(worker_url, pool_size=3, application_name="smoke-worker")
api_ctr, w_ctr = Container(settings, api_engine, store), Container(settings, w_engine, store)
with db.transaction(api_engine) as conn:
    auth_service.create_local_member(conn, login="demo", display_name="演示账号", password=PASSWORD)
app = create_app(settings, api_ctr)

# 播种：项目 + 招标文件 + 正文（走真实上传接口）
from tests.conftest import Api
lead = Api(TestClient(app, base_url="http://x")).login("demo")
pid = lead.post("/projects", PROJECT).json()["project_id"]
_upload(lead, store, pid, TENDER)
_upload(lead, store, pid, BODY, name="施工组织设计.pdf", role="body", key="body-upload-0001")



def _revise(system, user):
    """改稿建议：把超期的总工期改成满足要求的写法。"""
    from tests.fakes import docs

    finding = user.split("[")[1].split("]", maxsplit=1)[0]
    evidence = next(i for i in docs(user) if LATE in i[1])[0]
    return {"edits": [{"evidence_id": evidence, "original": LATE, "replacement": "计划总工期为一百七十日历天", "finding_id": finding, "facts_used": [], "note": ""}]}


llm = ScriptedLlm(lambda s, u: _respond(s, u) if ("合规检查员" in s or "抽取员" in s or "评标专家" in s or "目录分析员" in s) else _revise(s, u))
bus = InMemoryBus()
runners = [WorkerRunner(w_ctr, "parse", bus.consumer(["job.parse"]), build_handlers(llm), consumer_name="smoke-parse"),
           WorkerRunner(w_ctr, "ai", bus.consumer(["job.ai"]), build_handlers(llm), consumer_name="smoke-ai")]
def pump():
    while True:
        try:
            with w_engine.begin() as conn:
                tasks.relay_outbox(conn, bus.producer())
            for r in runners:
                while r.poll_once(0.05):
                    pass
        except Exception as e:
            print("pump error", repr(e), flush=True)
        time.sleep(0.3)
threading.Thread(target=pump, daemon=True).start()
print("READY project", pid, flush=True)
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
