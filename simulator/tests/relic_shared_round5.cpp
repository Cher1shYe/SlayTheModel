// Round 5 shared/character relic coverage: relics that were previously
// filtered out of every reward bag and the new on-obtain selectors.
#include "sts2/battle.h"
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
RunContext base() {
    RunContext r;
    r.init(147, 0);
    r.screen = RunScreen::SHOP;
    return r;
}
int first_card_of_type(const RunContext &r, CardType type, int skip = 0) {
    for (int i = 0; i < r.deckCount; ++i)
        if (card_def(r.deck[i].id).type == type && skip-- == 0) return i;
    return -1;
}
}

int main() {
    for (RelicId id : {RelicId::JUZU_BRACELET, RelicId::LASTING_CANDY, RelicId::WHITE_STAR,
                       RelicId::DOLLYS_MIRROR, RelicId::GNARLED_HAMMER, RelicId::KIFUDA,
                       RelicId::ORRERY, RelicId::PUNCH_DAGGER, RelicId::ROYAL_STAMP,
                       RelicId::WING_CHARM, RelicId::GOLD_PLATED_CABLES, RelicId::METRONOME,
                       RelicId::BONE_FLUTE, RelicId::BOOK_REPAIR_KNIFE,
                       RelicId::FUNERARY_MASK, RelicId::UNDYING_SIGIL})
        check(relic_implemented(id), "relic no longer filtered from pools");

    {
        // Juzu Bracelet removes Monster from the unknown-room table.
        auto plain = base();
        plain.nativeProgress.numberOfRuns = 1;
        plain.unknownMapPointsVisited = 10;
        plain.unknownMonsterOdds = 1.0f;
        plain.unknownEliteOdds = plain.unknownTreasureOdds = plain.unknownShopOdds = -1.0f;
        check(plain.roll_unknown_room_type() == static_cast<int>(RoomType::MONSTER),
              "unknown table rolls monster without Juzu");

        auto r = base();
        r.nativeProgress.numberOfRuns = 1;
        r.unknownMapPointsVisited = 10;
        r.unknownMonsterOdds = 1.0f;
        r.unknownEliteOdds = r.unknownTreasureOdds = r.unknownShopOdds = -1.0f;
        check(r.add_relic(RelicId::JUZU_BRACELET), "Juzu obtains");
        for (int i = 0; i < 5; ++i)
            check(r.roll_unknown_room_type() == static_cast<int>(RoomType::EVENT),
                  "Juzu never rolls monster");
        check(r.unknownMonsterOdds == 1.0f, "Juzu leaves monster odds un-grown");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::WING_CHARM), "Wing Charm obtains");
        check(r.queue_card_reward(Rarity::COMMON, false, r.character), "Wing Charm card reward");
        int swift = 0;
        for (int i = 0; i < r.rewardCardCounts[0]; ++i) {
            swift += r.rewardCards[0][i].enchantment == EnchantmentId::SWIFT &&
                     r.rewardCards[0][i].enchantmentAmount == 1;
        }
        check(r.rewardCardCounts[0] == 3 && swift == 1,
              "exactly one reward option gains Swift(1)");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::LASTING_CANDY), "Lasting Candy obtains");
        r.combatIsElite = false;
        for (int pass = 0; pass < 2; ++pass) {
            r.offeredCount = 3;
            for (int i = 0; i < 3; ++i)
                r.offered[i] = r.make_run_card(CardId::STRIKE_IRONCLAD, false);
            r.apply_combat_card_reward_relics();
            if (pass == 0) {
                check(r.offeredCount == 3, "first combat reward has three options");
            } else {
                check(r.offeredCount == 4, "second combat reward gains a fourth option");
                check(r.offeredCount == 4 &&
                      card_def(r.offered[3].id).type == CardType::POWER,
                      "extra Lasting Candy option is a Power card");
            }
        }
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::DOLLYS_MIRROR), "Dolly's Mirror obtains");
        check(r.cardGrid.kind == 18 && r.cardGrid.maxSelect == 1, "Dolly selector opens");
        const CardId wanted = r.deck[0].id;
        const std::uint16_t oldUid = r.deck[0].uid;
        const int before = r.deckCount;
        check(r.step({RunActionType::SELECT_GRID_CARD, 0}), "Dolly selects a card");
        check(r.deckCount == before + 1, "Dolly adds one copy");
        check(r.deck[r.deckCount - 1].id == wanted, "copy keeps the card identity");
        check(r.deck[r.deckCount - 1].uid != oldUid, "copy is a fresh entity");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::GNARLED_HAMMER), "Gnarled Hammer obtains");
        check(r.cardGrid.kind == 19 && r.cardGrid.minSelect == 0 && r.cardGrid.maxSelect == 3,
              "Gnarled Hammer selector allows up to three cards");
        const int attack = first_card_of_type(r, CardType::ATTACK);
        check(attack >= 0 && r.step({RunActionType::SELECT_GRID_CARD, attack}),
              "Gnarled Hammer selects an attack");
        check(r.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "Gnarled Hammer confirms");
        check(r.deck[attack].enchantment == EnchantmentId::SHARP &&
              r.deck[attack].enchantmentAmount == 3,
              "Gnarled Hammer enchants Sharp(3)");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::KIFUDA), "Kifuda obtains");
        check(r.cardGrid.kind == 20 && r.cardGrid.maxSelect == 3, "Kifuda selector opens");
        check(r.step({RunActionType::SELECT_GRID_CARD, 0}) &&
              r.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "Kifuda confirms");
        check(r.deck[0].enchantment == EnchantmentId::ADROIT &&
              r.deck[0].enchantmentAmount == 3, "Kifuda enchants Adroit(3)");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::PUNCH_DAGGER), "Punch Dagger obtains");
        const int attack = first_card_of_type(r, CardType::ATTACK);
        check(r.cardGrid.kind == 21 && attack >= 0 &&
              r.step({RunActionType::SELECT_GRID_CARD, attack}), "Punch Dagger selects");
        check(!r.cardGrid.kind && r.deck[attack].enchantment == EnchantmentId::MOMENTUM &&
              r.deck[attack].enchantmentAmount == 5, "Punch Dagger enchants Momentum(5)");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::ROYAL_STAMP), "Royal Stamp obtains");
        const int skill = first_card_of_type(r, CardType::SKILL);
        check(r.cardGrid.kind == 22 && skill >= 0 &&
              r.step({RunActionType::SELECT_GRID_CARD, skill}), "Royal Stamp selects");
        check(!r.cardGrid.kind &&
              r.deck[skill].enchantment == EnchantmentId::ROYALLY_APPROVED,
              "Royal Stamp applies Royally Approved");
        check(card_has(r.deck[skill], CF_INNATE) && card_has(r.deck[skill], CF_RETAIN),
              "Royally Approved grants Innate and Retain");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::ORRERY), "Orrery obtains");
        int queued = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
            queued += r.rewardCardPending[i];
            if (r.rewardCardPending[i]) check(r.rewardCardCounts[i] == 3, "Orrery reward has three cards");
        }
        check(queued == 5, "Orrery queues five card rewards");
    }

    {
        auto r = base();
        check(r.add_relic(RelicId::WHITE_STAR), "White Star obtains");
        check(r.queue_encounter_card_reward(false, true), "White Star boss card reward");
        check(r.rewardCardCounts[0] == 3, "White Star reward has three cards");
        for (int i = 0; i < r.rewardCardCounts[0]; ++i)
            check(card_def(r.rewardCards[0][i].id).rarity == Rarity::RARE,
                  "White Star reward rolls boss rares");
    }

    {
        // Driftwood: one reroll per card reward, with the same option set.
        auto r = base();
        check(r.add_relic(RelicId::DRIFTWOOD), "Driftwood obtains");
        r.screen = RunScreen::REWARDS;
        check(r.queue_card_reward(Rarity::COMMON, false, r.character), "Driftwood reward queued");
        check(r.rewardCardCanReroll[0], "Driftwood marks the reward rerollable");
        check(r.step({RunActionType::REROLL_CARD_REWARD, 0}), "Driftwood rerolls");
        check(r.rewardCardPending[0] && r.rewardCardCounts[0] == 3 &&
              !r.rewardCardCanReroll[0], "reroll refreshes three options once");
        check(!r.step({RunActionType::REROLL_CARD_REWARD, 0}),
              "second reroll is rejected");
    }

    {
        // Pael's Eye: an empty turn exhausts the hand and grants one extra
        // player turn without an enemy turn.
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 800 + i);
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 7, deck, 10, 0, 500, 500);
        b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
        b.relicCount = 1;
        b.relics[0] = static_cast<int>(RelicId::PAELS_EYE);
        b.relicMelted[0] = false;
        b.relicAux[0] = 0;
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 900);
        b.hand[b.handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 901);
        const int turn = b.turn;
        const int monsterHp = b.monsters[0].hp;
        const int playerHp = b.player.hp;
        b.end_player_turn();
        check(b.turn == turn + 1 && (b.paelsEyeState & BattleContext::PAELS_EYE_USED) != 0,
              "Pael's Eye takes an extra turn");
        check(b.handCount == 0 && b.exhaustCount == 2 && b.discardCount == 0,
              "Pael's Eye exhausts the hand before discarding");
        check(b.monsters[0].hp == monsterHp && b.player.hp == playerHp,
              "Pael's Eye skips the enemy turn");
        b.hand[b.handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 902);
        b.end_player_turn();
        check((b.paelsEyeState & BattleContext::PAELS_EYE_USED) != 0 && b.handCount > 0,
              "Pael's Eye only triggers once per combat");
    }

    std::cout << "relic shared round5: " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
