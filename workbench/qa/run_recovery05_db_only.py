"""Separate no-cloud restore acceptance. Does not read object configuration or call restore()."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

OUT=Path('/workspace/tender-docs/04-验证与测试/application-recovery-independent-checks/code-05-single-target-plan')
PROTOCOL=OUT/'DB-only独立恢复协议01.md'
BASE_PREPARED=Path('/workspace/tender-workbench/.local/qa-recovery05-ea8eb4ed0a5945ac920e75620ea2717e/prepared.json')
SOURCE=Path('/workspace/tender-workbench/.local/backups/application/drill04-20261017-c23d8a71')
CHILD=Path('/workspace/tender-workbench/qa/recovery05_db_only_child.py')
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def check(value,code):
    if not value:raise RuntimeError(code)
def save(p,data):
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def marker(manifest):
    check(sha(SOURCE/'plan.json')=='62a347bdd144c80f1e8ebcbb4c81fb579b70068598aebb4120e4dc8317bc82da','SOURCE_PLAN_CHANGED')
    nonce=read(SOURCE/'plan.json')['nonce']
    check(isinstance(nonce,str) and len(nonce)==32 and all(c in '0123456789abcdef' for c in nonce),'MARKER_SHAPE_INVALID')
    raw=json.dumps({'value':nonce},separators=(',',':')).encode()
    rows=[r for r in manifest['tables'] if r['schema']=='recovery_control' and r['name']=='identity']
    check(len(rows)==1 and rows[0]['rows']==1 and rows[0]['sha256']==hashlib.sha256(len(raw).to_bytes(8,'big')+raw).hexdigest(),'MARKER_NOT_BOUND')
    return nonce
def originals():
    check(sha(BASE_PREPARED)=='3ca8de5f3490ac1e204d6a6040003d21ebbd8b95d3d1cfc26bd5739a7a044a84','BASE_PREPARED_CHANGED')
    base=read(BASE_PREPARED)
    for item in read(OUT/'readonly-result.json')['inputs']+base['inputs']:
        check(sha(item['path'])==item['sha256'],'FROZEN_INPUT_CHANGED')
    marker(read(Path(base['directory'])/'archive/manifest.json'))
    return base
def prepare():
    base=originals();token=uuid4().hex
    directory=Path(base['root'])/'.local/backups/application'/('db-only-'+token)
    directory.mkdir(mode=0o700)
    cfg={'scenario':'db_only_no_cloud','execution_uuid':token,'root':base['root'],'directory':str(directory),'archive':str(Path(base['directory'])/'archive'),'backend':base['backend'],'target_port':55531,'protocol_sha256':sha(PROTOCOL),'driver_sha256':sha(__file__),'child_sha256':sha(CHILD),'base_prepared_sha256':sha(BASE_PREPARED),'created_at':datetime.now(timezone.utc).isoformat(),'state':'prepared_no_docker_or_external_io'}
    save(directory/'prepared.json',cfg);save(OUT/('db-only-prepared-'+token+'.json'),cfg)
    print(json.dumps({'state':cfg['state'],'prepared':str(directory/'prepared.json'),'sha256':sha(directory/'prepared.json'),'protocol_sha256':cfg['protocol_sha256'],'free_bytes':shutil.disk_usage('/workspace').free}))
def execute(path,approved):
    base=originals();cfg=read(path);directory=Path(cfg['directory']);root=Path(cfg['root'])
    check(Path(path)==directory/'prepared.json','PREPARED_PATH_MISMATCH')
    check(cfg['scenario']=='db_only_no_cloud','DB_ONLY_REQUIRED')
    check(sha(PROTOCOL)==cfg['protocol_sha256']==approved,'EXPLICIT_APPROVED_PROTOCOL_SHA_REQUIRED')
    check(sha(__file__)==cfg['driver_sha256'] and sha(CHILD)==cfg['child_sha256'],'QA_SCRIPT_CHANGED')
    check(shutil.disk_usage('/workspace').free>=1536*1048576,'SINGLE_TARGET_1536_MIB_REQUIRED')
    check(not (directory/'execution-intent.json').exists(),'ONE_SHOT_ATTEMPT_ALREADY_STARTED')
    with socket.socket() as probe:probe.bind(('127.0.0.1',cfg['target_port']))
    sys.path.insert(0,str(root))
    from deploy.application_recovery import archive,binding,cluster,definition_equivalence,probes,security as s
    import psycopg
    from psycopg import sql
    check(s.ROOT==root,'FROZEN_ROOT_MISMATCH')
    binding.install(cfg['backend'])
    # Any accidental call to the object's branch fails locally, never becomes an adapter.
    external_attempts=[]
    def forbidden(*args,**kwargs):
        external_attempts.append('object_port_or_http')
        raise RuntimeError('DB_ONLY_OBJECT_OR_HTTP_IO_FORBIDDEN')
    archive.object_port=forbidden
    import httpx
    import urllib.request
    httpx.HTTPTransport.handle_request=forbidden
    httpx.AsyncHTTPTransport.handle_async_request=forbidden
    urllib.request.urlopen=forbidden
    manifest=archive.validate(Path(cfg['archive']))
    intent={'scenario':'db_only_no_cloud','execution_uuid':cfg['execution_uuid'],'nonce':marker(manifest),'backend':cfg['backend'],'target_port':cfg['target_port'],'protocol_sha256':approved,'initial_free_bytes':shutil.disk_usage('/workspace').free,'at':datetime.now(timezone.utc).isoformat()}
    save(directory/'execution-intent.json',intent)
    target=None
    report={'status':'running','scenario':cfg['scenario'],'protocol_sha256':approved,'driver_sha256':sha(__file__),'child_sha256':sha(CHILD),'prepared_sha256':sha(path),'cloud_restore':'blocked_by_automatic_approval_not_executed','cloud_calls':0,'provider_calls':0,'consumers':0,'bucket_list':0,'object_delete':0,'stages':[]}
    def stage(name):
        free=shutil.disk_usage('/workspace').free
        check(free>=256*1048576,'DISK_FREE_BELOW_256_MIB')
        report['stages'].append({'name':name,'free_bytes':free,'at':datetime.now(timezone.utc).isoformat()})
    def rows(c):
        return {(t['schema'],t['name']):Counter(r[0] for r in c.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t').format(sql.Identifier(t['schema']),sql.Identifier(t['name'])))) for t in manifest['tables']}
    try:
        stage('before_create')
        target=cluster.create(directory,intent,'target',owner_label=manifest['owner_label'],backup_group=manifest['backup_group'])
        check(target['system_identifier']!=manifest['source_system_identifier'],'SOURCE_TARGET_CLUSTER_NOT_DISTINCT')
        stage('before_dump_toc')
        with (Path(cfg['archive'])/'database.dump').open('rb') as source,(directory/'dump-toc.txt').open('xb') as toc:
            os.chmod(toc.name,0o600);s.pg_tool(target,'pg_restore',['--list'],stdin=source,stdout=toc,role='ddl')
        check(sum(' TABLE DATA ' in line for line in (directory/'dump-toc.txt').read_text().splitlines())==164,'DUMP_TABLE_COUNT_CHANGED')
        stage('before_db_restore')
        with psycopg.connect(s.connection_dsn(target,'ddl'),autocommit=True) as c:
            s.verify(c,target,'ddl');cluster.assert_ddl_role(c,target)
            check(c.execute("SELECT to_regnamespace('design')").fetchone()==(None,),'TARGET_ALREADY_INITIALIZED')
        with (Path(cfg['archive'])/'database.dump').open('rb') as source:
            s.pg_tool(target,'pg_restore',['--dbname='+target['database'],'--exit-on-error','--single-transaction'],stdin=source,stdout=subprocess.DEVNULL,role='ddl')
        with psycopg.connect(s.connection_dsn(target,'ddl'),autocommit=True) as c:cluster.reassign(c,target)
        with psycopg.connect(s.connection_dsn(target),autocommit=True) as c:
            cluster.accounts(c,target);cluster.finish_ddl(c,target)
        stage('before_restricted_readback')
        with psycopg.connect(s.connection_dsn(target,'reader')) as c:
            c.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');archive.reader_guard(c,target)
            cat=archive.generic.catalog(c);inventory=archive.generic.inventory(c);definitions=archive.detail(c,target)
            save(directory/'actual-readback.json',{'catalog':cat,'tables':inventory,'definitions':definitions})
            check(cat==manifest['catalog'],'CATALOG_MISMATCH')
            check(inventory==manifest['tables'],'TABLE_CONTENT_HASH_MISMATCH')
            check(definition_equivalence.equivalent(manifest['definitions'],definitions),'DEFINITION_OR_ACL_MISMATCH')
            check(len(inventory)==164 and len(definitions['constraints'])==965,'FIXED_SCOPE_COUNT_CHANGED')
            before=rows(c)
        report['database']={'dump_toc_sha256':sha(directory/'dump-toc.txt'),'table_data_entries':164,'row_hashes_exact':True,'catalog_exact':True,'definitions_exact_except_known_check_pair':True,'checks':965,'readback_sha256':sha(directory/'actual-readback.json'),'target_system_identifier_distinct':True,'temporary_ddl_disabled_nonowner':target['temporary_ddl_disabled_and_nonowner']}
        report['permissions']=probes.verify(target)
        stage('before_local_asgi')
        credentials=read(SOURCE/'member-credential.json')
        payload={'root':str(root),'backend':cfg['backend'],'fixture':{'ids':read(SOURCE/'fixture.json')['ids']},'credential':{k:credentials[k] for k in ['login_name','password','old_cookie']}}
        completed=subprocess.run(['/workspace/tender-workbench/.venv/bin/python','-I','-B',str(CHILD)],input=json.dumps(payload).encode(),env=s.api_environment(s.connection_dsn(target,'api')),cwd='/tmp',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90,check=False)
        check(completed.returncode==0 and len(completed.stdout)<=1048576,'DB_ONLY_ASGI_FAILED_PRIVATE_DETAILS_SUPPRESSED')
        app_result=json.loads(completed.stdout)
        check(app_result['new_sync_work_verified'] is True and app_result['external_http_transports_hard_denied'] is True,'ASGI_POSTCONDITION_FAILED')
        with psycopg.connect(s.connection_dsn(target,'reader')) as c:after=rows(c)
        check(all(not(counter-after[k]) for k,counter in before.items()),'ORIGINAL_HISTORY_ROW_CHANGED')
        check(all(before[('design',n)]==after[('design',n)] for n in ['operations','outbox','model_calls']),'OLD_QUEUE_OR_UNKNOWN_FEE_CHANGED')
        check(sum(after[('design','bids')].values())-sum(before[('design','bids')].values())==1,'NEW_BID_COUNT_NOT_ONE')
        originals();check(not external_attempts,'EXTERNAL_IO_ATTEMPTED')
        report['application']=app_result
        report['independent_postconditions']={'all_original_rows_preserved':True,'old_operations_outbox_unknown_fee_identical':True,'exactly_one_new_bid':True,'source_and_prior_archives_unchanged':True}
        report['status']='database_and_local_paused_api_passed_cloud_restore_blocked'
    except Exception as exc:
        report['status']='db_only_failed_preserved_no_retry';report['error_type']=type(exc).__name__
        report['error_code']=str(exc) if isinstance(exc,(s.RecoveryError,RuntimeError)) else 'PRIVATE_DETAILS_SUPPRESSED'
    finally:
        report['external_attempts']=external_attempts
        if target is not None:
            try:
                cluster.assert_resources(target);s.docker(['stop','--time','30',target['container']],timeout=40)
                cluster.assert_resources(target);s.docker(['rm',target['container']])
                report['cleanup']={'own_container_removed':True,'container_id':target['container_id'],'volume_retained':target['volume'],'source_or_prior_target_touched':False}
            except Exception:
                report['status']='db_only_cleanup_pending';report['cleanup']={'status':'manual_exact_identity_inspection_required'}
        else:report['cleanup']={'status':'create_not_returned_inspect_only_own_creating_receipt'}
        report['loaded_backend_modules']=binding.require().origins()
        report['finished_at']=datetime.now(timezone.utc).isoformat();report['free_bytes_after']=shutil.disk_usage('/workspace').free
        report['limits']=['Native cloud object restore/download remains blocked and was not simulated','No source online SQL, production RPO/RTO, inflight resumption, newest A2/Score/Scale or real business qualification','Actual ASGI is local memory transport, not browser/public network server']
        save(directory/'qa-result.json',report);save(OUT/('db-only-actual-'+cfg['execution_uuid']+'.json'),report)
        print(json.dumps({'status':report['status'],'result':str(directory/'qa-result.json'),'sha256':sha(directory/'qa-result.json')}))
def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','execute']);p.add_argument('--prepared',type=Path);p.add_argument('--approved-protocol-sha256');a=p.parse_args()
    if a.phase=='prepare':prepare()
    else:
        check(a.prepared is not None,'PREPARED_REQUIRED');execute(a.prepared,a.approved_protocol_sha256)
if __name__=='__main__':main()
