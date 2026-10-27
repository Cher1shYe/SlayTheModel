"""Self-play v2 for the STS1 battle agent.

Adds the sample-efficiency pieces that matter for this project:
  * Go-Exploit style battle-state archive: most training episodes start from a
    cloned mid-battle state, so deep/hard states are covered and every episode
    yields an independent terminal value target.
  * KataGo style playout-cap randomization: only a fraction of decisions use a
    full search and produce policy targets; all decisions produce value targets.
  * Auxiliary value heads (win / remaining HP) on top of the main win+HP head.
  * Optional native-MCTS anchor on a fraction of full-search decisions.
  * Per-round evaluation: full-run floors, battle win rate / HP, value MSE.

Usage (see main):  python deployment/selfplay_v2.py --out ... --rounds 5 ...
"""
import argparse
import hashlib
import json
import math
import os
import random
import shutil
import statistics
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P_ARCH = (256, 256)
V_ARCH = tuple(int(x) for x in os.environ.get('STS_VALUE_ARCH', '256,256').split(','))
ARCHIVE = []
ARCHIVE_CAP = 1500
_NETS = {}
_AGNET = None


# ---------------------------------------------------------------- worker setup
def _install_aux(V, torch):
    if getattr(V, '_aux_installed', False):
        return
    nn = torch.nn

    class ValueNetAux(V.ValueNet):
        def __init__(self, arch=(256, 256)):
            super().__init__(arch)
            hidden = arch[-1] if arch else 256
            self.aux_win = nn.Linear(hidden, 1)
            self.aux_hp = nn.Linear(hidden, 1)

        def forward_tensor(self, x):
            h = self.net[:-1](x)
            main = self.net[-1](h).squeeze(-1)
            return main, self.aux_win(h).squeeze(-1), self.aux_hp(h).squeeze(-1)

        def forward_all(self, state):
            return self.forward_tensor(torch.tensor(B.sanitize_state(state), dtype=torch.float32))

    ValueNetAux.__name__ = 'ValueNetAux'
    V.ValueNet = ValueNetAux
    V._aux_installed = True


def init_worker(source):
    global torch, np, F, sts, B, V, MC, SP, AG
    os.environ['STS_BOT_DIR'] = source
    sys.path[:0] = [str(ROOT / os.environ.get('STS_SO_DIR', 'simulator/build312/Release')), str(ROOT / 'deployment'), source]
    import torch
    import numpy as np
    import torch.nn.functional as F
    import slaythespire as sts
    import armB_train as B
    import armB_value as V
    import armB_mcts as MC
    import armB_selfplay as SP
    import armG_train as AG
    torch.set_num_threads(1)
    AG.card_idx = lambda name: AG._vocab.get(name, AG.VOCAB_CAP - 1)
    if os.environ.get('STS_FAST_PUCT') == '1':
        import fast_puct
        fast_puct.install(MC)
    _install_aux(V, torch)


class EnsemblePolicy:
    def __init__(self, nets):
        self.nets = nets

    def net(self, rows):
        return sum(n.net(rows) for n in self.nets) / len(self.nets)

    def score(self, state, descs):
        rows = torch.stack([torch.tensor(state + c, dtype=torch.float32) for c in descs])
        out = self.net(rows)
        return out.squeeze(-1) if getattr(out, 'ndim', 1) > 1 else out

    def eval(self):
        return self


class EnsembleValue:
    def __init__(self, nets):
        self.nets = nets

    def net(self, x):
        return sum(n.net(x) for n in self.nets) / len(self.nets)

    def value(self, state):
        return sum(n.value(state) for n in self.nets) / len(self.nets)

    def forward_tensor(self, x):
        outs = [n.forward_tensor(x) for n in self.nets]
        return tuple(sum(o[i] for o in outs) / len(outs) for i in range(3))

    def eval(self):
        return self


def _load_one(wp, wv):
    policy = B.Scorer(P_ARCH)
    policy.load_state_dict(torch.load(wp, weights_only=True))
    policy.eval()
    value = V.ValueNet(V_ARCH)
    result = value.load_state_dict(torch.load(wv, weights_only=True), strict=False)
    bad = [k for k in result.missing_keys if not k.startswith('aux_')]
    if bad:
        raise RuntimeError('value checkpoint missing keys: ' + str(bad))
    value.eval()
    return policy, value


def load_nets(wp, wv):
    global _AGNET
    spec = os.environ.get('STS_ENSEMBLE', '')
    key = (str(wp), str(wv), spec)
    if key in _NETS:
        return _NETS[key]
    policy, value = _load_one(wp, wv)
    if spec:
        nets = [(policy, value)]
        for item in spec.split(','):
            if not item.strip():
                continue
            p_path, v_path = item.split(';')
            if (str(p_path), str(v_path)) == (str(wp), str(wv)):
                continue
            nets.append(_load_one(p_path, v_path))
        policy = EnsemblePolicy([n[0] for n in nets])
        value = EnsembleValue([n[1] for n in nets])
    _NETS[key] = (policy, value)
    return policy, value


def load_armg():
    global _AGNET
    if _AGNET is None:
        _AGNET = SP._load_armg()
    return _AGNET


# --------------------------------------------------------------------- helpers
def battle_targets(bc):
    win = 1.0 if bc.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
    hp = float(bc.player.cur_hp) / max(1.0, float(bc.player.max_hp))
    return win + hp, win, hp


def native_move(bc, sims, timed_ms=0.0):
    """Run the C++ native MCTS.  A positive timed_ms uses a wall-clock budget
    instead of a simulation count, which is what "time-matched MCTS" means."""
    if timed_ms and timed_ms > 0.0:
        res = sts.mcts_recommend_timed(bc, float(timed_ms))
        return res[0]
    return sts.mcts_recommend(bc, int(sims))


def native_label(bc, actions, cfg, soft):
    """Return (index, policy target) for the native teacher.  Soft targets use
    the root visit distribution; one-hot uses only the recommended action."""
    timed_ms = float(cfg.get('native_timed_ms', 0.0))
    if soft:
        if timed_ms > 0.0:
            best, bits, visits, _ = sts.mcts_visits_timed(bc, timed_ms)
        else:
            best, bits, visits = sts.mcts_visits(bc, int(cfg['native_sims']))
    else:
        best = native_move(bc, cfg['native_sims'], timed_ms)
        bits, visits = [], []
    idx = next((i for i, a in enumerate(actions) if a.bits == best.bits), -1)
    if idx < 0:
        return -1, None
    if soft:
        by_bits = {int(b): int(v) for b, v in zip(bits, visits)}
        arr = [float(by_bits.get(int(a.bits), 0)) for a in actions]
        total = sum(arr)
        if total > 0.0:
            return idx, [x / total for x in arr]
    visit = [0.0] * len(actions)
    visit[idx] = 1.0
    return idx, visit


def archive_tree_node(tree, rng):
    """Go-Exploit GESR: archive a deep node from the search tree, not just the
    played trajectory.  Those states are exactly the ones the value net sees as
    leaves, and restarting episodes there gives them independent outcome targets."""
    node = tree
    for _ in range(10):
        kids = [c for c in (node.children or []) if c is not None]
        if not kids:
            break
        node = kids[rng.randrange(len(kids))]
    if node.bc.outcome == sts.Outcome.UNDECIDED:
        archive_add(node.bc)


def archive_add(bc):
    if bc.outcome != sts.Outcome.UNDECIDED:
        return
    clone = bc.clone()
    if len(ARCHIVE) < ARCHIVE_CAP:
        ARCHIVE.append(clone)
    else:
        ARCHIVE[random.randrange(ARCHIVE_CAP)] = clone


def dump(path, obj):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=2), encoding='utf-8')
    tmp.replace(path)


# -------------------------------------------------------------------- episodes
def run_battle(bc, policy, value, cfg, rng, archive=False, from_archive=False):
    """Play one battle from bc using playout-cap randomized PUCT."""
    samples = []
    decisions = 0
    full = 0
    every = int(cfg['archive_every'])
    native_frac = float(cfg.get('native_frac', 0.0))
    # Archive restarts give dense value coverage, but their mid-battle state
    # distribution can starve the policy's early-game targets.  Optionally use
    # them for value only.
    train_policy = (not from_archive) or bool(cfg.get('archive_policy', 1))
    while bc.outcome == sts.Outcome.UNDECIDED:
        actions = sts.get_legal_actions(bc)
        if not actions:
            raise RuntimeError('Live battle has no actions')
        if len(actions) == 1:
            actions[0].execute(bc)
            decisions += 1
            if archive and every and decisions % every == 0:
                archive_add(bc)
            continue
        state = B.encode_battle(bc)
        hand = list(bc.hand)
        descs = [B.cand_desc(bc, a, hand) for a in actions]
        if cfg.get('behavior', 'search') == 'pure':
            # DAgger-style expert iteration: act with the current policy (so the
            # states are exactly the ones the policy visits) and label them with
            # the native search recommendation.
            with torch.inference_mode():
                idx = int(policy.score(state, descs).argmax())
            visit = None
            if native_frac > 0.0:
                j, visit = native_label(bc, actions, cfg, cfg.get('native_soft', 0))
                if j < 0:
                    visit = None
            samples.append((np.asarray(state, dtype=np.float32),
                            np.asarray(descs, dtype=np.float32),
                            None if visit is None else np.asarray(visit, dtype=np.float32),
                            None))
            actions[idx].execute(bc)
            decisions += 1
            if archive and every and decisions % every == 0:
                archive_add(bc)
            continue
        use_full = rng.random() < float(cfg['p_full'])
        if use_full:
            full += 1
            anchored = False
            if native_frac > 0.0 and rng.random() < native_frac:
                idx, visit = native_label(bc, actions, cfg, cfg.get('native_soft', 0))
                if idx >= 0:  # native can propose actions outside get_legal_actions
                    rootv = None
                    anchored = True
            if not anchored:
                tree = MC.Node(bc.clone())
                ms = float(cfg.get('n_full_timed_ms', 0.0))
                if ms > 0.0:
                    # MiniZero-style progressive budget, expressed in wall-clock:
                    # search exactly as long as the evaluated agent will.
                    deadline = time.perf_counter() + ms / 1000.0
                    k = 0
                    while k == 0 or time.perf_counter() < deadline:
                        MC.simulate(tree, policy, value)
                        k += 1
                else:
                    for _ in range(int(cfg['n_full'])):
                        MC.simulate(tree, policy, value)
                if cfg.get('search_archive', 0.0) > 0.0 and rng.random() < float(cfg['search_archive']):
                    archive_tree_node(tree, rng)
                if tree.cands is None:
                    raise RuntimeError('Search produced no candidates')
                total = sum(tree.N)
                if total <= 0:
                    raise RuntimeError('Search produced zero visits')
                visit = [n / total for n in tree.N]
                if cfg.get('prune_thr', 0.0) > 0.0 and len(visit) > 1:
                    # KataGo-style target pruning: drop low-visit noise.
                    thr = float(cfg['prune_thr']) * max(tree.N)
                    kept = [n if n >= thr else 0.0 for n in tree.N]
                    s = sum(kept)
                    if s > 0:
                        visit = [n / s for n in kept]
                rootv = sum(tree.W) / total
                idx = rng.choices(range(len(actions)), weights=visit)[0]
            samples.append((np.asarray(state, dtype=np.float32),
                            np.asarray(descs, dtype=np.float32),
                            None if not train_policy else np.asarray(visit, dtype=np.float32),
                            rootv))
        else:
            tree = MC.Node(bc.clone())
            for _ in range(int(cfg['n_fast'])):
                MC.simulate(tree, policy, value)
            if cfg.get('search_archive', 0.0) > 0.0 and rng.random() < float(cfg['search_archive']):
                archive_tree_node(tree, rng)
            if tree.cands is None:
                raise RuntimeError('Fast search produced no candidates')
            total = sum(tree.N)
            if total <= 0:
                raise RuntimeError('Fast search produced zero visits')
            idx = max(range(len(tree.N)), key=lambda i: tree.N[i])
            samples.append((np.asarray(state, dtype=np.float32),
                            np.asarray(descs, dtype=np.float32), None,
                            sum(tree.W) / total))
        actions[idx].execute(bc)
        decisions += 1
        if archive and every and decisions % every == 0:
            archive_add(bc)
    z, win, hp = battle_targets(bc)
    out = [(s, c, v, z, win, hp, rv) for (s, c, v, rv) in samples]
    return out, dict(win=win, hp=hp, decisions=decisions, full=full)


def _noncombat(gc, agnet):
    kind, descs, actions = AG.build_choices(gc)
    if not descs:
        if gc.screen_state == sts.ScreenState.REWARDS:
            gc.skip_reward_cards()
            return False
        raise RuntimeError('No noncombat actions: ' + kind)
    with torch.inference_mode():
        scores = agnet.score(torch.tensor(AG.obs_vec(gc)), descs)
    actions[int(scores.argmax())](gc)
    return True


def run_fresh(seed, policy, value, agnet, cfg, rng, mode='train'):
    """Play a complete run; train mode collects samples, eval mode collects stats."""
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent()
    ag.simulation_count_base = 2000
    SP._set_all_pauses(ag)
    samples = []
    battles = []
    values = []
    decisions = 0
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state != sts.ScreenState.BATTLE:
            if not _noncombat(gc, agnet):
                continue
            continue
        bc = sts.BattleContext()
        bc.init(gc)
        if mode == 'train':
            archive_add(bc)
            s, stats = run_battle(bc, policy, value, cfg, rng, archive=True)
            samples.extend(s)
            decisions += stats['decisions']
        else:
            stats, vals = run_battle_eval(bc, policy, value, cfg, rng, mode)
            battles.append(stats)
            values.extend(vals)
            decisions += stats['decisions']
        if bc.outcome == sts.Outcome.UNDECIDED:
            raise RuntimeError('Battle truncated before terminal')
        bc.exit_battle(gc)
    if gc.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('Run truncated before terminal')
    return dict(seed=seed, floor=gc.floor_num,
                win=gc.outcome == sts.GameOutcome.PLAYER_VICTORY,
                samples=samples, battles=battles, values=values, decisions=decisions)


def root_pick(tree, cfg):
    n = len(tree.N)
    if cfg.get('root_lcb', 0) and getattr(tree, 'W2', None) is not None:
        # KataGo's useLcbForSelection: pick the move with the best lower
        # confidence bound on Q instead of the most-visited move.  With more
        # simulations the most-visited edge is the one whose value estimate
        # looks best to a biased net; the LCB subtracts the standard error,
        # which penalises edges whose high Q rests on few or noisy visits.
        k = float(cfg.get('lcb_k', 5.0))
        prop = float(cfg.get('lcb_min_prop', 0.15))
        total = sum(tree.N)
        min_n = max(int(cfg.get('root_min_visits', 1)), int(prop * total))
        cand = [i for i in range(n) if tree.N[i] >= max(1, min_n)]
        if cand:
            best_i, best_l = -1, -1e18
            for i in cand:
                m = tree.W[i] / tree.N[i]
                var = max(0.0, tree.W2[i] / tree.N[i] - m * m)
                lcb = m - k * math.sqrt(var / tree.N[i])
                if lcb > best_l:
                    best_l, best_i = lcb, i
            return best_i
    if cfg.get('root_max', 0) and getattr(tree, 'M', None) is not None:
        min_n = int(cfg.get('root_min_visits', 1))
        cand = [i for i in range(n) if tree.N[i] >= min_n]
        if cand:
            return max(cand, key=lambda i: (tree.M[i], tree.N[i]))
    if cfg.get('root_q', 0) and any(tree.N):
        cand = [i for i in range(n) if tree.N[i] > 0]
        return max(cand, key=lambda i: (tree.W[i] / tree.N[i], tree.N[i]))
    return max(range(n), key=lambda i: tree.N[i])


def run_battle_eval(bc, policy, value, cfg, rng, mode):
    try:
        sts.set_playout_determinize(int(cfg.get('determinize', 0) or 0))
    except AttributeError:
        pass
    try:
        sts.set_playout_guard(int(cfg.get('playout_guard', 0) or 0))
    except AttributeError:
        pass
    try:
        sts.set_playout_variants(int(cfg.get('playout_variants', 0) or 0))
    except AttributeError:
        pass
    _hp0 = int(bc.player.cur_hp)
    _maxhp = int(bc.player.max_hp)
    _enc = str(bc.encounter)
    _floor = -1
    preds = []
    decisions = 0
    searched = 0
    search_ms = 0.0
    sims = 0
    timed_ms = float(cfg.get('eval_timed_ms', 130.0))
    ref_bc = None
    # Planned-line commitment: after a search, replay the first `commit_line`
    # actions of the winning line directly instead of re-searching every
    # decision.  The simulator is RNG-exact, so the line that was evaluated is
    # the line that will happen; re-searching only lets search noise move the
    # agent off it.  A mismatched bit (dead target, changed input state) drops
    # the rest of the plan.
    _commit_n = int(cfg.get('commit_line', 0) or 0)
    _pending = []
    _plan0 = -1
    _repl = 0
    _mism = 0
    while bc.outcome == sts.Outcome.UNDECIDED:
        actions = sts.get_legal_actions(bc)
        if not actions:
            raise RuntimeError('Live battle has no actions')
        if len(actions) == 1:
            actions[0].execute(bc)
            decisions += 1
            continue
        if _pending:
            _hit = next((a for a in actions if int(a.bits) == int(_pending[0])), None)
            if _hit is not None:
                _hit.execute(bc)
                _pending.pop(0)
                decisions += 1
                _repl += 1
                continue
            _mism += 1
            _pending = []
        state = B.encode_battle(bc)
        hand = list(bc.hand)
        t0 = time.perf_counter()
        if mode == 'pure':
            with torch.inference_mode():
                logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                preds.append(float(value.value(state).item()))
            idx = int(logits.argmax())
            sims += 1
        elif mode == 'puct_vprior_timed':
            # Root priors from the trained value net instead of the policy net:
            # one forward per candidate child state, standardised and sharpened.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                base_v = float(value.value(state).item())
                tvals = []
                for a in actions:
                    try:
                        bc2 = bc.clone()
                        a.execute(bc2)
                        if bc2.outcome != sts.Outcome.UNDECIDED:
                            tvals.append(2.0 if bc2.outcome == sts.Outcome.PLAYER_VICTORY else 0.0)
                        else:
                            tvals.append(float(value.value(B.encode_battle(bc2)).item()))
                    except Exception:
                        tvals.append(base_v)
                tv = torch.tensor(tvals, dtype=torch.float32)
                ttemp = float(cfg.get('value_prior_temp', 0.05))
                probs = torch.softmax((tv - tv.max()) / ttemp, dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            budget = max(1.0, timed_ms - policy_ms)
            priors = {int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            recommended, ns, _el = sts.mcts_puct_timed(
                bc, budget, priors, float(cfg.get('cpuct_native', 3.0)),
                float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)))
            sims += int(ns)
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode in ('puct_greedy_timed', 'native_greedy_timed'):
            # Same root search, but every simulation's playout follows the
            # expert-greedy rollout policy instead of uniform random actions.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                if float(cfg.get('prior_from_value', 0.0)) > 0.0:
                    # Root priors from the value net: one forward per candidate
                    # child state, standardised and sharpened.
                    _base = float(value.value(state).item())
                    _tv = []
                    for _a in actions:
                        try:
                            _b2 = bc.clone()
                            _a.execute(_b2)
                            if _b2.outcome != sts.Outcome.UNDECIDED:
                                _tv.append(2.0 if _b2.outcome == sts.Outcome.PLAYER_VICTORY else 0.0)
                            else:
                                _tv.append(float(value.value(B.encode_battle(_b2)).item()))
                        except Exception:
                            _tv.append(_base)
                    _t = torch.tensor(_tv, dtype=torch.float32)
                    _w = float(cfg.get('prior_vw', 1.0))
                    _pp = torch.softmax((_t - _t.max()) / float(cfg.get('value_prior_temp', 0.05)),
                                        dim=0).tolist()
                    logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                    _pn = torch.softmax(logits / float(cfg.get('prior_temp', 1.0)), dim=0).tolist()
                    probs = [((1.0 - _w) if _w < 1.0 else 0.0) * _pn[i] + _w * _pp[i]
                             for i in range(len(actions))]
                else:
                    logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                    probs = torch.softmax(logits / float(cfg.get('prior_temp', 1.0)), dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            budget = max(1.0, timed_ms - policy_ms)
            prior_map = {} if mode == 'native_greedy_timed' else {
                int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            if cfg.get('danger_mask') and mode != 'native_greedy_timed':
                # When the next monster turn can take most of the remaining
                # health, concentrate the root search on actions that add
                # block.  Replays of lost boss fights show the search spending
                # every point of energy on damage in exactly these spots,
                # because the greedy rollout assumes average draws from then on
                # and therefore always finds a line that survives.
                _thr = float(cfg.get('danger_thresh', 0.8))
                _inc = 0
                for _m in bc.monsters:
                    if not _m.alive:
                        continue
                    try:
                        _d = _m.intent_damage(bc)
                        _n = max(1, int(getattr(_d, 'attackCount', 1) or 1))
                        _base = int(_d.damage) + int(_m.strength)
                        if int(_m.weak) > 0:
                            _base = int(_base * 0.75)
                        _inc += max(0, _base) * _n
                    except Exception:
                        pass
                _unblocked = max(0, _inc - int(bc.player.block))
                if os.environ.get('STS_MASK_DEBUG'):
                    print('MASKCHK inc=%d hp=%d blk=%d unblk=%d thr=%.2f' % (
                        _inc, int(bc.player.cur_hp), int(bc.player.block), _unblocked, _thr),
                        file=sys.stderr)
                if _unblocked >= _thr * max(1, int(bc.player.cur_hp)):
                    _km = set()
                    _b0 = int(bc.player.block)
                    for _a in actions:
                        try:
                            _st = bc.clone()
                            _a.execute(_st)
                        except Exception:
                            continue
                        if int(_st.player.block) > _b0:
                            _km.add(int(_a.bits))
                    if 0 < len(_km) < len(actions):
                        _tot = sum(probs[i] for i, a in enumerate(actions)
                                   if int(a.bits) in _km) or 1.0
                        prior_map = {int(a.bits): (probs[i] / _tot
                                                   if int(a.bits) in _km else 1e-8)
                                     for i, a in enumerate(actions)}
            _nthreads = int(cfg.get('threads', 1) or 1)
            if _nthreads > 1 and hasattr(sts, 'mcts_ex_timed_parallel'):
                recommended, count, _el = sts.mcts_ex_timed_parallel(
                    bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                    float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                    int(cfg.get('playout_mode', 1)), float(cfg.get('playout_eps', 0.0)),
                    mode == 'puct_greedy_timed', _nthreads)
            elif int(cfg.get('root_pick_mode', 0) or 0):
                # Robust root selection: the default rule returns the first action
                # of the single best-scoring rollout line, i.e. a maximum over a
                # few hundred noisy samples.  Pool every sample per root edge
                # instead and rank by mean evaluation (mode 1) or visits (mode 2).
                _res, _bits, _vis, _esum, _wins, count = sts.mcts_stats_ex_timed(
                    bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                    float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                    int(cfg.get('playout_mode', 1)), float(cfg.get('playout_eps', 0.0)),
                    mode == 'puct_greedy_timed')
                _tot = sum(_vis) or 1
                _mode = int(cfg.get('root_pick_mode'))
                _k = None
                if _mode in (3, 4):
                    # Among the root edges that produced at least one won
                    # playout, prefer the one that wins most often: the plain
                    # best-line rule cannot tell a 5% line from a 30% line.
                    _wfloor = max(1.0, float(cfg.get('root_pick_floor', 0.01)) * _tot)
                    _wc = [i for i in range(len(_vis))
                           if _wins[i] > 0 and _vis[i] >= _wfloor]
                    if _wc:
                        if _mode == 3:
                            _k = max(_wc, key=lambda i: _wins[i] / float(_vis[i]))
                        else:
                            _k = max(_wc, key=lambda i: (float(_wins[i]),
                                                         _wins[i] / float(_vis[i])))
                    elif any(w > 0 for w in _wins):
                        _k = max(range(len(_vis)), key=lambda i: _wins[i])
                elif _mode == 2:
                    _k = max(range(len(_vis)), key=lambda i: _vis[i])
                else:
                    _floor = max(1.0, float(cfg.get('root_pick_floor', 0.02)) * _tot)
                    _cand = [i for i in range(len(_vis)) if _vis[i] >= _floor]
                    if not _cand:
                        _cand = list(range(len(_vis)))
                    _k = max(_cand, key=lambda i: _esum[i] / max(1.0, float(_vis[i])))
                if _k is None:
                    recommended = _res
                else:
                    recommended = next((a for a in actions if int(a.bits) == int(_bits[_k])),
                                       actions[_k] if _k < len(actions) else actions[0])
            elif _commit_n > 0 and hasattr(sts, 'mcts_line_ex_timed'):
                recommended, _line, count, _el = sts.mcts_line_ex_timed(
                    bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                    float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                    int(cfg.get('playout_mode', 1)), float(cfg.get('playout_eps', 0.0)),
                    mode == 'puct_greedy_timed')
                _pending = [int(x) for x in _line[1:1 + _commit_n]]
                _plan0 = int(recommended.bits)
            else:
                recommended, count, _el = sts.mcts_ex_timed(
                    bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                    float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                    int(cfg.get('playout_mode', 1)), float(cfg.get('playout_eps', 0.0)),
                    mode == 'puct_greedy_timed')
            sims += int(count)
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
            if _pending and int(actions[idx].bits) != _plan0:
                # the search's first action could not be mapped onto a legal
                # action, so the stored line no longer follows from this state
                _pending = []
        elif mode == 'puct_refprior_timed':
            # GAZ Play-to-Plan's comparative value, at inference: a frozen
            # greedy reference ("past self") advances one step per decision,
            # and each candidate child is scored by V(child) - V(reference
            # state at the same timestep) instead of its absolute value.  The
            # reference trajectory acts as a self-critical baseline that
            # cancels the value net's systematic optimism.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                if ref_bc is None:
                    ref_bc = bc.clone()
                if ref_bc.outcome != sts.Outcome.UNDECIDED:
                    v_ref = 2.0 if ref_bc.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
                    ref_next = ref_bc
                else:
                    racts = sts.get_legal_actions(ref_bc)
                    if not racts:
                        v_ref = float(value.value(B.encode_battle(ref_bc)).item())
                        ref_next = ref_bc
                    else:
                        rst = B.encode_battle(ref_bc)
                        rhd = list(ref_bc.hand)
                        rl = policy.score(rst, [B.cand_desc(ref_bc, x, rhd) for x in racts])
                        ref_next = ref_bc.clone()
                        racts[int(rl.argmax())].execute(ref_next)
                        if ref_next.outcome != sts.Outcome.UNDECIDED:
                            v_ref = 2.0 if ref_next.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
                        else:
                            v_ref = float(value.value(B.encode_battle(ref_next)).item())
                tvals = []
                for a in actions:
                    try:
                        bc2 = bc.clone()
                        a.execute(bc2)
                        if bc2.outcome != sts.Outcome.UNDECIDED:
                            tvals.append(2.0 if bc2.outcome == sts.Outcome.PLAYER_VICTORY else 0.0)
                        else:
                            tvals.append(float(value.value(B.encode_battle(bc2)).item()))
                    except Exception:
                        tvals.append(v_ref)
                tv = torch.tensor(tvals, dtype=torch.float32) - float(v_ref)
                ttemp = float(cfg.get('value_prior_temp', 0.05))
                probs = torch.softmax(tv / ttemp, dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            ref_bc = ref_next
            budget = max(1.0, timed_ms - policy_ms)
            priors = {int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            recommended, ns, _el = sts.mcts_puct_timed(
                bc, budget, priors, float(cfg.get('cpuct_native', 3.0)),
                float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)))
            sims += int(ns)
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode == 'playplan_timed':
            # Play-to-Plan style prior: from each root action, play H greedy
            # policy steps to see where the action leads (play), score the
            # resulting state/path with the value net (plan), and feed the
            # resulting distribution to the native PUCT search as root priors.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                H = int(cfg.get('play_horizon', 2))
                K = int(cfg.get('play_samples', 1))
                scores = []
                for a in actions:
                    tot = 0.0
                    for _ in range(K):
                        bc2 = bc.clone()
                        a.execute(bc2)
                        for _h in range(H):
                            if bc2.outcome != sts.Outcome.UNDECIDED:
                                break
                            ac2 = sts.get_legal_actions(bc2)
                            if not ac2:
                                break
                            st2 = B.encode_battle(bc2)
                            hd2 = list(bc2.hand)
                            lg = policy.score(st2, [B.cand_desc(bc2, x, hd2) for x in ac2])
                            ac2[int(lg.argmax())].execute(bc2)
                        if bc2.outcome != sts.Outcome.UNDECIDED:
                            v = 2.0 if bc2.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
                        else:
                            v = float(value.value(B.encode_battle(bc2)).item())
                        tot += v
                    scores.append(tot / K)
                tv = torch.tensor(scores, dtype=torch.float32)
                ttemp = float(cfg.get('value_prior_temp', 0.05))
                probs = torch.softmax((tv - tv.max()) / ttemp, dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            budget = max(1.0, timed_ms - policy_ms)
            priors = {int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            recommended, ns, _el = sts.mcts_puct_timed(
                bc, budget, priors, float(cfg.get('cpuct_native', 3.0)),
                float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)))
            sims += int(ns)
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode in ('puct_restarts_timed', 'native_restarts_timed'):
            # Restart portfolio (Go-Exploit-style): split the decision budget
            # over independent searches started from the root state with
            # different RNG streams, then keep the action of the best line
            # found by any of them.  The best-line statistic is an extremum,
            # so independent restarts raise it.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                probs = torch.softmax(logits / float(cfg.get('prior_temp', 1.0)), dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            budget = max(1.0, timed_ms - policy_ms)
            prior_map = {} if mode == 'native_restarts_timed' else {
                int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            recommended, count, _el = sts.mcts_restarts_timed(
                bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                int(cfg.get('restarts', 2)), mode == 'puct_restarts_timed')
            sims += int(count)
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode in ('native_q_timed', 'gaz_timed'):
            # GAZ (Gumbel AlphaZero, Danihelka et al. ICLR 2022) root policy
            # improvement: act by  argmax_a  g_a + log pi_a + sigma(completed Q_a)
            # with sigma(q)=(c_visit+max N)*c_scale*q and unvisited edges filled
            # with the prior-weighted mean Q.  This replaces native's "first
            # action of the single luckiest line" rule with an average-value
            # rule over all root edges.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                probs = torch.softmax(logits / float(cfg.get('prior_temp', 1.0)), dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            budget = max(1.0, timed_ms - policy_ms)
            prior_map = {} if mode == 'native_q_timed' else {
                int(a.bits): float(pr) for a, pr in zip(actions, probs)}
            nbits, nvisits, esums, count = sts.mcts_stats_timed(
                bc, budget, prior_map, float(cfg.get('cpuct_native', 3.0)),
                float(cfg.get('puct_anneal', 0.0)), int(cfg.get('puct_prior_mode', 0)),
                mode == 'gaz_timed')
            sims += int(count)
            qraw = [(esums[i] / nvisits[i]) if nvisits[i] > 0 else None
                    for i in range(len(nbits))]
            seen = [x for x in qraw if x is not None]
            lo, hi = (min(seen), max(seen)) if seen else (0.0, 1.0)
            span = hi - lo if hi > lo else 1.0
            qn = [None if x is None else (x - lo) / span for x in qraw]
            pw = sum(prior_map.get(int(b), 0.0) for b in nbits)
            if pw > 0:
                vmix = sum(prior_map.get(int(b), 0.0) * qn[i]
                           for i, b in enumerate(nbits) if qn[i] is not None) / pw
            elif seen:
                vmix = statistics.mean(x for x in qn if x is not None)
            else:
                vmix = 0.5
            qhat = [x if x is not None else vmix for x in qn]
            max_n = max(nvisits) if nvisits else 1
            c_visit = float(cfg.get('gaz_c_visit', 50.0))
            c_scale = float(cfg.get('gaz_c_scale', 1.0))
            sigma = [(c_visit + max_n) * c_scale * x for x in qhat]
            gum = [-math.log(-math.log(max(1e-12, rng.random()))) for _ in nbits]
            if prior_map:
                plog = [math.log(max(1e-9, prior_map.get(int(b), 0.0))) for b in nbits]
            else:
                plog = [0.0] * len(nbits)
            score = [plog[i] + gum[i] + sigma[i] for i in range(len(nbits))]
            pick = max(range(len(score)), key=lambda i: score[i])
            idx = next((i for i, a in enumerate(actions) if a.bits == nbits[pick]), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode == 'native_visits_timed':
            # Native rollout search, but pick the most-visited root action
            # instead of the first action of the single best-scoring line.
            _best, nbits, nvisits, count = sts.mcts_visits_timed(bc, timed_ms)
            sims += int(count)
            pick = max(range(len(nbits)), key=lambda i: nvisits[i])
            idx = next((i for i, a in enumerate(actions) if a.bits == nbits[pick]), -1)
            if idx < 0:
                with torch.inference_mode():
                    logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                idx = int(logits.argmax())
        elif mode in ('native', 'native_timed'):
            if mode == 'native_timed':
                recommended, ns, _elapsed = sts.mcts_recommend_timed(bc, timed_ms)
                sims += int(ns)
            else:
                recommended = sts.mcts_recommend(bc, int(cfg['eval_sims']))
                sims += int(cfg['eval_sims'])
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:  # native can propose actions outside get_legal_actions
                with torch.inference_mode():
                    logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                idx = int(logits.argmax())
        elif mode in ('puct_forest', 'puct_forest_timed'):
            # Many independent shallow PUCT trees whose root statistics are
            # pooled.  Averaging Q over trees divides the value-net noise, which
            # is what makes extra wall-clock useful without a single deep tree.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
            per = int(cfg.get('forest_sims', 512))
            noise = float(cfg.get('forest_noise', 0.0))
            total = [0.0] * len(actions)
            wsum = [0.0] * len(actions)
            trees = 0
            if mode == 'puct_forest':
                budget = int(cfg.get('forest_trees', 8))
                while trees < budget:
                    tree = MC.Node(bc.clone())
                    MC.simulate(tree, policy, value)
                    if noise > 0.0:
                        d = np.random.dirichlet([0.3] * len(tree.P))
                        tree.P = ((1.0 - noise) * np.asarray(tree.P) + noise * d).tolist()
                    for _ in range(per - 1):
                        MC.simulate(tree, policy, value)
                    if tree.cands is None or len(tree.N) != len(actions):
                        raise RuntimeError('Forest search produced mismatched candidates')
                    for i in range(len(actions)):
                        total[i] += tree.N[i]
                        wsum[i] += tree.W[i]
                    trees += 1
            else:
                deadline = time.perf_counter() + timed_ms / 1000.0
                while trees == 0 or time.perf_counter() < deadline:
                    tree = MC.Node(bc.clone())
                    MC.simulate(tree, policy, value)
                    if noise > 0.0:
                        d = np.random.dirichlet([0.3] * len(tree.P))
                        tree.P = ((1.0 - noise) * np.asarray(tree.P) + noise * d).tolist()
                    for _ in range(per - 1):
                        MC.simulate(tree, policy, value)
                    if tree.cands is None or len(tree.N) != len(actions):
                        raise RuntimeError('Forest search produced mismatched candidates')
                    for i in range(len(actions)):
                        total[i] += tree.N[i]
                        wsum[i] += tree.W[i]
                    trees += 1
            if cfg.get('forest_q', 0):
                nsum = sum(total)
                cand = [i for i in range(len(actions)) if total[i] >= max(1.0, 0.02 * nsum)]
                idx = max(cand, key=lambda i: wsum[i] / total[i]) if cand else max(range(len(actions)), key=lambda i: total[i])
            else:
                idx = max(range(len(total)), key=lambda i: total[i])
            sims += per * trees
        elif mode in ('puct_native', 'puct_native_timed'):
            # AlphaGo-style PUCT over the native rollout tree: the C++ search
            # keeps its cheap random playouts and best-line selection, while
            # the learned policy supplies root priors so root edges are chosen
            # by Q + c*P*sqrt(N)/(1+n) instead of UCB, and new root children
            # are sampled proportional to P instead of uniformly.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
                tp = time.perf_counter()
                logits = policy.score(state, [B.cand_desc(bc, a, hand) for a in actions])
                pt = float(cfg.get('prior_temp', 1.0))
                probs = torch.softmax(logits / pt, dim=0).tolist()
                policy_ms = (time.perf_counter() - tp) * 1000.0
            if cfg.get('uniform_priors', 0):
                # Control: same PUCT/prior-sampling machinery, no learned prior.
                probs = [1.0 / len(actions)] * len(actions)
            priors = {int(a.bits): float(p) for a, p in zip(actions, probs)}
            c = float(cfg.get('cpuct_native', 3.0))
            anneal = float(cfg.get('puct_anneal', 0.0))
            pmode = int(cfg.get('puct_prior_mode', 0))
            if mode == 'puct_native_timed':
                budget = max(1.0, timed_ms - policy_ms)
                recommended, ns, _el = sts.mcts_puct_timed(bc, budget, priors, c, anneal, pmode)
                sims += int(ns)
            else:
                recommended = sts.mcts_puct(bc, int(cfg['eval_sims']), priors, c, anneal, pmode)
                sims += int(cfg['eval_sims'])
            idx = next((i for i, a in enumerate(actions) if a.bits == recommended.bits), -1)
            if idx < 0:
                idx = max(range(len(probs)), key=lambda i: probs[i])
        elif mode == 'puct_timed':
            # Same wall-clock budget as time-matched native MCTS: run as many
            # PUCT simulations as fit, then take the most-visited move.
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
            tree = MC.Node(bc.clone())
            deadline = time.perf_counter() + timed_ms / 1000.0
            cap = int(cfg.get('eval_sim_cap', 0) or 0)
            n = 0
            while (n == 0 or time.perf_counter() < deadline) and (cap <= 0 or n < cap):
                MC.simulate(tree, policy, value)
                n += 1
            if tree.cands is None:
                raise RuntimeError('Eval search produced no candidates')
            idx = root_pick(tree, cfg)
            sims += n
        else:  # puct
            with torch.inference_mode():
                preds.append(float(value.value(state).item()))
            tree = MC.Node(bc.clone())
            for _ in range(int(cfg['eval_sims'])):
                MC.simulate(tree, policy, value)
            if tree.cands is None:
                raise RuntimeError('Eval search produced no candidates')
            idx = root_pick(tree, cfg)
            sims += int(cfg['eval_sims'])
        search_ms += (time.perf_counter() - t0) * 1000.0
        searched += 1
        actions[idx].execute(bc)
        decisions += 1
    z, win, hp = battle_targets(bc)
    vals = [(p, z) for p in preds]
    return dict(win=win, hp=hp, decisions=decisions, full=decisions,
                searched=searched, search_ms=search_ms, sims=sims,
                hp0=_hp0, maxhp=_maxhp, enc=_enc, floor=_floor,
                replayed=_repl, mismatches=_mism), vals


def play(job):
    seed, mode, wp, wv, cfg, fresh_prob = job
    started = time.perf_counter()
    try:
        policy, value = load_nets(wp, wv)
        agnet = load_armg()
        if mode in ('pure', 'puct', 'native', 'puct_timed', 'native_timed',
                    'puct_forest', 'puct_forest_timed', 'native_visits_timed',
                    'native_q_timed', 'gaz_timed',
                    'puct_restarts_timed', 'native_restarts_timed',
                    'puct_vprior_timed', 'playplan_timed', 'puct_refprior_timed',
                    'puct_greedy_timed', 'native_greedy_timed',
                    'puct_native', 'puct_native_timed'):
            r = run_fresh(seed, policy, value, agnet, cfg, random.Random(seed), mode=mode)
            return dict(kind='eval', seed=seed, status='ok', error=None,
                        floor=r['floor'], win=r['win'], battles=r['battles'],
                        values=r['values'], decisions=r['decisions'], samples=[],
                        seconds=time.perf_counter() - started)
        rng = random.Random(seed * 1000003 + 17)
        if ARCHIVE and rng.random() >= fresh_prob:
            bc = ARCHIVE[rng.randrange(len(ARCHIVE))].clone()
            samples, stats = run_battle(bc, policy, value, cfg, rng,
                                        archive=True, from_archive=True)
            return dict(kind='train', source='archive', seed=seed, status='ok', error=None,
                        floor=0, win=stats['win'], battles=[stats], values=[],
                        decisions=stats['decisions'], samples=samples,
                        seconds=time.perf_counter() - started)
        r = run_fresh(seed, policy, value, agnet, cfg, rng, mode='train')
        return dict(kind='train', source='fresh', seed=seed, status='ok', error=None,
                    floor=r['floor'], win=r['win'], battles=r['battles'], values=[],
                    decisions=r['decisions'], samples=r['samples'],
                    seconds=time.perf_counter() - started)
    except Exception:
        return dict(kind=mode, seed=seed, status='error', error=traceback.format_exc(),
                    samples=[], battles=[], values=[], decisions=0,
                    seconds=time.perf_counter() - started)


# ------------------------------------------------------------------- training
def train_models(policy, value, op, ov, buffer, epochs, batch, aux_w, mix):
    """Batched training: one value forward/backward per batch, one policy forward
    per batch with per-sample log-softmax over that sample's candidates."""
    idxs = list(range(len(buffer)))
    for ep in range(epochs):
        random.Random(1000 + ep).shuffle(idxs)
        for start in range(0, len(idxs), batch):
            chunk = idxs[start:start + batch]
            states = torch.from_numpy(np.stack([buffer[j][0] for j in chunk]))
            main_t = torch.tensor(
                [buffer[j][3] if (mix <= 0.0 or buffer[j][6] is None)
                 else (1.0 - mix) * buffer[j][3] + mix * buffer[j][6]
                 for j in chunk], dtype=torch.float32)
            win_t = torch.tensor([buffer[j][4] for j in chunk], dtype=torch.float32)
            hp_t = torch.tensor([buffer[j][5] for j in chunk], dtype=torch.float32)
            raw, win_logit, hp_logit = value.forward_tensor(states)
            loss_v = torch.nn.functional.smooth_l1_loss(raw, main_t, beta=0.25)
            loss_v = loss_v + aux_w[0] * torch.nn.functional.binary_cross_entropy_with_logits(
                win_logit, win_t)
            loss_v = loss_v + aux_w[1] * torch.nn.functional.mse_loss(
                torch.sigmoid(hp_logit), hp_t)
            ov.zero_grad()
            loss_v.backward()
            torch.nn.utils.clip_grad_norm_(value.parameters(), 1.0, error_if_nonfinite=True)
            ov.step()

            rows_list = []
            visits = []
            sizes = []
            for j in chunk:
                state, cands, visit, _, _, _, _ = buffer[j]
                if visit is None:
                    continue
                rows = np.empty((len(cands), B.INPUT_DIM), dtype=np.float32)
                rows[:, :B.STATE_DIM] = state
                rows[:, B.STATE_DIM:] = cands
                rows_list.append(rows)
                visits.append(torch.from_numpy(visit))
                sizes.append(len(cands))
            if not rows_list:
                continue
            logits = policy.net(torch.from_numpy(np.concatenate(rows_list))).squeeze(-1)
            losses = []
            pos = 0
            for size, target in zip(sizes, visits):
                logp = torch.log_softmax(logits[pos:pos + size], dim=0)
                losses.append(-(target * logp).sum())
                pos += size
            loss_p = torch.stack(losses).mean()
            op.zero_grad()
            loss_p.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0, error_if_nonfinite=True)
            op.step()


# ------------------------------------------------------------------ evaluation
def summarize_eval(rows):
    floors = [r['floor'] for r in rows]
    battles = [b for r in rows for b in r['battles']]
    preds = np.array([p for r in rows for (p, z) in r['values']]) if any(r['values'] for r in rows) else np.array([])
    zs = np.array([z for r in rows for (p, z) in r['values']]) if any(r['values'] for r in rows) else np.array([])
    out = dict(n=len(rows),
               mean_floor=statistics.mean(floors),
               wins=sum(r['win'] for r in rows),
               battles=len(battles),
               battle_win=statistics.mean(b['win'] for b in battles) if battles else float('nan'),
               battle_hp=statistics.mean(b['hp'] for b in battles) if battles else float('nan'),
               decisions=sum(r['decisions'] for r in rows))
    if len(preds):
        mse = float(((preds - zs) ** 2).mean())
        base = float(((preds - zs.mean()) ** 2).mean())
        out.update(value_mse=mse, value_r2=(1.0 - mse / base) if base > 0 else float('nan'))
    return out


def evaluate(pool, wp, wv, seeds, cfg):
    jobs = [(s, 'puct', str(wp), str(wv), cfg, 1.0) for s in seeds]
    rows = list(pool.map(play, jobs))
    for r in rows:
        if r['status'] != 'ok':
            raise RuntimeError(r['error'])
    puct = summarize_eval(rows)
    jobs = [(s, 'pure', str(wp), str(wv), cfg, 1.0) for s in seeds]
    rows = list(pool.map(play, jobs))
    for r in rows:
        if r['status'] != 'ok':
            raise RuntimeError(r['error'])
    pure = summarize_eval(rows)
    return dict(puct=puct, pure=pure)


def summarize_train(rows):
    battles = [b for r in rows for b in r['battles']]
    return dict(episodes=len(rows),
                fresh=sum(r.get('source') == 'fresh' for r in rows),
                archive=sum(r.get('source') == 'archive' for r in rows),
                samples=sum(len(r['samples']) for r in rows),
                decisions=sum(r['decisions'] for r in rows),
                battles=len(battles),
                battle_win=statistics.mean(b['win'] for b in battles) if battles else float('nan'),
                battle_hp=statistics.mean(b['hp'] for b in battles) if battles else float('nan'))


# ------------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--rounds', type=int, default=5)
    p.add_argument('--episodes', type=int, default=600)
    p.add_argument('--first-episodes', type=int, default=400)
    p.add_argument('--epochs', type=int, default=2)
    p.add_argument('--workers', type=int, default=64)
    p.add_argument('--eval-count', type=int, default=50)
    p.add_argument('--eval-sims', type=int, default=512)
    p.add_argument('--n-full', type=int, default=2048)
    p.add_argument('--n-fast', type=int, default=96)
    p.add_argument('--p-full', type=float, default=0.5)
    p.add_argument('--fresh-prob', type=float, default=0.1)
    p.add_argument('--first-fresh-prob', type=float, default=0.5)
    p.add_argument('--archive-every', type=int, default=8)
    p.add_argument('--archive-policy', type=int, default=1)
    p.add_argument('--behavior', choices=('search', 'pure'), default='search')
    p.add_argument('--native-frac', type=float, default=0.0)
    p.add_argument('--native-sims', type=int, default=2000)
    p.add_argument('--aux-win', type=float, default=0.5)
    p.add_argument('--aux-hp', type=float, default=0.5)
    p.add_argument('--value-mix', type=float, default=0.0)
    p.add_argument('--buffer-cap', type=int, default=80000)
    p.add_argument('--batch', type=int, default=64)
    p.add_argument('--value-hidden', type=int, default=0)
    p.add_argument('--lr-policy', type=float, default=3e-4)
    p.add_argument('--lr-value', type=float, default=3e-4)
    p.add_argument('--resume', type=Path, default=None)
    p.add_argument('--resume-round', type=int, default=0)
    p.add_argument('--gate', type=int, default=0)
    p.add_argument('--gate-margin', type=float, default=0.0)
    p.add_argument('--n-full-growth', type=float, default=1.0)
    p.add_argument('--n-full-max', type=int, default=8192)
    p.add_argument('--native-sims-growth', type=float, default=1.0)
    p.add_argument('--native-sims-max', type=int, default=8192)
    p.add_argument('--prune-thr', type=float, default=0.0)
    p.add_argument('--native-timed-ms', type=float, default=0.0)
    p.add_argument('--native-soft', type=int, default=0)
    p.add_argument('--n-full-timed-ms', type=float, default=0.0)
    p.add_argument('--search-archive', type=float, default=0.0)
    p.add_argument('--n-full-timed-growth', type=float, default=1.0)
    p.add_argument('--n-full-timed-max', type=float, default=1e9)
    p.add_argument('--eval-timed-ms', type=float, default=130.0)
    p.add_argument('--seed', type=int, default=20261026)
    a = p.parse_args()

    out = a.out.resolve()
    if out.exists():
        raise SystemExit('output directory already exists: ' + str(out))
    out.mkdir(parents=True)
    source = out / 'source'
    source.mkdir()
    parent = a.resume.resolve() if a.resume else None
    if parent is not None:
        psrc = parent / 'source'
        if not psrc.is_dir():
            raise SystemExit('resume source missing: ' + str(psrc))
        for f in psrc.iterdir():
            if f.is_file():
                shutil.copy2(f, source)
        start = a.resume_round
        if start <= 0:
            raise SystemExit('--resume-round must be > 0')
        for kind in ('policy', 'value'):
            src = parent / f'round{start}_{kind}.pt'
            if not src.exists():
                raise SystemExit('missing resume weights: ' + str(src))
            shutil.copy2(src, out / f'round{start}_{kind}.pt')
    else:
        template = ROOT / 'deployment/training_audit_v3/selfplay'
        for pattern in ('*.py', 'armS_card_vocab.json', 'armG_model_G128x128_15k.pt'):
            for f in template.glob(pattern):
                shutil.copy2(f, source)
        from stabilize_selfplay import patch_source
        patch_source(source)
        weights = ROOT / 'sts-rl-agent/weights'
        shutil.copy2(weights / 'armB_model_B256x256.pt', out / 'round0_policy.pt')
        shutil.copy2(weights / 'armB_model_VAL256x256.pt', out / 'round0_value.pt')
        start = 0
    shutil.copy2(__file__, out / 'driver_snapshot.py')
    shutil.copy2(ROOT / 'deployment/fast_puct.py', out / 'fast_puct.py')

    os.environ['STS_FAST_PUCT'] = '1'
    init_worker(str(source))

    if a.value_hidden > 0:
        os.environ['STS_VALUE_ARCH'] = f'{a.value_hidden},{a.value_hidden}'
        globals()['V_ARCH'] = (a.value_hidden, a.value_hidden)
        vpath = out / f'round{start}_value.pt'
        sd = torch.load(vpath, weights_only=True)
        old = sd['net.0.weight'].shape[0]
        if old != a.value_hidden:
            if a.value_hidden != 2 * old:
                raise SystemExit('value widening only supports doubling the hidden size')
            new = {}
            new['net.0.weight'] = torch.cat([sd['net.0.weight'], sd['net.0.weight']], 0)
            new['net.0.bias'] = torch.cat([sd['net.0.bias'], sd['net.0.bias']], 0)
            w2 = sd['net.2.weight']
            n2 = torch.zeros(2 * old, 2 * old)
            n2[:old, :old] = w2
            n2[old:, old:] = torch.eye(old)
            new['net.2.weight'] = n2
            new['net.2.bias'] = torch.cat([sd['net.2.bias'], torch.zeros(old)])
            new['net.4.weight'] = torch.cat([sd['net.4.weight'], torch.zeros(1, old)], 1)
            new['net.4.bias'] = sd['net.4.bias']
            for k in ('aux_win', 'aux_hp'):
                new[k + '.weight'] = torch.cat([sd[k + '.weight'], torch.zeros(1, old)], 1)
                new[k + '.bias'] = sd[k + '.bias']
            torch.save(new, vpath)
            torch.save(new, out / f'round{start}_value_256.pt')
            print(f'widened value {old} -> {a.value_hidden}', flush=True)

    eval_seeds = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
                  .read_text(encoding='utf-8').splitlines()
                  if x.strip() and not x.startswith('#')][:a.eval_count]
    eval_set = set(eval_seeds)
    seed_rng = random.Random(a.seed)

    def fresh_seeds(n):
        found = []
        while len(found) < n:
            s = seed_rng.randint(1, 10 ** 9)
            if s not in eval_set:
                found.append(s)
        return found

    cfg = dict(eval_sims=a.eval_sims, n_full=a.n_full, n_fast=a.n_fast,
               p_full=a.p_full, archive_every=a.archive_every,
               archive_policy=a.archive_policy, behavior=a.behavior,
               prune_thr=a.prune_thr,
               native_frac=a.native_frac, native_sims=a.native_sims,
               native_soft=a.native_soft,
               search_archive=a.search_archive,
               native_timed_ms=a.native_timed_ms,
               n_full_timed_ms=a.n_full_timed_ms,
               eval_timed_ms=a.eval_timed_ms)

    policy, value = load_nets(out / f'round{start}_policy.pt', out / f'round{start}_value.pt')
    op = torch.optim.Adam(policy.parameters(), lr=a.lr_policy)
    ov = torch.optim.Adam(value.parameters(), lr=a.lr_value)
    buffer = []
    history = []
    if parent is not None and (parent / 'history.json').exists():
        history = [h for h in json.loads((parent / 'history.json').read_text(encoding='utf-8'))
                   if h['round'] <= start]
        history.sort(key=lambda h: h['round'])
    started = time.perf_counter()
    best = None
    for h in history:
        if 'puct' in h:
            score = (h['puct']['mean_floor'], h['puct']['battle_win'])
            if best is None or score > best[0]:
                best = (score, h['round'])

    config = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}
    config = {**config, 'out': str(out), 'eval_seeds': eval_seeds,
              'torch': torch.__version__, 'cuda_available': torch.cuda.is_available(),
              'noncombat': 'frozen ArmG G128x128_15k; Ironclad A0',
              'archive': 'worker-local circular archive of cloned BattleContexts',
              'playout_cap': 'full search decisions produce policy targets; all decisions produce value targets',
              'aux_weight': [a.aux_win, a.aux_hp], 'value_mix': a.value_mix,
              'sha256': {str(f): hashlib.sha256(f.read_bytes()).hexdigest()
                         for f in [Path(sts.__file__), Path(__file__), source / 'armG_model_G128x128_15k.pt']}}
    dump(out / 'config.json', config)

    def save_models(i):
        wp, wv = out / f'round{i}_policy.pt', out / f'round{i}_value.pt'
        torch.save(policy.state_dict(), wp)
        torch.save(value.state_dict(), wv)
        return wp, wv

    def log(msg):
        print(msg, flush=True)

    with ProcessPoolExecutor(max_workers=a.workers, initializer=init_worker,
                             initargs=(str(source),)) as pool:
        start_row = next((h for h in history if h['round'] == start), None)
        if start_row is not None and 'puct' in start_row and 'pure' in start_row:
            ev = {k: start_row[k] for k in ('puct', 'pure')}
            log(f'round {start}: reusing parent eval')
        else:
            log(f'evaluating round {start}')
            ev = evaluate(pool, out / f'round{start}_policy.pt',
                          out / f'round{start}_value.pt', eval_seeds, cfg)
            history = [h for h in history if h['round'] != start]
            history.append(dict(round=start, **ev))
            history.sort(key=lambda h: h['round'])
            dump(out / f'eval_{start}.json', ev)
        log(f'round {start}: ' + json.dumps(ev['puct']))

        for rnd in range(start + 1, start + a.rounds + 1):
            n_ep = a.first_episodes if (rnd == 1 and parent is None) else a.episodes
            fp = a.first_fresh_prob if (rnd == 1 and parent is None) else a.fresh_prob
            seeds = fresh_seeds(n_ep)
            jobs = [(s, 'train', str(out / f'round{rnd-1}_policy.pt'),
                     str(out / f'round{rnd-1}_value.pt'), cfg, fp) for s in seeds]
            futures = [pool.submit(play, j) for j in jobs]
            rows = []
            t_play = time.perf_counter()
            for f in as_completed(futures):
                r = f.result()
                if r['status'] != 'ok':
                    dump(out / 'error.json', r)
                    raise RuntimeError(r['error'])
                rows.append(r)
                dump(out / 'progress.json', dict(stage=f'train_{rnd}', done=len(rows),
                                                 total=n_ep, wall_seconds=time.perf_counter() - started))
            train_stats = summarize_train(rows)
            new = [s for r in rows for s in r['samples']]
            if not new:
                raise RuntimeError('no training samples')
            buffer = (buffer + new)[-a.buffer_cap:]
            t_train = time.perf_counter()
            train_models(policy, value, op, ov, buffer, a.epochs, a.batch,
                         (a.aux_win, a.aux_hp), a.value_mix)
            if not all(torch.isfinite(t).all() for net in (policy, value) for t in net.parameters()):
                raise RuntimeError('nonfinite weights')
            wp, wv = save_models(rnd)
            ev = evaluate(pool, wp, wv, eval_seeds, cfg)
            raw_floors = {k: ev[k]['mean_floor'] for k in ev}
            dump(out / f'eval_raw_{rnd}.json', ev)
            shutil.copy2(wp, out / f'round{rnd}_raw_policy.pt')
            shutil.copy2(wv, out / f'round{rnd}_raw_value.pt')
            log(f"round {rnd}: raw floors {json.dumps(raw_floors)}")
            gated = False
            if a.gate and best is not None and ev['puct']['mean_floor'] < best[0][0] - a.gate_margin:
                prev_wp = out / f'round{rnd-1}_policy.pt'
                prev_wv = out / f'round{rnd-1}_value.pt'
                shutil.copy2(prev_wp, wp)
                shutil.copy2(prev_wv, wv)
                policy.load_state_dict(torch.load(prev_wp, weights_only=True))
                value.load_state_dict(torch.load(prev_wv, weights_only=True), strict=False)
                best_row = next(h for h in history if h['round'] == best[1])
                ev = {'puct': best_row['puct'], 'pure': best_row['pure']}
                gated = True
            row = dict(round=rnd, train=train_stats, buffer=len(buffer),
                       gated=gated,
                       play_seconds=time.perf_counter() - t_play,
                       train_seconds=time.perf_counter() - t_train, **ev)
            history.append(row)
            dump(out / f'eval_{rnd}.json', ev)
            dump(out / 'history.json', history)
            score = (ev['puct']['mean_floor'], ev['puct']['battle_win'])
            if best is None or (not gated and score > best[0]):
                best = (score, rnd)
            log(f"round {rnd}: train {json.dumps(train_stats)}")
            log(f"round {rnd}: gated {gated}")
            log(f"round {rnd}: puct {json.dumps(ev['puct'])}")
            log(f"round {rnd}: pure {json.dumps(ev['pure'])}")
            old_full, old_native = cfg['n_full'], cfg['native_sims']
            old_ms = cfg['n_full_timed_ms']
            cfg['n_full'] = min(a.n_full_max, max(1, int(round(cfg['n_full'] * a.n_full_growth))))
            cfg['native_sims'] = min(a.native_sims_max,
                                     max(1, int(round(cfg['native_sims'] * a.native_sims_growth))))
            if cfg['n_full_timed_ms'] > 0.0:
                cfg['n_full_timed_ms'] = min(a.n_full_timed_max,
                                             cfg['n_full_timed_ms'] * a.n_full_timed_growth)
            if (cfg['n_full'], cfg['native_sims'], cfg['n_full_timed_ms']) != (old_full, old_native, old_ms):
                log(f"round {rnd}: next search budget n_full={cfg['n_full']} "
                    f"native_sims={cfg['native_sims']} n_full_timed_ms={cfg['n_full_timed_ms']}")

    dump(out / 'results.json', dict(history=history, best_round=best[1] if best else 0,
                                    wall_seconds=time.perf_counter() - started))
    dump(out / 'progress.json', dict(stage='complete', wall_seconds=time.perf_counter() - started))
    log('COMPLETE')


if __name__ == '__main__':
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    main()
