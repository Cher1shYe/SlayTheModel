"""Drop-in PUCT expansion: same networks and tree policy, fewer tensor conversions.

Optional win-weighted leaf evaluation (STS_WIN_WEIGHT > 0): the main value head
is trained on win + HP fraction, which values losing at full HP as highly as
winning at 0 HP.  The auxiliary win/HP heads let search weight a win far more
heavily, matching the native MCTS objective (a loss ends the run)."""
import os
import numpy as np
import torch

WIN_WEIGHT = float(os.environ.get('STS_WIN_WEIGHT', '0') or 0)
ROLLOUT_MIX = float(os.environ.get('STS_ROLLOUT_MIX', '0') or 0)
ROLLOUT_N = int(os.environ.get('STS_ROLLOUT_N', '4') or 4)
PRIOR_TEMP = float(os.environ.get('STS_PRIOR_TEMP', '1') or 1)


def sanitize_state(state):
    # Float64 preserves the original Python-float comparisons before float32
    # network conversion. Vectorize validation without weakening it.
    values = np.asarray(state, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite battle observation')
    return np.clip(values, -100., 100.).tolist()


def _terminal_value(bc, sts):
    hp = float(bc.player.cur_hp) / max(1.0, float(bc.player.max_hp))
    win = 1.0 if bc.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
    if WIN_WEIGHT > 0:
        return WIN_WEIGHT * win + hp
    return win + hp


def install(mc):
    B, V, sts = mc.MB, mc.VV, mc.sts
    if not hasattr(B, 'sanitize_state') or not hasattr(V.ValueNet, 'raw_value'):
        raise RuntimeError('Fast PUCT requires the stabilized observation/value implementation')
    B.sanitize_state = sanitize_state
    def expand(node, policy, value):
        bc = node.bc
        if bc.outcome != sts.Outcome.UNDECIDED:
            node.terminal = True
            node.leaf_value = _terminal_value(bc, sts)
            if hasattr(node, 'leaf_max'):
                node.leaf_max = node.leaf_value
            return node.leaf_value
        cands = sts.get_legal_actions(bc)
        if not cands:
            node.terminal = True
            node.leaf_value = _terminal_value(bc, sts)
            if hasattr(node, 'leaf_max'):
                node.leaf_max = node.leaf_value
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
            node.P = torch.softmax(logits / PRIOR_TEMP, dim=0).tolist()
            if ROLLOUT_MIX >= 1.0:
                # Pure rollout leaves: a native playout costs ~6us against
                # ~300us for a neural evaluation, so the same wall clock buys
                # two orders of magnitude more value samples.  Unbiased even
                # though noisy, unlike a regressing value net.
                node.leaf_value = float(sts.rollout_value(bc, ROLLOUT_N))
            else:
                if WIN_WEIGHT > 0 and hasattr(value, 'forward_tensor'):
                    _raw, wl, hl = value.forward_tensor(torch.from_numpy(state))
                    v = WIN_WEIGHT * torch.sigmoid(wl) + torch.sigmoid(hl)
                    node.leaf_value = v.squeeze().clamp(0., 1. + WIN_WEIGHT).item()
                else:
                    node.leaf_value = value.net(torch.from_numpy(state)).squeeze(-1).clamp(0.,2.).item()
                if ROLLOUT_MIX > 0.0:
                    # KataGo/MCTS hybrid: blend the learned value with a few fast
                    # native random rollouts, the evaluator time-matched MCTS uses.
                    r = float(sts.rollout_value(bc, ROLLOUT_N))
                    node.leaf_value = (1.0 - ROLLOUT_MIX) * node.leaf_value + ROLLOUT_MIX * r
        n=len(cands)
        node.N=[0]*n; node.W=[0.]*n; node.children=[None]*n; node.expanded=True
        if hasattr(node, 'M'):
            node.M=[-1e18]*n; node.leaf_max=node.leaf_value
        if hasattr(node, 'W2'):
            node.W2=[0.0]*n
        return node.leaf_value
    mc.expand = expand
