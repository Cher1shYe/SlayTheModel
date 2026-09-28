import unittest

from azcombat.r5_experiment import assign_weights


class R5ExperimentTests(unittest.TestCase):
    def test_long_unresolved_trajectory_has_equal_policy_mass_not_value_mass(self):
        entries = [dict(taskId='a', partition='train', policy='pure-mcts',
                        rowCount=2, outcome='win'),
                   dict(taskId='b', partition='train', policy='tree-candidate',
                        rowCount=3, outcome='loss'),
                   dict(taskId='c', partition='train', policy='tree-candidate',
                        rowCount=271, outcome='unresolved')]
        assign_weights(entries)
        self.assertAlmostEqual(entries[0]['policyRowWeight'] * 2, .5)
        self.assertAlmostEqual(entries[1]['policyRowWeight'] * 3, .25)
        self.assertAlmostEqual(entries[2]['policyRowWeight'] * 271, .25)
        self.assertEqual(entries[2]['valueRowWeight'], 0)
        self.assertAlmostEqual(entries[1]['valueRowWeight'] * 3, .5)


if __name__ == '__main__':
    unittest.main()
