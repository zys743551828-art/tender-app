"""Purpose ports cannot read business profiles just by importing shared errors."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}


@pytest.mark.parametrize(
    "module",
    [
        "packages.domain.providers.deepseek_vision",
        "packages.domain.providers.json_protocol",
        "packages.model_governance.package_current_sources",
        "packages.model_governance.package_current_scope",
    ],
)
def test_purpose_import_never_enters_business_runtime_or_reads_env(module):
    code = """import importlib,json,os,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
original_exists=Path.exists
original_read=Path.read_text
reads=[]
def exists(path):
    return True if path.name=='.env' else original_exists(path)
def read(path,*args,**kwargs):
    if path.name=='.env':
        reads.append('synthetic profile read')
        return 'SHOULD_NOT_LOAD_BUSINESS_PROFILE=synthetic'
    return original_read(path,*args,**kwargs)
with patch.object(Path,'exists',exists),patch.object(Path,'read_text',read):
    importlib.import_module(sys.argv[2])
print(json.dumps({'runtime_loaded':'packages.domain.runtime' in sys.modules,
                  'legacy_text_port_loaded':'packages.domain.providers.deepseek' in sys.modules,
                  'profile_reads':len(reads),'profile_marker_present':'SHOULD_NOT_LOAD_BUSINESS_PROFILE' in os.environ}))
"""
    environment = {key: value for key, value in os.environ.items() if key in SYSTEM_KEYS}
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code, str(ROOT), module],
        capture_output=True,
        env=environment,
        check=True,
        timeout=20,
    )  # nosec B603
    assert json.loads(result.stdout) == {
        "runtime_loaded": False,
        "legacy_text_port_loaded": False,
        "profile_reads": 0,
        "profile_marker_present": False,
    }


def test_legacy_aliases_and_actual_api_handler_recognize_pure_errors():
    code = """import asyncio,json,sys
sys.path.insert(0,sys.argv[1])
import httpx
from fastapi import FastAPI,Request
from apps.api.main import app as business_app
from packages.domain.errors import DomainError
from packages.domain.providers.errors import ProviderError
from packages.domain.providers.deepseek_vision import VisionProviderError
from packages.domain.runtime import DomainError as LegacyDomainError
from packages.domain.providers.deepseek import ProviderError as LegacyProviderError
assert DomainError is LegacyDomainError
assert ProviderError is LegacyProviderError
app=FastAPI()
app.add_exception_handler(DomainError,business_app.exception_handlers[DomainError])
@app.get('/probe/{kind}')
async def probe(kind:str,request:Request):
    request.state.request_id='synthetic-request'
    if kind=='domain':
        raise DomainError('SYNTHETIC_DOMAIN','synthetic message',422,{'field':'synthetic'},True)
    if kind=='provider':
        raise ProviderError('SYNTHETIC_PROVIDER','synthetic provider')
    raise VisionProviderError('SYNTHETIC_VISION',raw_response=b'raw-not-public')
async def verify():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for kind,status,code in [('domain',422,'SYNTHETIC_DOMAIN'),('provider',503,'SYNTHETIC_PROVIDER'),('vision',503,'SYNTHETIC_VISION')]:
            response=await client.get('/probe/'+kind)
            body=response.json()
            assert response.status_code==status and body['code']==code
            assert body['request_id']=='synthetic-request'
            assert body['retryable'] is (kind=='domain')
            assert b'raw-not-public' not in response.content
            if kind!='domain':
                assert body['details']=={'provider':'deepseek','billing_state':'unknown','external_attempts':1}
asyncio.run(verify())
print(json.dumps({'same_legacy_class_identity':True,'actual_handler_cases':3,'raw_response_exposed':False}))
"""
    environment = {key: value for key, value in os.environ.items() if key in SYSTEM_KEYS}
    environment["WORKBENCH_ENV_FILE"] = "explicit-isolation-test-no-business-profile"
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code, str(ROOT)],
        capture_output=True,
        env=environment,
        check=False,
        timeout=30,
    )  # nosec B603
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert json.loads(result.stdout) == {
        "same_legacy_class_identity": True,
        "actual_handler_cases": 3,
        "raw_response_exposed": False,
    }
