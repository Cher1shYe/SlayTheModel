from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from azcombat.native_probe import _audit_reward_ledger, _audit_tree_parity, audit_probe
from azcombat.reward import Outcome, TerminalResult, score_result
from azcombat.samples import TrainingSample
from azcombat.schema import ActionNode
from azcombat.versions import REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION
from test_schema_reward import observation


def _ledger(*, outcome: str = "unresolved") -> tuple[dict, list[dict]]:
    transitions = [
        {"before": 20, "after": 15, "damage": 5,
         "historyStartIndex": 0, "historyEndIndex": 1,
         "enemyRosterBefore": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 20}],
         "enemyRosterAfter": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 15}],
         "enemyDamageEvents": [{"combatId": 1, "monsterId": "MONSTER.TEST",
                                "unblockedDamage": 5, "overkillDamage": 0, "creditedDamage": 5}]},
        {"before": 15, "after": 8, "damage": 7,
         "historyStartIndex": 1, "historyEndIndex": 2,
         "enemyRosterBefore": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 15}],
         "enemyRosterAfter": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 8}],
         "enemyDamageEvents": [{"combatId": 1, "monsterId": "MONSTER.TEST",
                                "unblockedDamage": 7, "overkillDamage": 0, "creditedDamage": 7}]},
    ]
    terminal = outcome != "unresolved"
    final_hp = 0 if outcome == "loss" else 76
    audits = []
    for index, (prefix, branch, total, root_hp) in enumerate(((0, 5, 5, 20), (5, 7, 12, 15))):
        row_outcome = outcome if index == 1 else "unresolved"
        settled_hp = final_hp if index == 1 else 80
        combat_hp = settled_hp - 6 if row_outcome == "win" else settled_hp
        audits.append({
            "TrajectoryId": "pilot-seed#1", "CaptureId": index + 1,
            "CaptureBoundaryKey": ("A" if index == 0 else "B") * 64,
            "Outcome": row_outcome, "EntryHp": 80,
            "CombatFinalHp": combat_hp, "CombatFinalMaxHp": 80 if row_outcome != "unresolved" else 0,
            "UnconditionalRelicHeal": 6 if row_outcome == "win" else 0,
            "WoundedRelicHeal": 0, "WoundedHpPercent": 0,
            "AppliedPostCombatHeal": 6 if row_outcome == "win" else 0,
            "SettledFinalHp": settled_hp, "EnemyHpLost": branch,
            "EnemyHpTotal": root_hp, "TrajectoryInitialEnemyHp": 20,
            "CapturedEnemyDamagePrefix": prefix, "TotalEnemyHpLost": total,
            "EnemyDamageProgress": total / 20,
            "Reward": score_result(TerminalResult(Outcome(row_outcome), 80, settled_hp, total, 20)),
        })
    provenance = {
        "seed": "pilot-seed", "entryHp": 80, "playerHp": final_hp,
        "terminal": terminal, "trajectoryInitialEnemyEffectiveHp": 20,
        "enemyDamageLost": 12, "enemyHpTransitions": transitions,
        "rewardAudits": audits,
    }
    metrics = [
        {"parentDecision": 0, "choiceLayer": 0},
        {"parentDecision": 1, "choiceLayer": 0},
    ]
    return provenance, metrics


def _one_step_ledger(before: list[dict], after: list[dict],
                     events: list[dict], damage: int) -> tuple[dict, list[dict]]:
    denominator = sum(enemy["hp"] for enemy in before)
    reward = score_result(TerminalResult(Outcome.UNRESOLVED, 80, 80,
                                         damage, denominator))
    audit = {"TrajectoryId": "pilot-seed#1", "CaptureId": 1,
             "CaptureBoundaryKey": "A" * 64, "Outcome": "unresolved",
             "EntryHp": 80, "CombatFinalHp": 80, "CombatFinalMaxHp": 0,
             "UnconditionalRelicHeal": 0, "WoundedRelicHeal": 0,
             "WoundedHpPercent": 0, "AppliedPostCombatHeal": 0,
             "SettledFinalHp": 80, "EnemyHpLost": damage,
             "EnemyHpTotal": denominator, "TrajectoryInitialEnemyHp": denominator,
             "CapturedEnemyDamagePrefix": 0, "TotalEnemyHpLost": damage,
             "EnemyDamageProgress": min(damage / denominator, 1),
             "Reward": reward}
    transition = {"before": denominator, "after": sum(enemy["hp"] for enemy in after),
                  "damage": damage, "historyStartIndex": 4,
                  "historyEndIndex": 5 + len(events),
                  "enemyRosterBefore": before, "enemyRosterAfter": after,
                  "enemyDamageEvents": events}
    return ({"seed": "pilot-seed", "entryHp": 80, "playerHp": 80,
             "terminal": False, "trajectoryInitialEnemyEffectiveHp": denominator,
             "enemyDamageLost": damage, "enemyHpTransitions": [transition],
             "rewardAudits": [audit]},
            [{"parentDecision": 0, "choiceLayer": 0}])


class PilotRewardLedgerTests(unittest.TestCase):
    def test_terminal_command_events_exclude_cleanup_hp(self):
        provenance, metrics = _ledger(outcome="loss")
        last = provenance["enemyHpTransitions"][-1]
        last["historyReset"] = True
        last["damageCaptureSource"] = "native-damage-command-v1"
        last["after"] = 0
        last["enemyRosterAfter"] = []
        # Actual command damage remains 7 although another 8 HP disappears.
        result = _audit_reward_ledger(provenance, metrics, final_outcome="loss",
                                     final_value=provenance["rewardAudits"][-1]["Reward"])
        self.assertEqual(result["totalEnemyHpLost"], 12)
        last["damage"] = 15
        with self.assertRaisesRegex(ValueError, "damage differs"):
            _audit_reward_ledger(provenance, metrics, final_outcome="loss",
                                 final_value=provenance["rewardAudits"][-1]["Reward"])

    def test_overkill_may_exceed_actual_hp_loss(self):
        fog = {"combatId": 1, "monsterId": "MONSTER.LIVING_FOG", "hp": 80}
        bomb = {"combatId": 4, "monsterId": "MONSTER.GAS_BOMB", "hp": 1}
        event = {"combatId": 4, "monsterId": "MONSTER.GAS_BOMB",
                 "unblockedDamage": 1, "overkillDamage": 8, "creditedDamage": 1}
        provenance, metrics = _one_step_ledger([bomb, fog], [fog], [event], 1)
        result = _audit_reward_ledger(
            provenance, metrics, final_outcome="unresolved",
            final_value=provenance["rewardAudits"][0]["Reward"])
        self.assertEqual(result["totalEnemyHpLost"], 1)
        self.assertEqual(result["nativeDamageEvents"], 1)

    def test_damage_and_overkill_ranges_preserve_only_actual_hp_credit(self):
        for hp_loss, overkill in ((1, 8), (5, 5), (5, 2), (5, 0), (0, 0)):
            with self.subTest(hp_loss=hp_loss, overkill=overkill):
                before = {"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 10}
                after = {**before, "hp": 10 - hp_loss}
                event = {"combatId": 1, "monsterId": "MONSTER.TEST",
                         "unblockedDamage": hp_loss, "overkillDamage": overkill,
                         "creditedDamage": hp_loss}
                provenance, metrics = _one_step_ledger([before], [after], [event], hp_loss)
                result = _audit_reward_ledger(
                    provenance, metrics, final_outcome="unresolved",
                    final_value=provenance["rewardAudits"][0]["Reward"])
                self.assertEqual(result["totalEnemyHpLost"], hp_loss)

    def test_damage_fields_reject_negative_bool_missing_and_wrong_types(self):
        for field in ("unblockedDamage", "overkillDamage", "creditedDamage"):
            for value in (-1, True, False, 1.0, "1", None, "missing"):
                with self.subTest(field=field, value=value):
                    provenance, metrics = _ledger()
                    event = provenance["enemyHpTransitions"][0]["enemyDamageEvents"][0]
                    if value == "missing":
                        del event[field]
                    else:
                        event[field] = value
                    with self.assertRaisesRegex(ValueError, "malformed damage event"):
                        _audit_reward_ledger(
                            provenance, metrics, final_outcome="unresolved",
                            final_value=provenance["rewardAudits"][-1]["Reward"])

    def test_overkill_fix_does_not_accept_forged_credit_totals_or_rewards(self):
        for field in ("creditedDamage", "damage", "enemyDamageLost", "Reward", "finalValue"):
            with self.subTest(field=field):
                provenance, metrics = _ledger()
                final_value = provenance["rewardAudits"][-1]["Reward"]
                if field == "creditedDamage":
                    provenance["enemyHpTransitions"][0]["enemyDamageEvents"][0][field] = 4
                elif field == "damage":
                    provenance["enemyHpTransitions"][0][field] = 4
                elif field == "enemyDamageLost":
                    provenance[field] = 11
                elif field == "Reward":
                    provenance["rewardAudits"][-1][field] += 0.01
                else:
                    final_value += 0.01
                with self.assertRaises(ValueError):
                    _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                         final_value=final_value)

    def test_summoned_bomb_departure_is_not_enemy_damage(self):
        fog = {"combatId": 1, "monsterId": "MONSTER.LIVING_FOG", "hp": 80}
        bomb = {"combatId": 10, "monsterId": "MONSTER.GAS_BOMB", "hp": 7}
        transitions = [
            {"before": 80, "after": 87, "damage": 0,
             "historyStartIndex": 0, "historyEndIndex": 1,
             "enemyRosterBefore": [fog], "enemyRosterAfter": [fog, bomb],
             "enemyDamageEvents": []},
            {"before": 87, "after": 80, "damage": 0,
             "historyStartIndex": 1, "historyEndIndex": 2,
             "enemyRosterBefore": [fog, bomb], "enemyRosterAfter": [fog],
             "enemyDamageEvents": []},
        ]
        audits = []
        for capture_id, root_hp in ((1, 80), (2, 87)):
            audits.append({
                "TrajectoryId": "pilot-seed#1", "CaptureId": capture_id,
                "CaptureBoundaryKey": "A" * 64, "Outcome": "unresolved",
                "EntryHp": 80, "CombatFinalHp": 52, "CombatFinalMaxHp": 0,
                "UnconditionalRelicHeal": 0, "WoundedRelicHeal": 0,
                "WoundedHpPercent": 0, "AppliedPostCombatHeal": 0,
                "SettledFinalHp": 52, "EnemyHpLost": 0, "EnemyHpTotal": root_hp,
                "TrajectoryInitialEnemyHp": 80, "CapturedEnemyDamagePrefix": 0,
                "TotalEnemyHpLost": 0, "EnemyDamageProgress": 0,
                "Reward": -0.5,
            })
        provenance = {"seed": "pilot-seed", "entryHp": 80, "playerHp": 52,
                      "terminal": False, "trajectoryInitialEnemyEffectiveHp": 80,
                      "enemyDamageLost": 0, "enemyHpTransitions": transitions,
                      "rewardAudits": audits}
        metrics = [{"parentDecision": index, "choiceLayer": 0}
                   for index in range(2)]
        summary = _audit_reward_ledger(provenance, metrics,
                                       final_outcome="unresolved", final_value=-0.5)
        self.assertEqual(summary["totalEnemyHpLost"], 0)
        self.assertEqual(summary["captureLedger"][1]["branchDamage"], 0)

    def test_overkill_diagnostic_does_not_reduce_unblocked_damage_credit(self):
        fog = {"combatId": 1, "monsterId": "MONSTER.LIVING_FOG", "hp": 15}
        bomb = {"combatId": 10, "monsterId": "MONSTER.GAS_BOMB", "hp": 5}
        event = {"combatId": 10, "monsterId": "MONSTER.GAS_BOMB",
                 "unblockedDamage": 5, "overkillDamage": 5, "creditedDamage": 5}
        provenance, metrics = _one_step_ledger([fog, bomb], [fog], [event], 5)
        reward = provenance["rewardAudits"][0]["Reward"]
        summary = _audit_reward_ledger(provenance, metrics,
                                       final_outcome="unresolved", final_value=reward)
        self.assertEqual(summary["totalEnemyHpLost"], 5)
        self.assertEqual(summary["nativeDamageEvents"], 1)
        forged = deepcopy(provenance)
        forged["enemyHpTransitions"][0]["enemyDamageEvents"][0]["creditedDamage"] = 4
        with self.assertRaisesRegex(ValueError, "event credit"):
            _audit_reward_ledger(forged, metrics,
                                 final_outcome="unresolved", final_value=reward)

    def test_damage_then_healing_in_one_action_preserves_gross_damage(self):
        enemy = {"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 10}
        event = {"combatId": 1, "monsterId": "MONSTER.TEST",
                 "unblockedDamage": 5, "overkillDamage": 0, "creditedDamage": 5}
        provenance, metrics = _one_step_ledger([enemy], [enemy], [event], 5)
        summary = _audit_reward_ledger(provenance, metrics,
                                       final_outcome="unresolved",
                                       final_value=provenance["rewardAudits"][0]["Reward"])
        self.assertEqual(summary["totalEnemyHpLost"], 5)

    def test_same_combat_id_cannot_change_monster_identity(self):
        before = [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 20}]
        after = [{"combatId": 1, "monsterId": "MONSTER.OTHER", "hp": 20}]
        provenance, metrics = _one_step_ledger(before, after, [], 0)
        with self.assertRaisesRegex(ValueError, "combatId changed monster identity"):
            _audit_reward_ledger(provenance, metrics,
                                 final_outcome="unresolved", final_value=-0.5)

    def test_history_slice_and_event_list_are_required(self):
        provenance, metrics = _ledger()
        provenance["enemyHpTransitions"][1]["historyStartIndex"] = 0
        with self.assertRaisesRegex(ValueError, "history indices are discontinuous"):
            _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                 final_value=provenance["rewardAudits"][-1]["Reward"])
        provenance, metrics = _ledger()
        del provenance["enemyHpTransitions"][0]["enemyDamageEvents"]
        with self.assertRaisesRegex(ValueError, "damage events exceed history slice"):
            _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                 final_value=provenance["rewardAudits"][-1]["Reward"])

    def test_nonzero_prefix_and_branch_use_actual_transitions(self):
        provenance, metrics = _ledger()
        summary = _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                       final_value=provenance["rewardAudits"][-1]["Reward"])
        self.assertEqual(summary["captures"], 2)
        self.assertEqual(summary["trajectoryInitialEnemyHp"], 20)
        self.assertEqual(summary["totalEnemyHpLost"], 12)
        self.assertEqual(summary["captureLedger"][1]["capturedPrefix"], 5)
        self.assertEqual(summary["captureLedger"][1]["branchDamage"], 7)

    def test_wrong_capture_prefix_is_rejected_at_first_difference(self):
        provenance, metrics = _ledger()
        provenance["rewardAudits"][1]["CapturedEnemyDamagePrefix"] = 4
        with self.assertRaisesRegex(ValueError, "capture 2.*prefix"):
            _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                 final_value=provenance["rewardAudits"][-1]["Reward"])

    def test_choice_samples_share_outer_capture(self):
        provenance, metrics = _ledger()
        metrics.insert(1, {"parentDecision": 0, "choiceLayer": 1})
        provenance["enemyHpTransitions"].insert(1, {
            "before": 15, "after": 15, "damage": 0,
            "historyStartIndex": 1, "historyEndIndex": 1,
            "enemyRosterBefore": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 15}],
            "enemyRosterAfter": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 15}],
            "enemyDamageEvents": [],
        })
        summary = _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                       final_value=provenance["rewardAudits"][-1]["Reward"])
        self.assertEqual(summary["captures"], 2)

    def test_win_uses_real_settled_hp_and_rejects_disagreement(self):
        provenance, metrics = _ledger(outcome="win")
        target = score_result(TerminalResult(Outcome.WIN, 80, 76, 12, 20))
        _audit_reward_ledger(provenance, metrics, final_outcome="win", final_value=target)
        broken = deepcopy(provenance)
        broken["rewardAudits"][-1]["SettledFinalHp"] = 75
        with self.assertRaisesRegex(ValueError, "settled HP"):
            _audit_reward_ledger(broken, metrics, final_outcome="win", final_value=target)

    def test_old_denominator_key_is_not_silently_accepted(self):
        provenance, metrics = _ledger()
        provenance["initialEnemyEffectiveHp"] = provenance.pop("trajectoryInitialEnemyEffectiveHp")
        with self.assertRaisesRegex(ValueError, "trajectoryInitialEnemyEffectiveHp"):
            _audit_reward_ledger(provenance, metrics, final_outcome="unresolved",
                                 final_value=provenance["rewardAudits"][-1]["Reward"])


class ActualTreeRootAuditTests(unittest.TestCase):
    def test_actual_callback_matches_saved_root_and_choice(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "root-parity.jsonl"
            observation = {"choice": {"effect": "Exhaust"}}
            action = {"Key": "choice:one"}
            raw = [{"seed": "seed", "stateKey": "root", "observation": observation,
                    "legalActions": [{"actionId": "choice:one", "payload": action}]}]
            metrics = [{"parentDecision": 0, "choiceLayer": 1}]
            serialized = json.dumps(observation, separators=(",", ":"))
            row = {"seed": "seed", "decision": 0, "choiceLayer": 1, "stateKey": "root",
                   "observationJson": serialized, "observation": observation,
                   "observationSha256": hashlib.sha256(serialized.encode()).hexdigest(),
                   "orderedActionIds": ["choice:one"], "legalActions": [action],
                   "logits": [0.25], "value": 0.5, "actualTreeEvaluator": True}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = _audit_tree_parity(path, raw, metrics)
            self.assertEqual(report["actualTreeEvaluatorRoots"], 1)
            self.assertEqual(report["actualTreeChoiceRoots"], 1)
            row["observation"]["choice"]["effect"] = "Discard"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "actual input differs"):
                _audit_tree_parity(path, raw, metrics)

    def test_outside_search_inference_cannot_count_as_tree_input(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "root-parity.jsonl"
            path.write_text('{"outsideSearch":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not an actual evaluator"):
                _audit_tree_parity(path, [{}], [{}])


class CurrentNativeProbeAuditTests(unittest.TestCase):
    def test_one_natural_unresolved_trajectory_uses_current_capture_contract(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "trajectory.jsonl"
            sample = TrainingSample("fresh-seed", "full_combat", observation(),
                                    (ActionNode("EndTurn", "end", terminal=True),),
                                    {"end": 5}, -0.4375, "unresolved")
            raw = sample.to_dict()
            raw.update({"stateKey": "root", "simulations": 5})
            reward_audit = {"TrajectoryId": "fresh-seed#1", "CaptureId": 1,
                            "CaptureBoundaryKey": "A" * 64, "Outcome": "unresolved",
                            "EntryHp": 80, "CombatFinalHp": 80, "CombatFinalMaxHp": 0,
                            "UnconditionalRelicHeal": 0, "WoundedRelicHeal": 0,
                            "WoundedHpPercent": 0, "AppliedPostCombatHeal": 0,
                            "SettledFinalHp": 80, "EnemyHpLost": 5, "EnemyHpTotal": 20,
                            "TrajectoryInitialEnemyHp": 20,
                            "CapturedEnemyDamagePrefix": 0, "TotalEnemyHpLost": 5,
                            "EnemyDamageProgress": 0.25, "Reward": -0.4375}
            assemblies = {}
            labels = (("NativeWorker", "nativeWorker"),
                      ("Search", "search"), ("CombatSolver", "combatSolver"))
            worker_lines = []
            for index, (label, field) in enumerate(labels, 1):
                identity = {"path": str(root / f"{label}.dll"),
                            "mvid": f"{index}" * 8 + "-1111-1111-1111-111111111111",
                            "sha256": str(index) * 64}
                assemblies[field] = identity
                worker_lines.append(f"SLAY_WORKER_ASSEMBLY label={label} path={identity['path']} "
                                    f"mvid={identity['mvid']} sha256={identity['sha256']}")
            raw["provenance"] = {
                "searchSemanticsVersion": SEARCH_SEMANTICS_VERSION,
                "rewardLedgerVersion": REWARD_LEDGER_VERSION, "seed": "fresh-seed",
                "encounter": "CULTISTS_NORMAL", "regressionOnly": False,
                "choiceFixture": False, "forcedFixtureCard": None,
                "generatedDeck": None, "startProvenance": None,
                "requestedSearchMode": "pure-mcts", "searchMode": "pure-mcts",
                "maxSimulations": None, "budgetMilliseconds": 1000,
                "maxDecisions": 1, "modelLoadStatus": "pure-mcts:no-model-configured",
                "modelScored": 0, "modelUsed": 0, "modelFallbacks": 0,
                "terminal": False, "entryHp": 80, "playerHp": 80,
                "trajectoryInitialEnemyEffectiveHp": 20, "enemyDamageLost": 5,
                "enemyHpTransitions": [{
                    "before": 20, "after": 15, "damage": 5,
                    "historyStartIndex": 0, "historyEndIndex": 1,
                    "enemyRosterBefore": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 20}],
                    "enemyRosterAfter": [{"combatId": 1, "monsterId": "MONSTER.TEST", "hp": 15}],
                    "enemyDamageEvents": [{"combatId": 1, "monsterId": "MONSTER.TEST",
                                           "unblockedDamage": 5, "overkillDamage": 0,
                                           "creditedDamage": 5}],
                }],
                "rewardAudits": [reward_audit],
                "decisionMetrics": [{"parentDecision": 0, "choiceLayer": 0,
                                     "selectedActionId": "end", "stateKey": "root",
                                     "simulations": 5, "elapsedMilliseconds": 1000.5,
                                     "maxSimulations": None, "budgetMilliseconds": 1000,
                                     "searchMode": "pure-mcts", "networkPriorCalls": 0,
                                     "networkValueCalls": 0, "networkFallbacks": 0,
                                     "networkFallbackReason": None}],
                "assemblies": assemblies,
            }
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            path.with_suffix(".worker.stdout.txt").write_text(
                "\n".join([*worker_lines, f"SLAY_WORKER_EXPORT_OUT={path.resolve()}"]) + "\n",
                encoding="utf-8")
            path.with_suffix(".worker.stderr.txt").write_text("", encoding="utf-8")
            expected = {"regressionOnly": False, "forceCard": None,
                        "requestedSearchMode": "pure-mcts", "maxSimulations": None,
                        "budgetMilliseconds": 1000, "maxDecisions": 1,
                        "seed": "fresh-seed", "encounter": "CULTISTS_NORMAL",
                        "modelSha256": None, "rootParityOutput": None}
            result = audit_probe(path, expected=expected, verify_current_assembly=False)
            self.assertEqual(result["trajectoryInitialEnemyEffectiveHp"], 20)
            self.assertEqual(result["rewardLedger"]["captureLedger"][0]["branchDamage"], 5)
            del raw["provenance"]["rewardLedgerVersion"]
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "native provenance/reward ledger version"):
                audit_probe(path, expected=expected, verify_current_assembly=False)
            raw["provenance"]["rewardLedgerVersion"] = REWARD_LEDGER_VERSION
            raw["provenance"]["regressionOnly"] = True
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "regression-only"):
                audit_probe(path, expected=expected, verify_current_assembly=False)


if __name__ == "__main__":
    unittest.main()
