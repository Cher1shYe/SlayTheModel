"""Policy/value network for in-combat and out-of-combat decisions. Input: ``obs.UObs``.

Starting point for the new network (written 2026-11-16 for the unified network with the
act-boss value head; kept through the 2026-11-18 cleanup, to be reworked for PPO with
dense rewards, docs/plan.md).

Two parts, one network:
* **run context** (deck, relics, map with its edges, boss, offers, GLOBAL, ...): entity
  embeddings -> one round of message passing along map edges -> Transformer encoder.
  Out of combat this is the whole observation. In combat it is constant for the fight, so
  its encoding can be computed once per combat and reused for every search leaf
  (``encode_context`` + ``forward(..., ctx=...)``).
* **combat** (player, hand, piles, monsters, ...; in combat only): a learned summary token
  plus the combat entities; Transformer decoder layers = self-attention among them +
  cross-attention to the run context. Out of combat only the summary token is present.
No positional encodings: both parts are sets. The GLOBAL row (patched with the current HP
and potions in a fight) and the combat PLAYER row go straight into the heads (lesson of
run small-b-d1: the policy ignored HP when it was only one entity among many).

Heads:
* policy: one score per legal candidate (action type + candidate numerics + the encoded
  entities it points at, with the state vector); softmax over candidates.
* value ``q`` (3 probabilities, never discounted):
    q[0] = P(beat this act's boss)                 (act 3 at A10: both bosses)
    q[1] = P(beat the next act | this act passed)
    q[2] = P(beat the act after | both passed)
* combat auxiliary (in combat only, helps the trunk): death logit, HP left / max HP,
  potions used.
* ``value`` (scalar, 2026-11-20): expected remaining dense reward for PPO (docs/plan.md 6.2).
  ``q`` stays as an auxiliary output.

``combine`` turns q into the decision value U with per-act rewards r and cross-act weights
w applied only at use time:
  act 1: U = q0 (r1 + w1 q1 (r2 + w2 r3 q2)); act 2: U = q0 (r2 + w2 r3 q1); act 3: U = r3 q0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import torch
import torch.nn as nn

from . import obs as uo


@dataclass
class UnifiedNetConfig:
    dim: int = 128
    ctx_layers: int = 3
    combat_layers: int = 2
    heads: int = 4
    ff_mult: int = 4
    dropout: float = 0.0
    observation_schema: str = "legacy"
    value_hidden: bool = False      # training-only value input; the policy never reads it


@dataclass
class ValueWeights:
    """Per-act rewards and cross-act weights (user 2026-11-16: r3 = 3, w1 = 0.2, w2 = 0.5)."""
    r: tuple = (1.0, 1.0, 3.0)
    w: tuple = (0.2, 0.5)


@dataclass
class UBatch:
    kind: torch.Tensor        # [B, M] run-context entities
    ids: torch.Tensor
    num: torch.Tensor         # [B, M, NUM]
    mask: torch.Tensor        # [B, M]
    edge_src: torch.Tensor    # [E] flat index into B*M
    edge_dst: torch.Tensor
    c_kind: torch.Tensor      # [B, K] combat entities (position 0 = summary token slot)
    c_ids: torch.Tensor
    c_num: torch.Tensor       # [B, K, NUM]
    c_mask: torch.Tensor      # [B, K] (position 0 always valid)
    global_row: torch.Tensor  # [B, MACRO_NUM]
    player_row: torch.Tensor  # [B, COMBAT_NUM]
    in_combat: torch.Tensor   # [B] float
    act: torch.Tensor         # [B] long
    ctype: torch.Tensor       # [B, C]
    ct1: torch.Tensor         # [B, C] index into cat(context, combat) = [0, M + K), -1 = none
    ct2: torch.Tensor
    cnum: torch.Tensor        # [B, C, CAND_NUM]
    cmask: torch.Tensor       # [B, C]
    hidden: torch.Tensor | None = None  # [B, HIDDEN_CARDS] value-only hidden input

    def to(self, device, non_blocking: bool = False) -> "UBatch":
        return UBatch(**{k: None if v is None else v.to(device, non_blocking=non_blocking)
                         for k, v in self.__dict__.items()})


_OFFS = {}


def _schema(name):
    if name == "legacy":
        return uo
    if name == "spire.public/1":
        from . import public_obs
        return public_obs
    raise ValueError(f"unknown observation schema: {name}")


def _offsets(name="legacy") -> np.ndarray:
    if name not in _OFFS:
        _OFFS[name] = np.concatenate([[0], np.cumsum(_schema(name).vocab_sizes())[:-1]]).astype(np.int64)
    return _OFFS[name]


def collate(obs: list[uo.UObs]) -> UBatch:
    names = {getattr(o, "schema_id", "legacy") for o in obs}
    if len(names) != 1:
        raise ValueError("cannot mix observation schemas in one policy batch")
    name = names.pop()
    uo = _schema(name)
    offs = _offsets(name)
    b = len(obs)
    m_max = max(1, max(o.n_ctx for o in obs))
    k_max = 1 + max(len(o.kind) - o.n_ctx for o in obs)
    c_max = max(1, max(len(o.cand_type) for o in obs))
    kind = np.zeros((b, m_max), np.int64); ids = np.zeros((b, m_max), np.int64)
    num = np.zeros((b, m_max, uo.NUM), np.float32); mask = np.zeros((b, m_max), bool)
    c_kind = np.zeros((b, k_max), np.int64); c_ids = np.zeros((b, k_max), np.int64)
    c_num = np.zeros((b, k_max, uo.NUM), np.float32); c_mask = np.zeros((b, k_max), bool)
    c_mask[:, 0] = True
    ctype = np.zeros((b, c_max), np.int64); ct1 = np.full((b, c_max), -1, np.int64); ct2 = np.full((b, c_max), -1, np.int64)
    cnum = np.zeros((b, c_max, uo.CAND_NUM), np.float32); cmask = np.zeros((b, c_max), bool)
    src, dst = [], []
    for i, o in enumerate(obs):
        m = o.n_ctx
        kind[i, :m] = o.kind[:m]; ids[i, :m] = o.id[:m] + offs[o.kind[:m]]; num[i, :m] = o.num[:m]; mask[i, :m] = True
        k = len(o.kind) - m
        if k:
            c_kind[i, 1:k + 1] = o.kind[m:]; c_ids[i, 1:k + 1] = o.id[m:] + offs[o.kind[m:]]
            c_num[i, 1:k + 1] = o.num[m:]; c_mask[i, 1:k + 1] = True
        remap = lambda t: np.where(t < 0, -1, np.where(t < m, t, m_max + 1 + (t - m)))
        q = len(o.cand_type)
        ctype[i, :q] = o.cand_type; ct1[i, :q] = remap(o.cand_t1); ct2[i, :q] = remap(o.cand_t2)
        cnum[i, :q] = o.cand_num; cmask[i, :q] = True
        if len(o.edges):
            src.append(o.edges[:, 0] + i * m_max); dst.append(o.edges[:, 1] + i * m_max)
    t = torch.from_numpy
    e_src = t(np.concatenate(src)) if src else torch.zeros(0, dtype=torch.long)
    e_dst = t(np.concatenate(dst)) if dst else torch.zeros(0, dtype=torch.long)
    return UBatch(t(kind), t(ids), t(num), t(mask), e_src, e_dst, t(c_kind), t(c_ids), t(c_num), t(c_mask),
                  t(np.stack([o.global_row for o in obs])), t(np.stack([o.player_row for o in obs])),
                  torch.tensor([float(o.in_combat) for o in obs]), torch.tensor([o.act for o in obs]),
                  t(ctype), t(ct1), t(ct2), t(cnum), t(cmask))


class UnifiedNet(nn.Module):
    def __init__(self, cfg: UnifiedNetConfig | None = None):
        super().__init__()
        self.cfg = cfg = cfg or UnifiedNetConfig()
        self.observation_schema = uo = _schema(cfg.observation_schema)
        d = cfg.dim
        self.kind_emb = nn.Embedding(uo.KINDS, d)
        self.id_emb = nn.Embedding(int(sum(uo.vocab_sizes())), d)
        self.macro_proj = nn.Linear(uo.MACRO_NUM, d)
        self.combat_proj = nn.Linear(uo.COMBAT_NUM, d)
        self.in_norm = nn.LayerNorm(d)
        self.down = nn.Linear(d, d)       # parent -> child (map edges)
        self.up = nn.Linear(d, d)         # child -> parent
        enc = nn.TransformerEncoderLayer(d, cfg.heads, d * cfg.ff_mult, cfg.dropout, activation="gelu",
                                         batch_first=True, norm_first=True)
        self.ctx_encoder = nn.TransformerEncoder(enc, cfg.ctx_layers, enable_nested_tensor=False)
        self.ctx_norm = nn.LayerNorm(d)
        self.summary = nn.Parameter(torch.randn(1, 1, d) * 0.02)
        dec = nn.TransformerDecoderLayer(d, cfg.heads, d * cfg.ff_mult, cfg.dropout, activation="gelu",
                                         batch_first=True, norm_first=True)
        self.combat_decoder = nn.TransformerDecoder(dec, cfg.combat_layers)
        self.combat_norm = nn.LayerNorm(d)
        self.pool_q = nn.Parameter(torch.randn(1, 1, d) * 0.02)
        self.pool = nn.MultiheadAttention(d, cfg.heads, batch_first=True)
        self.global_proj = nn.Sequential(nn.Linear(uo.MACRO_NUM, d), nn.GELU(), nn.Linear(d, d))
        self.player_proj = nn.Sequential(nn.Linear(uo.COMBAT_NUM + 1, d), nn.GELU(), nn.Linear(d, d))
        self.state_mlp = nn.Sequential(nn.Linear(3 * d, d), nn.GELU(), nn.Linear(d, d))
        self.q_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 3))
        self.aux_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 3))
        self.value_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        if cfg.value_hidden:
            from .rollout import HIDDEN_CARDS, HIDDEN_VOCAB
            self.hidden_cards = HIDDEN_CARDS
            self.hidden_emb = nn.Embedding(HIDDEN_VOCAB, 64, padding_idx=0)
            self.hidden_value = nn.Sequential(nn.Linear(d + 64 * HIDDEN_CARDS, d), nn.GELU(), nn.Linear(d, 1))
        self.type_emb = nn.Embedding(uo.CAND_TYPES, d)
        self.cnum_proj = nn.Linear(uo.CAND_NUM, d)
        self.ref = nn.Parameter(torch.zeros(2, d))
        self.cand_mlp = nn.Sequential(nn.Linear(3 * d, d), nn.GELU(), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    @staticmethod
    def _fp32(module, x):
        """Run a small input or output layer in FP32 inside BF16 autocast. BF16 keeps 8 significant
        bits: at a value of -0.15 it rounds to steps of 0.001, close to the reward of one HP
        (0.00125), and at a logit of 8 to steps of 0.06. Only the Transformer body stays BF16."""
        with torch.autocast(x.device.type, enabled=False):
            return module(x.float())

    def _embed(self, kind, ids, num):
        uo = self.observation_schema
        combat_kind = (kind >= uo.MACRO_KINDS)[..., None]
        numx = torch.where(combat_kind, self._fp32(self.combat_proj, num),
                           self._fp32(self.macro_proj, num[..., :uo.MACRO_NUM]))
        return self.in_norm(self.kind_emb(kind) + self.id_emb(ids) + numx)

    def encode_context(self, b: UBatch) -> tuple[torch.Tensor, torch.Tensor]:
        """Run-context encoding [B, M, d] and its mask; constant within a combat."""
        x = self._embed(b.kind, b.ids, b.num)
        if b.edge_src.numel():
            bsz, n, d = x.shape
            flat = x.reshape(bsz * n, d)
            ones = torch.ones(b.edge_src.shape[0], dtype=flat.dtype, device=flat.device)
            deg_dst = torch.zeros(bsz * n, dtype=flat.dtype, device=flat.device).index_add_(0, b.edge_dst, ones).clamp(min=1)[:, None]
            deg_src = torch.zeros(bsz * n, dtype=flat.dtype, device=flat.device).index_add_(0, b.edge_src, ones).clamp(min=1)[:, None]
            # Autocast can make the linear outputs BF16 while embeddings stay FP32.
            # index_add_ requires matching dtypes; accumulate in the embedding dtype.
            parent_messages = self.down(flat)[b.edge_src].to(dtype=flat.dtype)
            child_messages = self.up(flat)[b.edge_dst].to(dtype=flat.dtype)
            from_parents = torch.zeros_like(flat).index_add_(0, b.edge_dst, parent_messages) / deg_dst
            from_children = torch.zeros_like(flat).index_add_(0, b.edge_src, child_messages) / deg_src
            x = (flat + from_parents + from_children).reshape(bsz, n, d)
        x = self.ctx_encoder(x, src_key_padding_mask=~b.mask)
        return self.ctx_norm(x).masked_fill(~b.mask[..., None], 0.0), b.mask

    def forward(self, b: UBatch, ctx: tuple[torch.Tensor, torch.Tensor] | None = None) -> dict:
        """``ctx``: a cached ``encode_context`` result for these rows (same run context)."""
        if ctx is not None and self.cfg.observation_schema != "legacy":
            raise ValueError("public context includes live visible relic/selection state; recompute it for each decision")
        cx, cmask_ctx = self.encode_context(b) if ctx is None else ctx
        y = self._embed(b.c_kind, b.c_ids, b.c_num)
        y = torch.cat([self.summary.expand(y.shape[0], -1, -1), y[:, 1:]], 1)
        y = self.combat_decoder(y, cx, tgt_key_padding_mask=~b.c_mask, memory_key_padding_mask=~cmask_ctx)
        y = self.combat_norm(y).masked_fill(~b.c_mask[..., None], 0.0)
        x = torch.cat([cx, y], 1)
        xmask = torch.cat([cmask_ctx, b.c_mask], 1)
        pooled, _ = self.pool(self.pool_q.expand(x.shape[0], -1, -1), x, x, key_padding_mask=~xmask)
        player = torch.cat([b.player_row, b.in_combat[:, None]], -1)
        s = self._fp32(self.state_mlp, torch.cat([pooled[:, 0].float(), self._fp32(self.global_proj, b.global_row),
                                                  self._fp32(self.player_proj, player)], -1))

        def gather(t):
            g = torch.gather(x, 1, t.clamp(min=0)[..., None].expand(-1, -1, x.shape[-1]))
            return g * (t >= 0)[..., None]
        cand = (self.type_emb(b.ctype) + self._fp32(self.cnum_proj, b.cnum) + gather(b.ct1).float() + gather(b.ct2).float()
                + (b.ct1 >= 0)[..., None] * self.ref[0] + (b.ct2 >= 0)[..., None] * self.ref[1])
        sc = s[:, None].expand_as(cand)
        scores = self._fp32(self.cand_mlp, torch.cat((cand, sc, cand * sc), -1))[..., 0]
        logp = torch.log_softmax(scores.masked_fill(~b.cmask, float("-inf")), -1)
        value = self._fp32(self.value_head, s)[..., 0]
        if self.cfg.value_hidden:       # added after the policy's inputs: cannot reach the policy
            h = b.hidden if b.hidden is not None else torch.zeros(s.shape[0], self.hidden_cards, dtype=torch.long, device=s.device)
            e = self.hidden_emb(h).flatten(1).to(dtype=s.dtype)
            value = value + self._fp32(self.hidden_value, torch.cat([s, e], -1))[..., 0]
        return {"logp": logp, "value": value, "q_logit": self._fp32(self.q_head, s), "aux": self._fp32(self.aux_head, s)}


def combine(q: torch.Tensor, act: torch.Tensor, vw: ValueWeights = ValueWeights()) -> torch.Tensor:
    """Decision value U from q = [B, 3] probabilities and the act index (0, 1, 2)."""
    r1, r2, r3 = vw.r
    w1, w2 = vw.w
    q0, q1, q2 = q[:, 0], q[:, 1], q[:, 2]
    u1 = q0 * (r1 + w1 * q1 * (r2 + w2 * r3 * q2))
    u2 = q0 * (r2 + w2 * r3 * q1)
    u3 = r3 * q0
    return torch.where(act == 0, u1, torch.where(act == 1, u2, u3))


def count_params(net: nn.Module) -> int:
    return sum(p.numel() for p in net.parameters())


def save(path, net: UnifiedNet, extra: dict | None = None) -> None:
    from .sim import sim
    schema = _schema(net.cfg.observation_schema)
    torch.save({"format": "spire_rl.unified/1", "config": asdict(net.cfg), "state": net.state_dict(),
                "macro_obs_version": int(sim.MACRO_OBS_VERSION), "combat_obs_version": int(sim.COMBAT_OBS_VERSION),
                "public_catalog_sha256": getattr(schema, "CATALOG_SHA256", None),
                "public_feature_version": getattr(schema, "FEATURE_VERSION", None),
                "ruleset": sim.ENGINE_RULESET_ID, "extra": extra or {}}, path)


def load(path, device="cpu") -> UnifiedNet:
    from .sim import sim
    p = torch.load(path, map_location="cpu", weights_only=False)
    schema_name = p.get("config", {}).get("observation_schema", "legacy")
    schema = _schema(schema_name)
    if (p.get("format") != "spire_rl.unified/1" or (schema_name == "legacy" and
            (p.get("macro_obs_version") != int(sim.MACRO_OBS_VERSION)
             or p.get("combat_obs_version") != int(sim.COMBAT_OBS_VERSION))) or
            (schema_name != "legacy" and (p.get("public_catalog_sha256") != schema.CATALOG_SHA256
                                          or p.get("public_feature_version") != schema.FEATURE_VERSION))):
        raise ValueError(f"{path}: not a unified net for the current observation versions")
    net = UnifiedNet(UnifiedNetConfig(**p["config"]))
    net.load_state_dict(p["state"])
    return net.to(device).eval()
