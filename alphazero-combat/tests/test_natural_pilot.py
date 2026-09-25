from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from azcombat.natural_pilot import freeze_pilot, run_pilot


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _cross_root_stub() -> dict:
    def capture(number: int, prefix: int) -> dict:
        return {"TrajectoryId": "t", "CaptureId": number,
                "CaptureBoundaryKey": f"boundary-{number}",
                "InitialEnemyEffectiveHp": 80, "CapturedEnemyDamagePrefix": prefix}
    def reward(outcome: str, prefix: int, addition: int, hp: int, value: float) -> dict:
        capture = 3 if prefix == 14 else 2
        return {"Outcome": outcome, "TrajectoryId": "t", "EntryHp": 80,
                "SettledFinalHp": hp, "TrajectoryInitialEnemyHp": 80,
                "CaptureId": capture, "CaptureBoundaryKey": f"boundary-{capture}",
                "CapturedEnemyDamagePrefix": prefix, "EnemyHpLost": addition,
                "TotalEnemyHpLost": 14, "Reward": value}
    return {"format": "azcombat.cross-root-reward-regression.v1", "regressionOnly": True,
            "status": "passed", "crossRoot": {
                "regressionOnly": True, "trajectoryId": "t", "initialEnemyHp": 80,
                "prefixTransition": {"Before": 80, "After": 74, "Damage": 6},
                "branchTransition": {"Before": 74, "After": 66, "Damage": 8},
                "capturedPrefixDamage": 6, "branchDamage": 8, "totalEnemyHpLost": 14,
                "firstCapture": capture(1, 0), "secondCapture": capture(2, 6),
                "thirdCapture": capture(3, 14),
                "unresolvedAtDecisionCap": {"decisionCap": 2, "executedDecisions": 2,
                                            "terminationReason": "decision_cap",
                                            "rewardInputs": reward("unresolved", 6, 8, 1, -0.45625)},
                "rewardInputs": reward("loss", 6, 8, 0, -0.95625),
                "recapturedRewardInputs": reward("loss", 14, 0, 0, -0.95625),
                "actualReward": -0.95625, "expectedLoss": -0.95625,
                "liveSettledHp": 0}}


class NaturalPilotPlanTests(unittest.TestCase):
    def test_freeze_declares_20_paired_jobs_without_launching_or_rewriting(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            game, ritsu = base / "game", base / "ritsu"
            game.mkdir()
            ritsu.mkdir()
            (game / "data_sts2_windows_x86_64").mkdir()
            (ritsu / "compat" / "0.111.0").mkdir(parents=True)
            (game / "data_sts2_windows_x86_64" / "sts2.dll").write_bytes(b"game")
            (ritsu / "compat" / "0.111.0" / "STS2-RitsuLib.dll").write_bytes(b"ritsu")
            split = base / "split.json"
            _write_json(split, {"format": "azcombat.seed-split.v1",
                                "trainSeeds": [f"old-T{i}" for i in range(20)],
                                "validationSeeds": [f"old-V{i}" for i in range(5)],
                                "evaluationSeeds": [f"old-E{i}" for i in range(10)]})
            deck = base / "deck.json"
            templates = {name: {"characterCards": ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", card]}
                         for name, card in zip("ABCDE", ("ARMAMENTS", "BURNING_PACT", "HEADBUTT",
                                                           "ARMAMENTS", "BURNING_PACT"), strict=True)}
            _write_json(deck, {"format": "azcombat.deck-plan.v1", "templates": templates})
            budget = base / "budget.json"
            _write_json(budget, {"format": "azcombat.research-wave.v1", "status": "complete", "request": {
                "phase": "evaluation",
                "budgetMilliseconds": 1000, "maxSimulations": None, "maxDecisions": 256,
                "timeoutSeconds": 1800,
                "encounters": ["CULTISTS_NORMAL", "LIVING_FOG_NORMAL"]}})
            cross_root = base / "cross-root.json"
            _write_json(cross_root, _cross_root_stub())
            enemy_damage = base / "enemy-damage.json"
            _write_json(enemy_damage, {"format": "azcombat.enemy-damage-ledger-regression.v1",
                                       "regressionOnly": True, "status": "passed",
                                       "despawnUnresolved": {"bombHpBefore": 7,
                                                             "bombPresentAfter": False,
                                                             "transition": {"damage": 0},
                                                             "predictedBranchDamage": 0,
                                                             "nativeUnresolved": -0.5,
                                                             "predictedUnresolved": -0.5},
                                       "lethalOverkill": {"targetHpBefore": 4,
                                                          "unblockedDamage": 4,
                                                          "overkillDamage": 6,
                                                          "creditedDamage": 4,
                                                          "transition": {"damage": 4},
                                                          "predictedBranchDamage": 4},
                                       "despawnLoss": {"playerDead": True,
                                                       "nativeLoss": -1.0,
                                                       "predictedLoss": -1.0}})
            model = base / "candidate.onnx"
            model.write_bytes(b"frozen-model")
            _write_json(model.with_suffix(".manifest.json"), {
                "format": "azcombat.onnx.v4", "featureAbi": "azcombat.features.v4",
                "observationSchemaVersion": 3,
                "inputs": {"entities": ["N", 12], "globals": [4], "actions": ["A", 19]},
                "outputs": {"logits": ["A"], "value": []},
                "checkpointSha256": "0" * 64,
                "onnxSha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "training": {"trainSeeds": ["old-T0"], "validationSeeds": ["old-V0"]},
            })
            pilot = [f"fresh-P{i}" for i in range(5)]
            final = [f"fresh-F{i}" for i in range(5)]
            output = base / "pilot"
            with patch("azcombat.natural_pilot.TREE_CANDIDATE_SHA256",
                       hashlib.sha256(model.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot.R3_DECK_PLAN_SHA256",
                       hashlib.sha256(deck.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot.R1_SEED_SPLIT_SHA256",
                       hashlib.sha256(split.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot._source_snapshot", return_value={
                    "rootCommit": "a" * 40, "combatPinnedSourceCommit": "b" * 40,
                    "combatSourceCommitFileSha256": "d" * 64,
                    "sourceTreeSha256": "c" * 64}), \
                 patch("azcombat.natural_pilot._historical_seeds", return_value=set()):
                valid_damage = json.loads(enemy_damage.read_text(encoding="utf-8"))
                incomplete_damage = dict(valid_damage)
                del incomplete_damage["despawnUnresolved"]
                _write_json(enemy_damage, incomplete_damage)
                with self.assertRaisesRegex(ValueError, "enemy-damage regression"):
                    freeze_pilot(output=output, pilot_seeds=pilot,
                                 final_evaluation_seeds=final, deck_plan=deck,
                                 historical_split=split, model=model,
                                 game_dir=game, ritsu_root=ritsu,
                                 budget_evidence=budget, cross_root_evidence=cross_root,
                                 enemy_damage_evidence=enemy_damage)
                self.assertFalse(output.exists())
                _write_json(enemy_damage, valid_damage)
                manifest = freeze_pilot(output=output, pilot_seeds=pilot,
                                        final_evaluation_seeds=final, deck_plan=deck,
                                        historical_split=split, model=model,
                                        game_dir=game, ritsu_root=ritsu,
                                        budget_evidence=budget, cross_root_evidence=cross_root,
                                        enemy_damage_evidence=enemy_damage)
            self.assertEqual(len(manifest["tasks"]), 20)
            self.assertEqual(manifest["format"], "azcombat.natural-pilot.v2")
            self.assertEqual(manifest["contracts"]["rewardLedgerVersion"],
                             "azcombat.reward-ledger.v2")
            self.assertEqual(manifest["enemyDamageRegression"]["sha256"],
                             hashlib.sha256(enemy_damage.read_bytes()).hexdigest())
            self.assertEqual(manifest["treeCandidate"]["usage"], "fixed-behavior-policy-only")
            self.assertEqual(manifest["treeCandidate"]["trainingRewardLedgerVersion"],
                             "azcombat.reward-ledger.v1")
            self.assertEqual(len({task["taskId"] for task in manifest["tasks"]}), 20)
            self.assertEqual(manifest["seedPartitions"], {
                "train": pilot[:4], "validation": pilot[4:], "finalEvaluationSealed": final})
            self.assertEqual({task["encounter"] for task in manifest["tasks"]},
                             {"CULTISTS_NORMAL", "LIVING_FOG_NORMAL"})
            for seed in pilot:
                for encounter in ("CULTISTS_NORMAL", "LIVING_FOG_NORMAL"):
                    pair = [task for task in manifest["tasks"]
                            if task["seed"] == seed and task["encounter"] == encounter]
                    self.assertEqual([task["policy"] for task in pair],
                                     ["pure-mcts", "tree-candidate"])
                    self.assertEqual(len({task["generatedScenarioSha256"] for task in pair}), 1)
                    self.assertEqual(len({task["generatedScenario"] for task in pair}), 1)
                    self.assertEqual({task["maxSimulations"] for task in pair}, {None})
                    self.assertEqual({task["maxDecisions"] for task in pair}, {256})
                    self.assertEqual({task["budgetMilliseconds"] for task in pair}, {1000})
            self.assertTrue(manifest["deckTemplates"]["reusedHistoricalTemplates"])
            self.assertEqual(len(list((output / "inputs").glob("*.json"))), 10)
            self.assertEqual(hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
                             (output / "manifest.sha256").read_text(encoding="ascii").strip())
            with patch("azcombat.natural_pilot.TREE_CANDIDATE_SHA256",
                       hashlib.sha256(model.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot.R3_DECK_PLAN_SHA256",
                       hashlib.sha256(deck.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot.R1_SEED_SPLIT_SHA256",
                       hashlib.sha256(split.read_bytes()).hexdigest()), \
                 patch("azcombat.natural_pilot._source_snapshot", return_value={
                    "rootCommit": "a" * 40, "combatPinnedSourceCommit": "b" * 40,
                    "combatSourceCommitFileSha256": "d" * 64,
                    "sourceTreeSha256": "c" * 64}), \
                 patch("azcombat.natural_pilot._historical_seeds", return_value=set()):
                with self.assertRaises(FileExistsError):
                    freeze_pilot(output=output, pilot_seeds=pilot,
                                 final_evaluation_seeds=final, deck_plan=deck,
                                 historical_split=split, model=model,
                                 game_dir=game, ritsu_root=ritsu,
                                 budget_evidence=budget, cross_root_evidence=cross_root,
                                 enemy_damage_evidence=enemy_damage)

            original_manifest = (output / "manifest.json").read_bytes()
            with patch("azcombat.natural_pilot._source_snapshot", return_value={
                    "rootCommit": "a" * 40, "combatPinnedSourceCommit": "b" * 40,
                    "combatSourceCommitFileSha256": "d" * 64,
                    "sourceTreeSha256": "c" * 64}), \
                 patch("azcombat.native_probe.run_probe", side_effect=OSError("launch broken")) as probe:
                with self.assertRaisesRegex(OSError, "launch broken"):
                    run_pilot(output / "manifest.json", limit=1)
            self.assertEqual(probe.call_count, 1)
            attempt = output / "attempts" / manifest["tasks"][0]["taskId"] / "attempt-001"
            record = json.loads((attempt / "attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["failureClass"], "infrastructure")
            with patch("azcombat.natural_pilot._source_snapshot", return_value={
                    "rootCommit": "a" * 40, "combatPinnedSourceCommit": "b" * 40,
                    "combatSourceCommitFileSha256": "d" * 64,
                    "sourceTreeSha256": "c" * 64}), \
                 patch("azcombat.native_probe.run_probe", side_effect=ValueError("bad choice")) as probe:
                with self.assertRaisesRegex(ValueError, "bad choice"):
                    run_pilot(output / "manifest.json", retry_task=manifest["tasks"][0]["taskId"])
            self.assertEqual(probe.call_count, 1)
            retry = output / "attempts" / manifest["tasks"][0]["taskId"] / "attempt-002"
            record_retry = json.loads((retry / "attempt.json").read_text(encoding="utf-8"))
            self.assertEqual(record_retry["status"], "failed")
            self.assertEqual(record_retry["failureClass"], "protocol-or-unclassified")
            self.assertEqual(json.loads((attempt / "attempt.json").read_text(encoding="utf-8")), record)
            self.assertEqual((output / "manifest.json").read_bytes(), original_manifest)
            with patch("azcombat.natural_pilot._source_snapshot", return_value={
                    "rootCommit": "a" * 40, "combatPinnedSourceCommit": "b" * 40,
                    "combatSourceCommitFileSha256": "d" * 64,
                    "sourceTreeSha256": "c" * 64}), \
                 patch("azcombat.native_probe.run_probe") as forbidden:
                with self.assertRaisesRegex(ValueError, "failed prior attempt"):
                    run_pilot(output / "manifest.json", limit=1)
                forbidden.assert_not_called()
