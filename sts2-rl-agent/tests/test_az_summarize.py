"""The run report formatter must keep evidence and caveats next to the numbers."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from summarize_all_xs_run import summarize  # noqa: E402


def _report():
    return dict(
        version='az-all-xs-runner-v1',
        provenance=dict(content='ironclad-colorless-all-v6', reward='risk-terminal-v7',
                        rules='rules-v1', config_sha256='c' * 64, protocol_sha256='p' * 64,
                        generator_manifest_sha='g' * 64),
        iteration_budget=dict(iterations=2, episodes=4, updates=2, budget=8, batch_size=16),
        baseline=dict(episodes=64, win_rate=0.25, mean_utility=0.1, contract_rejections=0),
        history=[
            dict(iteration=0, episodes=['a' * 64, 'b' * 64], outcomes=['win', 'time_limit'],
                 updates=[dict(loss=0.5), dict(loss=0.7)],
                 validation=dict(mean_utility=0.2, win_rate=0.5),
                 paired_vs_baseline=dict(mean_gain=0.1, ci95=[0.05, 0.15],
                                         probability_positive=0.97),
                 target_stats=dict(rows=10, mean_entropy=0.8, mean_max_prob=0.6,
                                   forced_fraction=0.1),
                 validation_by_encounter={'setup_a': dict(episodes=2, mean_utility=0.2,
                                                          win_rate=0.5, death_rate=0.0)},
                 rejected_recipes=[dict(encounter='setup_b', error='ValueError: nope')],
                 seconds=dict(total=12.5), checkpoint='iteration-000.pt'),
            dict(iteration=1, episodes=['c' * 64], outcomes=['death'],
                 updates=[dict(loss=0.4)],
                 validation=dict(mean_utility=0.3, win_rate=0.6),
                 paired_vs_baseline=dict(mean_gain=0.2, ci95=[-0.1, 0.4],
                                         probability_positive=0.8),
                 target_stats=dict(rows=5, mean_entropy=0.9, mean_max_prob=0.5,
                                   forced_fraction=0.0),
                 validation_by_encounter={'setup_a': dict(episodes=1, mean_utility=-0.5,
                                                          win_rate=0.0, death_rate=1.0)},
                 seconds=dict(total=9.0), checkpoint='iteration-001.pt'),
        ],
        test_gate=dict(required='validation mean gain > 0', passed=True, enforced=True,
                       forced=False, comparison=dict(mean_gain=0.2)),
        test=dict(episodes=64, win_rate=0.3, mean_utility=0.25, contract_rejections=0),
        final_validation=dict(mean_utility=0.3, win_rate=0.6),
    )


def test_summary_contains_evidence_and_caveats():
    text = summarize(_report())
    assert 'az-all-xs-runner-v1' in text
    assert '`c' in text and 'Config SHA-256' in text
    assert '| 0 | 2 |' in text and '| 1 | 1 |' in text
    assert '0.100 [0.050, 0.150]' in text and '0.200 [-0.100, 0.400]' in text
    assert '0.970' in text and '0.800' in text
    assert '| `setup_a` | 1 | -0.500 | 0.000 | 1.000 |' in text
    assert '`setup_b`' in text and 'ValueError: nope' in text
    assert 'Passed: True' in text and 'Test: 64 episodes' in text
    assert 'CI containing 0 is not evidence of improvement' in text


def test_summary_handles_an_empty_history():
    report = _report()
    report['history'] = []
    text = summarize(report)
    assert '| Iter | Episodes | Outcomes | Loss |' in text
    assert 'None recorded.' in text

