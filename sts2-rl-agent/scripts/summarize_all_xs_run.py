"""Render a markdown report from an all-content runner's report.json.

The formal run stays the source of truth; this script only formats its evidence
and restates the honesty constraints next to the numbers.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _fmt(value, digits=3):
    return 'n/a' if value is None else f'{value:.{digits}f}'


def _loss(row):
    losses = [entry.get('loss') for entry in row.get('updates', []) if 'loss' in entry]
    return sum(losses) / len(losses) if losses else None


def summarize(report):
    lines = []
    provenance = report.get('provenance', {})
    budget = report.get('iteration_budget', {})
    lines.append('# AZ All-Content XS Run')
    lines.append('')
    lines.append('| Field | Value |')
    lines.append('|---|---|')
    lines.append(f"| Version | `{report.get('version', 'n/a')}` |")
    lines.append(f"| Content | `{provenance.get('content', 'n/a')}` |")
    lines.append(f"| Reward | `{provenance.get('reward', 'n/a')}` |")
    lines.append(f"| Rules | `{provenance.get('rules', 'n/a')}` |")
    lines.append(f"| Config SHA-256 | `{provenance.get('config_sha256', 'n/a')}` |")
    lines.append(f"| Protocol SHA-256 | `{provenance.get('protocol_sha256', 'n/a')}` |")
    lines.append(f"| Generator manifest SHA | `{provenance.get('generator_manifest_sha', 'n/a')}` |")
    lines.append(f"| Budget | iterations {budget.get('iterations')}, episodes {budget.get('episodes')}, "
                 f"updates {budget.get('updates')}, search {budget.get('budget')}, "
                 f"batch {budget.get('batch_size')} |")
    lines.append('')
    baseline = report.get('baseline') or {}
    if baseline:
        lines.append('## Baseline (initial weights)')
        lines.append('')
        lines.append('| Episodes | Win rate | Mean V7 utility | Contract rejections |')
        lines.append('|---:|---:|---:|---:|')
        lines.append(f"| {baseline.get('episodes')} | {_fmt(baseline.get('win_rate'))} | "
                     f"{_fmt(baseline.get('mean_utility'))} | {baseline.get('contract_rejections', 0)} |")
        lines.append('')
    if report.get('champion_checkpoint'):
        lines.append(f"Retained champion: `{report['champion_checkpoint']}`; final validation refers to this champion.")
        lines.append('Candidate rows below may include rejected regressions.')
        lines.append('')
    lines.append('## Iterations')
    lines.append('')
    lines.append('| Iter | Episodes | Outcomes | Loss | Val utility | Val win | Paired gain [95% CI] | P(gain>0) | Seconds |')
    lines.append('|---:|---:|---|---:|---:|---:|---|---:|---:|')
    for row in report.get('history', []):
        validation = row.get('validation') or {}
        comparison = row.get('paired_vs_baseline') or {}
        ci = comparison.get('ci95')
        gain = ('n/a' if not comparison else
                f"{_fmt(comparison.get('mean_gain'))} [{_fmt(ci[0])}, {_fmt(ci[1])}]")
        outcomes = row.get('outcomes', [])
        counts = {name: outcomes.count(name) for name in sorted(set(outcomes))}
        seconds = row.get('seconds') or {}
        lines.append(
            f"| {row.get('iteration')} | {len(row.get('episodes', []))} | "
            f"{', '.join(f'{k} {v}' for k, v in counts.items()) or 'n/a'} | "
            f"{_fmt(_loss(row))} | {_fmt(validation.get('mean_utility'))} | "
            f"{_fmt(validation.get('win_rate'))} | {gain} | "
            f"{_fmt(comparison.get('probability_positive'))} | "
            f"{_fmt(seconds.get('total'), 1)} |")
    lines.append('')
    stats = (report.get('history') or [{}])[-1].get('target_stats') or {}
    if stats:
        lines.append('## Search targets (last iteration)')
        lines.append('')
        lines.append('| Rows | Mean entropy | Mean max prob | Forced fraction |')
        lines.append('|---:|---:|---:|---:|')
        lines.append(f"| {stats.get('rows')} | {_fmt(stats.get('mean_entropy'))} | "
                     f"{_fmt(stats.get('mean_max_prob'))} | {_fmt(stats.get('forced_fraction'))} |")
        lines.append('')
    breakdown = (report.get('history') or [{}])[-1].get('validation_by_encounter') or {}
    if breakdown:
        ranked = sorted(breakdown.items(), key=lambda item: item[1]['mean_utility'])
        lines.append('## Weakest encounters (last iteration)')
        lines.append('')
        lines.append('| Encounter | Episodes | Mean utility | Win rate | Death rate |')
        lines.append('|---|---:|---:|---:|---:|')
        for encounter, row in ranked[:10]:
            lines.append(f"| `{encounter}` | {row['episodes']} | {_fmt(row['mean_utility'])} | "
                         f"{_fmt(row['win_rate'])} | {_fmt(row['death_rate'])} |")
        lines.append('')
    rejected = [(row.get('iteration'), item)
                for row in report.get('history', [])
                for item in row.get('rejected_recipes', [])]
    lines.append('## Rejected training recipes')
    lines.append('')
    if rejected:
        lines.append('| Iteration | Encounter | Error |')
        lines.append('|---:|---|---|')
        for iteration, item in rejected:
            lines.append(f"| {iteration} | `{item.get('encounter')}` | {item.get('error')} |")
    else:
        lines.append('None recorded.')
    lines.append('')
    gate = report.get('test_gate')
    if gate:
        lines.append('## Test split gate')
        lines.append('')
        lines.append(f"- Required: {gate.get('required')}")
        lines.append(f"- Passed: {gate.get('passed')}; enforced: {gate.get('enforced')}; "
                     f"forced: {gate.get('forced')}")
        test = report.get('test')
        if test:
            lines.append(f"- Test: {test.get('episodes')} episodes, win {_fmt(test.get('win_rate'))}, "
                         f"mean utility {_fmt(test.get('mean_utility'))}, "
                         f"rejections {test.get('contract_rejections', 0)}")
        lines.append('')
    lines.append('## Reading rules')
    lines.append('')
    lines.append('- Paired gain and its CI are descriptive; a CI containing 0 is not evidence of improvement.')
    lines.append('- Raw utility means are comparable only across policies evaluated on the same frozen split.')
    lines.append('- This report is not a learning claim; it documents what the frozen pipeline measured.')
    lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report')
    parser.add_argument('--out', default=str(ROOT / 'docs' / 'AZ_ALL_XS_RESULTS.md'))
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding='utf-8'))
    text = summarize(report)
    Path(args.out).write_text(text, encoding='utf-8')
    print(args.out)


if __name__ == '__main__':
    main()
