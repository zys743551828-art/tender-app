from pathlib import Path
import datetime,hashlib,json,subprocess,time
root=Path(__file__).resolve().parents[3];out=root/'qa-previews/assistant-task-10'
checks=[('contracts-verify',['python','qa-previews/assistant-task-10/harnesses/verify-contracts.py']),('format-check',['npm','run','format:check']),('lint',['npm','run','lint']),('typecheck',['npm','run','typecheck']),('test',['npm','run','test','--','--reporter=dot']),('build',['npm','run','build']),('generator-lint',['../../.venv/bin/ruff','check','scripts/generate-contracts.py']),('generator-format',['../../.venv/bin/ruff','format','--check','scripts/generate-contracts.py'])]
results=[]
for name,command in checks:
 started=time.monotonic();log=out/(name+'.log')
 with log.open('w') as stream:value=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
 results.append({'name':name,'command':command,'exit_code':value.returncode,'duration_seconds':round(time.monotonic()-started,3),'log':log.name,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()});print(json.dumps(results[-1]),flush=True)
 if value.returncode:break
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'all_passed':len(results)==len(checks) and all(item['exit_code']==0 for item in results),'checks':results};(out/'final-quality-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if result['all_passed'] else 1)
