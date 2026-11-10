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
    for(int i=0;i<c.costModifierCount;++i)
        if(c.costModifiers[i].absolute && c.costModifiers[i].amount>d.costUp && d.costUp<d.cost)
            c.costModifiers[i].amount=d.costUp;
    c.storedCost = d.costUp;
    if (!c.costThisTurn) c.costForTurn = d.costUp;
}

void card_apply_downgrade(Card &c) {
    // Used by deck-event downgrades. Native CardModel.DowngradeInternal resets
    // the canonical base cost and keywords, keeping the card instance and the
    // local cost modifiers (Snecko, Frantic Escape, free-this-combat ... on
    // the per-card stack), which apply on top of the restored base.
    // Damage/vars/printed keywords are selected from CardDef by upgraded;
    // the supported growth cards restore their accumulated bonus on downgrade.
    c.upgraded = false;
    const CardDef &d = card_def(c.id);
    c.storedCost = d.cost;
    if (!c.costThisTurn) c.costForTurn = d.cost;
    c.etherealThisCombat = false;
    c.retainThisCombat = false;
    // Enchantments, afflictions, replay and cost modifiers survive. Steady's
    // Retain is reapplied by card_has rather than stored as a temporary keyword.
}

bool card_upgradable(const Card &c) {
    if (c.upgraded) return false;
    return card_def(c.id).maxUpgradeLevel > 0;

}

int card_cost(const Card &c) {
    int value = c.costForTurn;
    if (value < 0) return value;
    if (c.combatCostCap >= 0) value = std::min(value, int(c.combatCostCap));
    for (int i=0;i<c.costModifierCount;++i) {
        const auto &m=c.costModifiers[i];
        const int next=m.absolute?m.amount:value+m.amount;
        value=m.reduceOnly?std::min(value,next):next;
    }
    return std::max(0,value);
}

void card_modify_cost(Card &c,int amount,bool absolute,std::uint8_t expiration,bool reduceOnly) {
    if((expiration & ~6u)!=0) throw std::invalid_argument("Unknown native cost expiration");
    if(!absolute && amount==0) return;
    if(absolute && amount==0 && card_def(c.id).cost<0) return;
    // A combat-long, unconditional absolute modifier overrides every earlier
    // entry for the rest of the combat, so dropping them is exact (keeps
    // per-draw Snecko re-rolls within capacity).
    if(absolute && !reduceOnly && expiration==0) {
        for(int i=0;i<c.costModifierCount;++i)c.costModifiers[i]=CardCostModifier{};
        c.costModifierCount=0;
    }
    // Adjacent relative modifiers with identical expiry commute and can be
    // merged exactly; never clamp intermediate local costs to zero.
    if(!absolute && c.costModifierCount>0) {
        auto &last=c.costModifiers[c.costModifierCount-1];
        if(!last.absolute && last.expiration==expiration && last.reduceOnly==reduceOnly) {
            last.amount+=reduceOnly?std::min(0,amount):amount; return;
        }
    }
    if(c.costModifierCount==MAX_CARD_COST_MODIFIERS)
        throw std::overflow_error("Card cost modifier capacity exhausted");
    c.costModifiers[c.costModifierCount++]={reduceOnly && !absolute?std::min(0,amount):amount,
                                         expiration,absolute,reduceOnly};
}

void card_clear_cost_modifiers(Card &c,std::uint8_t expiration) {
    int keep=0;
    for(int i=0;i<c.costModifierCount;++i)
        if(!(c.costModifiers[i].expiration & expiration)) c.costModifiers[keep++]=c.costModifiers[i];
    for(int i=keep;i<c.costModifierCount;++i)c.costModifiers[i]=CardCostModifier{};
    c.costModifierCount=keep;
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
    return (c.upgraded ? d.blockUp : d.block) + c.bonusBlock;
}

int card_var(const Card &c, VarId v) {
    const CardDef &d = card_def(c.id);
    const int i = static_cast<int>(v);
    return c.upgraded ? d.varUp[i] : d.var[i];
}

bool card_has(const Card &c, std::uint16_t flag) {
    if (flag == CF_RETAIN && (c.retainThisTurn || c.retainThisCombat || c.enchantment == EnchantmentId::STEADY)) return true;
    if (flag == CF_SLY && (c.slyThisTurn || c.slyThisCombat)) return true;
    // CardCmd.ApplyKeyword(Ethereal): Ghost Seed, Music Box clones, Sculpting Strike.
    if (flag == CF_ETHEREAL && c.etherealThisCombat) return true;
    // SoulsPower.OnEnchant removes the card's own Exhaust keyword.
    if (flag == CF_EXHAUST && c.enchantment == EnchantmentId::SOULS_POWER) return false;
    const CardDef &d = card_def(c.id);
    const std::uint16_t f = c.upgraded ? d.flagsUp : d.flags;
    return (f & flag) != 0;
}

CardType card_type(const Card &c) {
    if (c.id == CardId::MAD_SCIENCE && c.tinkerType)
        return c.tinkerType == 2 ? CardType::SKILL : c.tinkerType == 3 ? CardType::POWER : CardType::ATTACK;
    return card_def(c.id).type;
}

TargetType card_target(const Card &c) {
    if (c.id == CardId::MAD_SCIENCE)
        return card_type(c) == CardType::ATTACK ? TargetType::ENEMY : TargetType::SELF;
    return card_def(c.id).target;
}

bool card_is_attack(const Card &c) { return card_type(c) == CardType::ATTACK; }
bool card_is_skill(const Card &c) { return card_type(c) == CardType::SKILL; }
bool card_is_power(const Card &c) { return card_type(c) == CardType::POWER; }

bool card_is_playable(const Card &c) {
    // Playability is data-driven: several status/curse cards (Slimed, Toxic,
    // Magic Flower ...) are playable and only a flagged subset is not.
    return card_native_available(c.id) && !card_has(c, CF_UNPLAYABLE);
}

bool card_native_available(CardId id) {
    // GRAPPLE is a reserved legacy slot. The target DLL's ModelDb.AllCards has
    // no corresponding card; keeping its enum preserves serialized identities.
    return id > CardId::INVALID && id < CardId::COUNT && id != CardId::GRAPPLE;
}

bool card_can_enchant(const Card &c, EnchantmentId enchantment) {
    if (c.enchantment != EnchantmentId::NONE || c.id == CardId::INVALID ||
        !card_is_playable(c)) return false;
    const CardType type = card_type(c);
    if (type == CardType::CURSE || type == CardType::STATUS || type == CardType::QUEST) return false;
    if (enchantment == EnchantmentId::SOWN || enchantment == EnchantmentId::SWIFT ||
        enchantment == EnchantmentId::INKY ||
        enchantment == EnchantmentId::GLAM || enchantment == EnchantmentId::CLONE ||
        enchantment == EnchantmentId::STEADY) return true;
    if (enchantment == EnchantmentId::SPIRAL)
        return card_def(c.id).rarity == Rarity::BASIC && (card_is_strike(c) || card_is_defend(c));
    if (enchantment == EnchantmentId::PERFECT_FIT) return true;
    if (enchantment == EnchantmentId::CORRUPTED || enchantment == EnchantmentId::SHARP)
        return type == CardType::ATTACK;
    if (enchantment == EnchantmentId::IMBUED) return type == CardType::SKILL;  // Imbued.CanEnchantCardType
    // SoulsPower: the card's own (Local) keywords include Exhaust.
    if (enchantment == EnchantmentId::SOULS_POWER) {
        const CardDef &d = card_def(c.id);
        return ((c.upgraded ? d.flagsUp : d.flags) & CF_EXHAUST) != 0;
    }
    // Slither.CanEnchant: also not Unplayable and not an X cost.
    if (enchantment == EnchantmentId::SLITHER)
        return (c.upgraded ? card_def(c.id).costUp : card_def(c.id).cost) >= 0;
    if (enchantment == EnchantmentId::NIMBLE) {
        if (c.id == CardId::MAD_SCIENCE) return card_type(c) == CardType::SKILL;  // GainsBlock
        // Native CardModel.GainsBlock for the compiled card pool (not only a
        // positive static BlockVar: Stack and Fisticuffs compute block on play).
        switch (c.id) {
#include "sts2/native_block_cards.inc"
            return true;
            default: return false;
        }
    }
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
