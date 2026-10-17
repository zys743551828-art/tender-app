"""Single-purpose frozen API child; network HTTP transports are denied, local ASGI only."""
import json
import os
import socket
import sys
from pathlib import Path
import httpx
import urllib.request

attempts=[]
def forbidden(*args,**kwargs):
    attempts.append('external_http_or_socket')
    raise RuntimeError('RECOVERY_DB_ONLY_EXTERNAL_IO_FORBIDDEN')
httpx.HTTPTransport.handle_request=forbidden
httpx.AsyncHTTPTransport.handle_async_request=forbidden
urllib.request.urlopen=forbidden
# libpq uses the one explicit loopback API DSN; no Python remote socket is needed.
socket.create_connection=forbidden
socket.socket.connect=forbidden
payload=json.loads(sys.stdin.buffer.read(65537))
assert set(payload)=={'root','backend','fixture','credential'}
root=Path(payload.pop('root'))
sys.path.insert(0,str(root))
from deploy.application_recovery import application,binding,security as s
s.validate_api_environment(os.environ)
result=application.runtime_check({'backend':payload['backend']},payload['fixture'],payload['credential'])
assert not attempts
result['external_http_transports_hard_denied']=True
result['external_attempts']=attempts
result['loaded_backend_modules']=binding.require().origins()
print(json.dumps(result))
