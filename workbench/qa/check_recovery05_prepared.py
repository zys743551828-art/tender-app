"""Offline cold load of the prepared OPS05 tree. No target or external IO."""
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

prepared=Path(sys.argv[1])
cfg=json.loads(prepared.read_text())
root=Path(cfg['root'])
output=Path('/workspace/tender-docs/04-验证与测试/application-recovery-independent-checks/code-05-single-target-plan/prepared-cold-load.json')
assert not output.exists()
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
for item in cfg['inputs']:
    assert sha(item['path'])==item['sha256']
sys.path.insert(0,str(root))
import psycopg
attempts=[]
def forbidden(*a,**k):
    attempts.append('external_io')
    raise AssertionError('EXTERNAL_IO_FORBIDDEN')
psycopg.connect=forbidden
socket.create_connection=forbidden
subprocess.run=forbidden
from deploy.application_recovery import archive,binding,security as s
assert s.ROOT==root
manifest=archive.validate(Path(cfg['directory'])/'archive')
binding.install(cfg['backend'])
runtime=s.api_environment('postgresql://synthetic:synthetic@127.0.0.1:1/synthetic')
os.environ.clear();os.environ.update(runtime)
import apps.api.main
spec=apps.api.main.app.openapi()
raw=(json.dumps(spec,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
methods={'get','post','put','patch','delete','options','head','trace'}
origins=[]
expected={i['path']:i['sha256'] for i in cfg['inputs']}
for name,module in sorted(sys.modules.items()):
    if name=='deploy' or name.startswith('deploy.'):
        path=getattr(module,'__file__',None)
        if path:
            assert path in expected and sha(path)==expected[path]
            origins.append({'module':name,'path':path,'sha256':sha(path)})
assert not attempts
report={'status':'cold_load_and_local_archive_validate_passed_no_actual_restore','prepared_sha256':sha(prepared),'protocol_sha256':cfg['protocol_sha256'],'script_sha256':sha(__file__),'loaded_recovery_sources':origins,'loaded_backend_sources':binding.require().origins(),'local_archive_tables':len(manifest['tables']),'local_archive_objects':len(manifest['objects']),'actual':{'paths':len(spec['paths']),'operations':sum(k in methods for p in spec['paths'].values() for k in p),'schemas':len(spec.get('components',{}).get('schemas',{})),'json_sorted_indent2_newline_sha256':hashlib.sha256(raw).hexdigest()},'external_attempts':attempts,'real_pg':False,'real_docker':False,'cloud_calls':0,'provider_calls':0,'limits':['OpenAPI generation is an offline shape check, not endpoint execution','Target restore and runtime API login remain pending']}
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':report['status'],'actual':report['actual'],'result_sha256':sha(output)}))
