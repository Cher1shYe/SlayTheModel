"""SpireNet: entity Set Transformer + causal history Transformer + pointer scorer.

Shapes (B targets, U unique states, N entities, C candidates, W window steps):

    states   -> entity embeddings E[U, N, Ds] and summaries z[U, Ds]
    windows  -> tokens (g, z, a, r) per step, causal, read at the target's z token
    scoring  -> one logit per legal candidate of each target, masked softmax

One forward serves actor, critic and auxiliary heads (no second temporal pass).
Only public observation arrays enter the model; returns-to-go never do.

Inputs carry no training condition: no reward-stage id and no alpha-weighted
reward. History reward tokens hold what happened (floors, act entries, win),
so the actor sees the same input in training, validation and deployment. The
critic predicts the three return components separately; the scalar value for
any alpha is a fixed linear combination (``combine_value``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.utils.checkpoint import checkpoint

from .config import ModelConfig

TOKENS_PER_STEP = 4  # goal, state, action, reward
REWARD_FEATURES = 3  # events of the step: floors completed, acts entered, win
# Critic outputs are these components of the future return divided by the scale.
VALUE_COMPONENTS = ("floors", "acts", "win")
VALUE_SCALE = (50.0, 2.0, 1.0)
# SELECT_GRID_CARD on an already selected card (= deselect) gets its own group.
CAND_DESELECT_FEATURE = 4   # index in cand_num (macro observation v2)


@dataclass
class EnvSpec:
    """Sizes taken from the simulator (sim.identity())."""
    entity_num: int
    cand_num: int
    phases: int
    vocab: list[int]
    action_types: int

    @property
    def kinds(self) -> int:
        return len(self.vocab)

    @property
    def groups(self) -> int:
        """Action groups of the factorized policy: one per action type + deselect."""
        return self.action_types + 1


@dataclass
class MacroBatch:
    # unique states
    ent_kind: Tensor     # [U, N] long
    ent_id: Tensor       # [U, N] long, already offset into the joint vocabulary
    ent_num: Tensor      # [U, N, F]
    ent_mask: Tensor     # [U, N] bool, True = real entity
    edge_src: Tensor     # [E] long, flat index into U*N (parent)
    edge_dst: Tensor     # [E] long (child)
    # candidates of each target decision
    tgt_state: Tensor    # [B] long
    cand_type: Tensor    # [B, C] long
    cand_t1: Tensor      # [B, C] long, entity index in the state or -1
    cand_t2: Tensor      # [B, C] long
    cand_num: Tensor     # [B, C, K]
    cand_mask: Tensor    # [B, C] bool
    cand_group: Tensor   # [B, C] long, action group (type, or the extra deselect group)
    # history windows (left aligned; the target is the last valid step)
    win_state: Tensor    # [B, W] long, -1 = padding
    win_act_type: Tensor  # [B, W] long, chosen candidate of each past step
    win_act_t1: Tensor
    win_act_t2: Tensor
    win_act_num: Tensor  # [B, W, K]
    win_reward: Tensor   # [B, W, REWARD_FEATURES]
    win_phase: Tensor    # [B, W] long
    win_abs: Tensor      # [B, W] long, absolute decision index (clamped)
    win_len: Tensor      # [B] long, valid steps (>= 1)

    def to(self, device) -> "MacroBatch":
        return MacroBatch(**{k: v.to(device, non_blocking=True) for k, v in self.__dict__.items()})


@dataclass
class ModelOutput:
    logits: Tensor   # [B, C] log-probabilities, -inf on padding/illegal
    value: Tensor    # [B, 3] future (floors, act entries, win) / VALUE_SCALE
    aux: Tensor      # [B, 3] logits: survive, hp ratio (pre-sigmoid), act completion
    group_logp: Tensor | None = None   # [B, G] log P(group), -inf when absent (factorized only)


def value_weights(alpha: float, reward) -> tuple[float, float, float]:
    """Weights turning raw-unit components into r_train units for this alpha."""
    return (alpha * reward.floor / reward.scale, alpha * reward.act_entry / reward.scale,
            reward.win / reward.scale)


def combine_value(components, alpha: float, reward):
    """Scalar V in r_train units from [..., 3] normalized critic outputs."""
    w = value_weights(alpha, reward)
    return sum(components[..., k] * VALUE_SCALE[k] * w[k] for k in range(3))


class Attention(nn.Module):
    """Multi-head attention with one projection per role (no duplicate Q/K/V)."""

    def __init__(self, dim: int, heads: int, kv_dim: int | None = None, dropout: float = 0.0):
        super().__init__()
        if dim % heads:
            raise ValueError("dim must be divisible by heads")
        self.heads = heads
        self.q = nn.Linear(dim, dim)
        self.kv = nn.Linear(kv_dim or dim, 2 * dim)
        self.out = nn.Linear(dim, dim)
        self.dropout = dropout

    def forward(self, x: Tensor, ctx: Tensor, mask: Tensor | None) -> Tensor:
        b, q_len, d = x.shape
        k_len = ctx.shape[1]
        h = self.heads
        q = self.q(x).view(b, q_len, h, d // h).transpose(1, 2)
        k, v = self.kv(ctx).view(b, k_len, 2, h, d // h).permute(2, 0, 3, 1, 4)
        y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask,
                                           dropout_p=self.dropout if self.training else 0.0)
        return self.out(y.transpose(1, 2).reshape(b, q_len, d))


class FeedForward(nn.Module):
    def __init__(self, dim: int, mult: int, dropout: float):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(dim, dim * mult), nn.GELU(), nn.Dropout(dropout),
                                 nn.Linear(dim * mult, dim))

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class CrossBlock(nn.Module):
    """Pre-LN block: queries attend to a context set, then a feed-forward."""

    def __init__(self, dim: int, heads: int, mult: int, dropout: float):
        super().__init__()
        self.norm_q = nn.LayerNorm(dim)
        self.norm_kv = nn.LayerNorm(dim)
        self.attn = Attention(dim, heads, dropout=dropout)
        self.norm_ff = nn.LayerNorm(dim)
        self.ff = FeedForward(dim, mult, dropout)

    def forward(self, x: Tensor, ctx: Tensor, key_valid: Tensor | None) -> Tensor:
        mask = None
        if key_valid is not None:
            # Rows whose context is empty would produce NaN: let them see slot 0
            # and drop the update below.
            safe = key_valid.clone()
            empty = ~safe.any(dim=1)
            safe[empty, 0] = True
            mask = safe[:, None, None, :]
        update = self.attn(self.norm_q(x), self.norm_kv(ctx), mask)
        if key_valid is not None:
            update = update.masked_fill((~key_valid.any(dim=1))[:, None, None], 0.0)
        x = x + update
        return x + self.ff(self.norm_ff(x))


class ISAB(nn.Module):
    """Induced set attention block (permutation equivariant, O(N * inducing))."""

    def __init__(self, dim: int, heads: int, inducing: int, mult: int, dropout: float):
        super().__init__()
        self.inducing = nn.Parameter(torch.randn(1, inducing, dim) * 0.02)
        self.gather = CrossBlock(dim, heads, mult, dropout)
        self.scatter = CrossBlock(dim, heads, mult, dropout)

    def forward(self, x: Tensor, valid: Tensor) -> Tensor:
        h = self.gather(self.inducing.expand(x.shape[0], -1, -1), x, valid)
        x = self.scatter(x, h, None)
        return x.masked_fill(~valid[..., None], 0.0)


class SelfBlock(nn.Module):
    """Pre-LN causal self-attention block for the history Transformer."""

    def __init__(self, dim: int, heads: int, mult: int, dropout: float):
        super().__init__()
        self.norm_attn = nn.LayerNorm(dim)
        self.qkv = nn.Linear(dim, 3 * dim)
        self.out = nn.Linear(dim, dim)
        self.norm_ff = nn.LayerNorm(dim)
        self.ff = FeedForward(dim, mult, dropout)
        self.heads = heads
        self.dropout = dropout

    def forward(self, x: Tensor, mask: Tensor) -> Tensor:
        b, t, d = x.shape
        h = self.heads
        q, k, v = self.qkv(self.norm_attn(x)).view(b, t, 3, h, d // h).permute(2, 0, 3, 1, 4)
        y = F.scaled_dot_product_attention(q, k, v, attn_mask=mask,
                                           dropout_p=self.dropout if self.training else 0.0)
        x = x + self.out(y.transpose(1, 2).reshape(b, t, d))
        return x + self.ff(self.norm_ff(x))


class SpireNet(nn.Module):
    def __init__(self, cfg: ModelConfig, spec: EnvSpec):
        super().__init__()
        self.cfg, self.spec = cfg, spec
        ds, dh, da = cfg.set_dim, cfg.hist_dim, cfg.action_dim
        offsets = [0]
        for size in spec.vocab:
            offsets.append(offsets[-1] + size)
        self.register_buffer("vocab_offsets", torch.tensor(offsets[:-1], dtype=torch.long), persistent=False)
        # --- entity encoder
        self.kind_emb = nn.Embedding(spec.kinds, ds)
        self.id_emb = nn.Embedding(offsets[-1], ds)
        self.num_proj = nn.Linear(spec.entity_num, ds)
        self.entity_norm = nn.LayerNorm(ds)
        self.msg_down = nn.ModuleList(nn.Linear(ds, ds) for _ in range(cfg.map_message_rounds))
        self.msg_up = nn.ModuleList(nn.Linear(ds, ds) for _ in range(cfg.map_message_rounds))
        self.msg_norm = nn.ModuleList(nn.LayerNorm(ds) for _ in range(cfg.map_message_rounds))
        self.isabs = nn.ModuleList(ISAB(ds, cfg.set_heads, cfg.inducing_points, cfg.ff_mult, cfg.dropout)
                                   for _ in range(cfg.set_layers))
        self.pool_seed = nn.Parameter(torch.randn(1, 1, ds) * 0.02)
        self.pool = CrossBlock(ds, cfg.set_heads, cfg.ff_mult, cfg.dropout)
        self.set_out_norm = nn.LayerNorm(ds)
        # --- candidate encoder (shared by targets and past chosen actions)
        self.cand_type_emb = nn.Embedding(spec.action_types, ds)
        self.cand_num_proj = nn.Linear(spec.cand_num, ds)
        self.cand_ref = nn.Parameter(torch.zeros(2, ds))   # marks "has target 1/2"
        self.cand_attn = CrossBlock(ds, cfg.action_heads, cfg.ff_mult, cfg.dropout)
        self.cand_norm = nn.LayerNorm(ds)
        # --- history Transformer
        self.task_emb = nn.Embedding(1, dh)                 # WIN_RUN
        self.phase_emb = nn.Embedding(spec.phases, dh)
        self.state_in = nn.Linear(ds, dh)
        self.action_in = nn.Linear(ds, dh)
        self.reward_in = nn.Linear(REWARD_FEATURES, dh)
        self.token_type = nn.Embedding(TOKENS_PER_STEP, dh)
        self.position = nn.Embedding(cfg.window, dh)
        self.abs_step = nn.Embedding(cfg.max_step_index, dh)
        self.blocks = nn.ModuleList(SelfBlock(dh, cfg.hist_heads, cfg.ff_mult, cfg.dropout)
                                    for _ in range(cfg.hist_layers))
        self.hist_norm = nn.LayerNorm(dh)
        # --- heads
        self.policy_query = nn.Linear(dh, da)
        self.cand_proj = nn.Linear(ds, da)
        self.policy_mlp = nn.Sequential(nn.Linear(3 * da, da), nn.GELU(), nn.Linear(da, 1))
        if cfg.type_factorized:
            self.group_emb = nn.Embedding(spec.groups, da)
            self.group_mlp = nn.Sequential(nn.Linear(3 * da, da), nn.GELU(), nn.Linear(da, 1))
        self.value_head = nn.Linear(dh, len(VALUE_COMPONENTS))
        self.aux_head = nn.Linear(dh, 3)
        self.checkpointing = False
        self._init_weights()

    def _init_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, std=0.02)
        # Residual output projections scaled by depth (GPT-2 style).
        scale = 0.02 / math.sqrt(2 * max(1, self.cfg.hist_layers))
        for block in self.blocks:
            nn.init.normal_(block.out.weight, std=scale)
            nn.init.normal_(block.ff.net[-1].weight, std=scale)
        # Near-uniform initial policy over legal candidates.
        nn.init.normal_(self.policy_mlp[-1].weight, std=1e-4)
        nn.init.normal_(self.policy_query.weight, std=1e-3)
        if self.cfg.type_factorized:   # near-uniform over the groups present
            nn.init.normal_(self.group_mlp[-1].weight, std=1e-4)

    def set_checkpointing(self, enabled: bool) -> None:
        self.checkpointing = bool(enabled)

    def _maybe_ckpt(self, fn, *args):
        if self.checkpointing and self.training and torch.is_grad_enabled():
            return checkpoint(fn, *args, use_reentrant=False)
        return fn(*args)

    # -- states ------------------------------------------------------------
    def encode_states(self, b: MacroBatch) -> tuple[Tensor, Tensor]:
        u, n = b.ent_kind.shape
        ids = b.ent_id + self.vocab_offsets[b.ent_kind]
        x = self.kind_emb(b.ent_kind) + self.id_emb(ids) + self.num_proj(b.ent_num)
        x = self.entity_norm(x).masked_fill(~b.ent_mask[..., None], 0.0)
        if b.edge_src.numel():
            flat = x.reshape(u * n, -1)
            ones = torch.ones_like(b.edge_src, dtype=flat.dtype)
            deg_dst = torch.zeros(u * n, device=x.device, dtype=flat.dtype).index_add_(0, b.edge_dst, ones)
            deg_src = torch.zeros(u * n, device=x.device, dtype=flat.dtype).index_add_(0, b.edge_src, ones)
            for down, up, norm in zip(self.msg_down, self.msg_up, self.msg_norm):
                # Under autocast the Linear output is BF16 while `flat` (after LayerNorm) is FP32;
                # accumulate in flat's dtype.
                from_parents = torch.zeros_like(flat).index_add_(0, b.edge_dst, down(flat)[b.edge_src].to(flat.dtype))
                from_children = torch.zeros_like(flat).index_add_(0, b.edge_src, up(flat)[b.edge_dst].to(flat.dtype))
                msg = from_parents / deg_dst.clamp(min=1)[:, None] + from_children / deg_src.clamp(min=1)[:, None]
                flat = flat + F.gelu(norm(msg))
            x = flat.reshape(u, n, -1).masked_fill(~b.ent_mask[..., None], 0.0)
        for isab in self.isabs:
            x = self._maybe_ckpt(isab, x, b.ent_mask)
        x = self.set_out_norm(x).masked_fill(~b.ent_mask[..., None], 0.0)
        z = self.pool(self.pool_seed.expand(u, -1, -1), x, b.ent_mask)[:, 0]
        return x, z

    def encode_candidates(self, entities: Tensor, valid: Tensor, state: Tensor, ctype: Tensor,
                          t1: Tensor, t2: Tensor, cnum: Tensor) -> Tensor:
        """Candidates [B, C] of states ``state`` -> [B, C, Ds]."""
        ent = entities[state]                     # [B, N, Ds]
        ent_valid = valid[state]
        def gather(t: Tensor) -> Tensor:
            idx = t.clamp(min=0)
            g = torch.gather(ent, 1, idx[..., None].expand(-1, -1, ent.shape[-1]))
            return g * (t >= 0)[..., None]
        q = (self.cand_type_emb(ctype) + self.cand_num_proj(cnum) + gather(t1) + gather(t2)
             + (t1 >= 0)[..., None] * self.cand_ref[0] + (t2 >= 0)[..., None] * self.cand_ref[1])
        return self.cand_norm(self.cand_attn(q, ent, ent_valid))

    # -- full forward ----------------------------------------------------------
    def forward(self, b: MacroBatch) -> ModelOutput:
        entities, z = self.encode_states(b)
        bsz, w = b.win_state.shape
        dh = self.cfg.hist_dim
        step_valid = b.win_state >= 0
        safe_state = b.win_state.clamp(min=0)
        # Chosen action of every past step, encoded against that step's entities.
        flat_state = safe_state.reshape(-1)
        acts = self.encode_candidates(entities, b.ent_mask, flat_state, b.win_act_type.reshape(-1, 1),
                                      b.win_act_t1.reshape(-1, 1), b.win_act_t2.reshape(-1, 1),
                                      b.win_act_num.reshape(-1, 1, b.win_act_num.shape[-1]))
        acts = acts.reshape(bsz, w, -1)
        pos = torch.arange(w, device=z.device)
        common = self.position(pos)[None] + self.abs_step(b.win_abs.clamp(max=self.cfg.max_step_index - 1))
        g = self.task_emb.weight[0] + self.phase_emb(b.win_phase)
        tokens = torch.stack((
            g,
            self.state_in(z[safe_state]),
            self.action_in(acts),
            self.reward_in(b.win_reward),
        ), dim=2) + (common[:, :, None] + self.token_type.weight[None, None])
        # Token validity: g/z for every real step; a/r only for steps before the target.
        last = (b.win_len - 1)[:, None]
        past = (pos[None] < last) & step_valid
        valid = torch.stack((step_valid, step_valid, past, past), dim=2).reshape(bsz, w * TOKENS_PER_STEP)
        tokens = tokens.reshape(bsz, w * TOKENS_PER_STEP, dh)
        t = tokens.shape[1]
        causal = torch.ones(t, t, dtype=torch.bool, device=z.device).tril()
        mask = causal[None] & valid[:, None, :]
        mask = mask | torch.eye(t, dtype=torch.bool, device=z.device)[None]   # padding rows see themselves
        mask = mask[:, None]
        x = tokens
        for block in self.blocks:
            x = self._maybe_ckpt(block, x, mask)
        x = self.hist_norm(x)
        target_token = (b.win_len - 1) * TOKENS_PER_STEP + 1          # the target's z token
        h = x[torch.arange(bsz, device=x.device), target_token]       # [B, Dh]
        # Pointer scoring of the target's legal candidates.
        cands = self.encode_candidates(entities, b.ent_mask, b.tgt_state, b.cand_type, b.cand_t1,
                                       b.cand_t2, b.cand_num)
        # The heads always run in FP32, also under BF16 autocast. BF16 keeps 8 significant
        # bits: a score of 8..16 is stored in steps of 1/16, so the same decision scored in
        # two different batches (rollout, then update) differed by whole steps in log P.
        with torch.autocast(h.device.type, enabled=False):
            h, cands = h.float(), cands.float()
            c = self.cand_proj(cands)                                 # [B, C, Da]
            qh = self.policy_query(h)
            q = qh[:, None].expand_as(c)
            scores = ((q * c).sum(-1) / math.sqrt(c.shape[-1])
                      + self.policy_mlp(torch.cat((q, c, q * c), -1))[..., 0])
            group_logp = None
            if self.cfg.type_factorized:
                logits, group_logp = self._factorized(qh, scores, b.cand_group, b.cand_mask)
            else:
                logits = torch.log_softmax(scores.masked_fill(~b.cand_mask, float("-inf")), -1)
            return ModelOutput(logits, self.value_head(h), self.aux_head(h), group_logp)

    def _factorized(self, qh: Tensor, scores: Tensor, group: Tensor, mask: Tensor) -> tuple[Tensor, Tensor]:
        """log P(c) = log P(group(c)) + log P(c | group(c)); exact, so PPO ratios stay valid.

        Masked entries use a large finite negative (not -inf) until the final
        mask, so no all-masked logsumexp can put NaN into the backward pass.
        Returned group_logp is ~-1e9 for groups absent from the request.
        """
        neg = -1e9
        bsz, n_groups = scores.shape[0], self.spec.groups
        g = group.clamp(0, n_groups - 1)
        member = F.one_hot(g, n_groups).bool() & mask[..., None]                              # [B, C, G]
        present = member.any(1)                                                               # [B, G]
        e = self.group_emb.weight[None].expand(bsz, -1, -1)                                   # [B, G, Da]
        qg = qh[:, None].expand_as(e)
        u = (qg * e).sum(-1) / math.sqrt(e.shape[-1]) + self.group_mlp(torch.cat((qg, e, qg * e), -1))[..., 0]
        group_logp = torch.log_softmax(u.float().masked_fill(~present, neg), -1)
        safe = scores.masked_fill(~mask, neg)
        lse = torch.logsumexp(safe[..., None].masked_fill(~member, neg), 1)                   # [B, G]
        logits = group_logp.gather(1, g) + safe - lse.gather(1, g)
        return logits.masked_fill(~mask, float("-inf")), group_logp


def count_parameters(model: nn.Module) -> int:
    seen, total = set(), 0
    for p in model.parameters():
        if id(p) not in seen:
            seen.add(id(p))
            total += p.numel()
    return total
