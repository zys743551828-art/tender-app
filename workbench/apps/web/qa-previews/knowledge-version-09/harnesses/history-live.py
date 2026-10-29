import json,hashlib,datetime,subprocess
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/knowledge-version-09';origin='http://127.0.0.1:5176';assets_origin='http://127.0.0.1:5179';member=json.loads((root/'../../.local/combined_delivery01-test-members.json').read_text())[0];own=json.loads((root/'qa-previews/knowledge-metrics-07/knowledge-live-result.json').read_text());kid=own['knowledge_id'];bid=own['project_id'];m=json.loads((out/'frontend-candidate.json').read_text());digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert all(digest(out/'frozen-inputs'/x['path'])==x['sha256'] for x in m['source_files']);assert all(digest(out/'frozen-dist'/x['path'])==x['sha256'] for x in m['compiled_assets']);writes=[];errors=[];served=[];version_reads=[];stage='login'
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);context=browser.new_context(viewport={'width':390,'height':844});p=context.new_page();p.set_default_timeout(20000)
 def route(r):
  request=r.request;url=request.url
  if url.startswith(origin+'/api/'):
   if request.method in ['POST','PUT','PATCH'] and '/auth/' not in url:
    writes.append({'method':request.method,'path':url.split('/api/v1/')[-1].split('?')[0]});r.abort('blockedbyclient');return
   r.continue_()
  elif url.startswith(origin+'/'):
   response=r.fetch(url=url.replace(origin,assets_origin,1));path=urlsplit(url).path
   if path.startswith('/assets/'):
    expected=next(x for x in m['compiled_assets'] if '/'+x['path']==path);assert hashlib.sha256(response.body()).hexdigest()==expected['sha256'];served.append(path)
   r.fulfill(response=response)
  else:r.continue_()
 def read(response):
  if '/api/v1/knowledge/'+kid+'/versions/' in response.url:version_reads.append({'path':urlsplit(response.url).path,'status':response.status})
 context.route('**/*',route);p.on('pageerror',lambda e:errors.append(type(e).__name__));p.on('response',read)
 try:
  p.goto(origin+'/projects',wait_until='domcontentloaded');p.get_by_label('账号',exact=True).fill(member['login']);p.get_by_label('密码',exact=True).fill(member['password']);p.get_by_role('button',name='登录工作区',exact=True).click();p.get_by_role('button',name='＋ 新建投标',exact=True).wait_for();head=p.request.get(origin+f'/api/v1/knowledge/{kid}').json();versions=p.request.get(origin+f'/api/v1/knowledge/{kid}/versions').json()['items'];old=next(x for x in versions if x['version_no']==1);assert old['version_id']!=head['version_id'];old_full=p.request.get(origin+f'/api/v1/knowledge/{kid}/versions/{old["version_id"]}').json();assert old_full['version_id']==old['version_id'];before=p.request.get(origin+f'/api/v1/bids/{bid}/facts').json();params={'item':kid,'bid':bid,'trace':own['trace_id'],'citation':own['citation_id']};initial=origin+'/knowledge?'+urlencode(params)
  stage='select-v1';p.goto(initial,wait_until='domcontentloaded');p.get_by_text(f'版本 {head["version_no"]} · 最新维护版本',exact=True).wait_for();p.get_by_role('button',name='查看知识版本历史',exact=True).click();p.get_by_role('button',name='版本 1 · 待完善候选',exact=True).click();p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();selected_url=p.url;query=parse_qs(urlsplit(selected_url).query);assert query['version']==[old['version_id']];assert all(query[k]==[v] for k,v in params.items());assert p.get_by_role('button',name='完善并追加候选版本',exact=True).count()==0;assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'v1-fixed-url-mobile.png'),full_page=True)
  stage='refresh-v1';p.reload(wait_until='domcontentloaded');p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();assert p.url==selected_url;p.get_by_role('heading',name='已登记参考的历史与当前资格',exact=True).wait_for();assert p.get_by_role('button',name='登记为本项目参考',exact=True).first.is_disabled();p.screenshot(path=str(out/'v1-after-refresh-mobile.png'),full_page=True)
  stage='return-current-and-history';p.get_by_role('button',name='返回最新维护版本',exact=True).click();p.get_by_text(f'版本 {head["version_no"]} · 最新维护版本',exact=True).wait_for();query=parse_qs(urlsplit(p.url).query);assert 'version' not in query;assert all(query[k]==[v] for k,v in params.items());p.go_back();p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();assert p.url==selected_url;p.go_forward();p.get_by_text(f'版本 {head["version_no"]} · 最新维护版本',exact=True).wait_for();p.go_back();p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();p.reload(wait_until='domcontentloaded');p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();assert p.url==selected_url;assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
  stage='invalid-version-no-head-fallback';bad={**params,'version':'00000000-0000-4000-8000-000000000001'};p.goto(origin+'/knowledge?'+urlencode(bad),wait_until='domcontentloaded');p.locator('.knowledge-detail').get_by_role('alert').wait_for();assert p.locator('.knowledge-detail h2').count()==0;p.goto(selected_url,wait_until='domcontentloaded');p.get_by_text('版本 1 · 按明确版本查阅',exact=True).wait_for();assert p.request.get(origin+f'/api/v1/bids/{bid}/facts').json()==before;assert not writes and not errors
  processes=[]
  for line in subprocess.check_output(['ps','-eo','pid=,uid=,args='],text=True).splitlines():
   values=line.split(maxsplit=2)
   if len(values)==3 and values[2].startswith('node ') and str(out/'frozen-inputs') in values[2] and '--port 5179' in values[2]:processes.append({'pid':int(values[0]),'uid':int(values[1]),'argv':values[2]})
  assert len(processes)==1 and processes[0]['uid']==1000
  result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'09fixed compiled asset overlay at Origin5176, actual unchanged8806 knowledge API; own previously saved synthetic07project; not09independent deployment','candidate_sha256':digest(out/'frontend-candidate.json'),'source_files_verified':len(m['source_files']),'build_assets_verified':len(m['compiled_assets']),'served_assets_verified':sorted(set(served)),'runtime':processes[0],'project_id':bid,'knowledge_id':kid,'historical_version_id':old['version_id'],'historical_version_no':old['version_no'],'current_version_id':head['version_id'],'current_version_no':head['version_no'],'historical_server_payload_sha256':hashlib.sha256(json.dumps(old_full,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'selected_fixed_url':selected_url,'old_version_readonly':True,'reload_keeps_explicit_version':True,'browser_back_forward_keeps_identity':True,'return_current_removes_only_version':True,'bid_trace_citation_preserved':True,'trace_citation_restored_and_invalid_new_reference_disabled':True,'missing_version_never_falls_back_to_head':True,'facts_unchanged':True,'mobile_no_overflow':True,'version_reads':version_reads,'business_writes':writes,'page_errors':errors,'paid_calls':0}
  (out/'history-live-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['served_assets_verified','version_reads']},ensure_ascii=False))
 except Exception as e:
  p.screenshot(path=str(out/'history-live-failure.png'),full_page=True);(out/'history-live-failure.json').write_text(json.dumps({'stage':stage,'error_type':type(e).__name__,'writes':writes,'page_errors':errors},ensure_ascii=False,indent=2)+'\n');print({'stage':stage,'error_type':type(e).__name__});raise
 finally:browser.close()
