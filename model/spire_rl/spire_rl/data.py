"""Episode storage and batch construction.

Each stored decision keeps the raw public arrays once; history windows are
rebuilt by index (never 32 stored copies). The same collate function is used
for acting and for the PPO update, so window boundaries, positions and
candidate sets are identical in both.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch

from .env import Observation, Outcome
from .model import REWARD_FEATURES, MacroBatch


@dataclass
class Episode:
    episode_id: int
    game_seed: int
    stage: int
    obs: list[Observation] = field(default_factory=list)
    actions: list[int] = field(default_factory=list)
    logp: list[float] = field(default_factory=list)
    value: list[float] = field(default_factory=list)
    reward: list[np.ndarray] = field(default_factory=list)   # [REWARD_FEATURES] per transition
    outcome: Outcome = Outcome.RUNNING
    failure_reason: str = ""
    bootstrap_value: float = 0.0          # V(final state) for truncations
    final_obs: Observation | None = None
    aux: np.ndarray | None = None          # [T, 6]
    advantages: np.ndarray | None = None
    returns: np.ndarray | None = None
    info: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.actions)


def _pad(arrays: list[np.ndarray], length: int, fill, dtype) -> np.ndarray:
    shape = (len(arrays), length) + arrays[0].shape[1:]
    out = np.full(shape, fill, dtype=dtype)
    for i, a in enumerate(arrays):
        out[i, :a.shape[0]] = a
    return out


def collate(targets: list[tuple[Episode, int]], window: int, obs_override: dict | None = None) -> MacroBatch:
    """Build a batch whose targets are decision ``t`` of each episode.

    ``obs_override`` maps (episode_id, t) -> Observation for a target whose
    observation is not stored (truncation bootstrap); its window is otherwise
    the stored history.
    """
    unique: dict[tuple[int, int], int] = {}
    states: list[Observation] = []

    def state_index(ep: Episode, step: int) -> int:
        key = (ep.episode_id, step)
        if key not in unique:
            obs = obs_override[key] if obs_override and key in obs_override else ep.obs[step]
            unique[key] = len(states)
            states.append(obs)
        return unique[key]

    bsz = len(targets)
    win_state = np.full((bsz, window), -1, np.int64)
    win_act = np.zeros((bsz, window, 3), np.int64)
    win_act[..., 1:] = -1
    win_len = np.zeros(bsz, np.int64)
    win_phase = np.zeros((bsz, window), np.int64)
    win_stage = np.zeros((bsz, window), np.int64)
    win_abs = np.zeros((bsz, window), np.int64)
    win_reward = np.zeros((bsz, window, REWARD_FEATURES), np.float32)
    cand_k = None
    win_act_num = None
    tgt_state = np.zeros(bsz, np.int64)
    tgt_obs: list[Observation] = []
    for b, (ep, t) in enumerate(targets):
        start = max(0, t - window + 1)
        for j, step in enumerate(range(start, t + 1)):
            si = state_index(ep, step)
            win_state[b, j] = si
            obs = states[si]
            win_phase[b, j] = obs.phase
            win_stage[b, j] = ep.stage
            win_abs[b, j] = step
            if step < t:
                a = ep.actions[step]
                win_act[b, j] = (obs.cand_type[a], obs.cand_target[a], obs.cand_target2[a])
                if win_act_num is None:
                    cand_k = obs.cand_num.shape[1]
                    win_act_num = np.zeros((bsz, window, cand_k), np.float32)
                win_act_num[b, j] = obs.cand_num[a]
                win_reward[b, j] = ep.reward[step]
        win_len[b] = t - start + 1
        tgt_state[b] = win_state[b, t - start]
        tgt_obs.append(states[tgt_state[b]])
    if win_act_num is None:
        cand_k = tgt_obs[0].cand_num.shape[1]
        win_act_num = np.zeros((bsz, window, cand_k), np.float32)

    n_max = max(1, max(o.kind.shape[0] for o in states))
    ent_kind = _pad([o.kind for o in states], n_max, 0, np.int64)
    ent_id = _pad([o.id for o in states], n_max, 0, np.int64)
    ent_num = _pad([o.num for o in states], n_max, 0.0, np.float32)
    ent_mask = _pad([np.ones(o.kind.shape[0], bool) for o in states], n_max, False, bool)
    srcs, dsts = [], []
    for u, o in enumerate(states):
        if o.edges.shape[0]:
            srcs.append(o.edges[:, 0].astype(np.int64) + u * n_max)
            dsts.append(o.edges[:, 1].astype(np.int64) + u * n_max)
    edge_src = np.concatenate(srcs) if srcs else np.zeros(0, np.int64)
    edge_dst = np.concatenate(dsts) if dsts else np.zeros(0, np.int64)

    c_max = max(1, max(o.num_candidates for o in tgt_obs))
    cand_type = _pad([o.cand_type for o in tgt_obs], c_max, 0, np.int64)
    cand_t1 = _pad([o.cand_target for o in tgt_obs], c_max, -1, np.int64)
    cand_t2 = _pad([o.cand_target2 for o in tgt_obs], c_max, -1, np.int64)
    cand_num = _pad([o.cand_num for o in tgt_obs], c_max, 0.0, np.float32)
    cand_mask = _pad([np.ones(o.num_candidates, bool) for o in tgt_obs], c_max, False, bool)

    t = torch.from_numpy
    return MacroBatch(
        ent_kind=t(ent_kind), ent_id=t(ent_id), ent_num=t(ent_num), ent_mask=t(ent_mask),
        edge_src=t(edge_src), edge_dst=t(edge_dst),
        tgt_state=t(tgt_state), cand_type=t(cand_type), cand_t1=t(cand_t1), cand_t2=t(cand_t2),
        cand_num=t(cand_num), cand_mask=t(cand_mask),
        win_state=t(win_state), win_act_type=t(win_act[..., 0].copy()), win_act_t1=t(win_act[..., 1].copy()),
        win_act_t2=t(win_act[..., 2].copy()), win_act_num=t(win_act_num), win_reward=t(win_reward),
        win_phase=t(win_phase), win_stage=t(win_stage), win_abs=t(win_abs), win_len=t(win_len))
