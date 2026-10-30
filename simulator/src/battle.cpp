#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/effects.h"
#include "sts2/relics.h"

#include <algorithm>
#include <cstring>
#include <cstdio>
#include <stdexcept>
#include <tuple>

namespace sts2 {
#include "sts2/cards_generated.inc"
}

namespace sts2 {

void BattleContext::clear_card_uid_reservations() {
    std::memset(uidReservations, 0, sizeof(uidReservations));
}

std::uint16_t BattleContext::allocate_card_uid() {
    auto used = [this](std::uint16_t uid) {
        if (uidReservations[uid / 64] & (std::uint64_t{1} << (uid % 64))) return true;
        for (int i = 0; i < originalDeckCount; ++i) if (originalDeckUids[i] == uid) return true;
        for (int i = 0; i < theftCount; ++i) if (theftUids[i] == uid) return true;
        for (int i = 0; i < playedThisTurnCount; ++i) if (playedThisTurn[i] == uid) return true;
        for (int i = 0; i < playedLastTurnCount; ++i) if (playedLastTurn[i] == uid) return true;
        if (hasLastPlayed && lastPlayedCard.uid == uid) return true;
        auto in = [uid](const Card *cards, int count) {
            for (int i = 0; i < count; ++i) if (cards[i].uid == uid) return true;
            return false;
        };
        return in(hand, handCount) || in(draw, drawCount) || in(discard, discardCount) ||
               in(exhaust, exhaustCount) || in(playPile, playCount) ||
               in(returnNextTurn, returnNextTurnCount) || in(pending.cards, pending.count) ||
               (pending.hasSource && pending.sourceCard.uid == uid) ||
               (activePlay.active && activePlay.card.uid == uid);
    };
    unsigned candidate = nextUid;
    if (candidate == 0 || candidate == 65535) candidate = 1;
    for (unsigned i = 0; i < 65534; ++i) {
        auto uid = static_cast<std::uint16_t>(candidate);
        candidate = candidate == 65534 ? 1 : candidate + 1;
        if (used(uid)) continue;
        uidReservations[uid / 64] |= std::uint64_t{1} << (uid % 64);
        nextUid = static_cast<std::uint16_t>(candidate);
        return uid;
    }
    return 0;
}

std::uint16_t BattleContext::require_card_uid() {
    const std::uint16_t uid = allocate_card_uid();
    if (uid == 0) throw std::overflow_error("battle card UID space exhausted");
    return uid;
}

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

static bool enthralled_blocks(const BattleContext &bc, const Card &card) {
    if (card.id == CardId::ENTHRALLED) return false;
    for (int i = 0; i < bc.handCount; ++i) {
        if (bc.hand[i].id == CardId::ENTHRALLED) return true;
    }
    return false;
}

void BattleContext::face_surrounded_target(int target) {
    if (player_power(PowerId::SURROUNDED) <= 0 ||
        target < 0 || target >= monsterCount) return;
    const Monster &monster = monsters[target];
    if (monster.power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] > 0)
        player.surroundedFacingRight = false;
    else if (monster.power[static_cast<int>(PowerId::BACK_ATTACK_RIGHT)] > 0)
        player.surroundedFacingRight = true;
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

bool BattleContext::can_trigger_fatal(int target) const {
    if (target < 0 || target >= monsterCount || !monsters[target].alive ||
        monsters[target].reviving || monsters[target].power[static_cast<int>(PowerId::MINION)] > 0)
        return false;
    if (monsters[target].power[static_cast<int>(PowerId::REATTACH)] > 0) {
        for (int i = 0; i < monsterCount; ++i) {
            if (i != target && monsters[i].id == MonsterId::DECIMILLIPEDE_SEGMENT &&
                monsters[i].alive && !monsters[i].reviving && monsters[i].hp > 0) return false;
        }
    }
    return true;
}

void BattleContext::gain_gold(int amount) {
    if (amount <= 0 || relic_has(*this, RelicId::ECTOPLASM)) return;
    const int bonus = relic_has(*this, RelicId::BOWLER_HAT) ? amount / 5 : 0;
    gold += amount + bonus;
    combatGold += amount + bonus;
    if (relic_has(*this, RelicId::DRAGON_FRUIT)) {
        const int gains = 1 + (bonus > 0 ? 1 : 0);
        player.maxHp += gains;
        player.hp += gains;
    }
}

// Powers that count as visible Debuffs for ArtifactPower (a positive amount of
// one of these is intercepted by Artifact, whatever its source).
static bool power_is_debuff(PowerId id) {
    switch (id) {
        case PowerId::VULNERABLE:
        case PowerId::WEAK:
        case PowerId::FRAIL:
        case PowerId::SHRINK:
        case PowerId::NO_DRAW:
        case PowerId::TANGLED:
        case PowerId::SLOW:
        case PowerId::CHAINS_OF_BINDING:
        case PowerId::SMOGGY:
        case PowerId::RINGING:
        case PowerId::HEX:
        case PowerId::DAMPEN:
        case PowerId::PAPER_CUTS:
        case PowerId::SUCK:
        case PowerId::TENDER:
        case PowerId::GRAPPLE:
            return true;
        default:
            return false;
    }
}

void BattleContext::add_player_power(PowerId id, int amount) {
    // ArtifactPower.TryModifyPowerAmountReceived: any visible Debuff applied to
    // the owner is zeroed and consumes one Artifact charge.
    if (amount > 0 && power_is_debuff(id) && player_power(PowerId::ARTIFACT) > 0) {
        add_player_power(PowerId::ARTIFACT, -1);
        return;
    }
    // PowerCmd.Apply: a Debuff applied to a player skips its first duration
    // tick (WeakPower/FrailPower/VulnerablePower.AfterTurnEnd -> TickDownDuration).
    if (amount > 0 && power_is_debuff(id)) {
        if (id == PowerId::WEAK) weakSkipTick = true;
        if (id == PowerId::FRAIL) frailSkipTick = true;
        if (id == PowerId::VULNERABLE) vulnerableSkipTick = true;
    }
    if (id == PowerId::STRENGTH && amount > 0) relics_strength_gain(*this, amount);
    if (id == PowerId::AUTOMATION && amount > 0 && automationCount < MAX_AUTOMATION) {
        // AutomationPower.IsInstanced: each application counts its own ten
        // drawn cards (Data.cardsLeft), never a shared per-turn total.
        automationLeft[automationCount] = 10;
        automationAmount[automationCount] = amount;
        ++automationCount;
    }
    if (id == PowerId::ROLLING_BOULDER && amount > 0 && rollingCount < MAX_PILE) {
        rollingDamage[rollingCount++] = amount;
    }
    if (id == PowerId::PANACHE && amount > 0 && panacheCount < MAX_PILE) {
        panacheDamage[panacheCount] = amount;
        panacheLeft[panacheCount] = 5;
        panachePrimed[panacheCount] = false;
        ++panacheCount;
    }
    power_ref(player, id) += static_cast<std::int16_t>(amount);
}

void BattleContext::add_monster_power(int idx, PowerId id, int amount) {
    if (idx < 0 || idx >= monsterCount) return;
    // Monster-side Artifact (beetle shrink, potions, ...).
    if (amount > 0 && power_is_debuff(id) &&
        monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)] > 0) {
        --monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)];
        return;
    }
    if (id == PowerId::GRAPPLE && amount > 0 && monsters[idx].grappleCount < MAX_PILE) {
        Monster &monster = monsters[idx];
        monster.grappleAmounts[monster.grappleCount++] = amount;
    }
    power_ref(monsters[idx], id) += static_cast<std::int16_t>(amount);
    if (id == PowerId::ILLUSION && amount > 0) {
        monsters[idx].power[static_cast<int>(PowerId::MINION)] = 1;
    }
}

static bool card_exhausts(const BattleContext &bc, const Card &c) {
    if (card_has(c, CF_EXHAUST)) return true;
    if (bc.player_power(PowerId::CORRUPTION) > 0 && card_is_skill(c)) return true;
    // Power cards leave combat (PileType.None); they are never exhausted and do
    // not trigger exhaust hooks.
    return false;
}

void BattleContext::init(Encounter enc, std::uint32_t seed, const Card *deck, int deckCount,
                         int ascensionLevel, int playerHp, int playerMaxHp,
                         const int *relicIds, int relicN,
                         const int *potionIds, int potionN,
                         int slotCount, int turn1Energy, int energyPerTurn, int runGold,
                         std::uint32_t potionSeed, const int *relicAuxIn,
                         const Rng *runRngs) {
    *this = BattleContext();
    ascension = ascensionLevel;
    rng = Rng(seed);
    shuffleRng = Rng(seed ^ 0x243F6A88u);
    cardGenerationRng = Rng(seed ^ 0x85A308D3u);
    potionRng = Rng(potionSeed != 0 ? potionSeed : seed ^ 0x5F3759DFu);
    cardSelectionRng = Rng(seed ^ 0x13198A2Eu);
    energyCostRng = Rng(seed ^ 0x03707344u);
    targetRng = Rng(seed ^ 0xA4093822u);
    monsterAiRng = Rng(seed ^ 0x299F31D0u);
    nicheRng = Rng(seed ^ 0x082EFA98u);
    if (runRngs != nullptr) {
        // RunRngType order: shuffle=1, card generation=3, potion generation=4,
        // card selection=5, energy costs=6, targets=7, monster AI=8.
        shuffleRng = runRngs[1];
        cardGenerationRng = runRngs[3];
        potionRng = runRngs[4];
        cardSelectionRng = runRngs[5];
        energyCostRng = runRngs[6];
        targetRng = runRngs[7];
        monsterAiRng = runRngs[8];
        nicheRng = runRngs[9];
        rng = monsterAiRng;
    }
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
    for (int i = 0; i < relicCount; ++i) {
        relics[i] = relicIds[i];
        if (relicAuxIn && relic_aux_persistent(static_cast<RelicId>(relics[i]))) {
            relicAux[i] = relicAuxIn[i];
        }
    }
    for (int i = 0; i < deckCount && i < MAX_PILE; ++i) {
        originalDeckUids[originalDeckCount++] = deck[i].uid;
        draw[drawCount] = deck[i];
        draw[drawCount++].enchantmentDisabled = false;
    }
    shuffleRng.shuffle(draw, drawCount);
    setup_encounter(*this, enc);
    nextUid = 1000;
    // GalvanicPower.BeforeCombatStart afflicts every Power card already in the
    // player's combat piles.
    for (int i = 0; i < drawCount; ++i) {
        if (!card_is_power(draw[i])) continue;
        for (int j = 0; j < monsterCount; ++j) {
            const int amount =
                monsters[j].power[static_cast<int>(PowerId::GALVANIC)];
            if (monsters[j].alive && amount > 0) {
                draw[i].galvanized = static_cast<std::int16_t>(amount);
                break;
            }
        }
    }
    relics_combat_start(*this);
    start_player_turn();
    clear_card_uid_reservations();
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
    return alive[targetRng.next_int(0, n - 1)];
}

void BattleContext::check_outcome() {
    if (outcome != Outcome::UNDECIDED) return;
    if (player.hp <= 0) outcome = Outcome::PLAYER_LOSS;
    else {
        bool can_end = true;
        for (int i = 0; i < monsterCount; ++i) {
            if ((monsters[i].alive && !monsters[i].reviving &&
                 monsters[i].power[static_cast<int>(PowerId::MINION)] <= 0) ||
                monsters[i].combatEndBlocker) {
                can_end = false;
                break;
            }
        }
        if (can_end) outcome = Outcome::PLAYER_VICTORY;
    }
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
    // Preserve the exact order of cards the player already knows are on top
    // (Headbutt, Nostalgia, known status placements); only shuffle the unknown
    // remainder of the draw pile.
    const int hidden = std::max(0, drawCount - knownTopCount);
    // Normalize using only the public pile-view fields before randomizing.
    // Otherwise a fixed search seed would map different original hidden
    // permutations to different samples. Do not use internal card UIDs here.
    const auto publicPileKey = [](const Card &c) {
        return std::make_tuple(static_cast<int>(c.id), c.upgraded,
                               static_cast<int>(c.enchantment), c.enchantmentAmount,
                               c.enchantmentDisabled);
    };
    const auto publicPileLess = [&](const Card &a, const Card &b) {
        return publicPileKey(a) < publicPileKey(b);
    };
    std::sort(draw, draw + hidden, publicPileLess);
    for (int i = hidden - 1; i > 0; --i) {
        const int j = shuffle.next_int(0, i);
        Card t = draw[i];
        draw[i] = draw[j];
        draw[j] = t;
    }
    std::sort(discard, discard + discardCount, publicPileLess);
    for (int i = discardCount - 1; i > 0; --i) {
        const int j = shuffle.next_int(0, i);
        Card t = discard[i];
        discard[i] = discard[j];
        discard[j] = t;
    }
    // Every hidden future stream is replaced together.
    rng = Rng(seed ^ 0x9E3779B9u);
    shuffleRng = Rng(seed ^ 0x243F6A88u);
    cardGenerationRng = Rng(seed ^ 0x85A308D3u);
    potionRng = Rng(seed ^ 0x5F3759DFu);
    cardSelectionRng = Rng(seed ^ 0x13198A2Eu);
    energyCostRng = Rng(seed ^ 0x03707344u);
    targetRng = Rng(seed ^ 0xA4093822u);
    monsterAiRng = Rng(seed ^ 0x299F31D0u);
    nicheRng = Rng(seed ^ 0x082EFA98u);
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
    // RampartPower.AfterSideTurnStart(Player): every Rampart owner supplies
    // its Amount to all TurretOperator allies.
    for (int i = 0; i < monsterCount; ++i) {
        if (!monsters[i].alive ||
            monsters[i].power[static_cast<int>(PowerId::RAMPART)] <= 0) {
            continue;
        }
        const int amount = monsters[i].power[static_cast<int>(PowerId::RAMPART)];
        for (int j = 0; j < monsterCount; ++j) {
            if (monsters[j].alive && monsters[j].id == MonsterId::TURRET_OPERATOR) {
                monsters[j].block += amount;
            }
        }
    }
    player.tookUnblockedDamageThisTurn = false;
    if (player_power(PowerId::BARRICADE) <= 0) {
        const int keep = relics_block_retain(*this);
        player.block = keep > 0 ? std::min(player.block, keep) : 0;
    }
    // AfterBlockCleared runs at the start of the owner's turn, including
    // turns where no block was present or Barricade retained it.
    for (int i = 0; i < toricCount;) {
        gain_block(toricBlock[i], false, false);
        --toricTurns[i];
        add_player_power(PowerId::TORIC_TOUGHNESS, -1);
        if (toricTurns[i] <= 0) {
            player.toricToughnessBlock -= toricBlock[i];
            for (int j = i; j + 1 < toricCount; ++j) {
                toricBlock[j] = toricBlock[j + 1];
                toricTurns[j] = toricTurns[j + 1];
            }
            --toricCount;
        } else {
            ++i;
        }
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::BLOCK_NEXT_TURN) > 0) {
        const int b = player_power(PowerId::BLOCK_NEXT_TURN);
        add_player_power(PowerId::BLOCK_NEXT_TURN, -b);
        gain_block(b, false, false);
    }
    int baseEnergy = player.energyPerTurn;
    if (player_power(PowerId::PYRE) > 0) baseEnergy += player_power(PowerId::PYRE);
    player.energy = relics_energy_for_turn(*this, baseEnergy) + nextTurnEnergy;
    nextTurnEnergy = 0;
    // RadiancePower.AfterEnergyReset: +1 energy, then one stack expires.
    if (player_power(PowerId::RADIANCE) > 0) {
        player.energy += 1;
        add_player_power(PowerId::RADIANCE, -1);
    }

    cardsPlayedThisTurn = 0;
    attacksPlayedThisTurn = 0;
    skillsPlayedThisTurn = 0;
    hpLostThisTurn = 0;
    exhaustedThisTurn = 0;
    cardsDrawnThisTurn = 0;
    gainedBlockFromCardThisTurn = false;
    blockCardPlaysThisTurn = 0;
    blockPlayIndex = -1;
    playedAttackOrSkillThisTurn = false;
    attackSkillPlaysThisTurn = 0;
    // HardenedShellPower.BeforeSideTurnStart(side Player): the per-turn HP-loss
    // allowance is restored at the start of every player turn.
    for (int i = 0; i < monsterCount; ++i) monsters[i].shellHpLostThisTurn = 0;
    jugglingTriggeredThisTurn = false;
    reboundPending = false;
    skillsLocked = false;
    relics_turn_start(*this);
    if (outcome != Outcome::UNDECIDED) return;

    if (player_power(PowerId::DEMON_FORM) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::DEMON_FORM));
    if (player_power(PowerId::CRIMSON_MANTLE) > 0) {
        damage_player(1, true);
        if (outcome == Outcome::UNDECIDED)
            gain_block(player_power(PowerId::CRIMSON_MANTLE), false, false);
    }
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::INFERNO) > 0) damage_player(1, true);
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < rollingCount && outcome == Outcome::UNDECIDED; ++i) {
        attack_all(rollingDamage[i], 1, false);
        rollingDamage[i] += 5;
        power_ref(player, PowerId::ROLLING_BOULDER) += 5;
    }
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::PREP_TIME) > 0) add_player_power(PowerId::VIGOR, player_power(PowerId::PREP_TIME));

    // Cards whose cost was changed "this turn" expire now, wherever they are;
    // free-until-played costs persist until that copy is played.  Hidden Gem's
    // replay is BaseReplayCount (permanent for the combat), not a turn effect.
    for (int i = 0; i < handCount; ++i) card_restore_cost(hand[i]);
    for (int i = 0; i < drawCount; ++i) card_restore_cost(draw[i]);
    for (int i = 0; i < discardCount; ++i) card_restore_cost(discard[i]);

    for (int i = 0; i < returnNextTurnCount; ++i) add_card_to_hand(returnNextTurn[i]);
    returnNextTurnCount = 0;

    // ---- BeforeHandDraw hooks (all run before the hand is drawn) ----------
    // ThrummingHatchet.BeforeHandDraw: the exact instance played last round
    // returns from whichever pile holds it (normally the discard pile).
    recall_played_last_turn(CardId::THRUMMING_HATCHET);
    // HowlFromBeyond.BeforeHandDraw: every exhausted copy auto-plays.
    if (exhaustCount > 0) {
        std::uint16_t howls[MAX_PILE];
        int howlN = 0;
        for (int i = 0; i < exhaustCount; ++i) {
            if (exhaust[i].id == CardId::HOWL_FROM_BEYOND) howls[howlN++] = exhaust[i].uid;
        }
        for (int i = 0; i < howlN && outcome == Outcome::UNDECIDED; ++i) {
            for (int j = 0; j < exhaustCount; ++j) {
                if (exhaust[j].uid != howls[i]) continue;
                Card c = exhaust[j];
                for (int k = j; k + 1 < exhaustCount; ++k) exhaust[k] = exhaust[k + 1];
                --exhaustCount;
                auto_play_random(c, false);
                break;
            }
        }
    }
    // AggressionPower.BeforeSideTurnStart: move Amount random attacks from the
    // discard pile to hand and upgrade them, before the draw/shuffle.
    if (player_power(PowerId::AGGRESSION) > 0 && discardCount > 0) {
        int idxs[MAX_PILE];
        int n = 0;
        for (int i = 0; i < discardCount; ++i) {
            if (card_is_attack(discard[i])) idxs[n++] = i;
        }
        for (int i = n - 1; i > 0; --i) {
            const int j = cardSelectionRng.next_int(0, i);
            std::swap(idxs[i], idxs[j]);
        }
        const int take = std::min(n, player_power(PowerId::AGGRESSION));
        int chosen[MAX_PILE];
        for (int k = 0; k < take; ++k) chosen[k] = idxs[k];
        // Sort the chosen indices descending so removals do not shift the rest.
        for (int a = 1; a < take; ++a) {
            const int v = chosen[a];
            int b = a - 1;
            while (b >= 0 && chosen[b] < v) { chosen[b + 1] = chosen[b]; --b; }
            chosen[b + 1] = v;
        }
        for (int k = 0; k < take; ++k) {
            Card c = discard[chosen[k]];
            if (card_upgradable(c)) upgrade_card(c);
            add_card_to_hand(c);
        }
        for (int k = 0; k < take; ++k) {
            const int idx = chosen[k];
            for (int j = idx; j + 1 < discardCount; ++j) discard[j] = discard[j + 1];
            --discardCount;
        }
    }
    // DrumOfBattlePower.BeforeHandDrawLate: exhaust the top Amount cards,
    // shuffling the discard pile in as needed.
    if (player_power(PowerId::DRUM_OF_BATTLE) > 0) {
        for (int i = 0; i < player_power(PowerId::DRUM_OF_BATTLE); ++i) {
            if (drawCount == 0) shuffle_discard_into_draw();
            if (drawCount == 0) break;
            Card c = take_draw_top();
            move_to_exhaust(c);
        }
    }
    // HelloWorldPower.BeforeHandDraw: add distinct unlocked Ironclad commons
    // before the normal hand draw.
    if (player_power(PowerId::HELLO_WORLD) > 0) {
        CardId pool[static_cast<int>(CardId::COUNT)];
        int n = 0;
        for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
            const CardDef &d = CARD_DEFS[i];
            if (d.pool == CardPool::IRONCLAD && d.rarity == Rarity::COMMON &&
                !(d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                             CF_CANNOT_GENERATE_IN_COMBAT))) {
                pool[n++] = static_cast<CardId>(i);
            }
        }
        CardId picked[16];
        int pickedN = 0;
        const int wanted = std::min(player_power(PowerId::HELLO_WORLD),
                                    static_cast<int>(sizeof(picked) / sizeof(picked[0])));
        for (int guard = 0; guard < 256 && pickedN < wanted && n > 0; ++guard) {
            const int idx = cardGenerationRng.next_int(0, n - 1);
            bool duplicate = false;
            for (int j = 0; j < pickedN; ++j) duplicate |= picked[j] == pool[idx];
            if (duplicate) continue;
            picked[pickedN++] = pool[idx];
            add_card_to_hand(make_card(pool[idx], false, require_card_uid()));
        }
    }

    int drawCountThisTurn = relics_modify_draw(*this, player.drawPerTurn) + nextTurnDraw;
    nextTurnDraw = 0;
    // ClarityPower.ModifyHandDraw: one extra card for each remaining turn.
    const bool clarity = player_power(PowerId::CLARITY) > 0;
    // Innate cards go on top of the draw pile on turn 1; the opening draw is
    // max(normal draw, innate count), capped at the 10-card hand (C# CombatManager).
    if (turn == 1) {
        Card ordered[MAX_PILE];
        int n = 0;
        int innate = 0;
        for (int i = 0; i < drawCount; ++i) {
            if (!card_has(draw[i], CF_INNATE)) ordered[n++] = draw[i];
        }
        for (int i = 0; i < drawCount; ++i) {
            if (card_has(draw[i], CF_INNATE)) { ordered[n++] = draw[i]; ++innate; }
        }
        for (int i = 0; i < n; ++i) draw[i] = ordered[i];
        drawCount = n;
        knownTopCount = innate;
        drawCountThisTurn = std::min(MAX_HAND, std::max(drawCountThisTurn, innate));
    }
    if (clarity) drawCountThisTurn += 1;
    draw_cards(drawCountThisTurn);
    if (clarity) add_player_power(PowerId::CLARITY, -1);
    if (outcome != Outcome::UNDECIDED) return;
    // A Stratagem selection interrupted the draw; it resumes when resolved.
    if (pending.op != ChoiceOp::NONE) return;
    relics_hand_drawn(*this);

    // powers that act on the drawn hand
    if (player_power(PowerId::ENTROPY) > 0) {
        int n = player_power(PowerId::ENTROPY);
        while (n-- > 0 && handCount > 0) {
            const int idx = cardGenerationRng.next_int(0, handCount - 1);
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
            const int idx = attacks[cardSelectionRng.next_int(0, n - 1)];
            Card c = discard[idx];
            remove_at(discard, discardCount, idx);
            upgrade_card(c);
            add_card_to_hand(c);
        }
    }
    if (player_power(PowerId::MAYHEM) > 0) {
        auto_play_from_draw(player_power(PowerId::MAYHEM), false);
    }
}

void BattleContext::end_player_turn() {
    if (outcome != Outcome::UNDECIDED) return;
    if (turn >= 200) {  // stalemate cutoff, not a game-rule defeat
        outcome = Outcome::TRUNCATED;
        return;
    }
    // Rounds are the unit ThrummingHatchet's BeforeHandDraw looks back on.
    playedLastTurnCount = 0;
    for (int i = 0; i < playedThisTurnCount && playedLastTurnCount < MAX_PILE; ++i) {
        bool dup = false;
        for (int j = 0; j < playedLastTurnCount; ++j) {
            dup = dup || playedLastTurn[j] == playedThisTurn[i];
        }
        if (!dup) playedLastTurn[playedLastTurnCount++] = playedThisTurn[i];
    }
    playedThisTurnCount = 0;
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
            const int idx = candidates[cardSelectionRng.next_int(0, n - 1)];
            Card c = hand[idx];
            remove_at(hand, handCount, idx);
            // StampedePower -> CardCmd.AutoPlay: the whole play lifecycle
            // (counters, Rage/after-play hooks, Duplication) must run.
            auto_play_random(c, false);
        }
    }
    // Each bomb instance counts down and explodes independently; power duration
    // (Unpowered) ignores strength and vulnerable.
    for (int i = 0; i < bombCount;) {
        if (--bombTurns[i] > 0) { ++i; continue; }
        const int dmg = bombDamage[i];
        for (int j = i; j + 1 < bombCount; ++j) {
            bombTurns[j] = bombTurns[j + 1];
            bombDamage[j] = bombDamage[j + 1];
        }
        --bombCount;
        attack_all(dmg, 1, false);
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::PLATING) > 0)
        gain_block(player_power(PowerId::PLATING), false, false);
    if (player_power(PowerId::REGEN) > 0) {
        player.hp = std::min(player.maxHp, player.hp + player_power(PowerId::REGEN));
        add_player_power(PowerId::REGEN, -1);
    }
    relics_turn_end(*this);
    relics_after_turn(*this);
    if (outcome != Outcome::UNDECIDED) return;

    discard_hand();
    if (outcome != Outcome::UNDECIDED) return;
    flush_ethereal_exhaust_hooks();
    if (player.tempStrength != 0) {
        player.strength -= player.tempStrength;
        player.tempStrength = 0;
    }
    if (player.tempDexterity != 0) {
        player.dexterity -= player.tempDexterity;
        player.tempDexterity = 0;
    }
    if (player_power(PowerId::RITUAL) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RITUAL));
    if (player_power(PowerId::RAGE) > 0) add_player_power(PowerId::RAGE, -player_power(PowerId::RAGE));
    // DuplicationPower.AfterTurnEnd(owner side): copies expire at the end of
    // the turn in which they were applied.
    if (player_power(PowerId::DUPLICATION) > 0)
        add_player_power(PowerId::DUPLICATION, -player_power(PowerId::DUPLICATION));
    // One-Two Punch expires at end of turn.  FreeAttackPower has no end-of-turn
    // removal: it is consumed by the next attack that is actually played.
    if (player_power(PowerId::ONE_TWO_PUNCH) > 0) add_player_power(PowerId::ONE_TWO_PUNCH, -player_power(PowerId::ONE_TWO_PUNCH));
    if (player_power(PowerId::SETUP_STRIKE) > 0) add_player_power(PowerId::SETUP_STRIKE, -player_power(PowerId::SETUP_STRIKE));
    if (player_power(PowerId::EQUILIBRIUM) > 0) add_player_power(PowerId::EQUILIBRIUM, 0);
    if (player_power(PowerId::RETAIN_HAND) > 0) add_player_power(PowerId::RETAIN_HAND, -1);
    if (player_power(PowerId::NO_BLOCK) > 0) add_player_power(PowerId::NO_BLOCK, -1);
    if (player_power(PowerId::TENDER) > 0) {
        add_player_power(PowerId::STRENGTH, cardsPlayedThisTurn);
        player.dexterity += cardsPlayedThisTurn;
    }
    player.power[static_cast<int>(PowerId::RINGING)] = 0;
    // GrapplePower.AfterTurnEnd removes the debuff at the end of the turn
    // (TheGambit kills immediately in damage_player, never at turn end).
    for (int i = 0; i < monsterCount; ++i) {
        monsters[i].power[static_cast<int>(PowerId::GRAPPLE)] = 0;
        monsters[i].grappleCount = 0;
    }

    for (int i = 0; i < panacheCount; ++i) panacheLeft[i] = 5;
    for (int i = 0; i < monsterCount; ++i) monsters[i].skittishTriggeredThisTurn = false;
    monster_turn();
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < monsterCount; ++i) {
        if (monsters[i].tempStrengthLoss != 0) {
            monsters[i].strength += monsters[i].tempStrengthLoss;
            monsters[i].tempStrengthLoss = 0;
        }
    }
    // IntangiblePower.AfterTurnEnd: expires after the enemy turn it protected
    // against (it does not tick at the start of the next player turn).
    if (player_power(PowerId::INTANGIBLE) > 0) add_player_power(PowerId::INTANGIBLE, -1);
    if (player.vulnerable > 0 && !vulnerableSkipTick) --player.vulnerable;
    if (player.weak > 0 && !weakSkipTick) --player.weak;
    if (player.frail > 0 && !frailSkipTick) --player.frail;
    weakSkipTick = false;
    frailSkipTick = false;
    vulnerableSkipTick = false;
    // PlatingPower.AfterTurnEnd(side Enemy): the player's plating decays once
    // per enemy turn (enemy plating decays by the player count, i.e. one).
    if (player_power(PowerId::PLATING) > 0) add_player_power(PowerId::PLATING, -1);
    if (player_power(PowerId::SHRINK) > 0) add_player_power(PowerId::SHRINK, -1);
    add_player_power(PowerId::FLAME_BARRIER, 0);
    player.power[static_cast<int>(PowerId::FLAME_BARRIER)] = 0;
    // ColossusPower.AfterTurnEnd(side Enemy) ticks its duration once per enemy
    // turn; it does not disappear after a single turn.
    if (player_power(PowerId::COLOSSUS) > 0) add_player_power(PowerId::COLOSSUS, -1);
    player.power[static_cast<int>(PowerId::NO_DRAW)] = 0;
    player.power[static_cast<int>(PowerId::EQUILIBRIUM)] = 0;
    start_player_turn();
}

void BattleContext::monster_turn() {
    inMonsterTurn = true;
    vitalSparkTriggeredThisEnemyTurn = false;
    // SlowPower.AfterSideTurnStart: the card count resets when the monsters'
    // own side begins its turn.
    for (int i = 0; i < monsterCount; ++i) monsters[i].slowCardsThisTurn = 0;
    // SandpitPower.AfterSideTurnStart decrements before any enemy acts.  Its
    // removal kills the targeted player outright, bypassing death prevention.
    for (int i = 0; i < monsterCount; ++i) {
        Monster &m = monsters[i];
        int &sandpit = m.power[static_cast<int>(PowerId::SANDPIT)];
        if (!m.alive || sandpit <= 0) continue;
        if (--sandpit == 0) {
            player.hp = 0;
            check_outcome();
            inMonsterTurn = false;
            return;
        }
    }
    for (int i = 0; i < monsterCount; ++i) {
        if (!monsters[i].alive) continue;
        monster_act(*this, monsters[i]);
        check_outcome();
        if (outcome != Outcome::UNDECIDED) break;
    }
    if (outcome == Outcome::UNDECIDED) {
        // DemisePower.AfterTurnEnd(owner side): damage is Unblockable and
        // Unpowered, and the power remains for later enemy turns.
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive) continue;
            const int amount = monsters[i].power[static_cast<int>(PowerId::DEMISE)];
            if (amount <= 0) continue;
            damage_monster(i, amount, true, false, true);
            check_outcome();
            if (outcome != Outcome::UNDECIDED) break;
        }
    }
    inMonsterTurn = false;
}

// ---------------------------------------------------------------- piles

void BattleContext::shuffle_discard_into_draw() {
    if (discardCount == 0) return;
    for (int i = 0; i < discardCount; ++i) draw[i] = discard[i];
    drawCount = discardCount;
    discardCount = 0;
    shuffleRng.shuffle(draw, drawCount);
    knownTopCount = 0;
    relics_shuffled(*this);
    // StratagemPower.AfterShuffle: the player picks Amount cards from the fresh
    // draw pile (manual selection, not a random single card).
    if (player_power(PowerId::STRATAGEM) > 0 && drawCount > 0) {
        Card dummy{};
        dummy.uid = 0xFFFF;
        start_choice(ChoiceOp::DRAW_TO_HAND, ChoicePile::DRAW,
                     std::min(player_power(PowerId::STRATAGEM), drawCount), false, dummy,
                     false, 0, drawCount);
        if (pending.op != ChoiceOp::NONE) pending.hasSource = false;
    }
}

void BattleContext::draw_cards(int count) {
    if (player_power(PowerId::NO_DRAW) > 0) return;
    for (int i = 0; i < count; ++i) {
        // CardPileCmd.Draw stops when the hand is full; cards must not fall
        // through to the discard pile.
        if (handCount >= MAX_HAND) break;
        if (drawCount == 0) {
            shuffle_discard_into_draw();
            if (drawCount == 0) break;
        }
        // StratagemPower.AfterShuffle opens a selection before the draw
        // continues; resume the remaining draws once it is resolved.
        if (pending.op != ChoiceOp::NONE) {
            pendingDrawRemainder += count - i;
            break;
        }
        if (knownTopCount > 0) --knownTopCount;
        Card c = draw[--drawCount];
        ++cardsDrawnThisTurn;
        // AutomationPower.AfterCardDrawn: each instance counts down its own
        // ten cards, regardless of turn boundaries.
        for (int a = 0; a < automationCount; ++a) {
            if (--automationLeft[a] <= 0) {
                player.energy += automationAmount[a];
                automationLeft[a] = 10;
            }
        }
        if (player_power(PowerId::HELLRAISER) > 0 && card_is_strike(c)) {
            // HellraiserPower.AfterCardDrawnEarly -> CardCmd.AutoPlay.
            auto_play_random(c, false);
            continue;
        }
        // ConfusedPower.AfterCardDrawn (Snecko Eye): every drawn card with a
        // non-X canonical cost gets a random cost for the whole combat.
        if (relic_has(*this, RelicId::SNECKO_EYE) || relic_has(*this, RelicId::FAKE_SNECKO_EYE)) {
            const CardDef &d = card_def(c.id);
            const int canonical = c.upgraded ? d.costUp : d.cost;
            if (canonical >= 0) {
                c.costForTurn =
                    static_cast<std::int8_t>(energyCostRng.next_int(0, 3));
                c.costThisTurn = false;  // SetThisCombat, not SetThisTurn
                c.storedCost = c.costForTurn;
            }
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
                damage_player(card_var(c, VarId::HP_LOSS), true);
                break;
            // Curses -----------------------------------------------------
            case CardId::DECAY:  // DamageVar 2, unpowered but blockable
                damage_player(card_var(c, VarId::DAMAGE));
                break;
            case CardId::BAD_LUCK:  // 13 unblockable/unpowered
                damage_player(card_var(c, VarId::HP_LOSS), true);
                break;
            case CardId::REGRET:  // HP loss equal to cards in hand at turn end
                damage_player(handAtEnd, true);
                break;
            case CardId::DOUBT: {
                // A debuff applied to the player skips its first tick; Artifact
                // intercepts it like any other visible debuff.
                add_player_power(PowerId::WEAK, card_var(c, VarId::WEAK));
                break;
            }
            case CardId::SHAME: {
                add_player_power(PowerId::FRAIL, card_var(c, VarId::FRAIL));
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
        // Ethereal is resolved before retention (C# CombatManager end-of-turn).
        if (card_has(c, CF_ETHEREAL) || c.etherealThisCombat ||
            player_power(PowerId::HEX) > 0) {
            move_to_exhaust(c, true);
        } else if (card_has(c, CF_RETAIN) || retainAll) {
            if (keptN < MAX_HAND) kept[keptN++] = c;
        } else {
            move_to_discard(c);
        }
    }
    for (int i = keptN - 1; i >= 0; --i) hand[handCount++] = kept[i];
}

void BattleContext::move_to_discard(const Card &c) {
    if (discardCount < MAX_PILE) discard[discardCount++] = c;
}

void BattleContext::move_to_exhaust(const Card &c, bool causedByEthereal) {
    if (exhaustCount < MAX_PILE) exhaust[exhaustCount++] = c;
    ++exhaustedThisTurn;
    ++exhaustedThisCombat;
    trigger_exhaust_hooks(c, causedByEthereal);
}

void BattleContext::add_card_to_hand(const Card &c) {
    Card card = c;
    if (card_is_power(card) && card.galvanized == 0) {
        for (int i = 0; i < monsterCount; ++i) {
            const int amount =
                monsters[i].power[static_cast<int>(PowerId::GALVANIC)];
            if (monsters[i].alive && amount > 0) {
                card.galvanized = static_cast<std::int16_t>(amount);
                break;
            }
        }
    }
    if (card.id == CardId::STOMP && !card.costThisTurn && attacksPlayedThisTurn > 0) {
        card_set_turn_cost(card, std::max(0, card.costForTurn - attacksPlayedThisTurn));
    }
    if (handCount < MAX_HAND) hand[handCount++] = card;
    else move_to_discard(card);
}

void BattleContext::add_card_to_discard(const Card &c) {
    Card card = c;
    if (card_is_power(card) && card.galvanized == 0) {
        for (int i = 0; i < monsterCount; ++i) {
            const int amount =
                monsters[i].power[static_cast<int>(PowerId::GALVANIC)];
            if (monsters[i].alive && amount > 0) {
                card.galvanized = static_cast<std::int16_t>(amount);
                break;
            }
        }
    }
    move_to_discard(card);
}

void BattleContext::add_card_to_draw_top(const Card &c) {
    if (drawCount < MAX_PILE) {
        Card card = c;
        if (card_is_power(card) && card.galvanized == 0) {
            for (int i = 0; i < monsterCount; ++i) {
                const int amount =
                    monsters[i].power[static_cast<int>(PowerId::GALVANIC)];
                if (monsters[i].alive && amount > 0) {
                    card.galvanized = static_cast<std::int16_t>(amount);
                    break;
                }
            }
        }
        draw[drawCount++] = card;
        // Cards placed on top are visible to the player, so hidden-info
        // resampling must not move them.
        if (knownTopCount < drawCount) ++knownTopCount;
    } else {
        add_card_to_discard(c);
    }
}

void BattleContext::add_card_to_draw_random(const Card &c) {
    if (drawCount >= MAX_PILE) {
        add_card_to_discard(c);
        return;
    }
    add_card_to_draw_top(c);
    Card inserted = take_draw_top();
    const int pos = cardGenerationRng.next_int(0, drawCount);
    for (int i = drawCount; i > pos; --i) draw[i] = draw[i - 1];
    draw[pos] = inserted;
    ++drawCount;
    knownTopCount = 0;
}

void BattleContext::remove_draw_at(int idx) {
    if (idx < 0 || idx >= drawCount) return;
    // Known cards are the contiguous top prefix; removing one shrinks it by one.
    if (idx >= drawCount - knownTopCount && knownTopCount > 0) --knownTopCount;
    remove_at(draw, drawCount, idx);
}

Card BattleContext::take_draw_top() {
    if (drawCount == 0) return Card{};
    if (knownTopCount > 0) --knownTopCount;
    return draw[--drawCount];
}

void BattleContext::queue_return_next_turn(const Card &c) {
    for (int i = 0; i < returnNextTurnCount; ++i) {
        if (returnNextTurn[i].uid == c.uid) return;
    }
    if (returnNextTurnCount < MAX_HAND) returnNextTurn[returnNextTurnCount++] = c;
}

void BattleContext::recall_played_last_turn(CardId id) {
    for (int i = 0; i < playedLastTurnCount; ++i) {
        const std::uint16_t uid = playedLastTurn[i];
        Card found{};
        bool ok = false;
        for (int j = 0; j < handCount; ++j) {
            if (hand[j].uid == uid && hand[j].id == id) return;  // already in hand
        }
        for (int j = 0; j < discardCount && !ok; ++j) {
            if (discard[j].uid == uid && discard[j].id == id) {
                found = discard[j];
                remove_at(discard, discardCount, j);
                ok = true;
            }
        }
        for (int j = 0; j < drawCount && !ok; ++j) {
            if (draw[j].uid == uid && draw[j].id == id) {
                found = draw[j];
                remove_draw_at(j);
                ok = true;
            }
        }
        for (int j = 0; j < exhaustCount && !ok; ++j) {
            if (exhaust[j].uid == uid && exhaust[j].id == id) {
                found = exhaust[j];
                remove_at(exhaust, exhaustCount, j);
                ok = true;
            }
        }
        if (ok) add_card_to_hand(found);
    }
}

bool BattleContext::detach_card(std::uint16_t uid) {
    for (int i = 0; i < handCount; ++i) {
        if (hand[i].uid == uid) { remove_at(hand, handCount, i); return true; }
    }
    for (int i = 0; i < drawCount; ++i) {
        if (draw[i].uid == uid) { remove_draw_at(i); return true; }
    }
    for (int i = 0; i < discardCount; ++i) {
        if (discard[i].uid == uid) { remove_at(discard, discardCount, i); return true; }
    }
    for (int i = 0; i < exhaustCount; ++i) {
        if (exhaust[i].uid == uid) { remove_at(exhaust, exhaustCount, i); return true; }
    }
    return false;
}

void BattleContext::trigger_exhaust_hooks(const Card &c, bool causedByEthereal) {
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::DARK_EMBRACE) > 0) {
        if (causedByEthereal) ++darkEmbraceEthereal;
        else draw_cards(player_power(PowerId::DARK_EMBRACE));
    }
    if (player_power(PowerId::FEEL_NO_PAIN) > 0) {
        // FeelNoPainPower uses ValueProp.Unpowered: no dexterity/frail.
        gain_block(player_power(PowerId::FEEL_NO_PAIN), false, false);
    }
    if (c.id == CardId::DRUM_OF_BATTLE_CARD && card_is_power(c)) {
        player.energy += 1;
    }
    relics_exhausted(*this, c, causedByEthereal);
}

void BattleContext::flush_ethereal_exhaust_hooks() {
    if (darkEmbraceEthereal > 0) {
        const int n = player_power(PowerId::DARK_EMBRACE) * darkEmbraceEthereal;
        darkEmbraceEthereal = 0;
        if (n > 0) draw_cards(n);
    }
    relics_ethereal_turn_end(*this);
}

// ---------------------------------------------------------------- damage

int BattleContext::calc_player_damage(int base, int monsterIdx, bool powered,
                                      const Card *card) const {
    if (!powered) return base > 0 ? base : 0;
    // VigorPower applies once per AttackCommand, not per hit; callers that
    // start a command fold it into `base` (see attack_* below).
    float dmg = static_cast<float>(base + player.strength);
    // Hook.ModifyDamageAdditive runs before the multiplicative phases
    // (Strike Dummy +3 must be scaled by Weak, not added after it).
    if (card != nullptr) {
        dmg += relics_damage_additive(*this, *card);
        if (card->enchantment == EnchantmentId::VIGOROUS && !card->enchantmentDisabled)
            dmg += card->enchantmentAmount;
    }
    if (player_power(PowerId::GIGANTIFICATION) > 0) dmg *= 3.0f;
    if (player.weak > 0) dmg *= 0.75f;
    if (player_power(PowerId::SHRINK) > 0) dmg *= 0.7f;
    if (monsterIdx >= 0 && monsterIdx < monsterCount) {
        const Monster &m = monsters[monsterIdx];
        if (m.power[static_cast<int>(PowerId::COVERED)] > 0) return 0;
        if (m.power[static_cast<int>(PowerId::SOAR)] > 0) dmg *= 0.5f;
        if (m.power[static_cast<int>(PowerId::FLUTTER)] > 0) dmg *= 0.5f;
        if (m.vulnerable > 0) {
            // CrueltyPower.ModifyVulnerableMultiplier adds to the multiplier.
            float vuln = relic_has(*this, RelicId::PAPER_PHROG) ? 1.75f : 1.5f;
            vuln += player_power(PowerId::CRUELTY) / 100.0f;
            dmg *= vuln;
        }
        // SlowPower.ModifyDamageMultiplicative: +10% per card played this turn.
        if (m.power[static_cast<int>(PowerId::SLOW)] > 0 && m.slowCardsThisTurn > 0) {
            dmg *= 1.0f + 0.1f * m.slowCardsThisTurn;
        }
    }
    if (card != nullptr) dmg *= static_cast<float>(relics_damage_multiplier(*this, *card));
    const int result = static_cast<int>(std::floor(dmg));
    return result > 0 ? result : 0;
}

int BattleContext::calc_monster_damage(const Monster &m, int base) const {
    float dmg = static_cast<float>(base + m.strength + m.power[static_cast<int>(PowerId::VIGOR)]);
    if (m.power[static_cast<int>(PowerId::SHRINK)] > 0) dmg *= 0.7f;
    if (m.weak > 0) dmg *= 0.75f;
    if (player.vulnerable > 0) dmg *= 1.5f;
    if (player_power(PowerId::SURROUNDED) > 0 &&
        ((player.surroundedFacingRight && m.power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] > 0) ||
         (!player.surroundedFacingRight && m.power[static_cast<int>(PowerId::BACK_ATTACK_RIGHT)] > 0))) {
        dmg *= 1.5f;
    }
    // ColossusPower checks the *dealer's* Vulnerable, not the player's.
    if (player_power(PowerId::COLOSSUS) > 0 && m.vulnerable > 0) dmg *= 0.5f;
    const int result = static_cast<int>(std::floor(dmg));
    return result > 0 ? result : 0;
}

DamageDealt BattleContext::damage_monster(int idx, int amount, bool fromPlayer,
                                          bool poweredAttack, bool unblockable) {
    DamageDealt res;
    int surpriseGold = -1;
    bool diedThisHit = false;
    if (idx < 0 || idx >= monsterCount) return res;
    Monster &m = monsters[idx];
    const MonsterDef &def = monster_def(m.id);
    const int stolenStrength = m.power[static_cast<int>(PowerId::POSSESS_STRENGTH)] > 0 ? m.aux[0] : 0;
    const int stolenSpeed = m.power[static_cast<int>(PowerId::POSSESS_SPEED)] > 0 ? m.aux[0] : 0;
    if (!m.alive || m.reviving) return res;
    if (amount <= 0) return res;
    if (poweredAttack && m.power[static_cast<int>(PowerId::COVERED)] > 0) return res;
    // ThornsPower.BeforeDamageReceived: a powered attack from the player
    // triggers thorns before the hit resolves, even if the hit is fully
    // blocked.  The reflect is Unpowered: blockable, no strength/vulnerable.
    if (fromPlayer && poweredAttack && m.power[static_cast<int>(PowerId::THORNS)] > 0 &&
        outcome == Outcome::UNDECIDED) {
        damage_player(m.power[static_cast<int>(PowerId::THORNS)]);
        if (outcome != Outcome::UNDECIDED) return res;
    }
    int remaining = amount;
    // ModifyDamageCap is applied by the hook chain before block. Intangible,
    // HardToKill and Slippery therefore combine by taking the smallest cap.
    int damageCap = remaining;
    if (m.power[static_cast<int>(PowerId::INTANGIBLE)] > 0) damageCap = std::min(damageCap, 1);
    if (m.power[static_cast<int>(PowerId::HARD_TO_KILL)] > 0) {
        damageCap = std::min(damageCap,
                             m.power[static_cast<int>(PowerId::HARD_TO_KILL)]);
    }
    if (m.power[static_cast<int>(PowerId::SLIPPERY)] > 0) damageCap = std::min(damageCap, 1);
    remaining = std::min(remaining, damageCap);
    const bool hadBlock = m.block > 0;
    int blockedDamage = 0;
    if (m.block > 0 && !unblockable) {
        blockedDamage = remaining < m.block ? remaining : m.block;
        m.block -= blockedDamage;
        remaining -= blockedDamage;
    }
    res.blockBroken = !unblockable && hadBlock && m.block == 0;
    if (res.blockBroken && relic_has(*this, RelicId::HAND_DRILL)) {
        // HandDrill.AfterDamageGiven only requires DamageResult.WasBlockBroken,
        // including the exact hit that breaks the last point of block.
        apply_vulnerable(idx, 2);
    }
    // TheBoot.ModifyHpLostBeforeOsty: a powered attack that would cost the
    // enemy 1..4 HP instead costs 5, applied after block.
    if (poweredAttack && remaining > 0 && remaining < 5 && relic_has(*this, RelicId::THE_BOOT)) {
        remaining = 5;
    }
    // HardenedShellPower.ModifyHpLostBeforeOstyLate: HP loss is capped by the
    // power amount minus what this monster already lost this player turn.
    if (remaining > 0 && m.power[static_cast<int>(PowerId::HARDENED_SHELL)] > 0) {
        const int cap = m.power[static_cast<int>(PowerId::HARDENED_SHELL)];
        const int left = std::max(0, cap - m.shellHpLostThisTurn);
        if (remaining > left) remaining = left;
    }
    if (remaining > 0) {
        const bool hadAsleep = m.power[static_cast<int>(PowerId::ASLEEP)] > 0;
        const int hpBefore = m.hp;
        m.hp -= remaining;
        res.unblocked = std::min(remaining, std::max(0, hpBefore));
        res.overkill = std::max(0, remaining - hpBefore);
        res.total = blockedDamage + res.unblocked;
        res.fullyBlocked = blockedDamage > 0 && res.unblocked == 0;
        if (m.power[static_cast<int>(PowerId::HARDENED_SHELL)] > 0) {
            m.shellHpLostThisTurn += res.unblocked;
        }
        // Lagavulin: any unblocked damage wakes it, strips Plating and stuns it.
        if (hadAsleep) {
            m.power[static_cast<int>(PowerId::ASLEEP)] = 0;
            m.power[static_cast<int>(PowerId::PLATING)] = 0;
        }
        if (m.power[static_cast<int>(PowerId::CURL_UP)] > 0) {
            m.block += m.power[static_cast<int>(PowerId::CURL_UP)];
            m.power[static_cast<int>(PowerId::CURL_UP)] = 0;
        }
        if (m.hp <= 0) {
            m.hp = 0;
            diedThisHit = true;
            res.wasKilled = true;
            // Each SwipePower creates its own skippable special-card reward
            // in BeforeDeath. The run layer resolves the original deck card.
            for (int i = 0; i < theftCount; ++i) {
                if (theftOwners[i] == idx && !theftReturned[i]) theftReturned[i] = true;
            }
            if (m.power[static_cast<int>(PowerId::STEAM_ERUPTION)] > 0 &&
                m.id == MonsterId::WATERFALL_GIANT) {
                // TriggerAboutToBlowState keeps the giant in the encounter
                // through its windup and explosion.
                m.alive = true;
                m.reviving = false;
                m.stunned = false;
                m.hp = m.maxHp = 999999999;
                m.block = 0;
                m.move = 6;  // ABOUT_TO_BLOW -> EXPLODE
                relics_monster_died(*this);
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::ILLUSION)] > 0) {
                // Illusions remain in combat after death and revive on their
                // next turn, but are secondary enemies and do not delay victory.
                m.reviving = true;
                m.alive = true;
                m.stunned = false;
                m.combatEndBlocker = false;
                m.block = 0;
                m.weak = m.vulnerable = 0;
                m.power[static_cast<int>(PowerId::GRAPPLE)] = 0;
                m.grappleCount = 0;
                m.power[static_cast<int>(PowerId::MINION)] = 1;
                relics_monster_died(*this);
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::ADAPTABLE)] > 0 &&
                def.reviveState != 255 && m.aux[0] < 2) {
                // Test Subject: knocked out, revives on its next turn.
                m.reviving = true;
                m.combatEndBlocker = true;
                m.move = def.reviveState;
                m.block = 0;
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::STOCK)] > 0) {
                const int stock = m.power[static_cast<int>(PowerId::STOCK)];
                const MonsterId id = m.id;
                const int slot = idx;
                m.alive = false;
                relics_monster_died(*this);
                spawn_monster(*this, id, slot);
                monsters[slot].power[static_cast<int>(PowerId::STOCK)] = stock - 1;
                monsters[slot].move = 0;  // Axebot stock respawns in BOOT_UP.
                roll_intent(*this, monsters[slot]);
            } else if (m.power[static_cast<int>(PowerId::INFESTED)] > 0) {
                const int infested = m.power[static_cast<int>(PowerId::INFESTED)];
                const int deadSlot = idx;
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
                int nextSlot = deadSlot;
                for (int i = 0; i < infested && i < MAX_MONSTERS; ++i) {
                    if (i > 0) {
                        if (monsterCount < MAX_MONSTERS) {
                            nextSlot = monsterCount;
                        } else {
                            nextSlot = -1;
                            for (int s = 0; s < monsterCount; ++s) {
                                if (!monsters[s].alive && !monsters[s].reviving) {
                                    nextSlot = s;
                                    break;
                                }
                            }
                            if (nextSlot < 0) break;
                        }
                    }
                    spawn_monster(*this, MonsterId::WRIGGLER, nextSlot);
                    monsters[nextSlot].stunned = true;
                    monsterCount = std::max(monsterCount, nextSlot + 1);
                }
            } else if (m.power[static_cast<int>(PowerId::REATTACH)] > 0) {
                bool siblingAlive = false;
                for (int i = 0; i < monsterCount; ++i) {
                    if (i != idx && monsters[i].id == MonsterId::DECIMILLIPEDE_SEGMENT &&
                        monsters[i].alive && !monsters[i].reviving && monsters[i].hp > 0) {
                        siblingAlive = true;
                        break;
                    }
                }
                if (siblingAlive) {
                    m.reviving = true;
                    m.alive = true;  // non-interactable, but still gets a reattach turn
                    m.block = 0;
                    m.move = 3;  // DEAD_MOVE; follow-up is REATTACH_MOVE (4)
                    roll_intent(*this, m);
                } else {
                    for (int i = 0; i < monsterCount; ++i) {
                        if (monsters[i].id == MonsterId::DECIMILLIPEDE_SEGMENT &&
                            monsters[i].reviving) {
                            monsters[i].reviving = false;
                            monsters[i].alive = false;
                        }
                    }
                    m.reviving = false;
                    m.alive = false;
                    relics_monster_died(*this);
                }
            } else if (m.power[static_cast<int>(PowerId::DOOR_REVIVAL)] > 0) {
                m.reviving = true;
                m.alive = true;
                m.block = 0;
                m.move = 3;  // Door DEAD_MOVE
                roll_intent(*this, m);
                int slot = -1;
                for (int i = 0; i < monsterCount; ++i) {
                    if (monsters[i].id == MonsterId::DOORMAKER &&
                        !monsters[i].alive && monsters[i].hp > 0) {
                        slot = i;
                        break;
                    }
                }
                if (slot >= 0) {
                    // Door owns the same Doormaker creature across phases.
                    monsters[slot].alive = true;
                    roll_intent(*this, monsters[slot]);
                } else {
                    slot = monsterCount < MAX_MONSTERS ? monsterCount : -1;
                    if (slot < 0) {
                        for (int i = 0; i < monsterCount; ++i) {
                            if (i != idx && !monsters[i].alive && !monsters[i].reviving) {
                                slot = i;
                                break;
                            }
                        }
                    }
                    if (slot >= 0) {
                        spawn_monster(*this, MonsterId::DOORMAKER, slot);
                        monsterCount = std::max(monsterCount, slot + 1);
                    }
                }
            } else if (m.power[static_cast<int>(PowerId::SURPRISE)] > 0) {
                surpriseGold = m.stolenGold;
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
            } else {
                if (m.id == MonsterId::FAT_GREMLIN && m.stolenGold > 0) {
                    recoveredStolenGold += m.stolenGold;
                    m.stolenGold = 0;
                }
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
            }
        }
    } else {
        res.total = blockedDamage;
        res.fullyBlocked = blockedDamage > 0;
    }

    // AfterDamageReceived/AfterDamageGiven hooks run for non-lethal hits.
    if (m.alive && m.hp > 0) {
        if (res.blockBroken && m.power[static_cast<int>(PowerId::BURROWED)] > 0) {
            m.power[static_cast<int>(PowerId::BURROWED)] = 0;
            m.block = 0;
            m.stunned = true;
            if (m.id == MonsterId::TUNNELER) m.move = 3;  // DIZZY -> BITE
            roll_intent(*this, m);
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::SHRIEK)] > 0 &&
            m.hp <= m.power[static_cast<int>(PowerId::SHRIEK)]) {
            m.power[static_cast<int>(PowerId::SHRIEK)] = 0;
            m.stunned = true;
            if (m.id == MonsterId::TERROR_EEL) m.move = 2;  // STUN -> TERROR
            roll_intent(*this, m);
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::PLOW)] > 0 &&
            m.hp <= m.power[static_cast<int>(PowerId::PLOW)]) {
            m.power[static_cast<int>(PowerId::PLOW)] = 0;
            m.strength = 0;
            m.stunned = true;
            if (m.id == MonsterId::CEREMONIAL_BEAST) m.move = 2;  // STUN -> BEAST_CRY
            roll_intent(*this, m);
        }
        if (poweredAttack && res.unblocked > 0 &&
            m.power[static_cast<int>(PowerId::FLUTTER)] > 0 &&
            --m.power[static_cast<int>(PowerId::FLUTTER)] == 0) {
            m.stunned = true;
            roll_intent(*this, m);
        }
        if (m.power[static_cast<int>(PowerId::SLIPPERY)] > 0 && res.total != 0) {
            --m.power[static_cast<int>(PowerId::SLIPPERY)];
        }
        if (poweredAttack && m.power[static_cast<int>(PowerId::PERSONAL_HIVE)] > 0) {
            const int count = m.power[static_cast<int>(PowerId::PERSONAL_HIVE)];
            for (int i = 0; i < count; ++i) {
                add_card_to_draw_random(make_card(CardId::DAZED, false, require_card_uid()));
            }
        }
        if (poweredAttack && res.unblocked > 0 &&
            m.power[static_cast<int>(PowerId::VITAL_SPARK)] > 0 &&
            !vitalSparkTriggeredThisEnemyTurn) {
            vitalSparkTriggeredThisEnemyTurn = true;
            player.energy += m.power[static_cast<int>(PowerId::VITAL_SPARK)];
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::SLUMBER)] > 0) {
            --m.power[static_cast<int>(PowerId::SLUMBER)];
            if (m.power[static_cast<int>(PowerId::SLUMBER)] <= 0) {
                m.power[static_cast<int>(PowerId::PLATING)] = 0;
                m.stunned = true;
                m.move = 2;  // SlumberingBeetle ROLL_OUT_MOVE
                roll_intent(*this, m);
            }
        }
    }

    // CrabRagePower.AfterDeath: any ally death enrages surviving crab members.
    if (diedThisHit) {
        if (player_power(PowerId::SURROUNDED) > 0) {
            int first = -1;
            bool allLeft = true;
            bool allRight = true;
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive || monsters[i].reviving) continue;
                if (first < 0) first = i;
                allLeft &= monsters[i].power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] > 0;
                allRight &= monsters[i].power[static_cast<int>(PowerId::BACK_ATTACK_RIGHT)] > 0;
            }
            if (first >= 0 && (allLeft || allRight)) face_surrounded_target(first);
        }
        for (int i = 0; i < monsterCount; ++i) {
            Monster &ally = monsters[i];
            if (i != idx && ally.alive && !ally.reviving &&
                ally.power[static_cast<int>(PowerId::RAVENOUS)] > 0) {
                ally.strength += ally.power[static_cast<int>(PowerId::RAVENOUS)];
                ally.stunned = true;
                roll_intent(*this, ally);
            }
            if (i != idx && ally.alive && ally.power[static_cast<int>(PowerId::CRAB_RAGE)] > 0) {
                ally.strength += 5;
                ally.block += 99;
                ally.power[static_cast<int>(PowerId::CRAB_RAGE)] = 0;
            }
        }
        // Possess powers return exactly the amount stolen by this owner.
        if (stolenStrength != 0) add_player_power(PowerId::STRENGTH, stolenStrength);
        if (stolenSpeed != 0) add_player_power(PowerId::DEXTERITY, stolenSpeed);
    }
    if (surpriseGold >= 0) {
        spawn_monster(*this, MonsterId::SNEAKY_GREMLIN);
        int fatSlot = -1;
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive && !monsters[i].reviving) { fatSlot = i; break; }
        }
        if (fatSlot < 0 && monsterCount < MAX_MONSTERS) fatSlot = monsterCount++;
        if (fatSlot >= 0) {
            spawn_monster(*this, MonsterId::FAT_GREMLIN, fatSlot);
            monsters[fatSlot].stolenGold = surpriseGold;
        }
    }
    check_outcome();
    return res;
}

// VigorPower.BeforeAttack: fold the whole stack into one AttackCommand and
// consume it when that command ends.
static int take_vigor(BattleContext &bc, int base, bool powered) {
    if (powered && bc.player_power(PowerId::VIGOR) > 0) {
        const int v = bc.player_power(PowerId::VIGOR);
        bc.add_player_power(PowerId::VIGOR, -v);
        return base + v;
    }
    return base;
}

void BattleContext::trigger_skittish(int target, bool unblocked) {
    if (target < 0 || target >= monsterCount) return;
    Monster &m = monsters[target];
    const int amount = m.power[static_cast<int>(PowerId::SKITTISH)];
    if (unblocked && m.alive && !m.reviving && m.hp > 0 &&
        !m.skittishTriggeredThisTurn && amount > 0) {
        m.skittishTriggeredThisTurn = true;
        m.block += amount;
    }
}

void BattleContext::attack_monster(int target, int base, int hits, bool powered) {
    base = take_vigor(*this, base, powered);
    for (int i = 0; i < hits; ++i) {
        if (outcome != Outcome::UNDECIDED) return;
        if (target < 0 || target >= monsterCount || !monsters[target].alive) return;
        damage_monster(target, calc_player_damage(base, target, powered), true, powered);
    }
}

void BattleContext::attack_random_monster(int base, int hits, bool powered) {
    base = take_vigor(*this, base, powered);
    for (int i = 0; i < hits; ++i) {
        if (outcome != Outcome::UNDECIDED) return;
        const int idx = random_alive_monster();
        if (idx < 0) return;
        damage_monster(idx, calc_player_damage(base, idx, powered), true, powered);
    }
}

void BattleContext::attack_all(int base, int hits, bool powered) {
    base = take_vigor(*this, base, powered);
    for (int h = 0; h < hits; ++h) {
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive || outcome != Outcome::UNDECIDED) continue;
            damage_monster(i, calc_player_damage(base, i, powered), true, powered);
        }
    }
}

void BattleContext::attack_all_from_card(Card &card, int base, int hits) {
    bool unblocked[MAX_MONSTERS]{};
    int b = base;
    if (player_power(PowerId::VIGOR) > 0) {
        b += player_power(PowerId::VIGOR);
        add_player_power(PowerId::VIGOR, -player_power(PowerId::VIGOR));
    }
    for (int h = 0; h < hits; ++h) {
        if (outcome != Outcome::UNDECIDED) return;
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive) continue;
            const DamageDealt result = damage_monster(i, calc_player_damage(b, i, true, &card), true, true);
            unblocked[i] |= result.unblocked > 0;
        }
    }
    for (int i = 0; i < monsterCount; ++i) trigger_skittish(i, unblocked[i]);
}

bool BattleContext::attack_from_card(Card &card, int target, int base, int hits, bool all) {
    bool unblocked[MAX_MONSTERS]{};
    bool killed = false;
    int b = base;
    if (player_power(PowerId::VIGOR) > 0) {
        b += player_power(PowerId::VIGOR);
        add_player_power(PowerId::VIGOR, -player_power(PowerId::VIGOR));
    }
    for (int h = 0; h < hits; ++h) {
        if (outcome != Outcome::UNDECIDED) return killed;
        if (all) {
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive || outcome != Outcome::UNDECIDED) continue;
                const DamageDealt result = damage_monster(i, calc_player_damage(b, i, true, &card), true, true);
                unblocked[i] |= result.unblocked > 0;
                killed |= result.wasKilled;
            }
        } else {
            if (target < 0 || target >= monsterCount || !monsters[target].alive) return killed;
            const DamageDealt result = damage_monster(target, calc_player_damage(b, target, true, &card), true, true);
            unblocked[target] |= result.unblocked > 0;
            killed |= result.wasKilled;
        }
    }
    for (int i = 0; i < monsterCount; ++i) trigger_skittish(i, unblocked[i]);
    return killed;
}

int BattleContext::gain_block_raw(int amount, bool powered) {
    (void) powered;
    int result = amount < 0 ? 0 : amount;
    player.block += result;
    return result;
}

void BattleContext::gain_block(int amount, bool fromCard, bool powered) {
    if (amount <= 0) return;
    if (fromCard && player_power(PowerId::NO_BLOCK) > 0) return;
    // Hook.ModifyBlockAdditive (Dexterity) runs before the multiplicative
    // modifiers (Vambrace, UnmovablePower, Frail).
    float value = static_cast<float>(amount);
    if (powered) value += player.dexterity;
    int additive = static_cast<int>(value);
    if (powered) additive = relics_modify_block_gain(*this, additive, fromCard);
    value = static_cast<float>(additive);
    if (fromCard && player_power(PowerId::UNMOVABLE) > 0) {
        if (blockPlayIndex < 0) blockPlayIndex = blockCardPlaysThisTurn++;
        if (blockPlayIndex < player_power(PowerId::UNMOVABLE)) value *= 2.0f;
    }
    if (powered && player.frail > 0) value *= 0.75f;
    const int before = player.block;
    gain_block_raw(static_cast<int>(std::floor(value)), false);
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
    // GrapplePower.AfterBlockGained: the applier gaining block deals the
    // Grapple amount to its owner as Unpowered damage.
    if (amount > 0 && outcome == Outcome::UNDECIDED) {
        for (int i = 0; i < monsterCount; ++i) {
            const int grapple = monsters[i].power[static_cast<int>(PowerId::GRAPPLE)];
            if (monsters[i].alive && grapple > 0) {
                const int count = monsters[i].grappleCount;
                if (count == 0) {
                    damage_monster(i, grapple, true, false);
                } else {
                    for (int j = 0; j < count && monsters[i].alive &&
                                    outcome == Outcome::UNDECIDED; ++j) {
                        damage_monster(i, monsters[i].grappleAmounts[j], true, false);
                    }
                }
                if (outcome != Outcome::UNDECIDED) break;
            }
        }
    }
}

int BattleContext::damage_player(int amount, bool unblockable, bool poweredAttack) {
    if (amount <= 0 || outcome != Outcome::UNDECIDED) return 0;
    if (poweredAttack && player_power(PowerId::COVERED) > 0) return 0;
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
        if (!unblockable && relic_has(*this, RelicId::LAVA_LAMP)) {
            lavaLampTookQualifyingDamage = true;
        }
        ++unblockedHitsThisCombat;
        player.tookUnblockedDamageThisTurn = true;
        if (poweredAttack) player.tookUnblockedAttackDamageThisCombat = true;
        // TheGambitPower.AfterDamageReceived: only powered, unblocked attack
        // damage kills, and the kill is immediate (PowerCmd.Remove + Kill).
        if (poweredAttack && player_power(PowerId::THE_GAMBIT) > 0) {
            player.power[static_cast<int>(PowerId::THE_GAMBIT)] = 0;
            player.hp = 0;
            outcome = Outcome::PLAYER_LOSS;
            return remaining;
        }
        if (player.hp <= 0) {
            player.hp = 0;
            if (try_fairy_revive()) return remaining;
            if (relics_try_revive(*this)) return remaining;
            outcome = Outcome::PLAYER_LOSS;
            return remaining;
        }
        relics_damage_received(*this, remaining);
        // RupturePower: only damage taken during the owner's side; damage from
        // the card currently resolving is applied after that card finishes.
        if (!inMonsterTurn && player_power(PowerId::RUPTURE) > 0) {
            const int gain = player_power(PowerId::RUPTURE);
            if (resolvingCard) pendingRupture += gain;
            else add_player_power(PowerId::STRENGTH, gain);
        }
        if (player_power(PowerId::INFERNO) > 0 && outcome == Outcome::UNDECIDED) {
            attack_all(player_power(PowerId::INFERNO), 1, false);
        }
    }
    return remaining;
}

void BattleContext::lose_hp(int amount, bool fromCard) {
    (void) fromCard;
    if (amount <= 0 || outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::INTANGIBLE) > 0 && amount > 1) amount = 1;
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
    // Rupture triggers on damage received, not on direct HP loss.
    if (player_power(PowerId::INFERNO) > 0) attack_all(player_power(PowerId::INFERNO), 1, false);
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
    // ThornsPower.BeforeDamageReceived fires for a powered attack even when the
    // player blocks all of it.  Both reflects are Unpowered (blockable, no
    // strength/vulnerable scaling).
    if (player_power(PowerId::THORNS) > 0) {
        damage_monster(monsterIdx, player_power(PowerId::THORNS));
        if (outcome != Outcome::UNDECIDED) return;
    }
    const int blockBefore = player.block;
    const int unblocked = damage_player(dmg, false, true);
    const bool fullyBlocked =
        (blockBefore > 0 || player.block > 0) && unblocked == 0 && dmg > 0;
    if (outcome == Outcome::UNDECIDED && fullyBlocked &&
        m.power[static_cast<int>(PowerId::IMBALANCED)] > 0) {
        if (m.id == MonsterId::BOWLBUG_ROCK) m.offBalance = true;
        else m.stunned = true;
    }
    if (outcome != Outcome::UNDECIDED) return;
    // PaperCutsPower.AfterDamageGiven: each unblocked powered hit from this
    // owner also removes Amount Max HP.
    if (unblocked > 0 && m.power[static_cast<int>(PowerId::PAPER_CUTS)] > 0) {
        const int loss = m.power[static_cast<int>(PowerId::PAPER_CUTS)];
        player.maxHp = std::max(0, player.maxHp - loss);
        if (player.hp > player.maxHp) {
            const int excess = player.hp - player.maxHp;
            player.hp = player.maxHp;
            hpLostThisTurn += excess;
            hpLostThisCombat += excess;
        }
        if (player.maxHp <= 0 || player.hp <= 0) {
            player.hp = 0;
            outcome = Outcome::PLAYER_LOSS;
            return;
        }
    }
    // PainfulStabsPower.AfterAttack: one Wound per unblocked hit of a powered
    // attack, multiplied by the power amount.
    if (unblocked > 0 && m.power[static_cast<int>(PowerId::PAINFUL_STABS)] > 0) {
        const int wounds = m.power[static_cast<int>(PowerId::PAINFUL_STABS)];
        for (int i = 0; i < wounds && discardCount < MAX_PILE; ++i) {
            move_to_discard(make_card(CardId::WOUND, false, require_card_uid()));
        }
    }
    if (player_power(PowerId::FLAME_BARRIER) > 0 && m.alive) {
        damage_monster(monsterIdx, player_power(PowerId::FLAME_BARRIER));
    }
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

void BattleContext::apply_strength_loss(int idx, int amount) {
    if (amount <= 0 || idx < 0 || idx >= monsterCount || !monsters[idx].alive) return;
    if (monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)] > 0) {
        --monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)];
        return;
    }
    monsters[idx].strength -= amount;
    monsters[idx].tempStrengthLoss += amount;
}

void BattleContext::add_temp_strength(int amount) {
    // TemporaryStrengthPower.BeforeApplied applies StrengthPower (silent is a
    // display flag only), so Ruined Helmet doubles this gain like any other.
    add_player_power(PowerId::STRENGTH, amount);
    player.tempStrength += amount;
}

void BattleContext::add_temp_dexterity(int amount) {
    player.dexterity += amount;
    player.tempDexterity += amount;
}

// ---------------------------------------------------------------- card pools

Card BattleContext::random_card_of_type(CardType type, bool include_colorless) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type != type) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        if (d.pool == CardPool::IRONCLAD) {
            // Always available.
        } else if (d.pool == CardPool::COLORLESS && include_colorless) {
            // Caller explicitly requested the combined pool.
        } else {
            continue;
        }
        pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, require_card_uid());
    return make_card(pool[cardGenerationRng.next_int(0, n - 1)], false, require_card_uid());
}

Card BattleContext::random_attack() { return random_card_of_type(CardType::ATTACK, true); }
Card BattleContext::random_skill() { return random_card_of_type(CardType::SKILL, true); }
Card BattleContext::random_power() { return random_card_of_type(CardType::POWER, true); }

Card BattleContext::random_colorless_card() {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.pool != CardPool::COLORLESS) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, require_card_uid());
    return make_card(pool[cardGenerationRng.next_int(0, n - 1)], false, require_card_uid());
}

Card BattleContext::random_character_card_excluding(const CardId *excluded,
                                                    int excludedCount) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.pool != CardPool::IRONCLAD) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        bool blocked = false;
        for (int k = 0; k < excludedCount; ++k) {
            blocked = blocked || excluded[k] == static_cast<CardId>(i);
        }
        if (!blocked) pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, require_card_uid());
    return make_card(pool[cardGenerationRng.next_int(0, n - 1)], false, require_card_uid());
}

Card BattleContext::random_colorless_card_excluding(const CardId *excluded,
                                                    int excludedCount) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.pool != CardPool::COLORLESS) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        bool blocked = false;
        for (int k = 0; k < excludedCount; ++k) {
            blocked = blocked || excluded[k] == static_cast<CardId>(i);
        }
        if (!blocked) pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return make_card(CardId::STRIKE_IRONCLAD, false, require_card_uid());
    return make_card(pool[cardGenerationRng.next_int(0, n - 1)], false, require_card_uid());
}

void BattleContext::add_random_card_to_hand(CardType type, bool free, bool colorless, bool upgraded) {
    Card c = colorless ? random_colorless_card() : random_card_of_type(type, true);
    if (upgraded) upgrade_card(c);
    if (free) card_set_turn_cost(c, 0);
    add_card_to_hand(c);
}

void BattleContext::upgrade_card(Card &c) { card_apply_upgrade(c); }

void BattleContext::transform_card(Card &c) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    const CardDef &original = card_def(c.id);
    CardPool poolKind = original.pool;
    if (original.rarity == Rarity::ANCIENT || original.rarity == Rarity::EVENT ||
        original.rarity == Rarity::TOKEN) {
        poolKind = CardPool::COLORLESS;
    }
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.pool != poolKind) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        if (static_cast<CardId>(i) == c.id) continue;
        pool[n++] = static_cast<CardId>(i);
    }
    if (n == 0) return;
    const CardId id = pool[cardGenerationRng.next_int(0, n - 1)];
    const std::uint16_t uid = c.uid;
    c = make_card(id, false, uid);
    if (card_is_power(c)) {
        for (int i = 0; i < monsterCount; ++i) {
            const int amount =
                monsters[i].power[static_cast<int>(PowerId::GALVANIC)];
            if (monsters[i].alive && amount > 0) {
                c.galvanized = static_cast<std::int16_t>(amount);
                break;
            }
        }
    }
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
        for (int i = 0; i < handCount && pending.count < MAX_PILE; ++i) {
            if (op == ChoiceOp::UPGRADE && hand[i].upgraded) continue;
            if (op == ChoiceOp::DUPLICATE && !card_is_attack(hand[i]) &&
                !card_is_power(hand[i])) continue;
            pending.cards[pending.count++] = hand[i];
        }
    } else if (pile == ChoicePile::DISCARD) {
        for (int i = 0; i < discardCount && pending.count < MAX_PILE; ++i) {
            pending.cards[pending.count++] = discard[i];
        }
    } else if (pile == ChoicePile::DRAW) {
        int indices[MAX_PILE];
        for (int i = 0; i < drawCount; ++i) indices[i] = i;
        const int limit = std::min(candidateLimit, std::min(drawCount, MAX_PILE));
        for (int i = 0; i < limit; ++i) {
            const int j = i + cardSelectionRng.next_int(0, drawCount - 1 - i);
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
        if (type >= 0 && static_cast<int>(d.type) != type) continue;
        if (rarity >= 0 && static_cast<int>(d.rarity) != rarity) continue;
        indices[n++] = i;
    }
    std::sort(indices, indices + n, [&](int a, int b) {
        const int byId = std::strcmp(card_key(draw[a].id), card_key(draw[b].id));
        if (byId != 0) return byId < 0;
        return draw[a].upgraded < draw[b].upgraded;
    });
    // Seeker Strike samples from a stable-shuffled copy of the whole pile.
    // Full-grid choices such as Wish and Secret Weapon use no random draw.
    if (candidateLimit >= 0) cardSelectionRng.shuffle(indices, n);
    const int limit = candidateLimit < 0 ? n : std::min(candidateLimit, n);
    for (int i = 0; i < limit && pending.count < MAX_PILE; ++i) {
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
    for (int i = 0; i < count && i < MAX_PILE; ++i) pending.cards[pending.count++] = cards[i];
    if (pending.count == 0) pending = PendingChoice();
}

void BattleContext::maybe_finish_pending() {
    if (pending.op == ChoiceOp::NONE) return;
    if (pending.remaining > 0 && pending.count > 0) return;
    const ChoiceOp op = pending.op;
    const int payload = pending.payload;
    const Card src = pending.sourceCard;
    const bool hadSource = pending.hasSource;
    const bool sourceExhaust = pending.sourceExhaust;
    pending = PendingChoice();
    // A card play owns its source entity until every play iteration finished
    // (OnPlayWrapper moves it once, at the end).  Only standalone effects
    // (potions and the like) move a source card here.
    if (!activePlay.active && hadSource) {
        if (sourceExhaust) move_to_exhaust(src);
        else move_to_discard(src);
    }
    if (op == ChoiceOp::DISCARD_ANY) draw_cards(payload);
    if (src.id == CardId::BURNING_PACT) draw_cards(card_var(src, VarId::CARDS));
    if (src.id == CardId::BRAND) add_player_power(PowerId::STRENGTH, card_var(src, VarId::STRENGTH));
    if (src.id == CardId::SEEKER_STRIKE) { /* chosen card already added */ }
    // Resume a draw interrupted by the Stratagem selection.
    if (pendingDrawRemainder > 0 && pending.op == ChoiceOp::NONE) {
        const int n = pendingDrawRemainder;
        pendingDrawRemainder = 0;
        draw_cards(n);
    }
    check_outcome();
    // Resume the suspended play frame (remaining replays + AfterCardPlayed).
    if (activePlay.active) run_active_play();
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
    int originalHandIndex = -1;
    if (pile == ChoicePile::HAND) {
        for (int i = 0; i < handCount; ++i) if (hand[i].uid == uid) {
            chosen = hand[i];
            originalHandIndex = i;
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
            remove_draw_at(i);
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
            // LiquidMemories: EnergyCost.SetThisTurnOrUntilPlayed(0).
            if (pending.payload) card_set_turn_cost(chosen, 0);
            add_card_to_hand(chosen);
            break;
        case ChoiceOp::OFFER_TO_HAND:
            if (pending.payload) card_set_turn_cost(chosen, 0);
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
        case ChoiceOp::DUPLICATE:
            // The selected card stays in its original position; generated
            // copies are separate entities with fresh combat UIDs.
            for (int i = handCount; i > originalHandIndex; --i) hand[i] = hand[i - 1];
            hand[originalHandIndex] = chosen;
            ++handCount;
            for (int i = 0; i < pending.payload; ++i) {
                Card copy = chosen;
                copy.uid = require_card_uid();
                add_card_to_hand(copy);
            }
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
        if (enthralled_blocks(*this, c)) continue;
        if (c.id == CardId::CLASH) {
            bool hasNonAttack = false;
            for (int j = 0; j < handCount; ++j) {
                hasNonAttack |= !card_is_attack(hand[j]);
            }
            if (hasNonAttack) continue;
        }
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
    struct ClearReservations {
        BattleContext &battle;
        ~ClearReservations() { battle.clear_card_uid_reservations(); }
    } clearReservations{*this};
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
        if (enthralled_blocks(*this, c)) return false;
        if (c.id == CardId::CLASH) {
            for (int i = 0; i < handCount; ++i) {
                if (!card_is_attack(hand[i])) return false;
            }
        }
        if (c.id == CardId::PACTS_END && exhaustCount < card_var(c, VarId::CARDS)) return false;
        if (player_power(PowerId::RINGING) > 0 && cardsPlayedThisTurn > 0) return false;
        if (skillsLocked && card_is_skill(c)) return false;
        if (card_def(c.id).target == TargetType::ENEMY) {
            if (action.target >= monsterCount || !monsters[action.target].alive) return false;
        }
        return play_card(action.hand, action.target);
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

bool BattleContext::play_card(int handIdx, int target) {
    if (handIdx < 0 || handIdx >= handCount) return false;
    if (normality_blocks(*this)) return false;
    Card card = hand[handIdx];
    if (enthralled_blocks(*this, card)) return false;
    if (card.id == CardId::CLASH) {
        for (int i = 0; i < handCount; ++i) {
            if (!card_is_attack(hand[i])) return false;
        }
    }
    int cost = card_cost(card);
    const bool xCostCard = cost < 0;
    if (player_power(PowerId::CORRUPTION) > 0 && card_is_skill(card)) cost = 0;
    const bool freeAttack = card_is_attack(card) && player_power(PowerId::FREE_ATTACK) > 0;
    // FreeAttackPower.TryModifyEnergyCostInCombat returns 0 for attacks, but an
    // X-cost card still spends all current energy: GetAmountToSpend special-
    // cases CostsX before any cost modification.
    if (freeAttack && !xCostCard) cost = 0;
    if (relic_has(*this, RelicId::BRILLIANT_SCARF) && cardsPlayedThisTurn == 4) cost = 0;
    if (player_power(PowerId::CHAINS_OF_BINDING) > 0 && cost > 0) ++cost;
    if (relic_has(*this, RelicId::SPIKED_GAUNTLETS) && card_is_power(card) && cost > 0) ++cost;
    if (player_power(PowerId::RINGING) > 0 && cardsPlayedThisTurn > 0) return false;
    if (skillsLocked && card_is_skill(card)) return false;
    if (relic_has(*this, RelicId::VELVET_CHOKER) && cardsPlayedThisTurn >= 6) return false;
    int x = xCostCard ? player.energy : 0;
    if (xCostCard && relic_has(*this, RelicId::CHEMICAL_X)) x += 2;
    const int spend = xCostCard ? player.energy : cost;
    if (spend > player.energy) return false;

    if (freeAttack) add_player_power(PowerId::FREE_ATTACK, -1);
    // IntimidatingHelmet.BeforeCardPlayed checks the energy actually spent
    // (CardPlay.Resources.EnergyValue), not the printed cost.
    if (spend >= 2 && relic_has(*this, RelicId::INTIMIDATING_HELMET)) {
        gain_block(4, false, false);
        if (outcome != Outcome::UNDECIDED) return true;
    }
    player.energy -= spend;
    xCost = x;
    remove_at(hand, handCount, handIdx);
    returnToHand = false;
    begin_play(card, target, false, false, spend);
    return true;
}

void BattleContext::begin_play(const Card &cardIn, int target, bool autoPlay, bool forceExhaust,
                               int energySpent) {
    if (card_def(cardIn.id).target == TargetType::ENEMY ||
        card_def(cardIn.id).target == TargetType::RANDOM_ENEMY) {
        face_surrounded_target(target);
    }
    activePlay = ActivePlay();
    activePlay.active = true;
    activePlay.card = cardIn;
    activePlay.target = target;
    activePlay.autoPlay = autoPlay;
    activePlay.forceExhaust = forceExhaust;
    activePlay.dupe = nextPlayIsDupe;
    nextPlayIsDupe = false;
    activePlay.energySpent = energySpent;
    Card &card = activePlay.card;
    // NostalgiaPower decides the result pile once, before any play iteration
    // (CardModel.OnPlayWrapper).  Only cards that would land in the discard
    // pile are redirected; Exhaust/Power results are never overridden.
    if (player_power(PowerId::NOSTALGIA) > 0 && (card_is_attack(card) || card_is_skill(card)) &&
        !forceExhaust && !card_exhausts(*this, card) &&
        attackSkillPlaysThisTurn < player_power(PowerId::NOSTALGIA)) {
        activePlay.resultsToDraw = true;
    }
    // CardModel.GetEnchantedReplayCount + Hook.ModifyCardPlayCount.
    int plays = 1 + card.replay + card.bonusReplay;
    if (card.enchantment == EnchantmentId::GLAM && !card.enchantmentDisabled)
        ++plays;
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
    activePlay.playCount = plays > 0 ? plays : 1;
    run_active_play();
}

void BattleContext::run_active_play() {
    while (activePlay.active) {
        // A selector inside OnPlay suspends the frame until it is resolved.
        if (pending.op != ChoiceOp::NONE) return;
        if (activePlay.awaitingAfter) {
            Card &card = activePlay.card;
            if (activePlay.swiftAwaitingDraw) {
                activePlay.swiftAwaitingDraw = false;
                card.enchantmentDisabled = true;
            } else if (!card.enchantmentDisabled) {
                if (card.enchantment == EnchantmentId::SOWN) {
                    player.energy += card.enchantmentAmount;
                    card.enchantmentDisabled = true;
                } else if (card.enchantment == EnchantmentId::SWIFT) {
                    activePlay.swiftAwaitingDraw = true;
                    draw_cards(card.enchantmentAmount);
                    if (pending.op != ChoiceOp::NONE) return;
                    activePlay.swiftAwaitingDraw = false;
                    activePlay.card.enchantmentDisabled = true;
                } else if (card.enchantment == EnchantmentId::VIGOROUS ||
                           card.enchantment == EnchantmentId::GLAM) {
                    card.enchantmentDisabled = true;
                }
            }
            activePlay.awaitingAfter = false;
            after_card_played(activePlay.card);
            continue;
        }
        if (activePlay.nextPlay >= activePlay.playCount ||
            outcome != Outcome::UNDECIDED) {
            finish_active_play();
            return;
        }
        Card &card = activePlay.card;
        const int target = activePlay.target;
        ++activePlay.nextPlay;
        // Each play iteration is one CardPlay: history counters and
        // Before/AfterCardPlayed hooks run per iteration (CardModel.cs loop).
        ++cardsPlayedThisTurn;
        ++cardsPlayedThisCombat;
        if (card_is_attack(card)) {
            // Stomp listens to BeforeCardPlayed from every combat pile.
            Card *piles[] = {hand, draw, discard, exhaust, playPile, returnNextTurn};
            const int counts[] = {handCount, drawCount, discardCount, exhaustCount,
                                  playCount, returnNextTurnCount};
            for (int p = 0; p < 6; ++p) {
                for (int i = 0; i < counts[p]; ++i) {
                    Card &stomp = piles[p][i];
                    if (stomp.id == CardId::STOMP && stomp.costForTurn >= 0) {
                        card_set_turn_cost(stomp, std::max(0, stomp.costForTurn - 1));
                    }
                }
            }
            ++attacksPlayedThisTurn;
            ++attacksPlayedThisCombat;
        }
        if (card_is_skill(card)) {
            ++skillsPlayedThisTurn;
            ++skillsPlayedThisCombat;
        }
        if (card_is_attack(card) || card_is_skill(card)) {
            ++attackSkillPlaysThisTurn;
            if (playedThisTurnCount < MAX_PILE) playedThisTurn[playedThisTurnCount++] = card.uid;
        }
        blockPlayIndex = -1;
        relics_card_about_to_play(*this, card);
        resolvingCard = true;
        play_card_effect(card, target);
        resolvingCard = false;
        activePlay.awaitingAfter = true;
        if (pending.op != ChoiceOp::NONE) return;  // resume after the choice
    }
}

void BattleContext::finish_active_play() {
    const Card card = activePlay.card;
    const bool exhaustIt = activePlay.forceExhaust;
    const bool toDraw = activePlay.resultsToDraw;
    activePlay = ActivePlay();
    if (outcome != Outcome::UNDECIDED) {
        // The battle ended while the card was resolving; still move the one
        // source entity exactly once.  A card already queued for next turn
        // (Bolas) must not also appear in the discard pile.
        if (returnToHand) {
            returnToHand = false;
            return;
        }
        move_to_discard(card);
        return;
    }
    if (card_is_power(card)) {
        // Power cards are removed from combat (PileType.None).
        return;
    }
    if (returnToHand) {
        returnToHand = false;
        return;  // already queued in returnNextTurn
    }
    Card played = card;
    if (relic_has(*this, RelicId::RAZOR_TOOTH) &&
        (card_is_attack(played) || card_is_skill(played)) && card_upgradable(played)) {
        card_apply_upgrade(played);
    }
    // EnergyCost.AfterCardPlayedCleanup happens once, after all plays.
    card_restore_cost(played);
    // NostalgiaPower's result-pile modification (decided at play start).
    if (toDraw) {
        add_card_to_draw_top(played);
        return;
    }
    // ReboundPower modifies the next card that would otherwise enter discard.
    if (reboundPending && card.id != CardId::REBOUND && !exhaustIt &&
        !card_exhausts(*this, played)) {
        reboundPending = false;
        add_card_to_draw_top(played);
        return;
    }
    if (exhaustIt || card_exhausts(*this, played)) move_to_exhaust(played);
    else move_to_discard(played);
    check_outcome();
}

void BattleContext::after_card_played(const Card &card) {
    if (outcome != Outcome::UNDECIDED) return;
    // RupturePower.AfterCardPlayed: strength accrued during this card's OnPlay
    // is granted now, per play iteration.
    if (pendingRupture != 0) {
        add_player_power(PowerId::STRENGTH, pendingRupture);
        pendingRupture = 0;
    }
    // Galvanized affliction: the owner takes the Galvanic amount after playing
    // the afflicted Power card.
    if (card.galvanized > 0) {
        damage_player(card.galvanized, true, false);
        if (outcome != Outcome::UNDECIDED) return;
    }
    relics_card_played(*this, card);
    if (card_is_attack(card)) {
        if (player_power(PowerId::RAGE) > 0)
            gain_block(player_power(PowerId::RAGE), false, false);
        if (player_power(PowerId::CALAMITY) > 0) add_random_card_to_hand(CardType::ATTACK, true);
        if (player_power(PowerId::JUGGLING) > 0 && attacksPlayedThisTurn == 3 && !jugglingTriggeredThisTurn) {
            jugglingTriggeredThisTurn = true;
            for (int n = 0; n < player_power(PowerId::JUGGLING); ++n) {
                Card copy = card;
                copy.uid = require_card_uid();
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
    // SlowPower.AfterCardPlayed counts every card the player plays this turn.
    for (int i = 0; i < monsterCount; ++i) {
        if (monsters[i].alive && monsters[i].power[static_cast<int>(PowerId::SLOW)] > 0) {
            ++monsters[i].slowCardsThisTurn;
        }
    }
    // EnragePower.AfterCardPlayed: a Skill played by the player grants Strength.
    if (card_is_skill(card)) {
        for (int i = 0; i < monsterCount; ++i) {
            if (monsters[i].alive && monsters[i].power[static_cast<int>(PowerId::ENRAGE)] > 0) {
                add_monster_power(i, PowerId::STRENGTH,
                                  monsters[i].power[static_cast<int>(PowerId::ENRAGE)]);
            }
        }
    }
    // GigantificationPower.AfterAttack: one stack expires after the AttackCommand.
    if (card_is_attack(card) && player_power(PowerId::GIGANTIFICATION) > 0) {
        add_player_power(PowerId::GIGANTIFICATION, -1);
    }
    if (card_is_attack(card) || card_is_skill(card)) {
        playedAttackOrSkillThisTurn = true;
    }
    for (int i = 0; i < panacheCount && outcome == Outcome::UNDECIDED; ++i) {
        if (!panachePrimed[i]) {
            panachePrimed[i] = true;
            continue;
        }
        if (--panacheLeft[i] <= 0) {
            attack_all(panacheDamage[i], 1, false);
            panacheLeft[i] = 5;
        }
    }
    check_outcome();
}

void BattleContext::auto_play_random(const Card &card, bool exhaustIt) {
    if (outcome != Outcome::UNDECIDED) return;
    Card c = card;
    // CardCmd.AutoPlay calls Hook.ShouldPlay first; Velvet Choker's limit and
    // Normality apply to auto-plays exactly as they do to manual plays.
    const bool blocked =
        !card_is_playable(c) || normality_blocks(*this) ||
        (relic_has(*this, RelicId::VELVET_CHOKER) && cardsPlayedThisTurn >= 6);
    if (blocked) {
        // CardCmd.AutoPlay -> MoveToResultPileWithoutPlaying.
        if (exhaustIt) move_to_exhaust(c);
        else move_to_discard(c);
        return;
    }
    // AutoPlay runs the same OnPlayWrapper lifecycle as a manual play
    // (counters, Before/AfterCardPlayed, Duplication, replay).  It does not pay
    // energy, and X is captured from the current energy like CardCmd.AutoPlay.
    const ActivePlay outer = activePlay;
    // The parent frame lives on the C++ stack while the nested frame runs;
    // reserve its identity until the enclosing action completes.
    if (outer.active && outer.card.uid != 0 && outer.card.uid != 65535)
        uidReservations[outer.card.uid / 64] |= std::uint64_t{1} << (outer.card.uid % 64);
    const bool outerReturnToHand = returnToHand;
    const int outerXCost = xCost;
    int target = 0;
    if (card_def(c.id).target == TargetType::ENEMY || card_def(c.id).target == TargetType::RANDOM_ENEMY) {
        target = random_alive_monster();
        if (target < 0) target = 0;
    }
    const bool xCostCard = card_def(c.id).cost < 0;
    xCost = player.energy + (xCostCard && relic_has(*this, RelicId::CHEMICAL_X) ? 2 : 0);
    returnToHand = false;
    begin_play(c, target, true, exhaustIt);
    // Auto-played selectors are resolved automatically; resolution resumes the
    // suspended frame, so a replay's second selector cannot overwrite the first.
    if (pending.op != ChoiceOp::NONE) auto_resolve_pending();
    if (activePlay.active) {
        activePlay.nextPlay = activePlay.playCount;
        run_active_play();
    }
    activePlay = outer;
    returnToHand = outerReturnToHand;
    xCost = outerXCost;
}

void BattleContext::auto_play_dupe(const Card &card) {
    nextPlayIsDupe = true;
    auto_play_random(card, false);
    nextPlayIsDupe = false;
}

void BattleContext::auto_play_from_draw(int count, bool forceExhaust) {
    if (outcome != Outcome::UNDECIDED) return;
    Card picks[MAX_PILE];
    int n = 0;
    for (int i = 0; i < count && n < MAX_PILE; ++i) {
        if (drawCount == 0) shuffle_discard_into_draw();
        if (drawCount == 0) break;
        picks[n++] = take_draw_top();
    }
    for (int i = 0; i < n && outcome == Outcome::UNDECIDED; ++i) {
        auto_play_random(picks[i], forceExhaust);
    }
}

void BattleContext::play_card_effect(Card &card, int target) {
    if (ironclad_effect(*this, card, target)) return;
    if (colorless_effect(*this, card, target)) return;
    if (status_effect(*this, card, target)) return;
    // generic fallback for plain damage/block cards
    if (card_is_attack(card)) {
        if (card_def(card.id).target == TargetType::ALL_ENEMIES) attack_from_card(card, target, card_damage(card), 1, true);
        else if (card_def(card.id).target == TargetType::RANDOM_ENEMY) {
            const int target = random_alive_monster();
            if (target >= 0) attack_from_card(card, target, card_damage(card));
        }
        else attack_from_card(card, target, card_damage(card));
    } else if (card_block(card) > 0) {
        gain_block(card_block(card), true);
    }
}

bool BattleContext::card_will_exhaust(const Card &c) const {
    return card_exhausts(*this, c);
}

}  // namespace sts2
