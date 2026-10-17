import hashlib,json,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[3]
source=root/'qa-previews/assistant-task-10/implemented-task04.openapi.json'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='4af4b5d611539485be74aeed8b98f07d95fb4bc4e9c16572a781f219e5877ae2'
api=json.loads(source.read_text());schemas=api['components']['schemas'];paths=api['paths']
assert len(paths)==164
assert sum(method in {'get','post','put','patch','delete'} for operations in paths.values() for method in operations)==193
assert {'snapshot_id','sections'} <= set(schemas['DraftView']['properties'])
assert 'interpretation' not in schemas['DraftView']['properties']
assert 'interpretation' in schemas['TaskDraftView']['properties']
assert paths['/api/v1/bids/{bid_id}/drafts/{draft_id}']['get']['responses']['200']['content']['application/json']['schema']['$ref']=='#/components/schemas/DraftView'
assert paths['/api/v1/bids/{bid_id}/task-definition-drafts/{draft_id}']['get']['responses']['200']['content']['application/json']['schema']['$ref']=='#/components/schemas/TaskDraftView'
assert paths['/api/v1/bids/{bid_id}/task-definitions']['get']['responses']['200']['content']['application/json']['schema']['$ref']=='#/components/schemas/TemplatePage'
assert paths['/api/v1/bids/{bid_id}/task-definitions']['post']['requestBody']['content']['application/json']['schema']['$ref']=='#/components/schemas/TemplateRequest'
with tempfile.TemporaryDirectory() as temporary:
 output=Path(temporary)/'contracts.ts'
 subprocess.run(['python','scripts/generate-contracts.py','--openapi',str(source.relative_to(root)),'--output',str(output)],cwd=root,check=True)
 subprocess.run(['npx','prettier','--write',str(output)],cwd=root,check=True,capture_output=True)
 assert output.read_bytes()==(root/'src/contracts.ts').read_bytes()
for name,expected in {'PricingFormulaEditor.tsx':'e0952eaa0d9ae090a12488f704812343db5e298931042b615fb6b32a1b43295c','PricingFormulaEditor.test.tsx':'3b72a28a8e76f0fd7dabefdf58957bfba7586494ec20564c854fe94cfeb5dfad'}.items():assert hashlib.sha256((root/'src'/name).read_bytes()).hexdigest()==expected
base=json.loads((root/'qa-previews/knowledge-version-09/frontend-candidate.json').read_text())
for item in base['source_files']:
 if item['path']=='src/Knowledge.tsx':assert hashlib.sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256']
print('Fixed task05/04 actual regenerated exactly; A2 and task draft schemas distinct;08 pricing and09 knowledge source preserved.')
