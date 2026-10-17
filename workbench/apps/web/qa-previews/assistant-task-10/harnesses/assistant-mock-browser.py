import json,datetime,subprocess,time,uuid,hashlib
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench');out=root/'apps/web/qa-previews/assistant-task-10';origin='http://127.0.0.1:5184';members=json.loads((root/'.local/assistant_ui01-test-members.json').read_text());bid='c0de9e01-8d96-42e2-b1d2-1016e5a2d589';writes=[];accepted=[];page_errors=[];modes=[];checks=[];stage='start'
def control(mode,scope='global'):
 subprocess.run([str(root/'.venv/bin/python'),str(root/'qa/assistant_browser_fixture/launch.py'),'control','--config',str(root/'.local/assistant_ui01-fixture04final.json'),'--response',mode,'--scope',scope],cwd=root,check=True,capture_output=True);modes.append({'mode':mode,'scope':scope})
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1440,'height':1000});p=ctx.new_page();p.set_default_timeout(20000)
 def received(response):
  path=urlsplit(response.url).path
  if response.request.method not in ['GET','HEAD'] and '/auth/' not in path:
   writes.append({'method':response.request.method,'path':path,'status':response.status})
   if path.endswith('/turns') and response.status==202:accepted.append(response.json()['id'])
 p.on('response',received);p.on('pageerror',lambda e:page_errors.append(type(e).__name__))
 def login(page,member):
  page.goto(origin+'/projects');page.get_by_label('账号',exact=True).fill(member['login']);page.get_by_label('密码',exact=True).fill(member['password']);page.get_by_role('button',name='登录工作区',exact=True).click();page.get_by_role('button',name='＋ 新建投标',exact=True).wait_for()
 def wait_job(job_id,states):
  for _ in range(150):
   value=p.request.get(origin+'/api/v1/assistant/jobs/'+job_id).json()
   if value.get('operation',{}).get('state') in states and (value.get('publication') or states!=['succeeded']):return value
   p.wait_for_timeout(200)
  raise AssertionError('job did not reach expected persisted state')
 def ask(text):
  p.get_by_label('本次提问',exact=True).fill(text)
  for attempt in range(3):
   p.get_by_role('button',name='已核对会话，按当前修订继续',exact=True).click()
   with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/turns')) as promise:p.get_by_role('button',name='发送给助手',exact=True).click()
   response=promise.value
   if response.status==202:return response.json()['id']
   assert response.status==412,response.status
   p.get_by_text('会话或来源已变化，输入保留。请刷新消息与可信来源后明确核对基准；旧来源不会自动换成当前版。',exact=True).wait_for()
  raise AssertionError('turn was not accepted after explicit baseline review')
 try:
  login(p,members[1]);stage='global-main';p.goto(origin+'/assistant');create=p.get_by_role('button',name='创建并继续主会话',exact=True);create.or_(p.get_by_label('本次提问')).first.wait_for()
  if create.is_visible():create.click()
  p.get_by_label('本次提问').wait_for();global_main=p.request.get(origin+'/api/v1/assistant/global-conversations/main').json();assert global_main['bid_id'] is None
  stage='global-answer';control('answer');accepted.clear();job=ask('前端10显式合成回答 '+uuid.uuid4().hex);published=wait_job(job,['succeeded']);assert published['publication']['state']=='published';p.get_by_text('显式离线合成机制回答：请核对原文。本回答用于界面验收，不代表真实模型效果或正式评审。',exact=True).first.wait_for();p.reload();p.get_by_text('显式离线合成机制回答：请核对原文。本回答用于界面验收，不代表真实模型效果或正式评审。',exact=True).first.wait_for();checks.append({'case':'global-real-api-mock-worker-published-and-refreshed','job_id':job,'passed':True})
  stage='trusted-at-action';control('knowledge_action');p.get_by_role('button',name='＋ / @ 选择可信来源',exact=True).click();picker=p.get_by_role('region',name='可信来源选择');picker.get_by_label('来源所属项目',exact=True).select_option(label='显式合成助手浏览器项目');picker.get_by_label('助手来源类型',exact=True).select_option('project');picker.get_by_role('checkbox').first.wait_for();picker.get_by_role('checkbox').first.check();picker.get_by_label('助手来源类型',exact=True).select_option('document');picker.get_by_role('checkbox').first.wait_for();picker.get_by_role('checkbox').first.check();assert p.locator('.assistant-selected-sources > div').count()==2;accepted.clear();job=ask('前端10显式合成知识候选 '+uuid.uuid4().hex);wait_job(job,['succeeded']);confirm=p.get_by_role('button',name='确认建立知识候选',exact=True);confirm.wait_for();card=p.locator('.assistant-action-card').filter(has=confirm);assert card.get_by_text('需要明确处理的提议',exact=True).count()==1;action_id=card.locator('details').inner_text().split('记录')[-1].split('；')[0].strip() if False else None
  with p.expect_response(lambda r:'/assistant/actions/' in r.url and r.url.endswith('/resolve') and r.request.method=='POST') as promise:confirm.click()
  resolved=promise.value.json();assert resolved['state']=='executed';action_id=resolved['action_id'];knowledge_id=resolved['result']['assistant_resolution']['domain_result']['id'];p.locator('.assistant-action-card').get_by_text('已执行并留存结果',exact=True).first.wait_for();p.reload();p.get_by_text('已执行并留存结果',exact=True).first.wait_for();assert p.get_by_role('button',name='确认建立知识候选',exact=True).count()==0;assert sum(w['path'].endswith('/actions/'+action_id+'/resolve') for w in writes)==1;checks.append({'case':'trusted-project-document-at-and-action-one-confirm-persisted','job_id':job,'action_id':action_id,'knowledge_id':knowledge_id,'passed':True})
  stage='same-action-other-member';second=browser.new_context();p2=second.new_page();login(p2,members[0]);p2.goto(origin+'/assistant?action='+action_id);p2.get_by_text('已执行并留存结果',exact=True).first.wait_for();assert p2.get_by_role('button',name='确认建立知识候选',exact=True).count()==0;r=p2.request.get(origin+'/api/v1/assistant/actions/'+action_id);assert r.status==200 and r.json()['state']=='executed';assert p2.request.get(origin+f'/api/v1/assistant/global-conversations/{global_main["id"]}/messages').status==404;second.close();checks.append({'case':'shared-action-receipt-but-global-conversation-private','passed':True})
  stage='hold-cancel';control('hold');accepted.clear();job=ask('前端10显式合成取消 '+uuid.uuid4().hex);p.get_by_role('button',name='请求取消这次处理',exact=True).click();p.get_by_text('取消请求已收到，尚未到实际取消终态；费用另行核对。',exact=True).first.wait_for();control('answer');cancelled=wait_job(job,['cancelled']);assert cancelled['cancellation_terminal'] and cancelled['model_call'] is None;p.locator('.assistant-jobs > details > summary').click();p.get_by_text('服务端已记录取消终态。',exact=True).first.wait_for();checks.append({'case':'hold-accepted-then-real-cancel-terminal-without-model-call','job_id':job,'passed':True})
  stage='project-answer';control('answer','project');p.goto(origin+'/assistant?bid='+bid);p.get_by_label('本次提问').wait_for();accepted.clear();job=ask('前端10项目主会话显式合成 '+uuid.uuid4().hex);project_result=wait_job(job,['succeeded']);assert project_result['scope']=='project' and project_result['bid_id']==bid;p.get_by_text('显式离线合成机制回答：请核对原文。本回答用于界面验收，不代表真实模型效果或正式评审。',exact=True).first.wait_for();checks.append({'case':'project-assistant-engine-publishes-to-same-main','job_id':job,'passed':True})
  stage='unknown';control('unknown');p.goto(origin+'/assistant');p.get_by_label('本次提问').wait_for();accepted.clear();job=ask('前端10费用未知不新尝试 '+uuid.uuid4().hex);unknown=wait_job(job,['failed']);assert unknown['model_call']['state']=='unknown' and unknown['requires_billing_reconciliation'];p.get_by_text('调用／费用待核对',exact=True).first.wait_for();p.get_by_label('本次提问').fill('保留的新草稿不用于重复付费');assert p.get_by_role('button',name='发送给助手',exact=True).is_disabled();p.reload();p.get_by_text('调用／费用待核对',exact=True).first.wait_for();assert p.get_by_label('本次提问').input_value()=='保留的新草稿不用于重复付费';assert p.get_by_role('button',name='发送给助手',exact=True).is_disabled();checks.append({'case':'unknown-billing-persists-and-disables-new-attempt-after-refresh','job_id':job,'passed':True})
  stage='390';p.set_viewport_size({'width':390,'height':844});assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'assistant-mock-unknown-mobile.png'),full_page=True);p.goto(origin+'/assistant?bid='+bid);p.get_by_label('本次提问').wait_for();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'assistant-mock-project-mobile.png'),full_page=True);assert not page_errors;control('hold');result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Native5184 real8816 independent fixedtask04 API/DB, role-separated direct fixture worker/publisher, explicit MockTransport, local-original bytes; NOT real provider, NOT Kafka acceptance','actual_sha256':hashlib.sha256((out/'implemented-task04.openapi.json').read_bytes()).hexdigest(),'checks':checks,'writes':writes,'control_modes':modes,'mobile_no_overflow':True,'page_errors':page_errors,'real_provider_attempts':0,'paid_calls':0};(out/'assistant-mock-browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'checks':len(checks),'passed':True,'real_provider_attempts':0,'paid_calls':0},ensure_ascii=False))
 except Exception as error:
  p.screenshot(path=str(out/'assistant-mock-browser-failure.png'),full_page=True);(out/'assistant-mock-browser-failure.json').write_text(json.dumps({'stage':stage,'error_type':type(error).__name__,'writes':writes,'page_errors':page_errors},ensure_ascii=False,indent=2)+'\n');print({'stage':stage,'error_type':type(error).__name__});raise
 finally:browser.close()
