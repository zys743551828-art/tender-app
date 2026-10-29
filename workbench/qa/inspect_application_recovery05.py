"""Independent read-only archive inspection. No Docker, PG, provider or object IO."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/workspace/tender-docs/04-验证与测试/application-recovery-development-checks')
OUT = Path('/workspace/tender-docs/04-验证与测试/application-recovery-independent-checks/code-05-single-target-plan')
EXPECTED = {
    'code-05/candidate.json': '6436b14fbd0bd9278f6ae70bea10b1ee4d7e7e2faebda140dd77421d8def052a',
    'actual-code05-serial01/result.json': '9176380c0083fc479354a819b9221db370783392c8ccb9ee898282ce2d59c3ab',
    'actual-code05-serial01/evidence-index.json': '5533e3df11748a2e6ce74b67e37b9257184ca93d368b5eba6291e8f6b14d206d',
}

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def load(p):
    return json.loads(Path(p).read_bytes())

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / 'readonly-result.json'
    if output.exists():
        raise RuntimeError('REFUSE_OVERWRITE')
    checks = []
    inputs = []
    def check(name, predicate):
        if not predicate:
            raise AssertionError(name)
        checks.append(name)
    def verify(p, digest, size=None, mode=None):
        p = Path(p)
        check('bytes:' + str(p), p.is_file() and not p.is_symlink() and sha(p) == digest)
        if size is not None:
            check('size:' + str(p), p.stat().st_size == size)
        if mode is not None:
            check('mode:' + str(p), oct(p.stat().st_mode & 0o777) == mode)
        inputs.append({'path': str(p), 'sha256': digest, 'bytes': p.stat().st_size})
    for relative, digest in EXPECTED.items():
        verify(BASE / relative, digest)
    candidate = load(BASE / 'code-05/candidate.json')
    for item in candidate['owned_sources'] + candidate['observed_dependencies']:
        verify(item['archive'], item['sha256'])
    backend = candidate['backend']
    verify(backend['manifest'], backend['sha256'])
    backend_inputs = load(backend['manifest'])
    check('backend_exact_308', len(backend_inputs) == backend['file_count'] == 308)
    for item in backend_inputs:
        verify(Path(backend['source_root']) / item['path'], item['sha256'])
    baseline = load(BASE / 'protocol-02/baseline-inputs.json')
    for item in baseline['ordered_sql']:
        verify(item['frozen_input'], item['sha256'])
    check('sql_exact_15', len(baseline['ordered_sql']) == 15)
    index = load(BASE / 'actual-code05-serial01/evidence-index.json')
    check('private_evidence_49', len(index['records']) == 49)
    for item in index['records']:
        verify(item['path'], item['sha256'], item['bytes'], item['mode'])
    private = Path(index['private_root'])
    source = load(private / 'archive/manifest.json')
    target = load(private / 'target-archive/manifest.json')
    for label, manifest in [('archive', source), ('target-archive', target)]:
        root = private / label
        check(label + ':manifest_seal', sha(root / 'manifest.json') == (root / 'manifest.sha256').read_text())
        check(label + ':custom_dump_header', (root / 'database.dump').read_bytes()[:8] == b'PGDMP\x01\x10\x00')
        check(label + ':dump_hash', sha(root / 'database.dump') == manifest['database_sha256'])
        check(label + ':164_tables', len(manifest['tables']) == 164)
        check(label + ':complete_objects', manifest['objects_included'] is True and len(manifest['objects']) == 7)
        check(label + ':object_total_322', sum(o['bytes'] for o in manifest['objects']) == 322)
        for obj in manifest['objects']:
            check(label + ':object_identity:' + obj['id'], obj['file'] == 'objects/' + obj['id'] + '.bin')
            check(label + ':object_sha:' + obj['id'], sha(root / obj['file']) == obj['sha256'] and (root / obj['file']).stat().st_size == obj['bytes'])
        check(label + ':paused', manifest['operational_state'] == 'work_paused' and manifest['old_queue_resume_qualified'] is False)
        check(label + ':snapshot_isolation_recorded', manifest['isolation'] == 'repeatable_read_read_only')
        check(label + ':no_staging_claim', manifest['queue_and_staging_inventory']['staging_bytes_included'] is False)
    check('independent_cluster_ids_recorded', source['source_system_identifier'] != target['source_system_identifier'])
    check('distinct_prefixes_recorded', source['object_store']['prefix'] != target['object_store']['prefix'])
    check('catalogs_exact', source['catalog'] == target['catalog'])
    check('objects_exact', source['objects'] == target['objects'])
    check('source_snapshot_inventory_exact', source['tables'] == load(private / 'source-before-snapshot.json')['tables'])
    after = load(private / 'source-after-snapshot.json')['tables']
    changed_source = [(a,b) for a,b in zip(source['tables'], after) if a != b]
    check('post_snapshot_only_one_audit_row', len(changed_source) == 1 and changed_source[0][0]['name'] == 'audit_entries' and changed_source[0][1]['rows'] == changed_source[0][0]['rows'] + 1)
    check('unknown_queue_and_fee_archived', source['queue_and_staging_inventory']['operations'] == [['queued',1]] and source['queue_and_staging_inventory']['model_calls'] == [['unknown',1]])
    # Load only the pure comparison module, never the CLI/bootstrap or a moving module.
    mod_path = BASE / 'code-05/frozen-inputs/deploy/application_recovery/definition_equivalence.py'
    spec = importlib.util.spec_from_file_location('independent_frozen_definition_equivalence', mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sections = [k for k in source['definitions'] if source['definitions'][k] != target['definitions'][k]]
    deltas = [(a,b) for a,b in zip(source['definitions']['constraints'],target['definitions']['constraints']) if a!=b]
    check('one_exact_check_delta', sections == ['constraints'] and len(deltas) == 1 and tuple(deltas[0][0][:4]) == module.IDENTITY and deltas[0][0][4] == module.NESTED and deltas[0][1][4] == module.FLAT)
    check('allowed_pair_compares', module.equivalent(source['definitions'], target['definitions']))
    # Independent attacks: no general SQL normalization, weakened bounds or ACL omission.
    for label, mutate in [
        ('weaken_size', lambda d: d['constraints'].__setitem__(next(i for i,r in enumerate(d['constraints']) if tuple(r[:4]) == module.IDENTITY), [*module.IDENTITY,module.FLAT.replace('2097152','2097153')])),
        ('foreign_identity', lambda d: d['constraints'].__setitem__(next(i for i,r in enumerate(d['constraints']) if tuple(r[:4]) == module.IDENTITY), ['historical_input','another_check','chapter_payloads','',module.FLAT])),
        ('remove_function', lambda d: d['functions'].pop()),
        ('alter_default_acl', lambda d: d['default_acl'].append(['unreviewed','','r','{}'])),
        ('remove_trigger', lambda d: d['triggers'].pop()),
        ('remove_constraint', lambda d: d['constraints'].pop()),
    ]:
        damaged = deepcopy(target['definitions']); mutate(damaged)
        check('equivalence_rejects:' + label, not module.equivalent(source['definitions'], damaged))
    table_changes = [{'schema':a['schema'],'name':a['name'],'source_rows':a['rows'],'target_rows':b['rows']} for a,b in zip(source['tables'],target['tables']) if a != b]
    check('target_preserves_queue_table_hashes', all(next(x for x in source['tables'] if x['schema']=='design' and x['name']==n) == next(x for x in target['tables'] if x['schema']=='design' and x['name']==n) for n in ['operations','outbox','model_calls']))
    check('source_definitions_original_exact', source['definitions'] == load(private / 'source-definitions.json'))
    # Rehash all bytes at end; do not claim file hashing proves a live restore or remote GET.
    check('all_inputs_still_exact', all(sha(i['path']) == i['sha256'] for i in inputs))
    result = {
        'status':'read_only_archive_and_pure_boundary_checks_passed_actual_restore_pending',
        'executed_at':datetime.now(timezone.utc).isoformat(),
        'script':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)},
        'candidate_sha256':EXPECTED['code-05/candidate.json'],
        'private_evidence_count':49,'owned_sources':len(candidate['owned_sources']),
        'observed_dependencies':len(candidate['observed_dependencies']),'backend_files':308,'ordered_sql':15,
        'inputs':inputs,'assertions':checks,'source_target_table_deltas_after_developer_api':table_changes,
        'archive':{'source_manifest_sha256':sha(private/'archive/manifest.json'),'source_dump_sha256':sha(private/'archive/database.dump'),'source_dump_bytes':(private/'archive/database.dump').stat().st_size,'target_manifest_sha256':sha(private/'target-archive/manifest.json'),'target_dump_sha256':sha(private/'target-archive/database.dump'),'objects_per_archive':7,'object_bytes_per_archive':322,'constraints':len(source['definitions']['constraints']),'definition_delta_sections':sections},
        'disk':{'free_bytes':shutil.disk_usage('/workspace').free},
        'execution':{'docker_calls':0,'pg_connections':0,'cloud_calls':0,'providers':0,'consumers':0,'objects_listed':0,'objects_deleted':0},
        'limits':['No new target restore or actual PG ACL probes executed','Native object remote GET/PUT not executed by this inspection','Custom dump header and SHA verified; no host pg_restore is installed, TOC/physical restore pending target window','Snapshot acquisition concurrency is inherited input evidence, not independently re-executed','No production RPO/RTO, inflight multipart, newest A2/Score/Scale schema qualification'],
    }
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'input_count':len(inputs),'assertions':len(checks),'result_sha256':sha(output),'free_MiB':result['disk']['free_bytes']//1048576}))

if __name__ == '__main__':
    main()
