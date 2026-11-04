// Main-effect coverage for the relics that previously had no automated test
// reference in the port.
//
// Evidence level: local C++ port (ruleset native-41cef1ea-port-v10), checked
// against the decompiled v0.111.0 classes on the local DLL
// 0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9.
// The target DLL 9cb4f1ad... is not available on this machine, so this is not
// a native differential. Each block asserts the relic's main hook, and where
// the relic has a second observable branch (base/upgraded or acquire/use), it
// is asserted too.
#include "sts2/battle.h"
#include "sts2/defect.h"
#include "sts2/regent.h"
#include "sts2/relics.h"

#include <initializer_list>
#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}

BattleContext battle_with(std::initializer_list<RelicId> relics,
                          std::initializer_list<CardId> cards = {},
                          Encounter enc = Encounter::SETUP_BATTLEWORN_DUMMY_V1,
                          CardPool pool = CardPool::IRONCLAD) {
    Card deck[24];
    int deckN = 0;
    if (cards.size() == 0) {
        for (int i = 0; i < 10; ++i)
            deck[deckN++] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    } else {
        int uid = 1;
        for (CardId id : cards) deck[deckN++] = make_card(id, false, uid++);
    }
    int ids[MAX_RELICS];
    int relicN = 0;
    for (RelicId id : relics) ids[relicN++] = static_cast<int>(id);
    BattleContext b;
    b.init(enc, 123u, deck, deckN, 0, 150, 200, ids, relicN,
           nullptr, 0, BASE_POTION_SLOTS, 0, 3, 0, 0, nullptr, nullptr, nullptr,
           nullptr, nullptr, pool);
    b.player.energy = 30;
    return b;
}

int relic_slot(const BattleContext &b, RelicId id) {
    for (int i = 0; i < b.relicCount; ++i)
        if (b.relics[i] == static_cast<int>(id)) return i;
    return -1;
}

bool play(BattleContext &b, int hand, int target) {
    Action a{};
    a.type = ActionType::PLAY_CARD;
    a.hand = static_cast<std::uint8_t>(hand);
    a.target = static_cast<std::int8_t>(target);
    return b.step(a);
}

int count_in_hand(const BattleContext &b, CardId id) {
    int n = 0;
    for (int i = 0; i < b.handCount; ++i) n += b.hand[i].id == id;
    return n;
}

int count_hand_where(const BattleContext &b, bool (*pred)(const Card &)) {
    int n = 0;
    for (int i = 0; i < b.handCount; ++i) n += pred(b.hand[i]) ? 1 : 0;
    return n;
}

bool is_ethereal(const Card &c) { return card_has(c, CF_ETHEREAL); }
bool is_colorless_card(const Card &c) { return card_def(c.id).pool == CardPool::COLORLESS; }
bool is_attack_cost_zero(const Card &c) {
    return card_is_attack(c) && card_cost(c) == 0;
}
}  // namespace

int main() {
    // ---- combat start: powers / orbs / debuffs ---------------------------
    {
        auto b = battle_with({RelicId::CRACKED_CORE});
        check(b.defect.lightningChanneled == 1 &&
                  b.defect.orbs[0].id == OrbId::LIGHTNING,
              "Cracked Core channels one Lightning");
    }
    {
        auto b = battle_with({RelicId::INFUSED_CORE});
        check(b.defect.lightningChanneled == 3,
              "Infused Core channels three Lightning");
    }
    {
        auto b = battle_with({RelicId::BRONZE_SCALES});
        check(b.player_power(PowerId::THORNS) == 3, "Bronze Scales grants 3 Thorns");
    }
    {
        auto b = battle_with({RelicId::GORGET});
        check(b.player_power(PowerId::PLATING) == 4, "Gorget grants 4 Plating");
    }
    {
        auto b = battle_with({RelicId::ODDLY_SMOOTH_STONE});
        check(b.player.dexterity == 1, "Oddly Smooth Stone grants 1 Dexterity");
    }
    {
        auto b = battle_with({RelicId::BAG_OF_MARBLES});
        bool allVuln = true;
        for (int i = 0; i < b.monsterCount; ++i)
            if (b.monsters[i].alive && b.monsters[i].vulnerable < 1) allVuln = false;
        check(allVuln && b.monsterCount > 0, "Bag of Marbles applies Vulnerable");
    }
    {
        auto b = battle_with({RelicId::RED_MASK});
        bool allWeak = true;
        for (int i = 0; i < b.monsterCount; ++i)
            if (b.monsters[i].alive && b.monsters[i].weak < 1) allWeak = false;
        check(allWeak && b.monsterCount > 0, "Red Mask applies Weak");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::FESTIVE_POPPER});
        check(plain.monsters[0].hp - b.monsters[0].hp == 9,
              "Festive Popper deals 9 to all enemies");
    }
    {
        auto b = battle_with({RelicId::PETRIFIED_TOAD});
        check(b.potionCount == 1 && b.potions[0] == static_cast<int>(PotionId::POTION_SHAPED_ROCK),
              "Petrified Toad adds Potion Shaped Rock");
    }
    {
        auto elite = battle_with({RelicId::SLING_OF_COURAGE}, {},
                                 Encounter::SETUP_BYRDONIS_ELITE);
        auto normal = battle_with({RelicId::SLING_OF_COURAGE});
        check(elite.player_power(PowerId::STRENGTH) == 2,
              "Sling of Courage grants 2 Strength in an elite room");
        check(normal.player_power(PowerId::STRENGTH) == 0,
              "Sling of Courage is idle outside elites");
    }
    {
        auto b = battle_with({RelicId::RINGING_TRIANGLE});
        check(b.player_power(PowerId::RETAIN_HAND) == 1,
              "Ringing Triangle grants Retain Hand");
    }
    {
        auto b = battle_with({RelicId::TWISTED_FUNNEL});
        bool poisoned = true;
        for (int i = 0; i < b.monsterCount; ++i)
            if (b.monsters[i].alive &&
                b.monsters[i].power[static_cast<int>(PowerId::POISON)] != 4)
                poisoned = false;
        check(poisoned && b.monsterCount > 0, "Twisted Funnel applies 4 Poison");
    }
    {
        auto b = battle_with({RelicId::PHILOSOPHERS_STONE});
        bool strong = true;
        for (int i = 0; i < b.monsterCount; ++i)
            if (b.monsters[i].alive && b.monsters[i].strength != 1) strong = false;
        check(strong && b.monsterCount > 0, "Philosopher's Stone gives enemies 1 Strength");
    }
    {
        auto b = battle_with({RelicId::DATA_DISK});
        check(b.player_power(PowerId::FOCUS) == 1, "Data Disk grants 1 Focus");
    }
    {
        auto b = battle_with({RelicId::RUNIC_CAPACITOR});
        check(b.defect.orbCapacity == 3, "Runic Capacitor adds 3 orb slots");
    }
    {
        auto b = battle_with({RelicId::SYMBIOTIC_VIRUS});
        check(b.defect.orbCount == 1 && b.defect.orbs[0].id == OrbId::DARK,
              "Symbiotic Virus channels a Dark orb");
    }
    {
        auto b = battle_with({RelicId::FENCING_MANUAL});
        check(count_in_hand(b, CardId::SOVEREIGN_BLADE) == 1,
              "Fencing Manual forges a Sovereign Blade");
    }
    {
        auto b = battle_with({RelicId::NINJA_SCROLL});
        check(count_in_hand(b, CardId::SHIV) == 3, "Ninja Scroll adds three Shivs");
    }
    {
        // Big Hat samples from the character's own pool; the Ironclad pool has
        // no Ethereal cards, so Defect is used here.
        auto b = battle_with({RelicId::BIG_HAT}, {}, Encounter::SETUP_BATTLEWORN_DUMMY_V1,
                             CardPool::NECROBINDER);
        check(count_hand_where(b, is_ethereal) == 2,
              "Big Hat adds two Ethereal character cards");
    }
    {
        auto b = battle_with({RelicId::ORANGE_DOUGH});
        check(count_hand_where(b, is_colorless_card) == 2,
              "Orange Dough adds two colorless cards");
    }
    {
        auto b = battle_with({RelicId::POWER_CELL},
                             {CardId::SHIV, CardId::SHIV, CardId::SHIV, CardId::SHIV,
                              CardId::SHIV, CardId::SHIV, CardId::SHIV, CardId::SHIV});
        check(count_in_hand(b, CardId::SHIV) == 7,
              "Power Cell moves two zero-cost cards to the hand");
    }
    {
        auto b = battle_with({RelicId::PHYLACTERY_UNBOUND});
        check(b.necro.ostyPresent && b.necro.ostyHp == 7,
              "Phylactery Unbound summons Osty 5 + 2");
    }
    {
        // ---- combat start: turn-1 stances --------------------------------
        auto b = battle_with({RelicId::BELT_BUCKLE});
        const int slot = relic_slot(b, RelicId::BELT_BUCKLE);
        check(b.player.dexterity == 2 && b.relicAux[slot] == 1,
              "Belt Buckle grants 2 Dexterity with an empty belt");
        relics_potion_obtained(b);
        check(b.player.dexterity == 0 && b.relicAux[slot] == 0,
              "Belt Buckle drops its Dexterity when a potion is obtained");
        relics_potion_used(b);
        check(b.player.dexterity == 2 && b.relicAux[slot] == 1,
              "Belt Buckle restores its Dexterity when the belt empties");
    }

    // ---- turn-1 hand / draw relics ---------------------------------------
    {
        auto b = battle_with({RelicId::BELLOWS});
        bool allUpgraded = true;
        for (int i = 0; i < b.handCount; ++i) allUpgraded = allUpgraded && b.hand[i].upgraded;
        check(b.handCount > 0 && allUpgraded, "Bellows upgrades the opening hand");
    }
    {
        auto b = battle_with({RelicId::GAMBLING_CHIP});
        check(b.pending.op == ChoiceOp::DISCARD_ANY,
              "Gambling Chip opens the discard-any choice on turn 1");
    }
    {
        auto b = battle_with({RelicId::RADIANT_PEARL});
        check(count_in_hand(b, CardId::LUMINESCE) >= 1,
              "Radiant Pearl adds Luminesce");
    }
    {
        auto b = battle_with({RelicId::CROSSBOW});
        check(count_hand_where(b, is_attack_cost_zero) >= 1,
              "Crossbow adds a zero-cost Attack");
    }
    {
        auto b = battle_with({RelicId::VEXING_PUZZLEBOX});
        bool freeCard = false;
        for (int i = 0; i < b.handCount; ++i) freeCard = freeCard || b.hand[i].freeCombat;
        check(freeCard, "Vexing Puzzlebox adds a free character card");
    }
    {
        auto b = battle_with({RelicId::RING_OF_THE_SNAKE});
        check(relics_modify_draw(b, 5) == 7 && b.turn == 1,
              "Ring of the Snake draws +2 on turn 1");
        b.turn = 2;
        check(relics_modify_draw(b, 5) == 5, "Ring of the Snake is idle after turn 1");
    }
    {
        auto b = battle_with({RelicId::RING_OF_THE_DRAKE});
        check(relics_modify_draw(b, 5) == 7, "Ring of the Drake draws +2 on turn 1");
        b.turn = 3;
        check(relics_modify_draw(b, 5) == 7, "Ring of the Drake draws +2 on turn 3");
        b.turn = 4;
        check(relics_modify_draw(b, 5) == 5, "Ring of the Drake is idle after turn 3");
    }
    {
        auto b = battle_with({RelicId::POCKETWATCH});
        b.turn = 2;
        b.cardsPlayedLastTurn = 3;
        check(relics_modify_draw(b, 5) == 8, "Pocketwatch draws +3 after <=3 cards");
        b.cardsPlayedLastTurn = 4;
        check(relics_modify_draw(b, 5) == 5, "Pocketwatch is idle after 4 cards");
    }

    // ---- energy ----------------------------------------------------------
    {
        auto b = battle_with({RelicId::CANDELABRA});
        b.turn = 1;
        check(relics_energy_for_turn(b, 3) == 3, "Candelabra idle on turn 1");
        b.turn = 2;
        check(relics_energy_for_turn(b, 3) == 5, "Candelabra grants 2 on turn 2");
    }
    {
        auto b = battle_with({RelicId::CHANDELIER});
        b.turn = 3;
        check(relics_energy_for_turn(b, 3) == 6, "Chandelier grants 3 on turn 3");
    }
    {
        auto b = battle_with({RelicId::BREAD});
        b.turn = 1;
        check(relics_energy_for_turn(b, 3) == 2, "Bread costs one energy on turn 1");
        b.turn = 2;
        check(relics_energy_for_turn(b, 3) == 4, "Bread grants one energy after turn 1");
    }
    {
        auto b = battle_with({RelicId::ICE_CREAM});
        b.turn = 1;
        check(relics_energy_for_turn(b, 3) == 3, "Ice Cream keeps turn-1 energy");
        b.turn = 2;
        b.player.energy = 2;
        check(relics_energy_for_turn(b, 3) == 5, "Ice Cream carries unspent energy");
    }

    // ---- turn start ------------------------------------------------------
    {
        auto b = battle_with({RelicId::BRIMSTONE});
        check(b.player_power(PowerId::STRENGTH) == 2,
              "Brimstone grants 2 Strength once per turn");
        check(b.monsters[0].strength == 1, "Brimstone grants enemies 1 Strength");
    }
    {
        auto b = battle_with({RelicId::FAKE_ANCHOR});
        check(b.player.block == 4, "Fake Anchor grants 4 block on turn 1");
    }
    {
        auto b = battle_with({RelicId::FAKE_BLOOD_VIAL});
        check(b.player.hp == 151, "Fake Blood Vial heals 1 on turn 1");
    }
    {
        auto b = battle_with({RelicId::SAI});
        check(b.player.block == 7, "Sai grants 7 block at turn start");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::MERCURY_HOURGLASS});
        check(plain.monsters[0].hp - b.monsters[0].hp == 3,
              "Mercury Hourglass deals 3 at turn start");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::STONE_CALENDAR});
        check(plain.monsters[0].hp == b.monsters[0].hp,
              "Stone Calendar is idle before turn 7");
        b.turn = 7;
        relics_turn_start(b);
        check(plain.monsters[0].hp - b.monsters[0].hp == 52,
              "Stone Calendar deals 52 on turn 7");
    }
    {
        auto b = battle_with({RelicId::HORN_CLEAT});
        b.turn = 2;
        relics_turn_start(b);
        check(b.player.block == 14, "Horn Cleat grants 14 block on turn 2");
    }
    {
        auto b = battle_with({RelicId::CAPTAINS_WHEEL});
        b.turn = 3;
        relics_turn_start(b);
        check(b.player.block == 18, "Captain's Wheel grants 18 block on turn 3");
    }
    {
        auto b = battle_with({RelicId::SPARKLING_ROUGE});
        b.turn = 3;
        relics_turn_start(b);
        check(b.player_power(PowerId::STRENGTH) == 1 && b.player.dexterity == 1,
              "Sparkling Rouge grants Strength and Dexterity on turn 3");
    }
    {
        auto b = battle_with({RelicId::EMOTION_CHIP});
        defect_channel(b, OrbId::LIGHTNING);
        const int idx = relic_slot(b, RelicId::EMOTION_CHIP);
        b.relicAux[idx] = 1;
        const int hp = b.monsters[0].hp;
        relics_turn_start(b);
        check(hp - b.monsters[0].hp == 3,
              "Emotion Chip triggers an orb passive after unblocked damage");
        check(b.relicAux[idx] == 0, "Emotion Chip consumes its flag");
    }
    {
        auto b = battle_with({RelicId::DIVINE_DESTINY});
        check(b.regent.stars == 7, "Divine Destiny grants 7 stars on turn 1");
    }

    // ---- stars / generated cards -----------------------------------------
    {
        auto b = battle_with({RelicId::MINI_REGENT});
        relics_stars_spent(b, 1);
        check(b.player_power(PowerId::STRENGTH) == 1,
              "Mini Regent grants Strength on the first star spend");
        relics_stars_spent(b, 1);
        check(b.player_power(PowerId::STRENGTH) == 1,
              "Mini Regent is once per turn");
        relics_turn_start(b);
        relics_stars_spent(b, 1);
        check(b.player_power(PowerId::STRENGTH) == 2,
              "Mini Regent resets at the next turn");
    }
    {
        auto b = battle_with({RelicId::REGALITE});
        Card generated = make_card(CardId::STRIKE_IRONCLAD, false, 900);
        relics_card_generated(b, generated);
        check(b.player.block == 4, "Regalite grants 4 block when a card is generated");
        relics_card_generated(b, generated);
        check(b.player.block == 4, "Regalite is once per turn");
    }
    {
        auto b = battle_with({RelicId::GALACTIC_DUST});
        relics_stars_spent(b, 10);
        check(b.player.block == 10, "Galactic Dust converts 10 stars into 10 block");
    }
    {
        auto b = battle_with({RelicId::LUNAR_PASTRY});
        relics_turn_end(b);
        check(b.regent.stars == 1, "Lunar Pastry grants 1 star at turn end");
    }

    // ---- card play hooks -------------------------------------------------
    {
        auto b = battle_with({RelicId::KUNAI});
        for (int i = 0; i < 3; ++i) play(b, 0, 0);
        check(b.player.dexterity == 1, "Kunai grants Dexterity on every third attack");
    }
    {
        auto b = battle_with({RelicId::SHURIKEN});
        for (int i = 0; i < 3; ++i) play(b, 0, 0);
        check(b.player_power(PowerId::STRENGTH) == 1,
              "Shuriken grants Strength on every third attack");
    }
    {
        auto b = battle_with({RelicId::ORNAMENTAL_FAN});
        for (int i = 0; i < 3; ++i) play(b, 0, 0);
        check(b.player.block == 4, "Ornamental Fan grants 4 block on every third attack");
    }
    {
        auto b = battle_with({RelicId::HELICAL_DART});
        b.hand[b.handCount++] = make_card(CardId::SHIV, false, 800);
        play(b, b.handCount - 1, 0);
        check(b.player.tempDexterity == 1, "Helical Dart grants temporary Dexterity for a Shiv");
    }
    {
        auto b = battle_with({RelicId::IVORY_TILE});
        b.player.energy = 10;
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 801);
        play(b, b.handCount - 1, -1);
        check(b.player.energy == 8, "Ivory Tile refunds 1 energy after a 3-cost card");
    }
    {
        auto b = battle_with({RelicId::PERMAFROST});
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 802);
        play(b, b.handCount - 1, -1);
        check(b.player.block == 6, "Permafrost grants 6 block for the first Power");
        b.hand[b.handCount++] = make_card(CardId::TANK_CARD, false, 803);
        play(b, b.handCount - 1, -1);
        check(b.player.block == 6, "Permafrost triggers once per combat");
    }
    {
        auto b = battle_with({RelicId::GAME_PIECE});
        const int draw = b.drawCount;
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 804);
        play(b, b.handCount - 1, -1);
        check(b.drawCount == draw - 1, "Game Piece draws a card for a Power");
    }
    {
        auto b = battle_with({RelicId::RAINBOW_RING});
        b.handCount = 0;
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 805);
        b.hand[b.handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 806);
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 807);
        play(b, 0, 0);                 // Strike (attack)
        play(b, 0, -1);                // Defend (skill)
        play(b, 0, -1);                // Demon Form (power)
        check(b.player_power(PowerId::STRENGTH) == 1 && b.player.dexterity == 1,
              "Rainbow Ring grants Strength and Dexterity for all three types");
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 808);
        play(b, 0, 0);
        check(b.player_power(PowerId::STRENGTH) == 1,
              "Rainbow Ring does not trigger again after all three types");
    }
    {
        auto b = battle_with({RelicId::UNCEASING_TOP});
        b.handCount = 0;
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 809);
        const int draw = b.drawCount;
        play(b, 0, 0);
        check(b.drawCount == draw - 1, "Unceasing Top draws when the hand is empty");
    }
    {
        auto b = battle_with({RelicId::RAZOR_TOOTH});
        b.hand[b.handCount++] = make_card(CardId::BASH, false, 810);
        play(b, b.handCount - 1, 0);
        bool upgradedCopy = false;
        for (int i = 0; i < b.discardCount; ++i)
            if (b.discard[i].uid == 810) upgradedCopy = b.discard[i].upgraded;
        check(upgradedCopy, "Razor Tooth upgrades an Attack after it is played");
    }
    {
        auto b = battle_with({RelicId::SNECKO_SKULL});
        b.add_monster_power(0, PowerId::POISON, 1);
        check(b.monsters[0].power[static_cast<int>(PowerId::POISON)] == 2,
              "Snecko Skull adds 1 to applied Poison");
    }
    {
        auto b = battle_with({RelicId::UNSETTLING_LAMP});
        b.activePlay.active = true;  // the lamp only sees card-applied debuffs
        b.add_monster_power(0, PowerId::WEAK, 1);
        b.activePlay.active = false;
        check(b.monsters[0].weak == 2,
              "Unsettling Lamp doubles the first card-applied debuff");
        b.activePlay.active = true;
        b.add_monster_power(0, PowerId::WEAK, 1);
        b.activePlay.active = false;
        check(b.monsters[0].weak == 3, "Unsettling Lamp triggers once per combat");
    }
    {
        auto b = battle_with({RelicId::MYSTIC_LIGHTER});
        Card enchanted = make_card(CardId::STRIKE_IRONCLAD, false, 811);
        enchanted.enchantment = EnchantmentId::SHARP;
        enchanted.enchantmentAmount = 1;
        const int withRelic = b.calc_player_damage(6, 0, true, &enchanted);
        auto plain = battle_with({});
        const int without = plain.calc_player_damage(6, 0, true, &enchanted);
        // Sharp +1 and Mystic Lighter +9: 6+1+9 = 16 versus 6+1 = 7.
        check(withRelic == 16 && without == 7,
              "Mystic Lighter adds 9 to enchanted Attack damage");
    }
    {
        auto b = battle_with({RelicId::PAPER_PHROG});
        b.monsters[0].vulnerable = 1;
        Card strike = make_card(CardId::STRIKE_IRONCLAD, false, 812);
        const int withRelic = b.calc_player_damage(10, 0, true, &strike);
        auto plain = battle_with({});
        plain.monsters[0].vulnerable = 1;
        const int without = plain.calc_player_damage(10, 0, true, &strike);
        check(withRelic == 17 && without == 15,
              "Paper Phrog raises Vulnerable damage to 1.75x");
    }
    {
        auto b = battle_with({RelicId::PAPER_KRANE});
        const int withRelic = b.calc_monster_damage(b.monsters[0], 10);
        auto plain = battle_with({});
        const int without = plain.calc_monster_damage(plain.monsters[0], 10);
        check(withRelic == 8 && without == 10,
              "Paper Krane reduces incoming powered attacks by 15%");
    }
    {
        auto b = battle_with({RelicId::MINIATURE_CANNON});
        Card up = make_card(CardId::STRIKE_IRONCLAD, true, 813);
        check(b.calc_player_damage(9, 0, true, &up) == 12,
              "Miniature Cannon adds 3 to upgraded Attacks");
        Card basic = make_card(CardId::STRIKE_IRONCLAD, false, 814);
        check(b.calc_player_damage(6, 0, true, &basic) == 6,
              "Miniature Cannon ignores unupgraded Attacks");
    }
    {
        auto b = battle_with({RelicId::THROWING_AXE});
        const int hp = b.monsters[0].hp;
        play(b, 0, 0);
        check(hp - b.monsters[0].hp == 12,
              "Throwing Axe replays the first Attack once per combat");
        const int hp2 = b.monsters[0].hp;
        play(b, 0, 0);
        check(hp2 - b.monsters[0].hp == 6,
              "Throwing Axe is spent after its first Attack");
    }
    {
        auto b = battle_with({RelicId::VITRUVIAN_MINION});
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::MINION_STRIKE, false, 815);
        play(b, b.handCount - 1, 0);
        check(hp - b.monsters[0].hp == card_damage(make_card(CardId::MINION_STRIKE, false, 0)) * 2,
              "Vitruvian Minion doubles Minion card damage");
    }
    {
        auto b = battle_with({RelicId::SPIKED_GAUNTLETS});
        b.player.energy = 3;
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 816);
        check(!play(b, b.handCount - 1, -1),
              "Spiked Gauntlets makes a 3-cost Power cost 4");
        b.player.energy = 4;
        check(play(b, b.handCount - 1, -1),
              "Spiked Gauntlets still allows the Power at 4 energy");
    }

    // ---- damage received / hp loss ---------------------------------------
    {
        auto b = battle_with({RelicId::BEATING_REMNANT});
        b.hpLostThisTurn = 15;
        check(relics_modify_hp_loss(b, 10) == 5,
              "Beating Remnant caps damage at 20 per turn");
    }
    {
        auto b = battle_with({RelicId::CENTENNIAL_PUZZLE});
        const int draw = b.drawCount;
        relics_damage_received(b, 5);
        check(b.drawCount == draw - 3, "Centennial Puzzle draws 3 after damage");
        relics_damage_received(b, 5);
        check(b.drawCount == draw - 3, "Centennial Puzzle triggers once");
    }
    {
        auto b = battle_with({RelicId::DEMON_TONGUE});
        b.player.hp = 100;
        relics_damage_received(b, 5);
        check(b.player.hp == 105, "Demon Tongue heals unblocked damage");
        relics_damage_received(b, 5);
        check(b.player.hp == 105, "Demon Tongue triggers once per turn");
    }

    // ---- discard / exhaust / shuffle / death ----------------------------
    {
        auto b = battle_with({RelicId::TOUGH_BANDAGES});
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, 817);
        relics_card_discarded(b, c);
        check(b.player.block == 3, "Tough Bandages grants 3 block on discard");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::TINGSHA});
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, 818);
        relics_card_discarded(b, c);
        check(plain.monsters[0].hp - b.monsters[0].hp == 3,
              "Tingsha deals 3 when a card is discarded");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::CHARONS_ASHES});
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, 819);
        relics_exhausted(b, c, false);
        check(plain.monsters[0].hp - b.monsters[0].hp == 3,
              "Charon's Ashes deals 3 when a card is exhausted");
    }
    {
        auto b = battle_with({RelicId::BURNING_STICKS});
        const int hand = b.handCount;
        Card skill = make_card(CardId::DEFEND_IRONCLAD, false, 820);
        relics_exhausted(b, skill, false);
        check(b.handCount == hand + 1 && b.hand[b.handCount - 1].id == CardId::DEFEND_IRONCLAD,
              "Burning Sticks copies the first exhausted Skill");
        relics_exhausted(b, skill, false);
        check(b.handCount == hand + 1, "Burning Sticks triggers once per combat");
    }
    {
        auto b = battle_with({RelicId::PENDULUM});
        const int draw = b.drawCount;
        relics_shuffled(b);
        check(b.drawCount == draw - 1, "Pendulum draws a card on shuffle");
    }
    {
        auto b = battle_with({RelicId::THE_ABACUS});
        relics_shuffled(b);
        check(b.player.block == 6, "The Abacus grants 6 block on shuffle");
    }
    {
        auto b = battle_with({RelicId::BOOKMARK});
        Card retained[1];
        retained[0] = make_card(CardId::STRIKE_IRONCLAD, false, 821);
        retained[0].costForTurn = 2;
        relics_after_flush(b, retained, 1);
        check(card_cost(retained[0]) == 1, "Bookmark reduces a retained card's cost by 1");
    }
    {
        auto b = battle_with({RelicId::GREMLIN_HORN});
        const int energy = b.player.energy;
        const int draw = b.drawCount;
        relics_monster_died(b);
        check(b.player.energy == energy + 1 && b.drawCount == draw - 1,
              "Gremlin Horn grants energy and a card on kill");
    }

    // ---- turn end --------------------------------------------------------
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::SCREAMING_FLAGON});
        b.handCount = 0;
        relics_turn_end(b);
        check(plain.monsters[0].hp - b.monsters[0].hp == 20,
              "Screaming Flagon deals 20 with an empty hand");
    }
    {
        auto b = battle_with({RelicId::CLOAK_CLASP});
        b.handCount = 4;
        relics_turn_end(b);
        check(b.player.block == 4, "Cloak Clasp grants block equal to the hand size");
    }
    {
        auto b = battle_with({RelicId::RIPPLE_BASIN});
        b.attacksPlayedThisTurn = 0;
        relics_turn_end(b);
        check(b.player.block == 4, "Ripple Basin grants 4 block without attacks");
        auto b2 = battle_with({RelicId::RIPPLE_BASIN});
        b2.player.block = 0;
        b2.attacksPlayedThisTurn = 1;
        relics_turn_end(b2);
        check(b2.player.block == 0, "Ripple Basin is idle after an attack");
    }
    {
        auto plain = battle_with({});
        auto b = battle_with({RelicId::PARRYING_SHIELD});
        b.player.block = 10;
        relics_turn_end(b);
        check(plain.monsters[0].hp - b.monsters[0].hp == 6,
              "Parrying Shield deals 6 when ending with 10 block");
    }
    {
        auto b = battle_with({RelicId::STURDY_CLAMP});
        check(relics_block_retain(b) == 10, "Sturdy Clamp retains up to 10 block");
    }
    {
        auto b = battle_with({RelicId::REPTILE_TRINKET});
        relics_potion_used(b);
        check(b.player.tempStrength == 3, "Reptile Trinket grants 3 temporary Strength");
    }
    {
        auto b = battle_with({RelicId::ICE_CREAM});
        check(!relics_keep_energy(b), "relics_keep_energy stays false (Ice Cream is handled per turn)");
    }

    // ---- run-level obtains ----------------------------------------------
    {
        RunContext r; r.init(123u, 0);
        const int hp = r.hp, maxHp = r.maxHp;
        check(r.add_relic(RelicId::MANGO), "Mango obtains");
        check(r.maxHp == maxHp + 14 && r.hp == hp + 14, "Mango grants 14 max HP");
    }
    {
        RunContext r; r.init(123u, 0);
        r.hp = 40;
        const int maxHp = r.maxHp;
        check(r.add_relic(RelicId::LEES_WAFFLE), "Lee's Waffle obtains");
        check(r.maxHp == maxHp + 7 && r.hp == r.maxHp,
              "Lee's Waffle grants 7 max HP and a full heal");
    }
    {
        RunContext r; r.init(123u, 0);
        const int slots = r.potionSlots;
        check(r.add_relic(RelicId::POTION_BELT), "Potion Belt obtains");
        check(r.potionSlots == slots + 2, "Potion Belt adds two potion slots");
    }
    {
        RunContext r; r.init(123u, 0);
        r.add_relic(RelicId::DIVINE_RIGHT);
        r.begin_combat(Encounter::SETUP_BATTLEWORN_DUMMY_V1);
        check(r.battle.regent.stars == 3, "Divine Right grants 3 stars on room entry");
    }
    {
        RunContext plain; plain.init(123u, 0);
        plain.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
        plain.battle.outcome = Outcome::PLAYER_VICTORY;
        plain.finish_combat();
        int baseRewards = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) baseRewards += plain.rewardCardPending[i] ? 1 : 0;

        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::PRAYER_WHEEL), "Prayer Wheel obtains");
        r.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        int withWheel = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) withWheel += r.rewardCardPending[i] ? 1 : 0;
        check(withWheel == baseRewards + 1,
              "Prayer Wheel adds one card reward to a normal combat");
    }
    {
        // Chosen Cheese grants 1 max HP after a victorious combat.
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::CHOSEN_CHEESE), "Chosen Cheese obtains");
        const int maxHp = r.maxHp;
        r.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check(r.maxHp == maxHp + 1, "Chosen Cheese grants 1 max HP after combat");
    }
    {
        // Electric Shrymp: choose one deck Skill and enchant it with Imbued.
        RunContext r; r.init(123u, 0);
        check(r.add_relic(RelicId::ELECTRIC_SHRYMP), "Electric Shrymp obtains");
        check(r.cardGrid.kind == 23, "Electric Shrymp opens the Imbued selector");
        int pick = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (card_can_enchant(r.deck[i], EnchantmentId::IMBUED)) { pick = i; break; }
        check(pick >= 0, "Electric Shrymp has a deck Skill to enchant");
        if (pick >= 0) {
            RunAction select{};
            select.type = RunActionType::SELECT_GRID_CARD;
            select.index = pick;
            // kind 23 has maxSelect == 1, so the selector confirms itself.
            check(r.step(select), "Electric Shrymp accepts the Skill selection");
            check(r.cardGrid.kind == 0, "Electric Shrymp selector closes");
            check(r.deck[pick].enchantment == EnchantmentId::IMBUED,
                  "Electric Shrymp enchants the chosen Skill with Imbued");
        }
    }
    {
        // Ghost Seed affects Basic Strike/Defend of every character pool, not
        // just the Ironclad starter.
        RunContext r; r.init(123u, 0, CardPool::SILENT);
        r.add_relic(RelicId::GHOST_SEED);
        CardId basicStrike = basic_strike_of(CardPool::SILENT);
        const CardId basicDefend = CardId::DEFEND_SILENT;
        int seenStrike = 0, seenDefend = 0;
        r.begin_combat(Encounter::SETUP_BATTLEWORN_DUMMY_V1);
        for (int i = 0; i < r.battle.drawCount; ++i) {
            if (r.battle.draw[i].id == basicStrike && r.battle.draw[i].etherealThisCombat)
                ++seenStrike;
            if (r.battle.draw[i].id == basicDefend && r.battle.draw[i].etherealThisCombat)
                ++seenDefend;
        }
        for (int i = 0; i < r.battle.handCount; ++i) {
            if (r.battle.hand[i].id == basicStrike && r.battle.hand[i].etherealThisCombat)
                ++seenStrike;
            if (r.battle.hand[i].id == basicDefend && r.battle.hand[i].etherealThisCombat)
                ++seenDefend;
        }
        check(seenStrike > 0 && seenDefend > 0,
              "Ghost Seed makes every character's Basic Strike/Defend Ethereal");
    }
    {
        // Miniature Tent: the rest site stays open after an option and closes
        // through the explicit leave action.
        RunContext r; r.init(123u, 0);
        r.add_relic(RelicId::MINIATURE_TENT);
        r.screen = RunScreen::REST;
        const int tent = [&] {
            for (int i = 0; i < r.relicCount; ++i)
                if (r.relics[i] == static_cast<int>(RelicId::MINIATURE_TENT)) return i;
            return -1;
        }();
        r.relicAux[tent] = 0;
        r.hp = 20;
        const int hp = r.hp;
        RunAction heal{};
        heal.type = RunActionType::REST_HEAL;
        check(r.step(heal), "Miniature Tent rest heal succeeds");
        check(r.hp > hp && r.screen == RunScreen::REST,
              "Miniature Tent keeps the rest site open after healing");
        bool leave = false, upgrade = false;
        for (const auto &a : r.legal_actions()) {
            leave = leave || a.type == RunActionType::REST_LEAVE;
            upgrade = upgrade || a.type == RunActionType::REST_UPGRADE;
        }
        check(leave, "Miniature Tent exposes the leave action");
        check(upgrade, "Miniature Tent leaves other options available");
        check(!r.step(heal), "Miniature Tent cannot use the same option twice");
        RunAction leaveAction{};
        leaveAction.type = RunActionType::REST_LEAVE;
        check(r.step(leaveAction), "Miniature Tent leave action succeeds");
        check(r.screen == RunScreen::MAP, "Leaving the tent rest site returns to the map");
    }

    // ---- event / ancient relics -----------------------------------------
    {
        // AlchemicalCoffer.AfterObtained: +4 physical slots, then fill each new
        // slot with one generated potion.
        RunContext r; r.init(123u, 0);
        const int slots = r.potionSlots;
        check(r.add_relic(RelicId::ALCHEMICAL_COFFER), "Alchemical Coffer obtains");
        check(r.potionSlots == slots + 4 && r.potionCount == 4,
              "Alchemical Coffer adds four slots and four potions");
        bool filled = true;
        for (int i = slots; i < slots + 4; ++i) filled = filled && r.potions[i] != 0;
        check(filled, "Alchemical Coffer fills the new slots");
    }
    {
        // ArchaicTooth: the starter Bash becomes Break (upgrade state kept).
        RunContext r; r.init(123u, 0);
        int bash = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (r.deck[i].id == CardId::BASH) { bash = i; r.deck[i].upgraded = true; break; }
        check(bash >= 0, "Archaic Tooth test deck has Bash");
        check(r.add_relic(RelicId::ARCHAIC_TOOTH), "Archaic Tooth obtains");
        check(bash >= 0 && r.deck[bash].id == CardId::BREAK && r.deck[bash].upgraded,
              "Archaic Tooth turns Bash into Break and keeps the upgrade");
    }
    {
        // Ectoplasm: no gold can be gained (battle and run layers).
        auto b = battle_with({RelicId::ECTOPLASM});
        b.gain_gold(50);
        check(b.gold == 0, "Ectoplasm blocks combat gold gain");
        RunContext r; r.init(123u, 0);
        r.add_relic(RelicId::ECTOPLASM);
        const int gold = r.gold;
        run_gain_gold(r, 50);
        check(r.gold == gold, "Ectoplasm blocks run gold gain");
    }
    {
        auto b = battle_with({RelicId::FAKE_HAPPY_FLOWER});
        // combat init already consumed turn 1.
        int bonus = 0;
        for (int i = 0; i < 4; ++i) bonus = relics_energy_for_turn(b, 3) - 3;
        check(bonus == 1, "Fake Happy Flower pays out on the fifth turn");
    }
    {
        RunContext r; r.init(123u, 0);
        r.hp = 40;
        const int maxHp = r.maxHp;
        check(r.add_relic(RelicId::FAKE_LEES_WAFFLE), "Fake Lee's Waffle obtains");
        check(r.maxHp == maxHp && r.hp == 40 + maxHp / 10,
              "Fake Lee's Waffle heals 10% without raising max HP");
    }
    {
        RunContext r; r.init(123u, 0);
        const int hp = r.hp, maxHp = r.maxHp;
        check(r.add_relic(RelicId::FAKE_MANGO), "Fake Mango obtains");
        check(r.maxHp == maxHp + 3 && r.hp == hp + 3,
              "Fake Mango grants 3 max HP");
    }
    {
        auto b = battle_with({RelicId::FAKE_ORICHALCUM});
        b.player.block = 0;
        relics_turn_end(b);
        check(b.player.block == 3, "Fake Orichalcum grants 3 block at turn end");
    }
    {
        // Fake Snecko Eye randomizes drawn card costs but keeps the normal draw.
        auto plain = battle_with({});
        const int plainDraw = relics_modify_draw(plain, 5);
        auto b = battle_with({RelicId::FAKE_SNECKO_EYE});
        check(relics_modify_draw(b, 5) == plainDraw,
              "Fake Snecko Eye adds no cards");
        int randomized = 0;
        for (int i = 0; i < b.handCount; ++i)
            if (card_cost(b.hand[i]) != card_cost(plain.hand[i])) ++randomized;
        check(randomized > 0, "Fake Snecko Eye randomizes opening hand costs");
    }

    std::cout << "relic coverage round7: " << checks << " checks, " << failures
              << " failures\n";
    return failures ? 1 : 0;
}
