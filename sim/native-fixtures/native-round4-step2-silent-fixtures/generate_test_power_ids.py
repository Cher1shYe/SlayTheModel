"""Generate only the test's native power-name lookup from checked-in evidence."""
from pathlib import Path
import json
import re

here=Path(__file__).resolve().parent
mapping=json.loads((here.parent/'simulator/content/native_power_ids.json').read_text())
def native_key(name):
    return re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',re.sub(r'([A-Z])([A-Z][a-z])',r'\1_\2',name)).upper()
lookup={native_key(k):v for k,v in mapping.items()}
found=set()
def visit(obj):
    if isinstance(obj,dict):
        if 'powers' in obj:found.update(p['id'] for p in obj['powers'])
        for v in obj.values():visit(v)
    elif isinstance(obj,list):
        for v in obj:visit(v)
visit(json.loads((here/'results.json').read_text()))
(here/'native_power_test_ids.inc').write_text(''.join(f'{{"{key}",PowerId::{lookup[key]}}},\n' for key in sorted(found)))
