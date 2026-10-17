import hashlib,json,subprocess,tempfile
from pathlib import Path
root=Path('/workspace/tender-workbench/apps/web');actual=Path('/workspace/tender-docs/04-验证与测试/backend07-independent-checks/actual-main-07.openapi.json');baseline=json.loads((root/'qa-previews/pricing-method-08/frontend-candidate.json').read_text());assert hashlib.sha256(actual.read_bytes()).hexdigest()==baseline['api_contract_sha256']
with tempfile.TemporaryDirectory(prefix='frontend09-types-') as tmp:
 output=Path(tmp)/'contracts.ts'
 subprocess.run(['python','scripts/generate-contracts.py','--openapi',str(actual),'--output',str(output)],cwd=root,check=True)
 subprocess.run([str(root/'node_modules/.bin/prettier'),'--write',str(output)],cwd=root,check=True,capture_output=True)
 assert output.read_text().split('\n',1)[1]==(root/'src/contracts.ts').read_text().split('\n',1)[1]
for name in ['src/contracts.ts','src/PricingFormulaEditor.tsx','src/PricingFormulaEditor.test.tsx']:
 expected=next(row['sha256'] for row in baseline['source_files'] if row['path']==name);assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected
print('actual3249 generated types match08 and pricing baseline bytes retained')
