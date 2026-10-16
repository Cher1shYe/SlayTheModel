from __future__ import annotations

from copy import deepcopy

import pytest
import torch

from spireformer.raw_features import (
    ENTITY_KINDS,
    ENTITY_NUMBERS,
    RawFeatureEncoder,
    RawFeatureSpec,
)


def _card(native_id: int, model_id: str, *, cost: int | None = 1) -> dict:
    return {
        "combat_card_index": native_id,
        "model_id": model_id,
        "energy_cost": None,
        "affliction_id": None,
        "affliction_count": 0,
        "keywords": [],
        "upgrade_level": 0,
        "enchantment_id": None,
        "enchantment_amount": None,
        "display": None if cost is None else {
            "description": None, "energy_cost": cost,
            "star_cost": None, "costs_x": False, "dynamic_values": [],
        },
    }


def _combat_observation() -> dict:
    return {
        "schema_version": 5,
        "round_number": 1,
        "current_side": "Player",
        "players": [{
            "player_id": 17, "character_id": "NECROBINDER",
            "energy": 3, "stars": 0, "turn_number": 1,
            "phase": "Play", "gold": 0, "orb_capacity": 0,
            "piles": [
                {"pile_type": "Hand", "cards": [_card(10, "CARD.STRIKE", cost=0)]},
                {"pile_type": "Draw", "cards": [
                    _card(11, "CARD.DEFEND"), _card(12, "CARD.SLIMED"),
                ]},
                {"pile_type": "Discard", "cards": [_card(13, "CARD.DEFEND")]},
            ],
            "relics": [{"model_id": "RELIC.STARTER", "display": {
                "icon_status": "Normal", "is_melted": False,
                "is_wax": False, "visible_counter": 0,
                "hover_description": "localized text",
            }}],
            "potions": [{"slot_index": 2, "model_id": "POTION.HEAL"}],
            "orbs": [],
        }],
        "creatures": [
            {"combat_id": 1, "player_id": 17, "monster_id": None,
             "current_hp": 55, "max_hp": 70, "block": 0, "powers": [
                 {"model_id": "POWER.STRENGTH", "amount": 2},
             ]},
            {"combat_id": 7, "player_id": None, "monster_id": "MONSTER.JAW_WORM",
             "current_hp": 28, "max_hp": 40, "block": 5, "powers": []},
        ],
        "enemy_intents": [{"creature_combat_id": 7, "visibility": "visible",
                           "intents": [{"kind": "Attack", "display_text": "8",
                                        "total_damage": 8, "hits": 1}]}],
        "companions": [], "active_choice": None,
        "pending_manual_actions": [],
    }


def _combat_actions() -> list[dict]:
    return [
        {"kind": "play_card", "actor_player_id": 17,
         "combat_card_index": 10, "potion_index": None,
         "target_creature_id": 7, "choice_id": None,
         "selected_combat_card_ids": None, "selected_model_ids": None,
         "option_index": None},
        {"kind": "use_potion", "actor_player_id": 17,
         "combat_card_index": None, "potion_index": 2,
         "target_creature_id": None, "choice_id": None,
         "selected_combat_card_ids": None, "selected_model_ids": None,
         "option_index": None},
        {"kind": "end_turn", "actor_player_id": 17,
         "combat_card_index": None, "potion_index": None,
         "target_creature_id": None, "choice_id": None,
         "selected_combat_card_ids": None, "selected_model_ids": None,
         "option_index": None},
    ]


def test_mcts_selector_provenance_is_not_a_feature() -> None:
    observation = _combat_observation()
    observation["active_choice"] = {
        "source": "mcts_card_choice", "min_selections": 0, "max_selections": 1,
        "can_cancel": False, "cards": [_card(10, "CARD.STRIKE")],
    }
    neutral = deepcopy(observation)
    neutral["active_choice"]["source"] = "card_selector"
    spec = RawFeatureSpec.fit([{
        "domain": "combat", "observation": observation,
        "legal_actions": _combat_actions(), "context": {},
    }])
    assert "mcts" not in str(spec.to_dict()).lower()
    encoder = RawFeatureEncoder(spec)
    assert torch.equal(encoder.encode_observation("combat", observation),
                       encoder.encode_observation("combat", neutral))


def _outside_observation() -> dict:
    return {
        "schema_version": 5, "surface": "CardGridChoice",
        "choice_context": {"context_id": "CardGrid", "state_token": "a" * 64,
                           "phase": "Selection", "min_selections": 1,
                           "max_selections": 2, "selected_count": 0,
                           "cancelable": True, "requires_confirmation": True},
        "act_index": 1, "act_floor": 2, "total_floor": 2,
        "ascension_level": 0, "room_type": "Event",
        "room_model_id": "EVENT.TEST",
        "current_map_coordinate": {"row": 2, "column": 0},
        "players": [{"player_id": 17, "character_id": "NECROBINDER",
                     "current_hp": 55, "max_hp": 70, "gold": 0,
                     "max_potion_count": 3,
                     "deck": [{"deck_index": 0, "model_id": "CARD.DEFEND",
                               "upgrade_level": 0, "enchantment_id": None,
                               "affliction_id": None},
                              {"deck_index": 1, "model_id": "CARD.DEFEND",
                               "upgrade_level": 1, "enchantment_id": None,
                               "affliction_id": None}],
                     "relics": [], "potions": []}],
        "map_points": [
            {"coordinate": {"row": 2, "column": 0}, "point_type": "Event",
             "visited": True, "children": [{"row": 3, "column": 1}]},
            {"coordinate": {"row": 3, "column": 1}, "point_type": "Monster",
             "visited": False, "children": []},
        ],
        "card_selection_options": [
            {"option_index": 0, "model_id": "CARD.DEFEND", "deck_index": 0},
            {"option_index": 1, "model_id": "CARD.DEFEND", "deck_index": 1},
        ],
    }


def _outside_actions() -> list[dict]:
    return [
        {"action_id": "set:0", "kind": "remove_card_set", "ordinal": 0,
         "target_id": None, "map_coordinate": None, "cost": None,
         "target_deck_index": None, "is_selection_template": True},
        {"action_id": "cancel:1", "kind": "cancel_selection", "ordinal": 1,
         "target_id": "cancel", "map_coordinate": None, "cost": None,
         "target_deck_index": None},
    ]


def _encoder() -> RawFeatureEncoder:
    combat = {"domain": "combat", "observation": _combat_observation(),
              "legal_actions": _combat_actions(),
              "context": {"run_context": {"act_index": 1, "act_floor": 2,
                                          "total_floor": 2, "ascension_level": 0}}}
    outside = {"domain": "outside_combat", "observation": _outside_observation(),
               "legal_actions": _outside_actions()}
    return RawFeatureEncoder(RawFeatureSpec.fit([combat, outside]))


def _number_pair(features: torch.Tensor, kind: str, field: str,
                 encoder: RawFeatureEncoder, *, tag: str | None = None) -> torch.Tensor:
    kind_index = ENTITY_KINDS.index(kind)
    matching = features[:, kind_index] == 1
    if tag is not None:
        tag_index = len(ENTITY_KINDS) + encoder.spec.tokens.index(tag)
        matching &= features[:, tag_index] == 1
    selected = features[matching]
    assert len(selected) == 1
    field_index = [name for name, _ in ENTITY_NUMBERS].index(field)
    offset = len(ENTITY_KINDS) + len(encoder.spec.tokens) + field_index * 2
    return selected[0, offset:offset + 2]


def test_spec_is_deterministic_bounded_and_round_trips() -> None:
    decision = {"domain": "combat", "observation": _combat_observation(),
                "legal_actions": _combat_actions()}
    other = {"domain": "outside_combat", "observation": _outside_observation(),
             "legal_actions": _outside_actions()}
    left = RawFeatureSpec.fit([decision, other], max_vocabulary_size=12)
    right = RawFeatureSpec.fit([other, decision], max_vocabulary_size=12)
    assert left == right
    assert len(left.tokens) <= 12
    assert left.sha256() == right.sha256()
    assert RawFeatureSpec.from_dict(left.to_dict()) == left
    with pytest.raises(ValueError, match="layout"):
        RawFeatureSpec.from_dict({**left.to_dict(), "entity_numbers": []})


def test_internal_hand_missingness_and_unordered_piles() -> None:
    encoder = _encoder()
    observation = _combat_observation()
    original = encoder.encode_observation("combat", observation)
    assert _number_pair(original, "card", "energy_cost", encoder,
                        tag="zone:Hand")[1].item() == 1
    assert _number_pair(original, "card", "energy_cost", encoder,
                        tag="zone:Hand")[0].item() == 0
    changed = deepcopy(observation)
    changed["players"][0]["piles"][1]["cards"].reverse()
    changed["players"][0]["piles"][2]["cards"].reverse()
    assert torch.equal(original, encoder.encode_observation("combat", changed))
    changed["players"][0]["piles"][0]["cards"][0]["display"] = None
    missing = encoder.encode_observation("combat", changed)
    assert _number_pair(missing, "card", "energy_cost", encoder,
                        tag="zone:Hand")[1].item() == 0
    # A card that has reached the internal Hand stays an entity even without
    # a UI or native cost projection.
    assert (missing[:, ENTITY_KINDS.index("card")] == 1).sum().item() == 4
    assert encoder.encode_actions("combat", changed, _combat_actions()).shape[0] == 3


def test_strict_allowlist_and_old_schema_masks() -> None:
    encoder = _encoder()
    observation = _combat_observation()
    decision = {"metadata": {"steam_id": "private", "seed": "secret"},
                "state_fingerprint": "a" * 64}
    run_context = {"act_index": 1, "act_floor": 2, "total_floor": 2,
                   "ascension_level": 0, "seed": "secret", "steam_name": "private"}
    baseline = encoder.encode_observation("combat", observation, run_context)
    tampered = deepcopy(observation)
    tampered["secret_rng"] = {"next_card": "CARD.WIN"}
    tampered["players"][0]["piles"][0]["cards"][0]["display"]["description"] = "未来必胜"
    tampered["players"][0]["piles"][0]["cards"][0]["display"]["dynamic_values"] = [
        {"key": "Hidden", "value": 9999},
    ]
    assert torch.equal(baseline, encoder.encode_observation("combat", tampered,
                                                            {**run_context, **decision}))
    old = deepcopy(observation)
    old["schema_version"] = 1
    old["players"][0]["relics"][0]["stack_count"] = 999
    old["players"][0]["relics"][0]["display_amount"] = 999
    old_features = encoder.encode_observation("combat", old)
    assert _number_pair(old_features, "player", "gold", encoder)[1].item() == 0
    assert _number_pair(baseline, "player", "gold", encoder)[1].item() == 1
    assert _number_pair(old_features, "relic", "visible_counter", encoder)[1].item() == 0
    invisible = deepcopy(observation)
    invisible["enemy_intents"][0]["visibility"] = "unverified"
    hidden = encoder.encode_observation("combat", invisible)
    invisible["enemy_intents"][0]["intents"][0]["total_damage"] = 999
    assert torch.equal(hidden, encoder.encode_observation("combat", invisible))


def test_native_identity_is_only_used_to_join_observed_entities() -> None:
    encoder = _encoder()
    observation = _combat_observation()
    actions = _combat_actions()
    baseline = encoder.encode_actions("combat", observation, actions)
    renamed = deepcopy(observation)
    renamed["players"][0]["piles"][0]["cards"][0]["combat_card_index"] = 99000
    renamed["creatures"][1]["combat_id"] = 123456
    changed_actions = deepcopy(actions)
    changed_actions[0]["combat_card_index"] = 99000
    changed_actions[0]["target_creature_id"] = 123456
    changed_actions[0]["action_key"] = "native-secret"
    assert torch.equal(baseline, encoder.encode_actions("combat", renamed, changed_actions))
    missing_hand = deepcopy(observation)
    missing_hand["players"][0]["piles"][0]["cards"].clear()
    with pytest.raises(ValueError, match="card absent"):
        encoder.encode_actions("combat", missing_hand, actions)
    missing_potion = deepcopy(observation)
    missing_potion["players"][0]["potions"].clear()
    with pytest.raises(ValueError, match="potion slot absent"):
        encoder.encode_actions("combat", missing_potion, actions)
    unsupported = deepcopy(actions)
    unsupported[0]["selected_model_ids"] = ["CARD.TEST"]
    with pytest.raises(ValueError, match="selected_model_ids"):
        encoder.encode_actions("combat", observation, unsupported)


def test_outside_potion_actions_match_observed_slot_and_model() -> None:
    observation = _outside_observation()
    observation["surface"] = "Rewards"
    observation["players"][0]["potions"] = [
        {"slot_index": 0, "model_id": "POTION.AMBERGRIS"},
        {"slot_index": 2, "model_id": "POTION.BLOOD"},
    ]
    actions = [
        {"kind": "use_potion", "target_id": "POTION.AMBERGRIS",
         "potion_slot_index": 0},
        {"kind": "discard_potion", "target_id": "POTION.BLOOD",
         "potion_slot_index": 2},
    ]
    encoder = RawFeatureEncoder(RawFeatureSpec.fit([
        {"domain": "outside_combat", "observation": observation,
         "legal_actions": actions},
    ]))
    encoded = encoder.encode_actions("outside_combat", observation, actions)
    assert not torch.equal(encoded[0], encoded[1])
    assert encoder.encode_executed_action("outside_combat", observation,
                                          actions[0]).shape == encoded[0].shape

    wrong_slot = deepcopy(actions)
    wrong_slot[0]["potion_slot_index"] = 1
    with pytest.raises(ValueError, match="slot absent"):
        encoder.encode_actions("outside_combat", observation, wrong_slot)
    wrong_model = deepcopy(actions)
    wrong_model[0]["target_id"] = "POTION.BLOOD"
    with pytest.raises(ValueError, match="model does not match"):
        encoder.encode_actions("outside_combat", observation, wrong_model)


def test_set_candidates_and_true_selection_are_distinct_from_template() -> None:
    encoder = _encoder()
    observation = _outside_observation()
    choice = encoder.encode_set_candidates("outside_combat", observation)
    assert choice is not None
    assert choice.features.shape == (2, encoder.spec.entity_feature_dim)
    assert choice.candidate_keys == ((0, "CARD.DEFEND", 0), (1, "CARD.DEFEND", 1))
    assert (choice.min_select, choice.max_select) == (1, 2)
    # Two copies of the same model still carry their observed per-copy
    # upgrade values; deck_index is used only for this join, not as a feature.
    assert not torch.equal(choice.features[0], choice.features[1])
    selected_action = {"kind": "remove_card_set", "selected_cards": [
        {"option_index": 1, "model_id": "CARD.DEFEND", "deck_index": 1},
    ]}
    mask = encoder.encode_selected_set("outside_combat", observation,
                                       selected_action, choice)
    assert mask.tolist() == [False, True]
    template = encoder.encode_actions("outside_combat", observation,
                                      _outside_actions())[0]
    executed = encoder.encode_executed_action("outside_combat", observation,
                                               selected_action)
    assert not torch.equal(template, executed)
    # The outer policy head also sees the candidates when deciding whether
    # to choose the template or a cancellation action.
    entities = encoder.encode_observation("outside_combat", observation)
    choice_column = ENTITY_KINDS.index("card")
    assert (entities[:, choice_column] == 1).sum().item() == 4
    with pytest.raises(ValueError, match="unique subset"):
        encoder.encode_selected_set("outside_combat", observation,
                                    {"selected_cards": [
                                        {"option_index": 9, "model_id": "CARD.DEFEND",
                                         "deck_index": 1},
                                    ]}, choice)


def test_combat_set_selection_matches_native_card_identity() -> None:
    observation = _combat_observation()
    observation["active_choice"] = {
        "choice_id": 91, "source": "Hand", "min_selections": 1,
        "max_selections": 2, "can_cancel": True,
        "cards": [
            {"combat_card_index": 101, "model_id": "CARD.DEFEND",
             "upgrade_level": 0, "option_index": 0,
             "display": {"energy_cost": 2, "star_cost": 0, "costs_x": False}},
            {"combat_card_index": 102, "model_id": "CARD.DEFEND",
             "upgrade_level": 1, "option_index": 1,
             "display": {"energy_cost": 1, "star_cost": 0, "costs_x": False}},
        ],
    }
    spec = RawFeatureSpec.fit([{"domain": "combat", "observation": observation,
                               "legal_actions": [{"kind": "resolve_choice",
                                                  "is_selection_template": True}]}])
    encoder = RawFeatureEncoder(spec)
    choice = encoder.encode_set_candidates("combat", observation)
    assert choice is not None
    assert choice.candidate_keys == ((101, "CARD.DEFEND", 0),
                                     (102, "CARD.DEFEND", 1))
    assert not torch.equal(choice.features[0], choice.features[1])
    first = encoder.encode_executed_action("combat", observation,
                                            {"kind": "resolve_choice",
                                             "selected_combat_card_ids": [101]})
    second = encoder.encode_executed_action("combat", observation,
                                             {"kind": "resolve_choice",
                                              "selected_combat_card_ids": [102]})
    assert not torch.equal(first, second)
    assert encoder.encode_selected_set("combat", observation,
                                       {"kind": "resolve_choice",
                                        "selected_combat_card_ids": [102]},
                                       choice).tolist() == [False, True]
    with pytest.raises(ValueError, match="unique subset"):
        encoder.encode_selected_set("combat", observation,
                                    {"selected_combat_card_ids": [102, 102]}, choice)


def test_crystal_hidden_content_is_not_a_feature_and_map_order_is_irrelevant() -> None:
    encoder = _encoder()
    observation = _outside_observation()
    observation["schema_version"] = 3
    observation.pop("card_selection_options")
    observation["crystal_sphere"] = {
        "width": 1, "height": 1, "divinations_remaining": 2,
        "selected_tool": "none", "is_finished": False,
        "cells": [{"x": 0, "y": 0, "is_hidden": True,
                   "is_highlighted": False, "revealed_item_kind": None}],
    }
    baseline = encoder.encode_observation("outside_combat", observation)
    changed = deepcopy(observation)
    changed["crystal_sphere"]["cells"][0]["revealed_item_kind"] = "SECRET.RELIC"
    changed["map_points"].reverse()
    assert torch.equal(baseline, encoder.encode_observation("outside_combat", changed))
