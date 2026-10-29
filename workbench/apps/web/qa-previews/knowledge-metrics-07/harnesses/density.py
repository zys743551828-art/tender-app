import json,datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench');out=root/'apps/web/qa-previews/knowledge-metrics-07';origin='http://127.0.0.1:5176';member=json.loads((root/'.local/combined_delivery01-test-members.json').read_text())[0];fixture=json.loads((root/'apps/web/qa-previews/submission-report-06/standard-report-live-result.json').read_text());bid=fixture['project_id'];review=fixture['review_id'];writes=[];rows=[]
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);c=b.new_context();p=c.new_page()
 def route(r):
  url=r.request.url
  if url.startswith(origin+'/api/'):
   if r.request.method in ['POST','PUT','PATCH'] and '/auth/' not in url:writes.append(r.request.method+' '+url.split('/api/v1/')[-1].split('?')[0])
   r.continue_()
  elif url.startswith(origin+'/'):r.fulfill(response=r.fetch(url=url.replace(origin,'http://127.0.0.1:5177',1)))
  else:r.continue_()
 c.route('**/*',route);p.goto(origin+'/projects',wait_until='domcontentloaded');p.get_by_label('账号',exact=True).fill(member['login']);p.get_by_label('密码',exact=True).fill(member['password']);p.get_by_role('button',name='登录工作区',exact=True).click();p.get_by_role('button',name='＋ 新建投标',exact=True).wait_for()
 for width in [1440,390]:
  p.set_viewport_size({'width':width,'height':844});p.goto(origin+f'/bids/{bid}/review?review={review}',wait_until='domcontentloaded');p.get_by_text('已完成 2 项处理',exact=True).wait_for();p.get_by_role('combobox',name='报告用途与格式').wait_for();p.wait_for_timeout(200)
  summary=p.get_by_text('已完成 2 项处理',exact=True);assert not summary.evaluate('(e)=>e.parentElement.open');assert p.get_by_role('button',name='查看风险与本轮处理',exact=True).is_visible();assert p.evaluate('document.documentElement.scrollWidth<=innerWidth');nextbox=p.get_by_role('button',name='查看风险与本轮处理',exact=True).bounding_box();formatbox=p.get_by_role('combobox',name='报告用途与格式').bounding_box();rows.append({'width':width,'next_action':nextbox,'report_format':formatbox,'completed_folded':True,'no_overflow':True});p.screenshot(path=str(out/f'review-density-{width}.png'),full_page=True);summary.click();assert summary.evaluate('(e)=>e.parentElement.open');assert p.get_by_text('执行已结束',exact=True).count()==2
 assert not writes;(out/'review-density-result.json').write_text(json.dumps({'scope':'read-only developer delta, isolated frontend07 assets overlay; fixed synthetic review identity unchanged, no model execution','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'observations':rows,'business_writes':writes,'paid_calls':0},ensure_ascii=False,indent=2)+'\n');print(rows);b.close()
