// Regent lifecycle/cost mechanics.
//
// Evidence level: C# reference reading of the target DLL v0.111.0 decompile
// (star cost/spend, Void Form, Orbit, Monologue, Pale Blue Dot, Sword Sage,
// Arsenal, Reflect, Tyranny, Spectrum Shift, Star Next Turn). These checks do
// not claim fixture differential parity: no native Regent fixture set exists.
#include <iostream>

#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/regent.h"

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(const char *name, int actual, int expected) {
    ++checks;
    const bool ok = actual == expected;
    failures += ok ? 0 : 1;
    std::cout << name << " expected=" << expected << " actual=" << actual << ' '
              << (ok ? "PASS" : "FAIL") << '\n';
}
BattleContext base() {
    BattleContext b;
    Card deck[20];
    for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 20, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.player.energy = 20;
    b.regent.stars = 0;
    return b;
}
void hand(BattleContext &b, CardId id, bool up = false) {
    b.hand[b.handCount++] = make_card(id, up, b.require_card_uid());
}
}  // namespace

int main() {
    {   // CardModel.GetStarCostWithModifiers + HasEnoughResourcesFor.
        auto b = base();
        hand(b, CardId::ASTRAL_PULSE);
        check("star cost unaffordable", b.play_card(0, 0), false);
        b.regent.stars = 3;
        check("star cost affordable", b.play_card(0, 0), true);
        check("stars spent", b.regent.stars, 0);
        check("astral pulse cheap cost", b.player.energy, 20);  // 0-energy card
        const Card stardust = make_card(CardId::STARDUST, false, b.require_card_uid());
        b.regent.stars = 4;
        check("star-x cost reads stars", regent_star_cost(b, stardust), 4);
    }
    {   // VoidFormPower: first Amount manual plays cost 0 energy and 0 stars.
        auto b = base();
        hand(b, CardId::STRIKE_IRONCLAD);
        hand(b, CardId::STRIKE_IRONCLAD);
        hand(b, CardId::STRIKE_IRONCLAD);
        b.add_player_power(PowerId::VOID_FORM, 2);
        regent_reset_turn(b);
        b.player.energy = 3;
        check("void form first play free", b.play_card(0, 0), true);
        check("void form first energy", b.player.energy, 3);
        check("void form second play free", b.play_card(0, 0), true);
        check("void form second energy", b.player.energy, 3);
        check("void form third play costs", b.play_card(0, 0), true);
        check("void form third energy", b.player.energy, 2);
        check("void form manual plays", b.regent.voidFormManualPlays, 3);
    }
    {   // ChildOfTheStarsPower.AfterStarsSpent.
        auto b = base();
        hand(b, CardId::ASTRAL_PULSE);
        b.regent.stars = 3;
        b.add_player_power(PowerId::CHILD_OF_THE_STARS, 2);
        check("child play", b.play_card(0, 0), true);
        check("child block", b.player.block, 6);
    }
    {   // StarNextTurnPower.AfterEnergyReset.
        auto b = base();
        b.add_player_power(PowerId::STAR_NEXT_TURN, 2);
        regent_after_energy_reset(b);
        check("star next turn stars", b.regent.stars, 2);
        check("star next turn removed", b.player_power(PowerId::STAR_NEXT_TURN), 0);
    }
    {   // OrbitPower.AfterEnergySpent: one energy per 4 spent, per instance.
        auto b = base();
        hand(b, CardId::ORBIT);
        check("orbit play", b.play_card(0, 0), true);
        check("orbit instance", b.regent.orbitCount, 1);
        b.player.energy = 10;
        b.regent.orbitEnergy[0] = 0;
        regent_spend_energy(b, 4);
        check("orbit first trigger", b.player.energy, 7);
        regent_spend_energy(b, 4);
        check("orbit second trigger", b.player.energy, 4);
    }
    {   // MonologuePower: Strength per finished card, undone at side turn end.
        auto b = base();
        hand(b, CardId::MONOLOGUE);
        hand(b, CardId::STRIKE_IRONCLAD);
        check("monologue play", b.play_card(0, 0), true);
        check("monologue instance", b.regent.monologueCount, 1);
        check("strike play", b.play_card(0, 0), true);
        check("monologue strength", b.player.strength, 1);
        regent_player_turn_end(b);
        check("monologue restored", b.player.strength, 0);
        check("monologue removed", b.player_power(PowerId::MONOLOGUE), 0);
    }
    {   // PaleBlueDotPower: five finished plays -> draw next turn, once.
        auto b = base();
        b.add_player_power(PowerId::PALE_BLUE_DOT, 2);
        for (int i = 0; i < 5; ++i) hand(b, CardId::STRIKE_IRONCLAD);
        for (int i = 0; i < 5; ++i) check("pale play", b.play_card(0, 0), true);
        check("pale blue dot draw", b.player_power(PowerId::DRAW_CARDS_NEXT_TURN), 2);
        hand(b, CardId::STRIKE_IRONCLAD);
        check("pale play after", b.play_card(0, 0), true);
        check("pale blue dot once", b.player_power(PowerId::DRAW_CARDS_NEXT_TURN), 2);
    }
    {   // SwordSagePower: existing blades gain replay; new blades inherit it.
        auto b = base();
        hand(b, CardId::SOVEREIGN_BLADE);
        hand(b, CardId::SWORD_SAGE);
        check("sword sage play", b.play_card(1, 0), true);
        check("sword sage existing blade", b.hand[0].bonusReplay, 1);
        Card blade = make_card(CardId::SOVEREIGN_BLADE, false, b.require_card_uid());
        b.add_card_to_hand(blade);
        b.notify_card_generated(blade);
        check("sword sage entered blade", b.hand[b.handCount - 1].bonusReplay, 1);
    }
    {   // ArsenalPower.AfterCardGeneratedForCombat + Supermassive history.
        auto b = base();
        b.add_player_power(PowerId::ARSENAL, 2);
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, b.require_card_uid());
        b.add_card_to_hand(c);
        b.notify_card_generated(c);
        check("arsenal strength", b.player.strength, 2);
        check("generated this combat", b.regent.generatedThisCombat, 1);
    }
    {   // ReflectPower: blocked damage reflected, one-turn duration.
        auto b = base();
        b.add_player_power(PowerId::REFLECT, 1);
        const int hp = b.monsters[0].hp;
        regent_reflect_block(b, 0, 5);
        check("reflect damage", b.monsters[0].hp, hp - 5);
        regent_after_side_turn_start(b);
        check("reflect expired", b.player_power(PowerId::REFLECT), 0);
    }
    {   // TyrannyPower.AfterPlayerTurnStart exhausts Amount cards from hand.
        auto b = base();
        b.add_player_power(PowerId::TYRANNY, 1);
        hand(b, CardId::STRIKE_IRONCLAD);
        hand(b, CardId::DEFEND_IRONCLAD);
        regent_after_player_turn_start(b);
        check("tyranny choice", b.pending.op == ChoiceOp::EXHAUST ? 1 : 0, 1);
        check("tyranny candidates", b.pending.count, 2);
        Action pick;
        pick.type = ActionType::CHOOSE;
        pick.uid = b.pending.cards[0].uid;
        check("tyranny choose", b.step(pick), true);
        check("tyranny hand", b.handCount, 1);
        check("tyranny exhaust", b.exhaustCount, 1);
    }
    {   // SpectrumShiftPower.BeforeHandDraw generates to hand.
        auto b = base();
        b.add_player_power(PowerId::SPECTRUM_SHIFT, 1);
        regent_before_hand_draw(b);
        check("spectrum shift hand", b.handCount, 1);
        check("spectrum shift generated", b.regent.generatedThisCombat, 1);
        check("spectrum shift colorless",
              card_def(b.hand[0].id).pool == CardPool::COLORLESS ? 1 : 0, 1);
    }
    {   // BeatIntoShape counts powered player hits this turn.
        auto b = base();
        hand(b, CardId::STRIKE_IRONCLAD);
        check("beat hit play", b.play_card(0, 0), true);
        check("beat hits", b.regent.hitsGivenThisTurn[0], 1);
    }
    std::cout << "Regent mechanics: " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
