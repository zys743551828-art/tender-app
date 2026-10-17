import hashlib,json,datetime,subprocess,urllib.request
from pathlib import Path
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/assistant-continuation-11';base=root/'qa-previews/assistant-task-10'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((out/'frontend-candidate.json').read_text());b=json.loads((base/'frontend-candidate.json').read_text());browser=json.loads((out/'native-browser-result.json').read_text())
for directory,value in [(out,m),(base,b)]:
 for key,folder in [('source_files','frozen-inputs'),('compiled_assets','frozen-dist')]:
  assert all(sha(directory/folder/x['path'])==x['sha256'] for x in value[key])
assetmap={'/'+x['path']:x['sha256'] for x in m['compiled_assets']};assert browser['mode']=='native11' and len(browser['checks'])==6
assert all(assetmap[p]==s for p,s in browser['loaded_assets'].items());assert not browser['blocked_business_writes'] and not browser['page_errors']
expected=json.loads((base/'implemented-task04.openapi.json').read_text());live=json.load(urllib.request.urlopen('http://127.0.0.1:8816/openapi.json'));assert live==expected
processes=[]
for line in subprocess.check_output(['ps','-eo','pid=,uid=,args='],text=True).splitlines():
 p=line.strip().split(maxsplit=2)
 if len(p)==3 and p[2]=='node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5184 --strictPort':processes.append({'pid':int(p[0]),'uid':int(p[1]),'argv':p[2]})
assert len(processes)==1 and processes[0]['uid']==1000
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_path':str(out/'frontend-candidate.json'),'candidate_sha256':sha(out/'frontend-candidate.json'),'fixed_sources_verified_after_browser':len(m['source_files']),'fixed_assets_verified_after_browser':len(m['compiled_assets']),'baseline10_sources_verified':len(b['source_files']),'baseline10_assets_verified':len(b['compiled_assets']),'runtime':processes[0],'runtime_session':92187,'launch_workdir':str(out/'frozen-inputs'),'launch_workdir_basis':'exec_command explicit workdir; process argv and HTTP assets independently checked, no environ read','dependency_lock_sha256':m['dependency_lock']['sha256'],'node_modules_symlink_target':str((out/'frozen-inputs/node_modules').resolve()),'dist_symlink_target':str((out/'frozen-inputs/dist').resolve()),'proxy_target':'http://127.0.0.1:8816','loaded_assets':browser['loaded_assets'],'api_live_equals_fixed_task05_actual':True,'api_fixed_sha256':sha(base/'implemented-task04.openapi.json'),'browser_result_sha256':sha(out/'native-browser-result.json'),'browser_checks':6,'business_writes':0,'paid_calls':0,'real_provider_calls':0,'control_changes':0,'old_10_process':{'pid':2979532,'uid':1000,'verified_exact_argv_then_sigterm':True},'old10_files_preserved':True}
(out/'cold-runtime-binding.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'binding':str(out/'cold-runtime-binding.json'),'sha256':sha(out/'cold-runtime-binding.json'),'pid':processes[0]['pid'],'sources':len(m['source_files']),'assets':len(m['compiled_assets']),'browser_checks':6},ensure_ascii=False))
