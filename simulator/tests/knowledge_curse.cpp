// KnowledgeDemon.CurseOfKnowledgeMove: each of the three curse uses offers
// Disintegration (6/7/8 unpowered damage at side turn end) plus one of
// MindRot(1), Sloth(3), WasteAway(1). The chosen status card applies its
// debuff power to the player and never enters a pile.
#include "sts2/battle.h"
#include "sts2/run.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
BattleContext boss(int curseIndex) {
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 100 + i);
    BattleContext b;
    b.init(Encounter::SETUP_KNOWLEDGE_DEMON_BOSS, 42, deck, 10, 0, 500, 500);
    b.monsters[0].aux[0] = static_cast<std::int16_t>(curseIndex);
    return b;
}
int offered(const BattleContext &b, CardId id) {
    for (int i = 0; i < b.pending.count; ++i)
        if (b.pending.cards[i].id == id) return i;
    return -1;
}
bool choose(BattleContext &b, CardId id) {
    const int i = offered(b, id);
    if (i < 0) return false;
    Action a{};
    a.type = ActionType::CHOOSE;
    a.uid = b.pending.cards[i].uid;
    return b.step(a);
}
}

int main() {
    {
        auto b = boss(0);
        b.end_player_turn();
        check(b.pending.op == ChoiceOp::KNOWLEDGE_CURSE, "curse choice offered");
        check(b.pending.count == 2 && !b.pending.optional, "two mandatory offers");
        const int dis = offered(b, CardId::DISINTEGRATION);
        const int rot = offered(b, CardId::MIND_ROT);
        check(dis >= 0 && rot >= 0, "first set is Disintegration + Mind Rot");
        check(dis >= 0 && b.pending.cards[dis].bonusDamage == 6, "first Disintegration is 6");
        check(rot >= 0 && b.pending.cards[rot].bonusDamage == 1, "Mind Rot amount is 1");
        check(choose(b, CardId::MIND_ROT), "choosing Mind Rot resolves the curse");
        check(b.pending.op == ChoiceOp::NONE, "curse choice closes");
        check(b.player_power(PowerId::MIND_ROT) == 1, "Mind Rot applied");
        check(b.turn == 2, "next player turn started");
        check(b.handCount == 4, "Mind Rot reduces the next hand draw to four");
        check(b.handCount + b.drawCount + b.discardCount == 10, "no curse card entered a pile");
    }
    {
        auto b = boss(1);
        b.end_player_turn();
        check(offered(b, CardId::SLOTH_STATUS) >= 0, "second set offers Sloth");
        check(b.pending.cards[offered(b, CardId::DISINTEGRATION)].bonusDamage == 7,
              "second Disintegration is 7");
        check(choose(b, CardId::SLOTH_STATUS), "choosing Sloth resolves the curse");
        check(b.player_power(PowerId::SLOTH) == 3, "Sloth applied");
        int played = 0;
        for (int guard = 0; guard < 8 && played < 3; ++guard) {
            int hand = -1;
            for (const Action &a : b.legal_actions())
                if (a.type == ActionType::PLAY_CARD) { hand = a.hand; break; }
            if (hand < 0) break;
            Action a{};
            a.type = ActionType::PLAY_CARD;
            a.hand = static_cast<std::uint8_t>(hand);
            a.target = 0;
            if (!b.step(a)) break;
            ++played;
        }
        check(played == 3, "three cards fit under Sloth(3)");
        bool fourth = false;
        for (const Action &a : b.legal_actions())
            fourth = fourth || a.type == ActionType::PLAY_CARD;
        check(!fourth && b.player_power(PowerId::SLOTH) == 3,
              "Sloth blocks the fourth card play");
    }
    {
        auto b = boss(2);
        b.end_player_turn();
        check(offered(b, CardId::WASTE_AWAY) >= 0, "third set offers Waste Away");
        check(b.pending.cards[offered(b, CardId::DISINTEGRATION)].bonusDamage == 8,
              "third Disintegration is 8");
        check(choose(b, CardId::WASTE_AWAY), "choosing Waste Away resolves the curse");
        check(b.player_power(PowerId::WASTE_AWAY) == 1, "Waste Away applied");
        check(b.player.energy == 2, "Waste Away reduces max energy to two");
    }
    {
        // DisintegrationPower.AfterSideTurnEndLate: side-end damage is
        // unpowered but blockable; isolate it by clearing the monsters.
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 200 + i);
        BattleContext b;
        b.init(Encounter::SETUP_KNOWLEDGE_DEMON_BOSS, 7, deck, 10, 0, 500, 500);
        b.monsterCount = 0;
        b.add_player_power(PowerId::DISINTEGRATION, 6);
        const int hp = b.player.hp;
        b.end_player_turn();
        check(b.player.hp == hp - 6, "Disintegration deals six at player side end");
    }
    {
        // The pending curse choice round-trips through the run snapshot.
        RunContext rc;
        rc.init(11, 0);
        rc.begin_combat(Encounter::SETUP_KNOWLEDGE_DEMON_BOSS);
        rc.screen = RunScreen::COMBAT;
        rc.inBattle = true;
        rc.battle.end_player_turn();
        rc.battle.clear_card_uid_reservations();
        check(rc.battle.pending.op == ChoiceOp::KNOWLEDGE_CURSE, "run combat reaches the curse choice");
        const std::string blob = rc.serialize();
        RunContext restored;
        check(RunContext::restore(blob, restored), "snapshot with curse choice restores");
        check(restored.battle.pending.op == ChoiceOp::KNOWLEDGE_CURSE &&
              restored.battle.pending.count == 2 &&
              restored.battle.knowledgeCurseResume == 1,
              "restored battle keeps the pending curse and resume flag");
        check(restored.state_hash() == rc.state_hash(), "curse-choice snapshot hash is stable");
    }
    std::cout << "knowledge curse: " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
