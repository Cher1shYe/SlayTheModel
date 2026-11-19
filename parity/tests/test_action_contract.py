"""Decision transport tests. Synthetic inputs are not DLL behavior evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

from parity.action_contract import native_extra_key, native_navigation_request, potion_name
from parity.event_contract import simulator_event_option
from parity.semantic import ActionKey, UnsupportedSemanticState, project_native
from parity.compare import run_comparison
from test_semantic import native_frame, simulator_projection


def action(kind, **metadata):
    return {"id": "bound-action", "kind": kind, "metadata": metadata}


def frame_for(screen, actions):
    frame = native_frame()
    frame.update(screen=screen, actions=actions)
    frame["player"]["combatTurn"] = 0
    frame["entities"] = [e for e in frame["entities"] if e.get("pile") == "deck" or e["kind"] == "relic"]
    return frame


class ExpandedActionContractTests(unittest.TestCase):
    def test_rewards_use_model_metadata_and_visible_amount(self):
        frame = frame_for("NRewardsScreen", [
            action("reward", rewardType="GoldReward", ordinal=0, amount=23, recovered=False),
            {**action("reward", rewardType="PotionReward", ordinal=0, modelId="POTION.FIRE_POTION"), "id": "potion"},
            {**action("reward", rewardType="CardReward", ordinal=0), "id": "cards"},
            {**action("button", role="proceed"), "id": "leave"},
        ])
        before = project_native(frame)
        self.assertEqual(set(before.by_key()), {
            ActionKey("take_gold", (False, 23, 0)), ActionKey("take_potion", ("FIRE_POTION", 0)),
            ActionKey("open_card_reward", (0,)), ActionKey("leave_rewards")})
        for a in frame["actions"]:
            a["label"] = "与原语言完全不同的文字"
            a["hiddenRewardCards"] = ["CARD.UNREVEALED_FUTURE"]
        self.assertEqual(before.by_key(), project_native(frame).by_key())

    def test_rewards_missing_type_is_rejected_not_inferred_from_text(self):
        frame = frame_for("NRewardsScreen", [{"id": "reward", "kind": "reward", "label": "23 Gold"}])
        with self.assertRaisesRegex(UnsupportedSemanticState, "ordinal"):
            project_native(frame)

    def test_special_card_and_removal_rewards_preserve_separate_decisions(self):
        frame = frame_for("NRewardsScreen", [
            action("reward", rewardType="SpecialCardReward", ordinal=0, modelId="CARD.LANTERN_KEY", upgradeLevel=0),
            {**action("reward", rewardType="CardRemovalReward", ordinal=0), "id":"remove0"},
            {**action("reward", rewardType="CardRemovalReward", ordinal=1), "id":"remove1"},
        ])
        self.assertEqual(set(project_native(frame).by_key()), {
            ActionKey("take_special_card", ("LANTERN_KEY", 0, 0)),
            ActionKey("open_card_removal_reward", (0,)),
            ActionKey("open_card_removal_reward", (1,)),
        })

    def test_recovered_gold_and_multiple_reward_slots_are_distinct(self):
        normal = native_extra_key({}, "rewards", action("reward", rewardType="GoldReward", ordinal=0, amount=30), {})
        stolen = native_extra_key({}, "rewards", action("reward", rewardType="GoldReward", ordinal=1, amount=30, recovered=True), {})
        self.assertNotEqual(normal, stolen)
        self.assertNotEqual(native_extra_key({}, "rewards", action("reward", rewardType="CardReward", ordinal=0), {}),
                            native_extra_key({}, "rewards", action("reward", rewardType="CardReward", ordinal=1), {}))

    def test_potion_binding_uses_physical_hole_preserving_slot_and_target(self):
        frame = native_frame()
        frame["actions"] = [dict(action("use_potion", slot=2, modelId="POTION.FIRE_POTION"), targetId="enemy"),
                            dict(action("discard_potion", slot=2, modelId="POTION.FIRE_POTION"), id="discard")]
        keys = list(project_native(frame).by_key())
        self.assertEqual(keys[0], ActionKey("use_potion", (2, "FIRE_POTION", (0, None, "NIBBIT", 40, 40, 0))))
        self.assertEqual(keys[1], ActionKey("discard_potion", (2, "FIRE_POTION")))
        frame["actions"][0]["targetId"] = "unidentified-target"
        with self.assertRaisesRegex(UnsupportedSemanticState, "unsupported target"):
            project_native(frame)

    def test_potion_model_slug_is_native_not_cpp_acronym_spelling(self):
        values = json.loads((Path(__file__).resolve().parents[2] / "sim/content/potions.json").read_text())
        ids = {v["id"]: i + 1 for i, v in enumerate(values)}
        self.assertEqual(potion_name(ids["FairyInABottle"]), "FAIRY_IN_A_BOTTLE")
        self.assertEqual(potion_name(ids["ShipInABottle"]), "SHIP_IN_A_BOTTLE")

    def test_revival_requires_explicit_public_evidence(self):
        frame = native_frame()
        enemy = next(e for e in frame["entities"] if e["kind"] == "enemy")
        enemy.update(hp=0, modelId="MONSTER.TEST_SUBJECT")
        frame["actions"] = [{"id": "end", "kind": "endTurn"}]
        with self.assertRaisesRegex(UnsupportedSemanticState, "dead/reviving"):
            project_native(frame)
        frame["publicObservation"] = {"enemies": [{"transportId": "enemy", "reviving": True,
                                                    "alive": False, "hittable": False}]}
        projection = project_native(frame)
        self.assertEqual(projection.public_state["enemies"], ((0, None, "TEST_SUBJECT", 0, 40, 0, "reviving"),))
        self.assertEqual(set(projection.by_key()), {ActionKey("end_turn")})

    def test_selection_preserves_select_deselect_and_confirm(self):
        frame = frame_for("card_selection", [])
        frame["choices"] = [
            {"index": 0, "selected": False, "card": {"id": "a", "modelId": "CARD.STRIKE_IRONCLAD", "upgradeLevel": 0}},
            {"index": 1, "selected": True, "card": {"id": "b", "modelId": "CARD.STRIKE_IRONCLAD", "upgradeLevel": 0}},
        ]
        frame["actions"] = [dict(action("select_card"), entityId="a"),
                            dict(action("select_card"), entityId="b", id="deselect"),
                            dict(action("native_button", role="confirm_selection"), id="confirm")]
        self.assertEqual(set(project_native(frame).by_key()), {
            ActionKey("select_card", ("STRIKE_IRONCLAD", 0, 0)),
            ActionKey("deselect_card", ("STRIKE_IRONCLAD", 0, 0)), ActionKey("confirm_selection")})
        frame["actions"].reverse()
        self.assertEqual(len(project_native(frame).actions), 3)

    def test_reward_duplicate_choices_keep_public_occurrence(self):
        frame = frame_for("card_reward", [])
        frame["choices"] = [{"index": i, "card": {"id": str(i), "modelId": "CARD.ANGER", "upgradeLevel": 0}} for i in range(2)]
        frame["actions"] = [dict(action("choose_reward_card"), entityId=str(i), id=f"take-{i}") for i in range(2)]
        self.assertEqual(set(project_native(frame).by_key()), {
            ActionKey("take_card", ("ANGER", 0, 0)), ActionKey("take_card", ("ANGER", 0, 1))})

    def test_preview_cancel_and_selector_close_are_separate(self):
        cancel = native_extra_key({}, "card_selection", action("native_button", role="cancel_preview"), {})
        close = native_extra_key({}, "card_selection", action("native_button", role="cancel_selection"), {})
        self.assertEqual(cancel, ActionKey("cancel_preview"))
        self.assertEqual(close, ActionKey("cancel_selection"))

    def test_card_reward_alternatives_use_option_id_and_reject_unknown(self):
        for ident, key in (("Skip", "skip_card"), ("SACRIFICE", "sacrifice_card_reward"), ("REROLL", "reroll_card_reward")):
            self.assertEqual(native_extra_key({}, "card_reward", action("native_button", role="card_reward_alternative", optionId=ident), {}), ActionKey(key))
        with self.assertRaisesRegex(UnsupportedSemanticState, "alternative"):
            native_extra_key({}, "card_reward", action("native_button", role="card_reward_alternative", optionId="skip translated title"), {})

    def test_rest_uses_native_option_id(self):
        for option in ("HEAL", "SMITH", "LIFT", "DIG", "CLONE", "HATCH", "KINDLE"):
            self.assertEqual(native_extra_key({}, "rest", action("button", role="rest", optionId=option), {}), ActionKey("rest", (option,)))

    def test_shop_purchase_contains_model_and_current_price(self):
        buy = action("buy", modelId="RELIC.BAG_OF_PREPARATION", cost=151, index=0)
        self.assertEqual(native_extra_key({}, "shop", buy, {}), ActionKey("buy_relic", ("BAG_OF_PREPARATION", 151)))
        buy["metadata"]["index"] = 17  # UI ordering is not the purchase identity.
        self.assertEqual(native_extra_key({}, "shop", buy, {}).args, ("BAG_OF_PREPARATION", 151))
        self.assertEqual(native_extra_key({}, "shop", action("buy", modelId="CARD_REMOVAL", cost=75), {}),
                         ActionKey("open_remove_card", (75,)))
        self.assertEqual(native_extra_key({}, "shop", action("leave_shop", role="leave_shop"), {}), ActionKey("leave_shop"))

    def test_treasure_open_claim_and_leave_are_three_decisions(self):
        frame = {"entities": [{"id": "visible-relic", "modelId": "RELIC.VAJRA"}]}
        claim = dict(action("take_relic"), entityId="visible-relic")
        self.assertEqual(native_extra_key(frame, "treasure", action("button", role="open_treasure"), {}), ActionKey("open_treasure"))
        self.assertEqual(native_extra_key(frame, "treasure", claim, {}), ActionKey("take_treasure_relic", ("VAJRA",)))
        self.assertEqual(native_extra_key(frame, "treasure", action("button", role="proceed", isSkip=True), {}), ActionKey("leave_treasure"))

    def test_event_option_uses_id_and_exact_source_key(self):
        a = action("event", eventId="EVENT.AROMA_OF_CHAOS", pageKey="AROMA_OF_CHAOS.pages.INITIAL.description",
                   optionKey="AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO")
        a["choiceIndex"] = 0
        key = native_extra_key({}, "event", a, {})
        self.assertEqual(key, ActionKey("event_option", ("AROMA_OF_CHAOS", "AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO")))
        a["metadata"]["optionKey"] = "AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL"
        self.assertNotEqual(key, native_extra_key({}, "event", a, {}))
        del a["metadata"]["pageKey"]
        with self.assertRaisesRegex(UnsupportedSemanticState, "page/option"):
            native_extra_key({}, "event", a, {})

    def test_event_manifest_never_reuses_initial_keys_for_unknown_page(self):
        rc = SimpleNamespace(event_name="AROMA_OF_CHAOS", event_page=0, event_choices=2)
        self.assertEqual(simulator_event_option(rc, 1), "AROMA_OF_CHAOS.pages.INITIAL.options.MAINTAIN_CONTROL")
        rc.event_page = 17
        with self.assertRaisesRegex(UnsupportedSemanticState, "no audited"):
            simulator_event_option(rc, 1)
        rc.event_name, rc.event_page = "THE_LANTERN_KEY", 1
        self.assertEqual(simulator_event_option(rc, 0), "THE_LANTERN_KEY.pages.KEEP_THE_KEY.options.FIGHT")

    def test_crystal_action_keeps_tool_choice_with_public_coordinate(self):
        small = native_extra_key({}, "crystal_sphere", dict(action("reveal_cell", tool="Small"), x=3, y=7), {})
        big = native_extra_key({}, "crystal_sphere", dict(action("reveal_cell", tool="Big"), x=3, y=7), {})
        self.assertEqual(small, ActionKey("reveal_cell", ("Small", 3, 7)))
        self.assertNotEqual(small, big)

    def test_only_declared_transport_navigation_can_auto_open(self):
        frame = frame_for("NMerchantRoom", [action("button", role="open_shop", transportOnly=True)])
        self.assertEqual(native_navigation_request(frame), {"revision": 8, "actionId": "bound-action"})
        frame["actions"][0]["metadata"]["transportOnly"] = False
        self.assertIsNone(native_navigation_request(frame))
        frame["actions"] = [action("reward", rewardType="CardReward", ordinal=0)]
        self.assertIsNone(native_navigation_request(frame))

    def test_transport_is_logged_and_does_not_step_simulator(self):
        closed = frame_for("NMerchantRoom", [action("button", role="open_shop", transportOnly=True)])
        ready = native_frame()
        ready["revision"] = 9
        simulated = simulator_projection(project_native(ready))
        class Client:
            def __init__(self): self.posts = []
            def request(self, method, path, payload): self.posts.append((method, path, payload)); return {"revision": 9}
        client = Client()
        with tempfile.TemporaryDirectory() as directory, patch("parity.compare.wait_for_ready", side_effect=[closed, ready]), \
             patch("parity.compare.project_simulator", return_value=simulated):
            result = run_comparison(client, object(), object(), Path(directory), steps=0)
            self.assertEqual(result["status"], "limit_reached")
            self.assertEqual(result["actions_submitted"], 0)
            self.assertEqual(len(client.posts), 1)
            transport = json.loads((Path(directory) / "decision-0000-transport.json").read_text())
            self.assertFalse(transport["game_decision"])
