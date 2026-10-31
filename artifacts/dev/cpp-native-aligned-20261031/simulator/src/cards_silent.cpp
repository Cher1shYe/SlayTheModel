#include "sts2/silent.h"
#include <algorithm>

namespace sts2 {
namespace {
int var(const Card &c, VarId v) { return card_var(c,v); }
bool alive(const BattleContext &b,int i) { return i>=0&&i<b.monsterCount&&b.monsters[i].alive; }
void poison(BattleContext &b,int i,int n) { if(alive(b,i)&&n>0)b.add_monster_power(i,PowerId::POISON,n); }
void block(BattleContext &b,Card &c) {
    int amount=card_block(c);
    if(card_is_defend(c))amount+=b.player_power(PowerId::FASTEN);
    b.gain_block(amount,true);
}
void choose_discard(BattleContext &b,const Card &c,int n) {
    if(b.handCount<=0||n<=0)return;
    if(n>=b.handCount){Card selected[MAX_HAND];const int count=b.handCount;std::copy(b.hand,b.hand+count,selected);b.discard_cards(selected,count,0);return;}
    b.start_choice(ChoiceOp::SILENT_DISCARD,ChoicePile::HAND,n,false,c,b.card_will_exhaust(c));
}
void draw_then_discard(BattleContext &b,Card &c,int draw,int discard) {
    b.activePlay.silent.stage=1;b.activePlay.silent.amount=discard;
    b.draw_cards(draw);
}
void discard_whole_hand(BattleContext &b,int drawAfter) {
    Card cards[MAX_HAND];const int n=b.handCount;
    std::copy(b.hand,b.hand+n,cards);b.discard_cards(cards,n,drawAfter);
}
}

bool silent_effect(BattleContext &b,Card &c,int target) {
    const double damage=card_base_damage(c);
    const auto hit=[&](double amount,int hits=1){return b.attack_from_card(c,target,amount,hits);};
    const auto all=[&](double amount,int hits=1){b.attack_all_from_card(c,amount,hits);};
    const auto power=[&](PowerId id,int amount){b.add_player_power(id,amount);};
    switch(c.id) {
    case CardId::ABRASIVE: power(PowerId::DEXTERITY,var(c,VarId::DEXTERITY_POWER));power(PowerId::THORNS,var(c,VarId::THORNS_POWER));return true;
    case CardId::ACCELERANT: power(PowerId::ACCELERANT,var(c,VarId::ACCELERANT));return true;
    case CardId::ACCURACY: power(PowerId::ACCURACY,var(c,VarId::ACCURACY_POWER));return true;
    case CardId::ACROBATICS: draw_then_discard(b,c,var(c,VarId::CARDS),1);return true;
    case CardId::ADRENALINE: b.player.energy+=var(c,VarId::ENERGY);b.draw_cards(var(c,VarId::CARDS));return true;
    case CardId::AFTERIMAGE: power(PowerId::AFTERIMAGE,var(c,VarId::AFTERIMAGE_POWER));return true;
    case CardId::ANTICIPATE:
        power(PowerId::DEXTERITY,var(c,VarId::DEXTERITY_POWER));power(PowerId::ANTICIPATE,var(c,VarId::DEXTERITY_POWER));return true;
    case CardId::ASSASSINATE: hit(damage);if(alive(b,target))b.apply_vulnerable(target,var(c,VarId::VULNERABLE_POWER));return true;
    case CardId::BACKFLIP: block(b,c);b.draw_cards(var(c,VarId::CARDS));return true;
    case CardId::BACKSTAB:case CardId::PINPOINT:case CardId::SLICE:case CardId::STRIKE_SILENT:hit(damage);return true;
    case CardId::BLADE_OF_INK:silent_create_shivs(b,var(c,VarId::CARDS),false,true);return true;
    case CardId::BLADE_DANCE:case CardId::BLADE_SYMPHONY:
        // GetTeammatesOf includes the owner; a single-player combat has one.
        silent_create_shivs(b,var(c,VarId::CARDS));return true;
    case CardId::BLUR:block(b,c);power(PowerId::BLUR,var(c,VarId::BLUR));return true;
    case CardId::BOUNCING_FLASK:
        for(int i=0;i<var(c,VarId::REPEAT);++i){const int t=b.random_alive_monster();if(t>=0)poison(b,t,var(c,VarId::POISON_POWER));}return true;
    case CardId::BUBBLE_BUBBLE:if(alive(b,target)&&b.monster_power(target,PowerId::POISON)>0)poison(b,target,var(c,VarId::POISON_POWER));return true;
    case CardId::BULLET_TIME:
        for(int i=0;i<b.handCount;++i)if(card_def(b.hand[i].id).cost>=0)card_modify_cost(b.hand[i],0,true,2);
        power(PowerId::NO_DRAW,1);return true;
    case CardId::BURST:power(PowerId::BURST,var(c,VarId::SKILLS));return true;
    case CardId::CALCULATED_GAMBLE:discard_whole_hand(b,b.handCount);return true;
    case CardId::CLOAK_AND_DAGGER:block(b,c);silent_create_shivs(b,var(c,VarId::CARDS));return true;
    case CardId::CORROSIVE_WAVE:power(PowerId::CORROSIVE_WAVE,var(c,VarId::CORROSIVE_WAVE));return true;
    case CardId::CONCOCT:power(PowerId::CONCOCT,var(c,VarId::CONCOCT_POWER));return true;
    case CardId::DAGGER_SPRAY:all(damage,2);return true;
    case CardId::DAGGER_THROW:hit(damage);draw_then_discard(b,c,1,1);return true;
    case CardId::DASH:block(b,c);hit(damage);return true;
    case CardId::DEADLY_POISON:case CardId::SNAKEBITE:poison(b,target,var(c,VarId::POISON_POWER));return true;
    case CardId::DEFEND_SILENT:case CardId::DEFLECT:case CardId::UNTOUCHABLE:block(b,c);return true;
    case CardId::DODGE_AND_ROLL:{const int before=b.player.block;block(b,c);power(PowerId::BLOCK_NEXT_TURN,std::max(0,b.player.block-before));return true;}
    case CardId::ECHOING_SLASH:{
        // One AttackContext spans every repeat. Additive Vigor and Skittish
        // consequently apply to every strike, then expire once at the end.
        const int vigor=b.player_power(PowerId::VIGOR);
        if(vigor>0)b.add_player_power(PowerId::VIGOR,-vigor);
        bool firstSeen[MAX_MONSTERS]{},firstUnblocked[MAX_MONSTERS]{};
        int pending=1;
        while(pending>0&&b.outcome==Outcome::UNDECIDED&&b.alive_monster_count()>0){
            --pending;
            for(int i=0;i<b.monsterCount&&b.outcome==Outcome::UNDECIDED;++i)if(alive(b,i)){
                const auto result=b.damage_monster(i,b.calc_player_damage(damage+vigor,i,true,&c),true,true);
                if(!firstSeen[i])firstUnblocked[i]=result.unblocked>0;
                firstSeen[i]=true;if(result.wasKilled)++pending;
            }
        }
        for(int i=0;i<b.monsterCount;++i)b.trigger_skittish(i,firstUnblocked[i]);return true;
    }
    case CardId::ENVENOM:power(PowerId::ENVENOM,var(c,VarId::ENVENOM_POWER));return true;
    case CardId::ESCAPE_PLAN:
        b.activePlay.silent.stage=2;b.activePlay.silent.drawn=0;b.activePlay.silent.firstDrawnType=-1;
        b.draw_cards(1);return true;
    case CardId::EXPERTISE:
        b.activePlay.silent.stage=3;b.draw_cards(var(c,VarId::CARDS));return true;
    case CardId::EXPOSE:
        if(alive(b,target)){b.monsters[target].block=0;b.monsters[target].power[static_cast<int>(PowerId::ARTIFACT)]=0;b.apply_vulnerable(target,var(c,VarId::POWER));}return true;
    case CardId::FADE:power(PowerId::DEXTERITY,var(c,VarId::DEXTERITY_POWER));power(PowerId::FADE,var(c,VarId::DEXTERITY_POWER));return true;
    case CardId::FAN_OF_KNIVES:if(b.player_power(PowerId::FAN_OF_KNIVES)==0)power(PowerId::FAN_OF_KNIVES,1);silent_create_shivs(b,var(c,VarId::SHIVS));return true;
    case CardId::FINISHER:hit(damage,b.silent.attacksFinishedThisTurn);return true;
    case CardId::FLANKING:if(alive(b,target))b.add_monster_power(target,PowerId::FLANKING,2);return true;
    case CardId::FLECHETTES:{int n=0;for(int i=0;i<b.handCount;++i)n+=card_is_skill(b.hand[i]);hit(damage,n);return true;}
    case CardId::FLICK_FLACK:case CardId::GRAND_FINALE:all(damage);return true;
    case CardId::SIDESTEP:power(PowerId::ENERGY_NEXT_TURN,var(c,VarId::ENERGY));return true;
    case CardId::FOOTWORK:power(PowerId::DEXTERITY,var(c,VarId::DEXTERITY_POWER));return true;
    case CardId::HAND_TRICK:{
        block(b,c);b.start_choice(ChoiceOp::SILENT_SLY,ChoicePile::HAND,1,false,c,b.card_will_exhaust(c));
        int n=0;for(int i=0;i<b.pending.count;++i)if(card_is_skill(b.pending.cards[i])&&!card_has(b.pending.cards[i],CF_SLY))b.pending.cards[n++]=b.pending.cards[i];
        b.pending.count=n;
        if(n==1){if(Card *selected=b.find_in_hand(b.pending.cards[0].uid))selected->slyThisTurn=true;b.pending=PendingChoice();}
        else if(n==0)b.pending=PendingChoice();return true;
    }
    case CardId::HAZE:
        for(int i=0;i<b.monsterCount;++i)poison(b,i,var(c,VarId::POISON_POWER));
        for(int i=0;i<b.monsterCount;++i)if(alive(b,i))b.apply_weak(i,var(c,VarId::WEAK_POWER));return true;
    case CardId::HIDDEN_DAGGERS:
        b.activePlay.silent.stage=4;choose_discard(b,c,var(c,VarId::CARDS));
        return true;
    case CardId::INFINITE_BLADES:power(PowerId::INFINITE_BLADES,1);return true;
    case CardId::KNIFE_TRAP:{
        Card shivs[MAX_PILE];int n=0;
        for(int i=0;i<b.exhaustCount;++i)if(b.exhaust[i].id==CardId::SHIV){if(c.upgraded)card_apply_upgrade(b.exhaust[i]);shivs[n++]=b.exhaust[i];}
        b.auto_play_cards(shivs,n,target,false);return true;
    }
    case CardId::LEADING_STRIKE:hit(damage);silent_create_shivs(b,var(c,VarId::SHIVS));return true;
    case CardId::LEG_SWEEP:block(b,c);if(alive(b,target))b.apply_weak(target,var(c,VarId::WEAK_POWER));return true;
    case CardId::MALAISE:{const int n=b.xCost+(c.upgraded?1:0);if(alive(b,target)){b.add_monster_power(target,PowerId::STRENGTH,-n);b.apply_weak(target,n);}return true;}
    case CardId::MASTER_PLANNER:if(b.player_power(PowerId::MASTER_PLANNER)==0)power(PowerId::MASTER_PLANNER,1);return true;
    case CardId::MEMENTO_MORI:hit(var(c,VarId::CALCULATION_BASE)+var(c,VarId::EXTRA_DAMAGE)*b.silent.discardedThisTurn+c.bonusDamage);return true;
    case CardId::MIRAGE:{int n=0;for(int i=0;i<b.monsterCount;++i)if(alive(b,i))n+=b.monster_power(i,PowerId::POISON);b.gain_block(n,true);return true;}
    case CardId::MURDER:hit(var(c,VarId::CALCULATION_BASE)+var(c,VarId::EXTRA_DAMAGE)*b.silent.drawnThisCombat+c.bonusDamage);return true;
    case CardId::NEUTRALIZE:case CardId::SUCKER_PUNCH:case CardId::SUPPRESS:hit(damage);if(alive(b,target))b.apply_weak(target,var(c,VarId::WEAK_POWER));return true;
    case CardId::NIGHTMARE:
        if(b.handCount==1)silent_store_nightmare(b,b.hand[0]);
        else if(b.handCount>1)b.start_choice(ChoiceOp::SILENT_NIGHTMARE,ChoicePile::HAND,1,false,c,b.card_will_exhaust(c));return true;
    case CardId::NOXIOUS_FUMES:power(PowerId::NOXIOUS_FUMES,var(c,VarId::POISON_PER_TURN));return true;
    case CardId::OUTBREAK:
        for(int i=0;i<b.monsterCount;++i)poison(b,i,var(c,VarId::POISON_POWER));
        for(int i=0;i<b.monsterCount;++i)if(alive(b,i))silent_trigger_poison(b,i);return true;
    case CardId::PHANTOM_BLADES:{
        power(PowerId::PHANTOM_BLADES,var(c,VarId::PHANTOM_BLADES_POWER));
        Card *piles[]={b.hand,b.draw,b.discard,b.exhaust,b.playPile,b.returnNextTurn};
        const int counts[]={b.handCount,b.drawCount,b.discardCount,b.exhaustCount,b.playCount,b.returnNextTurnCount};
        for(int p=0;p<6;++p)for(int i=0;i<counts[p];++i)if(piles[p][i].id==CardId::SHIV)piles[p][i].retainThisCombat=true;return true;
    }
    case CardId::PIERCING_WAIL:
        for(int i=0;i<b.monsterCount;++i)if(alive(b,i)){
            // The outer debuff passes Artifact before BeforeApplied applies
            // negative Strength (StrengthPower itself is always a Buff).
            const int n=var(c,VarId::STRENGTH_LOSS),before=b.monster_power(i,PowerId::PIERCING_WAIL);
            b.add_monster_power(i,PowerId::PIERCING_WAIL,n);
            b.add_monster_power(i,PowerId::STRENGTH,-(b.monster_power(i,PowerId::PIERCING_WAIL)-before));
        }return true;
    case CardId::POISONED_STAB:hit(damage);poison(b,target,var(c,VarId::POISON_POWER));return true;
    case CardId::POUNCE:hit(damage);power(PowerId::FREE_SKILL,1);return true;
    case CardId::PRECISE_CUT:hit(var(c,VarId::CALCULATION_BASE)-var(c,VarId::EXTRA_DAMAGE)*b.handCount+c.bonusDamage);return true;
    case CardId::PREDATOR:hit(damage);power(PowerId::DRAW_CARDS_NEXT_TURN,2);return true;
    case CardId::PREPARED:draw_then_discard(b,c,var(c,VarId::CARDS),var(c,VarId::CARDS));return true;
    case CardId::REFLEX:b.draw_cards(var(c,VarId::CARDS));return true;
    case CardId::RICOCHET:b.attack_random_from_card(c,damage,var(c,VarId::REPEAT));return true;
    case CardId::SERPENT_FORM:power(PowerId::SERPENT_FORM,var(c,VarId::SERPENT_FORM_POWER));return true;
    case CardId::SHADOW_STEP:b.activePlay.silent.stage=5;discard_whole_hand(b,0);return true;
    case CardId::SHADOWMELD:power(PowerId::SHADOWMELD,var(c,VarId::POWER));return true;
    case CardId::SKEWER:hit(damage,b.xCost);return true;
    case CardId::SNEAKY:power(PowerId::SNEAKY,var(c,VarId::SNEAKY_POWER));return true;
    case CardId::SPEEDSTER:power(PowerId::SPEEDSTER,var(c,VarId::SPEEDSTER_POWER));return true;
    case CardId::STORM_OF_STEEL:
        b.activePlay.silent.stage=6;b.activePlay.silent.amount=b.handCount;
        discard_whole_hand(b,0);return true;
    case CardId::STRANGLE:hit(damage);if(alive(b,target))b.add_monster_power(target,PowerId::STRANGLE,var(c,VarId::STRANGLE_POWER));return true;
    case CardId::SURVIVOR:block(b,c);choose_discard(b,c,1);return true;
    case CardId::TACTICIAN:b.player.energy+=var(c,VarId::ENERGY);return true;
    case CardId::THE_HUNT:{const bool fatal=b.can_trigger_fatal(target);if(hit(damage)&&fatal){++b.silent.huntRewards;power(PowerId::THE_HUNT,1);}return true;}
    case CardId::TOOLS_OF_THE_TRADE:power(PowerId::TOOLS_OF_THE_TRADE,1);return true;
    case CardId::TRACKING:power(PowerId::TRACKING,50);return true;
    case CardId::UP_MY_SLEEVE:silent_create_shivs(b,var(c,VarId::CARDS));card_modify_cost(c,-1,false,0);return true;
    case CardId::WELL_LAID_PLANS:if(b.player_power(PowerId::WELL_LAID_PLANS)==0)power(PowerId::WELL_LAID_PLANS,1);return true;
    case CardId::WRAITH_FORM:power(PowerId::INTANGIBLE,var(c,VarId::INTANGIBLE_POWER));power(PowerId::WRAITH_FORM,var(c,VarId::WRAITH_FORM_POWER));return true;
    case CardId::SHIV:
        if(b.player_power(PowerId::FAN_OF_KNIVES)>0)all(damage);else hit(damage);
        if(c.enchantment==EnchantmentId::INKY){if(b.player_power(PowerId::FAN_OF_KNIVES)>0){for(int i=0;i<b.monsterCount;++i)if(alive(b,i))b.apply_weak(i,1);}else if(alive(b,target))b.apply_weak(target,1);}return true;
    default:return false;
    }
}

bool silent_resume_effect(BattleContext &b) {
    if(!b.activePlay.active)return true;
    if(b.pending.op!=ChoiceOp::NONE||b.pendingDrawRemainder>0)return false;
    auto &s=b.activePlay.silent;Card &c=b.activePlay.card;
    const int stage=s.stage;s.stage=0;
    switch(stage) {
    case 1:choose_discard(b,c,s.amount);break;
    case 2:if(s.firstDrawnType==static_cast<int>(CardType::SKILL))block(b,c);break;
    case 3:break; // Expertise marks the exact drawn entities in the draw hook.
    case 4:silent_create_shivs(b,var(c,VarId::SHIVS),c.upgraded);break;
    case 5:b.add_player_power(PowerId::SHADOW_STEP,1);break;
    case 6:silent_create_shivs(b,s.amount,c.upgraded);break;
    default:break;
    }
    return b.pending.op==ChoiceOp::NONE;
}
}
