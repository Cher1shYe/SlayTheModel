// Monster AI rules ported from native v0.111.0 in ruleset v9 (2026-11-18). Expectations
// are transcribed from the native source (MonsterMoves/*, Models/Monsters/*, CombatManager).
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include <cstdio>
#include <string>

using namespace sts2;

static int failures = 0;
static void check(bool ok, const std::string &label) {
    if (!ok) { ++failures; std::printf("FAIL %s\n", label.c_str()); }
}

static BattleContext start(Encounter enc, int asc = 0, std::uint64_t encSeed = 11) {
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
    BattleContext b;
    b.init(enc, 4242, deck, 10, asc, 5000, 5000, nullptr, 0, nullptr, 0, BASE_POTION_SLOTS, 0, 3, 0, 0,
           nullptr, nullptr, nullptr, nullptr, encSeed);
    return b;
}

int main() {
    // 1. Axebot: fixed cycle HAMMER_UPPERCUT (4) -> ONE_TWO (2) -> HAMMER_UPPERCUT, no random branch.
    {
        BattleContext b = start(Encounter::SETUP_AXEBOTS_NORMAL);
        check(b.monsters[0].move == 4, "Axebot starts with Hammer Uppercut");
        check(b.monsters[0].intentDamage == 14, "Hammer Uppercut 14 at A0");
        const int aiBefore = b.monsterAiRng.counter;
        b.end_player_turn();
        check(b.monsters[0].move == 2, "then One-Two");
        check(b.monsters[0].intentDamage == 10 && b.monsters[0].intentHits == 2, "One-Two 10 x 2");
        b.end_player_turn();
        check(b.monsters[0].move == 4, "then Hammer Uppercut again");
        check(b.monsterAiRng.counter == aiBefore, "a fixed cycle draws no MonsterAi");
        // Stock respawn: Boot Up, HP range +10 per respawn, Strength 3 x RespawnCount.
        b.kill_monster(0);
        check(b.monsters[0].alive && b.monsters[0].move == 1, "respawned Axebot starts with Boot Up");
        check(b.monsters[0].power[static_cast<int>(PowerId::STOCK)] == 1, "stock drops to 1");
        check(b.monsters[0].maxHp >= 80 && b.monsters[0].maxHp <= 88, "respawn HP 70..78 + 10");
        b.end_player_turn();
        check(b.monsters[0].block == 10 || b.monsters[0].block == 0, "Boot Up block");
        check(b.monsters[0].power[static_cast<int>(PowerId::STRENGTH)] == 3 || b.monsters[0].strength == 3,
              "Boot Up Strength 3 x 1 respawn");
    }
    // 2. Moves are rolled at the start of the player's turn, not right after acting.
    {
        BattleContext b = start(Encounter::SETUP_EXOSKELETONS_NORMAL);
        check(b.monsters[3].pendingRoll == false, "turn 1 rolled before the first decision");
        b.monster_turn();
        bool pending = false;
        for (int i = 0; i < b.monsterCount; ++i) pending |= b.monsters[i].pendingRoll;
        check(pending, "after the enemy turn the follow-ups wait for the player turn");
        const int before = b.monsterAiRng.counter;
        roll_pending_moves(b);
        check(b.monsterAiRng.counter > before, "rolling the random branch draws MonsterAi");
        for (int i = 0; i < b.monsterCount; ++i) check(!b.monsters[i].pendingRoll, "all rolled");
    }
    // 3. Exoskeleton starts by slot (first Skitter, second Mandibles, third Enrage, fourth random).
    {
        BattleContext b = start(Encounter::SETUP_EXOSKELETONS_NORMAL);
        check(b.monsterCount == 4, "four Exoskeletons");
        check(b.monsters[0].move == 1 && b.monsters[1].move == 2 && b.monsters[2].move == 3,
              "slots 1-3 start with Skitter / Mandibles / Enrage");
        check(b.monsters[3].move == 1 || b.monsters[3].move == 2, "slot 4 rolls Skitter or Mandibles");
    }
    // 4. A dead creature waiting to revive is not a legal target (Fogmog's illusion).
    {
        BattleContext b = start(Encounter::SETUP_FOGMOG_NORMAL);
        b.end_player_turn();   // Fogmog summons the Eye with Teeth
        int eye = -1;
        for (int i = 0; i < b.monsterCount; ++i) if (b.monsters[i].id == MonsterId::EYE_WITH_TEETH) eye = i;
        check(eye >= 0, "Fogmog summons the Eye");
        if (eye >= 0) {
            b.hand[0] = make_card(CardId::STRIKE_IRONCLAD, false, 900);
            b.handCount = 1;
            b.player.energy = 3;
            b.kill_monster(eye);
            check(b.monsters[eye].reviving, "the illusion waits to revive");
            bool targetsEye = false;
            for (const Action &a : b.legal_actions())
                targetsEye |= a.type == ActionType::PLAY_CARD && a.target == eye;
            check(!targetsEye, "no card can target it");
        }
    }
    // 5. Two-Tailed Rats call for backup (native weights 0.75 vs 1/12 once summonable).
    {
        int summons = 0;
        for (std::uint64_t s = 1; s <= 40; ++s) {
            BattleContext b = start(Encounter::SETUP_TWO_TAILED_RATS_NORMAL, 0, s);
            for (int t = 0; t < 6 && b.outcome == Outcome::UNDECIDED; ++t) b.end_player_turn();
            if (b.monsterCount > 3) {
                ++summons;
                int count = -1;
                bool same = true;
                for (int i = 0; i < b.monsterCount; ++i) {
                    if (!b.monsters[i].alive) continue;
                    if (count < 0) count = b.monsters[i].aux[1];
                    same &= b.monsters[i].aux[1] == count;
                }
                check(same && count >= 1, "every rat shares the call-for-backup count");
            }
            check(b.monsterCount <= 5, "at most five rats (encounter slots)");
        }
        check(summons > 20, "rats call for backup in most fights");
    }
    // 6. Fossil Stalker's Suck: Strength 3 per hit with unblocked damage.
    {
        BattleContext b = start(Encounter::SETUP_FOSSIL_STALKER_NORMAL);
        check(b.monsters[0].power[static_cast<int>(PowerId::SUCK)] == 3, "Fossil Stalker has Suck 3");
        Monster &m = b.monsters[0];
        m.move = 0;
        const int s0 = m.strength;
        b.player.block = 0;
        b.monster_turn();
        const int gained = m.strength - s0;
        check(gained % 3 == 0 && gained >= 3, "unblocked hits give Strength 3 each");
        BattleContext c = start(Encounter::SETUP_FOSSIL_STALKER_NORMAL);
        const int c0 = c.monsters[0].strength;
        c.player.block = 999;
        c.monster_turn();
        check(c.monsters[0].strength == c0, "fully blocked attacks give no Strength");
    }
    // 7. Native enemy order and summon slots.
    {
        // Fogmog's Eye goes to slot "illusion", before Fogmog: it acts and rolls first.
        BattleContext b = start(Encounter::SETUP_FOGMOG_NORMAL);
        b.end_player_turn();
        int order[MAX_MONSTERS];
        const int n = b.enemy_order(order);
        check(n == 2 && b.monsters[order[0]].id == MonsterId::EYE_WITH_TEETH, "illusion slot sorts first");
    }
    {
        // Ovicopter lays three eggs in the last free slots (egg5, egg4, egg3), Hatch 2 on its turn.
        BattleContext b = start(Encounter::SETUP_OVICOPTER_NORMAL);
        check(b.monsters[0].orderKey == 5, "Ovicopter in its slot");
        b.end_player_turn();
        int eggs = 0, hatch2 = 0, keySum = 0;
        for (int i = 0; i < b.monsterCount; ++i) {
            if (b.monsters[i].id != MonsterId::TOUGH_EGG) continue;
            ++eggs;
            keySum += b.monsters[i].orderKey;
            hatch2 += b.monsters[i].power[static_cast<int>(PowerId::HATCH)] == 2;
        }
        check(eggs == 3 && keySum == 4 + 3 + 2, "three eggs in egg5/egg4/egg3");
        check(hatch2 == 3, "eggs laid on the enemy turn hatch in 2");
        int order[MAX_MONSTERS];
        b.enemy_order(order);
        check(b.monsters[order[0]].id == MonsterId::TOUGH_EGG, "eggs come before the Ovicopter");
    }
    {
        // Fabricator: bots in the first free slots; never the same bot twice in a row.
        int checked = 0;
        for (std::uint64_t s = 1; s <= 30; ++s) {
            BattleContext b = start(Encounter::SETUP_FABRICATOR_NORMAL, 0, s);
            for (int t = 0; t < 4 && b.outcome == Outcome::UNDECIDED; ++t) b.end_player_turn();
            for (int i = 0; i < b.monsterCount; ++i) {
                const Monster &m = b.monsters[i];
                if (m.id == MonsterId::FABRICATOR) continue;
                if (!m.alive) continue;
                ++checked;
                check(m.orderKey != 2 && m.orderKey < 5, "bots use bot1..bot4");
                check(m.power[static_cast<int>(PowerId::MINION)] == 1, "bots are minions");
            }
            int living = 0;
            for (int i = 0; i < b.monsterCount; ++i) living += b.monsters[i].alive && !b.monsters[i].reviving;
            check(living <= 5, "at most five enemies");
        }
        check(checked > 20, "Fabricator summons bots");
    }
    {
        // Rats summon into the last free slot: second, then first.
        bool sawSecond = false;
        for (std::uint64_t s = 1; s <= 40 && !sawSecond; ++s) {
            BattleContext b = start(Encounter::SETUP_TWO_TAILED_RATS_NORMAL, 0, s);
            for (int t = 0; t < 6 && b.outcome == Outcome::UNDECIDED; ++t) b.end_player_turn();
            for (int i = 3; i < b.monsterCount; ++i) sawSecond |= b.monsters[i].orderKey == 1;
        }
        check(sawSecond, "the first summoned rat takes slot second");
    }
    {
        // CubexConstruct.AfterAddedToRoom gives every Cubex 13 block (Construct Menagerie too).
        BattleContext b = start(Encounter::SETUP_CONSTRUCT_MENAGERIE_NORMAL);
        int cubex = 0;
        for (int i = 0; i < b.monsterCount; ++i)
            if (b.monsters[i].id == MonsterId::CUBEX_CONSTRUCT) {
                ++cubex;
                check(b.monsters[i].block == 13, "Menagerie Cubex starts with 13 block");
            }
        check(cubex == 2, "two Cubex in the Menagerie");
    }
    // 8. Knowledge Demon: Curse of Knowledge suspends the enemy turn for a two-card choice.
    {
        BattleContext b = start(Encounter::SETUP_KNOWLEDGE_DEMON_BOSS);
        check(b.monsters[0].move == 0, "Knowledge Demon opens with Curse of Knowledge");
        const int turnBefore = b.turn;
        b.end_player_turn();
        check(b.pending.op == ChoiceOp::KNOWLEDGE_CURSE && b.pending.count == 2, "curse choice is pending");
        check(b.inMonsterTurn && b.turn == turnBefore, "the enemy turn waits for it");
        check(b.pending.cards[0].id == CardId::DISINTEGRATION && b.pending.cards[0].bonusDamage == 6 &&
                  b.pending.cards[1].id == CardId::MIND_ROT, "stage 1: Disintegration 6 or Mind Rot");
        const auto legal = b.legal_actions();
        check(legal.size() == 2 && legal[0].type == ActionType::CHOOSE, "only the two choices are legal");
        Action pick;
        pick.type = ActionType::CHOOSE;
        pick.uid = b.pending.cards[1].uid;
        check(b.step(pick), "choose Mind Rot");
        check(b.player.power[static_cast<int>(PowerId::MIND_ROT)] == 1, "Mind Rot applied");
        check(!b.inMonsterTurn && b.turn == turnBefore + 1, "the enemy turn finished and the player turn began");
        check(b.handCount == 4, "Mind Rot: one card fewer in the turn draw");
        check(b.monsters[0].aux[0] == 1, "curse counter 1");
        // Slap, Knowledge Overwhelming, Ponder, then the next curse (fourth enemy turn).
        for (int t = 0; t < 4 && b.pending.op == ChoiceOp::NONE; ++t) b.end_player_turn();
        check(b.pending.op == ChoiceOp::KNOWLEDGE_CURSE && b.pending.cards[0].bonusDamage == 7 &&
                  b.pending.cards[1].id == CardId::SLOTH_STATUS, "stage 2: Disintegration 7 or Sloth");
        pick.uid = b.pending.cards[0].uid;
        b.step(pick);
        check(b.player.power[static_cast<int>(PowerId::DISINTEGRATION)] == 7, "Disintegration 7 applied");
        const int hp = b.player.hp;
        b.player.block = 0;
        b.end_player_turn();
        check(b.player.hp <= hp - 7, "Disintegration damages at the end of the player turn");
    }
    {
        // Sloth: at most Amount cards per turn; Waste Away: max energy - Amount.
        BattleContext b = start(Encounter::SETUP_KNOWLEDGE_DEMON_BOSS);
        b.player.power[static_cast<int>(PowerId::SLOTH)] = 3;
        b.cardsPlayedThisTurn = 3;
        b.slothCardsPlayedThisTurn = 3;
        bool canPlay = false;
        for (const Action &a : b.legal_actions()) canPlay |= a.type == ActionType::PLAY_CARD;
        check(!canPlay, "Sloth blocks a fourth card");
        b.player.power[static_cast<int>(PowerId::WASTE_AWAY)] = 1;
        b.pending = PendingChoice();
        b.player.power[static_cast<int>(PowerId::SLOTH)] = 0;
        b.monsters[0].move = 1;   // Slap instead of another curse
        b.end_player_turn();
        if (b.pending.op == ChoiceOp::NONE) check(b.player.energy == 2, "Waste Away: 3 - 1 energy");
    }
    // 9. Queen Chains of Binding: drawn cards become Bound (3 per turn), one Bound card per turn.
    {
        BattleContext b = start(Encounter::SETUP_AXEBOTS_NORMAL);
        b.player.power[static_cast<int>(PowerId::CHAINS_OF_BINDING)] = 3;
        b.end_player_turn();
        int bound = 0, firstBound = -1, firstFree = -1;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].bound) { ++bound; if (firstBound < 0) firstBound = i; }
            else if (firstFree < 0) firstFree = i;
        }
        check(b.handCount == 5 && bound == 3, "three of five drawn cards are Bound");
        check(card_cost(b.hand[firstBound]) == 1, "Bound does not change the cost");
        Action play;
        play.type = ActionType::PLAY_CARD;
        play.hand = static_cast<std::uint8_t>(firstBound);
        play.target = 0;
        check(b.step(play), "first Bound card can be played");
        int boundLegal = 0, freeLegal = 0;
        for (const Action &a : b.legal_actions()) {
            if (a.type != ActionType::PLAY_CARD) continue;
            if (b.hand[a.hand].bound) ++boundLegal; else ++freeLegal;
        }
        check(boundLegal == 0 && freeLegal == 2, "other Bound cards are blocked, unbound cards are not");
        b.end_player_turn();
        int stillBound = 0;
        for (int i = 0; i < b.discardCount; ++i) stillBound += b.discard[i].bound;
        bound = 0;
        for (int i = 0; i < b.handCount; ++i) bound += b.hand[i].bound;
        check(stillBound == 0 && !b.boundCardPlayed, "Bound clears at the end of the player turn");
        check(bound == 3, "the next hand is Bound again");
    }
    // 10. Test Subject: two revivals; the knock-out removes every power but Adaptable / Painful Stabs.
    {
        BattleContext b = start(Encounter::SETUP_TEST_SUBJECT_BOSS);
        Monster &m = b.monsters[0];
        check(m.maxHp == 100 && m.power[static_cast<int>(PowerId::ENRAGE)] == 2, "phase 1: 100 HP, Enrage 2");
        b.add_monster_power(0, PowerId::STRENGTH, 4);
        b.add_monster_power(0, PowerId::VULNERABLE, 2);
        b.damage_monster(0, 500, true, false, true);
        check(m.reviving && m.hp == 0 && m.move == 0, "knocked out: Respawn intent");
        check(b.outcome == Outcome::UNDECIDED, "combat continues");
        check(m.strength == 0 && m.vulnerable == 0 && m.power[static_cast<int>(PowerId::ENRAGE)] == 0 &&
                  m.power[static_cast<int>(PowerId::ADAPTABLE)] == 1, "death removed Enrage / Strength / Vulnerable");
        bool targetable = false;
        for (const Action &a : b.legal_actions()) targetable |= a.type == ActionType::PLAY_CARD && a.target == 0 &&
                                                                card_target(b.hand[a.hand]) == TargetType::ENEMY;
        check(!targetable, "reviving Test Subject is not targetable");
        b.end_player_turn();
        check(!m.reviving && m.maxHp == 200 && m.hp == 200 && m.power[static_cast<int>(PowerId::PAINFUL_STABS)] == 1,
              "phase 2: 200 HP, Painful Stabs");
        check(m.move == 5 && m.intentHits == 3, "phase 2 opens with Multi Claw x3");
        b.end_player_turn();
        check(m.move == 5 && m.intentHits == 4, "Multi Claw gains a hit each use");
        b.damage_monster(0, 500, true, false, true);
        b.end_player_turn();
        check(m.maxHp == 300 && m.hp == 300 && m.power[static_cast<int>(PowerId::NEMESIS)] == 1 &&
                  m.power[static_cast<int>(PowerId::ADAPTABLE)] == 0 && m.power[static_cast<int>(PowerId::PAINFUL_STABS)] == 0,
              "phase 3: 300 HP, Nemesis, no Adaptable / Painful Stabs");
        check(m.move == 6 && m.power[static_cast<int>(PowerId::INTANGIBLE)] == 1, "Lacerate next; Intangible this player turn");
        b.end_player_turn();
        check(m.power[static_cast<int>(PowerId::INTANGIBLE)] == 0, "Nemesis: Intangible every other turn");
        b.damage_monster(0, 500, true, false, true);
        check(!m.alive && b.outcome == Outcome::PLAYER_VICTORY, "the third death ends the fight");
    }
    // 11. The Insatiable: Liquify Ground -> Sandpit 4, six Frantic Escapes; Sandpit 0 kills the player.
    {
        BattleContext b = start(Encounter::SETUP_THE_INSATIABLE_BOSS);
        Monster &m = b.monsters[0];
        b.end_player_turn();
        const auto count = [&](const Card *pile, int n) {
            int c = 0;
            for (int i = 0; i < n; ++i) c += pile[i].id == CardId::FRANTIC_ESCAPE;
            return c;
        };
        check(m.power[static_cast<int>(PowerId::SANDPIT)] == 4, "Sandpit 4 after Liquify Ground");
        check(count(b.draw, b.drawCount) + count(b.hand, b.handCount) + count(b.discard, b.discardCount) == 6,
              "six Frantic Escapes");
        int fe = -1;
        for (int i = 0; i < b.handCount; ++i) if (b.hand[i].id == CardId::FRANTIC_ESCAPE) fe = i;
        if (fe < 0) {   // put one in hand to test it
            b.add_card_to_hand(make_card(CardId::FRANTIC_ESCAPE, false, b.require_card_uid()));
            fe = b.handCount - 1;
        }
        Action play;
        play.type = ActionType::PLAY_CARD;
        play.hand = static_cast<std::uint8_t>(fe);
        play.target = 0;
        check(b.step(play), "Frantic Escape playable");
        check(m.power[static_cast<int>(PowerId::SANDPIT)] == 5, "Frantic Escape: Sandpit +1");
        int turns = 0;
        while (b.outcome == Outcome::UNDECIDED && turns < 10) { b.end_player_turn(); ++turns; }
        check(b.outcome == Outcome::PLAYER_LOSS && turns == 5, "Sandpit reaching 0 kills the player");
    }
    // 12. Slippery (Vantom 8 at A0 / 9 at A8; Inklet 1): block absorbs the full hit, HP loss
    // is capped at 1 after block, and only a hit that cost HP removes a stack.
    {
        BattleContext b = start(Encounter::SETUP_VANTOM_BOSS);
        Monster &m = b.monsters[0];
        check(m.power[static_cast<int>(PowerId::SLIPPERY)] == 8, "Vantom Slippery 8 at A0");
        check(start(Encounter::SETUP_VANTOM_BOSS, 8).monsters[0].power[static_cast<int>(PowerId::SLIPPERY)] == 9,
              "Vantom Slippery 9 at A8");
        const int hp = m.hp;
        m.block = 5;
        b.damage_monster(0, 3, true, true);
        check(m.block == 2 && m.hp == hp && m.power[static_cast<int>(PowerId::SLIPPERY)] == 8,
              "fully blocked hit: block -3, no HP loss, no stack used");
        b.damage_monster(0, 10, true, true);
        check(m.block == 0 && m.hp == hp - 1 && m.power[static_cast<int>(PowerId::SLIPPERY)] == 7,
              "10 damage into 2 block: block gone, 1 HP lost, one stack used");
        b.relics[b.relicCount++] = static_cast<int>(RelicId::THE_BOOT);
        b.damage_monster(0, 10, true, true);
        check(m.hp == hp - 6, "The Boot (after Slippery) raises the 1 HP loss to 5");
        BattleContext k = start(Encounter::SETUP_INKLETS_NORMAL);
        for (int i = 0; i < k.monsterCount; ++i)
            check(k.monsters[i].power[static_cast<int>(PowerId::SLIPPERY)] == 1, "Inklet Slippery 1");
    }
    // 13. Infested Prism Vital Spark: Skills are Tainted (2); playing one applies Tainted 2,
    // which adds 2 to each enemy attack on the player until the enemy turn ends.
    {
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
        BattleContext b;
        b.init(Encounter::SETUP_INFESTED_PRISMS_ELITE, 4242, deck, 10, 0, 5000, 5000, nullptr, 0, nullptr, 0,
               BASE_POTION_SLOTS, 0, 3, 0, 0, nullptr, nullptr, nullptr, nullptr, 11);
        check(b.hand[0].tainted == 2, "Skills start Tainted 2");
        const int base = b.calc_monster_damage(b.monsters[0], 10);
        Action play;
        play.type = ActionType::PLAY_CARD;
        play.hand = 0;
        play.target = 0;
        b.step(play);
        check(b.player.power[static_cast<int>(PowerId::TAINTED)] == 2, "playing a Tainted Skill applies Tainted 2");
        check(b.calc_monster_damage(b.monsters[0], 10) == base + 2, "Tainted adds 2 to enemy attacks");
        b.end_player_turn();
        check(b.player.power[static_cast<int>(PowerId::TAINTED)] == 0, "Tainted is removed when the enemy turn ends");
        b.damage_monster(0, 9999, true, false, true);
        int left = 0;
        for (int i = 0; i < b.handCount; ++i) left += b.hand[i].tainted;
        for (int i = 0; i < b.drawCount; ++i) left += b.draw[i].tainted;
        for (int i = 0; i < b.discardCount; ++i) left += b.discard[i].tainted;
        check(left == 0, "the Prism's death clears every Tainted");
    }
    // 14. Ceremonial Beast: Plow 150; at HP <= Plow it loses all Strength (temporary too),
    // skips one turn (STUN_MOVE), then Beast Cry -> Stomp -> Crush.
    {
        BattleContext b = start(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        Monster &m = b.monsters[0];
        b.end_player_turn();   // Stamp: Plow
        check(m.power[static_cast<int>(PowerId::PLOW)] == 150 && m.move == 1, "Stamp applies Plow 150, Plow next");
        b.end_player_turn();   // Plow: +2 Strength
        check(m.strength == 2, "Plow move gains 2 Strength");
        b.apply_strength_loss(0, 5);   // e.g. Dark Shackles this turn
        b.damage_monster(0, m.hp - 150, true, true);
        check(m.power[static_cast<int>(PowerId::PLOW)] == 0 && m.strength == 0 && m.tempStrengthLoss == 0 &&
                  m.move == 2, "Plow broken: Strength removed, stunned");
        const int hp = b.player.hp;
        b.end_player_turn();
        check(b.player.hp == hp && m.strength == 0, "stunned turn: no attack, the temporary loss is not restored");
        check(m.move == 3, "Beast Cry next");
        b.end_player_turn();
        check(b.player.power[static_cast<int>(PowerId::RINGING)] > 0 && m.move == 4, "Beast Cry rings the player, then Stomp");
    }
    // 15. Knights: Spectral Knight's Hex ends when it dies; Magi Knight's Dampen downgrades
    // upgraded cards until it dies, then they upgrade again.
    {
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, i < 4, i + 1);
        BattleContext b;
        b.init(Encounter::SETUP_KNIGHTS_ELITE, 4242, deck, 10, 0, 5000, 5000, nullptr, 0, nullptr, 0,
               BASE_POTION_SLOTS, 0, 3, 0, 0, nullptr, nullptr, nullptr, nullptr, 11);
        int spectral = -1, magi = -1;
        for (int i = 0; i < b.monsterCount; ++i) {
            if (b.monsters[i].id == MonsterId::SPECTRAL_KNIGHT) spectral = i;
            if (b.monsters[i].id == MonsterId::MAGI_KNIGHT) magi = i;
        }
        check(spectral >= 0 && magi >= 0, "knights present");
        const auto upgraded = [&] {
            int n = 0;
            const Card *piles[] = {b.hand, b.draw, b.discard, b.exhaust};
            const int counts[] = {b.handCount, b.drawCount, b.discardCount, b.exhaustCount};
            for (int p = 0; p < 4; ++p) for (int i = 0; i < counts[p]; ++i) n += piles[p][i].upgraded;
            return n;
        };
        b.end_player_turn();   // Spectral: Hex; Magi: Power Shield
        check(b.player.power[static_cast<int>(PowerId::HEX)] > 0, "Hex applied");
        check(upgraded() == 4, "no Dampen yet");
        b.end_player_turn();   // Magi: Dampen
        check(b.player.power[static_cast<int>(PowerId::DAMPEN)] > 0 && upgraded() == 0, "Dampen downgrades every upgraded card");
        check(b.exhaustCount > 0, "Hexed hand was exhausted at the end of the turn");
        b.damage_monster(spectral, 9999, true, false, true);
        check(b.player.power[static_cast<int>(PowerId::HEX)] == 0, "Hex ends when Spectral Knight dies");
        b.damage_monster(magi, 9999, true, false, true);
        check(b.player.power[static_cast<int>(PowerId::DAMPEN)] == 0 && upgraded() == 4,
              "Magi Knight's death ends Dampen and upgrades the cards again");
    }
    std::printf("native monster ai: %d failures\n", failures);
    return failures == 0 ? 0 : 1;
}
