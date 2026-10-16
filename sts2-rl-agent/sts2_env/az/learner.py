"""Candidate training; every candidate gets a fresh AdamW optimizer."""
from copy import deepcopy
import numpy as np
import torch

from .encoder import EncodedObservation
from .network import batch_observations, policy_value_loss


class Learner:
    def __init__(self, champion, learning_rate=0.0003, weight_decay=0.0001):
        self.model = deepcopy(champion).requires_grad_(True).train()
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        self.updates = 0

    def update(self, samples, microbatch_size=None):
        from .transformer_network import TransformerPolicyValueNetwork
        if isinstance(self.model, TransformerPolicyValueNetwork):
            return self.update_entities(samples, microbatch_size)
        observations = [EncodedObservation(**{k: np.asarray(v) for k, v in s["observation"].items()},
                                           information_mode=self.model.information_mode,
                                           reward_version=self.model.reward_version,
                                           content_version=self.model.content_version) for s in samples]
        batch = batch_observations(observations, next(self.model.parameters()).device)
        targets = torch.tensor(np.asarray([s["policy_target"] for s in samples]), dtype=torch.float32,
                               device=batch["numeric"].device)
        values = torch.tensor([s["z"] for s in samples], dtype=torch.float32, device=targets.device)
        self.optimizer.zero_grad(set_to_none=True)
        loss, metrics = policy_value_loss(self.model, batch, targets, values)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0, error_if_nonfinite=True)
        self.optimizer.step()
        self.updates += 1
        return dict(metrics, loss=float(loss.detach()), gradient_norm=float(norm), update=self.updates)

    def update_entities(self, samples, microbatch_size=None):
        from .entity_replay import unpack_observation
        from .transformer_network import batch_entities, keyed_targets
        if not samples or (microbatch_size is not None and (type(microbatch_size) is not int or microbatch_size < 1)):
            raise ValueError('Nonempty batch and positive microbatch required')
        size = microbatch_size or len(samples)
        # Stable length buckets change padding only; every sampled state retains
        # weight 1/N and sampling RNG is untouched.
        samples = sorted(samples, key=lambda s: (len(s['observation']['entities']), len(s['observation']['actions'])))
        device = next(self.model.parameters()).device
        self.optimizer.zero_grad(set_to_none=True)
        metrics = {}
        for start in range(0, len(samples), size):
            part = samples[start:start+size]
            batch = batch_entities([unpack_observation(s['observation']) for s in part], device)
            targets = keyed_targets(batch, [s['policy_target'] for s in part])
            values = torch.tensor([s['z'] for s in part], dtype=torch.float32, device=device)
            loss, current = policy_value_loss(self.model, batch, targets, values)
            weight = len(part)/len(samples)
            (loss*weight).backward()
            for k, v in dict(current, loss=float(loss.detach())).items():
                metrics[k] = metrics.get(k, 0.) + weight*v
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1., error_if_nonfinite=True)
        self.optimizer.step()
        self.updates += 1
        return dict(metrics, gradient_norm=float(norm), update=self.updates)

    def train(self, replay, rng, updates=200, batch_size=256):
        if (replay.compatibility["information_mode"] != self.model.information_mode
                or replay.compatibility["reward_version"] != self.model.reward_version
                or replay.content_version != self.model.content_version):
            raise ValueError("Learner/replay mode mismatch")
        if updates < 1:
            raise ValueError("Positive updates required")
        history = []
        for _ in range(updates):
            samples, counts = replay.sample(batch_size, rng)
            history.append(dict(self.update(samples), family_counts=counts))
        return history
