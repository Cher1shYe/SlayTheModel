"""Trajectory archive: every collected episode, stored once per rollout.

Separate from the PPO buffer (never fed back into PPO). Each decision keeps
its public entities, candidates, chosen action, behaviour log-probability and
value, and reward components; windows are rebuilt by index, not stored.
One compressed ``.npz`` per rollout, including compact paired-fork audit records.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .data import Episode
from .env import Observation, Outcome

FORMAT = "spire_rl.archive/3"          # 3 adds forks_json; public observation layout is unchanged
READABLE = ("spire_rl.archive/1", "spire_rl.archive/2", FORMAT)
_OBS_ARRAYS = ("kind", "id", "num", "edges", "cand_type", "cand_index", "cand_target", "cand_target2", "cand_num")


def write_rollout(path: Path, episodes: list[Episode], meta: dict) -> int:
    """Writes one rollout; returns the file size in bytes."""
    ep_rows, steps = [], []
    for ep in episodes:
        ep_rows.append(ep)
        steps.extend((ep, t) for t in range(len(ep)))
    out: dict[str, np.ndarray] = {
        "ep_id": np.array([e.episode_id for e in ep_rows], np.int64),
        "ep_seed": np.array([e.game_seed for e in ep_rows], np.int64),
        "ep_stage": np.array([e.stage for e in ep_rows], np.int16),
        "ep_outcome": np.array([int(e.outcome) for e in ep_rows], np.int8),
        "ep_length": np.array([len(e) for e in ep_rows], np.int32),
        "ep_floor": np.array([e.info.get("floor", -1) for e in ep_rows], np.int16),
        "ep_bootstrap_value": np.array([e.bootstrap_value for e in ep_rows], np.float32),
        "action": np.array([e.actions[t] for e, t in steps], np.int16),
        "logp": np.array([e.logp[t] for e, t in steps], np.float32),
        "value": np.array([e.value[t] for e, t in steps], np.float32),
        "value_comps": (np.stack([np.asarray(e.value_comps[t], np.float32) for e, t in steps])
                        if steps and all(len(e.value_comps) == len(e) for e in ep_rows)
                        else np.zeros((0, 3), np.float32)),
        "reward": np.stack([e.reward[t] for e, t in steps]) if steps else np.zeros((0, 4), np.float32),
        "phase": np.array([e.obs[t].phase for e, t in steps], np.int16),
    }
    for name in _OBS_ARRAYS:
        parts = [getattr(e.obs[t], name) for e, t in steps]
        out[name] = np.concatenate(parts) if parts else np.zeros(0)
        out[name + "_len"] = np.array([p.shape[0] for p in parts], np.int32)
    forks = []
    for i, ep in enumerate(ep_rows):
        for f in ep.info.get("forks", []):
            forks.append({"ep_index": i, "fork_id": f.fork_id, "t": f.t,
                          "options": f.options, "groups": f.groups, "group_level": f.group_level,
                          "screen": f.screen, "failed": f.failed,
                          "branches": [{**f.details.get((k, s), {}), "option": k, "seed_set": s,
                                        "return": f.returns.get((k, s))}
                                       for k, s in sorted(f.returns.keys() | f.details.keys())]})
    out["forks_json"] = np.frombuffer(json.dumps(forks).encode(), np.uint8)
    meta = {**meta, "format": FORMAT,
            "failure_reasons": {str(e.episode_id): e.failure_reason for e in ep_rows if e.failure_reason}}
    out["meta"] = np.frombuffer(json.dumps(meta, default=str).encode(), np.uint8)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(tmp, **out)
    tmp.replace(path)
    return path.stat().st_size


def read_rollout(path: Path) -> tuple[dict, list[Episode]]:
    z = np.load(path)
    meta = json.loads(bytes(z["meta"]).decode())
    if meta.get("format") not in READABLE:
        raise ValueError(f"{path}: unknown archive format {meta.get('format')!r}")
    offs = {n: np.concatenate([[0], np.cumsum(z[n + "_len"])]) for n in _OBS_ARRAYS}
    arrays = {n: z[n] for n in _OBS_ARRAYS}
    episodes, k = [], 0
    for i in range(len(z["ep_id"])):
        ep = Episode(int(z["ep_id"][i]), int(z["ep_seed"][i]), int(z["ep_stage"][i]))
        ep.outcome = Outcome(int(z["ep_outcome"][i]))
        ep.bootstrap_value = float(z["ep_bootstrap_value"][i])
        ep.failure_reason = meta["failure_reasons"].get(str(ep.episode_id), "")
        ep.info["floor"] = int(z["ep_floor"][i])
        for _ in range(int(z["ep_length"][i])):
            parts = {n: arrays[n][offs[n][k]:offs[n][k + 1]] for n in _OBS_ARRAYS}
            ep.obs.append(Observation(**parts, phase=int(z["phase"][k])))
            ep.actions.append(int(z["action"][k]))
            ep.logp.append(float(z["logp"][k]))
            ep.value.append(float(z["value"][k]))
            if "value_comps" in z.files and len(z["value_comps"]) > k:
                ep.value_comps.append(z["value_comps"][k])
            ep.reward.append(z["reward"][k])
            k += 1
        episodes.append(ep)
    if "forks_json" in z.files:
        from .rollout import Fork
        for row in json.loads(bytes(z["forks_json"]).decode()):
            ep = episodes[row["ep_index"]]
            f = Fork(row["fork_id"], ep, row["t"], row["options"], row["groups"],
                     row["group_level"], row["screen"], failed=row["failed"])
            for branch in row["branches"]:
                branch = dict(branch)
                key = (branch.pop("option"), branch.pop("seed_set"))
                value = branch.pop("return")
                if value is not None:
                    f.returns[key] = value
                f.details[key] = branch
            ep.info.setdefault("forks", []).append(f)
    z.close()
    return meta, episodes
