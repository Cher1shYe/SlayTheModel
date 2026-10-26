"""Compatibility-preserving bounded observations and robust value training."""
from pathlib import Path

def patch_source(source):
    p=source/'armB_train.py'; code=p.read_text(encoding='utf-8')
    code=code.replace('import os, sys, json, re','import os, sys, json, re, math')
    code=code.replace('def encode_battle(bc):', '''def sanitize_state(state):
    if not all(math.isfinite(x) for x in state):
        raise ValueError("Nonfinite battle observation")
    return [max(-100.0, min(100.0, x)) for x in state]

def encode_battle(bc):''')
    assert '    return o\n' in code
    code=code.replace('    return o\n','    return sanitize_state(o)\n')
    p.write_text(code,encoding='utf-8')
    p=source/'armB_value.py'; code=p.read_text(encoding='utf-8')
    old='        return self.net(torch.tensor(state, dtype=torch.float32)).squeeze(-1)'
    assert old in code
    code=code.replace(old,'''        return self.raw_value(state).clamp(0.0, 2.0)
    def raw_value(self, state):
        return self.net(torch.tensor(MB.sanitize_state(state), dtype=torch.float32)).squeeze(-1)''')
    p.write_text(code,encoding='utf-8')
    p=source/'armB_selfplay.py'; code=p.read_text(encoding='utf-8')
    old='lv.append((value.value(state) - V) ** 2)'
    assert old in code
    code=code.replace(old,'lv.append(torch.nn.functional.smooth_l1_loss(value.raw_value(state), torch.tensor(V, dtype=torch.float32), beta=0.25))')
    code=code.replace('backward(); opt_p.step()', 'backward(); torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0, error_if_nonfinite=True); opt_p.step()')
    code=code.replace('backward(); opt_v.step()', 'backward(); torch.nn.utils.clip_grad_norm_(value.parameters(), 1.0, error_if_nonfinite=True); opt_v.step()')
    p.write_text(code,encoding='utf-8')

def verify(B,value):
    import torch
    assert B.sanitize_state([0.,1.,-1.,1e12,-1e12])==[0.,1.,-1.,100.,-100.]
    for x in (float('nan'),float('inf')):
        try: B.sanitize_state([x])
        except ValueError: pass
        else: raise AssertionError('nonfinite accepted')
    state=[0.]*B.STATE_DIM; state[4]=state[10]=6e6
    with torch.no_grad():
        prediction=value.value(state).item()
    assert 0<=prediction<=2
    # Training on raw outputs avoids zero gradients caused by clipping at inference.
    raw=torch.tensor(-2000.,requires_grad=True)
    loss=torch.nn.functional.smooth_l1_loss(raw,torch.tensor(1.),beta=.25)
    loss.backward(); assert raw.grad.item()==-1.
    return dict(passed=True,extreme_input_prediction=prediction,nonfinite_rejected=True,
                ordinary_inputs_unchanged=True,raw_outside_range_gradient=raw.grad.item())
