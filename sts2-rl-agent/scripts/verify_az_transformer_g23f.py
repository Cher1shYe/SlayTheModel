"""Recompute audit summaries, source hashes and full legal witness trajectories."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_az_transformer_g23f import read, trajectory, aggregate, CombatScenario


def verify(root, output):
    root,output=Path(root),Path(output)
    report=read(output/'audit.json')
    assert report['training_started'] is False and report['final_test_read'] is False
    for relative,digest in report['source_sha256'].items():
        assert not Path(relative).name.startswith('test-')
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest,relative
    for group,rows in report['groups'].items():
        assert aggregate(rows)==report['summary'][group],group
    for name,digest in report['witness_sha256'].items():
        path=output/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
        witness=read(path)
        recipe=CombatScenario.from_dict(witness['recipe'])
        actions=iter(witness['actions'])
        _,actual=trajectory(recipe,lambda info:next(actions))
        # JSON canonicalization handles tuple/list representation only.
        assert json.loads(json.dumps(actual))==witness,name
    result=dict(sources=len(report['source_sha256']),groups=len(report['groups']),
                full_legal_witnesses=len(report['witness_sha256']),passed=True)
    print(json.dumps(result))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='output/az_transformer_t3_v7_formal_20261016')
    parser.add_argument('--output',default='docs/g23f_audit')
    verify(**vars(parser.parse_args()))
