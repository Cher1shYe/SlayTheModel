"""Combat policy/value network over the entity combat observation (sim combat_obs v1).

Input: one ``BattleContext.entity_observation()`` dict per state (entities = player,
encounter, powers, hand / draw / discard / exhaust / choice cards, monsters, potions,
relics; candidates = the legal actions in ``legal_actions()`` order).

Architecture: entity embeddings (kind + id + numeric) -> Transformer encoder (full
self-attention over the entities; no history) -> attention pooling. The player's raw
numeric row (HP, energy, block, incoming damage, ...) also goes straight into both heads,
so these scalars cannot be lost in the pooling (lesson of run small-b-d1, where the
macro policy ignored HP). Each candidate = action-type embedding + its numeric features
+ the encoded entities it points at (card / potion / choice, target monster), scored by
an MLP together with the pooled state. Value = expected combat value
(0 = death, win_base + (1 - win_base) * (hp + 4 * potions) / max_hp on a win).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .sim import sim

ACTION_TYPES = 5          # PLAY_CARD, END_TURN, CHOOSE, CONFIRM, USE_POTION


@dataclass
class CombatNetConfig:
    dim: int = 128
    layers: int = 3
    heads: int = 4
    ff_mult: int = 4
    dropout: float = 0.0


def vocab_offsets() -> tuple[list[int], int]:
    sizes = sim.combat_id_vocab()
    offs, total = [], 0
    for s in sizes:
        offs.append(total)
        total += max(1, s)
    return offs, total


@dataclass
class CombatBatch:
    kind: torch.Tensor      # [B, N] long
    ids: torch.Tensor       # [B, N] long (vocabulary offsets applied)
    num: torch.Tensor       # [B, N, E] float
    mask: torch.Tensor      # [B, N] bool
    player: torch.Tensor    # [B, E] the PLAYER entity's numeric row
    ctype: torch.Tensor     # [B, C] long
    ct1: torch.Tensor       # [B, C] long, -1 = none
    ct2: torch.Tensor       # [B, C] long, -1 = none
    cnum: torch.Tensor      # [B, C, K] float
    cmask: torch.Tensor     # [B, C] bool

    def to(self, device) -> "CombatBatch":
        return CombatBatch(**{k: v.to(device) for k, v in self.__dict__.items()})


_OFFS = None


def collate_obs(obs: list[dict]) -> CombatBatch:
    """Pad a list of entity-observation dicts into one batch."""
    global _OFFS
    if _OFFS is None:
        _OFFS = np.asarray(vocab_offsets()[0], np.int64)
    b = len(obs)
    n = max(1, max(len(o["kind"]) for o in obs))
    c = max(1, max(len(o["cand_type"]) for o in obs))
    e = obs[0]["num"].shape[1]
    k = obs[0]["cand_num"].shape[1] if len(obs[0]["cand_num"].shape) == 2 else sim.COMBAT_CAND_NUM
    kind = np.zeros((b, n), np.int64); ids = np.zeros((b, n), np.int64)
    num = np.zeros((b, n, e), np.float32); mask = np.zeros((b, n), bool)
    ctype = np.zeros((b, c), np.int64); ct1 = np.full((b, c), -1, np.int64); ct2 = np.full((b, c), -1, np.int64)
    cnum = np.zeros((b, c, k), np.float32); cmask = np.zeros((b, c), bool)
    for i, o in enumerate(obs):
        m = len(o["kind"])
        kk = np.asarray(o["kind"], np.int64)
        kind[i, :m] = kk
        ids[i, :m] = np.asarray(o["id"], np.int64) + _OFFS[kk]
        num[i, :m] = o["num"]
        mask[i, :m] = True
        q = len(o["cand_type"])
        ctype[i, :q] = o["cand_type"]; ct1[i, :q] = o["cand_target"]; ct2[i, :q] = o["cand_target2"]
        cnum[i, :q] = o["cand_num"]; cmask[i, :q] = True
    t = torch.from_numpy
    return CombatBatch(t(kind), t(ids), t(num), t(mask), t(num[:, 0].copy()), t(ctype), t(ct1), t(ct2), t(cnum), t(cmask))


def collate_packed(d: dict) -> CombatBatch:
    """Batch from sim.net_search_advance()'s packed arrays."""
    ent_len, cand_len = np.asarray(d["ent_len"]), np.asarray(d["cand_len"])
    eo = np.concatenate([[0], np.cumsum(ent_len)]); co = np.concatenate([[0], np.cumsum(cand_len)])
    obs = [{"kind": d["kind"][eo[i]:eo[i + 1]], "id": d["id"][eo[i]:eo[i + 1]], "num": d["num"][eo[i]:eo[i + 1]],
            "cand_type": d["cand_type"][co[i]:co[i + 1]], "cand_target": d["cand_target"][co[i]:co[i + 1]],
            "cand_target2": d["cand_target2"][co[i]:co[i + 1]], "cand_num": d["cand_num"][co[i]:co[i + 1]]}
           for i in range(len(ent_len))]
    return collate_obs(obs)


class CombatNet(nn.Module):
    def __init__(self, cfg: CombatNetConfig | None = None):
        super().__init__()
        self.cfg = cfg = cfg or CombatNetConfig()
        d = cfg.dim
        e, k = sim.COMBAT_ENTITY_NUM, sim.COMBAT_CAND_NUM
        _, total = vocab_offsets()
        self.kind_emb = nn.Embedding(sim.COMBAT_ENTITY_KINDS, d)
        self.id_emb = nn.Embedding(total, d)
        self.num_proj = nn.Linear(e, d)
        self.in_norm = nn.LayerNorm(d)
        layer = nn.TransformerEncoderLayer(d, cfg.heads, d * cfg.ff_mult, cfg.dropout, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, cfg.layers, enable_nested_tensor=False)
        self.out_norm = nn.LayerNorm(d)
        self.pool_q = nn.Parameter(torch.randn(1, 1, d) * 0.02)
        self.pool = nn.MultiheadAttention(d, cfg.heads, batch_first=True)
        self.player_proj = nn.Sequential(nn.Linear(e, d), nn.GELU(), nn.Linear(d, d))
        self.state_mlp = nn.Sequential(nn.Linear(2 * d, d), nn.GELU(), nn.Linear(d, d))
        self.value_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.type_emb = nn.Embedding(ACTION_TYPES, d)
        self.cnum_proj = nn.Linear(k, d)
        self.ref = nn.Parameter(torch.zeros(2, d))
        self.cand_mlp = nn.Sequential(nn.Linear(3 * d, d), nn.GELU(), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    def forward(self, b: CombatBatch) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns (log-probabilities over candidates [B, C] with -inf on padding, value [B])."""
        x = self.kind_emb(b.kind) + self.id_emb(b.ids) + self.num_proj(b.num)
        x = self.in_norm(x)
        x = self.encoder(x, src_key_padding_mask=~b.mask)
        x = self.out_norm(x).masked_fill(~b.mask[..., None], 0.0)
        pooled, _ = self.pool(self.pool_q.expand(x.shape[0], -1, -1), x, x, key_padding_mask=~b.mask)
        s = self.state_mlp(torch.cat((pooled[:, 0], self.player_proj(b.player)), -1))     # [B, d]
        value = self.value_head(s)[:, 0]

        def gather(t):
            idx = t.clamp(min=0)
            g = torch.gather(x, 1, idx[..., None].expand(-1, -1, x.shape[-1]))
            return g * (t >= 0)[..., None]
        cand = (self.type_emb(b.ctype) + self.cnum_proj(b.cnum) + gather(b.ct1) + gather(b.ct2)
                + (b.ct1 >= 0)[..., None] * self.ref[0] + (b.ct2 >= 0)[..., None] * self.ref[1])
        sc = s[:, None].expand_as(cand)
        scores = self.cand_mlp(torch.cat((cand, sc, cand * sc), -1))[..., 0]
        logp = torch.log_softmax(scores.masked_fill(~b.cmask, float("-inf")), -1)
        return logp, value


def save(path, net: CombatNet, extra: dict | None = None) -> None:
    torch.save({"format": "spire_rl.combat/1", "config": asdict(net.cfg), "state": net.state_dict(),
                "combat_obs_version": sim.COMBAT_OBS_VERSION, "ruleset": sim.ENGINE_RULESET_ID,
                "extra": extra or {}}, path)


def load(path, device="cpu") -> CombatNet:
    p = torch.load(path, map_location="cpu", weights_only=False)
    if p.get("format") != "spire_rl.combat/1" or p.get("combat_obs_version") != sim.COMBAT_OBS_VERSION:
        raise ValueError(f"{path}: not a combat net for combat_obs v{sim.COMBAT_OBS_VERSION}")
    net = CombatNet(CombatNetConfig(**p["config"]))
    net.load_state_dict(p["state"])
    return net.to(device).eval()


def losses(net: CombatNet, b: CombatBatch, policy_target: torch.Tensor, value_target: torch.Tensor,
           value_coef: float = 1.0) -> tuple[torch.Tensor, dict]:
    """policy_target: [B, C] distribution over candidates (zeros on padding)."""
    logp, value = net(b)
    pl = -(policy_target * logp.masked_fill(~b.cmask, 0.0)).sum(-1).mean()
    vl = F.mse_loss(value, value_target)
    return pl + value_coef * vl, {"policy": float(pl), "value": float(vl)}
