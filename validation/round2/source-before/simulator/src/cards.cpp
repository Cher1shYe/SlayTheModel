#include "sts2/common.h"

namespace sts2 {

#include "sts2/cards_generated.inc"

const CardDef &card_def(CardId id) {
    const int i = static_cast<int>(id);
    if (i <= 0 || i >= static_cast<int>(CardId::COUNT)) return CARD_DEFS[0];
    return CARD_DEFS[i];
}

Card make_card(CardId id, bool upgraded, std::uint16_t uid) {
    const CardDef &d = card_def(id);
    Card c;
    c.id = id;
    c.uid = uid;
    c.upgraded = upgraded;
    c.costForTurn = upgraded ? d.costUp : d.cost;
    c.storedCost = c.costForTurn;
    c.bonusDamage = 0;
    c.replay = 0;
    return c;
}

void card_apply_upgrade(Card &c) {
    if (c.upgraded) return;
    c.upgraded = true;
    const CardDef &d = card_def(c.id);
    c.storedCost = d.costUp;
    if (!c.costThisTurn) c.costForTurn = d.costUp;
}

bool card_upgradable(const Card &c) {
    if (c.upgraded) return false;
    const CardDef &d = card_def(c.id);
    if (d.damageUp != d.damage || d.blockUp != d.block ||
        d.costUp != d.cost || d.flagsUp != d.flags) {
        return true;
    }
    for (int i = 0; i < static_cast<int>(VarId::COUNT); ++i) {
        if (d.varUp[i] != d.var[i]) return true;
    }
    return false;
}

int card_cost(const Card &c) {
    if (c.freeCombat) return 0;
    if (c.combatCostCap >= 0 && c.costForTurn >= 0) {
        return std::min<int>(c.costForTurn, c.combatCostCap);
    }
    return c.costForTurn;
}

int card_damage(const Card &c) {
    return static_cast<int>(std::floor(card_base_damage(c)));
}

double card_base_damage(const Card &c) {
    const CardDef &d = card_def(c.id);
    return (c.upgraded ? d.damageUp : d.damage) + c.bonusDamage;
}

int card_block(const Card &c) {
    const CardDef &d = card_def(c.id);
    return c.upgraded ? d.blockUp : d.block;
}

int card_var(const Card &c, VarId v) {
    const CardDef &d = card_def(c.id);
    const int i = static_cast<int>(v);
    return c.upgraded ? d.varUp[i] : d.var[i];
}

bool card_has(const Card &c, std::uint16_t flag) {
    if (flag == CF_RETAIN && c.retainThisCombat) return true;
    const CardDef &d = card_def(c.id);
    const std::uint16_t f = c.upgraded ? d.flagsUp : d.flags;
    return (f & flag) != 0;
}

bool card_is_attack(const Card &c) { return card_def(c.id).type == CardType::ATTACK; }
bool card_is_skill(const Card &c) { return card_def(c.id).type == CardType::SKILL; }
bool card_is_power(const Card &c) { return card_def(c.id).type == CardType::POWER; }

bool card_is_playable(const Card &c) {
    // Playability is data-driven: several status/curse cards (Slimed, Toxic,
    // Magic Flower ...) are playable and only a flagged subset is not.
    return !card_has(c, CF_UNPLAYABLE);
}

bool card_can_enchant(const Card &c, EnchantmentId enchantment) {
    if (c.enchantment != EnchantmentId::NONE || c.id == CardId::INVALID ||
        !card_is_playable(c)) return false;
    const CardType type = card_def(c.id).type;
    if (type == CardType::CURSE || type == CardType::STATUS) return false;
    if (enchantment == EnchantmentId::SOWN || enchantment == EnchantmentId::SWIFT ||
        enchantment == EnchantmentId::GLAM || enchantment == EnchantmentId::CLONE) return true;
    return enchantment == EnchantmentId::VIGOROUS && type == CardType::ATTACK;
}

bool card_apply_enchantment(Card &c, EnchantmentId enchantment, int amount) {
    if (amount <= 0 || amount > 32767 || !card_can_enchant(c, enchantment)) return false;
    c.enchantment = enchantment;
    c.enchantmentAmount = static_cast<std::int16_t>(amount);
    c.enchantmentDisabled = false;
    return true;
}

bool card_is_strike(const Card &c) { return card_has(c, CF_STRIKE); }
bool card_is_defend(const Card &c) { return card_has(c, CF_DEFEND); }

const char *card_name(CardId id) { return card_def(id).name; }
const char *card_key(CardId id) { return card_def(id).key; }

}  // namespace sts2
