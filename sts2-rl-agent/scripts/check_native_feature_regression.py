"""Native end-to-end regression for HEXED keywords and downgraded calculated variables."""
import argparse
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sts2_env.az.native_generic_backend import NativeBackend
from sts2_env.az.native_generic import encode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,default=Path('tests/fixtures/native_hexed_calculated_v1.json.gz'))
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=False)
    with gzip.open(args.fixture,'rt',encoding='utf-8') as f: expected=json.load(f)
    c=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())['backend']; c['budget_ms']=250
    p=json.loads(Path('configs/az_native_generic_v1/protocol.json').read_text())
    b=NativeBackend(c,p,args.out); b.configure_search('mixed',.5)
    raw=b.fights(args.checkpoint,[expected['recipe']],args.out/'fights','policy')[0]
    # Use the original frozen model for exact policy trajectory reproduction.
    assert raw['modelSha256']==expected['modelSha256']
    assert {k:raw['outcome'][k] for k in expected['outcome']}==expected['outcome']
    assert [(encode(s['observation']),s['action']) for s in raw['steps']]==[(encode(s['observation']),s['action']) for s in expected['steps']]
    print('Native feature regression passed')


if __name__=='__main__': main()
