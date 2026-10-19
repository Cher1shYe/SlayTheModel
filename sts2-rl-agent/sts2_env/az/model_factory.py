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


def create_transformer(tier='XS', content_version=SCHEMA['content'], reward_version=None):
    if tier not in TIERS:
        raise ValueError(f'Unknown model tier: {tier}')
    from .native_generic import CONTENT as NATIVE_CONTENT
    if content_version == NATIVE_CONTENT:
        from .native_transformer import NativeTransformer
        from .rewards import V7
        if reward_version != V7: raise ValueError('Native generic requires V7')
        return NativeTransformer(TIERS[tier])
    return TransformerPolicyValueNetwork(TIERS[tier],content_version,reward_version)


def model_metadata(model):
    config = asdict(model.config)
    from .native_generic import CONTENT as NATIVE_CONTENT, SCHEMA as NATIVE_SCHEMA, SCHEMA_HASH as NATIVE_HASH
    if model.content_version == NATIVE_CONTENT:
        from .native_transformer import ARCHITECTURE
        return dict(format_version='native-transformer-checkpoint-v1',architecture=ARCHITECTURE,
                    config=config,config_hash=content_hash(config),schema=NATIVE_SCHEMA,schema_hash=NATIVE_HASH,
                    information_mode='observable',reward_version=model.reward_version,content_manifest_version=NATIVE_CONTENT,
                    parameter_count=sum(p.numel() for p in model.parameters()))
    return {'format_version': 'transformer-checkpoint-v1', 'architecture': ARCHITECTURE_VERSION,
            'config': config, 'config_hash': content_hash(config), 'schema': SCHEMA,
            'information_mode': 'observable', 'reward_version': model.reward_version, 'content_manifest_version': model.content_version,
            'schema_hash': SCHEMA_HASH, 'parameter_count': sum(p.numel() for p in model.parameters())}


def save_transformer_checkpoint(path, model, model_version='entity-initial', config=None, statistics=None,
                                iteration=0, training_state=None):
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError('Nonfinite Transformer weights')
    payload = dict(model_metadata(model), model_state=model.state_dict(), code_digest=code_digest(),
                   torch_version=str(torch.__version__), resume_scope='weights_only',
                   model_version=model_version, run_config=config or {}, statistics=statistics or {}, iteration=iteration)
    if training_state is not None:
        payload.update(training_state=training_state, resume_scope='training_update_boundary')
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


def load_transformer_checkpoint(path, expected_tier='XS', expected_content=SCHEMA['content'], expected_reward=None):
    if expected_tier not in TIERS:
        raise ValueError('Unknown Transformer tier')
    payload = torch.load(path, map_location='cpu', weights_only=True)
    from .native_generic import CONTENT as NATIVE_CONTENT, SCHEMA_HASH as NATIVE_HASH
    native = expected_content == NATIVE_CONTENT
    # Check cheap headers before allocating weights; never interpret an MLP as a Transformer.
    if (payload.get('format_version') != ('native-transformer-checkpoint-v1' if native else 'transformer-checkpoint-v1') or payload.get('schema_hash') != (NATIVE_HASH if native else SCHEMA_HASH)
            or payload.get('config') != asdict(TIERS[expected_tier])):
        raise ValueError('Transformer checkpoint architecture/schema/config mismatch')
    model = create_transformer(expected_tier,expected_content,expected_reward)
    if any(payload.get(k) != v for k, v in model_metadata(model).items()):
        raise ValueError('Transformer checkpoint metadata mismatch')
    model.load_state_dict(payload['model_state'], strict=True)
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError('Nonfinite Transformer checkpoint')
    return model.eval(), payload
