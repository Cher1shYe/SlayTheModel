#include "sts2/combat_obs.h"

#include "sts2/observe.h"

#include <algorithm>
#include <stdexcept>

namespace sts2 {
namespace {

class Builder {
public:
    explicit Builder(CombatObservation &out) : out_(out) {}
    int begin(CombatEntity kind, int id) {
        const int index = static_cast<int>(out_.kind.size());
        out_.kind.push_back(static_cast<std::int32_t>(kind));
        out_.id.push_back(id);
        open_ = 0;
        out_.num.resize(out_.num.size() + COMBAT_ENTITY_NUM, 0.0f);
        base_ = out_.num.size() - COMBAT_ENTITY_NUM;
        return index;
    }
    void f(float value) {
        if (open_ >= COMBAT_ENTITY_NUM) throw std::logic_error("combat entity feature overflow");
        out_.num[base_ + open_++] = value;
    }
    void one_hot(int index, int count) {
        for (int i = 0; i < count; ++i) f(i == index ? 1.0f : 0.0f);
    }

private:
    CombatObservation &out_;
    std::size_t base_ = 0;
    int open_ = 0;
};

// Visible card features; same fields as the macro observation's card_numeric plus
// the in-combat instance state. No UID, no pile position.
void card_numeric(Builder &b, const Card &c) {
    const CardDef &d = card_def(c.id);
    const int cost = card_cost(c);
    b.f(cost < 0 ? 1.0f : 0.0f);
    b.f(cost < 0 ? 0.0f : cost / 3.0f);
    b.one_hot(static_cast<int>(card_type(c)), 6);
    b.one_hot(static_cast<int>(d.rarity), 11);
    b.one_hot(static_cast<int>(card_target(c)), 7);
    b.f(c.upgraded ? 1.0f : 0.0f);
    b.f(std::min(99, card_damage(c)) / 30.0f);
    b.f(std::min(99, card_block(c)) / 30.0f);
    b.f(c.replay / 4.0f);
    b.f(c.bonusReplay / 4.0f);
    b.f(c.freeCombat ? 1.0f : 0.0f);
    b.f(c.costThisTurn ? 1.0f : 0.0f);
    b.f(c.costThisTurn ? c.storedCost / 3.0f : 0.0f);
    b.f(c.combatCostCap / 3.0f);
    b.f(static_cast<float>(c.bonusDamage) / 30.0f);
    b.f(c.bonusBlock / 30.0f);
    b.f(c.etherealThisCombat ? 1.0f : 0.0f);
    b.f(c.retainThisCombat ? 1.0f : 0.0f);
    b.f(c.retainThisTurn ? 1.0f : 0.0f);
    b.f(c.slyThisTurn ? 1.0f : 0.0f);
    b.f(c.slyThisCombat ? 1.0f : 0.0f);
    b.f(std::min<int>(99, c.galvanized) / 10.0f);
    b.f(c.guiltyCombatsSeen / 5.0f);
    b.one_hot(static_cast<int>(c.enchantment), static_cast<int>(ENCHANTMENT_LAST) + 1);
    b.f(c.enchantmentAmount / 10.0f);
    b.f(c.enchantmentDisabled ? 1.0f : 0.0f);
    b.f(c.tinkerType / 3.0f);
    b.f(c.tinkerRider / 9.0f);
}
constexpr int CARD_NUMERIC = 2 + 6 + 11 + 7 + 1 + 2 + 2 + 2 + 1 + 2 + 2 + 2 + 3 + 2 + 1 +
                             (static_cast<int>(ENCHANTMENT_LAST) + 1) + 2 + 2;
static_assert(CARD_NUMERIC + 4 <= COMBAT_ENTITY_NUM, "card features plus slot metadata must fit");

std::vector<const Card *> sorted_cards(const Card *cards, int count) {
    std::vector<const Card *> out;
    out.reserve(static_cast<std::size_t>(std::max(0, count)));
    for (int i = 0; i < count; ++i) out.push_back(&cards[i]);
    std::sort(out.begin(), out.end(), [](const Card *a, const Card *b) { return card_canonical_less(*a, *b); });
    return out;
}

}  // namespace

int combat_id_vocab(CombatEntity kind) {
    switch (kind) {
        case CombatEntity::PLAYER: return 1;
        case CombatEntity::ENCOUNTER: return static_cast<int>(Encounter::COUNT);
        case CombatEntity::PLAYER_POWER:
        case CombatEntity::MONSTER_POWER: return static_cast<int>(PowerId::COUNT);
        case CombatEntity::HAND_CARD:
        case CombatEntity::DRAW_CARD:
        case CombatEntity::DISCARD_CARD:
        case CombatEntity::EXHAUST_CARD:
        case CombatEntity::CHOICE_CARD:
        case CombatEntity::ACTIVE_CARD: return static_cast<int>(CardId::COUNT);
        case CombatEntity::MONSTER: return static_cast<int>(MonsterId::COUNT);
        case CombatEntity::POTION: return static_cast<int>(PotionId::COUNT);
        case CombatEntity::RELIC: return static_cast<int>(RelicId::COUNT);
        default: return 0;
    }
}

CombatObservation combat_entity_observation(const BattleContext &bc) {
    CombatObservation out;
    Builder b(out);
    const Player &p = bc.player;
    const auto legal = bc.legal_actions();

    // --- PLAYER --------------------------------------------------------------
    b.begin(CombatEntity::PLAYER, 0);
    b.f(p.maxHp > 0 ? static_cast<float>(p.hp) / p.maxHp : 0.0f);
    b.f(p.hp / 100.0f);
    b.f(p.maxHp / 100.0f);
    b.f(p.block / 50.0f);
    b.f(p.energy / 3.0f);
    b.f(p.energyPerTurn / 3.0f);
    b.f(p.drawPerTurn / 5.0f);
    b.f(p.strength / 10.0f);
    b.f(p.dexterity / 10.0f);
    b.f(p.tempStrength / 10.0f);
    b.f(p.tempDexterity / 10.0f);
    b.f(p.vulnerable / 10.0f);
    b.f(p.weak / 10.0f);
    b.f(p.frail / 10.0f);
    b.f(bc.turn / 20.0f);
    b.f(bc.cardsPlayedThisTurn / 10.0f);
    b.f(bc.attacksPlayedThisTurn / 10.0f);
    b.f(bc.skillsPlayedThisTurn / 10.0f);
    b.f(bc.unblockedHitsThisCombat / 10.0f);
    b.f(bc.cardsPlayedThisCombat / 10.0f);
    b.f(bc.cardsFinishedThisCombat / 10.0f);
    b.f(bc.exhaustedThisTurn / 10.0f);
    b.f(bc.hpLostThisTurn / 100.0f);
    b.f(bc.nextTurnEnergy / 10.0f);
    b.f(bc.nextTurnDraw / 10.0f);
    b.f(bc.attackSkillPlaysThisTurn / 10.0f);
    b.f(bc.blockCardPlaysThisTurn / 10.0f);
    b.f(bc.skillsLocked ? 1.0f : 0.0f);
    b.f(p.tookUnblockedDamageThisTurn ? 1.0f : 0.0f);
    b.f(p.tookUnblockedAttackDamageThisCombat ? 1.0f : 0.0f);
    b.f(p.toricToughnessBlock / 50.0f);
    b.f(p.crimsonMantleSelfDamage / 10.0f);
    b.f(p.infernoSelfDamage / 10.0f);
    b.f(bc.handCount / 10.0f);
    b.f(bc.drawCount / 30.0f);
    b.f(bc.discardCount / 30.0f);
    b.f(bc.exhaustCount / 30.0f);
    b.f(std::min(bc.knownTopCount, bc.drawCount) / 10.0f);
    b.f(bc.potionSlots / 5.0f);
    b.f(bc.potionCount / 5.0f);
    b.f(bc.relicCount / 20.0f);
    b.f(bc.bombCount / 5.0f);
    b.f(bc.automationCount / 5.0f);
    b.f(bc.panacheCount / 5.0f);
    b.f(bc.rollingCount / 5.0f);
    const PendingChoice &pc = bc.pending;
    b.f(pc.op != ChoiceOp::NONE ? 1.0f : 0.0f);
    b.one_hot(static_cast<int>(pc.op), static_cast<int>(ChoiceOp::REGENT_AUTO_SKILL) + 1);
    b.one_hot(static_cast<int>(pc.pile), 5);
    b.f(pc.remaining / 10.0f);
    b.f(pc.count / 10.0f);
    b.f(pc.optional ? 1.0f : 0.0f);
    b.f(pc.payload / 5.0f);
    b.f(pc.hasSource ? 1.0f : 0.0f);
    b.f(pc.sourceExhaust ? 1.0f : 0.0f);
    const ActivePlay &play = bc.activePlay;
    b.f(play.active ? 1.0f : 0.0f);
    b.f(play.active ? play.target / 4.0f : 0.0f);
    b.f(play.active ? play.playCount / 10.0f : 0.0f);
    b.f(play.active ? play.nextPlay / 10.0f : 0.0f);
    b.f(play.active && play.autoPlay ? 1.0f : 0.0f);
    b.f(play.active ? play.energySpent / 3.0f : 0.0f);
    int incoming = 0;
    for (int i = 0; i < bc.monsterCount; ++i)
        if (bc.monsters[i].alive && bc.monsters[i].intentType == 0)
            incoming += bc.monsters[i].intentDamage * std::max(1, bc.monsters[i].intentHits);
    b.f(incoming / 50.0f);
    b.f(std::max(0, incoming - p.block) / 50.0f);

    b.begin(CombatEntity::ENCOUNTER, static_cast<int>(bc.encounter));
    b.f(1.0f);

    // --- player powers --------------------------------------------------------
    for (int k = 0; k < static_cast<int>(PowerId::COUNT); ++k) {
        if (p.power[k] == 0) continue;
        b.begin(CombatEntity::PLAYER_POWER, k);
        b.f(p.power[k] / 10.0f);
        b.f(p.power[k] > 0 ? 1.0f : -1.0f);
    }

    // --- hand -------------------------------------------------------------------
    std::vector<int> handEntity(static_cast<std::size_t>(bc.handCount), -1);
    for (int i = 0; i < bc.handCount; ++i) {
        const Card &c = bc.hand[i];
        handEntity[static_cast<std::size_t>(i)] = b.begin(CombatEntity::HAND_CARD, static_cast<int>(c.id));
        card_numeric(b, c);
        bool playable = false;
        for (const Action &a : legal)
            playable |= a.type == ActionType::PLAY_CARD && a.hand == i;
        b.f(playable ? 1.0f : 0.0f);
        b.f(bc.energy_cost_in_combat(c) / 3.0f);
        b.f(i / 10.0f);
    }

    // --- piles ------------------------------------------------------------------
    const int known = std::min(bc.knownTopCount, bc.drawCount);
    for (int k = 0; k < known; ++k) {
        const Card &c = bc.draw[bc.drawCount - 1 - k];
        b.begin(CombatEntity::DRAW_CARD, static_cast<int>(c.id));
        card_numeric(b, c);
        b.f(1.0f);
        b.f((k + 1) / 10.0f);
    }
    for (const Card *c : sorted_cards(bc.draw, bc.drawCount - known)) {
        b.begin(CombatEntity::DRAW_CARD, static_cast<int>(c->id));
        card_numeric(b, *c);
        b.f(0.0f);
        b.f(0.0f);
    }
    for (const Card *c : sorted_cards(bc.discard, bc.discardCount)) {
        b.begin(CombatEntity::DISCARD_CARD, static_cast<int>(c->id));
        card_numeric(b, *c);
    }
    for (const Card *c : sorted_cards(bc.exhaust, bc.exhaustCount)) {
        b.begin(CombatEntity::EXHAUST_CARD, static_cast<int>(c->id));
        card_numeric(b, *c);
    }
    std::vector<std::pair<std::uint16_t, int>> choiceEntity;
    for (const Card *c : sorted_cards(pc.cards, pc.count)) {
        choiceEntity.emplace_back(c->uid, b.begin(CombatEntity::CHOICE_CARD, static_cast<int>(c->id)));
        card_numeric(b, *c);
    }
    if (play.active) {
        b.begin(CombatEntity::ACTIVE_CARD, static_cast<int>(play.card.id));
        card_numeric(b, play.card);
    }

    // --- monsters ---------------------------------------------------------------
    std::vector<int> monsterEntity(MAX_MONSTERS, -1);
    for (int i = 0; i < bc.monsterCount; ++i) {
        const Monster &m = bc.monsters[i];
        monsterEntity[static_cast<std::size_t>(i)] = b.begin(CombatEntity::MONSTER, static_cast<int>(m.id));
        b.f(m.alive ? 1.0f : 0.0f);
        b.f(m.maxHp > 0 ? static_cast<float>(m.hp) / m.maxHp : 0.0f);
        b.f(m.hp / 200.0f);
        b.f(m.maxHp / 200.0f);
        b.f(m.block / 50.0f);
        b.f(m.strength / 10.0f);
        b.f(m.vulnerable / 10.0f);
        b.f(m.weak / 10.0f);
        b.f(m.intentDamage / 50.0f);
        b.f(m.intentHits / 5.0f);
        b.f(m.intentType == 0 ? m.intentDamage * std::max(1, m.intentHits) / 50.0f : 0.0f);
        b.one_hot(std::min<int>(m.intentType, 9), 10);
        b.f(m.reviving ? 1.0f : 0.0f);
        b.f(m.shellHpLostThisTurn / 30.0f);
        for (int k = 0; k < 4; ++k) b.f(m.aux[k] / 5.0f);
        b.f(m.offBalance ? 1.0f : 0.0f);
        b.f(m.stunned ? 1.0f : 0.0f);
        b.f(m.slowCardsThisTurn / 10.0f);
        b.f(m.tempStrengthLoss / 10.0f);
        b.f(m.nemesisIntangible ? 1.0f : 0.0f);
        b.f(m.combatEndBlocker ? 1.0f : 0.0f);
        b.f(m.skittishTriggeredThisTurn ? 1.0f : 0.0f);
        b.f(m.stolenGold / 100.0f);
        b.f(m.steamEruptionDamage / 50.0f);
        b.f(m.grappleCount / 10.0f);
        b.one_hot(i, MAX_MONSTERS);
    }
    for (int i = 0; i < bc.monsterCount; ++i) {
        const Monster &m = bc.monsters[i];
        for (int k = 0; k < static_cast<int>(PowerId::COUNT); ++k) {
            if (m.power[k] == 0) continue;
            b.begin(CombatEntity::MONSTER_POWER, k);
            b.f(m.power[k] / 10.0f);
            b.f(m.power[k] > 0 ? 1.0f : -1.0f);
            b.one_hot(i, MAX_MONSTERS);
        }
    }

    // --- potions and relics -------------------------------------------------------
    std::vector<int> potionEntity(MAX_POTIONS, -1);
    for (int i = 0; i < bc.potionSlots && i < MAX_POTIONS; ++i) {
        const int id = bc.potions[i];
        potionEntity[static_cast<std::size_t>(i)] = b.begin(CombatEntity::POTION, id);
        b.f(i / 10.0f);
        b.f(id > 0 && bc.can_use_potion(i) ? 1.0f : 0.0f);
        if (id > 0) b.one_hot(static_cast<int>(potion_def(static_cast<PotionId>(id)).target), 4);
    }
    for (int i = 0; i < bc.relicCount && i < MAX_RELICS; ++i) {
        b.begin(CombatEntity::RELIC, bc.relics[i]);
        b.f(bc.relicAux[i] / 10.0f);
        b.f(bc.relicWax[i] ? 1.0f : 0.0f);
        b.f(bc.relicMelted[i] ? 1.0f : 0.0f);
    }

    // --- candidates -------------------------------------------------------------
    for (const Action &a : legal) {
        int t1 = -1, t2 = -1;
        float enemyTarget = 0.0f, cost = 0.0f;
        switch (a.type) {
            case ActionType::PLAY_CARD:
                if (a.hand < bc.handCount) {
                    t1 = handEntity[a.hand];
                    cost = bc.energy_cost_in_combat(bc.hand[a.hand]) / 3.0f;
                    if (card_target(bc.hand[a.hand]) == TargetType::ENEMY && a.target < bc.monsterCount) {
                        t2 = monsterEntity[a.target];
                        enemyTarget = 1.0f;
                    }
                }
                break;
            case ActionType::USE_POTION:
                if (a.hand < MAX_POTIONS) {
                    t1 = potionEntity[a.hand];
                    const int id = bc.potions[a.hand];
                    if (id > 0 && potion_def(static_cast<PotionId>(id)).target == PotionTarget::ANY_ENEMY &&
                        a.target < bc.monsterCount) {
                        t2 = monsterEntity[a.target];
                        enemyTarget = 1.0f;
                    }
                }
                break;
            case ActionType::CHOOSE:
                for (const auto &e : choiceEntity)
                    if (e.first == a.uid) { t1 = e.second; break; }
                break;
            default:
                break;
        }
        out.candType.push_back(static_cast<std::int32_t>(a.type));
        out.candTarget.push_back(t1);
        out.candTarget2.push_back(t2);
        out.candNum.push_back(enemyTarget);
        out.candNum.push_back(cost);
        out.candNum.push_back(t1 >= 0 ? 1.0f : 0.0f);
        out.candNum.push_back(0.0f);
    }
    return out;
}

}  // namespace sts2
