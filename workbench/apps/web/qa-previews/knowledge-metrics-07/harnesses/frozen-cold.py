import json,hashlib,subprocess,datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/knowledge-metrics-07';origin='http://127.0.0.1:5176';candidate=json.loads((out/'frontend-candidate.json').read_text());assets=json.loads((out/'build-assets.json').read_text());d=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert all(d(out/'frozen-inputs'/row['path'])==row['sha256'] for row in candidate['source_files']);assert all(d(out/'frozen-dist'/row['path'])==row['sha256'] for row in assets['files']);member=json.loads((root/'../../.local/combined_delivery01-test-members.json').read_text())[0];prior=json.loads((out/'knowledge-live-result.json').read_text());bid=prior['project_id'];writes=[];errors=[];asset_requests=[]
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);c=b.new_context(viewport={'width':390,'height':844});p=c.new_page()
 def route(r):
  url=r.request.url
  if url.startswith(origin+'/api/'):
   if r.request.method in ['POST','PUT','PATCH'] and '/auth/' not in url:writes.append({'method':r.request.method,'path':url.split('/api/v1/')[-1].split('?')[0]})
   r.continue_()
  elif url.startswith(origin+'/'):
   path=url.split(origin,1)[1].split('?')[0];response=r.fetch(url=url.replace(origin,'http://127.0.0.1:5177',1))
   if path.startswith('/assets/'):
    content=response.body();entry=next(x for x in assets['files'] if '/'+x['path']==path);assert hashlib.sha256(content).hexdigest()==entry['sha256'];asset_requests.append(path)
   r.fulfill(response=response)
  else:r.continue_()
 c.route('**/*',route);p.on('pageerror',lambda e:errors.append(type(e).__name__));p.goto(origin+'/projects',wait_until='domcontentloaded');p.get_by_label('账号',exact=True).fill(member['login']);p.get_by_label('密码',exact=True).fill(member['password']);p.get_by_role('button',name='登录工作区',exact=True).click();p.get_by_role('button',name='＋ 新建投标',exact=True).wait_for();p.goto(origin+f'/knowledge?bid={bid}&trace={prior["trace_id"]}&citation={prior["citation_id"]}',wait_until='domcontentloaded');p.get_by_role('heading',name='已登记参考的历史与当前资格',exact=True).wait_for();p.get_by_text('当前不能据此新增选用；当时内容仍保留',exact=True).first.wait_for();assert p.get_by_role('button',name='登记为本项目参考',exact=True).first.is_disabled();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'frozen-cold-knowledge-mobile.png'),full_page=True)
 p.goto(origin+f'/bids/{bid}/outcomes',wait_until='domcontentloaded');p.get_by_role('button',name='登记／查看此实交的实际结果',exact=True).click();p.get_by_role('heading',name='已明确未中标',exact=True).first.wait_for();p.get_by_text('查看结果历史（已加载5／共5条）',exact=True).click();p.get_by_role('heading',name='中标候选',exact=True).wait_for();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'frozen-cold-results-mobile.png'),full_page=True)
 p.goto(origin+'/metrics',wait_until='domcontentloaded');p.get_by_text('限定项目（已选0个，最多20个）',exact=True).click();p.get_by_role('checkbox',name=prior['title'],exact=True).check();p.get_by_role('button',name='更新统计范围',exact=True).click();p.get_by_text('统计范围：明确选择的1个项目。按实际提交时间：',exact=False).wait_for();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');p.screenshot(path=str(out/'frozen-cold-metrics-mobile.png'),full_page=True);assert not writes and not errors
 rows=[]
 for line in subprocess.check_output(['ps','-eo','pid=,uid=,args='],text=True).splitlines():
  parts=line.split(maxsplit=2)
  if len(parts)==3 and parts[2].startswith('node ') and 'vite preview' in parts[2] and '--port 5177' in parts[2]:rows.append({'pid':int(parts[0]),'uid':int(parts[1]),'argv':parts[2]})
 assert len(rows)==1 and rows[0]['uid']==1000
 result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'cold fixed compiled07 frontend asset overlay at Origin5176; actualAPI8806 unchanged; not independently deployed07 same-origin acceptance','candidate_sha256':d(out/'frontend-candidate.json'),'source_tree_sha256':candidate['source_tree_sha256'],'source_files_verified':len(candidate['source_files']),'build_assets_verified':len(assets['files']),'served_assets_sha_verified':sorted(set(asset_requests)),'runtime':rows[0],'asset_service':'http://127.0.0.1:5177','root':str(out/'frozen-inputs'),'compiled_root':str(out/'frozen-dist'),'lock_sha256':d(out/'frozen-inputs/package-lock.json'),'api_contract_sha256':candidate['actual_contract']['sha256'],'restored_trace_and_citation_old_bytes':True,'current_ineligible_new_reference_disabled':True,'server_result_current_and_history':True,'metrics_explicit_project_filter':True,'mobile_no_overflow':True,'business_writes':writes,'page_errors':errors,'paid_calls':0}
 (out/'runtime-cold-start.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='served_assets_sha_verified'},ensure_ascii=False));b.close()
