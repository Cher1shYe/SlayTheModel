#include "sts2/observe.h"

namespace sts2 {

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

std::vector<float> combat_action_features(const BattleContext &bc, const Action &a) {
    std::vector<float> v;
    v.reserve(ACTION_FEAT_DIM);
    for (int i = 0; i < 4; ++i) v.push_back(static_cast<int>(a.type) == i ? 1.0f : 0.0f);

    const Card *card = nullptr;
    if (a.type == ActionType::PLAY_CARD && a.hand < bc.handCount) {
        card = &bc.hand[a.hand];
    } else if (a.type == ActionType::CHOOSE) {
        for (int i = 0; i < bc.handCount; ++i) {
            if (bc.hand[i].uid == a.uid) { card = &bc.hand[i]; break; }
        }
    }
    const int id = card ? static_cast<int>(card->id) : 0;
    for (int i = 0; i < static_cast<int>(CardId::COUNT); ++i) v.push_back(i == id ? 1.0f : 0.0f);

    v.push_back(card ? card_cost(*card) / 3.0f : 0.0f);
    v.push_back(card && card->upgraded ? 1.0f : 0.0f);
    v.push_back(a.hand / 10.0f);
    v.push_back(a.target / 4.0f);
    v.push_back(a.type == ActionType::PLAY_CARD &&
                a.target < bc.monsterCount && bc.monsters[a.target].alive ? 1.0f : 0.0f);
    v.push_back(card && card_is_attack(*card)
                    ? std::min(99, card_damage(*card) + bc.player.strength + bc.player.tempStrength) / 30.0f
                    : 0.0f);
    v.push_back(card && card_is_skill(*card) ? std::min(99, card_block(*card)) / 30.0f : 0.0f);
    return v;
}

}  // namespace sts2
