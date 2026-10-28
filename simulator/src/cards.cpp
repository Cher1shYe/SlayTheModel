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

int card_cost(const Card &c) { return c.freeCombat ? 0 : c.costForTurn; }

int card_damage(const Card &c) {
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
    return (card_def(c.id).flags & flag) != 0;
}

bool card_is_attack(const Card &c) { return card_def(c.id).type == CardType::ATTACK; }
bool card_is_skill(const Card &c) { return card_def(c.id).type == CardType::SKILL; }
bool card_is_power(const Card &c) { return card_def(c.id).type == CardType::POWER; }

bool card_is_playable(const Card &c) {
    if (card_has(c, CF_UNPLAYABLE)) return false;
    if (card_def(c.id).type == CardType::STATUS || card_def(c.id).type == CardType::CURSE) return false;
    return true;
}

bool card_is_strike(const Card &c) { return card_has(c, CF_STRIKE); }
bool card_is_defend(const Card &c) { return card_has(c, CF_DEFEND); }

const char *card_name(CardId id) { return card_def(id).name; }
const char *card_key(CardId id) { return card_def(id).key; }

}  // namespace sts2
