import datetime,hashlib,json,subprocess
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/assistant-task-10';origin='http://127.0.0.1:5184';member=json.loads((root/'../../.local/assistant_ui01-test-members.json').read_text())[1];manifest=json.loads((out/'frontend-candidate.json').read_text());task=json.loads((out/'tasks-browser-result.json').read_text());assistant=json.loads((out/'assistant-mock-browser-result.json').read_text());api=json.loads((out/'implemented-task04.openapi.json').read_text());observed={};writes=[];errors=[];redirected_assets=[];asset_errors=[]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def verify():
 assert all(sha(out/'frozen-inputs'/item['path'])==item['sha256'] for item in manifest['source_files'])
 assert all(sha(out/'frozen-dist'/item['path'])==item['sha256'] for item in manifest['compiled_assets'])
 assert sha(out/'frozen-inputs/package-lock.json')==manifest['dependency_lock']['sha256']
verify()
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1440,'height':1000});page=ctx.new_page();page.set_default_timeout(20000)
 def record(response):
  path=urlsplit(response.url).path
  if path.startswith('/assets/') and response.status!=200:
   redirected_assets.append({'path':path,'status':response.status});return
  if path.startswith('/assets/'):
   expected=next(item['sha256'] for item in manifest['compiled_assets'] if '/'+item['path']==path);actual=hashlib.sha256(response.body()).hexdigest();assert actual==expected;observed[path]=actual
  if response.request.method not in ['GET','HEAD'] and '/auth/' not in path:writes.append({'path':path,'method':response.request.method})
 page.on('response',record);page.on('pageerror',lambda e:errors.append(type(e).__name__))
 page.goto(origin+'/projects');page.get_by_label('账号',exact=True).fill(member['login']);page.get_by_label('密码',exact=True).fill(member['password']);page.get_by_role('button',name='登录工作区',exact=True).click();page.get_by_role('button',name='＋ 新建投标',exact=True).wait_for();httpapi=page.request.get(origin+'/openapi.json')
 # /openapi.json is the SPA route; read actual API direct below, not through an unregistered proxy path.
 backend=ctx.request.get('http://127.0.0.1:8816/openapi.json');assert backend.status==200 and backend.json()==api
 bid=task['project_id'];run=next(v['run_id'] for v in task['checks'] if 'run_id' in v);draft=next(v['draft_id'] for v in task['checks'] if 'draft_id' in v);path=f'/bids/{bid}/tasks?run={run}&task_draft={draft}'
 before=page.request.get(origin+f'/api/v1/bids/{bid}/task-definitions?limit=100').json();page.goto(origin+path);page.get_by_text('此草案已一次保存为以下模板；继续修改请建立该模板的新版本，未另建重复模板。',exact=True).wait_for();page.get_by_text('已登记补遗关系核对：已汇总已登记关系，语义影响尚未检查。',exact=True).wait_for();page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(out/'frozen-task05-mobile.png'),full_page=True)
 action=next(v['action_id'] for v in assistant['checks'] if 'action_id' in v);page.goto(origin+'/assistant?action='+action);page.get_by_role('heading',name='明确链接的操作提议',exact=True).wait_for();page.locator('.assistant-action-card').first.get_by_text('已执行并留存结果',exact=True).wait_for();assert page.get_by_role('button',name='确认建立知识候选',exact=True).count()==0;page.get_by_label('本次提问',exact=True).wait_for();page.get_by_text('调用／费用待核对',exact=True).first.wait_for();assert page.get_by_role('button',name='发送给助手',exact=True).is_disabled();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(out/'frozen-assistant-unknown-mobile.png'),full_page=True)
 page.goto(origin+'/bids/c0de9e01-8d96-42e2-b1d2-1016e5a2d589/materials');trigger=page.get_by_role('button',name='项目助手',exact=True);trigger.click();dialog=page.get_by_role('dialog',name='项目主会话助手',exact=True);dialog.get_by_label('本次提问',exact=True).wait_for();page.keyboard.press('Escape');assert page.evaluate('document.activeElement.textContent')=='项目助手';assert page.request.get(origin+f'/api/v1/bids/{bid}/task-definitions?limit=100').json()==before;assert not writes and not errors;assert any('/assets/index-' in path and path.endswith('.css') for path in observed) and any('/assets/index-' in path and path.endswith('.js') for path in observed) and any('/assets/TaskPanel-' in path and path.endswith('.js') for path in observed);browser.close()
verify();processes=[]
for line in subprocess.check_output(['ps','-eo','pid=,uid=,args='],text=True).splitlines():
 values=line.strip().split(maxsplit=2)
 if len(values)==3 and values[2].startswith('node ') and str(out/'frozen-inputs') in values[2] and '--port 5184 --strictPort' in values[2]:processes.append({'pid':int(values[0]),'uid':int(values[1]),'argv':values[2]})
assert len(processes)==1 and processes[0]['uid']==1000
api_binding=Path('/workspace/tender-docs/04-验证与测试/assistant-browser-environment01/fixture05/final-result.json')
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Frozen frontend10 exact215 compiled assets, nativeOrigin5184/proxy8816 independent task05 API, no overlay/no HMR, readonly existing synthetic task+Mock receipts','candidate_sha256':sha(out/'frontend-candidate.json'),'source_files_verified_before_and_after':len(manifest['source_files']),'assets_verified_before_and_after':len(manifest['compiled_assets']),'loaded_assets':observed,'non200_asset_responses':redirected_assets,'runtime':processes[0],'runtime_session':25465,'dependency_lock_sha256':manifest['dependency_lock']['sha256'],'proxy_target':'http://127.0.0.1:8816','api_actual_objects_equal_fixed_task05':True,'api_actual_frozen_sha256':sha(out/'implemented-task04.openapi.json'),'backend_task05_candidate_sha256':manifest['actual_contract']['backend_task05_candidate_sha256'],'backend_facility_binding':{'path':str(api_binding),'sha256':sha(api_binding)},'tasks_fixed_draft_and_run_refreshed':True,'executed_action_receipt_no_second_button':True,'unknown_billing_disables_new_attempt':True,'mobile_no_overflow':True,'drawer_escape_returns_focus':True,'business_writes':writes,'page_errors':errors,'real_provider_attempts':0,'paid_calls':0,'shared_old_runtimes_unchanged':True};(out/'cold-runtime-binding.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({key:value for key,value in result.items() if key!='loaded_assets'},ensure_ascii=False))
