#include <iostream>
#include <cstring>
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/card_candidates.h"

using namespace sts2;

int main() {
    int failures = 0;
    auto check = [&](bool ok, const char *label) {
        if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
    };
    Card strike = make_card(CardId::STRIKE_IRONCLAD, false, 1);
    Card defend = make_card(CardId::DEFEND_IRONCLAD, false, 2);
    Card curse = make_card(CardId::GUILTY, false, 3);
    check(!card_can_enchant(curse, EnchantmentId::SOWN), "curse rejected");
    check(card_can_transform_from_deck(curse), "removable curse can transform");
    check(!card_can_transform_from_deck(make_card(CardId::ASCENDERS_BANE, false, 8)),
          "eternal curse cannot transform");
    check(!card_can_enchant(defend, EnchantmentId::VIGOROUS), "vigorous needs attack");
    check(!card_apply_enchantment(strike, EnchantmentId::SOWN, 0), "zero amount rejected");
    check(card_apply_enchantment(strike, EnchantmentId::VIGOROUS, 8), "vigorous applied");
    check(!card_apply_enchantment(strike, EnchantmentId::SOWN, 1), "second enchantment rejected");

    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 10);
    BattleContext b;
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 10, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.player.energy = 20;
    b.monsters[0].hp = b.monsters[0].maxHp = 10000;
    b.monsters[0].block = 0;
    b.player.weak = 1;
    check(b.calc_player_damage(6, 0, true, &strike) == 10, "vigorous before weak multiplier");
    check(b.calc_player_damage(6, 0, false, &strike) == 6, "vigorous excludes unpowered damage");
    strike.replay = 1;
    b.hand[b.handCount++] = strike;
    const int hp = b.monsters[0].hp;
    check(b.play_card(0, 0), "play vigorous");
    check(hp - b.monsters[0].hp == 14, "vigorous first replay only");
    check(b.discardCount == 1 && b.discard[0].enchantmentDisabled, "vigorous disabled in discard");

    Card sown = make_card(CardId::DEFEND_IRONCLAD, false, 4);
    check(card_apply_enchantment(sown, EnchantmentId::SOWN, 1), "sown applied");
    sown.replay = 1;
    b.hand[b.handCount++] = sown;
    int energy = b.player.energy;
    check(b.play_card(0, 0), "play sown");
    check(b.player.energy == energy, "sown energy once across replays");
    check(b.discard[b.discardCount - 1].enchantmentDisabled, "sown disabled in discard");
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    Card pact = make_card(CardId::BURNING_PACT, false, 500);
    check(card_apply_enchantment(pact, EnchantmentId::SOWN, 1), "sown on selection card");
    b.hand[b.handCount++] = pact;
    b.hand[b.handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 501);
    energy = b.player.energy;
    check(b.play_card(0, 0) && b.pending.op != ChoiceOp::NONE,
          "card play suspends for selection");
    check(b.player.energy == energy - card_cost(pact), "sown waits for card effect");
    Action choice;
    choice.type = ActionType::CHOOSE;
    choice.uid = b.pending.cards[0].uid;
    b.step(choice);
    check(b.pending.op == ChoiceOp::NONE && b.player.energy == energy - card_cost(pact) + 1,
          "sown fires after selection resolves");
    sown.enchantmentDisabled = true;
    BattleContext next;
    next.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, &sown, 1, 0, 500, 500);
    check(next.handCount == 1 && !next.hand[0].enchantmentDisabled, "combat resets enchantment");

    auto event_id = [](const char *name) {
        for (int i = 0; i < event_count(); ++i)
            if (std::strcmp(event_info(i)->name, name) == 0) return i;
        return -1;
    };
    RunContext run;
    run.init(123, 0);
    event_begin(run, event_id("SAPPHIRE_SEED"), false);
    check(run.step({RunActionType::EVENT_CHOICE, 1}), "plant seed");
    check(run.eventCardSelection == 2, "plant offers manual selection");
    check(!run.step({RunActionType::EVENT_CHOICE, 0}), "cannot bypass selector");
    RunContext restored;
    check(RunContext::restore(run.serialize(), restored) && restored.eventCardSelection == 2,
          "pending selection survives snapshot");
    RunContext corrupt = run;
    corrupt.eventCardSelection = 3;
    check(!RunContext::restore(corrupt.serialize(), restored), "snapshot rejects mismatched selector");
    const auto options = run.legal_actions();
    check(!options.empty() && options[0].type == RunActionType::EVENT_SELECT_CARD,
          "selector actions available");
    const int selected = options[0].index;
    check(run.step({RunActionType::EVENT_SELECT_CARD, selected}), "select sown card");
    check(run.deck[selected].enchantment == EnchantmentId::SOWN &&
          run.deck[selected].enchantmentAmount == 1, "selected card retains sown");
    check(RunContext::restore(run.serialize(), restored) &&
          restored.deck[selected].enchantment == EnchantmentId::SOWN,
          "deck enchantment survives snapshot");

    run.init(123, 0);
    run.hp = 60;
    event_begin(run, event_id("SAPPHIRE_SEED"), false);
    check(run.step({RunActionType::EVENT_CHOICE, 0}) && run.hp == 69 &&
          run.eventCardSelection == 1, "eat heals and offers upgrade selection");
    const int upgrade = run.legal_actions()[0].index;
    check(run.step({RunActionType::EVENT_SELECT_CARD, upgrade}) && run.deck[upgrade].upgraded,
          "eat upgrades selected card");

    run.init(123, 0);
    run.add_potion(PotionId::BLOOD_POTION);
    event_begin(run, event_id("STONE_OF_ALL_TIME"), false);
    const int start_hp = run.hp;
    check(!run.use_potion_out_of_combat(0), "stone locks potion removal");
    check(run.step({RunActionType::EVENT_CHOICE, 1}) && run.hp == start_hp - 6 &&
          run.eventCardSelection == 3, "stone push offers attack selection");
    int attack = run.legal_actions()[0].index;
    check(run.step({RunActionType::EVENT_SELECT_CARD, attack}) &&
          run.deck[attack].enchantment == EnchantmentId::VIGOROUS &&
          run.deck[attack].enchantmentAmount == 8, "selected attack retains vigorous");

    run.init(123, 0);
    run.deckCount = 1;
    run.deck[0] = make_card(CardId::DEFEND_IRONCLAD, false, 1);
    event_begin(run, event_id("SAPPHIRE_SEED"), false);
    check(run.step({RunActionType::EVENT_CHOICE, 1}) &&
          run.deck[0].enchantment == EnchantmentId::SOWN && !run.eventCardSelection,
          "single enchantable card selected automatically");
    run.init(123, 0);
    run.cardRarityOdds = 0.23f;
    strike.upgraded = true;
    Card maul = make_maul_transformation(run, strike);
    check(maul.id == CardId::MAUL && maul.upgraded && maul.uid != strike.uid &&
          maul.enchantment == EnchantmentId::VIGOROUS && maul.enchantmentAmount == 8,
          "maul preserves upgrade and compatible enchantment");
    Card choices[8];
    check(make_noncombat_card_candidates(run, choices, 5, CardPool::IRONCLAD, false) == 5,
          "brain leech offers five cards");
    check(run.cardRarityOdds == 0.23f, "noncombat cards preserve combat rarity odds");
    for (int i = 0; i < 5; ++i) check(!choices[i].upgraded, "brain leech candidates unupgraded");
    check(make_noncombat_card_candidates(run, choices, 8, CardPool::IRONCLAD, true) == 8,
          "cheese offers eight common cards");
    for (int i = 0; i < 8; ++i) {
        check(!choices[i].upgraded && card_def(choices[i].id).rarity == Rarity::COMMON,
              "cheese candidates are common and unupgraded");
        for (int j = 0; j < i; ++j) check(choices[i].id != choices[j].id, "cheese candidates distinct");
    }
    run.init(123, 0);
    event_begin(run, event_id("BRAIN_LEECH"), false);
    check(run.step({RunActionType::EVENT_CHOICE, 0}) && run.cardGrid.count == 5,
          "brain leech opens five-card selection");
    check(!run.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "brain leech selection mandatory");
    const CardId shared = run.cardGrid.cards[2].id;
    check(run.step({RunActionType::SELECT_GRID_CARD, 2}) && !run.cardGrid.kind &&
          run.deck[run.deckCount - 1].id == shared,
          "brain leech adds selected card");

    run.init(123, 0);
    event_begin(run, event_id("ROOM_FULL_OF_CHEESE"), false);
    check(run.step({RunActionType::EVENT_CHOICE, 0}) && run.cardGrid.count == 8,
          "cheese opens eight-card selection");
    check(run.step({RunActionType::SELECT_GRID_CARD, 0}), "cheese first selection");
    check(!run.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "cheese requires two");
    check(run.step({RunActionType::SELECT_GRID_CARD, 0}) && run.cardGrid.selectedCount == 0,
          "cheese selection can be undone");
    check(run.step({RunActionType::SELECT_GRID_CARD, 0}), "cheese reselect");
    check(RunContext::restore(run.serialize(), restored) && restored.cardGrid.selected[0],
          "grid selection survives snapshot");
    check(run.step({RunActionType::SELECT_GRID_CARD, 1}) && !run.cardGrid.kind && run.deckCount == 12,
          "cheese adds the two selected cards");

    for (int origin = 0; origin < 3; ++origin) {
        run.init(123, 0);
        card_apply_upgrade(run.deck[0]);
        card_apply_enchantment(run.deck[0], EnchantmentId::VIGOROUS, 8);
        if (origin == 0) {
            event_begin(run, event_id("NEOW"), true);
            run.eventRelics[0] = static_cast<int>(RelicId::CLAWS);
            check(run.step({RunActionType::EVENT_CHOICE, 0}), "claws from event");
        } else if (origin == 1) {
            run.screen = RunScreen::SHOP;
            run.shopRelicCount = 1;
            run.shopRelics[0] = static_cast<int>(RelicId::CLAWS);
            run.shopRelicPrices[0] = 0;
            check(run.step({RunActionType::BUY_RELIC, 0}), "claws from shop");
        } else {
            run.screen = RunScreen::REWARDS;
            run.pendingRelicCount = 1;
            run.pendingRelics[0] = static_cast<int>(RelicId::CLAWS);
            check(run.step({RunActionType::TAKE_RELIC_REWARD, 0}), "claws from reward");
        }
        const RunScreen resume = run.screen;
        check(run.cardGrid.kind == 3, "claws grid stays on original page");
        check(run.step({RunActionType::SELECT_GRID_CARD, 0}), "claws select card");
        check(run.step({RunActionType::SELECT_GRID_CARD, 0}) && run.cardGrid.selectedCount == 0,
              "claws selection can be undone");
        check(run.step({RunActionType::SELECT_GRID_CARD, 0}), "claws reselect");
        check(RunContext::restore(run.serialize(), restored) && restored.cardGrid.selected[0],
              "claws grid snapshot");
        check(restored.step({RunActionType::CONFIRM_GRID_CARDS, 0}) && restored.cardGrid.preview,
              "claws shows confirmation preview");
        check(restored.step({RunActionType::CANCEL_GRID_PREVIEW, 0}) &&
              !restored.cardGrid.preview && !restored.cardGrid.selectedCount,
              "claws preview cancellation clears selection");
        check(restored.step({RunActionType::SELECT_GRID_CARD, 0}) &&
              restored.step({RunActionType::CONFIRM_GRID_CARDS, 0}) &&
              restored.step({RunActionType::CONFIRM_GRID_CARDS, 0}) && restored.screen == resume,
              "claws confirmation returns to original page");
        const Card &last = restored.deck[restored.deckCount - 1];
        check(last.id == CardId::MAUL && last.upgraded && last.enchantment == EnchantmentId::VIGOROUS,
              "claws selected card becomes upgraded enchanted maul");
    }
    std::cout << "dimensions=" << PUBLIC_OBS_DIM << ',' << PUBLIC_COMBAT_OBS_DIM
              << ',' << CARD_FEAT_DIM << ',' << ACTION_FEAT_DIM << '\n';
    return failures ? 1 : 0;
}
