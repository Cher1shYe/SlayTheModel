#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
#include "sts2/silent.h"
#include "sts2/defect.h"
#include "sts2/necrobinder.h"
namespace sts2 {
int &power_ref(Player &,PowerId);
int &power_ref(Monster &,PowerId);
static bool power_allows_negative(PowerId id) {
    switch(id) {
        case PowerId::DEXTERITY:
        case PowerId::FOCUS:
        case PowerId::SHRIEK:
        case PowerId::SHRINK:
        case PowerId::STRENGTH:
            return true;
        default:return false;
    }
}
static bool power_is_debuff(PowerId id,int amount) {
    if(amount<0&&power_allows_negative(id))return true;
    if(amount<0)return false;
    switch(id) {
        case PowerId::BIASED_COGNITION:
        case PowerId::BORROWED_TIME:
        case PowerId::CHAINS_OF_BINDING:
        case PowerId::CONFUSED:
        case PowerId::CONQUEROR:
        case PowerId::CONSTRICT:
        case PowerId::CRUSH_UNDER:
        case PowerId::DAMPEN:
        case PowerId::DARK_SHACKLES:
        case PowerId::DEBILITATE:
        case PowerId::DEMISE:
        case PowerId::DISINTEGRATION:
        case PowerId::DOOM:
        case PowerId::DYING_STAR:
        case PowerId::ENFEEBLING_TOUCH:
        case PowerId::FLANKING:
        case PowerId::FRAIL:
        case PowerId::HANG:
        case PowerId::HEX:
        case PowerId::HYPERBEAM_FOCUS_DOWN:
        case PowerId::IMBALANCED:
        case PowerId::KNOCKDOWN:
        case PowerId::MAGIC_BOMB:
        case PowerId::MANGLE_POW:
        case PowerId::MIND_ROT:
        case PowerId::MONARCHS_GAZE_STRENGTH_DOWN:
        case PowerId::NEUROSURGE:
        case PowerId::NO_BLOCK:
        case PowerId::NO_DRAW:
        case PowerId::NO_ENERGY_GAIN:
        case PowerId::OBLIVION:
        case PowerId::PIERCING_WAIL:
        case PowerId::PLOW:
        case PowerId::POISON:
        case PowerId::RINGING:
        case PowerId::SHACKLING_POTION:
        case PowerId::SHRIEK:
        case PowerId::SHRINK:
        case PowerId::SIC_EM:
        case PowerId::SLOTH:
        case PowerId::SLOW:
        case PowerId::SMOGGY:
        case PowerId::STRANGLE:
        case PowerId::SURROUNDED:
        case PowerId::TAG_TEAM:
        case PowerId::TAINTED:
        case PowerId::TANGLED:
        case PowerId::TENDER:
        case PowerId::THE_GAMBIT:
        case PowerId::VULNERABLE:
        case PowerId::WASTE_AWAY:
        case PowerId::WEAK:
        case PowerId::WRAITH_FORM:
            return true;
        default:return false;
    }
}
static bool power_visible(PowerId id) {
    switch(id) {
        case PowerId::AMBERGRIS:
            return false;
        default:return true;
    }
}
static int power_new_amount(PowerId id,int before,int delta) {
    const auto sum=std::clamp(static_cast<long long>(before)+delta,-999999999LL,999999999LL);
    return static_cast<int>(power_allows_negative(id)?sum:std::max(0LL,sum));
}

void BattleContext::add_player_power(PowerId id, int amount) {
    if(amount==0)return;
    const int previousAmount = player_power(id);
    // ArtifactPower.TryModifyPowerAmountReceived: any visible Debuff applied to
    // the owner is zeroed and consumes one Artifact charge.
    if (power_is_debuff(id,amount) && power_visible(id) && player_power(PowerId::ARTIFACT) > 0) {
        add_player_power(PowerId::ARTIFACT, -1);
        return;
    }
    // PowerCmd.Apply: a Debuff applied to a player skips its first duration
    // tick (WeakPower/FrailPower/VulnerablePower.AfterTurnEnd -> TickDownDuration).
    if (amount > 0 && power_is_debuff(id,amount)) {
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
    power_ref(player,id)=power_new_amount(id,previousAmount,amount);
    const int accepted=player_power(id)-previousAmount;
    defect_power_changed(*this,id,accepted);
    necrobinder_after_power_changed(*this,-1,id,accepted,!inMonsterTurn);
    // Native stores these values on the PowerModel, independently of Amount.
    // Only the card's successful OnPlay increments SelfDamage; raw Apply does
    // not. Removing and later reapplying a power creates a fresh instance.
    if (id == PowerId::CRIMSON_MANTLE) {
        if (previousAmount <= 0 || player_power(id) <= 0)
            player.crimsonMantleSelfDamage = 0;
        if (previousAmount <= 0 && player_power(id) > 0)
            player.infernoBeforeCrimsonMantle = player_power(PowerId::INFERNO) > 0;
        else if (player_power(id) <= 0)
            player.infernoBeforeCrimsonMantle = false;
    } else if (id == PowerId::INFERNO) {
        if (previousAmount <= 0 || player_power(id) <= 0)
            player.infernoSelfDamage = 0;
        if (previousAmount <= 0 || player_power(id) <= 0)
            player.infernoBeforeCrimsonMantle = false;
    }
}

void BattleContext::add_monster_power(int idx, PowerId id, int amount) {
    if (idx < 0 || idx >= monsterCount || !monsters[idx].alive || monsters[idx].hp<=0 || amount==0) return;
    const int previousAmount=monster_power(idx,id);
    // Monster-side Artifact (beetle shrink, potions, ...).
    if (power_is_debuff(id,amount) && power_visible(id) &&
        monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)] > 0) {
        --monsters[idx].power[static_cast<int>(PowerId::ARTIFACT)];
        return;
    }
    if (id == PowerId::GRAPPLE && amount > 0 && monsters[idx].grappleCount < MAX_PILE) {
        Monster &monster = monsters[idx];
        monster.grappleAmounts[monster.grappleCount++] = amount;
    }
    power_ref(monsters[idx],id)=power_new_amount(id,previousAmount,amount);
    necrobinder_after_power_changed(*this,idx,id,monster_power(idx,id)-previousAmount,!inMonsterTurn);
    if (id == PowerId::ILLUSION && amount > 0) {
        monsters[idx].power[static_cast<int>(PowerId::MINION)] = 1;
    }
}
}
