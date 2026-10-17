import json,datetime,hashlib,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
root=Path('/workspace/tender-workbench/apps/web');out=root/'qa-previews/assistant-continuation-11';origin='http://127.0.0.1:5184';native=os.environ.get('NATIVE')=='1';asset='http://127.0.0.1:5186';member=json.loads((root/'../../.local/assistant_ui01-test-members.json').read_text())[1];checks=[];writes=[];errors=[];assets={};bid='c0de9e01-8d96-42e2-b1d2-1016e5a2d589'
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1440,'height':1000});page=ctx.new_page();page.set_default_timeout(20000)
 def route(r):
  path=urlsplit(r.request.url).path
  if path.startswith('/api/'):
   if r.request.method not in ['GET','HEAD'] and '/auth/' not in path:
    writes.append({'path':path,'method':r.request.method});r.abort();return
   r.continue_();return
  if native:r.continue_()
  else:r.fulfill(response=ctx.request.get(asset+path))
 ctx.route(origin+'/**',route)
 def response(r):
  path=urlsplit(r.url).path
  if path.startswith('/assets/') and r.status==200:assets[path]=hashlib.sha256(r.body()).hexdigest()
 page.on('response',response);page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(origin+'/projects');page.get_by_label('账号',exact=True).fill(member['login']);page.get_by_label('密码',exact=True).fill(member['password']);page.get_by_role('button',name='登录工作区',exact=True).click();page.get_by_role('button',name='＋ 新建投标',exact=True).wait_for()
 def input_ready():
  page.get_by_label('本次提问',exact=True).wait_for();page.wait_for_function("document.activeElement?.getAttribute('aria-label') === '本次提问'");page.wait_for_timeout(300)
 def box():return page.get_by_label('本次提问',exact=True).bounding_box()
 def visible():
  b=box();assert b and b['y']>=0 and b['y']+b['height']<=page.viewport_size['height'];return b
 for width,height in [(1440,1000),(390,844)]:
  print('viewport',width,flush=True);page.set_viewport_size({'width':width,'height':height});page.goto(origin+'/assistant');input_ready();initial=visible();assert page.get_by_role('button',name='发送给助手',exact=True).is_disabled();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(out/f'{width}-latest.png'))
  page.reload();input_ready();refreshed=visible();page.wait_for_timeout(4200);assert page.get_by_label('本次提问',exact=True).evaluate('(e)=>document.activeElement===e')
  page.mouse.move(width//2,height//2);page.mouse.wheel(0,-10000);page.wait_for_timeout(350);old=page.evaluate('scrollY');assert old<1000;page.wait_for_timeout(4500);assert abs(page.evaluate('scrollY')-old)<4
  jump=page.get_by_role('button',name='回到最新／继续提问',exact=True);jump.focus();page.keyboard.press('Tab');page.keyboard.press('Shift+Tab');assert jump.evaluate('(e)=>document.activeElement===e');page.keyboard.press('Enter');assert page.get_by_label('本次提问',exact=True).evaluate('(e)=>document.activeElement===e');visible()
  checks.append({'viewport':width,'cold_and_refresh_input_visible':True,'initial_input_box':initial,'refreshed_input_box':refreshed,'history_scroll_preserved_after_poll':old,'keyboard_continue_focus':True,'unknown_send_disabled':True,'no_overflow':True})
 global_input=page.get_by_label('本次提问',exact=True);global_input.fill('frontend11只读草稿-全局');page.get_by_label('助手会话范围',exact=True).select_option(bid);input_ready();page.get_by_label('本次提问',exact=True).fill('frontend11只读草稿-项目');page.get_by_label('助手会话范围',exact=True).select_option('');input_ready();assert page.get_by_label('本次提问',exact=True).input_value()=='frontend11只读草稿-全局';page.go_back();input_ready();assert page.get_by_label('本次提问',exact=True).input_value()=='frontend11只读草稿-项目';visible();checks.append({'scoped_unsent_drafts_and_browser_back':True})
 page.goto(origin+f'/bids/{bid}/materials');trigger=page.get_by_role('button',name='项目助手',exact=True);trigger.click();dialog=page.get_by_role('dialog',name='项目主会话助手',exact=True);input_ready();visible();assert dialog.get_by_label('本次提问',exact=True).input_value()=='frontend11只读草稿-项目';page.screenshot(path=str(out/'390-drawer.png'));page.keyboard.press('Escape');assert trigger.evaluate('(e)=>document.activeElement===e');checks.append({'mobile_drawer_visible_input_and_draft':True,'escape_returns_trigger':True})
 trigger.click();input_ready()
 for _ in range(25):
  page.keyboard.press('Tab');assert dialog.evaluate('(d)=>d.contains(document.activeElement)')
 dialog.get_by_role('link',name='全屏打开同一主会话',exact=True).click();input_ready();visible();assert page.get_by_label('本次提问',exact=True).input_value()=='frontend11只读草稿-项目';assert page.get_by_role('dialog').count()==0;checks.append({'drawer_tab_trap_and_fullscreen_same_draft':True})
 page.goto(origin+'/assistant?action=90110e14-e937-43ca-a5bd-1cc209575ef1');page.get_by_role('heading',name='明确链接的操作提议',exact=True).wait_for();page.get_by_label('本次提问',exact=True).wait_for();page.wait_for_timeout(4500);assert page.evaluate('scrollY')<100;assert page.get_by_role('button',name='确认建立知识候选',exact=True).count()==0;page.get_by_role('button',name='回到最新／继续提问',exact=True).click();visible();checks.append({'explicit_action_link_preserves_position':True,'executed_receipt_preserved':True})
 assert not writes and not errors;browser.close()
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'mode':'native11' if native else 'development11asset_overlay_only','origin':origin,'api':'http://127.0.0.1:8816','checks':checks,'loaded_assets':assets,'blocked_business_writes':writes,'page_errors':errors,'model_calls':0,'control_changes':0,'task_runs':0};(out/('native-browser-result.json' if native else 'development-browser-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'mode':result['mode'],'checks':len(checks),'assets':len(assets),'writes':writes,'errors':errors},ensure_ascii=False))
