"""Seal engineering evidence only after a stable, successful full regression."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

FILES=['test_az_content_expansion','test_az_player_abilities','test_az_simple_cards',
 'test_az_transformer_g23e','test_az_transformer_t2','test_az_boss_cards','test_az_boss_reconstruction',
 'test_az_morph','test_az_selection','test_az_lifecycle','test_az_risk_reward','test_az_timeout_replay',
 'test_all_cards_unit_coverage','test_power_lifecycle_and_modifier_hooks','test_ironclad_parity',
 'test_colorless_parity','test_colorless_support_powers_and_returning_attacks_parity',
 'test_ironclad_core_card_model_parity','test_ironclad_exhaust_self_damage_card_model_parity',
 'test_colorless_card_effects_reference_parity','test_az_foundation_interactions',
 'test_nested_autoplay_continuations','test_az_generation_foundation','test_az_foundation_boundaries']

def main():
    from sts2_env.az.network import code_digest
    from sts2_env.az.entity_encoder import SCHEMA
    from sts2_env.az.config import content_hash
    from sts2_env.az.generation_contract import audit
    from scripts.audit_ironclad_colorless_coverage import inventory
    def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
    start=read('docs/ironclad_colorless_foundation_start.json')
    if start['code_digest']!=code_digest():raise ValueError('Source changed during regression')
    root=ET.Element('testsuites')
    logs=[]
    for i in range(4):
        part=ET.parse(ROOT/f'docs/ironclad_colorless_foundation_part{i}.xml').getroot()
        for suite in part.iter('testsuite'):root.append(suite)
        logs.append(f'=== Regression part {i} ===\n'+(ROOT/f'docs/ironclad_colorless_foundation_part{i}.txt').read_text(encoding='utf-8'))
    suites=list(root.iter('testsuite'))
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    if counts['tests']<4000 or any(counts[k] for k in ('failures','errors','skipped')):raise ValueError('Incomplete or failing regression')
    actual=sorted(c.get('classname')+'::'+c.get('name') for c in root.iter('testcase'))
    if actual!=read('docs/ironclad_colorless_foundation_collected.json'):raise ValueError('Regression partition lost or repeated collected cases')
    ET.ElementTree(root).write(ROOT/'docs/ironclad_colorless_foundation_verification.xml',encoding='utf-8',xml_declaration=True)
    (ROOT/'docs/ironclad_colorless_foundation_tests.txt').write_text('\n'.join(logs),encoding='utf-8')
    inv=inventory();pools=audit()
    if inv!=read('docs/ironclad_colorless_coverage.json'):raise ValueError('Coverage artifact is stale')
    if pools!=read('docs/ironclad_colorless_generation_pools.json'):raise ValueError('Generation artifact is stale')
    if any(r['missing'] for r in pools['pools'].values() if r['admitted']):raise ValueError('Open admitted generation dependency')
    paths=['tests/'+n+'.py' for n in FILES]+['scripts/verify_az_foundation.py','scripts/audit_ironclad_colorless_coverage.py',
        'docs/ironclad_colorless_coverage.json','docs/IRONCLAD_COLORLESS_COVERAGE.md',
        'docs/ironclad_colorless_generation_pools.json','docs/ironclad_colorless_foundation_verification.xml',
        'docs/ironclad_colorless_foundation_tests.txt','docs/ironclad_colorless_foundation_collected.json',
        'docs/ironclad_colorless_foundation_start.json']
    paths += [f'docs/ironclad_colorless_foundation_part{i}.{ext}' for i in range(4) for ext in ('xml','txt')]
    for name,digest in start['test_canonical_text_sha256'].items():
        if hashlib.sha256((ROOT/name).read_text(encoding='utf-8').encode('utf-8')).hexdigest()!=digest:raise ValueError('Tests changed during regression')
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT/'sts2_env').rglob('*.py')]
    result=dict(version='ironclad-colorless-foundation-evidence-v4',date='2026-10-17',content=inv['content'],
        code_digest=start['code_digest'],schema_hash=content_hash(SCHEMA),source_stable_during_tests=True,
        tests=counts,seconds=sum(float(s.get('time',0)) for s in suites),parallel_parts=4,
        all_collected_cases_executed_exactly_once=True,pytest_files=['tests/'+n+'.py' for n in FILES],
        admitted=inv['admitted'],total=inv['total'],pending=inv['pending'],new_since_published_v3=inv['admitted']-70,
        training_experiment_started=False,final_holdout_used=False,network_quality_assessed=False,
        acceptance='future actual network whole-combat V7 utility; engineering contracts only in this batch',
        file_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths))},
        canonical_text_sha256={p:hashlib.sha256((ROOT/p).read_text(encoding='utf-8').encode('utf-8')).hexdigest() for p in sorted(set(paths))},
        hash_note='file_sha256 covers tested local bytes; canonical_text_sha256 normalizes CRLF/LF for Git checkout verification')
    (ROOT/'docs/ironclad_colorless_foundation_evidence.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('file_sha256','canonical_text_sha256')},indent=2))

if __name__=='__main__':main()
