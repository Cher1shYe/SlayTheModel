"""Combat training data for the unified network (docs/claude-unified-net-design-20261116.md,
step 3): every searched combat decision with its run context and the run's per-act outcome.

Storage per part file (npz, float16 numerics):
* per combat: the run context (``RunContext.macro_observation()`` at the combat start, as
  ``unified_obs.run_context`` will use it), act, floor, kind, game seed, result (won, HP and
  potions before/after), and the episode's outcome labels (acts passed, outcome);
* per decision: the combat entity observation, the chosen action and the root visit counts
  of the teacher search, and its combat index.
The run context is constant during a fight, so it is stored once per combat.

``CombatSamples`` turns parts into training samples: ``UObs`` (run context + combat
entities), policy target, q labels / mask (outcome labels; TD targets replace them online)
and the combat auxiliary targets.
"""
from __future__ import annotations

import glob
from dataclasses import dataclass

import numpy as np

from . import unified_obs as uo

BOSS_FLOOR = (17, 33, 48)
KINDS = ("normal", "elite", "boss")


def acts_passed(final_floor: int, won: bool) -> list[bool]:
    return [bool(won or final_floor > BOSS_FLOOR[k]) for k in range(3)]


def q_labels(act: int, passed: list[bool]) -> tuple[np.ndarray, np.ndarray]:
    lab = np.zeros(3, np.float32); msk = np.zeros(3, np.float32)
    lab[0], msk[0] = passed[act], 1.0
    if act + 1 <= 2 and passed[act]:
        lab[1], msk[1] = passed[act + 1], 1.0
        if act + 2 <= 2 and passed[act + 1]:
            lab[2], msk[2] = passed[act + 2], 1.0
    return lab, msk


def make_recording_hook(budgets: dict, sink: list):
    """MacroEnv.combat_hook: the rollout MCTS plays (teacher), every decision is recorded,
    and the run context at the combat start is kept."""
    from . import combat_play as cp

    def hook(env, seed):
        m = env.rc.macro_observation()
        res = cp.play_rollout_mcts(env.rc, budgets, seed, record=True)
        res.meta.update(game_seed=int(env.game_seed), ctx=m)
        sink.append(res)
        return res.decisions, res.forced, res.simulations, res.ok
    return hook


def pack(records: list, episodes: dict) -> dict | None:
    """records: CombatResults from the hook; episodes: game_seed -> (final floor, won)."""
    records = [r for r in records if r.ok and r.obs and r.meta.get("game_seed") in episodes]
    if not records:
        return None
    ctx = [r.meta["ctx"] for r in records]
    obs = [o for r in records for o in r.obs]
    cat = lambda seq, k, dt: np.concatenate([np.asarray(o[k]).ravel() for o in seq]).astype(dt)
    passed = np.array([acts_passed(*episodes[r.meta["game_seed"]]) for r in records], bool)
    won_run = np.array([episodes[r.meta["game_seed"]][1] for r in records], bool)
    return dict(
        ctx_kind=cat(ctx, "kind", np.int16), ctx_id=cat(ctx, "id", np.int16),
        ctx_num=np.concatenate([np.asarray(m["num"], np.float32).reshape(len(m["kind"]), -1) for m in ctx]).astype(np.float16),
        ctx_len=np.array([len(m["kind"]) for m in ctx], np.int32),
        ctx_edges=np.concatenate([np.asarray(m["edges"]).reshape(-1, 2) for m in ctx]).astype(np.int16),
        ctx_edges_len=np.array([np.asarray(m["edges"]).reshape(-1, 2).shape[0] for m in ctx], np.int32),
        kind=cat(obs, "kind", np.int16), id=cat(obs, "id", np.int16),
        num=np.concatenate([np.asarray(o["num"], np.float32).reshape(len(o["kind"]), -1) for o in obs]).astype(np.float16),
        ent_len=np.array([len(o["kind"]) for o in obs], np.int32),
        cand_type=cat(obs, "cand_type", np.int8), cand_target=cat(obs, "cand_target", np.int16),
        cand_target2=cat(obs, "cand_target2", np.int16),
        cand_num=np.concatenate([np.asarray(o["cand_num"], np.float32).reshape(len(o["cand_type"]), -1) for o in obs]).astype(np.float16),
        cand_len=np.array([len(o["cand_type"]) for o in obs], np.int32),
        action=np.array([a for r in records for a in r.actions], np.int16),
        visits=np.concatenate([np.asarray(v, np.int32) for r in records for v in r.visits]),
        combat=np.concatenate([np.full(len(r.obs), i, np.int32) for i, r in enumerate(records)]),
        combat_kind=np.array([KINDS.index(r.kind) for r in records], np.int8),
        combat_act=np.array([r.act for r in records], np.int8), combat_floor=np.array([r.floor for r in records], np.int16),
        combat_won=np.array([r.won for r in records], bool),
        hp_before=np.array([r.hp_before for r in records], np.int16), hp_after=np.array([r.hp_after for r in records], np.int16),
        max_hp=np.array([r.max_hp for r in records], np.int16),
        potions_before=np.array([r.potions_before for r in records], np.int8),
        potions_after=np.array([r.potions_after for r in records], np.int8),
        game_seed=np.array([r.meta["game_seed"] for r in records], np.int64),
        acts_passed=passed, run_won=won_run)


@dataclass
class Sample:
    ctx: uo.RunContextPart    # shared by every decision of the combat (memory: stored once)
    cobs: dict                # the combat entity observation of this decision
    policy: np.ndarray        # [C] target distribution
    q: np.ndarray             # [3]
    q_mask: np.ndarray        # [3]
    aux: np.ndarray           # [3]: died, HP left / max HP, potions used
    combat: int
    game_seed: int
    kind: int

    @property
    def obs(self) -> uo.UObs:
        """Built on demand (run context + combat entities)."""
        return uo.combat_obs(self.ctx, self.cobs)


def _off(lengths):
    return np.concatenate([[0], np.cumsum(lengths)])


def load_part(path: str, target: str = "mix") -> list[Sample]:
    """target: 'action' (teacher's choice), 'visits' (root visit distribution) or 'mix'."""
    with np.load(path) as zf:
        z = {k: zf[k] for k in zf.files}
    co, eo = _off(z["ctx_len"]), _off(z["ctx_edges_len"])
    ctxs = []
    for c in range(len(z["ctx_len"])):
        m = {"kind": z["ctx_kind"][co[c]:co[c + 1]].astype(np.int64), "id": z["ctx_id"][co[c]:co[c + 1]].astype(np.int64),
             "num": z["ctx_num"][co[c]:co[c + 1]].astype(np.float32), "edges": z["ctx_edges"][eo[c]:eo[c + 1]].astype(np.int64)}
        ctxs.append(uo.run_context(m))
    no, cdo = _off(z["ent_len"]), _off(z["cand_len"])
    out = []
    for i in range(len(z["ent_len"])):
        c = int(z["combat"][i])
        o = {"kind": z["kind"][no[i]:no[i + 1]].astype(np.int64), "id": z["id"][no[i]:no[i + 1]].astype(np.int64),
             "num": z["num"][no[i]:no[i + 1]].astype(np.float32),
             "cand_type": z["cand_type"][cdo[i]:cdo[i + 1]].astype(np.int64),
             "cand_target": z["cand_target"][cdo[i]:cdo[i + 1]].astype(np.int64),
             "cand_target2": z["cand_target2"][cdo[i]:cdo[i + 1]].astype(np.int64),
             "cand_num": z["cand_num"][cdo[i]:cdo[i + 1]].astype(np.float32)}
        v = z["visits"][cdo[i]:cdo[i + 1]].astype(np.float32)
        onehot = np.zeros(len(v), np.float32); onehot[int(z["action"][i])] = 1.0
        vis = v / max(1.0, v.sum())
        pol = onehot if target == "action" else vis if target == "visits" else 0.5 * (onehot + vis)
        q, qm = q_labels(int(z["combat_act"][c]), list(z["acts_passed"][c]))
        mx = max(1, int(z["max_hp"][c]))
        aux = np.array([0.0 if z["combat_won"][c] else 1.0, z["hp_after"][c] / mx if z["combat_won"][c] else 0.0,
                        float(z["potions_before"][c]) - float(z["potions_after"][c])], np.float32)
        out.append(Sample(ctxs[c], o, pol, q, qm, aux, c, int(z["game_seed"][c]), int(z["combat_kind"][c])))
    return out


def part_files(dirs: list[str]) -> list[str]:
    return sorted(f for d in dirs for f in glob.glob(f"{d}/part_*.npz"))
