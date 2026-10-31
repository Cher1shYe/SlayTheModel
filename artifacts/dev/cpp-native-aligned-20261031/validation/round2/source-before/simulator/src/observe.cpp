#include "sts2/observe.h"

#include <algorithm>
#include <cassert>
#include <tuple>

#include "sts2/monsters.h"

namespace sts2 {

namespace {

void push_one_hot(std::vector<float> &v, int index, int count) {
    for (int i = 0; i < count; ++i) v.push_back(i == index ? 1.0f : 0.0f);
}

bool is_visited(const RunContext &rc, int idx) {
    if (idx < 0) return false;
    if (idx < 64) return (rc.visitedLo >> idx) & 1u;
    if (idx < 128) return (rc.visitedHi >> (idx - 64)) & 1u;
    return false;
}

void push_card_bag(std::vector<float> &v, const Card *cards, int n) {
    float counts[static_cast<int>(CardId::COUNT)]{};
    for (int i = 0; i < n; ++i) {
        const int id = static_cast<int>(cards[i].id);
        if (id >= 0 && id < static_cast<int>(CardId::COUNT)) counts[id] += 1.0f;
    }
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(counts[i]);
}

// Visible pile contents with the card's upgrade state kept distinct: the pile
// viewer shows upgraded identities, so the bag must not merge them.
void push_card_bag_split(std::vector<float> &v, const Card *cards, int n) {
    float base[static_cast<int>(CardId::COUNT)]{};
    float up[static_cast<int>(CardId::COUNT)]{};
    for (int i = 0; i < n; ++i) {
        const int id = static_cast<int>(cards[i].id);
        if (id < 0 || id >= static_cast<int>(CardId::COUNT)) continue;
        if (cards[i].upgraded) up[id] += 1.0f;
        else base[id] += 1.0f;
    }
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(base[i]);
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(up[i]);
}

// Only attributes visible on the offered card are used to order a choice.
// The underlying draw/discard stack order is not public information.
auto visible_choice_key(const Card &c) {
    return std::make_tuple(static_cast<int>(c.id), c.upgraded, card_cost(c), c.replay,
                           c.bonusReplay, c.freeCombat, c.costThisTurn, c.combatCostCap,
                           c.bonusDamage, c.etherealThisCombat, c.retainThisCombat,
                           c.galvanized, c.guiltyCombatsSeen,
                           static_cast<int>(c.enchantment), c.enchantmentAmount,
                           c.enchantmentDisabled);
}

}  // namespace

std::vector<float> run_observation(const RunContext &rc) {
    std::vector<float> v;
    v.reserve(RUN_OBS_DIM);
    v.push_back(rc.maxHp > 0 ? static_cast<float>(rc.hp) / rc.maxHp : 0.0f);
    v.push_back(rc.maxHp / 100.0f);
    v.push_back(rc.gold / 300.0f);
    v.push_back(rc.floor / 49.0f);
    v.push_back((rc.act + 1) / 3.0f);
    v.push_back(rc.deckCount / 40.0f);
    int upgrades = 0;
    for (int i = 0; i < rc.deckCount; ++i) upgrades += rc.deck[i].upgraded ? 1 : 0;
    v.push_back(rc.deckCount > 0 ? static_cast<float>(upgrades) / rc.deckCount : 0.0f);

    const int screen = static_cast<int>(rc.screen);
    for (int i = 0; i < 8; ++i) v.push_back(screen == i ? 1.0f : 0.0f);

    float counts[static_cast<int>(CardId::COUNT)]{};
    for (int i = 0; i < rc.deckCount; ++i) {
        const int id = static_cast<int>(rc.deck[i].id);
        if (id >= 0 && id < static_cast<int>(CardId::COUNT)) counts[id] += 1.0f;
    }
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(counts[i] / 10.0f);
    return v;
}

std::vector<float> card_features(const Card &c, int price) {
    std::vector<float> v;
    v.reserve(CARD_FEAT_DIM);
    const int id = static_cast<int>(c.id);
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(i == id ? 1.0f : 0.0f);

    const CardDef &d = card_def(c.id);
    const int cost = card_cost(c);
    v.push_back(cost < 0 ? 1.0f : cost / 3.0f);
    for (int i = 0; i < 5; ++i) v.push_back(static_cast<int>(d.type) == i ? 1.0f : 0.0f);
    for (int i = 0; i < 5; ++i) v.push_back(static_cast<int>(d.rarity) == i ? 1.0f : 0.0f);
    v.push_back(c.upgraded ? 1.0f : 0.0f);
    v.push_back(price >= 0 ? price / 200.0f : 0.0f);
    v.push_back(price >= 0 ? 1.0f : 0.0f);
    // Replay changes how many times a play resolves; it is visible on the card.
    v.push_back(c.replay / 4.0f);
    v.push_back(c.bonusReplay / 4.0f);
    // A permanently free card (Touch of Insanity) and a card whose cost was
    // changed only this turn are different states even when both read as 0.
    v.push_back(c.freeCombat ? 1.0f : 0.0f);
    v.push_back(c.costThisTurn ? 1.0f : 0.0f);
    v.push_back(std::min<int>(99, c.galvanized) / 10.0f);
    v.push_back(c.bonusDamage / 30.0f);
    v.push_back(c.etherealThisCombat ? 1.0f : 0.0f);
    v.push_back(c.retainThisCombat ? 1.0f : 0.0f);
    v.push_back(c.costThisTurn ? c.storedCost / 3.0f : 0.0f);
    v.push_back(c.combatCostCap / 3.0f);
    v.push_back(c.guiltyCombatsSeen / 5.0f);
    v.push_back(static_cast<int>(c.enchantment) / 5.0f);
    v.push_back(c.enchantmentAmount / 10.0f);
    v.push_back(c.enchantmentDisabled ? 1.0f : 0.0f);
    return v;
}

std::vector<float> combat_observation(const BattleContext &bc) {
    std::vector<float> v;
    v.reserve(COMBAT_OBS_DIM);
    const Player &p = bc.player;
    v.push_back(p.maxHp > 0 ? static_cast<float>(p.hp) / p.maxHp : 0.0f);
    v.push_back(p.hp / 100.0f);
    v.push_back(p.block / 50.0f);
    v.push_back(p.energy / 3.0f);
    v.push_back(p.energyPerTurn / 3.0f);
    v.push_back(p.strength / 10.0f);
    v.push_back(p.dexterity / 10.0f);
    v.push_back(p.vulnerable / 10.0f);
    v.push_back(p.weak / 10.0f);
    v.push_back(p.frail / 10.0f);
    v.push_back(bc.player_power(PowerId::RAGE) / 5.0f);
    v.push_back(bc.player_power(PowerId::FLAME_BARRIER) / 20.0f);
    v.push_back(bc.player_power(PowerId::THORNS) / 10.0f);
    v.push_back(bc.player_power(PowerId::DEMON_FORM) / 5.0f);
    v.push_back(bc.handCount / 10.0f);
    v.push_back(bc.drawCount / 30.0f);
    v.push_back(bc.discardCount / 30.0f);
    v.push_back(bc.exhaustCount / 30.0f);
    v.push_back(bc.turn / 20.0f);
    v.push_back(bc.pending.op != ChoiceOp::NONE ? 1.0f : 0.0f);
    v.push_back(bc.alive_monster_count() / 4.0f);

    for (int i = 0; i < MAX_MONSTERS; ++i) {
        const Monster &m = bc.monsters[i];
        v.push_back(i < bc.monsterCount && m.alive ? 1.0f : 0.0f);
        v.push_back(m.maxHp > 0 ? static_cast<float>(m.hp) / m.maxHp : 0.0f);
        v.push_back(m.hp / 100.0f);
        v.push_back(m.block / 50.0f);
        v.push_back(m.strength / 10.0f);
        v.push_back(m.vulnerable / 10.0f);
        v.push_back(m.weak / 10.0f);
        v.push_back(m.intentDamage / 50.0f);
        v.push_back(m.intentHits / 3.0f);
        v.push_back(m.intentType / 4.0f);
    }
    return v;
}

// ------------------------------------------------------------------ public

std::vector<float> public_combat_observation(const BattleContext &bc) {
    std::vector<float> v;
    v.reserve(PUBLIC_COMBAT_OBS_DIM);
    const Player &p = bc.player;

    // Player scalars.
    v.push_back(p.maxHp > 0 ? static_cast<float>(p.hp) / p.maxHp : 0.0f);
    v.push_back(p.hp / 100.0f);
    v.push_back(p.block / 50.0f);
    v.push_back(p.energy / 3.0f);
    v.push_back(p.energyPerTurn / 3.0f);
    v.push_back(p.drawPerTurn / 5.0f);
    v.push_back(p.strength / 10.0f);
    v.push_back(p.dexterity / 10.0f);
    // Temporary Strength/Dexterity expire at end of turn; the permanent value
    // alone cannot predict the next turn's attack.
    v.push_back(p.tempStrength / 10.0f);
    v.push_back(p.tempDexterity / 10.0f);
    v.push_back(p.vulnerable / 10.0f);
    v.push_back(p.weak / 10.0f);
    v.push_back(p.frail / 10.0f);
    v.push_back(bc.turn / 20.0f);
    for (int i = 0; i < POWER_COUNT; ++i) v.push_back(p.power[i] / 10.0f);
    // Cards played this turn decide Panache (every 5) and Letter Opener (every
    // 3 skills); both counters are player-visible.
    v.push_back(bc.cardsPlayedThisTurn / 10.0f);
    v.push_back(bc.attacksPlayedThisTurn / 10.0f);
    v.push_back(bc.skillsPlayedThisTurn / 10.0f);
    v.push_back(bc.unblockedHitsThisCombat / 10.0f);
    v.push_back(bc.cardsPlayedThisCombat / 10.0f);
    // AutomationPower is instanced; both the amount and remaining draw count
    // are visible in the power UI and change future energy gains.
    v.push_back(bc.automationCount / static_cast<float>(BattleContext::MAX_AUTOMATION));
    for (int i = 0; i < BattleContext::MAX_AUTOMATION; ++i) {
        const bool exists = i < bc.automationCount;
        v.push_back(exists ? bc.automationLeft[i] / 10.0f : 0.0f);
        v.push_back(exists ? bc.automationAmount[i] / 5.0f : 0.0f);
    }
    v.push_back(p.toricToughnessBlock / 50.0f);
    v.push_back(p.surroundedFacingRight ? 1.0f : 0.0f);
    v.push_back(p.tookUnblockedDamageThisTurn ? 1.0f : 0.0f);
    v.push_back(p.tookUnblockedAttackDamageThisCombat ? 1.0f : 0.0f);
    v.push_back(bc.exhaustedThisTurn / 10.0f);
    v.push_back(bc.hpLostThisTurn / 100.0f);
    v.push_back(bc.nextTurnEnergy / 10.0f);
    v.push_back(bc.nextTurnDraw / 10.0f);
    v.push_back(bc.attackSkillPlaysThisTurn / 10.0f);
    v.push_back(bc.blockCardPlaysThisTurn / 10.0f);
    v.push_back(bc.skillsLocked ? 1.0f : 0.0f);
    v.push_back(bc.recoveredStolenGold / 100.0f);

    const ActivePlay &play = bc.activePlay;
    v.push_back(play.active ? 1.0f : 0.0f);
    v.push_back(play.active ? play.target / 4.0f : 0.0f);
    v.push_back(play.active ? play.playCount / 10.0f : 0.0f);
    v.push_back(play.active ? play.nextPlay / 10.0f : 0.0f);
    v.push_back(play.active && play.autoPlay ? 1.0f : 0.0f);
    v.push_back(play.active && play.forceExhaust ? 1.0f : 0.0f);
    v.push_back(play.active && play.dupe ? 1.0f : 0.0f);
    v.push_back(play.active && play.resultsToDraw ? 1.0f : 0.0f);
    v.push_back(play.active && play.awaitingAfter ? 1.0f : 0.0f);
    v.push_back(play.active && play.swiftAwaitingDraw ? 1.0f : 0.0f);
    v.push_back(play.active ? play.energySpent / 3.0f : 0.0f);
    if (play.active) {
        const auto feat = card_features(play.card);
        v.insert(v.end(), feat.begin(), feat.end());
    } else {
        v.insert(v.end(), CARD_FEAT_DIM, 0.0f);
    }

    v.push_back(bc.toricCount / static_cast<float>(MAX_PILE));
    for (int i = 0; i < MAX_PILE; ++i) {
        const bool exists = i < bc.toricCount;
        v.push_back(exists ? bc.toricBlock[i] / 50.0f : 0.0f);
        v.push_back(exists ? bc.toricTurns[i] / 10.0f : 0.0f);
    }
    v.push_back(bc.rollingCount / static_cast<float>(MAX_PILE));
    for (int i = 0; i < MAX_PILE; ++i)
        v.push_back(i < bc.rollingCount ? bc.rollingDamage[i] / 50.0f : 0.0f);
    v.push_back(bc.panacheCount / static_cast<float>(MAX_PILE));
    for (int i = 0; i < MAX_PILE; ++i) {
        const bool exists = i < bc.panacheCount;
        v.push_back(exists ? bc.panacheDamage[i] / 50.0f : 0.0f);
        v.push_back(exists ? bc.panacheLeft[i] / 5.0f : 0.0f);
        v.push_back(exists && bc.panachePrimed[i] ? 1.0f : 0.0f);
    }
    // Cards removed by Swipe are public and can be returned after their thief dies.
    v.push_back(bc.theftCount / static_cast<float>(MAX_PILE));
    for (int i = 0; i < MAX_PILE; ++i) {
        const Card *c = i < bc.theftCount ? &bc.theftCards[i] : nullptr;
        v.push_back(c ? static_cast<int>(c->id) / static_cast<float>(CardId::COUNT) : 0.0f);
        v.push_back(c && c->upgraded ? 1.0f : 0.0f);
        v.push_back(c ? card_cost(*c) / 3.0f : 0.0f);
        v.push_back(c ? c->replay / 4.0f : 0.0f);
        v.push_back(c ? c->bonusReplay / 4.0f : 0.0f);
        v.push_back(c && c->freeCombat ? 1.0f : 0.0f);
        v.push_back(c && c->costThisTurn ? 1.0f : 0.0f);
        v.push_back(c ? c->combatCostCap / 3.0f : 0.0f);
        v.push_back(c ? c->bonusDamage / 30.0f : 0.0f);
        v.push_back(c && c->etherealThisCombat ? 1.0f : 0.0f);
        v.push_back(c && c->retainThisCombat ? 1.0f : 0.0f);
        v.push_back(c ? c->galvanized / 10.0f : 0.0f);
        v.push_back(c ? c->guiltyCombatsSeen / 5.0f : 0.0f);
        v.push_back(c ? static_cast<int>(c->enchantment) / 5.0f : 0.0f);
        v.push_back(c ? c->enchantmentAmount / 10.0f : 0.0f);
        v.push_back(c && c->enchantmentDisabled ? 1.0f : 0.0f);
        v.push_back(c ? (bc.theftOwners[i] + 1) / static_cast<float>(MAX_MONSTERS) : 0.0f);
        v.push_back(c && bc.theftReturned[i] ? 1.0f : 0.0f);
    }

    // Hand: full identity and playability.
    for (int i = 0; i < MAX_HAND; ++i) {
        if (i < bc.handCount) {
            const Card &c = bc.hand[i];
            const auto feat = card_features(c, -1);
            v.insert(v.end(), feat.begin(), feat.end());
            v.push_back(card_is_playable(c) ? 1.0f : 0.0f);
            v.push_back(card_cost(c) / 3.0f);
        } else {
            v.insert(v.end(), CARD_FEAT_DIM + 2, 0.0f);
        }
    }

    // Pile sizes and visible (unordered) contents.
    v.push_back(bc.handCount / 10.0f);
    v.push_back(bc.drawCount / 30.0f);
    v.push_back(bc.discardCount / 30.0f);
    v.push_back(bc.exhaustCount / 30.0f);
    push_card_bag_split(v, bc.draw, bc.drawCount);
    push_card_bag_split(v, bc.discard, bc.discardCount);
    push_card_bag_split(v, bc.exhaust, bc.exhaustCount);
    // Pile viewers expose enchantment states but not the stack order.
    const Card *piles[] = {bc.draw, bc.discard, bc.exhaust};
    const int pileCounts[] = {bc.drawCount, bc.discardCount, bc.exhaustCount};
    for (int p = 0; p < 3; ++p) {
        std::vector<const Card *> cards;
        for (int i = 0; i < pileCounts[p]; ++i) cards.push_back(&piles[p][i]);
        std::sort(cards.begin(), cards.end(), [](const Card *a, const Card *b) {
            return visible_choice_key(*a) < visible_choice_key(*b);
        });
        for (int i = 0; i < MAX_PILE; ++i) {
            const Card *c = i < static_cast<int>(cards.size()) ? cards[i] : nullptr;
            v.push_back(c ? static_cast<int>(c->id) / static_cast<float>(CardId::COUNT) : 0.0f);
            v.push_back(c && c->upgraded ? 1.0f : 0.0f);
            v.push_back(c ? static_cast<int>(c->enchantment) / 5.0f : 0.0f);
            v.push_back(c ? c->enchantmentAmount / 10.0f : 0.0f);
            v.push_back(c && c->enchantmentDisabled ? 1.0f : 0.0f);
        }
    }

    // Order of the known top of the draw pile (Headbutt, Nostalgia, innate,
    // known status placements).  Only knownTopCount entries are exposed.
    {
        const int known = std::min(bc.knownTopCount, bc.drawCount);
        v.push_back(known / 30.0f);
        for (int k = 0; k < PUB_KNOWN_TOP; ++k) {
            const int idx = bc.drawCount - 1 - k;
            if (k < known && idx >= 0) {
                const Card &c = bc.draw[idx];
                push_one_hot(v, static_cast<int>(c.id), static_cast<int>(CardId::COUNT));
                v.push_back(c.upgraded ? 1.0f : 0.0f);
            } else {
                for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(0.0f);
                v.push_back(0.0f);
            }
        }
        // Preserve the rest of the visible order without expanding every card
        // into another full one-hot vector.
        for (int k = PUB_KNOWN_TOP; k < MAX_PILE; ++k) {
            const int idx = bc.drawCount - 1 - k;
            const bool exists = k < known && idx >= 0;
            v.push_back(exists ? static_cast<int>(bc.draw[idx].id) /
                                     static_cast<float>(CardId::COUNT) : 0.0f);
            v.push_back(exists && bc.draw[idx].upgraded ? 1.0f : 0.0f);
        }
        for (int k = 0; k < MAX_PILE; ++k) {
            const int idx = bc.drawCount - 1 - k;
            const Card *c = k < known && idx >= 0 ? &bc.draw[idx] : nullptr;
            v.push_back(c ? static_cast<int>(c->enchantment) / 5.0f : 0.0f);
            v.push_back(c ? c->enchantmentAmount / 10.0f : 0.0f);
            v.push_back(c && c->enchantmentDisabled ? 1.0f : 0.0f);
        }
    }

    // Bomb instances are visible: each has its own countdown and damage.
    v.push_back(bc.bombCount / static_cast<float>(PUB_BOMB_SLOTS));
    for (int k = 0; k < PUB_BOMB_SLOTS; ++k) {
        const bool exists = k < bc.bombCount;
        v.push_back(exists ? bc.bombTurns[k] / 10.0f : 0.0f);
        v.push_back(exists ? bc.bombDamage[k] / 50.0f : 0.0f);
    }

    // Relics carried into this combat (identity + counter) and potions in the
    // belt: both change the legal actions and must be distinguishable.
    {
        float relicCounts[RELIC_COUNT]{};
        float relicAux[RELIC_COUNT]{};
        for (int i = 0; i < bc.relicCount; ++i) {
            const int id = bc.relics[i];
            if (id > 0 && id < RELIC_COUNT) {
                relicCounts[id] += 1.0f;
                relicAux[id] += bc.relicAux[i];
            }
        }
        for (int i = 0; i < RELIC_COUNT; ++i) v.push_back(relicCounts[i]);
        for (int i = 0; i < RELIC_COUNT; ++i) v.push_back(relicAux[i] / 10.0f);
        float potionCounts[POTION_COUNT]{};
        for (int i = 0; i < bc.potionCount; ++i) {
            const int id = bc.potions[i];
            if (id > 0 && id < POTION_COUNT) potionCounts[id] += 1.0f;
        }
        for (int i = 0; i < POTION_COUNT; ++i) v.push_back(potionCounts[i]);
        for (int i = 0; i < MAX_POTIONS; ++i)
            v.push_back(i < bc.potionCount ? bc.potions[i] / static_cast<float>(POTION_COUNT) : 0.0f);
    }

    // Monsters: identity, live stats, full power list, intent.
    for (int i = 0; i < MAX_MONSTERS; ++i) {
        if (i >= bc.monsterCount) {
            v.insert(v.end(), PUB_MON_FEAT, 0.0f);
            continue;
        }
        const Monster &m = bc.monsters[i];
        v.push_back(m.alive ? 1.0f : 0.0f);
        push_one_hot(v, static_cast<int>(m.id), MONSTER_COUNT);
        v.push_back(m.maxHp > 0 ? static_cast<float>(m.hp) / m.maxHp : 0.0f);
        v.push_back(m.hp / 200.0f);
        v.push_back(m.maxHp / 200.0f);
        v.push_back(m.block / 50.0f);
        v.push_back(m.strength / 10.0f);
        v.push_back(m.vulnerable / 10.0f);
        v.push_back(m.weak / 10.0f);
        v.push_back(m.intentDamage / 50.0f);
        v.push_back(m.intentHits / 3.0f);
        v.push_back(m.intentType / 8.0f);
        v.push_back(m.reviving ? 1.0f : 0.0f);
        v.push_back(m.shellHpLostThisTurn / 30.0f);
        for (int k = 0; k < POWER_COUNT; ++k) v.push_back(m.power[k] / 10.0f);
        for (int k = 0; k < 4; ++k) v.push_back(m.aux[k] / 5.0f);
        v.push_back(m.offBalance ? 1.0f : 0.0f);
        v.push_back(m.stunned ? 1.0f : 0.0f);
        v.push_back(m.slowCardsThisTurn / 10.0f);
        v.push_back(m.tempStrengthLoss / 10.0f);
        v.push_back(m.nemesisIntangible ? 1.0f : 0.0f);
        v.push_back(m.combatEndBlocker ? 1.0f : 0.0f);
        v.push_back(m.skittishTriggeredThisTurn ? 1.0f : 0.0f);
        v.push_back(m.stolenGold / 100.0f);
        v.push_back(m.steamEruptionDamage / 50.0f);
        v.push_back(m.grappleCount / static_cast<float>(MAX_PILE));
        for (int k = 0; k < MAX_PILE; ++k)
            v.push_back(k < m.grappleCount ? m.grappleAmounts[k] / 50.0f : 0.0f);
    }

    // Pending choice candidates (may come from hand, draw, discard or offers).
    // A whole pile can be offered; duplicates with the same identity are
    // interchangeable, so the set is encoded as per-card bags.  The operation
    // and source pile change what a choice means, so both are encoded below.
    v.push_back(bc.pending.op != ChoiceOp::NONE ? 1.0f : 0.0f);
    {
        float baseCounts[static_cast<int>(CardId::COUNT)]{};
        float upCounts[static_cast<int>(CardId::COUNT)]{};
        float tempCostCounts[static_cast<int>(CardId::COUNT)]{};
        for (int i = 0; i < bc.pending.count; ++i) {
            const Card &c = bc.pending.cards[i];
            const int id = static_cast<int>(c.id);
            if (id <= 0 || id >= static_cast<int>(CardId::COUNT)) continue;
            if (c.upgraded) upCounts[id] += 1.0f;
            else baseCounts[id] += 1.0f;
            const CardDef &d = card_def(c.id);
            const int baseCost = c.upgraded ? d.costUp : d.cost;
            if (c.freeCombat || card_cost(c) != baseCost) tempCostCounts[id] += 1.0f;
        }
        for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(baseCounts[i]);
        for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(upCounts[i]);
        for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(tempCostCounts[i]);
    }
    v.push_back(bc.pending.remaining / 10.0f);
    v.push_back(bc.pending.count / 10.0f);
    v.push_back(bc.pending.optional ? 1.0f : 0.0f);
    v.push_back(bc.pending.payload / 5.0f);
    push_one_hot(v, static_cast<int>(bc.pending.op), PUB_CHOICE_OP_N);
    push_one_hot(v, static_cast<int>(bc.pending.pile), PUB_CHOICE_PILE_N);
    v.push_back(bc.pending.hasSource ? 1.0f : 0.0f);
    v.push_back(bc.pending.sourceExhaust ? 1.0f : 0.0f);
    push_one_hot(v, bc.pending.hasSource ? static_cast<int>(bc.pending.sourceCard.id) : 0,
                 static_cast<int>(CardId::COUNT));
    // Choice actions name a particular offered card. Sort by visible features
    // so this does not disclose the order of a hidden draw/discard pile.
    std::vector<const Card *> visibleChoices;
    visibleChoices.reserve(bc.pending.count);
    for (int i = 0; i < bc.pending.count; ++i) visibleChoices.push_back(&bc.pending.cards[i]);
    std::sort(visibleChoices.begin(), visibleChoices.end(), [](const Card *a, const Card *b) {
        return visible_choice_key(*a) < visible_choice_key(*b);
    });
    for (int i = 0; i < MAX_PILE; ++i) {
        if (i >= static_cast<int>(visibleChoices.size())) {
            v.insert(v.end(), PUB_PENDING_INSTANCE_FEAT, 0.0f);
            continue;
        }
        const Card &c = *visibleChoices[i];
        v.push_back(static_cast<int>(c.id) / static_cast<float>(CardId::COUNT));
        v.push_back(c.upgraded ? 1.0f : 0.0f);
        v.push_back(card_cost(c) / 3.0f);
        v.push_back(c.replay / 4.0f);
        v.push_back(c.bonusReplay / 4.0f);
        v.push_back(c.freeCombat ? 1.0f : 0.0f);
        v.push_back(c.costThisTurn ? 1.0f : 0.0f);
        v.push_back(c.combatCostCap / 3.0f);
        v.push_back(c.bonusDamage / 30.0f);
        v.push_back(c.etherealThisCombat ? 1.0f : 0.0f);
        v.push_back(c.retainThisCombat ? 1.0f : 0.0f);
        v.push_back(c.galvanized / 10.0f);
        v.push_back(c.guiltyCombatsSeen / 5.0f);
        v.push_back(static_cast<int>(c.enchantment) / 5.0f);
        v.push_back(c.enchantmentAmount / 10.0f);
        v.push_back(c.enchantmentDisabled ? 1.0f : 0.0f);
    }

    assert(static_cast<int>(v.size()) == PUBLIC_COMBAT_OBS_DIM);
    return v;
}

std::vector<float> public_observation(const RunContext &rc) {
    std::vector<float> v;
    v.reserve(PUBLIC_OBS_DIM);

    const bool inCombat = rc.screen == RunScreen::COMBAT && rc.inBattle;
    const int liveHp = inCombat ? rc.battle.player.hp : rc.hp;
    const int liveMaxHp = inCombat ? rc.battle.player.maxHp : rc.maxHp;
    const int livePotionCount = inCombat ? rc.battle.potionCount : rc.potionCount;
    const int livePotionSlots = inCombat ? rc.battle.potionSlots : rc.potionSlots;

    // --- run scalars --------------------------------------------------------
    v.push_back(liveMaxHp > 0 ? static_cast<float>(liveHp) / liveMaxHp : 0.0f);
    v.push_back(liveMaxHp / 100.0f);
    v.push_back((inCombat ? rc.battle.gold : rc.gold) / 300.0f);
    v.push_back(rc.floor / 49.0f);
    v.push_back((rc.act + 1) / 3.0f);
    v.push_back(rc.deckCount / 40.0f);
    int upgrades = 0;
    for (int i = 0; i < rc.deckCount; ++i) upgrades += rc.deck[i].upgraded ? 1 : 0;
    v.push_back(rc.deckCount > 0 ? static_cast<float>(upgrades) / rc.deckCount : 0.0f);
    v.push_back(rc.won ? 1.0f : 0.0f);
    v.push_back(rc.inBattle ? 1.0f : 0.0f);
    v.push_back(rc.combatIsElite ? 1.0f : 0.0f);
    v.push_back(rc.combatIsBoss ? 1.0f : 0.0f);
    v.push_back(rc.actFloor / 15.0f);
    v.push_back(livePotionSlots > 0 ? static_cast<float>(livePotionCount) / livePotionSlots : 0.0f);
    v.push_back(rc.relicCount / 20.0f);
    v.push_back((rc.eventId + 1) / 48.0f);
    v.push_back(rc.eventPage / 4.0f);
    v.push_back(rc.combatsFought / 40.0f);
    v.push_back(rc.elitesFought / 10.0f);
    v.push_back(rc.bossesFought / 3.0f);
    v.push_back(rc.screen == RunScreen::RUN_OVER ? 1.0f : 0.0f);
    v.push_back(rc.rewardIsBoss ? 1.0f : 0.0f);
    v.push_back(livePotionSlots / static_cast<float>(MAX_POTIONS));
    v.push_back(rc.teaSetPending ? 1.0f : 0.0f);
    v.push_back(rc.cardsAdded / 10.0f);
    v.push_back(rc.nextCombatEnergy / 10.0f);
    v.push_back(rc.nextCombatUpgradeHand ? 1.0f : 0.0f);
    v.push_back(rc.nextCombatDazed / 10.0f);
    v.push_back(rc.emberTeaCombats / 10.0f);
    v.push_back(rc.furCoatCombats / 10.0f);
    v.push_back(rc.toyBoxCombats / 10.0f);
    v.push_back(rc.wongoCombats / 10.0f);
    v.push_back(rc.swordOfStoneWins / 10.0f);
    v.push_back(rc.paelsWingSkips / 10.0f);
    v.push_back(rc.silverCrucibleUses / 10.0f);
    v.push_back(rc.mawBankPurchased ? 1.0f : 0.0f);
    v.push_back(rc.treasureSkipped ? 1.0f : 0.0f);
    v.push_back(rc.truncated ? 1.0f : 0.0f);
    v.push_back(rc.eventCardSelection / 3.0f);

    // --- screen one-hot -----------------------------------------------------
    const int screen = static_cast<int>(rc.screen);
    for (int i = 0; i < PUB_SCREENS; ++i) v.push_back(screen == i ? 1.0f : 0.0f);

    // --- deck ---------------------------------------------------------------
    push_card_bag(v, rc.deck, rc.deckCount);
    // Run actions refer to deck positions. Preserve which visible card is
    // upgraded at each slot, including otherwise identical copies.
    for (int i = 0; i < MAX_DECK; ++i) {
        const bool exists = i < rc.deckCount;
        v.push_back(exists ? static_cast<int>(rc.deck[i].id) /
                                 static_cast<float>(CardId::COUNT) : 0.0f);
        v.push_back(exists && rc.deck[i].upgraded ? 1.0f : 0.0f);
        v.push_back(exists ? rc.deck[i].guiltyCombatsSeen / 5.0f : 0.0f);
        v.push_back(exists ? static_cast<int>(rc.deck[i].enchantment) / 5.0f : 0.0f);
        v.push_back(exists ? rc.deck[i].enchantmentAmount / 10.0f : 0.0f);
        v.push_back(exists && rc.deck[i].enchantmentDisabled ? 1.0f : 0.0f);
    }
    const RunCardGrid &grid = rc.cardGrid;
    v.push_back(grid.kind / 5.0f);
    v.push_back(grid.count / static_cast<float>(MAX_DECK));
    v.push_back(grid.selectedCount / 8.0f);
    v.push_back(grid.minSelect / 8.0f);
    v.push_back(grid.maxSelect / 8.0f);
    v.push_back(grid.preview ? 1.0f : 0.0f);
    v.push_back(grid.slotCount / 8.0f);
    v.push_back((grid.freeHead + 1) / 8.0f);
    for (int i = 0; i < 8; ++i)
        v.push_back(grid.kind ? (grid.orderSlots[i] + 1) / static_cast<float>(MAX_DECK) : 0.0f);
    for (int i = 0; i < 8; ++i)
        v.push_back(grid.kind ? (grid.freeNext[i] + 1) / 8.0f : 0.0f);
    for (int i = 0; i < 8; ++i) {
        if ((grid.kind == 1 || grid.kind == 2 || grid.kind == 5) && i < grid.count) {
            const auto features = card_features(grid.cards[i]);
            v.insert(v.end(), features.begin(), features.end());
        } else if (grid.kind >= 6 && i == 0) {
            // These new selectors do not use the generated-card slots. Their
            // pending effects must still be visible to a state-based policy.
            v.push_back(grid.damageAfterSelection / 16.0f);
            v.push_back(static_cast<int>(grid.curseAfterSelection) / static_cast<float>(CardId::COUNT));
            v.insert(v.end(), CARD_FEAT_DIM - 2, 0.0f);
        } else v.insert(v.end(), CARD_FEAT_DIM, 0.0f);
    }
    for (int i = 0; i < MAX_DECK; ++i)
        v.push_back(grid.kind && i < grid.count && grid.selected[i] ? 1.0f : 0.0f);

    // --- relics and counters ------------------------------------------------
    float relicCounts[RELIC_COUNT]{};
    int relicAux[RELIC_COUNT]{};
    for (int i = 0; i < rc.relicCount; ++i) {
        const int id = rc.relics[i];
        if (id > 0 && id < RELIC_COUNT) {
            relicCounts[id] += 1.0f;
            relicAux[id] += rc.relicAux[i];
        }
    }
    for (int i = 0; i < RELIC_COUNT; ++i) v.push_back(relicCounts[i]);
    for (int i = 0; i < RELIC_COUNT; ++i) v.push_back(relicAux[i] / 10.0f);

    // --- potions ------------------------------------------------------------
    {
        float potionCounts[POTION_COUNT]{};
        const int *livePotions = inCombat ? rc.battle.potions : rc.potions;
        for (int i = 0; i < livePotionCount; ++i) {
            const int id = livePotions[i];
            if (id > 0 && id < POTION_COUNT) potionCounts[id] += 1.0f;
        }
        for (int i = 0; i < POTION_COUNT; ++i) v.push_back(potionCounts[i]);
        for (int i = 0; i < MAX_POTIONS; ++i)
            v.push_back(i < livePotionCount ? livePotions[i] / static_cast<float>(POTION_COUNT) : 0.0f);
    }

    // --- map ----------------------------------------------------------------
    push_one_hot(v, rc.bossEncounter, static_cast<int>(Encounter::COUNT));
    push_one_hot(v, rc.secondBossEncounter, static_cast<int>(Encounter::COUNT));
    const std::vector<int> reachable = rc.available_map_nodes();
    for (int idx = 0; idx < MAP_MAX_POINTS; ++idx) {
        int row = -1;
        int col = -1;
        for (int r = 0; r < MAP_MAX_ROWS && row < 0; ++r) {
            for (int c = 0; c < MAP_WIDTH; ++c) {
                if (rc.map.index[r][c] == idx) { row = r; col = c; break; }
            }
        }
        const bool present = idx < rc.map.pointCount && row >= 0;
        bool isReachable = false;
        for (const int r : reachable) if (r == idx) { isReachable = true; break; }
        v.push_back(present ? 1.0f : 0.0f);
        const int type = present ? static_cast<int>(rc.map.nodes[idx].type) : 0;
        push_one_hot(v, type, 9);
        v.push_back(row / 16.0f);
        v.push_back(col / 6.0f);
        v.push_back(isReachable ? 1.0f : 0.0f);
        v.push_back(is_visited(rc, idx) ? 1.0f : 0.0f);
        v.push_back(rc.map.nodes[idx].childCount / 8.0f);
    }

    // --- event --------------------------------------------------------------
    push_one_hot(v, rc.eventId, PUB_EVENT_N);
    for (int i = 0; i < PUB_EVENT_CHOICES; ++i) {
        const bool exists = i < rc.eventChoiceCount;
        v.push_back(exists ? 1.0f : 0.0f);
        v.push_back(rc.eventData[i] / 100.0f);
        v.push_back(exists && rc.eventRelics[i] > 0 ? 1.0f : 0.0f);
        v.push_back(rc.eventRelics[i] / 300.0f);
        v.push_back(rc.eventCombat ? 1.0f : 0.0f);
        v.push_back(i == rc.eventPage ? 1.0f : 0.0f);
        // Relic offers (Ancients): identity is part of the visible choice.
        push_one_hot(v, rc.eventRelics[i], RELIC_COUNT);
    }
    for (int i = 0; i < 4; ++i) v.push_back(rc.eventData[i] / 100.0f);

    // --- reward overview ----------------------------------------------------
    const bool rewardsVisible = rc.screen == RunScreen::REWARDS ||
        (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);
    v.push_back(rewardsVisible ? rc.pendingGoldReward / 300.0f : 0.0f);
    v.push_back(rewardsVisible ? rc.pendingRecoveredGold / 300.0f : 0.0f);
    v.push_back(rewardsVisible && rc.pendingCardReward ? 1.0f : 0.0f);
    v.push_back(rewardsVisible && rc.pendingReturnToEvent ? 1.0f : 0.0f);
    push_one_hot(v, rewardsVisible ? rc.pendingPotionReward : 0, POTION_COUNT);
    for (int i = 0; i < MAX_REWARD_RELICS; ++i) {
        const bool exists = rewardsVisible && i < rc.pendingRelicCount;
        v.push_back(exists ? 1.0f : 0.0f);
        v.push_back(exists && rc.pendingRelicClaimed[i] ? 1.0f : 0.0f);
        push_one_hot(v, exists ? rc.pendingRelics[i] : 0, RELIC_COUNT);
    }
    for (int i = 0; i < MAX_REWARD_POTIONS; ++i)
        v.push_back(rewardsVisible && i < rc.pendingPotionCount ?
                    rc.pendingPotions[i] / static_cast<float>(POTION_COUNT) : 0.0f);
    for (int i = 0; i < MAX_CARD_REWARDS; ++i)
        v.push_back(rewardsVisible && rc.rewardCardPending[i] ? 1.0f : 0.0f);
    v.push_back(rewardsVisible ? (rc.activeCardReward + 1) / static_cast<float>(MAX_CARD_REWARDS) : 0.0f);
    push_one_hot(v, rewardsVisible ? static_cast<int>(rc.rewardResumeScreen) : -1, PUB_SCREENS);
    v.push_back(rewardsVisible && rc.deferredCustomRewards ? 1.0f : 0.0f);
    const bool theftVisible = inCombat || rewardsVisible;
    v.push_back(theftVisible ? rc.stolenSyncCount / static_cast<float>(MAX_PILE) : 0.0f);
    for (int i = 0; i < MAX_PILE; ++i) {
        const bool present = theftVisible && i < rc.stolenSyncCount && rc.stolenOriginalPresent[i];
        const Card *c = present ? &rc.stolenOriginals[i] : nullptr;
        v.push_back(c ? static_cast<int>(c->id) / static_cast<float>(CardId::COUNT) : 0.0f);
        v.push_back(c && c->upgraded ? 1.0f : 0.0f);
        v.push_back(c ? card_cost(*c) / 3.0f : 0.0f);
        v.push_back(c ? c->replay / 4.0f : 0.0f);
        v.push_back(c ? c->bonusReplay / 4.0f : 0.0f);
        v.push_back(c && c->freeCombat ? 1.0f : 0.0f);
        v.push_back(c && c->costThisTurn ? 1.0f : 0.0f);
        v.push_back(c ? c->combatCostCap / 3.0f : 0.0f);
        v.push_back(c ? c->bonusDamage / 30.0f : 0.0f);
        v.push_back(c && c->etherealThisCombat ? 1.0f : 0.0f);
        v.push_back(c && c->retainThisCombat ? 1.0f : 0.0f);
        v.push_back(c ? c->galvanized / 10.0f : 0.0f);
        v.push_back(c ? c->guiltyCombatsSeen / 5.0f : 0.0f);
        v.push_back(c ? static_cast<int>(c->enchantment) / 5.0f : 0.0f);
        v.push_back(c ? c->enchantmentAmount / 10.0f : 0.0f);
        v.push_back(c && c->enchantmentDisabled ? 1.0f : 0.0f);
        v.push_back(present ? 1.0f : 0.0f);
        v.push_back(theftVisible && i < rc.stolenSyncCount && rc.stolenRewardPending[i] ? 1.0f : 0.0f);
    }

    // --- card reward --------------------------------------------------------
    for (int i = 0; i < PUB_CARD_REWARD_N; ++i) {
        const bool exists = rc.screen == RunScreen::CARD_REWARD && i < rc.offeredCount;
        const auto feat = card_features(exists ? rc.offered[i] : Card{}, -1);
        v.insert(v.end(), feat.begin(), feat.end());
    }

    // --- shop ---------------------------------------------------------------
    for (int i = 0; i < MAX_SHOP_CARDS; ++i) {
        const bool exists = i < rc.shopCount;
        const auto feat = card_features(exists ? rc.shopCards[i] : Card{}, -1);
        v.insert(v.end(), feat.begin(), feat.end());
        v.push_back(exists ? rc.shopPrices[i] / 200.0f : 0.0f);
        v.push_back(exists && rc.shopSold[i] ? 1.0f : 0.0f);
    }
    for (int i = 0; i < MAX_SHOP_RELICS; ++i) {
        const bool exists = i < rc.shopRelicCount;
        push_one_hot(v, exists ? rc.shopRelics[i] : 0, RELIC_COUNT);
        v.push_back(exists ? rc.shopRelicPrices[i] / 300.0f : 0.0f);
        v.push_back(exists && rc.shopRelicSold[i] ? 1.0f : 0.0f);
    }
    for (int i = 0; i < MAX_SHOP_POTIONS; ++i) {
        const bool exists = i < rc.shopPotionCount;
        push_one_hot(v, exists ? rc.shopPotions[i] : 0, POTION_COUNT);
        v.push_back(exists ? rc.shopPotionPrices[i] / 150.0f : 0.0f);
        v.push_back(exists && rc.shopPotionSold[i] ? 1.0f : 0.0f);
    }
    v.push_back(rc.removalPrice / 200.0f);
    v.push_back(rc.removalUsed ? 1.0f : 0.0f);
    v.push_back(rc.cardShopRemovalsUsed / 5.0f);
    v.push_back(0.0f);  // reserved

    // --- combat -------------------------------------------------------------
    if (rc.screen == RunScreen::COMBAT && rc.inBattle) {
        const auto combat = public_combat_observation(rc.battle);
        v.insert(v.end(), combat.begin(), combat.end());
    } else {
        v.insert(v.end(), PUBLIC_COMBAT_OBS_DIM, 0.0f);
    }

    assert(static_cast<int>(v.size()) == PUBLIC_OBS_DIM);
    return v;
}

std::vector<float> combat_action_features(const BattleContext &bc, const Action &a) {
    std::vector<float> v;
    v.reserve(ACTION_FEAT_DIM);
    push_one_hot(v, static_cast<int>(a.type), 5);

    const Card *card = nullptr;
    bool fromOffer = false;
    if (a.type == ActionType::PLAY_CARD && a.hand < bc.handCount) {
        card = &bc.hand[a.hand];
    } else if (a.type == ActionType::CHOOSE) {
        for (int i = 0; i < bc.pending.count; ++i) {
            if (bc.pending.cards[i].uid == a.uid) {
                card = &bc.pending.cards[i];
                fromOffer = bc.pending.pile == ChoicePile::OFFER;
                break;
            }
        }
        if (card == nullptr) {
            for (int i = 0; i < bc.handCount; ++i) {
                if (bc.hand[i].uid == a.uid) { card = &bc.hand[i]; break; }
            }
        }
        if (card == nullptr) {
            for (int i = 0; i < bc.discardCount; ++i) {
                if (bc.discard[i].uid == a.uid) { card = &bc.discard[i]; break; }
            }
        }
        if (card == nullptr) {
            for (int i = 0; i < bc.drawCount; ++i) {
                if (bc.draw[i].uid == a.uid) { card = &bc.draw[i]; break; }
            }
        }
    }
    const int id = card ? static_cast<int>(card->id) : 0;
    push_one_hot(v, id, static_cast<int>(CardId::COUNT));

    const int potionId = (a.type == ActionType::USE_POTION && a.hand < bc.potionCount)
                             ? bc.potions[a.hand] : 0;
    push_one_hot(v, potionId, POTION_COUNT);

    v.push_back(card ? card_cost(*card) / 3.0f : 0.0f);
    v.push_back(card && card->upgraded ? 1.0f : 0.0f);
    // Replay modifiers decide how many times this exact action resolves.
    v.push_back(card ? card->replay / 4.0f : 0.0f);
    v.push_back(card ? card->bonusReplay / 4.0f : 0.0f);
    v.push_back(card && card->freeCombat ? 1.0f : 0.0f);
    v.push_back(card && card->costThisTurn ? 1.0f : 0.0f);
    v.push_back(std::min<int>(99, card ? card->galvanized : 0) / 10.0f);
    v.push_back(card ? card->bonusDamage / 30.0f : 0.0f);
    v.push_back(card && card->etherealThisCombat ? 1.0f : 0.0f);
    v.push_back(card && card->retainThisCombat ? 1.0f : 0.0f);
    v.push_back(card ? card->combatCostCap / 3.0f : 0.0f);
    v.push_back(card ? card->guiltyCombatsSeen / 5.0f : 0.0f);
    v.push_back(card ? static_cast<int>(card->enchantment) / 5.0f : 0.0f);
    v.push_back(card ? card->enchantmentAmount / 10.0f : 0.0f);
    v.push_back(card && card->enchantmentDisabled ? 1.0f : 0.0f);
    int choiceRank = 0;
    if (a.type == ActionType::CHOOSE && card) {
        choiceRank = 1;
        const auto key = visible_choice_key(*card);
        for (int i = 0; i < bc.pending.count; ++i)
            if (visible_choice_key(bc.pending.cards[i]) < key) ++choiceRank;
    }
    v.push_back(choiceRank / static_cast<float>(MAX_PILE));
    v.push_back(a.hand / 10.0f);
    v.push_back(a.target / 4.0f);
    v.push_back(a.type != ActionType::PLAY_CARD ||
                (a.target < bc.monsterCount && bc.monsters[a.target].alive) ? 1.0f : 0.0f);
    v.push_back(card && card_is_attack(*card)
                    ? std::min(99, card_damage(*card) + bc.player.strength) / 30.0f
                    : 0.0f);
    v.push_back(card && card_is_skill(*card) ? std::min(99, card_block(*card)) / 30.0f : 0.0f);
    v.push_back(fromOffer ? 1.0f : 0.0f);
    v.push_back(a.type == ActionType::CHOOSE ? 1.0f : 0.0f);
    v.push_back(potionId > 0 ? static_cast<int>(potion_def(static_cast<PotionId>(potionId)).usage) / 2.0f : 0.0f);
    v.push_back(potionId > 0 ? static_cast<int>(potion_def(static_cast<PotionId>(potionId)).target) / 3.0f : 0.0f);
    v.push_back(a.type == ActionType::END_TURN ? 1.0f : 0.0f);
    v.push_back(bc.unblockedHitsThisCombat / 10.0f);
    v.push_back(bc.cardsPlayedThisCombat / 10.0f);
    v.push_back(bc.automationCount > 0 ? bc.automationLeft[0] / 10.0f : 0.0f);
    v.push_back(a.target >= 0 && a.target < bc.monsterCount
                    ? bc.monsters[a.target].shellHpLostThisTurn / 30.0f
                    : 0.0f);
    const bool choosing = a.type == ActionType::CHOOSE;
    push_one_hot(v, choosing ? static_cast<int>(bc.pending.op) : 0, PUB_CHOICE_OP_N);
    push_one_hot(v, choosing ? static_cast<int>(bc.pending.pile) : 0, PUB_CHOICE_PILE_N);

    assert(static_cast<int>(v.size()) == ACTION_FEAT_DIM);
    return v;
}

}  // namespace sts2
