"""Contract tests; synthetic frames test routing, never claim native rule parity."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

from parity.semantic import (
    ActionKey, BoundAction, ParityMismatch, Projection, SimulatorCatalog,
    UnsupportedSemanticState, compare_public_state, model_entry,
    native_request_for_candidate, native_request_for_simulator_action,
    pair_actions, project_native, project_simulator,
)


def native_frame():
    return {
        "revision": 8, "status": "ready", "screen": "combat",
        "actOrder": ["OVERGROWTH", "HIVE", "GLORY"],
        "player": {"hp": 64, "maxHp": 80, "gold": 99, "act": 1, "floor": 2,
                   "totalFloor": 2, "combatTurn": 1, "block": 0, "energy": 3},
        "entities": [
            {"id": "hand-b", "kind": "card", "pile": "hand", "slotIndex": 1,
             "modelId": "CARD.STRIKE_IRONCLAD", "upgradeLevel": 0, "cost": 1},
            {"id": "hand-a", "kind": "card", "pile": "hand", "slotIndex": 0,
             "modelId": "CARD.STRIKE_IRONCLAD", "upgradeLevel": 0, "cost": 1},
            {"id": "enemy", "kind": "enemy", "modelId": "MONSTER.NIBBIT",
             "hp": 40, "maxHp": 40, "block": 0, "enemyOrderIndex": 0},
            {"id": "deck", "kind": "card", "pile": "deck",
             "modelId": "CARD.STRIKE_IRONCLAD", "upgradeLevel": 0, "cost": 1},
            {"id": "relic", "kind": "relic", "modelId": "RELIC.BURNING_BLOOD"},
        ],
        "actions": [
            {"id": "a9", "kind": "play", "entityId": "hand-b", "targetId": "enemy"},
            {"id": "a2", "kind": "endTurn"},
            {"id": "a7", "kind": "play", "entityId": "hand-a", "targetId": "enemy"},
        ],
    }


def simulator_projection(native):
    enemy = (0, None, "NIBBIT", 40, 40, 0)
    return Projection("simulator", "combat", deepcopy(native.public_state), (
        BoundAction(ActionKey("play", ((0, "STRIKE_IRONCLAD", 0, 1), enemy)), (0, 0, 0, 101)),
        BoundAction(ActionKey("play", ((1, "STRIKE_IRONCLAD", 0, 1), enemy)), (0, 1, 0, 117)),
        BoundAction(ActionKey("end_turn"), (1, 0, 0, 0)),
    ))


class SemanticContractTests(unittest.TestCase):
    def test_duplicate_cards_match_public_hand_slot_not_array_position(self):
        native = project_native(native_frame())
        simulator = simulator_projection(native)
        self.assertEqual(pair_actions(simulator, native), {
            (0, 0, 0, 101): "a7", (0, 1, 0, 117): "a9", (1, 0, 0, 0): "a2"})
        request = native_request_for_simulator_action(simulator, native, (0, 1, 0, 117))
        self.assertEqual(request, {"revision": 8, "actionId": "a9"})
        self.assertEqual(native_request_for_candidate(simulator, native, 0),
                         {"revision": 8, "actionId": "a7"})
        with self.assertRaisesRegex(UnsupportedSemanticState, "out of range"):
            native_request_for_candidate(simulator, native, -1)

    def test_reordering_entities_and_actions_does_not_change_semantics(self):
        frame = native_frame()
        before = project_native(frame)
        frame["entities"].reverse()
        frame["actions"].reverse()
        after = project_native(frame)
        self.assertEqual(before.public_state, after.public_state)
        self.assertEqual(before.by_key(), after.by_key())

    def test_only_current_biome_is_projected(self):
        frame = native_frame()
        before = project_native(frame)
        frame["actOrder"][1:] = ["OTHER_FUTURE_ACT", "OTHER_FUTURE_ACT"]
        self.assertEqual(before.public_state, project_native(frame).public_state)
        frame["actOrder"][0] = "UNDERDOCKS"
        self.assertEqual(project_native(frame).public_state["act_type"], "UNDERDOCKS")

    def test_transport_ids_and_localized_labels_are_not_semantics(self):
        frame = native_frame()
        before = project_native(frame)
        for entity in frame["entities"]:
            entity["id"] = "changed-" + entity["id"]
            entity["name"] = "任意显示文字"
        for action in frame["actions"]:
            for field in ("entityId", "targetId"):
                if field in action:
                    action[field] = "changed-" + action[field]
            action["id"] = "changed-" + action["id"]
            action["label"] = "irrelevant English label"
        after = project_native(frame)
        self.assertEqual(before.public_state, after.public_state)
        self.assertEqual(before.by_key().keys(), after.by_key().keys())

    def test_unrelated_hidden_payload_is_not_projected(self):
        frame = native_frame()
        before = project_native(frame)
        frame["rngState"] = [91, 42]
        frame["hiddenDrawOrder"] = ["future-one", "future-two"]
        after = project_native(frame)
        self.assertEqual(before.public_state, after.public_state)
        self.assertEqual(before.by_key(), after.by_key())

    def test_missing_hand_slot_is_unsupported_even_when_only_one_card_matches(self):
        frame = native_frame()
        del frame["entities"][0]["slotIndex"]
        with self.assertRaisesRegex(UnsupportedSemanticState, "missing slotIndex"):
            project_native(frame)

    def test_duplicate_enemy_order_is_rejected(self):
        frame = native_frame()
        second = deepcopy(frame["entities"][2])
        second["id"] = "second-enemy"
        second["enemyOrderIndex"] = 0
        frame["entities"].append(second)
        with self.assertRaisesRegex(UnsupportedSemanticState, "ambiguous_target"):
            project_native(frame)

    def test_different_hp_does_not_hide_multienemy_position_mismatch(self):
        frame = native_frame()
        second = deepcopy(frame["entities"][2])
        second.update(id="second-enemy", hp=31, enemyOrderIndex=1)
        frame["entities"].append(second)
        before = project_native(frame)
        frame["entities"][2]["enemyOrderIndex"] = 1
        second["enemyOrderIndex"] = 0
        after = project_native(frame)
        self.assertNotEqual(before.public_state["enemies"], after.public_state["enemies"])
        self.assertNotEqual(before.by_key().keys(), after.by_key().keys())

    def test_enemy_position_is_required_even_for_one_enemy(self):
        frame = native_frame()
        del frame["entities"][2]["enemyOrderIndex"]
        with self.assertRaisesRegex(UnsupportedSemanticState, "missing enemyOrderIndex"):
            project_native(frame)

    def test_identical_enemies_remain_distinct_by_public_order(self):
        frame = native_frame()
        second = deepcopy(frame["entities"][2])
        second.update(id="second-enemy", enemyOrderIndex=1)
        frame["entities"].append(second)
        frame["actions"].append({"id": "other-target", "kind": "play", "entityId": "hand-a", "targetId": "second-enemy"})
        projection = project_native(frame)
        targeted = [a for a in projection.actions if a.key.kind == "play" and a.key.args[0][0] == 0]
        self.assertEqual({a.key.args[1][0] for a in targeted}, {0, 1})

    def test_same_action_count_different_semantics_fails(self):
        native = project_native(native_frame())
        simulator = simulator_projection(native)
        simulator.actions = (BoundAction(ActionKey("play", ((0, "BASH", 0, 2),
                             (0, None, "NIBBIT", 40, 40, 0))), (0, 0, 0, 101)), *simulator.actions[1:])
        with self.assertRaisesRegex(ParityMismatch, "legal actions differ"):
            pair_actions(simulator, native)

    def test_state_difference_prevents_dispatch_even_if_actions_match(self):
        native = project_native(native_frame())
        simulator = simulator_projection(native)
        simulator.public_state["hp"] = 63
        self.assertEqual(compare_public_state(simulator, native)["hp"], {"simulator": 63, "native": 64})
        with self.assertRaisesRegex(ParityMismatch, "public state differs"):
            native_request_for_simulator_action(simulator, native, (1, 0, 0, 0))

    def test_unknown_legal_action_is_not_silently_dropped(self):
        frame = native_frame()
        frame["actions"].append({"id": "potion", "kind": "openPotion"})
        with self.assertRaisesRegex(UnsupportedSemanticState, "unsupported legal action"):
            project_native(frame)

    def test_neow_uses_offered_relic_id_and_rejects_missing_metadata(self):
        frame = native_frame()
        frame.update(screen="NEventRoom", surfaceModelId="EVENT.NEOW", actions=[
            {"id": "choice", "kind": "event", "optionModelId": "RELIC.BOOMING_CONCH"}])
        self.assertEqual(project_native(frame).actions[0].key, ActionKey("neow_relic", ("BOOMING_CONCH",)))
        del frame["actions"][0]["optionModelId"]
        with self.assertRaises(UnsupportedSemanticState):
            project_native(frame)

    def test_neow_proceed_requires_explicit_native_flag(self):
        frame = native_frame()
        frame.update(screen="NEventRoom", surfaceModelId="EVENT.NEOW", actions=[
            {"id": "continue", "kind": "event", "optionIsProceed": True}])
        self.assertEqual(project_native(frame).actions[0].key, ActionKey("neow_proceed"))
        frame["actions"][0]["optionIsProceed"] = False
        frame["actions"][0]["label"] = "Proceed"
        with self.assertRaises(UnsupportedSemanticState):
            project_native(frame)

    def test_map_uses_coordinates_and_records_ui_navigation(self):
        frame = native_frame()
        frame.update(screen="map", map={"nodes": [{"x": 5, "y": 1, "available": True}]}, actions=[
            {"id": "go", "kind": "map", "x": 5, "y": 1}, {"id": "back", "kind": "back"}])
        projection = project_native(frame)
        self.assertEqual(projection.actions[0].key, ActionKey("move", (5, 1)))
        self.assertEqual(projection.ignored_navigation, ("back",))

    def test_model_ids_are_strict_and_do_not_accept_titles_or_wrong_categories(self):
        for value in ("Strike", "StrikeIronclad", "RELIC.STRIKE_IRONCLAD", None):
            with self.assertRaises(UnsupportedSemanticState):
                model_entry(value, "CARD")

    def test_busy_frames_and_unlisted_policy_actions_are_rejected(self):
        frame = native_frame()
        frame["status"] = "busy"
        with self.assertRaisesRegex(UnsupportedSemanticState, "not ready"):
            project_native(frame)
        native = project_native(native_frame())
        with self.assertRaisesRegex(UnsupportedSemanticState, "not currently legal"):
            native_request_for_simulator_action(simulator_projection(native), native, (0, 5, 0, 0))


class SimulatorAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim/build"))
        try:
            import sts2_sim
        except ImportError as exc:
            raise unittest.SkipTest(f"built simulator unavailable for this Python: {exc}")
        cls.sim = sts2_sim
        cls.catalog = SimulatorCatalog.from_repo()

    def test_concrete_segment_ids_are_shared_by_public_view_and_target_projection(self):
        rc = self.sim.RunContext()
        rc.init_seed("PARITY0001", 10)
        for _ in range(12):
            if rc.screen == self.sim.RunScreen.COMBAT:
                break
            projection = project_simulator(rc, self.sim, self.catalog)
            choice = next((a for a in projection.actions
                           if a.key == ActionKey("neow_relic", ("GOLDEN_PEARL",))), projection.actions[0])
            rc.step(*choice.handle)
        self.assertEqual(rc.screen, self.sim.RunScreen.COMBAT)
        bludgeon = next(i for i in self.catalog.cards if self.catalog.card(i) == "BLUDGEON")
        rc.battle.init(int(self.sim.Encounter.SETUP_DECIMILLIPEDE_ELITE), 111,
                       [bludgeon] * 10, [False] * 10, 10, 999, 999)
        expected = ["DECIMILLIPEDE_SEGMENT_" + suffix for suffix in ("FRONT", "MIDDLE", "BACK")]
        facts = self.sim.public_model_state(rc)
        self.assertEqual([e["modelId"] for e in facts["enemies"]], ["MONSTER." + x for x in expected])
        projection = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual([e[2] for e in projection.public_state["enemies"]], expected)

        # Synthetic list-rank change checks routing only, not a native behavior
        # claim: the stable slot/model identity must survive a changed rank.
        class Override:
            def __init__(self, target, **values):
                self.target = target
                self.__dict__.update(values)

            def __getattr__(self, name):
                return getattr(self.target, name)

        positions = [dict(p) for p in rc.battle.monster_positions]
        for row, rank in zip(positions, (2, 0, 1)):
            row["enemy_order_index"] = rank
        changed = Override(rc, battle=Override(rc.battle, monster_positions=positions))
        reordered = project_simulator(changed, self.sim, self.catalog)
        self.assertEqual([e[2] for e in reordered.public_state["enemies"]], [expected[1], expected[2], expected[0]])

    def test_generated_card_mapping_and_actual_initial_legal_actions(self):
        rc = self.sim.RunContext()
        rc.init_seed("PARITY0001", 10)
        projection = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual(projection.screen, "neow")
        self.assertEqual({a.handle for a in projection.actions}, {tuple(a) for a in rc.legal_actions()})
        self.assertEqual([a.key.args[0] for a in projection.actions],
                         [self.sim.relic_info(r)[0] for r in rc.event_relics])
        self.assertIn(("ASCENDERS_BANE", 0), projection.public_state["deck"])

    def test_actual_map_actions_are_node_coordinates(self):
        rc = self.sim.RunContext()
        rc.init_seed("PARITY0001", 10)
        initial = project_simulator(rc, self.sim, self.catalog)
        pearl = next(a for a in initial.actions if a.key == ActionKey("neow_relic", ("GOLDEN_PEARL",)))
        rc.step(*pearl.handle)
        proceeding = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual(rc.screen, self.sim.RunScreen.EVENT)
        self.assertEqual([a.key for a in proceeding.actions], [ActionKey("neow_proceed")])
        rc.step(*proceeding.actions[0].handle)
        projection = project_simulator(rc, self.sim, self.catalog)
        nodes = {n[0]: (n[2], n[3]) for n in rc.map_nodes()}
        for action in projection.actions:
            self.assertEqual(action.key.args, nodes[action.handle[1]])

    def test_actual_combat_candidates_keep_policy_card_and_target_references(self):
        try:
            import numpy  # noqa: F401: the pybind observation export requires it
        except ImportError:
            self.skipTest("numpy unavailable in this Python")
        rc = self.sim.RunContext()
        rc.init_seed("PARITY0001", 10)
        initial = project_simulator(rc, self.sim, self.catalog)
        rc.step(*next(a.handle for a in initial.actions if a.key == ActionKey("neow_relic", ("GOLDEN_PEARL",))))
        proceeding = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual([a.key for a in proceeding.actions], [ActionKey("neow_proceed")])
        rc.step(*proceeding.actions[0].handle)
        rc.step(*project_simulator(rc, self.sim, self.catalog).actions[0].handle)
        projection = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual(projection.screen, "combat")
        self.assertEqual({a.handle for a in projection.actions}, {tuple(a) for a in rc.battle.legal_actions()})
        for action in projection.actions:
            if action.key.kind == "play":
                hand_slot = action.handle[1]
                self.assertEqual(action.key.args[0][0], hand_slot)
                self.assertEqual(action.key.args[0][1], self.catalog.card(rc.battle.hand[hand_slot][0]))

        for seed in (1, 2):
            clone = rc.clone()
            clone.battle.resample_hidden(seed)
            hidden_changed = project_simulator(clone, self.sim, self.catalog)
            self.assertEqual(projection.public_state, hidden_changed.public_state)
            self.assertEqual(projection.by_key(), hidden_changed.by_key())

        # When energy runs out, unplayable cards still need their public costs;
        # the adapter must not rely only on the remaining legal-play candidates.
        for _ in range(3):
            current = project_simulator(rc, self.sim, self.catalog)
            strike = next(a for a in current.actions
                          if a.key.kind == "play" and a.key.args[0][1] == "STRIKE_IRONCLAD")
            rc.step_combat(*strike.handle)
        no_energy = project_simulator(rc, self.sim, self.catalog)
        self.assertEqual(no_energy.public_state["energy"], 0)
        self.assertEqual(len(no_energy.public_state["hand"]), len(rc.battle.hand))
        self.assertEqual([a.key.kind for a in no_energy.actions], ["end_turn"])


if __name__ == "__main__":
    unittest.main()
