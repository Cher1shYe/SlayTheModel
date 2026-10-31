#include <iostream>
#include "sts2/battle.h"
#include "sts2/monsters.h"

using namespace sts2;

static int failures = 0;
static void check(const char *name, int actual, int expected) {
    if (actual != expected) {
        std::cerr << name << ": expected " << expected << ", got " << actual << '\n';
        ++failures;
    }
}

static BattleContext battle(int ascension = 0) {
    BattleContext b;
    b.player.hp = b.player.maxHp = 1000;
    b.ascension = ascension;
    b.monsterAiRng = Rng(7001, "monster");
    return b;
}

int main() {
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.activePlay.active = true;
        b.activePlay.card = make_card(CardId::DEFEND_IRONCLAD, false, 1000);
        b.nextUid = 1000;
        b.auto_play_random(make_card(CardId::ANGER, false, 1001), false);
        check("Nested play reserves outer card UID", b.discard[0].uid, 1002);
        check("Nested play restores outer frame", b.activePlay.card.uid, 1000);
        b.clear_card_uid_reservations();
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.player.energy = 10;
        Card card = make_card(CardId::STRIKE_IRONCLAD, false, 11);
        card.enchantment = EnchantmentId::GLAM;
        card.enchantmentAmount = 1;
        b.hand[b.handCount++] = card;
        const int hp = b.monsters[0].hp;
        b.play_card(0, 0);
        check("Glam repeats the first play", hp - b.monsters[0].hp, 12);
        check("Glam disables itself", b.discard[0].enchantmentDisabled, 1);
        b.hand[b.handCount++] = b.discard[0];
        b.discardCount = 0;
        const int hp2 = b.monsters[0].hp;
        b.play_card(0, 0);
        check("Glam does not repeat later plays", hp2 - b.monsters[0].hp, 6);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.player.energy = 10;
        Card card = make_card(CardId::STRIKE_IRONCLAD, false, 21);
        card.enchantment = EnchantmentId::SWIFT;
        card.enchantmentAmount = 2;
        b.hand[b.handCount++] = card;
        b.draw[b.drawCount++] = make_card(CardId::ANGER, false, 22);
        b.draw[b.drawCount++] = make_card(CardId::ANGER, false, 23);
        b.play_card(0, 0);
        check("Swift draws its amount", b.handCount, 2);
        check("Swift disables itself", b.discard[0].enchantmentDisabled, 1);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.player.energy = 10;
        b.add_player_power(PowerId::HELLRAISER, 1);
        Card card = make_card(CardId::DEFEND_IRONCLAD, false, 25);
        card.enchantment = EnchantmentId::SWIFT;
        card.enchantmentAmount = 1;
        b.hand[b.handCount++] = card;
        b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 26);
        const int hp = b.monsters[0].hp;
        b.play_card(0, 0);
        check("Swift preserves outer play through Hellraiser autoplay", b.activePlay.active, 0);
        check("Swift drawn Strike autoplays", hp - b.monsters[0].hp, 6);
        check("Swift source reaches discard once", b.discardCount, 2);
        check("Swift source remains disabled", b.discard[1].enchantmentDisabled, 1);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.player.energy = 10;
        b.add_player_power(PowerId::STRATAGEM, 1);
        Card card = make_card(CardId::STRIKE_IRONCLAD, false, 31);
        card.enchantment = EnchantmentId::SWIFT;
        card.enchantmentAmount = 1;
        b.hand[b.handCount++] = card;
        b.discard[b.discardCount++] = make_card(CardId::ANGER, false, 32);
        b.discard[b.discardCount++] = make_card(CardId::ANGER, false, 33);
        b.play_card(0, 0);
        check("Swift suspends for Stratagem", b.activePlay.swiftAwaitingDraw, 1);
        check("Swift stays enabled until draw resumes", b.activePlay.card.enchantmentDisabled, 0);
        Action choose{};
        choose.type = ActionType::CHOOSE;
        choose.uid = b.pending.cards[0].uid;
        check("Stratagem choice resolves", b.step(choose), 1);
        check("Swift finishes after draw choice", b.activePlay.active, 0);
        check("Swift is then disabled", b.discard[b.discardCount - 1].enchantmentDisabled, 1);
    }
    {
        BattleContext b = battle();
        b.nextUid = 65534;
        b.originalDeckUids[b.originalDeckCount++] = 65534;
        b.hand[b.handCount++] = make_card(CardId::ANGER, false, 1);
        b.pending.cards[b.pending.count++] = make_card(CardId::ANGER, false, 2);
        b.activePlay.active = true;
        b.activePlay.card = make_card(CardId::ANGER, false, 3);
        b.playedThisTurn[b.playedThisTurnCount++] = 4;
        b.playedLastTurn[b.playedLastTurnCount++] = 5;
        b.hasLastPlayed = true;
        b.lastPlayedCard = make_card(CardId::ANGER, false, 6);
        check("UID allocator protects history after wrapping", b.allocate_card_uid(), 7);
        b.nextUid = 7;
        check("UID allocator reserves local candidates", b.allocate_card_uid(), 8);
        b.clear_card_uid_reservations();
        b.nextUid = 7;
        check("UID allocator releases temporary reservations", b.allocate_card_uid(), 7);
        for (auto &bits : b.uidReservations) bits = ~std::uint64_t{0};
        check("UID allocator fails without silent reuse", b.allocate_card_uid(), 0);
    }
    {
        BattleContext b = battle();
        b.cardGenerationRng = Rng(12345, "theft");
        Rng expected = b.cardGenerationRng;
        spawn_monster(b, MonsterId::THIEVING_HOPPER, 0);
        b.monsterCount = 1;
        b.originalDeckUids[0] = 12;
        b.originalDeckUids[1] = 13;
        b.originalDeckUids[2] = 14;
        b.originalDeckCount = 3;
        b.draw[b.drawCount++] = make_card(CardId::ASHEN_STRIKE, false, 12);
        b.draw[b.drawCount++] = make_card(CardId::ASHEN_STRIKE, false, 999); // generated
        b.draw[b.drawCount++] = make_card(CardId::ANGER, false, 14);
        b.discard[b.discardCount++] = make_card(CardId::BATTLE_TRANCE, false, 13);
        const int choice = expected.next_int(0, 1);
        monster_act(b, b.monsters[0]);
        check("Hopper steals one deck card", b.theftCount, 1);
        check("Hopper samples same-rarity candidates", b.theftUids[0], choice == 0 ? 12 : 13);
        check("Hopper keeps stolen card until death", b.theftReturned[0], 0);
        b.damage_monster(0, 1000, true, false, true);
        check("Hopper death offers stolen card", b.theftReturned[0], 1);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::THIEVING_HOPPER, 0);
        b.monsterCount = 1;
        b.monsters[0].stunned = true;
        b.originalDeckUids[0] = 12;
        b.originalDeckCount = 1;
        b.draw[b.drawCount++] = make_card(CardId::ASHEN_STRIKE, false, 12);
        monster_act(b, b.monsters[0]);
        check("Stunned Hopper does not steal", b.theftCount, 0);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::THE_INSATIABLE, 0);
        b.monsterCount = 1;
        Monster &boss = b.monsters[0];
        boss.move = 0;
        monster_act(b, boss);
        check("Liquify initializes Sandpit", boss.power[static_cast<int>(PowerId::SANDPIT)], 4);
        check("Liquify creates three draw cards", b.drawCount, 3);
        check("Liquify creates three discard cards", b.discardCount, 3);
        b.player.energy = 10;
        b.hand[0] = make_card(CardId::FRANTIC_ESCAPE, false, 501);
        b.handCount = 1;
        check("Frantic Escape plays", b.play_card(0, -1), 1);
        check("Frantic Escape extends Sandpit", boss.power[static_cast<int>(PowerId::SANDPIT)], 5);
        check("Frantic Escape increases its combat cost", card_cost(b.discard[b.discardCount - 1]), 2);
        b.monster_turn();
        check("Sandpit ticks before enemy action", boss.power[static_cast<int>(PowerId::SANDPIT)], 4);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::THE_INSATIABLE, 0);
        b.monsterCount = 1;
        b.monsters[0].power[static_cast<int>(PowerId::SANDPIT)] = 1;
        b.player.block = 999;
        b.monster_turn();
        check("Sandpit forcibly kills at zero", b.player.hp, 0);
        check("Sandpit kill ends combat", static_cast<int>(b.outcome), static_cast<int>(Outcome::PLAYER_LOSS));
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::THE_INSATIABLE, 0);
        b.monsterCount = 1;
        b.monsters[0].power[static_cast<int>(PowerId::SANDPIT)] = 1;
        b.monsters[0].alive = false;
        b.monster_turn();
        check("Dead Sandpit owner cannot kill", b.player.hp, 1000);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::GAS_BOMB, 0);
        spawn_monster(b, MonsterId::GREMLIN_MERC, 1);
        b.monsterCount = 2;
        Monster &bomb = b.monsters[0];
        roll_intent(b, bomb);
        check("Gas Bomb intent damage", bomb.intentDamage, asc >= 9 ? 9 : 8);
        monster_act(b, bomb);
        check("Gas Bomb actual explosion damage", 1000 - b.player.hp, asc >= 9 ? 9 : 8);
        check("Gas Bomb dies after exploding", bomb.alive, 0);
    }
    for (int asc : {0, 8, 9}) {
        for (int move : {2, 4}) {  // SWIPE and THROW_RELIC
            BattleContext b = battle(asc);
            spawn_monster(b, MonsterId::FAKE_MERCHANT_MONSTER, 0);
            b.monsterCount = 1;
            Monster &merchant = b.monsters[0];
            merchant.move = move;
            roll_intent(b, merchant);
            check("Fake Merchant intent damage", merchant.intentDamage,
                  move == 4 ? (asc >= 9 ? 10 : 9) : (asc >= 9 ? 15 : 13));
            monster_act(b, merchant);
            check("Fake Merchant actual damage", 1000 - b.player.hp, asc >= 9 ? 15 : 13);
        }
    }
    struct InnateCase { MonsterId monster; PowerId power; int base; int tough; };
    const InnateCase innateCases[] = {
        {MonsterId::FROG_KNIGHT, PowerId::PLATING, 15, 19},
        {MonsterId::LOUSE_PROGENITOR, PowerId::CURL_UP, 14, 18},
        {MonsterId::PHANTASMAL_GARDENER, PowerId::SKITTISH, 6, 7},
        {MonsterId::SEWER_CLAM, PowerId::PLATING, 8, 9},
        {MonsterId::SLUMBERING_BEETLE, PowerId::PLATING, 15, 18},
        {MonsterId::TERROR_EEL, PowerId::SHRIEK, 70, 75},
    };
    for (const InnateCase &item : innateCases) {
        for (int asc : {0, 8, 9}) {
            BattleContext b = battle(asc);
            spawn_monster(b, item.monster, 0);
            check("A8 innate monster power", b.monsters[0].power[static_cast<int>(item.power)],
                  asc >= 8 ? item.tough : item.base);
        }
    }
    check("same encounter tag matches",
          encounters_share_tags(Encounter::SETUP_BOWLBUGS_NORMAL,
                                Encounter::SETUP_BOWLBUGS_WEAK), 1);
    check("one of multiple tags matches",
          encounters_share_tags(Encounter::SETUP_FLYCONID_NORMAL,
                                Encounter::SETUP_SLIMES_WEAK), 1);
    check("unrelated tags do not match",
          encounters_share_tags(Encounter::SETUP_CHOMPERS_NORMAL,
                                Encounter::SETUP_SLIMES_WEAK), 0);
    check("invalid encounter has no tags", encounter_tags(Encounter::INVALID), 0);
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::AXEBOT, 0);
        b.monsterCount = 1;
        b.monsters[0].move = 2;  // ONE_TWO_MOVE
        roll_intent(b, b.monsters[0]);
        check("A9 Axebot intent", b.monsters[0].intentDamage, asc >= 9 ? 6 : 5);
        monster_act(b, b.monsters[0]);
        check("A9 Axebot damage", 1000 - b.player.hp, asc >= 9 ? 12 : 10);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::GREMLIN_MERC, 0);
        b.monsterCount = 1;
        b.monsters[0].move = 0;  // GIMME_MOVE scales at A8, not A9.
        roll_intent(b, b.monsters[0]);
        check("A8 Gremlin Merc intent", b.monsters[0].intentDamage, asc >= 8 ? 8 : 7);
        monster_act(b, b.monsters[0]);
        check("A8 Gremlin Merc damage", 1000 - b.player.hp, asc >= 8 ? 16 : 14);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
        b.monsterCount = 1;
        b.monsters[0].move = 0;  // STAMP_MOVE
        monster_act(b, b.monsters[0]);
        check("A9 Plow threshold", b.monsters[0].power[static_cast<int>(PowerId::PLOW)], asc >= 9 ? 160 : 150);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::INFESTED_PRISM, 0);
        b.monsterCount = 1;
        b.monsters[0].move = 1;  // RADIATE_MOVE
        monster_act(b, b.monsters[0]);
        check("A9 Radiate block", b.monsters[0].block, asc >= 9 ? 18 : 16);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::ENTOMANCER, 0);
        b.monsterCount = 1;
        b.monsters[0].move = 0;  // BEES_MOVE
        roll_intent(b, b.monsters[0]);
        check("A9 Bees intent hit count", b.monsters[0].intentHits, asc >= 9 ? 8 : 7);
        const int damage = b.monsters[0].intentDamage;
        monster_act(b, b.monsters[0]);
        check("A9 Bees actual hit count", 1000 - b.player.hp, damage * (asc >= 9 ? 8 : 7));
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::TEST_SUBJECT, 0);
        b.monsterCount = 1;
        check("A9 Test Subject innate Enrage", b.monsters[0].power[static_cast<int>(PowerId::ENRAGE)], asc >= 9 ? 3 : 2);
        b.monsters[0].move = 8;  // BURNING_GROWL_MOVE
        monster_act(b, b.monsters[0]);
        check("A9 Burning Growl Burns", b.discardCount, asc >= 9 ? 5 : 3);
        check("A9 Burning Growl strength", b.monsters[0].strength, asc >= 9 ? 3 : 2);
    }
    for (int asc : {0, 8, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::WATERFALL_GIANT, 0);
        b.monsterCount = 1;
        Monster &giant = b.monsters[0];
        giant.move = 0;  // PRESSURIZE_MOVE
        monster_act(b, giant);
        check("A9 Steam Eruption amount", giant.power[static_cast<int>(PowerId::STEAM_ERUPTION)], asc >= 9 ? 20 : 15);
        giant.move = 4;  // PRESSURE_GUN_MOVE
        roll_intent(b, giant);
        const int base = asc >= 9 ? 23 : 20;
        check("Pressure Gun initial intent", giant.intentDamage, base);
        monster_act(b, giant);
        check("Pressure Gun first damage", 1000 - b.player.hp, base);
        giant.move = 4;
        roll_intent(b, giant);
        check("Pressure Gun grows by five", giant.intentDamage, base + 5);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::ZAPBOT, 0);
        b.monsterCount = 1;
        monster_act(b, b.monsters[0]);
        check("HighVoltage after enemy turn", b.monsters[0].strength, 2);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::GREMLIN_MERC, 0);
        b.monsterCount = 1;
        b.gold = 25;
        monster_act(b, b.monsters[0]);
        check("Gremlin Merc steals 20", b.gold, 5);
        check("Thievery tracks stolen gold", b.monsters[0].stolenGold, 20);
        monster_act(b, b.monsters[0]);
        check("Thievery is capped by player gold", b.gold, 0);
        check("Thievery accumulates actual amount", b.monsters[0].stolenGold, 25);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::TUNNELER, 0);
        b.monsterCount = 1;
        Monster &m = b.monsters[0];
        m.move = 2;
        m.block = 30;
        m.power[static_cast<int>(PowerId::BURROWED)] = 1;
        monster_act(b, m);
        check("Burrowed retains block", m.block, 30);
        m.stunned = true;
        roll_intent(b, m);
        check("Stunned monster shows stun intent", m.intentType, 8);
        check("Stun intent has no attack damage", m.intentDamage, 0);
    }
    {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::FOGMOG, 0);
        spawn_monster(b, MonsterId::GREMLIN_MERC, 1);
        b.monsterCount = 2;
        b.monsters[0].move = 0;
        monster_act(b, b.monsters[0]);
        check("Summon preserves existing ally", b.monsters[1].power[static_cast<int>(PowerId::ILLUSION)], 0);
        check("Illusion summoned", b.monsterCount, 3);
        Monster &illusion = b.monsters[2];
        check("Summoned illusion has Minion", illusion.power[static_cast<int>(PowerId::MINION)], 1);
        illusion.reviving = true;
        illusion.hp = 0;
        const int hp = b.player.hp;
        monster_act(b, illusion);
        check("Illusion revives to full HP", illusion.hp, illusion.maxHp);
        check("Illusion revive consumes its turn", b.player.hp, hp);
    }
    for (int asc : {0, 8}) {
        BattleContext b = battle(asc);
        b.nicheRng = Rng(123);
        Rng expected = b.nicheRng;
        spawn_monster(b, MonsterId::TOUGH_EGG, 0);
        b.monsterCount = 1;
        Monster &egg = b.monsters[0];
        egg.strength = 7;
        egg.weak = 2;
        egg.power[static_cast<int>(PowerId::METALLICIZE)] = 4;
        monster_act(b, egg);
        check("Hatchling HP uses Niche RNG", egg.maxHp,
              expected.next_int_range(asc ? 20 : 19, asc ? 23 : 22));
        check("Hatchling starts at full HP", egg.hp, egg.maxHp);
        check("Hatch removes buffs", egg.strength, 0);
        check("Hatch removes debuffs", egg.weak, 0);
        check("Hatch removes other powers", egg.power[static_cast<int>(PowerId::METALLICIZE)], 0);
        check("Hatch retains Minion", egg.power[static_cast<int>(PowerId::MINION)], 1);
        check("Hatch power removed", egg.power[static_cast<int>(PowerId::HATCH)], 0);
        check("Hatch follows with Nibble", egg.move, 1);
    }
    for (int initialHp : {1000, 10}) {
        BattleContext b = battle();
        spawn_monster(b, MonsterId::WATERFALL_GIANT, 0);
        b.monsterCount = 1;
        b.player.hp = initialHp;
        Monster &giant = b.monsters[0];
        giant.hp = 1;
        giant.power[static_cast<int>(PowerId::STEAM_ERUPTION)] = 23;
        b.damage_monster(0, 1, true, true);
        check("Steam death starts windup", giant.move, 6);
        check("Steam death preserves combat", static_cast<int>(b.outcome), static_cast<int>(Outcome::UNDECIDED));
        monster_act(b, giant);
        check("Steam eruption stores damage", giant.steamEruptionDamage, 23);
        check("Steam eruption removes power", giant.power[static_cast<int>(PowerId::STEAM_ERUPTION)], 0);
        check("Explosion intent shows damage", giant.intentDamage, 23);
        check("Explosion follows preparation", giant.move, 7);
        check("Preparation does not end combat", static_cast<int>(b.outcome), static_cast<int>(Outcome::UNDECIDED));
        monster_act(b, giant);
        check("Explosion damages player", b.player.hp, initialHp > 23 ? initialHp - 23 : 0);
        check("Explosion removes giant", giant.alive, 0);
        check("Explosion ends combat", static_cast<int>(b.outcome),
              static_cast<int>(initialHp > 23 ? Outcome::PLAYER_VICTORY : Outcome::PLAYER_LOSS));
    }
    for (int asc : {0, 9}) {
        BattleContext b = battle(asc);
        spawn_monster(b, MonsterId::DOOR, 0);
        spawn_monster(b, MonsterId::DOORMAKER, 1);
        b.monsterCount = 2;
        b.monsters[0].reviving = true;
        b.monsters[1].move = 2;
        monster_act(b, b.monsters[1]);
        check("Door first revival HP", b.monsters[0].maxHp, asc ? 190 : 175);
        check("Door first revival strength", b.monsters[0].strength, asc ? 4 : 3);
        b.monsters[0].reviving = true;
        spawn_monster(b, MonsterId::DOORMAKER, 2);
        b.monsterCount = 3;
        b.monsters[2].move = 2;
        monster_act(b, b.monsters[2]);
        check("Door second revival resets base HP", b.monsters[0].maxHp, asc ? 215 : 195);
        check("Door second revival strength", b.monsters[0].strength, asc ? 8 : 6);
    }
    return failures == 0 ? 0 : 1;
}
