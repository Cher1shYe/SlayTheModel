// Event-relic audit: event-pool relics are never random drops, so their
// acquisition paths and effects are verified individually. Two relics are pure
// markers in the reference game (no RelicModel overrides); the rest must have
// observable hooks. Evidence: reference decompilation of local build
// 0861bfa1..., not a differential against the unavailable target DLL.
#include "sts2/battle.h"
#include "sts2/relics.h"
#include "sts2/relic_card_rewards.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
}

int main() {
    {
        // Reference-confirmed effect-free event relics.
        check(relic_implemented(RelicId::WONGO_CUSTOMER_APPRECIATION_BADGE),
              "Wongo badge is an implemented (marker) event relic");
        check(relic_implemented(RelicId::FAKE_MERCHANTS_RUG),
              "Fake Merchant's Rug is an implemented (marker) event relic");
        for (const RelicId marker : {RelicId::WONGO_CUSTOMER_APPRECIATION_BADGE,
                                     RelicId::FAKE_MERCHANTS_RUG}) {
            RunContext rc;
            rc.init(3, 0);
            const int deck = rc.deckCount, hp = rc.hp, maxHp = rc.maxHp, gold = rc.gold;
            check(rc.add_relic(marker), "marker event relic is obtainable");
            check(rc.deckCount == deck && rc.hp == hp && rc.maxHp == maxHp && rc.gold == gold,
                  "marker event relic has no side effects on obtain");
        }
    }
    {
        // Driftwood.TryModifyCardRewardOptions? -> reward reroll availability.
        RunContext with, without;
        with.init(4, 0);
        without.init(4, 0);
        check(with.add_relic(RelicId::DRIFTWOOD), "Driftwood is obtainable");
        check(with.queue_encounter_card_reward(false, false), "reward queued with Driftwood");
        check(without.queue_encounter_card_reward(false, false), "reward queued without Driftwood");
        check(with.rewardCardCanReroll[0], "Driftwood enables the card-reward reroll");
        check(!without.rewardCardCanReroll[0], "no reroll without Driftwood");
    }
    {
        // Nutritious Soup.AfterObtained: every Basic Strike gains
        // TezcatarasEmber (Eternal).
        RunContext rc;
        rc.init(5, 0);
        int basicStrikes = 0, embers = 0;
        for (int i = 0; i < rc.deckCount; ++i) {
            if (card_def(rc.deck[i].id).rarity == Rarity::BASIC &&
                card_is_strike(rc.deck[i])) {
                ++basicStrikes;
                embers += rc.deck[i].enchantment == EnchantmentId::TEZCATARAS_EMBER ? 1 : 0;
            }
        }
        check(basicStrikes > 0 && embers == 0, "starter strikes start unenchanted");
        check(rc.add_relic(RelicId::NUTRITIOUS_SOUP), "Nutritious Soup is obtainable");
        int after = 0;
        for (int i = 0; i < rc.deckCount; ++i)
            if (card_def(rc.deck[i].id).rarity == Rarity::BASIC &&
                card_is_strike(rc.deck[i]))
                after += rc.deck[i].enchantment == EnchantmentId::TEZCATARAS_EMBER ? 1 : 0;
        check(after == basicStrikes, "Nutritious Soup enchants every Basic Strike");
    }
    {
        // Glitter.TryModifyCardRewardOptionsLate: combat card rewards are
        // Glam-enchanted too (not only event/encounter rewards).
        RunContext rc;
        rc.init(6, 0);
        check(rc.add_relic(RelicId::GLITTER), "Glitter is obtainable");
        rc.roll_card_reward(false);
        check(rc.offeredCount > 0, "combat rewards generated");
        rc.apply_combat_card_reward_relics();
        int glam = 0;
        bool everyEligible = true;
        for (int i = 0; i < rc.offeredCount; ++i) {
            const Card &c = rc.offered[i];
            if (c.enchantment == EnchantmentId::GLAM) { ++glam; continue; }
            Card plain = make_card(c.id, c.upgraded, 0);
            everyEligible = everyEligible && !card_can_enchant(plain, EnchantmentId::GLAM);
        }
        check(glam > 0 && everyEligible, "Glitter Glams every eligible combat reward");
    }
    {
        // SilkenTress: lose all gold on obtain; one reward set is Glam'd,
        // then it is used up.
        RunContext rc;
        rc.init(7, 0);
        check(rc.gold > 0, "run starts with gold");
        check(rc.add_relic(RelicId::SILKEN_TRESS), "Silken Tress is obtainable");
        check(rc.gold == 0, "Silken Tress spends all gold on obtain");
        int slot = -1;
        for (int i = 0; i < rc.relicCount; ++i)
            if (rc.relics[i] == static_cast<int>(RelicId::SILKEN_TRESS)) slot = i;
        check(slot >= 0, "Silken Tress occupies a relic slot");
        rc.roll_card_reward(false);
        rc.apply_combat_card_reward_relics();
        int glam = 0;
        for (int i = 0; i < rc.offeredCount; ++i)
            glam += rc.offered[i].enchantment == EnchantmentId::GLAM ? 1 : 0;
        check(glam > 0, "Silken Tress Glams one reward set");
        check(slot >= 0 && rc.relicAux[slot] == 1, "Silken Tress records its single use");
        rc.roll_card_reward(false);
        rc.apply_combat_card_reward_relics();
        int second = 0;
        for (int i = 0; i < rc.offeredCount; ++i)
            second += rc.offered[i].enchantment == EnchantmentId::GLAM ? 1 : 0;
        check(second == 0, "Silken Tress does not Glam a second reward set");
    }
    {
        // PaelsEye.BeforeSideTurnEndEarly: a turn with no card plays grants an
        // extra player turn once per combat, skipping the enemy turn.
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 100 + i);
        const int relics[] = {static_cast<int>(RelicId::PAELS_EYE)};
        BattleContext b;
        b.init(Encounter::SETUP_CULTISTS_NORMAL, 9, deck, 10, 0, 500, 500, relics, 1);
        const int hp = b.player.hp;
        b.end_player_turn();
        check(b.turn == 2, "Pael's Eye grants a second player turn");
        check(b.player.hp == hp, "the enemy turn is skipped for the extra turn");
        check((b.paelsEyeState & BattleContext::PAELS_EYE_USED) != 0,
              "Pael's Eye marks its use");
        b.end_player_turn();
        check(b.turn == 3, "the next end of turn returns to the normal flow");
    }
    {
        // Encounter-reward path is covered by the shared reward hook: an
        // event reward with Glitter owned receives Glam.
        RunContext rc;
        rc.init(8, 0);
        check(rc.add_relic(RelicId::GLITTER), "Glitter obtained for event rewards");
        Card cards[3];
        for (int i = 0; i < 3; ++i)
            cards[i] = rc.make_run_card(CardId::STRIKE_IRONCLAD, false);
        apply_card_reward_hooks(rc, cards, 3, true);
        int glam = 0;
        for (int i = 0; i < 3; ++i)
            glam += cards[i].enchantment == EnchantmentId::GLAM ? 1 : 0;
        check(glam == 3, "Glitter applies to non-combat card rewards");
    }
    std::cout << "relic event audit: " << checks << " checks, " << failures
              << " failures\n";
    return failures ? 1 : 0;
}
