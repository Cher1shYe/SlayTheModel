"""Serializable configuration for the macro (out-of-combat) policy.

Everything that changes behaviour lives here and is stored with the run
(config.json) and with best.pt.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    # Set Transformer over the current entities.
    set_dim: int = 512
    set_heads: int = 8
    set_layers: int = 2            # ISAB blocks
    inducing_points: int = 32
    map_message_rounds: int = 2    # neighbour passes over map links before the ST
    # Causal history Transformer over (goal, state, action, reward) tokens.
    hist_dim: int = 1024
    hist_heads: int = 16
    hist_layers: int = 14
    ff_mult: int = 4
    window: int = 32               # decision points per history window (incl. current)
    max_step_index: int = 512      # absolute decision index embedding (clamped)
    # Candidate scoring.
    action_dim: int = 512
    action_heads: int = 8
    dropout: float = 0.0
    # Policy = P(action group | state) * P(candidate | group, state). Without it a
    # screen with 1 heal + 15 upgrade candidates starts at 1/16 heal and a single
    # confirm among 15 card toggles starts at 1/16 confirm (run main-a0-s1 lost both).
    type_factorized: bool = True


PRESETS: dict[str, ModelConfig] = {
    # ~0.20B: main experiment.
    "main": ModelConfig(),
    # ~0.7B: fallback when ~1B does not fit or is too slow.
    "large-0.7b": ModelConfig(hist_dim=1536, hist_heads=24, hist_layers=24),
    # ~0.93-1.0B: preferred large comparison.
    "large-1b": ModelConfig(hist_dim=1536, hist_heads=24, hist_layers=32),
    # ~0.02B, 8-step history (run 4). Run 2 spent ~90% of its wall clock in the 0.2B
    # network; an imitation test found no measurable use of the 32-step history.
    "small": ModelConfig(set_dim=256, set_heads=8, set_layers=2, inducing_points=16,
                         hist_dim=512, hist_heads=8, hist_layers=4, window=8,
                         action_dim=256, action_heads=8),
    # Tiny shape for CPU tests and smoke runs only.
    "tiny": ModelConfig(set_dim=64, set_heads=4, set_layers=1, inducing_points=8,
                        hist_dim=64, hist_heads=4, hist_layers=2, window=8,
                        action_dim=64, action_heads=4),
}


# Separate critic (~15M). Run main-a0-s1's shared value head never learned
# (on-policy explained variance <= 0); a separate network trained for several
# value-only passes per update is not limited by the policy's KL early stop.
CRITIC_SMALL = ModelConfig(set_dim=256, set_heads=8, set_layers=2, inducing_points=16,
                           hist_dim=512, hist_heads=8, hist_layers=4, window=32,
                           action_dim=256, action_heads=8)
# Critic of the "small" preset (~1.9M, dropout). Run 2's 19.6M critic explained >0.95 of
# the variance of the batch it was just trained on and 0.06-0.17 of the next one; a
# three-feature linear fit (floor, HP, act) reached 0.23-0.34 on held-out data.
CRITIC_LITE = ModelConfig(set_dim=128, set_heads=4, set_layers=1, inducing_points=8,
                          hist_dim=128, hist_heads=4, hist_layers=2, window=4,
                          action_dim=128, action_heads=4, dropout=0.1)
CRITIC_TINY = ModelConfig(set_dim=32, set_heads=4, set_layers=1, inducing_points=4,
                          hist_dim=32, hist_heads=4, hist_layers=1, window=8,
                          action_dim=32, action_heads=4)


@dataclass(frozen=True)
class CombatConfig:
    """Fixed combat executor (C++ hidden-state MCTS); identical in train and eval."""
    normal_simulations: int = 128
    boss_simulations: int = 512
    exploration: float = 4.242640687   # 3 * sqrt(2)
    rollout_epsilon: float = 0.05
    potion_weight: float = 4.0


@dataclass(frozen=True)
class ForkConfig:
    """Paired forks (run 3): at some decisions the state is copied and each option is
    played forward with the SAME search seeds and sampling streams (common random
    numbers), so outcome differences between options are mostly due to the option.
    Campfire and map forks end at an act change, after ``max_combats`` fights, after
    ``max_decisions`` decisions or at the end of the run; the rest is estimated by
    the critic. Card-reward forks compare every offered card and skip, and by default
    run to the end of the act (through its boss) and count only what really happened.
    The centred option returns, normalized per screen, drive an extra policy loss.
    Probabilities are per eligible decision; 0 disables that screen.
    """
    rest_prob: float = 0.0       # campfire with >= 2 action groups (heal / upgrade / ...)
    map_prob: float = 0.0        # map with >= 2 moves
    card_prob: float = 0.0       # card reward: each card and skip
    seeds: int = 2               # paired seed sets per fork (at most 8)
    max_options: int = 4         # at most 8
    max_combats: int = 2
    max_decisions: int = 40
    max_active_branches: int = 96   # forks beyond this are skipped (which ones depends on timing)
    coef: float = 1.0            # weight of the fork policy loss
    # Card forks: a pick pays off many floors later, so two fights say little.
    card_to_act_end: bool = True     # no fight limit; stop at the act change or the end of the run
    card_max_decisions: int = 400    # safety cap (then the critic estimates the rest)
    card_bootstrap: bool = False     # add the critic's estimate of later acts at the act change
    # The critic's win output has seen 23 wins in 16,001 episodes (EV -0.04, values
    # between -0.04 and 0.35) and carries the largest weight; real wins inside a
    # branch always count, the critic's guess of later wins only if this is set.
    bootstrap_win: bool = False

    @property
    def enabled(self) -> bool:
        return max(self.rest_prob, self.map_prob, self.card_prob) > 0


@dataclass(frozen=True)
class RewardStage:
    until_episode: int     # inclusive upper bound of training starts in this stage
    alpha: float           # weight of floor / act progress shaping
    entropy_coef: float


@dataclass(frozen=True)
class RewardConfig:
    win: float = 5.0
    floor: float = 0.05
    act_entry: float = 0.5
    scale: float = 5.0     # r_train = r_raw / scale
    stages: tuple[RewardStage, ...] = (
        RewardStage(2000, 1.0, 0.020),
        RewardStage(4000, 0.5, 0.015),
        RewardStage(6000, 0.2, 0.010),
        RewardStage(10 ** 9, 0.0, 0.005),
    )
    # Gates before entering stage index 1 and the final (alpha = 0) stage.
    gate_act2_episodes: int = 1
    gate_win_seed_families: int = 10
    # "hold" (stay in the stage, keep training) or "stop" (pause for diagnosis).
    # Default changed to hold on 2026-11-10: run 1 stopped at 6,001 of 10,000 episodes.
    gate_policy: str = "hold"


@dataclass(frozen=True)
class PPOConfig:
    num_envs: int = 8
    min_transitions: int = 2048        # per rollout, then in-flight episodes finish
    epochs: int = 3                    # max passes; the sampled-KL stop usually ends earlier
    clip: float = 0.2
    target_kl: float = 0.01
    # KL early stop on a fixed sample of the rollout (not the current 128-target
    # minibatch, whose noisy estimate stopped every run-1 update after ~10 steps).
    kl_check_every: int = 8            # optimizer steps between checks
    kl_check_targets: int = 512
    kl_hard_mult: float = 4.0          # a single minibatch above mult * target still stops
    gamma: float = 1.0
    gae_lambda: float = 0.99
    batch_targets: int = 128           # targets per optimizer step
    microbatch: int = 4                # targets per forward (memory knob only)
    lr: float = 3e-5                   # policy (run 1: 1e-4, KL stop after ~10 steps / 0.65 passes)
    # Every run starts with a fresh Adam (weights-only checkpoints), whose first steps move
    # each weight by about lr regardless of the gradient. With warm-started weights and
    # daily restarts both learning rates therefore ramp from 10% to 100% over this many
    # policy optimizer steps (0 = off).
    lr_warmup_steps: int = 0
    betas: tuple[float, float] = (0.9, 0.999)
    eps: float = 1e-8
    weight_decay: float = 0.0
    max_grad_norm: float = 0.5
    value_coef: float = 0.5            # shared value head only (critic = None)
    critic_lr: float = 1e-4
    value_epochs: int = 2              # value-only passes of the separate critic per update (over current + replay)
    # Critic replay: each update also trains on a sample of up to this many earlier
    # rollouts (run 2's critic fitted each batch and forgot it: on-policy EV ~0.05,
    # while the same network trained offline on many rollouts reached ~0.29).
    critic_replay_rollouts: int = 12
    critic_replay_ratio: float = 1.0   # replay targets per current target in each critic update
    value_huber_delta: float = 1.0
    aux_survival_coef: float = 0.05
    aux_hp_coef: float = 0.02
    aux_hp_huber_delta: float = 0.1
    aux_act_coef: float = 0.05
    # Extra entropy bonus on the action-group distribution only (factorized policy),
    # so spreading mass over many targets of one group cannot hide that a whole
    # group (rest, skip, confirm, leave) went to zero.
    type_entropy_coef: float = 0.01
    bf16: bool = True                  # CUDA only; CPU always runs FP32
    activation_checkpointing: bool = True
    recompute_tolerance: float = 0.05  # max |logp_saved - logp_recomputed| before update


@dataclass(frozen=True)
class RunConfig:
    preset: str = "main"
    model: ModelConfig = field(default_factory=ModelConfig)
    critic: ModelConfig | None = CRITIC_SMALL   # None = value head of the policy network
    fork: ForkConfig = field(default_factory=ForkConfig)
    combat: CombatConfig = field(default_factory=CombatConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    ppo: PPOConfig = field(default_factory=PPOConfig)
    total_episodes: int = 10_000       # training starts, failures included
    ascension: int = 0
    seed: int = 1                      # training randomness (init, sampling, MCTS seeds)
    train_seed_base: int = 1_000_000   # game seeds of training episodes
    val_seeds: tuple[int, int] = (9_000_000, 200)    # (first, count), fixed family
    test_seeds: tuple[int, int] = (8_000_000, 1000)
    eval_every: int = 2000             # training starts between validation runs
    max_macro_steps: int = 600         # per episode safety cap (truncation); legit p99 was 136
    max_grid_steps: int = 64           # decisions inside one open card grid before a menu_loop truncation
    sweet_spot: tuple[int, int] = (8000, 20000)       # marked on the dashboard
    archive_trajectories: bool = True  # keep every collected episode (separate from the PPO buffer)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def fingerprint(self) -> str:
        """Hash of the settings that change what is learned.

        Operational knobs are excluded (budget, validation interval, sweet
        spot, archiving, num_envs, microbatch), so runs that differ only in
        those share a fingerprint.
        """
        d = self.to_dict()
        for key in ("total_episodes", "eval_every", "sweet_spot", "archive_trajectories"):
            d.pop(key)
        for key in ("num_envs", "microbatch"):
            d["ppo"].pop(key)
        blob = json.dumps(d, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RunConfig":
        reward = dict(d["reward"])
        reward["stages"] = tuple(RewardStage(**s) for s in reward["stages"])
        ppo = dict(d["ppo"])
        ppo["betas"] = tuple(ppo["betas"])
        return RunConfig(
            preset=d["preset"], model=ModelConfig(**d["model"]), combat=CombatConfig(**d["combat"]),
            reward=RewardConfig(**reward), ppo=PPOConfig(**ppo),
            critic=ModelConfig(**d["critic"]) if d.get("critic") else None,
            fork=ForkConfig(**d["fork"]) if d.get("fork") else ForkConfig(),
            **{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()
               if k not in ("preset", "model", "combat", "reward", "ppo", "critic", "fork")})


def make_config(preset: str = "main", **overrides: Any) -> RunConfig:
    """Preset model shape plus per-size defaults from the training plan."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(PRESETS)}")
    model = PRESETS[preset]
    ppo = PPOConfig()
    if preset.startswith("large"):
        ppo = dataclasses.replace(ppo, lr=3e-5, microbatch=1)
    critic = CRITIC_SMALL
    if preset == "small":
        ppo = dataclasses.replace(ppo, lr=1e-4, microbatch=32, activation_checkpointing=False, lr_warmup_steps=150)
        critic = CRITIC_LITE
    if preset == "tiny":
        ppo = dataclasses.replace(ppo, num_envs=2, min_transitions=32, batch_targets=16,
                                  microbatch=8, bf16=False, activation_checkpointing=False,
                                  kl_check_targets=16, kl_check_every=2)
        critic = CRITIC_TINY
    cfg = RunConfig(preset=preset, model=model, ppo=ppo, critic=critic)
    if "critic" in overrides and overrides["critic"] is None:
        cfg = dataclasses.replace(cfg, critic=None)
        overrides = {k: v for k, v in overrides.items() if k != "critic"}
    nested = {"model", "combat", "reward", "ppo", "critic", "fork"}
    top = {k: v for k, v in overrides.items() if k not in nested}
    cfg = dataclasses.replace(cfg, **top)
    for name in nested & overrides.keys():
        cfg = dataclasses.replace(cfg, **{name: dataclasses.replace(getattr(cfg, name), **overrides[name])})
    return cfg
