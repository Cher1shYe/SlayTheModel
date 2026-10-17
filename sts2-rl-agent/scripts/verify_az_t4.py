"""Read-only T4 freeze/source/continuation checks. Does not run heldout combat."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sts2_env.az.natural_course import validate_course,restore,advance
from sts2_env.az.t4_protocol import generate_protocol,validate_protocol
from sts2_env.az.network import code_digest
from sts2_env.az.config import content_hash
from sts2_env.az.combo_diagnostic import probe,sequence


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    course=read('configs/az_transformer_t4_v1/natural_course.json')
    protocol=read('configs/az_transformer_t4_v1/protocol.json')
    report=read('docs/transformer_t4_preparation.json')
    if protocol!=generate_protocol(): raise ValueError('Frozen recipe drift')
    for path,digest in course['source_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest: raise ValueError('Witness byte drift')
    entries=validate_course(course,[read(p) for p in sorted(course['source_sha256'])])
    counts=validate_protocol(protocol,entries)
    for entry in entries:restore(entry)
    if (report['course_sha256']!=course['sha256'] or report['protocol_sha256']!=protocol['sha256']
            or report['code_digest']!=code_digest() or report['counts']!=counts
            or report['training_started'] or report['heldout_battles_executed']
            or report['network_quality_accepted']): raise ValueError('Diagnostic binding mismatch')
    # Uniform search is deterministic and independent of local checkpoint availability.
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.scenarios import CombatScenario
    from sts2_env.az.rewards import V7
    witness=read('docs/g23f_audit/rule-win-9cdfa66bbf7f.json')
    info=ObservableCombatAdapter(CombatScenario.from_dict(witness['recipe']),reward_version=V7).information
    def factory():return ObservableCombatAdapter(CombatScenario.from_dict(witness['recipe']),reward_version=V7)
    for name,tokens in [('block_then_slam',['ARMAMENTS+','BODY_SLAM+']),
                        ('slam_then_block',['BODY_SLAM+','ARMAMENTS+'])]:
        if sequence(factory,tokens)!=report['orders'][name]:raise ValueError('Armaments sequence drift')
    def iron_factory():
        env=factory()
        for action in report['iron_wave_order']['prefix']:advance(env,action)
        return env
    for name,tokens in [('block_then_slam',['IRON_WAVE+','BODY_SLAM+']),
                        ('slam_then_block',['BODY_SLAM+','IRON_WAVE+'])]:
        if sequence(iron_factory,tokens)!=report['iron_wave_order'][name]:raise ValueError('Iron Wave sequence drift')
    for budget in (8,32,128):
        if probe(info,budget=budget)!=report['probes']['uniform'][str(budget)]:
            raise ValueError('Uniform probe differs')
    print(json.dumps(dict(passed=True,snapshots=len(entries),counts=counts,
                         source_witnesses=len(course['source_sha256']),uniform_search_budgets=[8,32,128])))


if __name__=='__main__':main()
