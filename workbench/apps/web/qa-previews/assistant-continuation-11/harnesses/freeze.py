import json,hashlib,datetime,shutil
from pathlib import Path
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/assistant-continuation-11';baseout=root/'qa-previews/assistant-task-10';base=json.loads((baseout/'frontend-candidate.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(a):return hashlib.sha256(''.join(x['path']+'\0'+x['sha256']+'\n' for x in a).encode()).hexdigest()
assert not (out/'frozen-inputs').exists() and not (out/'frozen-dist').exists()
for key,folder in [('source_files','frozen-inputs'),('compiled_assets','frozen-dist')]:
 assert all(sha(baseout/folder/x['path'])==x['sha256'] for x in base[key])
quality=[]
for name in ['format-check','lint','typecheck','test','contracts-verify']:
 p=out/(name+'.log');assert p.exists();t=p.read_text();assert 'Error:' not in t and 'error TS' not in t and 'FAIL' not in t
 quality.append({'check':name,'log':p.name,'sha256':sha(p),'result':'passed'})
assert '16 passed' in (out/'test.log').read_text()
assert 'built in' in (out/'build-development-retry.log').read_text()
quality.append({'check':'build','log':'build-development-retry.log','sha256':sha(out/'build-development-retry.log'),'result':'passed','original_failure_retained':'build-development.log: ENOSPC; subsequent existing-dependency retry succeeded, no install or evidence deletion'})
paths={x['path'] for x in base['source_files']}|{str(p.relative_to(root)) for p in (root/'src').rglob('*') if p.is_file()};total=sum((root/n).stat().st_size for n in paths)+sum(p.stat().st_size for p in (root/'dist').rglob('*') if p.is_file());assert total<30*1024*1024
sources=[]
for n in sorted(paths):
 target=out/'frozen-inputs'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/n,target);sources.append({'path':n,'sha256':sha(target)})
shutil.copytree(root/'dist',out/'frozen-dist');assets=[{'path':str(p.relative_to(out/'frozen-dist')),'sha256':sha(p)} for p in sorted((out/'frozen-dist').rglob('*')) if p.is_file()]
oldhash={x['path']:x['sha256'] for x in base['source_files']};changed=[x['path'] for x in sources if oldhash.get(x['path'])!=x['sha256']]
manifest={'candidate':'frontend11-assistant-continuation','status':'frozen_pending_independent_user_delta','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base10_manifest_sha256':sha(baseout/'frontend-candidate.json'),'scope':'U10-01 continuation only: initial/refresh input visibility, explicit keyboard jump, respectful history polling, scope copy','source_files':sources,'source_tree_sha256':tree(sources),'source_file_count':len(sources),'changed_sources_from10':changed,'compiled_assets':assets,'compiled_tree_sha256':tree(assets),'actual_contract':base['actual_contract'],'dependency_lock':base['dependency_lock'],'quality':quality,'baseline10_frozen_sources_and_assets_verified':True,'browser_evidence':{'development':'development-browser-result.json','native':'native-browser-result.json (appended after cold start)'},'copied_bytes':total,'limits':['0 models/turns/actions/control/task runs; only authentication and read-only API, local unsent text.','Existing explicit Mock facility is not real provider quality or production acceptance.','16 targeted tests passed;122 previous baseline tests are not claimed rerun.','No Word/A2 future interfaces or contracts added.']}
(out/'frontend-candidate.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(out/'frozen-inputs/node_modules').symlink_to(root/'node_modules',target_is_directory=True);(out/'frozen-inputs/dist').symlink_to(out/'frozen-dist',target_is_directory=True)
print(json.dumps({'path':str(out/'frontend-candidate.json'),'sha256':sha(out/'frontend-candidate.json'),'sources':len(sources),'assets':len(assets),'copied_bytes':total,'changed':changed},ensure_ascii=False))
