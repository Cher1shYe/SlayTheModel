"""Whole-episode FIFO replay; a single atomic manifest is the commit point."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from .config import ACTION_VERSION, CONTENT_VERSION, REWARD_VERSION, RULES_VERSION, atomic_json, content_hash
from .content import M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, PROFILES, profiles
from .encoder import CARDS, schema_for
from .rewards import V2, V3, V4, terminal_reward


def episode_digest(episode):
    canonical = deepcopy(episode)
    # Retried jobs have identical labels but different wall-clock measurements.
    for row in canonical["rows"]:
        row["search_seconds"] = 0.0
    return content_hash(canonical)


class ReplayBuffer:
    def __init__(self, directory, capacity=200_000, information_mode="observable", reward_version=REWARD_VERSION, content_version=CONTENT_VERSION):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Positive replay capacity required")
        self.directory = Path(directory)
        self.content_version = content_version
        schema = schema_for(information_mode, reward_version, content_version)
        self.compatibility = dict(information_mode=information_mode, encoder_version=schema["encoder_version"],
                                  schema_hash=content_hash(schema), action_schema_version=schema["action_schema_version"],
                                  reward_version=reward_version, rules_version=RULES_VERSION)
        self.schema = schema
        self.capacity = capacity
        self.episodes = []
        self.committed = {}
        path = self.directory / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest["compatibility"] != self.compatibility or manifest["capacity"] != capacity:
                raise ValueError("Replay version/capacity mismatch")
            self.committed = manifest["committed"]
            for episode_id in manifest["active"]:
                episode = json.loads((self.directory / "episodes" / f"{episode_id}.json").read_text(encoding="utf-8"))
                self.validate(episode)
                if episode_digest(episode) != self.committed[episode_id]:
                    raise ValueError("Replay episode checksum mismatch")
                self.episodes.append(episode)

    @property
    def size(self):
        return sum(len(e["rows"]) for e in self.episodes)

    def validate(self, episode):
        rows = episode.get("rows", [])
        if episode.get("complete") is not True or episode.get("split") != "train" or not rows:
            raise ValueError("Only complete nonempty training episodes may enter replay")
        episode_id = episode.get("episode_id", "")
        if len(episode_id) != 64 or any(c not in "0123456789abcdef" for c in episode_id):
            raise ValueError("Invalid episode identity")
        first = rows[0]
        reason = first["termination_reason"]
        if reason not in ("win", "death", "time_limit"):
            raise ValueError("Invalid terminal reason")
        for index, row in enumerate(rows):
            hp_range = (38, 40)
            if self.content_version in (M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
                profile = next((p for p in profiles(self.content_version).values() if p["encounter"] == row.get("encounter_id")), None)
                if profile is None or row["encounter_id"] != first["encounter_id"]:
                    raise ValueError("Missing/inconsistent supported encounter")
                hp_range = profile["hp"]
            expected_reward = terminal_reward(reason, row["final_hp"], row.get("initial_hp", 80),
                                              row.get("enemy_final_hp", 0), row.get("enemy_max_hp", 40),
                                              self.compatibility["reward_version"], enemy_initial_hp=row.get("enemy_initial_hp"), enemy_roster=row.get("enemy_roster"))
            if self.compatibility["reward_version"] == V4:
                expected_members = profile.get("members", tuple(name for name, p in profiles(self.content_version).items() if p is profile))
                if (tuple(e["monster_id"] for e in row["enemy_roster"]) != tuple(expected_members)
                        or row["enemy_roster"] != first["enemy_roster"]):
                    raise ValueError("Replay fixed roster differs from encounter/episode")
            if self.compatibility["reward_version"] in (V3, V4):
                if (type(row.get("enemy_initial_hp")) is not int or row["enemy_initial_hp"] != first["enemy_initial_hp"]
                        or not 0 < row["enemy_initial_hp"] <= row["enemy_max_hp"]
                        or row.get("content_manifest_version") != self.content_version):
                    raise ValueError("Missing/inconsistent v3 initial enemy HP/content")
            if self.compatibility["reward_version"] in (V2, V3, V4):
                for field in ("initial_hp", "enemy_final_hp", "enemy_max_hp"):
                    if field not in row or row[field] != first[field]:
                        raise ValueError("Missing/inconsistent HP reward metadata")
                if (any(type(row[field]) is not int for field in ("initial_hp", "enemy_final_hp", "enemy_max_hp", "final_hp"))
                        or not 0 < row["initial_hp"] <= 80 or not hp_range[0] <= row["enemy_max_hp"] <= hp_range[1]
                        or not 0 <= row["enemy_final_hp"] <= row["enemy_max_hp"]
                        or not 0 <= row["final_hp"] <= row["initial_hp"]
                        or not np.isclose(row["observation"]["numeric"][-1], row["initial_hp"] / 80, atol=1e-7)):
                    raise ValueError("Invalid HP reward fields/initial HP observation")
            if any(row.get(k) != v for k, v in self.compatibility.items()):
                raise ValueError("Incompatible replay version")
            if (row["episode_id"] != episode_id or row["step_index"] != index
                    or row["decisions"] != len(rows) or row["z"] != expected_reward
                    or any(row[k] != first[k] for k in ("termination_reason", "final_hp", "turns",
                                                       "model_version", "family_id", "scenario_id"))):
                raise ValueError("Inconsistent episode labels")
            mask = np.asarray(row["legal_mask"])
            pi = np.asarray(row["policy_target"], dtype=float)
            visits = np.asarray(row["root_visits"])
            action = row["chosen_action"]
            if (mask.shape != (self.schema["action_size"],) or mask.dtype != np.bool_ or not mask.any()
                    or pi.shape != (self.schema["action_size"],) or visits.shape != (self.schema["action_size"],)
                    or not np.isfinite(pi).all() or (pi < 0).any() or not np.isclose(pi.sum(), 1)
                    or (pi[~mask] != 0).any() or (visits[~mask] != 0).any()
                    or not np.isfinite(visits).all() or (visits < 0).any() or (visits != visits.astype(int)).any()
                    or type(action) is not int or not 0 <= action < self.schema["action_size"] or not mask[action]
                    or not np.isfinite(row["search_seconds"]) or row["search_seconds"] < 0):
                raise ValueError("Invalid search labels")
            if row["forced_action"]:
                if mask.sum() != 1 or row["search_simulations"] != 0 or visits.sum() != 0 or pi[action] != 1:
                    raise ValueError("Invalid forced action")
            elif (row["search_simulations"] <= 0 or visits.sum() != row["search_simulations"]
                  or not np.allclose(pi, visits / visits.sum())):
                raise ValueError("Policy target must equal raw normalized visits")
            observation = row["observation"]
            if set(observation) != set(self.schema["shapes"]):
                raise ValueError("Unexpected observation fields")
            for key, shape in self.schema["shapes"].items():
                array = np.asarray(observation[key])
                if array.shape != tuple(shape) or not np.isfinite(array).all():
                    raise ValueError("Observation shape/nonfinite mismatch")
            ids = np.asarray(observation["card_ids"])
            if ((ids < 0).any() or (ids >= len(self.schema["card_vocabulary"])).any() or (ids != ids.astype(int)).any()
                    or not np.array_equal(observation["legal_mask"], mask)):
                raise ValueError("Invalid observation cards/mask")

    def commit(self, episode):
        self.validate(episode)
        if len(episode["rows"]) > self.capacity:
            raise ValueError("Episode exceeds replay capacity")
        # Debug metadata is persisted separately and never exposed to the learner.
        payload = deepcopy({k: v for k, v in episode.items() if k not in ("debug", "worker_pid")})
        identity = payload["episode_id"]
        digest = episode_digest(payload)
        if identity in self.committed:
            if self.committed[identity] != digest:
                raise ValueError("Conflicting duplicate episode")
            return False
        active = self.episodes + [payload]
        while sum(len(e["rows"]) for e in active) > self.capacity:
            active.pop(0)
        committed = {**self.committed, identity: digest}
        atomic_json(self.directory / "episodes" / f"{identity}.json", payload)
        atomic_json(self.directory / "debug" / f"{identity}.json",
                    dict(metadata=episode.get("debug"), search_seconds=[r["search_seconds"] for r in episode["rows"]]))
        atomic_json(self.directory / "manifest.json", dict(compatibility=self.compatibility, capacity=self.capacity,
                    active=[e["episode_id"] for e in active], committed=committed))
        self.episodes, self.committed = active, committed
        return True

    def sample(self, count, rng):
        if type(count) is not int or count < 1 or not self.episodes:
            raise ValueError("Nonempty replay and positive batch size required")
        families = {}
        for episode in self.episodes:
            first = episode["rows"][0]
            stratum = first["family_id"]
            if self.content_version in (M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
                stratum += "/" + first["encounter_id"]
            families.setdefault(stratum, []).append(episode)
        names = sorted(families)
        batch, counts = [], Counter()
        for _ in range(count):
            family = names[int(rng.integers(len(names)))]
            episodes = families[family]
            episode = episodes[int(rng.integers(len(episodes)))]
            row = episode["rows"][int(rng.integers(len(episode["rows"])))]
            batch.append(deepcopy({k: row[k] for k in ("observation", "policy_target", "z")}))
            counts[family] += 1
        return batch, dict(counts)
