#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/effects.h"
#include "sts2/relics.h"

#include <cstring>
#include <cstdio>

namespace sts2 {
#include "sts2/cards_generated.inc"
}

namespace sts2 {

static void remove_at(Card *arr, int &count, int idx) {
    for (int i = idx; i < count - 1; ++i) arr[i] = arr[i + 1];
    --count;
}

// Normality: while it is in hand, no more cards can be played once three have
// been played this turn (C# Normality.ShouldPlay).
static bool normality_blocks(const BattleContext &bc) {
    if (bc.cardsPlayedThisTurn < 3) return false;
    for (int i = 0; i < bc.handCount; ++i) {
        if (bc.hand[i].id == CardId::NORMALITY) return true;
    }
    return false;
}

int &power_ref(Player &p, PowerId id) {
    switch (id) {
        case PowerId::STRENGTH: return p.strength;
        case PowerId::DEXTERITY: return p.dexterity;
        case PowerId::VULNERABLE: return p.vulnerable;
        case PowerId::WEAK: return p.weak;
        case PowerId::FRAIL: return p.frail;
        default: return p.power[static_cast<int>(id)];
    }
}

int &power_ref(Monster &m, PowerId id) {
    switch (id) {
        case PowerId::STRENGTH: return m.strength;
        case PowerId::VULNERABLE: return m.vulnerable;
        case PowerId::WEAK: return m.weak;
        default: return m.power[static_cast<int>(id)];
    }
}

int BattleContext::player_power(PowerId id) const {
    switch (id) {
        case PowerId::STRENGTH: return player.strength;
        case PowerId::DEXTERITY: return player.dexterity;
        case PowerId::VULNERABLE: return player.vulnerable;
        case PowerId::WEAK: return player.weak;
        case PowerId::FRAIL: return player.frail;
        default: return player.power[static_cast<int>(id)];
    }
}

int BattleContext::monster_power(int idx, PowerId id) const {
    if (idx < 0 || idx >= monsterCount) return 0;
    const Monster &m = monsters[idx];
    switch (id) {
        case PowerId::STRENGTH: return m.strength;
        case PowerId::VULNERABLE: return m.vulnerable;
        case PowerId::WEAK: return m.weak;
        default: return m.power[static_cast<int>(id)];
    }
}

void BattleContext::add_player_power(PowerId id, int amount) {
    if (id == PowerId::STRENGTH && amount > 0) relics_strength_gain(*this, amount);
    power_ref(player, id) += static_cast<std::int16_t>(amount);
}

void BattleContext::add_monster_power(int idx, PowerId id, int amount) {
    if (idx < 0 || idx >= monsterCount) return;
    power_ref(monsters[idx], id) += static_cast<std::int16_t>(amount);
}

static bool card_exhausts(const BattleContext &bc, const Card &c) {
    if (card_has(c, CF_EXHAUST)) return true;
    if (bc.player_power(PowerId::CORRUPTION) > 0 && card_is_skill(c)) return true;
    if (card_is_power(c)) return true;
    return false;
}

void BattleContext::init(Encounter enc, std::uint32_t seed, const Card *deck, int deckCount,
                         int ascensionLevel, int playerHp, int playerMaxHp,
                         const int *relicIds, int relicN,
                         const int *potionIds, int potionN,
                         int slotCount, int turn1Energy, int energyPerTurn, int runGold,
                         std::uint32_t potionSeed) {
    *this = BattleContext();
    ascension = ascensionLevel;
    rng = Rng(seed);
    potionRng = Rng(potionSeed != 0 ? potionSeed : seed ^ 0x5F3759DFu);
    player.maxHp = playerMaxHp > 0 ? playerMaxHp : 80;
    player.hp = playerHp >= 0 ? playerHp : player.maxHp;
    player.energyPerTurn = energyPerTurn;
    player.drawPerTurn = 5;
    this->turn1Energy = turn1Energy;
    gold = runGold;
    potionSlots = std::min(slotCount, MAX_POTIONS);
    potionCount = std::min(potionN, potionSlots);
    for (int i = 0; i < potionCount; ++i) potions[i] = potionIds[i];
    relicCount = std::min(relicN, MAX_RELICS);
    for (int i = 0; i < relicCount; ++i) relics[i] = relicIds[i];
    for (int i = 0; i < deckCount && i < MAX_PILE; ++i) draw[drawCount++] = deck[i];
    rng.shuffle(draw, drawCount);
    setup_encounter(*this, enc);
    nextUid = 1000;
    relics_combat_start(*this);
    start_player_turn();
}

int BattleContext::alive_monster_count() const {
    int n = 0;
    for (int i = 0; i < monsterCount; ++i) n += monsters[i].alive ? 1 : 0;
    return n;
}

int BattleContext::first_alive_monster() const {
    for (int i = 0; i < monsterCount; ++i) if (monsters[i].alive) return i;
    return -1;
}

int BattleContext::random_alive_monster() {
    int alive[MAX_MONSTERS];
    int n = 0;
    for (int i = 0; i < monsterCount; ++i) if (monsters[i].alive) alive[n++] = i;
    if (n == 0) return -1;
    return alive[rng.next_int(0, n - 1)];
}

void BattleContext::check_outcome() {
    if (outcome != Outcome::UNDECIDED) return;
    if (player.hp <= 0) outcome = Outcome::PLAYER_LOSS;
    else if (alive_monster_count() == 0) outcome = Outcome::PLAYER_VICTORY;
}

Card *BattleContext::find_in_hand(std::uint16_t uid) {
    for (int i = 0; i < handCount; ++i) if (hand[i].uid == uid) return &hand[i];
    return nullptr;
}
Card *BattleContext::find_in_discard(std::uint16_t uid) {
    for (int i = 0; i < discardCount; ++i) if (discard[i].uid == uid) return &discard[i];
    return nullptr;
}
Card *BattleContext::find_in_draw(std::uint16_t uid) {
    for (int i = 0; i < drawCount; ++i) if (draw[i].uid == uid) return &draw[i];
    return nullptr;
}

// ---------------------------------------------------------------- turn flow

void BattleContext::resample_hidden(std::uint32_t seed) {
    Rng shuffle(seed);
    for (int i = drawCount - 1; i > 0; --i) {
        const int j = shuffle.next_int(0, i);
        Card t = draw[i];
        draw[i] = draw[j];
        draw[j] = t;
    }
    for (int i = discardCount - 1; i > 0; --i) {
        const int j = shuffle.next_int(0, i);
        Card t = discard[i];
        discard[i] = discard[j];
        discard[j] = t;
    }
    // The future monster-AI / shuffle rolls are hidden from the player.
    rng = Rng(seed ^ 0x9E3779B9u);
    potionRng = Rng(seed ^ 0x5F3759DFu);
}

void BattleContext::start_player_turn() {
    ++turn;
    // PlatingPower.BeforeSideTurnStart: at the start of round 1 enemies gain
    // block equal to their plating.
    if (turn == 1) {
        for (int i = 0; i < monsterCount; ++i) {
            const int plating = monsters[i].power[static_cast<int>(PowerId::PLATING)];
            if (monsters[i].alive && plating > 0) monsters[i].block += plating;
        }
    }
    player.tookUnblockedDamageThisTurn = false;
    if (player_power(PowerId::BARRICADE) <= 0) {
        const int keep = relics_block_retain(*this);
        player.block = keep > 0 ? std::min(player.block, keep) : 0;
    }
    if (player_power(PowerId::BLOCK_NEXT_TURN) > 0) {
        const int b = player_power(PowerId::BLOCK_NEXT_TURN);
        add_player_power(PowerId::BLOCK_NEXT_TURN, -b);
        gain_block(b, false);
    }
    int baseEnergy = player.energyPerTurn;
    if (player_power(PowerId::PYRE) > 0) baseEnergy += player_power(PowerId::PYRE);
    player.energy = relics_energy_for_turn(*this, baseEnergy) + nextTurnEnergy;
    nextTurnEnergy = 0;

    cardsPlayedThisTurn = 0;
    attacksPlayedThisTurn = 0;
    skillsPlayedThisTurn = 0;
    hpLostThisTurn = 0;
    exhaustedThisTurn = 0;
    cardsDrawnThisTurn = 0;
    gainedBlockFromCardThisTurn = false;
    playedAttackOrSkillThisTurn = false;
    jugglingTriggeredThisTurn = false;
    skillsLocked = false;
    relics_turn_start(*this);
    if (outcome != Outcome::UNDECIDED) return;

    if (player_power(PowerId::DEMON_FORM) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::DEMON_FORM));
    if (player_power(PowerId::CRIMSON_MANTLE) > 0) {
        lose_hp(1, false);
        if (outcome == Outcome::UNDECIDED) gain_block(player_power(PowerId::CRIMSON_MANTLE), false);
    }
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::INFERNO) > 0) lose_hp(1, false);
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::ROLLING_BOULDER) > 0) {
        const int dmg = player_power(PowerId::ROLLING_BOULDER);
        attack_all(dmg);
        add_player_power(PowerId::ROLLING_BOULDER, 5);
    }
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::PREP_TIME) > 0) add_player_power(PowerId::VIGOR, player_power(PowerId::PREP_TIME));

    // reset retained card costs
    for (int i = 0; i < handCount; ++i) {
        hand[i].costForTurn = hand[i].upgraded ? card_def(hand[i].id).costUp : card_def(hand[i].id).cost;
        if (hand[i].replay > 0) hand[i].replay = 0;
    }

    for (int i = 0; i < returnNextTurnCount; ++i) add_card_to_hand(returnNextTurn[i]);
    returnNextTurnCount = 0;

    // Innate: start each combat with these cards in hand.
    if (turn == 1) {
        for (int i = drawCount - 1; i >= 0; --i) {
            if (!card_has(draw[i], CF_INNATE)) continue;
            Card c = draw[i];
            remove_at(draw, drawCount, i);
            add_card_to_hand(c);
        }
    }
    draw_cards(relics_modify_draw(*this, player.drawPerTurn) + nextTurnDraw);
    nextTurnDraw = 0;
    if (outcome != Outcome::UNDECIDED) return;
    relics_hand_drawn(*this);

    // powers that act on the drawn hand
    if (player_power(PowerId::ENTROPY) > 0) {
        int n = player_power(PowerId::ENTROPY);
        while (n-- > 0 && handCount > 0) {
            const int idx = rng.next_int(0, handCount - 1);
            transform_card(hand[idx]);
        }
    }
    if (player_power(PowerId::AGGRESSION) > 0) {
        int attacks[MAX_PILE];
        int n = 0;
        for (int i = 0; i < discardCount; ++i) {
            if (card_is_attack(discard[i])) attacks[n++] = i;
        }
        if (n > 0) {
            const int idx = attacks[rng.next_int(0, n - 1)];
            Card c = discard[idx];
            remove_at(discard, discardCount, idx);
            upgrade_card(c);
            add_card_to_hand(c);
        }
    }
    if (player_power(PowerId::MAYHEM) > 0 && drawCount > 0) {
        Card c = draw[--drawCount];
        auto_play_random(c, false);
    }
}

void BattleContext::end_player_turn() {
    if (outcome != Outcome::UNDECIDED) return;
    if (turn >= 200) {  // ponytail: stalemate guard
        outcome = Outcome::PLAYER_LOSS;
        return;
    }
    // end-of-turn powers
    if (player_power(PowerId::CONSTRICT) > 0) {
        damage_player(player_power(PowerId::CONSTRICT));
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::STAMPEDE) > 0) {
        int attacks = player_power(PowerId::STAMPEDE);
        while (attacks-- > 0 && handCount > 0 && outcome == Outcome::UNDECIDED) {
            int candidates[MAX_HAND];
            int n = 0;
            for (int i = 0; i < handCount; ++i) if (card_is_attack(hand[i])) candidates[n++] = i;
            if (n == 0) break;
            const int idx = candidates[rng.next_int(0, n - 1)];
            Card c = hand[idx];
            remove_at(hand, handCount, idx);
            const int target = random_alive_monster();
            c.costForTurn = 0;
            play_card_effect(c, target >= 0 ? target : 0);
            if (pending.op != ChoiceOp::NONE) auto_resolve_pending();
            if (pending.op == ChoiceOp::NONE) finish_played_card(c);
        }
    }
    if (player_power(PowerId::THE_BOMB) > 0) {
        add_player_power(PowerId::THE_BOMB, -1);
        if (player_power(PowerId::THE_BOMB) == 0) {
            attack_all(player_power(PowerId::THE_BOMB_DAMAGE));
            player.power[static_cast<int>(PowerId::THE_BOMB_DAMAGE)] = 0;
        }
    }
    for (int i = 0; i < exhaustCount; ++i) {
        if (exhaust[i].id == CardId::HOWL_FROM_BEYOND && outcome == Outcome::UNDECIDED) {
            Card c = exhaust[i];
            remove_at(exhaust, exhaustCount, i);
            c.costForTurn = 0;
            play_card_effect(c, 0);
            if (pending.op != ChoiceOp::NONE) auto_resolve_pending();
            if (pending.op == ChoiceOp::NONE) finish_played_card(c);
            break;
        }
    }

    if (player_power(PowerId::PLATING) > 0) gain_block(player_power(PowerId::PLATING), false);
    if (player_power(PowerId::REGEN) > 0) {
        player.hp = std::min(player.maxHp, player.hp + player_power(PowerId::REGEN));
        add_player_power(PowerId::REGEN, -1);
    }
    relics_turn_end(*this);
    relics_after_turn(*this);
    if (outcome != Outcome::UNDECIDED) return;

    discard_hand();
    if (player.tempStrength != 0) {
        player.strength -= player.tempStrength;
        player.tempStrength = 0;
    }
    if (player.tempDexterity != 0) {
        player.dexterity -= player.tempDexterity;
        player.tempDexterity = 0;
    }
    if (player_power(PowerId::RITUAL) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RITUAL));
    if (player_power(PowerId::GIGANTIFICATION) > 0) {
        player.power[static_cast<int>(PowerId::GIGANTIFICATION)] = 0;
    }
    if (player_power(PowerId::RAGE) > 0) add_player_power(PowerId::RAGE, -player_power(PowerId::RAGE));
    // one-two-punch / free attacks expire at end of turn
    if (player_power(PowerId::ONE_TWO_PUNCH) > 0) add_player_power(PowerId::ONE_TWO_PUNCH, -player_power(PowerId::ONE_TWO_PUNCH));
    if (player_power(PowerId::FREE_ATTACK) > 0) add_player_power(PowerId::FREE_ATTACK, -player_power(PowerId::FREE_ATTACK));
    if (player_power(PowerId::SETUP_STRIKE) > 0) add_player_power(PowerId::SETUP_STRIKE, -player_power(PowerId::SETUP_STRIKE));
    if (player_power(PowerId::EQUILIBRIUM) > 0) add_player_power(PowerId::EQUILIBRIUM, 0);
    if (player_power(PowerId::RETAIN_HAND) > 0) add_player_power(PowerId::RETAIN_HAND, -1);
    if (player_power(PowerId::NO_BLOCK) > 0) add_player_power(PowerId::NO_BLOCK, -1);
    if (player_power(PowerId::TENDER) > 0) {
        player.strength += cardsPlayedThisTurn;
        player.dexterity += cardsPlayedThisTurn;
    }
    player.power[static_cast<int>(PowerId::RINGING)] = 0;

    monster_turn();
    if (outcome == Outcome::UNDECIDED && player_power(PowerId::THE_GAMBIT) > 0 &&
        player.tookUnblockedAttackDamageThisCombat) {
        player.hp = 0;
        if (!try_fairy_revive()) outcome = Outcome::PLAYER_LOSS;
    }
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < monsterCount; ++i) {
        if (monsters[i].tempStrengthLoss != 0) {
            monsters[i].strength += monsters[i].tempStrengthLoss;
            monsters[i].tempStrengthLoss = 0;
        }
    }
    if (player.vulnerable > 0) --player.vulnerable;
    if (player.weak > 0 && !weakSkipTick) --player.weak;
    if (player.frail > 0 && !frailSkipTick) --player.frail;
    weakSkipTick = false;
    frailSkipTick = false;
    if (player_power(PowerId::SHRINK) > 0) add_player_power(PowerId::SHRINK, -1);
    add_player_power(PowerId::FLAME_BARRIER, 0);
    player.power[static_cast<int>(PowerId::FLAME_BARRIER)] = 0;
    player.power[static_cast<int>(PowerId::COLOSSUS)] = 0;
    player.power[static_cast<int>(PowerId::NO_DRAW)] = 0;
    player.power[static_cast<int>(PowerId::EQUILIBRIUM)] = 0;
    start_player_turn();
}

void BattleContext::monster_turn() {
    inMonsterTurn = true;
    for (int i = 0; i < monsterCount; ++i) {
        if (!monsters[i].alive) continue;
        monster_act(*this, monsters[i]);
        check_outcome();
        if (outcome != Outcome::UNDECIDED) break;
    }
    inMonsterTurn = false;
}

// ---------------------------------------------------------------- piles

void BattleContext::shuffle_discard_into_draw() {
    if (discardCount == 0) return;
    for (int i = 0; i < discardCount; ++i) draw[i] = discard[i];
    drawCount = discardCount;
    discardCount = 0;
    rng.shuffle(draw, drawCount);
    relics_shuffled(*this);
    if (player_power(PowerId::STRATAGEM) > 0 && drawCount > 0) {
        const int idx = rng.next_int(0, drawCount - 1);
        Card c = draw[idx];
        remove_at(draw, drawCount, idx);
        add_card_to_hand(c);
    }
}

void BattleContext::draw_cards(int count) {
    if (player_power(PowerId::NO_DRAW) > 0) return;
    for (int i = 0; i < count; ++i) {
        if (drawCount == 0) {
            shuffle_discard_into_draw();
            if (drawCount == 0) break;
        }
        Card c = draw[--drawCount];
        ++cardsDrawnThisTurn;
        if (player_power(PowerId::AUTOMATION) > 0 && cardsDrawnThisTurn % 10 == 0) {
            player.energy += player_power(PowerId::AUTOMATION);
        }
        if (player_power(PowerId::HELLRAISER) > 0 && card_is_strike(c)) {
            const int target = random_alive_monster();
            c.costForTurn = 0;
            play_card_effect(c, target >= 0 ? target : 0);
            if (pending.op == ChoiceOp::NONE) finish_played_card(c);
            continue;
        }
        add_card_to_hand(c);
        if (c.id == CardId::VOID) {
            player.energy -= card_var(c, VarId::ENERGY);
            if (player.energy < 0) player.energy = 0;
        }
    }
}

void BattleContext::discard_hand() {
    // end-of-turn in-hand status/curses triggers (C# HasTurnEndInHandEffect).
    const int handAtEnd = handCount;
    for (int i = 0; i < handCount && outcome == Outcome::UNDECIDED; ++i) {
        const Card &c = hand[i];
        switch (c.id) {
            case CardId::BURN:
            case CardId::TOXIC:
            case CardId::INFECTION:
                damage_player(card_var(c, VarId::DAMAGE));
                break;
            case CardId::BECKON:
                lose_hp(card_var(c, VarId::HP_LOSS));
                break;
            // Curses -----------------------------------------------------
            case CardId::DECAY:  // DamageVar 2, unpowered but blockable
                damage_player(card_var(c, VarId::DAMAGE));
                break;
            case CardId::BAD_LUCK:  // 13 unblockable/unpowered
                lose_hp(card_var(c, VarId::HP_LOSS));
                break;
            case CardId::REGRET:  // HP loss equal to cards in hand at turn end
                lose_hp(handAtEnd);
                break;
            case CardId::DOUBT: {
                // Apply 1 Weak; an existing Weak keeps its normal tick.
                if (player.weak == 0) weakSkipTick = true;
                player.weak += card_var(c, VarId::WEAK);
                break;
            }
            case CardId::SHAME: {
                if (player.frail == 0) frailSkipTick = true;
                player.frail += card_var(c, VarId::FRAIL);
                break;
            }
            case CardId::DEBT: {
                const int loss = std::min(card_var(c, VarId::GOLD), gold);
                gold -= loss;
                break;
            }
            default:
                break;
        }
    }
    Card kept[MAX_HAND];
    int keptN = 0;
    const bool retainAll = player_power(PowerId::RETAIN_HAND) > 0 ||
                           player_power(PowerId::EQUILIBRIUM) > 0 ||
                           relic_has(*this, RelicId::RUNIC_PYRAMID);
    while (handCount > 0) {
        Card c = hand[--handCount];
        if (card_has(c, CF_RETAIN) || retainAll) {
            if (keptN < MAX_HAND) kept[keptN++] = c;
        } else if (card_has(c, CF_ETHEREAL) || c.etherealThisCombat ||
                   player_power(PowerId::HEX) > 0) {
            move_to_exhaust(c);
        } else {
            move_to_discard(c);
        }
    }
    for (int i = keptN - 1; i >= 0; --i) hand[handCount++] = kept[i];
}

void BattleContext::move_to_discard(const Card &c) {
    if (discardCount < MAX_PILE) discard[discardCount++] = c;
}

void BattleContext::move_to_exhaust(const Card &c) {
    if (exhaustCount < MAX_PILE) exhaust[exhaustCount++] = c;
    ++exhaustedThisTurn;
    ++exhaustedThisCombat;
    trigger_exhaust_hooks(c);
}

void BattleContext::add_card_to_hand(const Card &c) {
    Card card = c;
    if (card.id == CardId::STOMP) {
        const int base = card.upgraded ? card_def(card.id).costUp : card_def(card.id).cost;
        card.costForTurn = static_cast<std::int8_t>(std::max(0, base - attacksPlayedThisTurn));
    }
    if (handCount < MAX_HAND) hand[handCount++] = card;
    else move_to_discard(card);
}

void BattleContext::add_card_to_discard(const Card &c) {
    move_to_discard(c);
}

void BattleContext::add_card_to_draw_top(const Card &c) {
    if (drawCount < MAX_PILE) draw[drawCount++] = c;
    else move_to_discard(c);
}

void BattleContext::trigger_exhaust_hooks(const Card &c) {
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::DARK_EMBRACE) > 0) {
        draw_cards(player_power(PowerId::DARK_EMBRACE));
    }
    if (player_power(PowerId::FEEL_NO_PAIN) > 0) {
        gain_block(player_power(PowerId::FEEL_NO_PAIN), false);
    }
    if (c.id == CardId::DRUM_OF_BATTLE_CARD && card_is_power(c)) {
        player.energy += 1;
    }
    relics_exhausted(*this, c);
}

// ---------------------------------------------------------------- damage

int BattleContext::calc_player_damage(int base, int monsterIdx) const {
    float dmg = static_cast<float>(base + player.strength + player.tempStrength);
    if (player_power(PowerId::VIGOR) > 0) dmg += player_power(PowerId::VIGOR);
    if (player_power(PowerId::GIGANTIFICATION) > 0) dmg *= 2.0f;
    if (player.weak > 0) dmg *= 0.75f;
    if (player_power(PowerId::SHRINK) > 0) dmg *= 0.7f;
    if (monsterIdx >= 0 && monsterIdx < monsterCount) {
        const Monster &m = monsters[monsterIdx];
        if (m.vulnerable > 0) {
            dmg *= relic_has(*this, RelicId::PAPER_PHROG) ? 1.75f : 1.5f;
            if (player_power(PowerId::CRUELTY) > 0) dmg *= 1.0f + player_power(PowerId::CRUELTY) / 100.0f;
        }
        if (m.power[static_cast<int>(PowerId::GRAPPLE)] > 0) {
            dmg += static_cast<float>(m.power[static_cast<int>(PowerId::GRAPPLE)]);
        }
    }
    const int result = static_cast<int>(std::floor(dmg));
    return result > 0 ? result : 0;
}

int BattleContext::calc_monster_damage(const Monster &m, int base) const {
    float dmg = static_cast<float>(base + m.strength + m.power[static_cast<int>(PowerId::VIGOR)]);
    if (m.power[static_cast<int>(PowerId::SHRINK)] > 0) dmg *= 0.7f;
    if (m.weak > 0) dmg *= 0.75f;
    if (player.vulnerable > 0) dmg *= 1.5f;
    if (player_power(PowerId::COLOSSUS) > 0 && player.vulnerable > 0) dmg *= 0.5f;
    const int result = static_cast<int>(std::floor(dmg));
    return result > 0 ? result : 0;
}

void BattleContext::damage_monster(int idx, int amount, bool fromPlayer) {
    if (idx < 0 || idx >= monsterCount) return;
    Monster &m = monsters[idx];
    if (!m.alive || m.reviving) return;
    (void) fromPlayer;
    int remaining = amount;
    if (m.power[static_cast<int>(PowerId::INTANGIBLE)] > 0 && remaining > 1) remaining = 1;
    const bool hadBlock = m.block > 0;
    if (m.block > 0) {
        const int blocked = remaining < m.block ? remaining : m.block;
        m.block -= blocked;
        remaining -= blocked;
    }
    if (hadBlock && m.block == 0 && remaining > 0 && relic_has(*this, RelicId::HAND_DRILL)) {
        apply_vulnerable(idx, 2);
    }
    if (remaining > 0) {
        const bool hadAsleep = m.power[static_cast<int>(PowerId::ASLEEP)] > 0;
        m.hp -= remaining;
        // Lagavulin: any unblocked damage wakes it, strips Plating and stuns it.
        if (hadAsleep) {
            m.power[static_cast<int>(PowerId::ASLEEP)] = 0;
            m.power[static_cast<int>(PowerId::PLATING)] = 0;
        }
        if (m.power[static_cast<int>(PowerId::CURL_UP)] > 0) {
            m.block += m.power[static_cast<int>(PowerId::CURL_UP)];
            m.power[static_cast<int>(PowerId::CURL_UP)] = 0;
        }
        if (fromPlayer && m.power[static_cast<int>(PowerId::THORNS)] > 0 &&
            outcome == Outcome::UNDECIDED) {
            damage_player(m.power[static_cast<int>(PowerId::THORNS)], true);
        }
        if (m.hp <= 0) {
            m.hp = 0;
            const MonsterDef &def = monster_def(m.id);
            if (m.power[static_cast<int>(PowerId::ADAPTABLE)] > 0 &&
                def.reviveState != 255 && m.aux[0] < 2) {
                // Test Subject: knocked out, revives on its next turn.
                m.reviving = true;
                m.move = def.reviveState;
                m.block = 0;
                roll_intent(*this, m);
            } else {
                m.alive = false;
                relics_monster_died(*this);
            }
        }
    }
    check_outcome();
}

void BattleContext::attack_monster(int target, int base, int hits) {
    for (int i = 0; i < hits; ++i) {
        if (outcome != Outcome::UNDECIDED) return;
        if (target < 0 || target >= monsterCount || !monsters[target].alive) return;
        damage_monster(target, calc_player_damage(base, target));
    }
}

void BattleContext::attack_random_monster(int base, int hits) {
    for (int i = 0; i < hits; ++i) {
        if (outcome != Outcome::UNDECIDED) return;
        const int idx = random_alive_monster();
        if (idx < 0) return;
        damage_monster(idx, calc_player_damage(base, idx));
    }
}

void BattleContext::attack_all(int base, int hits) {
    for (int h = 0; h < hits; ++h) {
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive || outcome != Outcome::UNDECIDED) continue;
            damage_monster(i, calc_player_damage(base, i));
        }
    }
}

void BattleContext::attack_from_card(Card &card, int target, int base, int hits, bool all) {
    int b = base;
    if (player_power(PowerId::VIGOR) > 0) {
        b += player_power(PowerId::VIGOR);
        add_player_power(PowerId::VIGOR, -player_power(PowerId::VIGOR));
    }
    for (int h = 0; h < hits; ++h) {
        if (outcome != Outcome::UNDECIDED) return;
        if (all) {
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive || outcome != Outcome::UNDECIDED) continue;
                damage_monster(i, relics_modify_damage(*this, calc_player_damage(b, i), i, &card));
            }
        } else {
            if (target < 0 || target >= monsterCount || !monsters[target].alive) return;
            damage_monster(target, relics_modify_damage(*this, calc_player_damage(b, target), target, &card));
        }
    }
}

int BattleContext::gain_block_raw(int amount) {
    float block = static_cast<float>(amount + player.dexterity + player.tempDexterity);
    if (player.frail > 0) block *= 0.75f;
    int result = static_cast<int>(std::floor(block));
    if (result < 0) result = 0;
    player.block += result;
    return result;
}

void BattleContext::gain_block(int amount, bool fromCard) {
    if (amount <= 0) return;
    if (fromCard && player_power(PowerId::NO_BLOCK) > 0) return;
    int value = amount;
    value = relics_modify_block_gain(*this, value, fromCard);
    if (fromCard && !gainedBlockFromCardThisTurn && player_power(PowerId::UNMOVABLE) > 0) {
        value *= 2;
    }
    const int before = player.block;
    gain_block_raw(value);
    const int gained = player.block - before;
    if (fromCard) gainedBlockFromCardThisTurn = true;
    if (gained > 0) trigger_block_hooks(gained);
}

void BattleContext::trigger_block_hooks(int amount) {
    if (player_power(PowerId::JUGGERNAUT) > 0 && amount > 0) {
        const int target = random_alive_monster();
        if (target >= 0) {
            damage_monster(target, player_power(PowerId::JUGGERNAUT));
        }
    }
}

void BattleContext::damage_player(int amount, bool unblockable) {
    if (amount <= 0 || outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::INTANGIBLE) > 0) amount = 1;
    int remaining = amount;
    if (!unblockable && player.block > 0) {
        const int blocked = remaining < player.block ? remaining : player.block;
        player.block -= blocked;
        remaining -= blocked;
    }
    if (remaining > 0) {
        if (player_power(PowerId::BUFFER) > 0) {
            add_player_power(PowerId::BUFFER, -1);
            remaining = 0;
        }
    }
    remaining = relics_modify_hp_loss(*this, remaining);
    if (remaining > 0) {
        player.hp -= remaining;
        hpLostThisTurn += remaining;
        hpLostThisCombat += remaining;
        ++unblockedHitsThisCombat;
        player.tookUnblockedDamageThisTurn = true;
        if (player_power(PowerId::THE_GAMBIT) > 0) player.tookUnblockedAttackDamageThisCombat = true;
        if (player.hp <= 0) {
            player.hp = 0;
            if (try_fairy_revive()) return;
            if (relics_try_revive(*this)) return;
            outcome = Outcome::PLAYER_LOSS;
            return;
        }
        relics_damage_received(*this, remaining);
        if (player_power(PowerId::RUPTURE) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RUPTURE));
        if (player_power(PowerId::INFERNO) > 0 && outcome == Outcome::UNDECIDED) {
            attack_all(player_power(PowerId::INFERNO));
        }
    }
}

void BattleContext::lose_hp(int amount, bool fromCard) {
    (void) fromCard;
    if (amount <= 0 || outcome != Outcome::UNDECIDED) return;
    amount = relics_modify_hp_loss(*this, amount);
    if (amount <= 0) return;
    player.hp -= amount;
    hpLostThisTurn += amount;
    hpLostThisCombat += amount;
    player.tookUnblockedDamageThisTurn = true;
    if (player.hp <= 0) {
        player.hp = 0;
        if (try_fairy_revive()) return;
        if (relics_try_revive(*this)) return;
        outcome = Outcome::PLAYER_LOSS;
        return;
    }
    if (player_power(PowerId::RUPTURE) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RUPTURE));
    if (player_power(PowerId::INFERNO) > 0) attack_all(player_power(PowerId::INFERNO));
}

void BattleContext::monster_attack_player(int monsterIdx, int base) {
    if (outcome != Outcome::UNDECIDED) return;
    Monster &m = monsters[monsterIdx];
    if (!m.alive) return;
    int dmg = calc_monster_damage(m, base);
    if (player_power(PowerId::DIAMOND_DIADEM) > 0) dmg /= 2;
    if (m.power[static_cast<int>(PowerId::VIGOR)] > 0) {
        m.power[static_cast<int>(PowerId::VIGOR)] = 0;
    }
    const bool had_block = player.block > 0;
    damage_player(dmg);
    (void) had_block;
    const int back = player_power(PowerId::THORNS) + player_power(PowerId::FLAME_BARRIER);
    if (back > 0 && m.alive) damage_monster(monsterIdx, back);
}

void BattleContext::apply_vulnerable(int idx, int amount) {
    if (idx >= 0 && idx < monsterCount && monsters[idx].alive) {
        if (monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)] > 0) {
            --monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)];
            return;
        }
        monsters[idx].vulnerable += amount;
        if (player_power(PowerId::VICIOUS) > 0) draw_cards(player_power(PowerId::VICIOUS));
    }
}

void BattleContext::apply_weak(int idx, int amount) {
    if (idx >= 0 && idx < monsterCount && monsters[idx].alive) {
        if (monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)] > 0) {
            --monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)];
            return;
        }
        monsters[idx].weak += amount;
    }
}

// ---------------------------------------------------------------- card pools

Card BattleContext::random_card_of_type(CardType type, bool include_colorless) {
    CardId pool[256];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type != type) continue;
        if (d.rarity == Rarity::SPECIAL || d.rarity == Rarity::BASIC) continue;
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        // reference pool membership is approximated by the manifest order;
        // colorless cards live after the Ironclad block.
        const bool is_colorless = i > static_cast<int>(CardId::WHIRLWIND) &&
                                  i < static_cast<int>(CardId::BECKON);
        if (!include_colorless && is_colorless) continue;
        pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, nextUid++);
    return make_card(pool[rng.next_int(0, n - 1)], false, nextUid++);
}

Card BattleContext::random_attack() { return random_card_of_type(CardType::ATTACK, true); }
Card BattleContext::random_skill() { return random_card_of_type(CardType::SKILL, true); }
Card BattleContext::random_power() { return random_card_of_type(CardType::POWER, true); }

Card BattleContext::random_colorless_card() {
    CardId pool[128];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type == CardType::STATUS || d.type == CardType::CURSE) continue;
        if (d.rarity == Rarity::BASIC || d.rarity == Rarity::SPECIAL) continue;
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        const bool is_colorless = i > static_cast<int>(CardId::WHIRLWIND) &&
                                  i < static_cast<int>(CardId::BECKON);
        if (is_colorless) pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, nextUid++);
    return make_card(pool[rng.next_int(0, n - 1)], false, nextUid++);
}

void BattleContext::add_random_card_to_hand(CardType type, bool free, bool colorless, bool upgraded) {
    Card c = colorless ? random_colorless_card() : random_card_of_type(type, true);
    if (upgraded) upgrade_card(c);
    if (free) c.costForTurn = 0;
    add_card_to_hand(c);
}

void BattleContext::upgrade_card(Card &c) {
    if (c.upgraded) return;
    c.upgraded = true;
    const CardDef &d = card_def(c.id);
    if (c.costForTurn != 0 || d.cost != 0) c.costForTurn = d.costUp;
    c.storedCost = d.costUp;
}

void BattleContext::transform_card(Card &c) {
    CardId pool[256];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type == CardType::STATUS || d.type == CardType::CURSE) continue;
        if (d.rarity == Rarity::SPECIAL || d.rarity == Rarity::BASIC) continue;
        if (d.flags & CF_MULTIPLAYER_ONLY) continue;
        pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return;
    const CardId id = pool[rng.next_int(0, n - 1)];
    const std::uint16_t uid = c.uid;
    c = make_card(id, false, uid);
}

// ---------------------------------------------------------------- choices

void BattleContext::start_choice(ChoiceOp op, ChoicePile pile, int count, bool optional,
                                 const Card &source, bool sourceExhaust, int payload,
                                 int candidateLimit) {
    pending = PendingChoice();
    pending.op = op;
    pending.pile = pile;
    pending.remaining = count;
    pending.optional = optional;
    pending.sourceCard = source;
    pending.hasSource = true;
    pending.sourceExhaust = sourceExhaust;
    pending.payload = payload;
    if (pile == ChoicePile::HAND) {
        for (int i = 0; i < handCount && pending.count < MAX_HAND; ++i) {
            if (op == ChoiceOp::UPGRADE && hand[i].upgraded) continue;
            pending.cards[pending.count++] = hand[i];
        }
    } else if (pile == ChoicePile::DISCARD) {
        for (int i = 0; i < discardCount && pending.count < MAX_HAND; ++i) {
            pending.cards[pending.count++] = discard[i];
        }
    } else if (pile == ChoicePile::DRAW) {
        int indices[MAX_PILE];
        for (int i = 0; i < drawCount; ++i) indices[i] = i;
        const int limit = std::min(candidateLimit, std::min(drawCount, MAX_HAND));
        for (int i = 0; i < limit; ++i) {
            const int j = i + rng.next_int(0, drawCount - 1 - i);
            std::swap(indices[i], indices[j]);
            pending.cards[pending.count++] = draw[indices[i]];
        }
    }
    if (pending.count == 0) pending = PendingChoice();
}

void BattleContext::start_draw_choice(const Card &source, bool sourceExhaust, int type, int rarity,
                                      int candidateLimit) {
    pending = PendingChoice();
    int indices[MAX_PILE];
    int n = 0;
    for (int i = 0; i < drawCount; ++i) {
        const CardDef &d = card_def(draw[i].id);
        if (d.flags & CF_UNPLAYABLE) continue;
        if (type >= 0 && static_cast<int>(d.type) != type) continue;
        if (rarity >= 0 && static_cast<int>(d.rarity) != rarity) continue;
        indices[n++] = i;
    }
    const int limit = candidateLimit < 0 ? n : std::min(candidateLimit, n);
    for (int i = 0; i < limit && pending.count < MAX_HAND; ++i) {
        const int j = i + rng.next_int(0, n - 1 - i);
        std::swap(indices[i], indices[j]);
        pending.cards[pending.count++] = draw[indices[i]];
    }
    if (pending.count == 0) return;
    pending.op = ChoiceOp::DRAW_TO_HAND;
    pending.pile = ChoicePile::DRAW;
    pending.remaining = 1;
    pending.optional = false;
    pending.sourceCard = source;
    pending.hasSource = true;
    pending.sourceExhaust = sourceExhaust;
}

void BattleContext::start_offer(ChoiceOp op, const Card *cards, int count,
                                const Card &source, bool sourceExhaust, bool free) {
    pending = PendingChoice();
    pending.op = op;
    pending.pile = ChoicePile::OFFER;
    pending.optional = false;
    pending.remaining = 1;
    pending.sourceCard = source;
    pending.hasSource = true;
    pending.sourceExhaust = sourceExhaust;
    pending.payload = free ? 1 : 0;
    for (int i = 0; i < count && i < MAX_HAND; ++i) pending.cards[pending.count++] = cards[i];
    if (pending.count == 0) pending = PendingChoice();
}

void BattleContext::finish_pending_source() {
    if (!pending.hasSource) {
        pending = PendingChoice();
        return;
    }
    Card src = pending.sourceCard;
    const bool exhaustIt = pending.sourceExhaust;
    pending = PendingChoice();
    if (exhaustIt) move_to_exhaust(src);
    else move_to_discard(src);
}

void BattleContext::maybe_finish_pending() {
    if (pending.op == ChoiceOp::NONE) return;
    if (pending.remaining <= 0 || pending.count == 0) {
        const ChoiceOp op = pending.op;
        const int payload = pending.payload;
        const Card src = pending.sourceCard;
        finish_pending_source();
        if (op == ChoiceOp::DISCARD_ANY) draw_cards(payload);
        if (src.id == CardId::BURNING_PACT) draw_cards(card_var(src, VarId::CARDS));
        if (src.id == CardId::BRAND) add_player_power(PowerId::STRENGTH, card_var(src, VarId::STRENGTH));
        if (src.id == CardId::SEEKER_STRIKE) { /* chosen card already added */ }
        check_outcome();
    }
}

void BattleContext::auto_resolve_pending() {
    int guard = 0;
    while (pending.op != ChoiceOp::NONE && pending.count > 0 && pending.remaining > 0 &&
           guard++ < 64) {
        resolve_choice(pending.cards[0].uid);
    }
    if (pending.op != ChoiceOp::NONE) {
        pending.remaining = 0;
        maybe_finish_pending();
        if (pending.op != ChoiceOp::NONE) pending = PendingChoice();
    }
}

void BattleContext::resolve_choice(std::uint16_t uid) {
    if (pending.op == ChoiceOp::NONE) return;
    const ChoiceOp op = pending.op;
    const ChoicePile pile = pending.pile;
    Card chosen{};
    bool found = false;
    if (pile == ChoicePile::HAND) {
        for (int i = 0; i < handCount; ++i) if (hand[i].uid == uid) {
            chosen = hand[i];
            remove_at(hand, handCount, i);
            found = true;
            break;
        }
    } else if (pile == ChoicePile::DISCARD) {
        for (int i = 0; i < discardCount; ++i) if (discard[i].uid == uid) {
            chosen = discard[i];
            remove_at(discard, discardCount, i);
            found = true;
            break;
        }
    } else if (pile == ChoicePile::DRAW) {
        for (int i = 0; i < drawCount; ++i) if (draw[i].uid == uid) {
            chosen = draw[i];
            remove_at(draw, drawCount, i);
            found = true;
            break;
        }
    } else if (pile == ChoicePile::OFFER) {
        for (int i = 0; i < pending.count; ++i) if (pending.cards[i].uid == uid) {
            chosen = pending.cards[i];
            found = true;
            break;
        }
    }
    if (!found) {
        // Stale candidate (the pile changed since the choice was offered): drop it
        // so the choice cannot deadlock the combat.
        for (int i = 0; i < pending.count; ++i) {
            if (pending.cards[i].uid == uid) {
                remove_at(pending.cards, pending.count, i);
                break;
            }
        }
        --pending.remaining;
        maybe_finish_pending();
        return;
    }

    switch (op) {
        case ChoiceOp::UPGRADE:
            // chosen was removed from hand above; put it back upgraded
            upgrade_card(chosen);
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::EXHAUST:
            move_to_exhaust(chosen);
            break;
        case ChoiceOp::RETURN_DISCARD_TOP:
            add_card_to_draw_top(chosen);
            break;
        case ChoiceOp::PUT_HAND_TOP:
            add_card_to_draw_top(chosen);
            break;
        case ChoiceOp::DRAW_TO_HAND:
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::DISCARD_TO_HAND:
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::OFFER_TO_HAND:
            if (pending.payload) chosen.costForTurn = 0;
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::GIVE_REPLAY:
            chosen.replay = static_cast<std::uint8_t>(pending.payload);
            add_card_to_draw_top(chosen);
            break;
        case ChoiceOp::TRANSFORM:
            transform_card(chosen);
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::MAKE_FREE:
            chosen.freeCombat = true;
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::DISCARD_ANY:
            move_to_discard(chosen);
            ++pending.payload;
            break;
        default:
            break;
    }
    --pending.remaining;
    // remove chosen candidate from the pending list
    for (int i = 0; i < pending.count; ++i) {
        if (pending.cards[i].uid == uid) {
            remove_at(pending.cards, pending.count, i);
            break;
        }
    }
    maybe_finish_pending();
}

// ---------------------------------------------------------------- playing

std::vector<Action> BattleContext::legal_actions() const {
    std::vector<Action> actions;
    if (outcome != Outcome::UNDECIDED) return actions;
    if (pending.op != ChoiceOp::NONE) {
        for (int i = 0; i < pending.count; ++i) {
            Action a;
            a.type = ActionType::CHOOSE;
            a.uid = pending.cards[i].uid;
            actions.push_back(a);
        }
        if (pending.optional) {
            Action c;
            c.type = ActionType::CONFIRM;
            actions.push_back(c);
        }
        return actions;
    }
    Action end;
    end.type = ActionType::END_TURN;
    actions.push_back(end);
    const bool noMoreCards = normality_blocks(*this);
    for (int i = 0; i < handCount && !noMoreCards; ++i) {
        const Card &c = hand[i];
        if (!card_is_playable(c)) continue;
        if (c.id == CardId::PACTS_END && exhaustCount < card_var(c, VarId::CARDS)) continue;
        if (player_power(PowerId::RINGING) > 0 && cardsPlayedThisTurn > 0) continue;
        if (skillsLocked && card_is_skill(c)) continue;
        if (relic_has(*this, RelicId::VELVET_CHOKER) && cardsPlayedThisTurn >= 6) continue;
        int cost = card_cost(c);
        if (player_power(PowerId::CORRUPTION) > 0 && card_is_skill(c)) cost = 0;
        if (card_is_attack(c) && player_power(PowerId::FREE_ATTACK) > 0) cost = 0;
        if (relic_has(*this, RelicId::BRILLIANT_SCARF) && cardsPlayedThisTurn == 4) cost = 0;
        if (cost > 0 && player_power(PowerId::CHAINS_OF_BINDING) > 0) ++cost;
        if (relic_has(*this, RelicId::SPIKED_GAUNTLETS) && card_is_power(c) && cost > 0) ++cost;
        if (cost > player.energy) continue;
        if (card_def(c.id).target == TargetType::ENEMY) {
            for (int m = 0; m < monsterCount; ++m) {
                if (!monsters[m].alive) continue;
                Action a;
                a.type = ActionType::PLAY_CARD;
                a.hand = static_cast<std::uint8_t>(i);
                a.target = static_cast<std::uint8_t>(m);
                actions.push_back(a);
            }
        } else {
            Action a;
            a.type = ActionType::PLAY_CARD;
            a.hand = static_cast<std::uint8_t>(i);
            a.target = 0;
            actions.push_back(a);
        }
    }
    for (int i = 0; i < potionCount; ++i) {
        if (!can_use_potion(i)) continue;
        const PotionDef &d = potion_def(static_cast<PotionId>(potions[i]));
        if (d.target == PotionTarget::ANY_ENEMY) {
            for (int m = 0; m < monsterCount; ++m) {
                if (!monsters[m].alive) continue;
                Action a;
                a.type = ActionType::USE_POTION;
                a.hand = static_cast<std::uint8_t>(i);
                a.target = static_cast<std::uint8_t>(m);
                actions.push_back(a);
            }
        } else {
            Action a;
            a.type = ActionType::USE_POTION;
            a.hand = static_cast<std::uint8_t>(i);
            actions.push_back(a);
        }
    }
    return actions;
}

bool BattleContext::step(const Action &action) {
    if (outcome != Outcome::UNDECIDED) return false;
    if (pending.op != ChoiceOp::NONE) {
        if (action.type == ActionType::CHOOSE) {
            const bool exists = [&] {
                for (int i = 0; i < pending.count; ++i) if (pending.cards[i].uid == action.uid) return true;
                return false;
            }();
            if (!exists) return false;
            resolve_choice(action.uid);
            return true;
        }
        if (action.type == ActionType::CONFIRM && pending.optional) {
            pending.remaining = 0;
            maybe_finish_pending();
            return true;
        }
        return false;
    }
    if (action.type == ActionType::END_TURN) {
        end_player_turn();
        return true;
    }
    if (action.type == ActionType::PLAY_CARD) {
        if (action.hand >= handCount) return false;
        if (normality_blocks(*this)) return false;
        const Card &c = hand[action.hand];
        if (!card_is_playable(c)) return false;
        if (c.id == CardId::PACTS_END && exhaustCount < card_var(c, VarId::CARDS)) return false;
        if (player_power(PowerId::RINGING) > 0 && cardsPlayedThisTurn > 0) return false;
        if (skillsLocked && card_is_skill(c)) return false;
        if (card_def(c.id).target == TargetType::ENEMY) {
            if (action.target >= monsterCount || !monsters[action.target].alive) return false;
        }
        play_card(action.hand, action.target);
        return true;
    }
    if (action.type == ActionType::USE_POTION) {
        if (!can_use_potion(action.hand)) return false;
        const PotionDef &d = potion_def(static_cast<PotionId>(potions[action.hand]));
        if (d.target == PotionTarget::ANY_ENEMY &&
            (action.target >= monsterCount || !monsters[action.target].alive)) {
            return false;
        }
        use_potion(action.hand, action.target);
        return true;
    }
    return false;
}

void BattleContext::play_card(int handIdx, int target) {
    if (handIdx < 0 || handIdx >= handCount) return;
    if (normality_blocks(*this)) return;
    Card card = hand[handIdx];
    int cost = card_cost(card);
    if (player_power(PowerId::CORRUPTION) > 0 && card_is_skill(card)) cost = 0;
    if (card_is_attack(card) && player_power(PowerId::FREE_ATTACK) > 0) {
        cost = 0;
        add_player_power(PowerId::FREE_ATTACK, -1);
    }
    if (relic_has(*this, RelicId::BRILLIANT_SCARF) && cardsPlayedThisTurn == 4) cost = 0;
    if (player_power(PowerId::CHAINS_OF_BINDING) > 0 && cost > 0) ++cost;
    if (relic_has(*this, RelicId::SPIKED_GAUNTLETS) && card_is_power(card) && cost > 0) ++cost;
    if (player_power(PowerId::RINGING) > 0 && cardsPlayedThisTurn > 0) return;
    if (skillsLocked && card_is_skill(card)) return;
    if (relic_has(*this, RelicId::VELVET_CHOKER) && cardsPlayedThisTurn >= 6) return;
    int x = cost < 0 ? player.energy : 0;
    if (cost < 0 && relic_has(*this, RelicId::CHEMICAL_X)) x += 2;
    const int spend = cost < 0 ? player.energy : cost;
    if (spend > player.energy) return;

    player.energy -= spend;
    xCost = x;
    remove_at(hand, handCount, handIdx);
    ++cardsPlayedThisTurn;
    ++cardsPlayedThisCombat;
    if (card_is_attack(card)) {
        ++attacksPlayedThisTurn;
        ++attacksPlayedThisCombat;
    }
    if (card_is_skill(card)) {
        ++skillsPlayedThisTurn;
        ++skillsPlayedThisCombat;
    }
    relics_card_about_to_play(*this, card);

    returnToHand = false;
    int plays = 1 + card.replay + card.bonusReplay;
    if (card_is_attack(card) && player_power(PowerId::ONE_TWO_PUNCH) > 0) {
        plays += 1;
        add_player_power(PowerId::ONE_TWO_PUNCH, -1);
    }
    if (player_power(PowerId::DUPLICATION) > 0) {
        plays += 1;
        add_player_power(PowerId::DUPLICATION, -1);
    }
    if (relic_has(*this, RelicId::THROWING_AXE) && relic_aux(*this, RelicId::THROWING_AXE) == 0) {
        plays += 1;
        relic_aux_set(*this, RelicId::THROWING_AXE, 1);
    }
    for (int i = 0; i < plays && outcome == Outcome::UNDECIDED; ++i) {
        Card copy = card;
        play_card_effect(copy, target);
        card = copy;
    }

    after_card_played(card);

    if (pending.op != ChoiceOp::NONE) {
        pending.sourceCard = card;
        pending.hasSource = true;
        pending.sourceExhaust = card_exhausts(*this, card);
    } else {
        finish_played_card(card);
    }
}

void BattleContext::after_card_played(const Card &card) {
    if (outcome != Outcome::UNDECIDED) return;
    if (card_is_attack(card)) {
        if (player_power(PowerId::RAGE) > 0) gain_block(player_power(PowerId::RAGE), false);
        if (player_power(PowerId::CALAMITY) > 0) add_random_card_to_hand(CardType::ATTACK, true);
        if (player_power(PowerId::JUGGLING) > 0 && attacksPlayedThisTurn == 3 && !jugglingTriggeredThisTurn) {
            jugglingTriggeredThisTurn = true;
            for (int n = 0; n < player_power(PowerId::JUGGLING); ++n) {
                Card copy = card;
                copy.uid = nextUid++;
                copy.costForTurn = copy.upgraded ? card_def(copy.id).costUp : card_def(copy.id).cost;
                add_card_to_hand(copy);
            }
        }
    }
    if (card_is_skill(card) && player_power(PowerId::SMOGGY) > 0) skillsLocked = true;
    if (player_power(PowerId::TENDER) > 0) {
        player.strength -= 1;
        player.dexterity -= 1;
    }
    if (card_is_attack(card) || card_is_skill(card)) {
        if (player_power(PowerId::NOSTALGIA) > 0 && !playedAttackOrSkillThisTurn) {
            nostalgiaPending = true;
        }
        playedAttackOrSkillThisTurn = true;
    }
    if (player_power(PowerId::PANACHE) > 0 && cardsPlayedThisTurn % 5 == 0) {
        attack_all(player_power(PowerId::PANACHE));
    }
    check_outcome();
}

void BattleContext::finish_played_card(const Card &card) {
    if (outcome != Outcome::UNDECIDED) {
        move_to_discard(card);
        return;
    }
    relics_card_played(*this, card);
    if (returnToHand) {
        returnToHand = false;
        return;  // already queued in returnNextTurn
    }
    Card played = card;
    if (relic_has(*this, RelicId::RAZOR_TOOTH) &&
        (card_is_attack(played) || card_is_skill(played)) && card_upgradable(played)) {
        played.upgraded = true;
    }
    if (nostalgiaPending) {
        nostalgiaPending = false;
        add_card_to_draw_top(played);
        return;
    }
    if (card_exhausts(*this, played)) move_to_exhaust(played);
    else move_to_discard(played);
    check_outcome();
}

void BattleContext::auto_play_random(const Card &card, bool exhaustIt) {
    Card c = card;
    if (!card_is_playable(c)) {
        if (exhaustIt) move_to_exhaust(c);
        else move_to_discard(c);
        return;
    }
    int target = 0;
    if (card_def(c.id).target == TargetType::ENEMY || card_def(c.id).target == TargetType::RANDOM_ENEMY) {
        target = random_alive_monster();
        if (target < 0) target = 0;
    }
    c.costForTurn = 0;
    xCost = 0;
    returnToHand = false;
    play_card_effect(c, target);
    // auto-pick the first option for choice cards played through effects
    auto_resolve_pending();
    if (exhaustIt) move_to_exhaust(c);
    else finish_played_card(c);
}

void BattleContext::play_card_effect(Card &card, int target) {
    if (ironclad_effect(*this, card, target)) return;
    if (colorless_effect(*this, card, target)) return;
    if (status_effect(*this, card, target)) return;
    // generic fallback for plain damage/block cards
    if (card_is_attack(card)) {
        if (card_def(card.id).target == TargetType::ALL_ENEMIES) attack_from_card(card, target, card_damage(card), 1, true);
        else if (card_def(card.id).target == TargetType::RANDOM_ENEMY) attack_random_monster(card_damage(card));
        else attack_from_card(card, target, card_damage(card));
    } else if (card_block(card) > 0) {
        gain_block(card_block(card), true);
    }
}

bool BattleContext::card_will_exhaust(const Card &c) const {
    return card_exhausts(*this, c);
}

}  // namespace sts2
