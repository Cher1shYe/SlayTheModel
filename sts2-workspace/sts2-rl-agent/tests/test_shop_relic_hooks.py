"""Regression tests for merchant relic hook plumbing."""

import sts2_env.potions  # noqa: F401

from sts2_env.cards.factory import create_card
from sts2_env.core.enums import CardId, CardRarity, PotionRarity, RelicRarity, RoomType
from sts2_env.run.modifiers import HoarderModifier
from sts2_env.run.run_manager import RunManager
from sts2_env.run.shop import (
    SHOP_ENTRY_SOLD_OUT_PRICE,
    ShopCardEntry,
    ShopInventory,
    ShopPotionEntry,
    ShopRelicEntry,
    generate_shop_inventory,
)
from sts2_env.run.run_state import RunState


def test_membership_card_halves_shop_prices():
    base = RunState(seed=301, character_id="Ironclad")
    discounted = RunState(seed=301, character_id="Ironclad")
    assert discounted.player.obtain_relic("MEMBERSHIP_CARD")

    base_inv = generate_shop_inventory(base)
    discounted_inv = generate_shop_inventory(discounted)

    assert discounted_inv.cards[0].price == round(base_inv.cards[0].price * 0.5)
    assert discounted_inv.removal_cost == round(base_inv.removal_cost * 0.5)


def test_the_courier_refills_bought_shop_card_slot():
    mgr = RunManager(seed=302, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("THE_COURIER")
    mgr.run_state.player.gold = 9999
    mgr._enter_shop()

    assert mgr._shop_inventory is not None
    original_entry = mgr._shop_inventory.cards[0]
    original_card_id = original_entry.card_id

    result = mgr._do_shop_action({"action": "buy_card", "index": 0})

    assert "Bought card" in result["description"]
    refilled_entry = mgr._shop_inventory.cards[0]
    assert refilled_entry.price < SHOP_ENTRY_SOLD_OUT_PRICE
    assert refilled_entry.card_id
    assert len(mgr.run_state.player.deck) > 0
    assert refilled_entry is not original_entry or refilled_entry.card_id != original_card_id


def test_molten_egg_and_fresnel_lens_modify_merchant_cards():
    run_state = RunState(seed=304, character_id="Ironclad")
    assert run_state.player.obtain_relic("MOLTEN_EGG")
    assert run_state.player.obtain_relic("FRESNEL_LENS")

    inv = generate_shop_inventory(run_state)

    attack_entries = [entry for entry in inv.cards if entry.card_type == "Attack" and entry.card is not None]
    block_entries = [entry for entry in inv.cards if entry.card is not None and entry.card.base_block is not None]
    nonblock_entries = [entry for entry in inv.cards if entry.card is not None and entry.card.base_block is None]
    assert attack_entries
    assert all(entry.card.upgraded for entry in attack_entries)
    assert block_entries
    assert all(entry.card.enchantments.get("Nimble") == 2 for entry in block_entries)
    assert all("Nimble" not in entry.card.enchantments for entry in nonblock_entries)


def test_buying_modified_merchant_card_preserves_modifications_in_deck():
    mgr = RunManager(seed=304, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("MOLTEN_EGG")
    assert mgr.run_state.player.obtain_relic("FRESNEL_LENS")
    mgr.run_state.player.gold = 9999
    mgr._enter_shop()

    assert mgr._shop_inventory is not None
    block_index = next(i for i, entry in enumerate(mgr._shop_inventory.cards) if entry.card is not None and entry.card.base_block is not None)
    mgr._do_shop_action({"action": "buy_card", "index": block_index})

    added = mgr.run_state.player.deck[-1]
    assert added.enchantments.get("Nimble") == 2


def test_lords_parasol_auto_purchases_shop_inventory_for_free(monkeypatch):
    mgr = RunManager(seed=305, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("LORDS_PARASOL")
    mgr.run_state.player.gold = 10
    starting_deck_size = len(mgr.run_state.player.deck)
    inventory = ShopInventory(
        cards=[
            ShopCardEntry(
                rarity=CardRarity.COMMON,
                card_type="Attack",
                card=create_card(CardId.STRIKE_IRONCLAD),
                price=100,
            )
        ],
        relics=[ShopRelicEntry(relic_rarity=RelicRarity.COMMON, relic_id="STRAWBERRY", price=100)],
        potions=[ShopPotionEntry(potion_rarity=PotionRarity.COMMON, potion_id="FirePotion", price=100)],
    )
    monkeypatch.setattr("sts2_env.run.run_manager.generate_shop_inventory", lambda _run_state: inventory)

    mgr._enter_room(RoomType.SHOP)

    assert mgr.run_state.player.gold == 10
    assert len(mgr.run_state.player.deck) == starting_deck_size + 1
    assert "STRAWBERRY" in mgr.run_state.player.relics
    assert [p.potion_id for p in mgr.run_state.player.held_potions()] == ["FirePotion"]
    assert inventory.cards[0].price == SHOP_ENTRY_SOLD_OUT_PRICE
    assert inventory.relics[0].price == SHOP_ENTRY_SOLD_OUT_PRICE
    assert inventory.potions[0].price == SHOP_ENTRY_SOLD_OUT_PRICE
    assert mgr.run_state.pending_choice is not None

    mgr.take_action({"action": "choose", "index": 0})

    assert mgr.run_state.player.gold == 10
    assert len(mgr.run_state.player.deck) == starting_deck_size
    assert inventory.removal_used
    assert mgr.run_state.player.card_shop_removals_used == 1
    assert not any(action["action"] == "remove_card" for action in mgr.get_available_actions())


def test_maw_bank_ignores_lords_parasol_free_shop_purchases(monkeypatch):
    mgr = RunManager(seed=306, character_id="Ironclad")
    assert mgr.run_state.player.obtain_relic("MAW_BANK")
    assert mgr.run_state.player.obtain_relic("LORDS_PARASOL")
    mgr.run_state.player.gold = 10
    inventory = ShopInventory(
        cards=[
            ShopCardEntry(
                rarity=CardRarity.COMMON,
                card_type="Attack",
                card=create_card(CardId.STRIKE_IRONCLAD),
                price=100,
            )
        ],
    )
    monkeypatch.setattr("sts2_env.run.run_manager.generate_shop_inventory", lambda _run_state: inventory)

    mgr._enter_room(RoomType.SHOP)
    mgr.take_action({"action": "choose", "index": 0})

    assert mgr.run_state.player.gold == 22
    maw_bank = next(relic for relic in mgr.run_state.player.get_relic_objects() if relic.relic_id.name == "MAW_BANK")
    maw_bank.after_room_entered(mgr.run_state.player, RoomType.MONSTER)
    assert mgr.run_state.player.gold == 34


def test_hoarder_modifier_blocks_shop_card_removal():
    mgr = RunManager(seed=307, character_id="Ironclad")
    mgr._phase = RunManager.PHASE_SHOP
    mgr.run_state.modifiers = [HoarderModifier()]
    mgr.run_state.player.gold = 999
    starting_deck_size = len(mgr.run_state.player.deck)
    mgr._shop_inventory = ShopInventory(removal_cost=75)

    assert not any(action["action"] == "remove_card" for action in mgr.get_available_actions())

    result = mgr._do_shop_action({"action": "remove_card"})

    assert result["description"] == "Cannot afford removal."
    assert mgr.run_state.pending_choice is None
    assert len(mgr.run_state.player.deck) == starting_deck_size
    assert not mgr._shop_inventory.removal_used
    assert mgr.run_state.player.card_shop_removals_used == 0


def test_hoarder_modifier_duplicates_new_deck_cards_only_once():
    run_state = RunState(seed=308, character_id="Ironclad")
    hoarder = HoarderModifier()
    run_state.modifiers = [hoarder]
    run_state.player.deck = []

    run_state.player.add_card_instance_to_deck(create_card(CardId.STRIKE_IRONCLAD))

    assert [card.card_id for card in run_state.player.deck] == [
        CardId.STRIKE_IRONCLAD,
        CardId.STRIKE_IRONCLAD,
        CardId.STRIKE_IRONCLAD,
    ]
    assert len({card.instance_id for card in run_state.player.deck}) == len(run_state.player.deck)

    run_state.player.add_card_instance_to_deck(create_card(CardId.DEFEND_IRONCLAD), source=hoarder)

    assert [card.card_id for card in run_state.player.deck].count(CardId.DEFEND_IRONCLAD) == 1
