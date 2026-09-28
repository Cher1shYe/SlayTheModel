from dataclasses import replace
import unittest
import torch
from azcombat.r4_training import R4WeightedSample, weighted_epoch
from azcombat.training import DeepSetsPolicyValue
from test_training import sample


class WeightedEpochTests(unittest.TestCase):
    def test_splitting_row_weight_preserves_update(self):
        torch.manual_seed(7)
        first = DeepSetsPolicyValue(16)
        second = DeepSetsPolicyValue(16)
        second.load_state_dict(first.state_dict())
        item = R4WeightedSample(sample('train'), 'task', 'train', 'pure-mcts', 'win', 1., 1.)
        weighted_epoch(first, [item], torch.optim.Adam(first.parameters(), lr=.001))
        half = replace(item, policy_weight=.5, value_weight=.5)
        weighted_epoch(second, [half, half], torch.optim.Adam(second.parameters(), lr=.001))
        for left, right in zip(first.parameters(), second.parameters()):
            torch.testing.assert_close(left, right, atol=1e-7, rtol=1e-6)

    def test_unresolved_value_target_does_not_change_update(self):
        torch.manual_seed(7)
        first = DeepSetsPolicyValue(16)
        second = DeepSetsPolicyValue(16)
        second.load_state_dict(first.state_dict())
        item = R4WeightedSample(replace(sample('train'), outcome='unresolved'), 'task', 'train', 'pure-mcts', 'unresolved', 1., 0.)
        other = replace(item, sample=replace(item.sample, value_target=-.5))
        weighted_epoch(first, [item], torch.optim.Adam(first.parameters(), lr=.001))
        weighted_epoch(second, [other], torch.optim.Adam(second.parameters(), lr=.001))
        for left, right in zip(first.parameters(), second.parameters()):
            torch.testing.assert_close(left, right, atol=0, rtol=0)
