import unittest

from azcombat.experiments import RESEARCH_ENCOUNTERS
from azcombat.research_report import (_require_root_visit_accounting,
                                      summarize_evaluation, summarize_teacher)


def row(seed, partition, encounter, policy="teacher", outcome="win", status="complete", deck="A"):
    value = {"seed": seed, "partition": partition, "encounter": encounter,
             "policy": policy, "status": status}
    if status == "complete":
        value.update({"outcome": outcome, "terminal": outcome != "unresolved",
                      "valueTarget": 0.6 if outcome == "win" else -1.0,
                      "entryHp": 80, "playerHp": 70 if outcome == "win" else 0,
                      "samples": 5, "choiceSamples": 1, "simulations": [100] * 5,
                      "elapsedMilliseconds": [1000.0] * 5,
                      "priorCalls": 0 if policy in {"teacher", "pure-mcts"} else 10,
                      "valueCalls": 0 if policy in {"teacher", "pure-mcts"} else 10,
                      "fallbacks": 0, "jsonl": f"{seed}-{encounter}-{policy}.jsonl"})
        value.update({"deckTemplate": deck, "openingMonsters": ["MONSTER.TEST"],
                      "openingStateKey": "same-root", "openingObservationSha256": "same-observation"})
    else:
        value["error"] = "preserved failure"
    return value


class ResearchReportTests(unittest.TestCase):
    def test_root_visit_accounting_distinguishes_tree_expansion_from_pure_rollout(self):
        pure = {"simulations": 12, "visitPolicy": {"a": 7, "b": 5}}
        tree = {"simulations": 12, "visitPolicy": {"a": 7, "b": 4}}
        self.assertIsNone(_require_root_visit_accounting(
            pure, {"searchMode": "pure-mcts", "selectedActionId": "a"}, 0))
        self.assertIsNone(_require_root_visit_accounting(
            tree, {"searchMode": "policy-value-tree-v1", "selectedActionId": "a"}, 0))
        with self.assertRaisesRegex(ValueError, "root visit distribution"):
            _require_root_visit_accounting(
                pure, {"searchMode": "policy-value-tree-v1", "selectedActionId": "a"}, 0)
        with self.assertRaisesRegex(ValueError, "root visit distribution"):
            _require_root_visit_accounting(
                tree, {"searchMode": "policy-value-tree-v1", "selectedActionId": "missing"}, 0)

    def test_teacher_requires_predeclared_coverage_and_lists_every_exclusion(self):
        rows = [row(f"T{i:02d}", "train", encounter, deck=chr(65 + i % 5)) for i in range(20)
                for encounter in RESEARCH_ENCOUNTERS]
        rows += [row(f"V{i:02d}", "validation", encounter, deck=chr(65 + i % 5)) for i in range(5)
                 for encounter in RESEARCH_ENCOUNTERS]
        report = summarize_teacher({"phase": "teacher", "runs": rows,
                                    "request": {"deckPlanPath": "frozen-decks.json"}})
        self.assertTrue(report["readyForTraining"])
        self.assertEqual(report["terminalBattles"], 50)
        self.assertEqual(report["terminalDecisionSamples"], 250)
        self.assertEqual(len(report["trainingInputs"]), 50)

        rows[0] = row("T00", "train", RESEARCH_ENCOUNTERS[0], outcome="unresolved")
        rows[1] = row("T00", "train", RESEARCH_ENCOUNTERS[1], status="error")
        report = summarize_teacher({"phase": "teacher", "runs": rows,
                                    "request": {"deckPlanPath": "frozen-decks.json"}})
        self.assertEqual(report["statusCounts"]["unresolved"], 1)
        self.assertEqual(report["statusCounts"]["error"], 1)
        self.assertEqual(len(report["excluded"]), 2)
        self.assertEqual(len(report["trainingInputs"]), 48)
        self.assertEqual(report["trainSeeds"], 19)

    def test_evaluation_counts_battles_not_decision_lines_and_preserves_pairs(self):
        policies = ("pure-mcts", "old-tree", "new-tree")
        rows = [row("E00", "evaluation", encounter, policy) for encounter in RESEARCH_ENCOUNTERS
                for policy in policies]
        rows[1] = row("E00", "evaluation", RESEARCH_ENCOUNTERS[0], "old-tree", status="error")
        summary = summarize_evaluation({"phase": "evaluation", "runs": rows,
                                        "request": {"evaluationSeeds": ["E00"]}})
        self.assertEqual(summary["plannedTasks"], 6)
        self.assertEqual(summary["byArm"]["old-tree"]["counts"]["error"], 1)
        self.assertEqual(summary["byArm"]["new-tree"]["decisionSamples"], 10)
        self.assertEqual(summary["completePairs"], 1)
        self.assertEqual(summary["mismatchedOpeningRoots"], 0)
        self.assertEqual(len(summary["pairedBattles"]), 2)


if __name__ == "__main__":
    unittest.main()
