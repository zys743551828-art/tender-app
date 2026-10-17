import subprocess,json,time,datetime,hashlib
from pathlib import Path
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/submission-report-06';commands=[('contracts-generate',['npm','run','contracts:generate']),('format-check',['npm','run','format:check']),('lint',['npm','run','lint']),('typecheck',['npm','run','typecheck']),('test',['npm','run','test','--','--reporter=dot']),('build',['npm','run','build']),('generator-lint',['../../.venv/bin/ruff','check','scripts/generate-contracts.py']),('generator-format',['../../.venv/bin/ruff','format','--check','scripts/generate-contracts.py'])];results=[]
for name,command in commands:
 start=time.monotonic();p=subprocess.run(command,cwd=root,capture_output=True,text=True);output=p.stdout+p.stderr;log=out/(name+'.log');log.write_text(output);row={'name':name,'command':command,'exit_code':p.returncode,'duration_seconds':round(time.monotonic()-start,3),'log':log.name,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()};results.append(row);print(name,p.returncode,flush=True)
 if name in ['test','build']:print(output,flush=True)
 if p.returncode:print(output,flush=True);break
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'all_passed':len(results)==len(commands) and all(x['exit_code']==0 for x in results),'checks':results};(out/'final-quality-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');raise SystemExit(0 if result['all_passed'] else 1)
