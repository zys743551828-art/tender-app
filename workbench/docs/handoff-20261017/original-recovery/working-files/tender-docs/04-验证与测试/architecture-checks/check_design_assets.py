"""检查全新设计证据身份和需求追踪；不代替运行实验或软件验收。"""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source_cache, output, orchestration_cache=None, product_cache=None):
    failures = []
    def check(condition, message):
        if not condition:
            failures.append(message)
    docs = [ROOT/'01-背景与市场研究/成熟AI系统与技术组件调研.md',ROOT/'05-技术与设计/AI投标工作台全新系统技术方案.md',ROOT/'04-验证与测试/全新技术方案验证与自审.md',ROOT/'README.md',HERE/'README.md',ROOT/'05-技术与设计/评分预测训练与验收方案.md',ROOT/'02-业务与产品/AI投标工作台产品化方案.md',ROOT/'05-技术与设计/LangGraph路线技术方案.md']
    docs += [ROOT/'01-背景与市场研究/AI执行与工作流选型复核.md',ROOT/'01-背景与市场研究/相似AI产品技术路线核查.md']
    prd = ROOT/'02-业务与产品/AI投标工作台PRD.md'
    trace = json.loads((HERE/'requirements-trace.json').read_text())['trace']
    required = set(re.findall(r'^\| ((?:FR|NFR)-\d{3}) \|',prd.read_text(),re.M))
    check(len(required)==50,'PRD需求集合不是预期50项')
    check({x['requirement'] for x in trace}==required and len(trace)==len(required),'技术追踪缺项、重复或多项')
    technical = docs[1].read_text()
    sections = set(map(int,re.findall(r'^## (\d+)\.',technical,re.M)))
    check(sections==set(range(1,19)),'技术方案18章不完整')
    audit = docs[2].read_text()
    for row in trace:
        check(bool(row['sections']) and set(row['sections'])<=sections,'技术追踪章节不存在:'+row['requirement'])
        expected='| '+row['requirement']+' | '+'、'.join(map(str,row['sections']))+' | 待实现／验收 |'
        check(expected in audit,'可读追踪与主数据不一致:'+row['requirement'])
    catalog = json.loads((HERE/'official-sources.json').read_text())
    check(len(catalog['sources'])==28,'官方仓库数变化，请重审文档')
    fetched=rehashes=0
    for source in catalog['sources']:
        commit=source['commit']
        check(bool(re.fullmatch('[0-9a-f]{40}',commit)),'非固定来源提交:'+source['id'])
        check(source['id'] in docs[0].read_text(),'来源索引缺失:'+source['id'])
        for file in source['files']:
            expected='https://raw.githubusercontent.com/'+source['repository']+'/'+commit+'/'+file['path']
            check(file['url']==expected,'来源URL与提交不一致:'+source['id']+'/'+file['path'])
            if file.get('status')!=200:
                check(bool(file.get('error')),'失败来源未保留失败原因')
                continue
            fetched+=1
            check(bool(re.fullmatch('[0-9a-f]{64}',file['sha256'])),'来源摘要不合法')
            if source_cache:
                path=source_cache/source['id']/file['path']
                check(path.exists() and digest(path)==file['sha256'],'原文摘要不一致:'+source['id']+'/'+file['path'])
                rehashes+=int(path.exists())
    check(fetched==77,'成功原文数量变化，请同步调研报告')
    supplemental=[]
    review_inputs=[]
    for name, cache in [('orchestration-sources.json', orchestration_cache), ('product-architecture-sources.json', product_cache)]:
        manifest_path=HERE/name
        review_inputs.append(manifest_path)
        manifest=json.loads(manifest_path.read_text())
        successful=rehashed=0
        repositories=set()
        identities=set()
        for file in manifest['files']:
            identity=(file['source'],file['path'])
            check(identity not in identities,'重复专项来源:'+name+':'+str(identity))
            identities.add(identity)
            check(bool(re.fullmatch('[0-9a-f]{40}',file['commit'])),'专项来源不是固定提交:'+name)
            expected='https://raw.githubusercontent.com/'+file['repository']+'/'+file['commit']+'/'+file['path']
            check(file['url']==expected,'专项来源URL与身份不符:'+name)
            if file.get('status')!=200:
                check(bool(file.get('error')),'专项失败来源缺少原因:'+name)
                continue
            successful+=1
            repositories.add(file['repository'])
            check(bool(re.fullmatch('[0-9a-f]{64}',file['sha256'])),'专项来源摘要不合法:'+name)
            if cache:
                path=cache/file['source']/file['path']
                check(path.exists() and digest(path)==file['sha256'],'专项原文摘要不一致:'+str(identity))
                rehashed+=int(path.exists())
        supplemental.append(dict(manifest=name,repositories=len(repositories),files=successful,files_rehashed=rehashed,cache_status='已复核原文缓存' if cache else '未提供缓存，仅核对清单'))
    runtime=json.loads((HERE/'run-manifest.json').read_text())
    check(digest(HERE/'requirements.lock.txt')==runtime['dependency_lock_sha256'],'依赖快照已变化或过期')
    for rel, expected in runtime['artifact_hashes'].items():
        path=ROOT/rel
        check(path.exists() and digest(path)==expected,'运行证据已变化或过期:'+rel)
    results={name:json.loads((HERE/(name+'-result.json')).read_text()) for name in ('temporal','langgraph','postgres','pgvector','scoring')}
    check(all(r.get('passed') is True and r.get('external_model_calls')==0 for r in results.values()),'机制结果失败或调用身份变化')
    t=results['temporal']['cases']
    check(t[0]['result']['effect_count']==2 and t[1]['result']['effect_count']==1,'Temporal负对照/保护结果不符')
    g=results['langgraph']['cases']
    check(g[0]['business_effects']==2 and g[1]['business_effects']==1,'LangGraph恢复负对照不符')
    v=results['pgvector']
    check(len(v['naive_hnsw_ids'])<10 and len(v['iterative_hnsw_ids'])==10 and v['negative_control_reproduced'],'ANN过滤负对照不符')
    s=results['scoring']
    check(s['group_split_mae']>s['naive_random_split_mae']*10,'相关样本泄漏对照未复现')
    check(runtime['temporal_cli']['verified'] is True,'CLI没有官方校验记录')
    scripts=list(HERE.glob('probe_*.py'))
    for script in scripts:
        tree=ast.parse(script.read_text())
        for node in ast.walk(tree):
            imports=[]
            if isinstance(node,ast.Import):imports=[n.name for n in node.names]
            if isinstance(node,ast.ImportFrom):imports=[node.module or '']
            check(not any(n.startswith(('bidwb','tender_research')) for n in imports),'隔离实验导入了旧应用:'+script.name)
    links=0
    for doc in docs:
        text=doc.read_text()
        check(text.count('~~~')%2==0,'代码围栏未闭合:'+doc.name)
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',text):
            if '://' in target or target.startswith(('#','mailto:')):continue
            path=(doc.parent/target.split('#',1)[0].strip('<>')).resolve()
            check(path.exists() or path==output.resolve(),'本地链接不存在:'+doc.name+':'+target)
            links+=1
    return dict(scope='文档、来源与执行产物身份检查；不重跑实验，不代表整套产品或真实评分验收',passed=not failures,requirements_traced=len(trace),official_repositories=28,official_files=fetched,source_files_rehashed=rehashes,source_rehash_status='已复核原文缓存' if source_cache else '未提供缓存，仅核对清单，未重新访问远端',supplemental_source_checks=supplemental,isolated_probe_scripts=len(scripts),result_groups=len(results),local_links_checked=links,failures=failures,input_hashes={str(p.relative_to(ROOT)):digest(p) for p in [*docs,*review_inputs,prd,HERE/'official-sources.json',HERE/'requirements-trace.json',HERE/'run-manifest.json',Path(__file__).resolve(),HERE/'fetch_official_sources.py']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache',type=Path)
    parser.add_argument('--orchestration-source-cache',type=Path)
    parser.add_argument('--product-source-cache',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.source_cache,args.output,args.orchestration_source_cache,args.product_source_cache)
    rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    args.output.write_text(rendered)
    print(rendered,end='')
    raise SystemExit(int(not result['passed']))
