"""Drop-in PUCT expansion: same networks and tree policy, fewer tensor conversions."""
import numpy as np
import torch

def sanitize_state(state):
    # Float64 preserves the original Python-float comparisons before float32
    # network conversion. Vectorize validation without weakening it.
    values = np.asarray(state, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite battle observation')
    return np.clip(values, -100., 100.).tolist()

def install(mc):
    B, V, sts = mc.MB, mc.VV, mc.sts
    if not hasattr(B, 'sanitize_state') or not hasattr(V.ValueNet, 'raw_value'):
        raise RuntimeError('Fast PUCT requires the stabilized observation/value implementation')
    B.sanitize_state = sanitize_state
    def expand(node, policy, value):
        bc = node.bc
        if bc.outcome != sts.Outcome.UNDECIDED:
            node.terminal = True; node.leaf_value = V._battle_value(bc)
            return node.leaf_value
        cands = sts.get_legal_actions(bc)
        if not cands:
            node.terminal = True; node.leaf_value = V._battle_value(bc)
            return node.leaf_value
        node.cands = cands
        # encode_battle has already validated and bounded every state feature.
        state = np.asarray(B.encode_battle(bc), dtype=np.float32)
        hand = list(bc.hand)
        desc = np.asarray([B.cand_desc(bc,a,hand) for a in cands],dtype=np.float32)
        rows = np.empty((len(cands), B.INPUT_DIM), dtype=np.float32)
        rows[:, :B.STATE_DIM] = state
        rows[:, B.STATE_DIM:] = desc
        with torch.inference_mode():
            logits = policy.net(torch.from_numpy(rows)).squeeze(-1)
            node.P = torch.softmax(logits,dim=0).tolist()
            node.leaf_value = value.net(torch.from_numpy(state)).squeeze(-1).clamp(0.,2.).item()
        n=len(cands)
        node.N=[0]*n; node.W=[0.]*n; node.children=[None]*n; node.expanded=True
        return node.leaf_value
    mc.expand = expand

