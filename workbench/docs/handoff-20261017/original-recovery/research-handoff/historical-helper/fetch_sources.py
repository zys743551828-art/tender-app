import concurrent.futures
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = Path('/workspace/.setup/orchestration-review/cache')
MANIFEST = Path('/workspace/tender-docs/04-验证与测试/architecture-checks/orchestration-sources.json')
SOURCES = [
    ('OR-LC', 'langchain-ai/docs', '8f2fa7e3fc5f76715b703e391772286864a49bb1', [
        'src/oss/langgraph/persistence.mdx', 'src/oss/langgraph/interrupts.mdx',
        'src/oss/langgraph/deploy.mdx', 'src/langsmith/deploy-standalone-server.mdx',
        'src/langsmith/agent-server.mdx', 'src/langsmith/agent-server-overview.mdx',
        'src/langsmith/scalability-and-resilience.mdx', 'src/langsmith/enqueue-concurrent.mdx',
        'src/langsmith/double-texting.mdx', 'src/langsmith/background-run.mdx',
        'src/langsmith/deploy-to-self-hosted-overview.mdx', 'src/langsmith/deployment.mdx',
        'src/langsmith/agent-server-scale.mdx', 'src/langsmith/pricing-plans.mdx',
        'src/langsmith/self-hosted.mdx', 'src/langsmith/deployment-revisions.mdx',
    ]),
    ('OR-DIFY', 'langgenius/dify', 'f3d7a49927da129f75c52a55392aad79a613e993', [
        'README.md', 'LICENSE', 'docker/docker-compose.yaml', 'docker/README.md',
        'api/tasks/async_workflow_tasks.py', 'api/tasks/app_generate/workflow_execute_task.py',
        'api/core/workflow/human_input_policy.py',
        'api/tests/test_containers_integration_tests/test_workflow_pause_integration.py',
        'api/tests/test_containers_integration_tests/core/workflow/test_human_input_resume_node_execution.py',
    ]),
    ('OR-TEMPORAL', 'temporalio/temporal', 'dcd360f177a1238c6f7c59ef5889613b7e243a03', [
        'README.md', 'LICENSE', 'CONTRIBUTING.md',
    ]),
    ('OR-HELM', 'temporalio/helm-charts', '5b55686b4d2e377a3d7d5873926e682db34ed25a', [
        'README.md', 'charts/temporal/values.yaml', 'charts/temporal/Chart.yaml', 'UPGRADING.md',
    ]),
    ('OR-LG', 'langchain-ai/langgraph', 'e77a5cb08c1f3ff306d997dd76fc7169afdab5ea', [
        'LICENSE', 'README.md', 'libs/checkpoint-postgres/README.md',
    ]),
]

def fetch(entry):
    sid, repo, commit, path = entry
    url = f'https://raw.githubusercontent.com/{repo}/{commit}/{path}'
    result = dict(source=sid, repository=repo, commit=commit, path=path, url=url)
    try:
        with urlopen(Request(url, headers={'User-Agent': 'TenderArchitectureResearch'}), timeout=25) as response:
            body = response.read()
        local = BASE / sid / path
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(body)
        result.update(status=200, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    except (HTTPError, URLError, TimeoutError) as exc:
        result.update(status=getattr(exc, 'code', None), error=str(exc))
    return result

if __name__ == '__main__':
    entries=[(sid,repo,commit,path) for sid,repo,commit,paths in SOURCES for path in paths]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        files=list(pool.map(fetch, entries))
    result=dict(scope='官方资料和部署配置静态核验；没有运行平台或真实模型', files=files)
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(successful=sum(f['status']==200 for f in files), failed=[f for f in files if f['status']!=200]),ensure_ascii=False))
