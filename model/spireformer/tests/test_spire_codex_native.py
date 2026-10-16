from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "spireformer"
    / "spire_codex_native.py"
)
SPEC = importlib.util.spec_from_file_location("spire_codex_native_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
spire_codex_native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spire_codex_native
SPEC.loader.exec_module(spire_codex_native)


class SpireCodexNativeReplayTests(unittest.TestCase):
    def _write_proof(self, root: Path) -> tuple[Path, Path]:
        source = {
            "build_id": "v0.111.0",
            "combat_index": 0,
            "episode_id": "episode-a",
            "mod_version": "v1.2.1",
            "run_hash": "run-a",
        }
        plan = {
            "format_version": spire_codex_native.PLAN_VERSION,
            "replay_only_hidden_state": True,
            "source": source,
            "run": {
                "ascension": 7,
                "character": "IRONCLAD",
                "seed": "REPLAY-ONLY",
            },
            "combat": {
                "encounter": "CULTISTS_NORMAL",
                "run_snapshot": {
                    "act": 1,
                    "ascension": 7,
                    "floor": 1,
                    "room": {"kind": "combat", "room_type": "monster"},
                },
                "actions": [{"source_sequence": 19}],
            },
        }
        plan_path = root / "run-a-combat-0.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        plan_sha256 = sha256(plan_path.read_bytes()).hexdigest()
        selected = {
            "kind": "end_turn",
            "actor_player_id": 1,
            "combat_card_index": None,
        }
        report = {
            "formatVersion": spire_codex_native.REPORT_VERSION,
            "source": source,
            "planSha256": plan_sha256,
            "error": None,
            "nativeVictory": True,
            "replayOnlyStateExcludedFromDecisions": True,
            "matchedDecisions": 1,
            "decisions": [
                {
                    "sourceSequence": 19,
                    "nativeObservation": {"schema_version": 5, "players": []},
                    "nativeLegalActions": [selected],
                    "nativeSelectedAction": selected,
                }
            ],
        }
        report_path = root / "run-a-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return plan_path, report_path

    def test_valid_proof_emits_only_native_policy_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_proof(root)

            replays = spire_codex_native.load_validated_native_replays(root)

        self.assertEqual(1, len(replays))
        self.assertEqual("IRONCLAD", replays[0]["character"])
        step = replays[0]["steps"][0]
        self.assertEqual("combat", step["domain"])
        self.assertEqual(0, step["selected_action_index"])
        self.assertIsNone(step["selected_action"])
        self.assertNotIn("seed", step)
        self.assertNotIn("seed", step["context"]["run_context"])

    def test_tampered_plan_is_rejected_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan_path, _ = self._write_proof(root)
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                spire_codex_native.load_validated_native_replays(root)

    def test_hidden_replay_state_in_policy_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, report_path = self._write_proof(root)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["decisions"][0]["nativeObservation"]["seed"] = "LEAK"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "hidden field observation.seed"):
                spire_codex_native.load_validated_native_replays(root)

    def test_sequential_proof_loads_two_combat_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            sources = []
            plans = []
            proofs = []
            for combat_index, sequence in enumerate((19, 41)):
                source = {
                    "build_id": "v0.111.0",
                    "combat_index": combat_index,
                    "episode_id": "episode-sequential",
                    "mod_version": "v1.2.1",
                    "run_hash": "run-sequential",
                }
                selected = {
                    "kind": "end_turn",
                    "actor_player_id": 1,
                    "combat_card_index": None,
                }
                plan = {
                    "format_version": spire_codex_native.PLAN_VERSION,
                    "replay_only_hidden_state": True,
                    "source": source,
                    "run": {
                        "ascension": 7,
                        "character": "IRONCLAD",
                        "seed": "REPLAY-ONLY",
                    },
                    "combat": {
                        "encounter": f"ENCOUNTER_{combat_index}",
                        "run_snapshot": {
                            "act": 1,
                            "ascension": 7,
                            "floor": combat_index + 1,
                            "room": {"kind": "combat", "room_type": "monster"},
                        },
                        "actions": [{"source_sequence": sequence}],
                    },
                }
                proof = {
                    "sourceSequence": sequence,
                    "nativeObservation": {"schema_version": 5, "players": []},
                    "nativeLegalActions": [selected],
                    "nativeSelectedAction": selected,
                }
                path = root / f"run-sequential-combat-{combat_index}.json"
                path.write_text(json.dumps(plan), encoding="utf-8")
                sources.append(source)
                plans.append(path)
                proofs.append(proof)
            report = {
                "formatVersion": spire_codex_native.SEQUENTIAL_REPORT_VERSION,
                "firstPlanSha256": sha256(plans[0].read_bytes()).hexdigest(),
                "nextPlanSha256": sha256(plans[1].read_bytes()).hexdigest(),
                "sources": sources,
                "error": None,
                "nativeVictory": True,
                "replayOnlyStateExcludedFromDecisions": True,
                "matchedDecisions": 2,
                "combats": [
                    {"encounter": "ENCOUNTER_0", "decisions": [proofs[0]]},
                    {"encounter": "ENCOUNTER_1", "decisions": [proofs[1]]},
                ],
            }
            (root / "run-sequential-report.json").write_text(
                json.dumps(report), encoding="utf-8"
            )

            replays = spire_codex_native.load_validated_native_replays(root)

        self.assertEqual(1, len(replays))
        self.assertEqual(2, len(replays[0]["steps"]))
        self.assertEqual([0, 1], [step["segment_index"] for step in replays[0]["steps"]])
        self.assertEqual(
            ["native-combat:0", "native-combat:1"],
            [step["trajectory_group"] for step in replays[0]["steps"]],
        )


if __name__ == "__main__":
    unittest.main()
