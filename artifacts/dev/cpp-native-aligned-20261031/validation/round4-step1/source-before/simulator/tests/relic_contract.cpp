#include <iostream>

#include "sts2/relics.h"

using namespace sts2;

namespace {
int checks = 0;
int failures = 0;
void check(bool ok, const char *name) {
    ++checks;
    if (!ok) { ++failures; std::cout << "FAIL " << name << '\n'; }
}

int count_card(const RunContext &r, CardId id) {
    int count = 0;
    for (int i = 0; i < r.deckCount; ++i) count += r.deck[i].id == id;
    return count;
}

BattleContext battle_with(RelicId relic) {
    Card deck[10];
    for (int i = 0; i < 10; ++i)
        deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    const int relicId = static_cast<int>(relic);
    BattleContext b;
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 123u, deck, 10, 0, 80, 80,
           &relicId, 1);
    return b;
}
}  // namespace

int main() {
    {
        RunContext r; r.init(123u, 0);
        const RelicId gated[] = {
            RelicId::AMETHYST_AUBERGINE, RelicId::BOOK_OF_FIVE_RINGS,
            RelicId::BOWLER_HAT, RelicId::DRAGON_FRUIT, RelicId::FROZEN_EGG,
            RelicId::GIRYA, RelicId::JUZU_BRACELET, RelicId::LASTING_CANDY,
            RelicId::LUCKY_FYSH, RelicId::MEAL_TICKET, RelicId::MOLTEN_EGG,
            RelicId::OLD_COIN, RelicId::PLANISPHERE, RelicId::SHOVEL,
            RelicId::TOXIC_EGG, RelicId::WHITE_BEAST_STATUE, RelicId::WHITE_STAR,
        };
        for (RelicId id : gated) {
            r.floor = 40;
            check(run_relic_allowed(r, id), "floor-gated relic available before 41");
            r.floor = 41;
            check(!run_relic_allowed(r, id), "floor-gated relic excluded at 41");
        }
        check(run_relic_allowed(r, RelicId::ANCHOR), "ungated relic remains available");
        Rng rng(123u);
        bool allAllowed = true;
        for (int i = 0; i < 2000; ++i) {
            const RelicId id = run_random_relic(rng, r);
            if (id != RelicId::INVALID && !run_relic_allowed(r, id)) allAllowed = false;
        }
        check(allAllowed, "random relic pool applies floor gate");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::BOWLER_HAT), "obtain bowler");
        const int before = r.gold;
        run_gain_gold(r, 19);
        check(r.gold == before + 22, "bowler rounds bonus down");
        check(r.add_relic(RelicId::DRAGON_FRUIT), "obtain dragon fruit");
        const int hp = r.maxHp;
        run_gain_gold(r, 10);
        check(r.maxHp == hp + 2, "bonus gain triggers dragon fruit separately");
        const int hp2 = r.maxHp;
        run_gain_gold(r, 4);
        check(r.maxHp == hp2 + 1, "zero bonus does not trigger second gain");
    }
    {
        RunContext r; r.init(123u, 0); r.act = 1;
        check(r.add_relic(RelicId::PUMPKIN_CANDLE), "obtain candle");
        check(run_energy_bonus(r) == 1, "candle active in obtained act");
        r.act = 2;
        check(run_energy_bonus(r) == 0, "candle inactive in later act");
        r.act = 1;
        check(run_energy_bonus(r) == 1, "candle remembers obtained act");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::BLOOD_SOAKED_ROSE), "obtain rose");
        check(count_card(r, CardId::ENTHRALLED) == 1, "rose adds enthralled");
        check(run_energy_bonus(r) == 1, "rose grants energy");
    }
    {
        BattleContext a = battle_with(RelicId::VERY_HOT_COCOA);
        BattleContext b = battle_with(RelicId::VERY_HOT_COCOA);
        check(a.player.energy == 7 && b.player.energy == 7, "cocoa first turn every combat");
        a.turn = 2;
        check(relics_energy_for_turn(a, 3) == 3, "cocoa not later turns");
        BattleContext mushroom = battle_with(RelicId::BIG_MUSHROOM);
        check(mushroom.handCount == 3, "mushroom first turn draw");
        mushroom.turn = 2;
        check(relics_modify_draw(mushroom, 5) == 5, "mushroom later turn draw");
    }
    {
        BattleContext b = battle_with(RelicId::BELT_BUCKLE);
        check(b.player.dexterity == 2, "buckle empty at start");
        b.add_potion(PotionId::FIRE_POTION);
        check(b.player.dexterity == 0, "buckle removed on potion gain");
        b.use_potion(0, 0);
        if (b.potionCount != 0 || b.player.dexterity != 2)
            std::cout << "buckle state count=" << b.potionCount << " dex=" << b.player.dexterity
                      << " aux=" << relic_aux(b, RelicId::BELT_BUCKLE) << '\n';
        check(b.potionCount == 0 && b.player.dexterity == 2, "buckle restored on last use");
        relics_potion_used(b);
        check(b.player.dexterity == 2, "buckle not applied twice");
    }
    {
        BattleContext b = battle_with(RelicId::TOASTY_MITTENS);
        b.drawCount = 2;
        b.draw[0] = make_card(CardId::STRIKE_IRONCLAD, false, 200);
        b.draw[1] = make_card(CardId::DRAMATIC_ENTRANCE, false, 201);
        b.turn = 1;
        const int exhausted = b.exhaustCount;
        relics_turn_start(b);
        check(b.exhaustCount == exhausted + 1 && b.exhaust[exhausted].uid == 200,
              "mittens preserve innate before first draw");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::DISTINGUISHED_CAPE), "obtain cape");
        check(count_card(r, CardId::APPARITION) == 3, "cape adds apparitions");
        check(r.add_relic(RelicId::TANXS_WHISTLE), "obtain whistle relic");
        check(count_card(r, CardId::WHISTLE) == 1, "whistle relic adds whistle");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::PRESERVED_FOG), "obtain fog");
        check(r.cardGrid.kind == 6 && r.cardGrid.minSelect == 3,
              "fog waits for three player-selected removals");
        check(count_card(r, CardId::FOLLY) == 0, "fog curse waits for removal completion");
        for (int i = 0; i < 3; ++i)
            check(r.step({RunActionType::SELECT_GRID_CARD, i}), "select fog removal");
        check(r.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "confirm fog removal");
        check(count_card(r, CardId::FOLLY) == 1, "fog adds folly after selected removals");
        check(r.add_relic(RelicId::CALLING_BELL), "obtain bell");
        check(count_card(r, CardId::CURSE_OF_THE_BELL) == 1, "bell adds curse");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::SERE_TALON), "obtain talon");
        check(count_card(r, CardId::WISH) == 3, "talon adds three wishes");
        CardId first = CardId::INVALID;
        int curses = 0;
        bool distinct = true;
        for (int i = 0; i < r.deckCount; ++i) {
            if (card_def(r.deck[i].id).type != CardType::CURSE) continue;
            if (curses == 0) first = r.deck[i].id;
            else distinct = distinct && r.deck[i].id != first;
            ++curses;
        }
        check(curses == 0, "native SereTalon adds no curses");
        check(r.maxHp == 71 && r.hp == 71, "native SereTalon loses nine maximum HP");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::SWORD_OF_STONE), "obtain stone sword");
        r.combatIsElite = true;
        for (int i = 0; i < 4; ++i) relics_combat_end(r, true, false);
        check(run_has_relic(r, RelicId::SWORD_OF_STONE), "stone sword before fifth elite");
        relics_combat_end(r, true, false);
        check(!run_has_relic(r, RelicId::SWORD_OF_STONE) && run_has_relic(r, RelicId::SWORD_OF_JADE),
              "stone sword becomes jade after fifth elite");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::WONGOS_MYSTERY_TICKET), "obtain ticket");
        for (int i = 0; i < 5; ++i) relics_combat_end(r, true, false);
        const int count = r.relicCount;
        const int queued = r.pendingRelicCount;
        for (int i = 0; i < 5; ++i) relics_combat_end(r, true, false);
        check(queued == 0 && r.wongoCombats == 5 && r.relicCount == count &&
              r.pendingRelicCount == queued, "ticket counter stops at five");
    }
    {
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::AMETHYST_AUBERGINE), "obtain aubergine");
        const int initial = r.gold;
        relics_combat_end(r, true, true);
        check(r.gold == initial + 10, "aubergine first boss reward");
        r.act = 2;
        const int last = r.gold;
        relics_combat_end(r, true, true);
        check(r.gold == last, "aubergine excludes final boss");
    }
    std::cout << "checks=" << checks << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
