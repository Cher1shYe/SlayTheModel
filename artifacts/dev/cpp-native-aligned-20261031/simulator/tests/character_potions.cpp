// Character potions: per-character drops and the ten epoch-4 potion effects.
// Evidence level: behaviour read from the reference decompilation of the local
// build (0861bfa1...), not a differential against the unavailable target DLL.
#include "sts2/battle.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
BattleContext battle() {
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 100 + i);
    BattleContext b;
    b.init(Encounter::SETUP_CULTISTS_NORMAL, 21, deck, 10, 0, 500, 500);
    b.monsters[0].hp = 500;
    return b;
}
int hand_count_id(const BattleContext &b, CardId id) {
    int n = 0;
    for (int i = 0; i < b.handCount; ++i) n += b.hand[i].id == id ? 1 : 0;
    return n;
}
}

int main() {
    {
        // FocusPotion: +2 Focus.
        auto b = battle();
        b.add_potion(PotionId::FOCUS_POTION);
        check(b.can_use_potion(0), "Focus Potion is usable in combat");
        b.use_potion(0, -1);
        check(b.player_power(PowerId::FOCUS) == 2, "Focus Potion grants two Focus");
        check(b.potions[0] == 0, "Focus Potion is consumed");
    }
    {
        // PoisonPotion: 6 Poison to one enemy.
        auto b = battle();
        b.add_potion(PotionId::POISON_POTION);
        b.use_potion(0, 0);
        check(b.monsters[0].power[static_cast<int>(PowerId::POISON)] == 6,
              "Poison Potion applies six Poison");
    }
    {
        // PotionOfDoom: 33 Doom to one enemy.
        auto b = battle();
        b.add_potion(PotionId::POTION_OF_DOOM);
        b.use_potion(0, 0);
        check(b.monsters[0].power[static_cast<int>(PowerId::DOOM)] == 33,
              "Potion of Doom applies 33 Doom");
    }
    {
        // StarPotion: +3 stars.
        auto b = battle();
        b.add_potion(PotionId::STAR_POTION);
        b.use_potion(0, -1);
        check(b.regent.stars == 3, "Star Potion grants three stars");
    }
    {
        // BoneBrew: summon Osty with 15 HP.
        auto b = battle();
        b.add_potion(PotionId::BONE_BREW);
        b.use_potion(0, -1);
        check(b.necro.ostyPresent && b.necro.ostyHp == 15 && b.necro.ostyMaxHp == 15,
              "Bone Brew summons a 15 HP Osty");
    }
    {
        // CunningPotion: three upgraded Shivs into the hand.
        auto b = battle();
        b.add_potion(PotionId::CUNNING_POTION);
        b.use_potion(0, -1);
        check(hand_count_id(b, CardId::SHIV) == 3, "Cunning Potion creates three Shivs");
        bool allUpgraded = true;
        for (int i = 0; i < b.handCount; ++i)
            if (b.hand[i].id == CardId::SHIV) allUpgraded = allUpgraded && b.hand[i].upgraded;
        check(allUpgraded, "Cunning Potion Shivs are upgraded");
    }
    {
        // KingsCourage: forge 15 — creates a Sovereign Blade carrying +15.
        auto b = battle();
        b.add_potion(PotionId::KINGS_COURAGE);
        b.use_potion(0, -1);
        int blade = -1;
        for (int i = 0; i < b.handCount; ++i)
            if (b.hand[i].id == CardId::SOVEREIGN_BLADE) blade = i;
        check(blade >= 0, "King's Courage creates a Sovereign Blade");
        check(blade >= 0 && b.hand[blade].bonusDamage == 15,
              "King's Courage forges fifteen damage");
    }
    {
        // PotionOfCapacity: +2 orb slots.
        auto b = battle();
        b.add_potion(PotionId::POTION_OF_CAPACITY);
        b.use_potion(0, -1);
        check(b.defect.orbCapacity == 2, "Potion of Capacity adds two orb slots");
    }
    {
        // EssenceOfDarkness: channel one Dark orb per orb slot.
        auto b = battle();
        b.defect.orbCapacity = 3;
        b.add_potion(PotionId::ESSENCE_OF_DARKNESS);
        b.use_potion(0, -1);
        check(b.defect.orbCount == 3, "Essence of Darkness fills every slot");
        bool allDark = b.defect.orbCount == 3;
        for (int i = 0; i < b.defect.orbCount; ++i)
            allDark = allDark && b.defect.orbs[i].id == OrbId::DARK;
        check(allDark, "Essence of Darkness channels Dark orbs");
    }
    {
        // PotOfGhouls: two Soul cards into the hand.
        auto b = battle();
        b.add_potion(PotionId::POT_OF_GHOULS);
        b.use_potion(0, -1);
        check(hand_count_id(b, CardId::SOUL) == 2, "Pot of Ghouls creates two Souls");
    }
    {
        // Per-character pools: the three epoch potions appear only for their
        // own character; every character also draws shared potions.
        struct Owned { CardPool pool; PotionId a, b, c; };
        const Owned owned[] = {
            {CardPool::IRONCLAD, PotionId::BLOOD_POTION, PotionId::SOLDIERS_STEW, PotionId::ASHWATER},
            {CardPool::SILENT, PotionId::POISON_POTION, PotionId::GHOST_IN_AJAR, PotionId::CUNNING_POTION},
            {CardPool::DEFECT, PotionId::FOCUS_POTION, PotionId::ESSENCE_OF_DARKNESS, PotionId::POTION_OF_CAPACITY},
            {CardPool::REGENT, PotionId::STAR_POTION, PotionId::COSMIC_CONCOCTION, PotionId::KINGS_COURAGE},
            {CardPool::NECROBINDER, PotionId::POTION_OF_DOOM, PotionId::POT_OF_GHOULS, PotionId::BONE_BREW},
        };
        for (const Owned &self : owned) {
            Rng rng(4242);
            bool seen[static_cast<int>(PotionId::COUNT)] = {};
            for (int iter = 0; iter < 400; ++iter) {
                PotionId out[8];
                const int n = random_potions_out_of_combat(rng, out, 8, self.pool);
                for (int i = 0; i < n; ++i) seen[static_cast<int>(out[i])] = true;
            }
            check(seen[static_cast<int>(self.a)] && seen[static_cast<int>(self.b)] &&
                      seen[static_cast<int>(self.c)],
                  "own character potions are in the drop pool");
            check(seen[static_cast<int>(PotionId::ENERGY_POTION)],
                  "shared potions are in every character pool");
            for (const Owned &other : owned) {
                if (other.pool == self.pool) continue;
                check(!seen[static_cast<int>(other.a)] &&
                          !seen[static_cast<int>(other.b)] &&
                          !seen[static_cast<int>(other.c)],
                      "other characters' potions are excluded from the pool");
            }
        }
    }
    std::cout << "character potions: " << checks << " checks, " << failures
              << " failures\n";
    return failures ? 1 : 0;
}
