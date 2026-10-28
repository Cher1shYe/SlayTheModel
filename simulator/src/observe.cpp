#include "sts2/observe.h"

#include <cassert>

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
    v.push_back(p.vulnerable / 10.0f);
    v.push_back(p.weak / 10.0f);
    v.push_back(p.frail / 10.0f);
    v.push_back(bc.turn / 20.0f);
    for (int i = 0; i < POWER_COUNT; ++i) v.push_back(p.power[i] / 10.0f);

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
    push_card_bag(v, bc.draw, bc.drawCount);
    push_card_bag(v, bc.discard, bc.discardCount);
    push_card_bag(v, bc.exhaust, bc.exhaustCount);

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
        for (int k = 0; k < POWER_COUNT; ++k) v.push_back(m.power[k] / 10.0f);
        for (int k = 0; k < 4; ++k) v.push_back(m.aux[k] / 5.0f);
    }

    // Pending choice candidates (may come from hand, draw, discard or offers).
    v.push_back(bc.pending.op != ChoiceOp::NONE ? 1.0f : 0.0f);
    for (int i = 0; i < MAX_HAND; ++i) {
        if (i < bc.pending.count) {
            const auto feat = card_features(bc.pending.cards[i], -1);
            v.insert(v.end(), feat.begin(), feat.end());
            v.push_back(1.0f);
        } else {
            v.insert(v.end(), CARD_FEAT_DIM + 1, 0.0f);
        }
    }
    v.push_back(bc.pending.remaining / 10.0f);
    v.push_back(bc.pending.count / 10.0f);
    v.push_back(bc.pending.optional ? 1.0f : 0.0f);
    v.push_back(bc.pending.payload / 5.0f);

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
    v.push_back(rc.gold / 300.0f);
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

    // --- screen one-hot -----------------------------------------------------
    const int screen = static_cast<int>(rc.screen);
    for (int i = 0; i < PUB_SCREENS; ++i) v.push_back(screen == i ? 1.0f : 0.0f);

    // --- deck ---------------------------------------------------------------
    push_card_bag(v, rc.deck, rc.deckCount);

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
    }

    // --- map ----------------------------------------------------------------
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
    }
    for (int i = 0; i < 4; ++i) v.push_back(rc.eventData[i] / 100.0f);

    // --- card reward --------------------------------------------------------
    for (int i = 0; i < PUB_CARD_REWARD_N; ++i) {
        const bool exists = i < rc.offeredCount;
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
    v.push_back(a.hand / 10.0f);
    v.push_back(a.target / 4.0f);
    v.push_back(a.type != ActionType::PLAY_CARD ||
                (a.target < bc.monsterCount && bc.monsters[a.target].alive) ? 1.0f : 0.0f);
    v.push_back(card && card_is_attack(*card)
                    ? std::min(99, card_damage(*card) + bc.player.strength + bc.player.tempStrength) / 30.0f
                    : 0.0f);
    v.push_back(card && card_is_skill(*card) ? std::min(99, card_block(*card)) / 30.0f : 0.0f);
    v.push_back(fromOffer ? 1.0f : 0.0f);
    v.push_back(a.type == ActionType::CHOOSE ? 1.0f : 0.0f);
    v.push_back(potionId > 0 ? static_cast<int>(potion_def(static_cast<PotionId>(potionId)).usage) / 2.0f : 0.0f);
    v.push_back(potionId > 0 ? static_cast<int>(potion_def(static_cast<PotionId>(potionId)).target) / 3.0f : 0.0f);
    v.push_back(a.type == ActionType::END_TURN ? 1.0f : 0.0f);

    assert(static_cast<int>(v.size()) == ACTION_FEAT_DIM);
    return v;
}

}  // namespace sts2
