"""Two-level Pre-LN Transformer with shared, chunkable dynamic action scoring."""
from dataclasses import dataclass, asdict
import torch
from torch import nn

from .entity_encoder import SCHEMA, SCHEMA_HASH, KINDS, ZONES, NUMERIC_FIELDS
from .mechanic_registry import OPS, TARGETS, TIMINGS
from .network import masked_log_probs, policy_value_loss


@dataclass(frozen=True)
class TransformerConfig:
    tier: str = 'XS'
    layers: int = 4
    d_model: int = 128
    heads: int = 4
    dropout: float = 0.0

    def validate(self):
        if self.tier not in TIERS or asdict(self) != asdict(TIERS[self.tier]):
            raise ValueError('Unknown Transformer configuration; new settings need a new version')
        return self


TIERS = {name: TransformerConfig(name, layers, width, heads) for name, layers, width, heads in
         [('XS', 4, 128, 4), ('S', 6, 256, 8), ('M', 8, 384, 8), ('L', 12, 512, 8), ('XL', 16, 768, 12)]}
ARCHITECTURE_VERSION = 'mechanic-entity-transformer-v1'


def batch_entities(observations, device='cpu'):
    if not observations:
        raise ValueError('Empty entity batch')
    for obs in observations:
        obs.validate()
    b, n, a = len(observations), max(len(o.entities) for o in observations), max(len(o.actions) for o in observations)
    k = max(1, max(len(e.effects) for o in observations for e in o.entities))
    def zeros(*shape, dtype=torch.long):
        return torch.zeros(shape, dtype=dtype, device=device)
    batch = {'numbers': zeros(b, n, len(NUMERIC_FIELDS), dtype=torch.float32),
             'kind': zeros(b, n), 'zone': zeros(b, n), 'owner': zeros(b, n),
             'entity_mask': zeros(b, n, dtype=torch.bool), 'state_index': zeros(b),
             'op': zeros(b, n, k), 'target': zeros(b, n, k), 'timing': zeros(b, n, k),
             'op_numbers': zeros(b, n, k, 2, dtype=torch.float32), 'op_mask': zeros(b, n, k, dtype=torch.bool),
             'action_type': zeros(b, a), 'source': zeros(b, a), 'target_ref': zeros(b, a),
             'legal_mask': zeros(b, a, dtype=torch.bool), 'schema_hash': SCHEMA_HASH,
             'action_keys': tuple(tuple(a.action_key for a in o.actions) for o in observations)}
    for bi, obs in enumerate(observations):
        refs = {e.ref: i + 1 for i, e in enumerate(obs.entities)}  # zero means no reference
        for i, e in enumerate(obs.entities):
            batch['numbers'][bi, i] = torch.tensor(e.numbers, device=device)
            batch['kind'][bi, i], batch['zone'][bi, i] = KINDS.index(e.kind), ZONES.index(e.zone)
            batch['owner'][bi, i] = refs.get(e.owner, 0)
            batch['entity_mask'][bi, i] = True
            if e.kind == 'state':
                batch['state_index'][bi] = i
            for j, op in enumerate(e.effects):
                batch['op'][bi, i, j] = OPS.index(op.kind)
                batch['target'][bi, i, j] = TARGETS.index(op.target)
                batch['timing'][bi, i, j] = TIMINGS.index(op.timing)
                batch['op_numbers'][bi, i, j] = torch.tensor([op.amount / 100, op.hits / 100], device=device)
                batch['op_mask'][bi, i, j] = True
        for i, action in enumerate(obs.actions):
            batch['action_type'][bi, i] = ('end_turn', 'play').index(action.action_type)
            batch['source'][bi, i] = refs.get(action.source_ref, 0)
            batch['target_ref'][bi, i] = refs[action.target_refs[0]] if action.target_refs else 0
            batch['legal_mask'][bi, i] = action.legal
    return batch


def gather_refs(states, indices):
    padded = torch.cat([states.new_zeros(states.shape[0], 1, states.shape[-1]), states], dim=1)
    return padded.gather(1, indices.unsqueeze(-1).expand(-1, -1, states.shape[-1]))


class TransformerPolicyValueNetwork(nn.Module):
    def __init__(self, config=TIERS['XS']):
        super().__init__()
        self.config = config.validate()
        d = config.d_model
        self.op = nn.Embedding(len(OPS), 32)
        self.op_target = nn.Embedding(len(TARGETS), 32)
        self.timing = nn.Embedding(len(TIMINGS), 32)
        self.effect_position = nn.Embedding(SCHEMA['max_effects'], 32)
        # Position interacts nonlinearly with semantics BEFORE pooling, preserving order.
        self.mechanic = nn.Sequential(nn.Linear(130, 128), nn.GELU(), nn.Linear(128, d))
        self.numeric = nn.Linear(len(NUMERIC_FIELDS), d)
        self.kind = nn.Embedding(len(KINDS), d)
        self.zone = nn.Embedding(len(ZONES), d)
        self.owner_projection = nn.Linear(d, d, bias=False)
        self.layers = nn.ModuleList([nn.TransformerEncoderLayer(d, config.heads, 4*d, dropout=0,
            activation='gelu', batch_first=True, norm_first=True) for _ in range(config.layers)])
        self.final_norm = nn.LayerNorm(d)
        self.action_type = nn.Embedding(2, d)
        self.query = nn.Linear(3*d, d)
        self.cross_attention = nn.MultiheadAttention(d, config.heads, dropout=0, batch_first=True)
        self.score = nn.Sequential(nn.Linear(3*d, d), nn.GELU(), nn.Linear(d, 1))
        self.value = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1), nn.Tanh())

    def forward(self, batch, action_chunk_size=None):
        if batch.get('schema_hash') != SCHEMA_HASH:
            raise ValueError('Transformer input schema mismatch')
        if action_chunk_size is not None and (type(action_chunk_size) is not int or action_chunk_size < 1):
            raise ValueError('Action chunk size must be positive')
        op = batch['op']
        positions = self.effect_position(torch.arange(op.shape[-1], device=op.device)).expand(*op.shape, -1)
        local = self.mechanic(torch.cat([self.op(op), self.op_target(batch['target']),
            self.timing(batch['timing']), positions, batch['op_numbers']], dim=-1))
        local = (local * batch['op_mask'].unsqueeze(-1)).sum(-2)
        x = local + self.numeric(batch['numbers']) + self.kind(batch['kind']) + self.zone(batch['zone'])
        x = x + self.owner_projection(gather_refs(x, batch['owner']))
        for layer in self.layers:
            x = layer(x, src_key_padding_mask=~batch['entity_mask'])
        x = self.final_norm(x)
        state = x[torch.arange(len(x), device=x.device), batch['state_index']]
        count = batch['action_type'].shape[1]
        chunk = action_chunk_size or count
        logits = []
        for start in range(0, count, chunk):
            end = start + chunk
            query = self.query(torch.cat([self.action_type(batch['action_type'][:, start:end]),
                gather_refs(x, batch['source'][:, start:end]), gather_refs(x, batch['target_ref'][:, start:end])], -1))
            context, _ = self.cross_attention(query, x, x, key_padding_mask=~batch['entity_mask'], need_weights=False)
            logits.append(self.score(torch.cat([query, context, state[:, None].expand(-1, query.shape[1], -1)], -1)).squeeze(-1))
        return torch.cat(logits, -1), self.value(state).squeeze(-1)

    @torch.no_grad()
    def predict(self, observation, action_chunk_size=None):
        batch = batch_entities([observation], next(self.parameters()).device)
        was_training = self.training
        try:
            self.eval()
            logits, values = self(batch, action_chunk_size)
        finally:
            self.train(was_training)
        probs = masked_log_probs(logits, batch['legal_mask']).exp()[0]
        if not torch.isfinite(values).all():
            raise ValueError('Nonfinite value prediction')
        return dict(zip(batch['action_keys'][0], probs.cpu().tolist())), float(values[0])


def keyed_targets(batch, targets, device=None):
    if len(targets) != len(batch['action_keys']):
        raise ValueError('Policy target batch mismatch')
    result = torch.zeros_like(batch['legal_mask'], dtype=torch.float32, device=device or batch['legal_mask'].device)
    for i, (keys, target) in enumerate(zip(batch['action_keys'], targets)):
        if set(target) != set(keys):
            raise ValueError('Policy action keys mismatch')
        result[i, :len(keys)] = torch.tensor([target[k] for k in keys], device=result.device)
    return result


# The existing state-averaged CE + value MSE contract is deliberately reused.
transformer_loss = policy_value_loss
