"""Explicit architecture dispatch at training/worker boundaries, not legacy loaders."""
import torch
from . import network
from .model_factory import save_transformer_checkpoint, load_transformer_checkpoint
from .transformer_network import TransformerPolicyValueNetwork
from .config import CONTENT_VERSION, REWARD_VERSION


def save_checkpoint(path, model, *args, **kwargs):
    if isinstance(model, TransformerPolicyValueNetwork):
        return save_transformer_checkpoint(path, model, *args, **kwargs)
    return network.save_checkpoint(path, model, *args, **kwargs)


def load_checkpoint(path, expected_mode, expected_reward=REWARD_VERSION, expected_content=CONTENT_VERSION):
    header = torch.load(path, map_location='cpu', weights_only=True)
    if header.get('format_version') == 'transformer-checkpoint-v1':
        from .entity_encoder import SUPPORTED, supported_reward
        if expected_mode != 'observable' or not supported_reward(expected_content, expected_reward):
            raise ValueError('Transformer content/mode/reward mismatch')
        tier = header['config']['tier']
        del header
        return load_transformer_checkpoint(path, tier,expected_content,expected_reward)
    del header
    return network.load_checkpoint(path, expected_mode, expected_reward, expected_content)
