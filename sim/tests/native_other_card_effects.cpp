// Colorless, event and shared card effects and turn order against the v0.111.0 decompilation (DEVLOG 45).
#include <cassert>
#include <iostream>
#include <memory>
#include <vector>

#include "sts2/battle.h"
#include "sts2/necrobinder.h"
#include "sts2/regent.h"
#include "sts2/relics.h"

using namespace sts2;

namespace {

std::unique_ptr<BattleContext> battle(int slots = 1, CardId fill = CardId::DEFEND_IRONCLAD) {
    auto b = std::make_unique<BattleContext>();
    std::vector<Card> deck;
    for (int i = 0; i < 30; ++i) deck.push_back(make_card(fill, false, static_cast<std::uint16_t>(i + 1)));
    for (int e = 1; e < 400; ++e) {
        try {
            b->init(static_cast<Encounter>(e), 17, deck.data(), 30, 10, 500, 500, nullptr, 0, nullptr, 0, 3, 0, 3, 0, 0);
            if (b->monsterCount == 1 && b->monsters[0].hp > 30 && b->pending.op == ChoiceOp::NONE) break;
        } catch (const std::exception &) {}
    }
    b->monsters[0].hp = b->monsters[0].maxHp = 5000;
    for (int i = 1; i < slots; ++i) b->monsters[i] = b->monsters[0];
    b->monsterCount = slots;
    b->handCount = 0;
    b->player.energy = 9;
    return b;
}

Card put(BattleContext &b, CardId id) {
    const Card c = make_card(id, false, b.require_card_uid());
    b.hand[b.handCount++] = c;
    return c;
}

bool play(BattleContext &b, std::uint16_t uid) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::PLAY_CARD && b.hand[a.hand].uid == uid) return b.step(a);
    return false;
}

void end_turn(BattleContext &b) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::END_TURN) { assert(b.step(a)); return; }
    assert(false);
}

void neows_fury_lets_the_player_choose() {
    auto b = battle();
    for (int i = 0; i < 3; ++i) b->discard[b->discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b->require_card_uid());
    const int selection = b->cardSelectionRng.counter;
    const Card fury = put(*b, CardId::NEOWS_FURY);
    assert(play(*b, fury.uid));
    assert(b->pending.op == ChoiceOp::DISCARD_TO_HAND && b->pending.optional && b->pending.count == 3);
    assert(b->pending.remaining == 2 && b->cardSelectionRng.counter == selection);
}

void entropy_is_a_choice_after_the_hand_is_drawn() {
    auto b = battle();
    b->add_player_power(PowerId::ENTROPY, 2);
    const int generation = b->cardGenerationRng.counter, selection = b->cardSelectionRng.counter;
    end_turn(*b);
    assert(b->pending.op == ChoiceOp::TRANSFORM && b->pending.remaining == 2 && b->pending.count == 5);
    assert(b->cardGenerationRng.counter == generation && b->cardSelectionRng.counter == selection);
    // Hand selections are picked one by one, then confirmed; replacements keep their slots.
    const std::uint16_t first = b->hand[0].uid, second = b->hand[3].uid;
    for (const std::uint16_t uid : {first, second}) {
        bool chose = false;
        for (const Action &a : b->legal_actions())
            if (a.type == ActionType::CHOOSE && a.uid == uid) { assert(b->step(a)); chose = true; break; }
        assert(chose);
    }
    if (b->pending.op != ChoiceOp::NONE) {
        bool confirmed = false;
        for (const Action &a : b->legal_actions())
            if (a.type == ActionType::CONFIRM) { assert(b->step(a)); confirmed = true; break; }
        assert(confirmed);
    }
    assert(b->pending.op == ChoiceOp::NONE && b->handCount == 5);
    assert(b->hand[0].uid != first && b->hand[3].uid != second);
    assert(b->hand[1].id == CardId::DEFEND_IRONCLAD && b->hand[2].id == CardId::DEFEND_IRONCLAD);
    assert(b->cardSelectionRng.counter == selection + 2);
}

void fasten_reaches_every_defend_card() {
    auto b = battle();
    b->add_player_power(PowerId::FASTEN, 4);
    const Card d = put(*b, CardId::ULTIMATE_DEFEND);
    assert(play(*b, d.uid));
    assert(b->player.block == 11 + 4);
}

void omnislice_splash_triggers_thorns() {
    auto b = battle(2);
    b->monsters[1].power[static_cast<int>(PowerId::THORNS)] = 3;
    const int hp = b->player.hp;
    const Card o = put(*b, CardId::OMNISLICE);
    assert(play(*b, o.uid));
    assert(b->player.hp == hp - 3);
}

void rebound_stacks_and_spares_its_own_card() {
    auto b = battle();
    const Card r1 = put(*b, CardId::REBOUND), r2 = put(*b, CardId::REBOUND), s = put(*b, CardId::STRIKE_IRONCLAD);
    assert(play(*b, r1.uid));
    assert(b->player_power(PowerId::REBOUND) == 1 && b->discard[b->discardCount - 1].uid == r1.uid);
    assert(play(*b, r2.uid));          // goes on top, and adds a stack during its own play
    assert(b->draw[b->drawCount - 1].uid == r2.uid && b->player_power(PowerId::REBOUND) == 1);
    assert(play(*b, s.uid));
    assert(b->draw[b->drawCount - 1].uid == s.uid && b->player_power(PowerId::REBOUND) == 0);
}

void bolas_waits_in_discard_and_returns() {
    auto b = battle();
    const Card bolas = put(*b, CardId::BOLAS);
    assert(play(*b, bolas.uid));
    assert(b->discardCount == 1 && b->discard[0].uid == bolas.uid);
    end_turn(*b);
    bool inHand = false;
    for (int i = 0; i < b->handCount; ++i) inHand |= b->hand[i].uid == bolas.uid;
    assert(inHand);
}

void apotheosis_upgrades_everything_but_itself() {
    auto b = battle();
    const Card a = put(*b, CardId::APOTHEOSIS);
    const Card s = put(*b, CardId::STRIKE_IRONCLAD);
    b->discard[b->discardCount++] = make_card(CardId::BASH, false, b->require_card_uid());
    assert(play(*b, a.uid));
    assert(b->discard[0].upgraded);
    for (int i = 0; i < b->handCount; ++i) if (b->hand[i].uid == s.uid) assert(b->hand[i].upgraded);
    for (int i = 0; i < b->exhaustCount; ++i) if (b->exhaust[i].uid == a.uid) assert(!b->exhaust[i].upgraded);
}

void end_of_turn_block_absorbs_constrict() {
    auto b = battle();
    b->add_player_power(PowerId::PLATING, 200);
    b->add_player_power(PowerId::CONSTRICT, 3);
    const int hp = b->player.hp;
    b->end_player_turn();
    assert(b->player.hp == hp);
}

void pounce_makes_the_next_skill_free() {
    auto b = battle();
    const Card pounce = put(*b, CardId::POUNCE);
    const Card first = put(*b, CardId::DEFEND_IRONCLAD), second = put(*b, CardId::DEFEND_IRONCLAD);
    assert(play(*b, pounce.uid));
    assert(b->player_power(PowerId::FREE_SKILL) == 1);
    const int energy = b->player.energy;
    assert(play(*b, first.uid));
    assert(b->player.energy == energy && b->player_power(PowerId::FREE_SKILL) == 0);
    assert(play(*b, second.uid));
    assert(b->player.energy == energy - 1);
}

void generated_shivs_fire_the_generated_hook() {
    auto b = battle();
    b->add_player_power(PowerId::ARSENAL, 1);
    const Card dance = put(*b, CardId::BLADE_DANCE);
    assert(play(*b, dance.uid));
    assert(b->player.strength == 3);   // ArsenalPower: one per generated card
}

void a_transform_is_not_a_generated_card() {
    auto b = battle();
    b->add_player_power(PowerId::ARSENAL, 1);
    put(*b, CardId::DAZED);
    const Card compact = put(*b, CardId::COMPACT);
    assert(play(*b, compact.uid));
    assert(b->hand[0].id == CardId::FUEL && b->player.strength == 0);
}

void regent_cards_with_their_own_hooks() {
    {   // Result piles.
        auto b = battle();
        b->regent.stars = 20;
        const Card wall = put(*b, CardId::PARTICLE_WALL), strike = put(*b, CardId::SHINING_STRIKE);
        assert(play(*b, wall.uid));
        assert(b->find_in_hand(wall.uid) != nullptr);
        assert(play(*b, strike.uid));
        assert(b->draw[b->drawCount - 1].uid == strike.uid);
    }
    {   // Drawn: Kingly Kick costs 1 less, Kingly Punch hits harder.
        auto b = battle();
        const Card kick = make_card(CardId::KINGLY_KICK, false, b->require_card_uid());
        const Card punch = make_card(CardId::KINGLY_PUNCH, false, b->require_card_uid());
        b->draw[b->drawCount++] = kick;
        b->draw[b->drawCount++] = punch;
        b->draw_cards(2);
        assert(card_cost(*b->find_in_hand(kick.uid)) == 3);
        assert(b->find_in_hand(punch.uid)->bonusDamage == 4);
    }
    {   // Bombardment auto-plays from the exhaust pile at the start of the turn.
        auto b = battle();
        b->exhaust[b->exhaustCount++] = make_card(CardId::BOMBARDMENT, false, b->require_card_uid());
        const int hp = b->monsters[0].hp;
        end_turn(*b);
        assert(hp - b->monsters[0].hp >= 18 && b->exhaustCount == 1);
    }
    {   // I Am Invincible plays itself from the top of the draw pile when the turn ends.
        auto b = battle();
        const Card top = make_card(CardId::I_AM_INVINCIBLE, false, b->require_card_uid());
        b->draw[b->drawCount++] = top;
        const int before = b->drawCount;
        b->end_player_turn();
        assert(b->find_in_draw(top.uid) == nullptr || b->drawCount < before);
    }
    {   // Make It So returns on every third Skill.
        auto b = battle();
        const Card so = make_card(CardId::MAKE_IT_SO, false, b->require_card_uid());
        b->discard[b->discardCount++] = so;
        for (int i = 0; i < 3; ++i) {
            const Card d = put(*b, CardId::DEFEND_IRONCLAD);
            assert(play(*b, d.uid));
            assert((b->find_in_hand(so.uid) != nullptr) == (i == 2));
        }
    }
    {   // SetToFreeThisTurn also clears the star cost.
        auto b = battle();
        Card c = make_card(CardId::KNOCKOUT_BLOW, false, b->require_card_uid());
        const int starCost = card_def(CardId::GUIDING_STAR).starCost;
        (void)starCost;
        Card star = make_card(CardId::GUIDING_STAR, false, b->require_card_uid());
        assert(regent_star_cost(*b, star) > 0);
        card_modify_cost(star, 0, true, 2 | 4 | 8);
        assert(regent_star_cost(*b, star) == 0);
        (void)c;
    }
}

void necrobinder_handles_six_enemies() {
    {
        auto b = battle(6);
        for (int i = 0; i < 6; ++i) b->monsters[i].power[static_cast<int>(PowerId::DOOM)] = 9999;
        necrobinder_doom_kill(*b);
        for (int i = 0; i < 6; ++i) assert(!b->monsters[i].alive);
    }
    {
        auto b = battle(6);
        necrobinder_summon(*b, 10);
        const Card five = put(*b, CardId::HIGH_FIVE);
        assert(play(*b, five.uid));
        for (int i = 0; i < 6; ++i) assert(b->monsters[i].hp < 5000 && b->monsters[i].vulnerable > 0);
    }
    {   // Only Fetch records its identity, so a long turn cannot exhaust the list.
        auto b = battle();
        b->necro.finishedUidCount = 160;
        const Card d = put(*b, CardId::DEFEND_IRONCLAD);
        assert(play(*b, d.uid));
        assert(b->necro.finishedUidCount == 160);
    }
}

void relic_timing_matches_native() {
    const auto give = [](BattleContext &b, RelicId id) {
        b.relics[b.relicCount++] = static_cast<int>(id);
    };
    {   // Intimidating Helmet fires on every play iteration of a 2-energy card.
        auto b = battle();
        give(*b, RelicId::INTIMIDATING_HELMET);
        Card bash = make_card(CardId::BASH, false, b->require_card_uid());
        bash.bonusReplay = 1;
        b->hand[b->handCount++] = bash;
        assert(play(*b, bash.uid));
        assert(b->player.block == 8);
    }
    {   // Ghost Seed reaches a Basic Defend that enters the combat later.
        auto b = battle();
        give(*b, RelicId::GHOST_SEED);
        Card d = make_card(CardId::DEFEND_SILENT, false, b->require_card_uid());
        b->add_card_to_hand(d);
        b->notify_card_generated(d);
        assert(b->find_in_hand(d.uid)->etherealThisCombat);
    }
    {   // Unceasing Top draws after the card has left, but not if the card came back to hand.
        auto b = battle();
        give(*b, RelicId::UNCEASING_TOP);
        const Card s = put(*b, CardId::STRIKE_IRONCLAD);
        assert(play(*b, s.uid));
        assert(b->handCount == 1);
        b->handCount = 0;
        b->regent.stars = 9;
        const Card wall = put(*b, CardId::PARTICLE_WALL);
        const int drawBefore = b->drawCount;
        assert(play(*b, wall.uid));
        assert(b->handCount == 1 && b->hand[0].uid == wall.uid && b->drawCount == drawBefore);
    }
    {   // A Pen Nib attack that wins the combat leaves no doubled attack behind.
        auto b = battle();
        give(*b, RelicId::PEN_NIB);
        b->relicAux[b->relicCount - 1] = 9;
        b->monsters[0].hp = 1;
        const Card s = put(*b, CardId::STRIKE_IRONCLAD);
        assert(play(*b, s.uid));
        assert(b->outcome != Outcome::UNDECIDED && b->relicAux[b->relicCount - 1] == 0);
    }
}

void only_a_new_player_debuff_skips_its_first_tick() {
    auto b = battle();
    b->add_player_power(PowerId::WEAK, 2);
    b->after_monster_turn();
    assert(b->player.weak == 2);       // new: first tick skipped
    b->add_player_power(PowerId::WEAK, 1);
    b->after_monster_turn();
    assert(b->player.weak == 2);       // stacked: 3, then a normal tick
}

}  // namespace

int main() {
    neows_fury_lets_the_player_choose();
    entropy_is_a_choice_after_the_hand_is_drawn();
    fasten_reaches_every_defend_card();
    omnislice_splash_triggers_thorns();
    rebound_stacks_and_spares_its_own_card();
    bolas_waits_in_discard_and_returns();
    apotheosis_upgrades_everything_but_itself();
    end_of_turn_block_absorbs_constrict();
    pounce_makes_the_next_skill_free();
    generated_shivs_fire_the_generated_hook();
    a_transform_is_not_a_generated_card();
    regent_cards_with_their_own_hooks();
    necrobinder_handles_six_enemies();
    relic_timing_matches_native();
    only_a_new_player_debuff_skips_its_first_tick();
    std::cout << "native other card effects: ok\n";
    return 0;
}
