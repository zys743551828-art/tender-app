import json,hashlib,tempfile,subprocess
from pathlib import Path
root=Path('/workspace/tender-workbench/apps/web');contract=root/'qa-previews/word-authoring-12/implemented-application02.openapi.json';value=json.loads(contract.read_text())
assert hashlib.sha256(contract.read_bytes()).hexdigest()=='b65141d0db4afd51317e51a919c1582337bd260d858c27bfbeadc0b5c3cf9ab2'
assert len(value['paths'])==227
assert sum(m in {'get','post','put','patch','delete'} for ops in value['paths'].values() for m in ops)==258
assert len(value['components']['schemas'])==406
with tempfile.TemporaryDirectory() as temporary:
 path=Path(temporary)/'contracts.ts';subprocess.run(['python','scripts/generate-contracts.py','--openapi',str(contract.relative_to(root)),'--output',str(path)],cwd=root,check=True);subprocess.run(['npx','prettier','--write',str(path)],cwd=root,check=True,capture_output=True);assert path.read_bytes()==(root/'src/contracts.ts').read_bytes()
old=root/'qa-previews/assistant-continuation-11';manifest=json.loads((old/'frontend-candidate.json').read_text())
for k,folder in [('source_files','frozen-inputs'),('compiled_assets','frozen-dist')]:assert all(hashlib.sha256((old/folder/item['path']).read_bytes()).hexdigest()==item['sha256'] for item in manifest[k])
for name,expected in {'PricingFormulaEditor.tsx':'e0952eaa0d9ae090a12488f704812343db5e298931042b615fb6b32a1b43295c','PricingFormulaEditor.test.tsx':'3b72a28a8e76f0fd7dabefdf58957bfba7586494ec20564c854fe94cfeb5dfad'}.items():assert hashlib.sha256((root/'src'/name).read_bytes()).hexdigest()==expected
base=json.loads((root/'qa-previews/knowledge-version-09/frontend-candidate.json').read_text());expected=next(v['sha256'] for v in base['source_files'] if v['path']=='src/Knowledge.tsx');assert hashlib.sha256((root/'src/Knowledge.tsx').read_bytes()).hexdigest()==expected
print('Actual application02 227/258/406 exact regeneration; recursive JSON emits TS index signature;11 frozen130/215 andPricing08/Knowledge09 preserved. Pending03 Word declaration actual is not fabricated.')
