"""Frozen recovery wrapper only, synthetic downstream; never real API/PG/restore."""
from __future__ import annotations
import asyncio
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

BASE = Path('/workspace/tender-docs/04-验证与测试/application-recovery-development-checks/code-05')
OUT = Path('/workspace/tender-docs/04-验证与测试/application-recovery-independent-checks/code-05-single-target-plan/paused-boundary-result.json')
sys.path[:0] = [str(BASE/'frozen-inputs'), str(BASE/'observed-inputs')]
import httpx
import psycopg
from deploy.application_recovery.application import PausedApplication
from deploy.application_recovery import security

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class SyntheticDownstream:
    def __init__(self, status=201):
        self.status = status
        self.calls = []
        self.identity = str(uuid4())
    async def __call__(self, scope, receive, send):
        self.calls.append((scope['method'], scope['path']))
        await send({'type':'http.response.start','status':self.status,'headers':[]})
        await send({'type':'http.response.body','body':json.dumps({'id':self.identity}).encode()})

async def main():
    if OUT.exists():
        raise RuntimeError('REFUSE_OVERWRITE')
    attempts=[]
    def forbidden(*a,**k):
        attempts.append('external_or_subprocess_or_database')
        raise AssertionError('EXTERNAL_IO_FORBIDDEN')
    psycopg.connect = forbidden
    socket.create_connection = forbidden
    subprocess.run = forbidden
    fixture={'ids':{k:str(uuid4()) for k in ['bid','knowledge','report','operation']}}
    cases=[]
    def check(name, value):
        if not value:
            raise AssertionError(name)
        cases.append(name)
    app=SyntheticDownstream(); guard=PausedApplication(app,fixture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guard),base_url='http://synthetic.invalid') as client:
        r=await client.patch('/api/v1/bids/'+fixture['ids']['bid']+'/settings',json={})
        check('old_project_mutation_blocked_before_downstream',r.status_code==423 and not app.calls)
        r=await client.post('/api/v1/bids/'+fixture['ids']['bid']+'/uploads',json={})
        check('uploads_blocked_before_downstream',r.status_code==423 and not app.calls)
        r=await client.get('/api/v1/operations/'+fixture['ids']['operation'])
        check('old_operation_read_not_a_resume_entry',r.status_code==423 and not app.calls)
        r=await client.post('/api/v1/bids',json=guard.create_body)
        check('create_without_key_refused',r.status_code==423 and not app.calls)
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'synthetic-one'},json={**guard.create_body,'auto_review':True})
        check('extra_field_cannot_enable_auto_review',r.status_code==423 and not app.calls)
        r=await client.post('/api/v1/bids',headers=[('Idempotency-Key','one'),('Idempotency-Key','two')],json=guard.create_body)
        check('ambiguous_duplicate_key_refused',r.status_code==423 and not app.calls)
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'one'},content=b' '*8193)
        check('oversized_body_refused_before_downstream',r.status_code==413 and not app.calls)
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'one'},json=guard.create_body)
        check('first_success_binds_one_uuid',r.status_code==201 and guard.new_bid==app.identity and len(app.calls)==1)
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'two'},json=guard.create_body)
        check('new_command_cannot_create_second_project',r.status_code==423 and len(app.calls)==1)
        r=await client.patch('/api/v1/bids/'+app.identity+'/settings',json={'result_reminder':False,'auto_review':True})
        check('bound_project_settings_still_exact_allowlist',r.status_code==423 and len(app.calls)==1)
    # An uncertain 500 permanently consumes the sole command identity; no new key retry.
    app=SyntheticDownstream(500); guard=PausedApplication(app,fixture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guard),base_url='http://synthetic.invalid') as client:
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'unknown-one'},json=guard.create_body)
        check('downstream_500_remains_uncertain',r.status_code==500 and guard.new_bid is None and guard.create_command is not None)
        r=await client.post('/api/v1/bids',headers={'Idempotency-Key':'unknown-two'},json=guard.create_body)
        check('unknown_outcome_cannot_be_retried_with_new_key',r.status_code==423 and len(app.calls)==1)
    safe=security.api_environment('postgresql://synthetic:synthetic@127.0.0.1:1/synthetic')
    check('api_environment_no_inherited_provider_or_owner',not any(k in safe for k in ['DEEPSEEK_API_KEY','OBJECT_STORE_SECRET_KEY','BACKUP_DATABASE_DSN','WORKER_DATABASE_DSN','DATABASE_URL']))
    for name in ['DEEPSEEK_API_KEY','OBJECT_STORE_SECRET_KEY','BACKUP_DATABASE_DSN','WORKER_DATABASE_DSN']:
        try:
            security.validate_api_environment({**safe,name:'synthetic-do-not-log'})
        except security.RecoveryError:
            pass
        else:
            raise AssertionError('foreign_environment_accepted')
    check('foreign_credentials_rejected_by_child_allowlist',True)
    inputs=[]
    candidate=json.loads((BASE/'candidate.json').read_text())
    expected={str(Path(i['archive'])):i['sha256'] for i in candidate['owned_sources']+candidate['observed_dependencies']}
    for name,module in sorted(sys.modules.items()):
        if name=='deploy' or name.startswith('deploy.'):
            path=getattr(module,'__file__',None)
            if path:
                if path not in expected or sha(path)!=expected[path]:
                    raise AssertionError('UNFROZEN_DEPLOY_MODULE')
                inputs.append({'module':name,'path':path,'sha256':sha(path)})
    check('no_external_database_or_subprocess_attempts',not attempts)
    result={'status':'pure_wrapper_boundary_passed_not_actual_api_restore','cases':cases,'loaded_inputs':inputs,'synthetic_downstream':True,'real_pg':False,'real_api':False,'real_docker':False,'cloud_calls':0,'provider_calls':0,'script_sha256':sha(__file__),'limits':['Authentication/CSRF delegated to actual frozen API remains pending real target','No live restore, table readback, native object PUT/GET or recovery timing executed']}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'cases':len(cases),'loaded_inputs':len(inputs),'result_sha256':sha(OUT)}))

if __name__=='__main__':
    asyncio.run(main())
