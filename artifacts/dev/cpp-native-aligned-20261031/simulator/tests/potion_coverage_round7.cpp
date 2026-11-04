// Main-effect coverage for the potions that previously had no automated test
// reference in the port.
//
// Evidence level: local C++ port (ruleset native-41cef1ea-port-v10), checked
// against the decompiled v0.111.0 classes on the local DLL
// 0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9.
// The target DLL 9cb4f1ad... is not available on this machine, so this is not
// a native differential. Every block covers the full obtain -> use flow through
// the same entry points the agent uses.
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
}  // namespace

int main() {
    {
        auto b = battle();
        b.add_potion(PotionId::DEXTERITY_POTION);
        check(b.can_use_potion(0), "Dexterity Potion is usable in combat");
        b.use_potion(0, -1);
        check(b.player.dexterity == 2, "Dexterity Potion grants 2 Dexterity");
        check(b.potionCount == 0, "Dexterity Potion is consumed");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::POWER_POTION);
        b.use_potion(0, -1);
        check(b.pending.op == ChoiceOp::OFFER_TO_HAND && b.pending.count == 3,
              "Power Potion offers three cards");
        bool allPower = b.pending.count == 3;
        for (int i = 0; i < b.pending.count; ++i)
            allPower = allPower && card_def(b.pending.cards[i].id).type == CardType::POWER;
        check(allPower, "Power Potion offers only Power cards");
        if (b.pending.count > 0) {
            const std::uint16_t uid = b.pending.cards[0].uid;
            const int before = b.handCount;
            b.resolve_choice(uid);
            check(b.pending.op == ChoiceOp::NONE, "Power Potion selection resolves");
            check(b.handCount == before + 1 && b.find_in_hand(uid) != nullptr,
                  "Power Potion adds the chosen card to the hand");
        }
    }
    {
        auto b = battle();
        b.add_potion(PotionId::SKILL_POTION);
        b.use_potion(0, -1);
        check(b.pending.op == ChoiceOp::OFFER_TO_HAND && b.pending.count == 3,
              "Skill Potion offers three cards");
        bool allSkill = b.pending.count == 3;
        for (int i = 0; i < b.pending.count; ++i)
            allSkill = allSkill && card_def(b.pending.cards[i].id).type == CardType::SKILL;
        check(allSkill, "Skill Potion offers only Skill cards");
    }
    {
        auto b = battle();
        const int draw = b.drawCount;
        b.add_potion(PotionId::SWIFT_POTION);
        b.use_potion(0, -1);
        check(b.drawCount == draw - 3, "Swift Potion draws 3 cards");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::WEAK_POTION);
        b.use_potion(0, 0);
        check(b.monsters[0].weak == 3, "Weak Potion applies 3 Weak");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::BLESSING_OF_THE_FORGE);
        b.use_potion(0, -1);
        bool allUpgraded = b.handCount > 0;
        for (int i = 0; i < b.handCount; ++i) allUpgraded = allUpgraded && b.hand[i].upgraded;
        check(allUpgraded, "Blessing of the Forge upgrades the whole hand");
    }
    {
        auto b = battle();
        const int energy = b.player.energy;
        const int draw = b.drawCount;
        b.add_potion(PotionId::CURE_ALL);
        b.use_potion(0, -1);
        check(b.player.energy == energy + 1 && b.drawCount == draw - 2,
              "Cure All grants 1 energy and draws 2");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::DUPLICATOR);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::DUPLICATION) == 1,
              "Duplicator grants one Duplication");
        b.handCount = 0;
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 700);
        const int hp = b.monsters[0].hp;
        Action play{};
        play.type = ActionType::PLAY_CARD;
        play.hand = 0;
        play.target = 0;
        check(b.step(play), "The duplicated card plays");
        check(hp - b.monsters[0].hp == 12, "Duplicator plays the card twice");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::FYSH_OIL);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::STRENGTH) == 1 && b.player.dexterity == 1,
              "Fysh Oil grants 1 Strength and 1 Dexterity");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::GAMBLERS_BREW);
        b.use_potion(0, -1);
        check(b.pending.op == ChoiceOp::DISCARD_ANY && b.pending.pile == ChoicePile::HAND,
              "Gambler's Brew opens the hand discard choice");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::LIQUID_BRONZE);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::THORNS) == 3, "Liquid Bronze grants 3 Thorns");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::POTION_OF_BINDING);
        b.use_potion(0, -1);
        check(b.monsters[0].weak == 1 && b.monsters[0].vulnerable == 1,
              "Potion of Binding gives every enemy 1 Weak and 1 Vulnerable");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::REGEN_POTION);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::REGEN) == 5, "Regen Potion grants 5 Regen");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::STABLE_SERUM);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::RETAIN_HAND) == 2,
              "Stable Serum grants 2 Retain Hand");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::TOUCH_OF_INSANITY);
        b.use_potion(0, -1);
        check(b.pending.op == ChoiceOp::MAKE_FREE && b.pending.remaining == 1,
              "Touch of Insanity selects one hand card");
        if (b.pending.count > 0) {
            const std::uint16_t uid = b.pending.cards[0].uid;
            b.resolve_choice(uid);
            check(b.pending.op == ChoiceOp::NONE, "Touch of Insanity selection resolves");
            const Card *c = b.find_in_hand(uid);
            check(c != nullptr && c->freeCombat && card_cost(*c) == 0,
                  "Touch of Insanity makes the chosen card free");
        }
    }
    {
        auto b = battle();
        const int maxHp = b.player.maxHp;
        b.add_potion(PotionId::FRUIT_JUICE);
        b.use_potion(0, -1);
        check(b.player.maxHp == maxHp + 5 && b.player.hp == b.player.maxHp,
              "Fruit Juice grants 5 max HP and heals 5");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::LUCKY_TONIC);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::BUFFER) == 1, "Lucky Tonic grants 1 Buffer");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::MAZALETHS_GIFT);
        b.use_potion(0, -1);
        check(b.player_power(PowerId::RITUAL) == 1, "Mazaleth's Gift grants 1 Ritual");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::SHIP_IN_ABOTTLE);
        b.use_potion(0, -1);
        check(b.player.block == 10 && b.player_power(PowerId::BLOCK_NEXT_TURN) == 10,
              "Ship in a Bottle grants 10 block now and next turn");
        // end_player_turn runs the enemy turn and the next player turn start.
        b.end_player_turn();
        check(b.turn == 2 && b.player.block == 10 &&
                  b.player_power(PowerId::BLOCK_NEXT_TURN) == 0,
              "Ship in a Bottle pays out at the next turn start");
    }
    {
        auto b = battle();
        b.add_potion(PotionId::POTION_SHAPED_ROCK);
        const int hp = b.monsters[0].hp;
        b.use_potion(0, 0);
        check(hp - b.monsters[0].hp == 15, "Potion Shaped Rock deals 15 damage");
    }

    std::cout << "potion coverage round7: " << checks << " checks, " << failures
              << " failures\n";
    return failures ? 1 : 0;
}
