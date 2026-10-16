"""Versioned Transformer factory; old MLP loaders remain unchanged."""
from dataclasses import asdict
import os
from pathlib import Path
import tempfile
import torch

from .config import atomic_replace, content_hash
from .entity_encoder import SCHEMA, SCHEMA_HASH
from .network import code_digest
from .transformer_network import TIERS, ARCHITECTURE_VERSION, TransformerPolicyValueNetwork


def create_transformer(tier='XS'):
    if tier not in TIERS:
        raise ValueError(f'Unknown model tier: {tier}')
    return TransformerPolicyValueNetwork(TIERS[tier])


def model_metadata(model):
    config = asdict(model.config)
    return {'format_version': 'transformer-checkpoint-v1', 'architecture': ARCHITECTURE_VERSION,
            'config': config, 'config_hash': content_hash(config), 'schema': SCHEMA,
            'schema_hash': SCHEMA_HASH, 'parameter_count': sum(p.numel() for p in model.parameters())}


def save_transformer_checkpoint(path, model):
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError('Nonfinite Transformer weights')
    payload = dict(model_metadata(model), model_state=model.state_dict(), code_digest=code_digest(),
                   torch_version=str(torch.__version__), resume_scope='weights_only_T1')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            torch.save(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_transformer_checkpoint(path, expected_tier='XS'):
    payload = torch.load(path, map_location='cpu', weights_only=True)
    # Check cheap headers before allocating weights; never interpret an MLP as a Transformer.
    if (payload.get('format_version') != 'transformer-checkpoint-v1' or payload.get('schema_hash') != SCHEMA_HASH
            or payload.get('config') != asdict(TIERS[expected_tier])):
        raise ValueError('Transformer checkpoint architecture/schema/config mismatch')
    model = create_transformer(expected_tier)
    if any(payload.get(k) != v for k, v in model_metadata(model).items()):
        raise ValueError('Transformer checkpoint metadata mismatch')
    model.load_state_dict(payload['model_state'], strict=True)
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError('Nonfinite Transformer checkpoint')
    return model.eval(), payload
