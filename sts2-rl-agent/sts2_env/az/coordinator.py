"""Synchronous rounds with atomic stage state and update-boundary recovery.

One coordinator owns an output directory. The state file is authoritative;
champion.json is a derived pointer repaired on restart.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import random
import platform
import numpy as np
import torch

from .config import CONTENT_VERSION, EpisodeLimits, atomic_json, content_hash, derive_seed
from .content import DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, validate_content
from .content import BOSS_CONTENT
from .evaluation import compare, evaluate_parallel
from .learner import Learner
from .network import PolicyValueNetwork, code_digest
from .model_io import load_checkpoint, save_checkpoint
from .replay_buffer import ReplayBuffer
from .scenarios import load_manifest, balanced_selection, save_manifest
from .self_play import CollectionJob, Collector, file_digest, initialize_worker
from .rewards import V1, validate_reward
from .search_config import LEGACY, validate_search


@dataclass(frozen=True)
class TrainingConfig:
    promotion_policy: str = 'network-only-v1'
    model_tier: str = 'mlp'
    microbatch_size: int = 64
    seed: int = 42
    workers: int = 4
    episodes_per_iteration: int = 256
    simulations: int = 64
    eval_simulations: int = 256
    validation_count: int = 256
    capacity: int = 200_000
    batch_size: int = 256
    updates: int = 200
    iterations: int = 3
    max_decisions: int = 400
    max_turns: int = 100
    reward_version: str = V1
    content_version: str = CONTENT_VERSION
    sampling_version: str = "standard"
    initial_checkpoint: str | None = None
    search_version: str = LEGACY

    def __post_init__(self):
        validate_reward(self.reward_version)
        validate_search(self.search_version)
        validate_content(self.content_version)
        if self.promotion_policy not in ('network-only-v1','network-utility-v1'):
            raise ValueError('Unknown promotion policy')
        if any(type(v) is not int or v < 1 for k, v in asdict(self).items() if k not in ("seed", "reward_version", "content_version", "sampling_version", "initial_checkpoint", "search_version", "model_tier", "promotion_policy")):
            raise ValueError("Positive integer training settings required")
        from .transformer_network import TIERS
        from .search_config import DYNAMIC
        if self.model_tier != 'mlp':
            from .entity_encoder import SUPPORTED
            if self.model_tier not in TIERS or self.search_version != DYNAMIC or SUPPORTED.get(self.content_version) != self.reward_version:
                raise ValueError('Transformer requires supported starter content and explicit dynamic search')
        elif self.search_version == DYNAMIC:
            raise ValueError('Dynamic search cannot use an MLP')
        if self.sampling_version != "standard":
            from .boss_curriculum import VERSION
            if self.sampling_version not in (VERSION,"boss-search-course-v1","transformer-g23e-course-v1","transformer-g23e-smoke-v1") or self.content_version != BOSS_CONTENT or self.episodes_per_iteration != 180:
                raise ValueError("Incompatible Boss curriculum configuration")
        if self.sampling_version.startswith('transformer-g23e-'):
            smoke = self.sampling_version == 'transformer-g23e-smoke-v1'
            if (self.model_tier != 'S' or self.initial_checkpoint is not None or self.promotion_policy != 'network-utility-v1'
                    or self.seed not in ((42,) if smoke else (42,43))
                    or self.iterations != (2 if smoke else 3)):
                raise ValueError('Frozen T3 requires independent S initialization and fixed seeds/rounds')
        if self.initial_checkpoint is not None and (type(self.initial_checkpoint) is not str or not self.initial_checkpoint):
            raise ValueError("Explicit initial checkpoint path required")
        if self.validation_count > 256:
            raise ValueError("Promotion manifest has exactly 256 slots")
        if self.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
            from .rewards import V3, V4, V5, V6
            expected = (V6 if self.content_version == BOSS_CONTENT else V5 if self.content_version == SUMMON_CONTENT
                        else V4 if self.content_version == MULTI_CONTENT else V3)
            if self.reward_version != expected or not 0 <= self.seed < 1024 or self.iterations > 1024 or self.episodes_per_iteration > 1024:
                raise ValueError("Incompatible deck generator configuration")


def save_training(path, learner, rng, replay, version, config, history, iteration):
    state = dict(optimizer=learner.optimizer.state_dict(), updates=learner.updates,
                 numpy_rng=rng.bit_generator.state, torch_rng=torch.get_rng_state(),
                 python_rng=random.getstate(), replay_hash=file_digest(replay.directory / "manifest.json"))
    save_checkpoint(path, learner.model, version, config, dict(history=history), iteration, state)


def restore_training(path, replay):
    model, payload = load_checkpoint(path, "observable", replay.compatibility["reward_version"], replay.content_version)
    state = payload["training_state"]
    if payload.get('format_version') == 'transformer-checkpoint-v1' and (payload['code_digest'] != code_digest()
            or payload['torch_version'] != str(torch.__version__)):
        raise ValueError('Transformer resume requires identical implementation/runtime')
    if state["replay_hash"] != file_digest(replay.directory / "manifest.json"):
        raise ValueError("Replay changed since training checkpoint")
    learner = Learner(model)
    learner.optimizer.load_state_dict(state["optimizer"])
    learner.updates = state["updates"]
    if (type(learner.updates) is not int or learner.updates < 0
            or learner.updates != len(payload["statistics"]["history"])):
        raise ValueError("Invalid training update history")
    if any(not torch.isfinite(v).all() for item in learner.optimizer.state.values()
           for v in item.values() if torch.is_tensor(v)):
        raise ValueError("Nonfinite optimizer state")
    rng = np.random.default_rng()
    rng.bit_generator.state = state["numpy_rng"]
    torch.set_rng_state(state["torch_rng"])
    random.setstate(state["python_rng"])
    return learner, rng, payload["statistics"]["history"]


class Coordinator:
    def __init__(self, output, manifest=None, config=None):
        self._writer_lock = None
        state_path = Path(output) / "state.json"
        content = (json.loads(state_path.read_text())["config"]["content_version"] if state_path.exists()
                   else (config.content_version if config else CONTENT_VERSION))
        if content in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
            from .run_lock import RunLock
            self._writer_lock = RunLock(output)
        try:
            self._initialize(output, manifest, config)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._writer_lock is not None:
            self._writer_lock.close()

    def _initialize(self, output, manifest=None, config=None):
        self.root = Path(output).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        initialize_worker()
        runtime = dict(python=platform.python_version(), torch=str(torch.__version__), numpy=np.__version__,
                       cpu_threads=1, deterministic_algorithms=True)
        state_path = self.root / "state.json"
        if state_path.exists():
            self.state = json.loads(state_path.read_text(encoding="utf-8"))
            self.config = TrainingConfig(**self.state["config"])
            if config is not None and config != self.config:
                raise ValueError("Resume configuration mismatch")
            if self.state["code_digest"] != code_digest():
                raise ValueError("Code changed: resume requires the same implementation")
            if self.state["runtime"] != runtime:
                raise ValueError("Resume dependency/runtime mismatch")
        else:
            if any(self.root.iterdir()):
                raise ValueError("New run requires an empty directory")
            if manifest is None:
                raise ValueError("New run requires a manifest")
            self.config = config or TrainingConfig()
            recipes = load_manifest(manifest)
            frozen = [r.to_dict() for r in recipes]
            atomic_json(self.root / "recipes.json", frozen)
            if self.config.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
                from .generation import generator_config
                atomic_json(self.root / "generator.json", self.generator_config())
            torch.manual_seed(self.config.seed)
            random.seed(self.config.seed)
            initialization = {}
            if self.config.initial_checkpoint:
                source = Path(self.config.initial_checkpoint).resolve()
                model, metadata = load_checkpoint(source, "observable", self.config.reward_version, self.config.content_version)
                initialization = dict(source=str(source), sha256=file_digest(source),
                                      source_code_digest=metadata.get("code_digest"), optimizer="fresh")
            else:
                if self.config.model_tier == 'mlp':
                    model = PolicyValueNetwork("observable", self.config.reward_version, self.config.content_version)
                else:
                    from .model_factory import create_transformer
                    model = create_transformer(self.config.model_tier,self.config.content_version,self.config.reward_version)
            actual_tier = getattr(getattr(model, 'config', None), 'tier', 'mlp')
            if actual_tier != self.config.model_tier:
                raise ValueError('Initial checkpoint architecture/tier mismatch')
            save_checkpoint(self.root / "initial.pt", model, "initial", asdict(self.config), {"initialization": initialization})
            self.state = dict(format_version=1, information_mode="observable", phase="collect", iteration=0,
                              champion="initial.pt", champion_hash=file_digest(self.root / "initial.pt"),
                              config=asdict(self.config), manifest_hash=content_hash(frozen), code_digest=code_digest(),
                              runtime=runtime, round_failed=False)
            self.persist()
        from .scenarios import CombatScenario
        frozen = json.loads((self.root / "recipes.json").read_text(encoding="utf-8"))
        if content_hash(frozen) != self.state["manifest_hash"]:
            raise ValueError("Frozen manifest changed")
        if self.config.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
            from .generation import generator_config
            if json.loads((self.root / "generator.json").read_text()) != self.generator_config():
                raise ValueError("Frozen generator changed")
        if self.state.get("information_mode") != "observable" or self.state.get("format_version") != 1:
            raise ValueError("Coordinator version mismatch")
        recipes = [CombatScenario.from_dict(r) for r in frozen]
        self.train = [r for r in recipes if r.split == "train"]
        self.validation = balanced_selection([r for r in recipes if r.split == "validation"], self.config.validation_count)
        if not self.train or len(self.validation) != self.config.validation_count:
            raise ValueError("Insufficient training/validation recipes")
        if any(r.content_manifest_version != self.config.content_version for r in recipes):
            raise ValueError("Manifest/config content mismatch")
        if file_digest(self.root / self.state["champion"]) != self.state["champion_hash"]:
            raise ValueError("Champion checkpoint was modified")
        load_checkpoint(self.root / self.state["champion"], "observable", self.config.reward_version, self.config.content_version)
        replay_class = ReplayBuffer
        if self.config.model_tier != 'mlp':
            from .entity_replay import EntityReplayBuffer
            replay_class = EntityReplayBuffer
        self.replay = replay_class(self.root / "replay", self.config.capacity, reward_version=self.config.reward_version,
                                   content_version=self.config.content_version, search_version=self.config.search_version)
        self.sync_champion()

    def persist(self):
        atomic_json(self.root / "state.json", self.state)

    def generator_config(self):
        if self.config.sampling_version.startswith('transformer-g23e-'):
            from .transformer_course import configuration, SMOKE_VERSION
            return configuration(self.config.sampling_version == SMOKE_VERSION)
        if self.config.sampling_version == "boss-search-course-v1":
            from .boss_search_curriculum import configuration
            return configuration()
        if self.config.sampling_version != "standard":
            from .boss_curriculum import configuration
            return configuration()
        from .generation import generator_config
        return generator_config(self.config.content_version)

    def sync_champion(self):
        atomic_json(self.root / "champion.json", dict(checkpoint=self.state["champion"],
                    sha256=self.state["champion_hash"], iteration=self.state["iteration"]))

    @property
    def limits(self):
        return EpisodeLimits(self.config.max_decisions, self.config.max_turns)

    def step(self, collector=None):
        if self._writer_lock is not None and self._writer_lock.stream.closed:
            raise RuntimeError("Coordinator writer lock was released")
        c, iteration, phase = self.config, self.state["iteration"], self.state["phase"]
        if phase == "done":
            return False
        champion, metadata = load_checkpoint(self.root / self.state["champion"], "observable", c.reward_version, c.content_version)
        version = f"candidate-{iteration}"
        training_path = self.root / f"training-{iteration}.pt"
        candidate_path = self.root / f"candidate-{iteration}.pt"
        if phase == "collect":
            jobs = []
            generated = None
            if c.content_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
                from .generation import generate_recipe
                generated = [generate_recipe(c.seed, iteration, j, content_version=c.content_version) for j in range(c.episodes_per_iteration)]
                if c.sampling_version != "standard":
                    from .boss_curriculum import generate
                    if c.sampling_version == "boss-search-course-v1":
                        from .boss_search_curriculum import generate
                    if c.sampling_version.startswith('transformer-g23e-'):
                        from functools import partial
                        from .transformer_course import generate, SMOKE_VERSION
                        generate = partial(generate,smoke=c.sampling_version == SMOKE_VERSION)
                    generated = [generate(c.seed, iteration, j) for j in range(c.episodes_per_iteration)]
                path = self.root / "manifests" / f"train-{iteration}.json"
                if path.exists():
                    if load_manifest(path) != generated:
                        raise ValueError("Round manifest changed")
                else:
                    save_manifest(path, generated)
            for j in range(c.episodes_per_iteration):
                job_id = str(j)
                identity = content_hash([c.seed, iteration, job_id])
                if identity in self.replay.committed:
                    continue
                rng = np.random.default_rng(derive_seed(c.seed, iteration, job_id, "scenario"))
                strata = sorted({(r.family_id, r.encounter_id) for r in self.train})
                group = [r for r in self.train if (r.family_id, r.encounter_id) == strata[j % len(strata)]]
                recipe = generated[j] if generated is not None else group[int(rng.integers(len(group)))]
                jobs.append(CollectionJob(job_id, iteration, c.seed, recipe.to_dict(),
                            str(self.root / self.state["champion"]), self.state["champion_hash"],
                            metadata["model_version"], str(self.root / "errors"), c.simulations, self.limits, c.reward_version, c.search_version))
            if jobs:
                def commit_collected(pool):
                    stream = getattr(pool, "iter_collect", pool.collect)(jobs)
                    for episode in stream:
                        self.replay.commit(episode)
                if collector is None:
                    with Collector(c.workers) as pool:
                        commit_collected(pool)
                else:
                    commit_collected(collector)
            self.state["phase"] = "train"
        elif phase == "train":
            if training_path.exists():
                learner, rng, history = restore_training(training_path, self.replay)
            else:
                learner = Learner(champion)
                rng = np.random.default_rng(derive_seed(c.seed, iteration, "learner", "batches"))
                history = []
            if learner.updates < c.updates:
                samples, counts = self.replay.sample(c.batch_size, rng)
                history.append(dict(learner.update(samples, microbatch_size=c.microbatch_size), family_counts=counts))
                save_training(training_path, learner, rng, self.replay, version, asdict(c), history, iteration)
            if learner.updates == c.updates:
                save_checkpoint(candidate_path, learner.model, version, asdict(c), dict(history=history), iteration)
                self.state.update(phase="evaluate", candidate_hash=file_digest(candidate_path))
        elif phase == "evaluate":
            if file_digest(candidate_path) != self.state["candidate_hash"]:
                raise ValueError("Candidate checkpoint was modified")
            candidate, _ = load_checkpoint(candidate_path, "observable", c.reward_version, c.content_version)
            runner = None
            if collector is not None:
                def runner(role, budget):
                    path = self.root / self.state["champion"] if role == "champion" else candidate_path
                    return evaluate_parallel(collector.pool, path, self.validation, budget, c.seed, self.limits,
                                             self.root / "evaluation_cache", reward_version=c.reward_version, search_version=c.search_version)
            report = compare(champion, candidate, metadata["model_version"], version, self.validation,
                             c.eval_simulations, c.seed, self.limits, str(self.root / "errors"), runner, c.reward_version, c.search_version,c.promotion_policy)
            # Smoke limits do not define the formal task, even with 256 scenarios.
            if self.limits != EpisodeLimits():
                report.update(promote=False, restriction="nonstandard_episode_limits")
            if self.state.get("round_failed"):
                report.update(promote=False, restriction="round_previously_failed")
            atomic_json(self.root / f"evaluation-{iteration}.json", report)
            self.state.update(phase="finalize", promote=report["promote"])
        elif phase == "finalize":
            if self.state["promote"]:
                if file_digest(candidate_path) != self.state["candidate_hash"]:
                    raise ValueError("Candidate checkpoint was modified")
                self.state.update(champion=candidate_path.name, champion_hash=self.state["candidate_hash"])
            self.state.update(iteration=iteration + 1, phase="done" if iteration + 1 >= c.iterations else "collect",
                              round_failed=False)
        else:
            raise ValueError("Unknown coordinator phase")
        self.persist()
        self.sync_champion()
        return True

    def run(self):
        with Collector(self.config.workers) as collector:
            while self.state["phase"] != "done":
                phase = self.state["phase"]
                try:
                    self.step(collector)
                except Exception as exc:
                    self.state["round_failed"] = True
                    self.persist()
                    atomic_json(self.root / "errors" / "coordinator.json", dict(state=self.state, error=repr(exc)))
                    raise
                if phase != "train" or self.state["phase"] != "train":
                    print(f"iteration={self.state['iteration']} phase={self.state['phase']}", flush=True)
        return self.state
